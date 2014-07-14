'''
Copyright (C) 2013 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Patrick Moore

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

####class definitions####

import bpy
import math
import time
import copy
from mathutils import Vector, Quaternion
from mathutils.geometry import intersect_point_line, intersect_line_plane
import contour_utilities, general_utilities
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d
import bmesh
import blf, bgl
import itertools
from polystrips_utilities import *
from polystrips_draw import *
from general_utilities import iter_running_sum, dprint, get_object_length_scale, profiler

#Make the addon name and location accessible
AL = general_utilities.AddonLocator()



class GVert:
    def __init__(self, obj, length_scale, position, radius, normal, tangent_x, tangent_y):
        # store info
        self.obj       = obj
        self.length_scale = length_scale
        
        self.position  = position
        self.radius    = radius
        self.normal    = normal
        self.tangent_x = tangent_x
        self.tangent_y = tangent_y
        
        self.snap_pos  = position
        self.snap_norm = normal
        self.snap_tanx = tangent_x
        self.snap_tany = tangent_y
        
        self.gedge0 = None
        self.gedge1 = None
        self.gedge2 = None
        self.gedge3 = None
        self.gedge_inner = None
        
        self.doing_update = False
        
        self.visible = True
        
        self.update()
    
    def clone(self):
        gv = GVert(self.obj, self.length_scale, Vector(self.position), self.radius, Vector(self.normal), Vector(self.tangent_x), Vector(self.tangent_y))
        gv.snap_pos = Vector(self.snap_pos)
        gv.snap_norm = Vector(self.snap_norm)
        gv.snap_tanx = Vector(self.snap_tanx)
        gv.snap_tany = Vector(self.snap_tany)
        return gv
    
    def has_0(self): return not (self.gedge0 is None)
    def has_1(self): return not (self.gedge1 is None)
    def has_2(self): return not (self.gedge2 is None)
    def has_3(self): return not (self.gedge3 is None)
    
    def count_gedges(self):   return len(self.get_gedges_notnone())
    
    def is_unconnected(self): return not (self.has_0() or self.has_1() or self.has_2() or self.has_3())
    def is_endpoint(self):    return self.has_0() and not (self.has_1() or self.has_2() or self.has_3())
    def is_endtoend(self):    return self.has_0() and self.has_2() and not (self.has_1() or self.has_3())
    def is_ljunction(self):   return self.has_0() and self.has_1() and not (self.has_2() or self.has_3())
    def is_tjunction(self):   return self.has_0() and self.has_1() and self.has_3() and not self.has_2()
    def is_cross(self):       return self.has_0() and self.has_1() and self.has_2() and self.has_3()
    
    def get_gedges(self): return [self.gedge0,self.gedge1,self.gedge2,self.gedge3]
    def _set_gedges(self, ge0, ge1, ge2, ge3):
        self.gedge0,self.gedge1,self.gedge2,self.gedge3 = ge0,ge1,ge2,ge3
    def count_gedges(self):
        return sum([self.has_0(),self.has_1(),self.has_2(),self.has_3()])
    def get_gedges_notnone(self): return [ge for ge in self.get_gedges() if ge]
    
    def get_inner_gverts(self): return [ge.get_inner_gvert_at(self) for ge in self.get_gedges_notnone()]
    
    def disconnect_gedge(self, gedge):
        pr = profiler.start()
        if self.gedge_inner == gedge:
            self.gedge_inner = None
        else:
            l_gedges = self.get_gedges_notnone()
            assert gedge in l_gedges
            l_gedges = [ge for ge in l_gedges if ge != gedge]
            l = len(l_gedges)
            l_gedges = [l_gedges[i] if i < l else None for i in range(4)]
            self._set_gedges(*l_gedges)
            self.update_gedges()
        pr.done()
    
    def connect_gedge_inner(self, gedge):
        assert self.is_unconnected()
        assert not self.gedge_inner
        self.gedge_inner = gedge
    
    def update_gedges(self):
        if self.is_unconnected(): return
        
        pr = profiler.start()
        
        norm = self.snap_norm
        
        l_gedges = self.get_gedges_notnone()
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        if any(v.length == 0 for v in l_vecs): print (l_vecs)
        #l_vecs = [v if v.length else Vector((1,0,0)) for v in l_vecs]
        l_gedges = sort_objects_by_angles(norm, l_gedges, l_vecs)
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        if any(v.length == 0 for v in l_vecs): print(l_vecs)
        #l_vecs = [v if v.length else Vector((1,0,0)) for v in l_vecs]
        l_angles = [vector_angle_between(v0,v1,norm) for v0,v1 in zip(l_vecs,l_vecs[1:]+[l_vecs[0]])]
        
        connect_count = len(l_gedges)
        
        if connect_count == 1:
            self._set_gedges(l_gedges[0],None,None,None)
            assert self.is_endpoint()
        elif connect_count == 2:
            d0 = abs(l_angles[0]-math.pi)
            d1 = abs(l_angles[1]-math.pi)
            if d0 < math.pi*0.2 and d1 < math.pi*0.2:
                self._set_gedges(l_gedges[0],None,l_gedges[1],None)
                assert self.is_endtoend()
            else:
                if l_angles[0] < l_angles[1]:
                    self._set_gedges(l_gedges[0],l_gedges[1],None,None)
                else:
                    self._set_gedges(l_gedges[1],l_gedges[0],None,None)
                assert self.is_ljunction()
        elif connect_count == 3:
            if l_angles[0] >= l_angles[1] and l_angles[0] >= l_angles[2]:
                self._set_gedges(l_gedges[2],l_gedges[0],None,l_gedges[1])
            elif l_angles[1] >= l_angles[0] and l_angles[1] >=  l_angles[2]:
                self._set_gedges(l_gedges[0],l_gedges[1],None,l_gedges[2])
            else:
                self._set_gedges(l_gedges[1],l_gedges[2],None,l_gedges[0])
            assert self.is_tjunction()
        elif connect_count == 4:
            self._set_gedges(*l_gedges)
            assert self.is_cross()
        else:
            assert False
        
        self.update()
        
        pr.done()
    
    
    def connect_gedge(self, gedge):
        pr = profiler.start()
        if not self.gedge0: self.gedge0 = gedge
        elif not self.gedge1: self.gedge1 = gedge
        elif not self.gedge2: self.gedge2 = gedge
        elif not self.gedge3: self.gedge3 = gedge
        else: assert False
        self.update_gedges()
        pr.done()
    
    def snap_corners(self):
        pr = profiler.start()
        
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        self.corner0 = mx * self.obj.closest_point_on_mesh(imx*self.corner0)[0]
        self.corner1 = mx * self.obj.closest_point_on_mesh(imx*self.corner1)[0]
        self.corner2 = mx * self.obj.closest_point_on_mesh(imx*self.corner2)[0]
        self.corner3 = mx * self.obj.closest_point_on_mesh(imx*self.corner3)[0]
        
        pr.done()
    
    def update(self, do_edges=True):
        if self.doing_update: return
        
        pr = profiler.start()
        
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        l,n,i = self.obj.closest_point_on_mesh(imx*self.position)
        self.snap_pos  = mx * l
        self.snap_norm = (mx3x3 * n).normalized()
        self.snap_tanx = self.tangent_x.normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        
        if not self.is_unconnected() or True:
            self.position = self.snap_pos
        # NOTE! DO NOT UPDATE NORMAL, TANGENT_X, AND TANGENT_Y
        
        if do_edges:
            self.doing_update = True
            for gedge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3]:
                if gedge: gedge.update()
            if self.gedge_inner: self.gedge_inner.update()
            self.doing_update = False
        
        self.snap_tanx = (Vector((0.2,0.1,0.5)) if not self.gedge0 else self.gedge0.get_derivative_at(self)).normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        
        # NOTE! DO NOT UPDATE NORMAL, TANGENT_X, AND TANGENT_Y
        
        
        #         ge2         #
        #          |          #
        #      2 --+-- 3      #
        #      |       |      #
        # ge1--+   +Y  +--ge3 #
        #      |   X   |      #
        #      1---+---0      #
        #          |          #
        #         ge0         #
        
        def get_corner(self,dmx,dmy, igv0,r0, igv1,r1):
            if not igv0 and not igv1:
                return self.snap_pos + self.snap_tanx*self.radius*dmx + self.snap_tany*self.radius*dmy
            if igv0 and not igv1:
                return igv0.position + igv0.tangent_y*r0
            if igv1 and not igv0:
                return igv1.position - igv1.tangent_y*r1
            return (igv0.position+igv0.tangent_y*r0 + igv1.position-igv1.tangent_y*r1)/2
        
        igv0 = None if (not self.gedge0 or self.gedge0.force_count) else self.gedge0.get_igvert_at(self)
        igv1 = None if (not self.gedge1 or self.gedge0.force_count) else self.gedge1.get_igvert_at(self)
        igv2 = None if (not self.gedge2 or self.gedge0.force_count) else self.gedge2.get_igvert_at(self)
        igv3 = None if (not self.gedge3 or self.gedge0.force_count) else self.gedge3.get_igvert_at(self)
        
        r0 = 0 if not igv0 else (igv0.radius*(1 if igv0.tangent_x.dot(self.snap_tanx)>0 else -1))
        r1 = 0 if not igv1 else (igv1.radius*(1 if igv1.tangent_x.dot(self.snap_tany)<0 else -1))
        r2 = 0 if not igv2 else (igv2.radius*(1 if igv2.tangent_x.dot(self.snap_tanx)<0 else -1))
        r3 = 0 if not igv3 else (igv3.radius*(1 if igv3.tangent_x.dot(self.snap_tany)>0 else -1))
        
        self.corner0 = get_corner(self, 1, 1, igv0,r0, igv3,r3)
        self.corner1 = get_corner(self, 1,-1, igv1,r1, igv0,r0)
        self.corner2 = get_corner(self,-1,-1, igv2,r2, igv1,r1)
        self.corner3 = get_corner(self,-1, 1, igv3,r3, igv2,r2)
        
        self.snap_corners()
        
        pr.done()
    
    def update_visibility(self, r3d, update_gedges=False):
        self.visible = contour_utilities.ray_cast_visible([self.snap_pos], self.obj, r3d)[0]
        if not update_gedges: return
        for ge in self.get_gedges_notnone():
            ge.update_visibility(r3d)
    
    def is_visible(self): return self.visible
    
    def get_corners(self):
        return (self.corner0, self.corner1, self.corner2, self.corner3)
    
    def is_picked(self, pt):
        if not self.visible: return False
        c0 = self.corner0 - pt
        c1 = self.corner1 - pt
        c2 = self.corner2 - pt
        c3 = self.corner3 - pt
        n = self.snap_norm
        return c1.cross(c0).dot(n)>0 and c2.cross(c1).dot(n)>0 and c3.cross(c2).dot(n)>0 and c0.cross(c3).dot(n)>0
    
    def get_corners_of(self, gedge):
        if gedge == self.gedge0: return (self.corner0, self.corner1)
        if gedge == self.gedge1: return (self.corner1, self.corner2)
        if gedge == self.gedge2: return (self.corner2, self.corner3)
        if gedge == self.gedge3: return (self.corner3, self.corner0)
        assert False, "GEdge is not connected"
    
    def get_cornerinds_of(self, gedge):
        if gedge == self.gedge0: return (0,1)
        if gedge == self.gedge1: return (1,2)
        if gedge == self.gedge2: return (2,3)
        if gedge == self.gedge3: return (3,0)
        assert False, "GEdge is not connected"
    
    def toggle_corner(self):
        if (self.is_endtoend() or self.is_ljunction()):
            if self.is_ljunction():
                self._set_gedges(self.gedge0,None,self.gedge1,None)
                assert self.is_endtoend()
            else:
                self._set_gedges(self.gedge2,self.gedge0,None,None)
                assert self.is_ljunction()
            self.update()
        elif self.is_tjunction():
            self._set_gedges(self.gedge3,self.gedge0,None,self.gedge1)
            assert self.is_tjunction()
            self.update()
        else:
            print('Cannot toggle corner on GVert with %i connections' % self.count_gedges())
    
    def smooth(self, v=0.1):
        pr = profiler.start()
        
        der0 = self.gedge0.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge0 else Vector()
        der1 = self.gedge1.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge1 else Vector()
        der2 = self.gedge2.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge2 else Vector()
        der3 = self.gedge3.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge3 else Vector()
        
        if self.is_endtoend():
            angle = (math.pi - der0.angle(der2))*v
            cross = der0.cross(der2).normalized()
            
            quat0 = Quaternion(cross, -angle)
            quat1 = Quaternion(cross, angle)
            
            self.gedge0.rotate_gverts_at(self, quat0)
            self.gedge2.rotate_gverts_at(self, quat1)
            self.update()
        
        if self.is_ljunction():
            angle = (math.pi/2 - der0.angle(der1))*v
            cross = der0.cross(der1).normalized()
            
            quat0 = Quaternion(cross, -angle)
            quat1 = Quaternion(cross, angle)
            
            self.gedge0.rotate_gverts_at(self, quat0)
            self.gedge1.rotate_gverts_at(self, quat1)
            self.update()
        
        if self.is_tjunction():
            angle = (math.pi/2 - der3.angle(der0))*v
            cross = der3.cross(der0).normalized()
            self.gedge3.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge0.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            angle = (math.pi/2 - der0.angle(der1))*v
            cross = der0.cross(der1).normalized()
            self.gedge0.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge1.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            self.update()
        
        if self.is_cross():
            cross = self.snap_norm.normalized()
            
            ang30 = (math.pi/2 - vector_angle_between(der3,der0,cross))*v
            self.gedge3.rotate_gverts_at(self, Quaternion(cross,  ang30))
            self.gedge0.rotate_gverts_at(self, Quaternion(cross, -ang30))
            
            ang01 = (math.pi/2 - vector_angle_between(der0,der1,cross))*v
            self.gedge0.rotate_gverts_at(self, Quaternion(cross,  ang01))
            self.gedge1.rotate_gverts_at(self, Quaternion(cross, -ang01))
            
            ang12 = (math.pi/2 - vector_angle_between(der1,der2,cross))*v
            self.gedge1.rotate_gverts_at(self, Quaternion(cross,  ang12))
            self.gedge2.rotate_gverts_at(self, Quaternion(cross, -ang12))
            
            ang23 = (math.pi/2 - vector_angle_between(der2,der3,cross))*v
            self.gedge2.rotate_gverts_at(self, Quaternion(cross,  ang23))
            self.gedge3.rotate_gverts_at(self, Quaternion(cross, -ang23))
            
            self.update()
        
        pr.done()


class GEdge:
    '''
    Graph Edge (GEdge) stores end points and "way points" (cubic bezier)
    '''
    def __init__(self, obj, length_scale, gvert0, gvert1, gvert2, gvert3):
        # store end gvertices
        self.obj = obj
        self.length_scale = length_scale
        self.gvert0 = gvert0
        self.gvert1 = gvert1
        self.gvert2 = gvert2
        self.gvert3 = gvert3
        
        self.force_count = False
        self.n_quads = None
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
        
        gvert0.connect_gedge(self)
        gvert1.connect_gedge_inner(self)
        gvert2.connect_gedge_inner(self)
        gvert3.connect_gedge(self)
        
    
    def rotate_gverts_at(self, gv, quat):
        if gv == self.gvert0:
            v = self.gvert1.position - self.gvert0.position
            v = quat * v
            self.gvert1.position = self.gvert0.position + v
            self.gvert1.update()
        elif gv == self.gvert3:
            v = self.gvert2.position - self.gvert3.position
            v = quat * v
            self.gvert2.position = self.gvert3.position + v
            self.gvert2.update()
        else:
            assert False
    
    def disconnect(self):
        self.gvert0.disconnect_gedge(self)
        self.gvert1.disconnect_gedge(self)
        self.gvert2.disconnect_gedge(self)
        self.gvert3.disconnect_gedge(self)
    
    def update_visibility(self, rv3d):
        lp = [gv.snap_pos for gv in self.cache_igverts]
        lv = contour_utilities.ray_cast_visible(lp, self.obj, rv3d)
        for gv,v in zip(self.cache_igverts,lv): gv.visible = v
    
    def gverts(self):
        return [self.gvert0,self.gvert1,self.gvert2,self.gvert3]
    
    def get_derivative_at(self, gv, ignore_igverts=False):
        if not ignore_igverts and len(self.cache_igverts) < 3:
            if self.gvert0 == gv:
                return self.gvert3.position - self.gvert0.position
            if self.gvert3 == gv:
                return self.gvert0.position - self.gvert3.position
            assert False, "gv is not an endpoint"
        p0,p1,p2,p3 = self.get_positions()
        if self.gvert0 == gv:
            return cubic_bezier_derivative(p0,p1,p2,p3,0)
        if self.gvert3 == gv:
            return cubic_bezier_derivative(p3,p2,p1,p0,0)
        assert False, "gv is not an endpoint"
    
    def get_inner_gvert_at(self, gv):
        if self.gvert0 == gv: return self.gvert1
        if self.gvert3 == gv: return self.gvert2
        assert False, "gv is not an endpoint"
    
    def get_inner_gverts(self):
        return [self.gvert1, self.gvert2]
    
    def get_vector_from(self, gv):
        is_0 = (self.gvert0==gv)
        gv0 = self.gvert0 if is_0 else self.gvert3
        gv1 = self.gvert2 if is_0 else self.gvert1
        return gv1.position - gv0.position
    
    def get_igvert_at(self, gv):
        if self.gvert0 == gv:
            if len(self.cache_igverts):
                return self.cache_igverts[1]
            return None #self.gvert0
        if self.gvert3 == gv:
            if len(self.cache_igverts):
                return self.cache_igverts[-2]
            return None #self.gvert3
        assert False, "gv is not an endpoint"
    
    def get_positions(self):
        return (
            self.gvert0.position,
            self.gvert1.position,
            self.gvert2.position,
            self.gvert3.position
            )
    def get_normals(self):
        return (
            self.gvert0.normal,
            self.gvert1.normal,
            self.gvert2.normal,
            self.gvert3.normal
            )
    def get_radii(self):
        return (
            self.gvert0.radius,
            self.gvert1.radius,
            self.gvert2.radius,
            self.gvert3.radius
            )
    
    def get_length(self):
        p0,p1,p2,p3 = self.get_positions()
        mx = self.obj.matrix_world
        imx = mx.inverted()
        p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/64.0) for t in range(65)]
        p3d = [mx*self.obj.closest_point_on_mesh(imx * p)[0] for p in p3d]
        return sum((p1-p0).length for p0,p1 in zip(p3d[:-1],p3d[1:]))
        #return cubic_bezier_length(p0,p1,p2,p3)
    
    def get_closest_point(self, pt):
        p0,p1,p2,p3 = self.get_positions()
        if len(self.cache_igverts) < 3:
            return cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,pt)
        min_t,min_d = -1,-1
        i,l = 0,len(self.cache_igverts)
        for gv0,gv1 in zip(self.cache_igverts[:-1],self.cache_igverts[1:]):
            p0,p1 = gv0.position,gv1.position
            t,d = contour_utilities.closest_t_and_distance_point_to_line_segment(pt, p0,p1)
            if min_t < 0 or d < min_d: min_t,min_d = (i+t)/l,d
            i += 1
        return min_t,min_d
        
    
    def update(self, debug=False):
        '''
        recomputes interval gverts along gedge
        note: considering only the radii of end points
        note: approx => not snapped to surface
        '''
        
        p0,p1,p2,p3 = self.get_positions()
        r0,r1,r2,r3 = self.get_radii()
        n0,n1,n2,n3 = self.get_normals()
        
        # get bezier length
        l = self.get_length()
        
        # find "optimal" count for subdividing spline
        cmin,cmax = int(math.floor(l/max(r0,r3))),int(math.floor(l/min(r0,r3)))
        
        if self.force_count and self.n_quads:
            c = 2 * (self.n_quads - 2)
            
            #average width of GEdges internal quads
            davg = (l - r0 - r3)/c
            # compute difference for smoothly interpolating radii perpendicular to GEdge
            s = (r3-r0) / float(c-1) 
            #print('s is %f' % s)
            # compute how much space is left over (to be added to each interval)
            #tot = r0*(c+1) + s*(c+1)*c/2
            
            
            #o = l -r0 - tot
            #oc = o / (c + 1)
            #print('leftover %f' % oc)
            
            # compute interval lengths, ts, blend weights
            l_widths = [0] + [r0] + [davg for i in range(1,c)] + [r3]
            l_ts = [p/l for w,p in iter_running_sum(l_widths)]
            l_weights = [cubic_bezier_weights(t) for t in l_ts]
            
            
        else:
            
            c = 0
            for ctest in range(max(4,cmin-2),cmax+2):
                s = (r3-r0) / (ctest-1)
                tot = r0*(ctest+1) + s*(ctest+1)*ctest/2
                if tot > l:
                    break
                if ctest % 2 == 1:
                    c = ctest
            if c <= 1:
                self.cache_igverts = []
                return
        
            # compute difference for smoothly interpolating radii
            s = (r3-r0) / float(c-1)
            
            # compute how much space is left over (to be added to each interval)
            tot = r0*(c+1) + s*(c+1)*c/2
            o = l - tot
            oc = o / (c+1)
            
            # compute interval lengths, ts, blend weights
            l_widths = [0] + [r0+oc+i*s for i in range(c+1)]
            l_ts = [p/l for w,p in iter_running_sum(l_widths)]
            l_weights = [cubic_bezier_weights(t) for t in l_ts]
        
        # compute interval pos, rad, norm, tangent x, tangent y
        l_pos   = [cubic_bezier_blend_weights(p0,p1,p2,p3,weights) for weights in l_weights]
        l_radii = [r0 + i*s for i in range(c+2)]
        l_norms = [cubic_bezier_blend_weights(n0,n1,n2,n3,weights).normalized() for weights in l_weights]
        l_tanx  = [cubic_bezier_derivative(p0,p1,p2,p3,t).normalized() for t in l_ts]
        l_tany  = [t.cross(n).normalized() for t,n in zip(l_tanx,l_norms)]
        
        # create igverts!
        self.cache_igverts = [GVert(self.obj,self.length_scale,p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
        
        '''
        snaps already computed igverts to surface of object ob
        '''
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        for igv in self.cache_igverts:
            l,n,i = self.obj.closest_point_on_mesh(imx * igv.position)
            igv.position = mx * l
            igv.normal = (mx3x3 * n).normalized()
            igv.tangent_y = igv.normal.cross(igv.tangent_x).normalized()
        
        self.gvert0.update(do_edges=False)
        self.gvert1.update(do_edges=False)
        self.gvert2.update(do_edges=False)
        self.gvert3.update(do_edges=False)
    
    def is_picked(self, pt):
        for p0,p1,p2,p3 in self.iter_segments(only_visible=True):
            
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            if c1.cross(c0).dot(n)>0 and c2.cross(c1).dot(n)>0 and c3.cross(c2).dot(n)>0 and c0.cross(c3).dot(n)>0:
                return True
        return False
    
    def iter_segments(self, only_visible=False):
        l = len(self.cache_igverts)
        if l == 0:
            cur0,cur1 = self.gvert0.get_corners_of(self)
            cur2,cur3 = self.gvert3.get_corners_of(self)
            if not only_visible or (self.gvert0.is_visible() and self.gvert3.is_visible()):
                yield (cur0,cur1,cur2,cur3)
            return
        
        prev0,prev1 = None,None
        for i,gvert in enumerate(self.cache_igverts):
            if i%2 == 0: continue
            
            if i == 1:
                gv0 = self.gvert0
                cur0,cur1 = gv0.get_corners_of(self)
            elif i == l-2:
                gv3 = self.gvert3
                cur1,cur0 = gv3.get_corners_of(self)
            else:
                cur0 = gvert.position+gvert.tangent_y*gvert.radius
                cur1 = gvert.position-gvert.tangent_y*gvert.radius
            
            if prev0 and prev1:
                if not only_visible or gvert.is_visible():
                    yield (prev0,cur0,cur1,prev1)
            prev0,prev1 = cur0,cur1


class PolyStrips(object):
    def __init__(self, context, obj):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        self.obj = obj
        self.length_scale = get_object_length_scale(self.obj)
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        
    
    def disconnect_gedge(self, gedge):
        assert gedge in self.gedges
        gedge.disconnect()
        self.gedges = [ge for ge in self.gedges if ge != gedge]
    
    def disconnect_gvert(self, gvert):
        assert gvert in self.gverts
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
    
    def remove_unconnected_gverts(self):
        egvs = set(gv for gedge in self.gedges for gv in gedge.gverts())
        gvs = set(gv for gv in self.gverts if gv.is_unconnected() and gv not in egvs)
        self.gverts = [gv for gv in self.gverts if gv not in gvs]
    
    def create_gvert(self, co, radius=0.005):
        #if type(co) is not Vector: co = Vector(co)
        p0  = co
        r0  = radius
        n0  = Vector((0,0,1))
        tx0 = Vector((1,0,0))
        ty0 = Vector((0,1,0))
        gv = GVert(self.obj,self.length_scale,p0,r0,n0,tx0,ty0)
        self.gverts += [gv]
        return gv
    
    def create_gedge(self, gv0, gv1, gv2, gv3):
        ge = GEdge(self.obj, self.length_scale, gv0, gv1, gv2, gv3)
        ge.update()
        self.gedges += [ge]
        return ge
    
    def closest_gedge_to_point(self, p):
        min_i,min_ge,min_t,min_d = -1,None,-1,0
        for i,gedge in enumerate(self.gedges):
            p0,p1,p2,p3 = gedge.get_positions()
            t,d = cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,p)
            if min_i==-1 or d < min_d:
                min_i,min_ge,min_t,min_d = i,gedge,t,d
        return (min_i,min_ge, min_t, min_d)
    
    def update_visibility(self, r3d):
        for gv in self.gverts:
            gv.update_visibility(r3d)
        for ge in self.gedges:
            ge.update_visibility(r3d)
    
    def split_gedge_at_t(self, gedge, t):
        p0,p1,p2,p3 = gedge.get_positions()
        r0,r1,r2,r3 = gedge.get_radii()
        cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3, t, self.length_scale)
        rm = cubic_bezier_blend_t(r0,r1,r2,r3, t)
        
        gv_split = self.create_gvert(cb0[3], radius=rm)
        
        gv0_0 = gedge.gvert0
        gv0_1 = self.create_gvert(cb0[1], radius=rm)
        gv0_2 = self.create_gvert(cb0[2], radius=rm)
        gv0_3 = gv_split
        
        gv1_0 = gv_split
        gv1_1 = self.create_gvert(cb1[1], radius=rm)
        gv1_2 = self.create_gvert(cb1[2], radius=rm)
        gv1_3 = gedge.gvert3
        
        self.disconnect_gedge(gedge)
        ge0 = self.create_gedge(gv0_0,gv0_1,gv0_2,gv0_3)
        ge1 = self.create_gedge(gv1_0,gv1_1,gv1_2,gv1_3)
        
        ge0.gvert0.update()
        ge1.gvert3.update()
        gv_split.update()
        gv_split.update_gedges()
        
        return (ge0,ge1)
    
    def insert_gedge_from_stroke(self, stroke, sgv0=None, sgv3=None, depth=0, sgedges=None):
        '''
        stroke: list of tuples (3d location, pressure)
        '''
        
        assert depth < 10
        if not sgedges: sgedges = set()
        
        # too few samples?
        if len(stroke) <= 1:
            dprint('Too few samples in stroke (subsample??)')
            #subsampling function in contour_utils.space_evenly_on_path
            return
        
        r0,r3 = stroke[0][1],stroke[-1][1]
        
        threshold_tooshort     = (r0+r3)/2
        threshold_junctiondist = (r0+r3)/2 * 2
        threshold_splitdist    = (r0+r3)/2 / 2
        
        tot_length = sum((s0[0]-s1[0]).length for s0,s1 in zip(stroke[:-1],stroke[1:]))
        dprint('stroke len: %f' % tot_length)
        if tot_length < threshold_tooshort and not (sgv0 and sgv3):
            dprint('Stroke too short (%f)' % tot_length)
            return
        
        if sgv0 and sgv0==sgv3:
            dprint('Stroke uses same endpoints?')
            return
        
        # TODO: self intersection tests!
        # check for self-intersections
        #for i0,info0 in enumerate(stroke):
        #    pt0,pr0 = info0
        #    for i1,info1 in enumerate(stroke):
        #        if i1 <= i0: continue
        #        pt1,pr1 = info1
        
        
        
        # check for junctions
        for i_gedge,gedge in enumerate(self.gedges):
            #if gedge in sgedges: continue
            
            p0,p1,p2,p3 = gedge.get_positions()
            
            min_i0,min_t,min_d = -1,-1,0
            # find closest distance between stroke and gedge
            for i0,info0 in enumerate(stroke):
                if sgv0 and i0 <= 6: continue
                if sgv3 and i0 >= len(stroke)-7: continue
                
                pt0,pr0 = info0
                split_t,split_d = gedge.get_closest_point(pt0)
                #(split_t,split_d) = cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,pt0)
                if min_i0 == -1 or split_d <= min_d: min_i0,min_t,min_d = i0,split_t,split_d
            if min_i0 == -1 or min_d > max([threshold_junctiondist,threshold_splitdist]): continue
            
            if min_i0 <= 6: min_i0 = 0 if not sgv0 else 7
            if min_i0 >= len(stroke)-7: min_i0 = len(stroke)-1 if not sgv3 else len(stroke)-8
            
            split_bpt = cubic_bezier_blend_t(p0,p1,p2,p3,min_t)
            
            closeto_p0 = ((split_bpt-p0).length <= threshold_junctiondist) and gedge.gvert0.count_gedges()<4
            closeto_p3 = ((split_bpt-p3).length <= threshold_junctiondist) and gedge.gvert3.count_gedges()<4
            
            if closeto_p0 and gedge.gvert0.count_gedges() < 4:
                sgedges = set(sgedges) | {gedge}
                if min_i0 == 0:
                    dprint('Joining gedge %i at p0; Joining stroke at 0' % (i_gedge))
                    self.insert_gedge_from_stroke(stroke, sgv0=gedge.gvert0, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
                elif min_i0 == len(stroke)-1:
                    dprint('Joining gedge %i at p0; Joining stroke at %i' % (i_gedge,len(stroke)-1))
                    self.insert_gedge_from_stroke(stroke, sgv0=sgv0, sgv3=gedge.gvert0, depth=depth+1, sgedges=sgedges)
                else:
                    dprint('Joining gedge %i at p0; Splitting stroke at 0-%i-%i' % (i_gedge,min_i0,len(stroke)-1))
                    self.insert_gedge_from_stroke(stroke[:min_i0], sgv0=sgv0, sgv3=gedge.gvert0, depth=depth+1, sgedges=sgedges)
                    self.insert_gedge_from_stroke(stroke[min_i0:], sgv0=gedge.gvert0, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
                return
            
            if closeto_p3 and gedge.gvert3.count_gedges() < 4:
                sgedges = set(sgedges) | {gedge}
                if min_i0 == 0:
                    dprint('Joining gedge %i at p3; Joining stroke at 0' % (i_gedge,))
                    self.insert_gedge_from_stroke(stroke, sgv0=gedge.gvert3, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
                elif min_i0 == len(stroke)-1:
                    dprint('Joining gedge %i at p3; Joining stroke at %i' % (i_gedge,len(stroke)-1))
                    self.insert_gedge_from_stroke(stroke, sgv0=sgv0, sgv3=gedge.gvert3, depth=depth+1, sgedges=sgedges)
                else:
                    dprint('Joining gedge %i at p3; Splitting stroke at 0-%i-%i' % (i_gedge,min_i0,len(stroke)-1))
                    self.insert_gedge_from_stroke(stroke[:min_i0], sgv0=sgv0, sgv3=gedge.gvert3, depth=depth+1, sgedges=sgedges)
                    self.insert_gedge_from_stroke(stroke[min_i0:], sgv0=gedge.gvert3, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
                return
            
            if min_d > threshold_splitdist: continue
            
            pt0,pr0 = stroke[min_i0]
            cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3,min_t, self.length_scale)
            
            rm = (r0+r3)/2
            
            gv_split = self.create_gvert(cb0[3], radius=rm)
            
            gv0_0 = gedge.gvert0
            gv0_1 = self.create_gvert(cb0[1], radius=rm)
            gv0_2 = self.create_gvert(cb0[2], radius=rm)
            gv0_3 = gv_split
            
            gv1_0 = gv_split
            gv1_1 = self.create_gvert(cb1[1], radius=rm)
            gv1_2 = self.create_gvert(cb1[2], radius=rm)
            gv1_3 = gedge.gvert3
            
            self.disconnect_gedge(gedge)
            ge0 = self.create_gedge(gv0_0,gv0_1,gv0_2,gv0_3)
            ge1 = self.create_gedge(gv1_0,gv1_1,gv1_2,gv1_3)
            
            gv0_0.update()
            gv0_0.update_gedges()
            gv_split.update()
            gv_split.update_gedges()
            gv1_3.update()
            gv1_3.update_gedges()
            
            # debugging printout
            if (ge0.gvert1.position-ge0.gvert0.position).length == 0: dprint('ge0.der0 = 0')
            if (ge0.gvert2.position-ge0.gvert3.position).length == 0: dprint('ge0.der3 = 0')
            if (ge1.gvert1.position-ge1.gvert0.position).length == 0: dprint('ge1.der0 = 0')
            if (ge1.gvert2.position-ge1.gvert3.position).length == 0: dprint('ge1.der3 = 0')
            
            sgedges = set(sgedges) | {ge0,ge1}
            if min_i0 == 0:
                dprint('Splitting gedge %i at %f; Joining stroke at 0' % (i_gedge,min_t))
                self.insert_gedge_from_stroke(stroke, sgv0=gv_split, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
            elif min_i0 == len(stroke)-1:
                dprint('Splitting gedge %i at %f; Joining stroke at %i' % (i_gedge,min_t,len(stroke)-1))
                self.insert_gedge_from_stroke(stroke, sgv0=sgv0, sgv3=gv_split, depth=depth+1, sgedges=sgedges)
            else:
                dprint('Splitting gedge %i at %f; Splitting stroke at 0-%i-%i' % (i_gedge,min_t,min_i0,len(stroke)-1))
                self.insert_gedge_from_stroke(stroke[:min_i0], sgv0=sgv0, sgv3=gv_split, depth=depth+1, sgedges=sgedges)
                self.insert_gedge_from_stroke(stroke[min_i0:], sgv0=gv_split, sgv3=sgv3, depth=depth+1, sgedges=sgedges)
            return
            
        
        l_bpts = cubic_bezier_fit_points([pt for pt,pr in stroke], min(r0,r3) / 20)
        pregv,fgv = None,None
        for i,bpts in enumerate(l_bpts):
            t0,t3,bpt0,bpt1,bpt2,bpt3 = bpts
            if i == 0:
                gv0 = self.create_gvert(bpt0, radius=r0) if not sgv0 else sgv0
                fgv = gv0
            else:
                gv0 = pregv
            
            gv1 = self.create_gvert(bpt1,radius=(r0+r3)/2)
            gv2 = self.create_gvert(bpt2,radius=(r0+r3)/2)
            
            if i == len(l_bpts)-1:
                gv3 = self.create_gvert(bpt3, radius=r3) if not sgv3 else sgv3
            else:
                gv3 = self.create_gvert(bpt3, radius=r3)
            
            if (gv1.position-gv0.position).length == 0: dprint('gv01.der = 0')
            if (gv2.position-gv3.position).length == 0: dprint('gv32.der = 0')
            if (gv0.position-gv3.position).length == 0:
                dprint('gv03.der = 0')
                dprint(l_bpts)
                dprint(str(sgv0.position) if sgv0 else 'None')
                dprint(str(sgv3.position) if sgv3 else 'None')
            
            self.create_gedge(gv0,gv1,gv2,gv3)
            pregv = gv3
            gv0.update()
            gv0.update_gedges()
        gv3.update()
        gv3.update_gedges()
        
    def dissolve_gvert(self, gvert, tessellation=20):
        if not (gvert.is_endtoend() or gvert.is_ljunction()):
            print('Cannot dissolve GVert with %i connections' % gvert.count_gedges())
            return
        
        gedge0 = gvert.gedge0
        gedge1 = gvert.gedge1 if gvert.gedge1 else gvert.gedge2
        
        p00,p01,p02,p03 = gedge0.get_positions()
        p10,p11,p12,p13 = gedge1.get_positions()
        
        pts0 = [cubic_bezier_blend_t(p00,p01,p02,p03,i/tessellation) for i in range(tessellation+1)]
        pts1 = [cubic_bezier_blend_t(p10,p11,p12,p13,i/tessellation) for i in range(tessellation+1)]
        if gedge0.gvert0 == gvert: pts0.reverse()
        if gedge1.gvert3 == gvert: pts1.reverse()
        pts = pts0 + pts1
        
        t0,t3,p0,p1,p2,p3 = cubic_bezier_fit_points(pts, self.length_scale, allow_split=False)[0]
        
        gv0 = gedge0.gvert3 if gedge0.gvert0 == gvert else gedge0.gvert0
        gv1 = self.create_gvert(p1, gvert.radius)
        gv2 = self.create_gvert(p2, gvert.radius)
        gv3 = gedge1.gvert3 if gedge1.gvert0 == gvert else gedge1.gvert0
        
        self.disconnect_gedge(gedge0)
        self.disconnect_gedge(gedge1)
        self.create_gedge(gv0,gv1,gv2,gv3)
        gv0.update()
        gv0.update_gedges()
        gv3.update()
        gv3.update_gedges()
    
    def create_mesh(self):
        
        mx = self.obj.matrix_world
        imx = mx.inverted()
        
        verts = []
        quads = []
        dgvcorners = {}
        dgvindex = {}
        
        def create_vert(verts, imx, v):
            i = len(verts)
            verts += [imx*v]
            return i
        
        def create_quad(quads, iv0,iv1,iv2,iv3):
            quads += [(iv0,iv1,iv2,iv3)]
        
        for i,gv in enumerate(self.gverts):
            if gv.is_unconnected(): continue
            dgvindex[gv] = i
            p0,p1,p2,p3 = gv.get_corners()
            dgvcorners[(i,0)] = create_vert(verts,imx,p0)
            dgvcorners[(i,1)] = create_vert(verts,imx,p1)
            dgvcorners[(i,2)] = create_vert(verts,imx,p2)
            dgvcorners[(i,3)] = create_vert(verts,imx,p3)
            create_quad(quads, dgvcorners[(i,3)], dgvcorners[(i,2)], dgvcorners[(i,1)], dgvcorners[(i,0)])
        
        for ge in self.gedges:
            p0,p1,p2,p3 = ge.gvert0.snap_pos, ge.gvert1.snap_pos, ge.gvert2.snap_pos, ge.gvert3.snap_pos
            l = len(ge.cache_igverts)
            
            i0 = dgvindex[ge.gvert0]
            i3 = dgvindex[ge.gvert3]
            i00,i01 = ge.gvert0.get_cornerinds_of(ge)
            i32,i33 = ge.gvert3.get_cornerinds_of(ge)
            
            c0 = dgvcorners[(i0,i00)]
            c1 = dgvcorners[(i0,i01)]
            c2 = dgvcorners[(i3,i32)]
            c3 = dgvcorners[(i3,i33)]
            
            if l == 0:
                create_quad(quads, c0, c1, c2, c3)
                continue
            
            cc0 = c0
            cc1 = c1
            
            for i,gvert in enumerate(ge.cache_igverts):
                if i%2 == 0: continue
                if i == 1: continue
                
                if i == l-2:
                    cc2 = c2
                    cc3 = c3
                
                elif i == len(ge.cache_igverts) - 1 and ge.force_count:
                    print('did the funky math')
                    p2, p3 = ge.gvert3.get_corners_of(ge)
                    cc2, cc3 = verts.index(imx * p2), verts.index(imx * p3)
                else:
                    p2 = gvert.position-gvert.tangent_y*gvert.radius
                    p3 = gvert.position+gvert.tangent_y*gvert.radius
                    p2 = mx * self.obj.closest_point_on_mesh(imx*p2)[0]
                    p3 = mx * self.obj.closest_point_on_mesh(imx*p3)[0]
                    cc2 = create_vert(verts,imx, p2)
                    cc3 = create_vert(verts,imx, p3)
                
                create_quad(quads, cc0, cc1, cc2, cc3)
                
                cc0 = cc3
                cc1 = cc2
        
        return (verts,quads)
    
    def rip_gvert(self, gvert):
        if gvert.is_unconnected(): return
        l_gedges = gvert.get_gedges_notnone()
        for ge in l_gedges:
            ngv = gvert.clone()
            l_gv = [ngv if gv==gvert else gv for gv in ge.gverts()]
            self.disconnect_gedge(ge)
            self.create_gedge(*l_gv)
            self.gverts += [ngv]
        



