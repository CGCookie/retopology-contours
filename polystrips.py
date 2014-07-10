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
import blf
import itertools
from polystrips_utilities import *
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
        
        self.update()
    
    def has_0(self): return not (self.gedge0 is None)
    def has_1(self): return not (self.gedge1 is None)
    def has_2(self): return not (self.gedge2 is None)
    def has_3(self): return not (self.gedge3 is None)
    
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
    
    def disconnect_gedge(self, gedge):
        gedges = [ge for ge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3] if ge]
        assert gedge in gedges
        gedges = [ge for ge in gedges if ge != gedge]
        self._set_gedges(None,None,None,None)
        for ge in gedges:
            self.connect_gedge(ge)
    
    def connect_gedge_inner(self, gedge):
        assert self.is_unconnected()
        assert not self.gedge_inner
        self.gedge_inner = gedge
    
    def connect_gedge(self, gedge):
        pr = profiler.start()
        
        norm = self.snap_norm
        
        gedge0,gedge1,gedge2,gedge3 = self.get_gedges()
        vec  = gedge.get_derivative_at(self).normalized()
        vec0 = None if not gedge0 else gedge0.get_derivative_at(self).normalized()
        vec1 = None if not gedge1 else gedge1.get_derivative_at(self).normalized()
        vec2 = None if not gedge2 else gedge2.get_derivative_at(self).normalized()
        vec3 = None if not gedge3 else gedge3.get_derivative_at(self).normalized()
        
        l_gedges = [ge for ge in self.get_gedges()+[gedge] if ge]
        l_vecs = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        l_gedges = sort_objects_by_angles(norm, l_gedges, l_vecs)
        l_gedges.reverse()
        l_vecs = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        l_angles = [math.fmod(v0.angle(v1),math.pi*2) for v0,v1 in zip(l_vecs,l_vecs[1:]+[l_vecs[0]])]
        
        connect_count = len(l_gedges)
        
        
        #Larger abs value restricts more parallel
        #end to end connections.
        threshold_angle_endtoend = -0.8
        
        if connect_count == 1:
            # first to be connected
            dprint('unconnected => endpoint')
            self._set_gedges(gedge,None,None,None)
            assert self.is_endpoint()
        
        elif connect_count == 2:
            if vec0.dot(vec) < threshold_angle_endtoend:
                dprint('endpoint => end-to-end')
                self._set_gedges(gedge0,None,gedge,None)
                assert self.is_endtoend()
            else:
                dprint('endpoint => l-junction')
                if vec0.cross(vec).dot(norm) < 0:
                    self._set_gedges(gedge0,gedge,None,None)
                else:
                    self._set_gedges(gedge,gedge0,None,None)
                assert self.is_ljunction()
        
        elif connect_count == 3:
            if self.is_endtoend():
                dprint('end-to-end => t-junction')
            else:
                dprint('l-junction => t-junction')
            max_i,max_a = 0,0
            for i,a in enumerate(l_angles):
                if a>max_a: max_i,max_a = i,a
            i0 = (max_i+2) % 3
            i1 = max_i
            i3 = (max_i+1) % 3
            self._set_gedges(l_gedges[i0],l_gedges[i1],None,l_gedges[i3])
            assert self.is_tjunction()
        
        elif connect_count == 4:
            dprint('t-junction => cross-junction')
            self._set_gedges(l_gedges[0],l_gedges[1],l_gedges[2],l_gedges[3])
            assert self.is_cross()
        
        else:
            assert False, "CANNOT CONNECT %i GEDGES" % connect_count
        
        assert self.gedge0 == gedge or self.gedge1 == gedge or self.gedge2 == gedge or self.gedge3 == gedge
        self.update()
        
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
        
        igv0 = None if not self.gedge0 else self.gedge0.get_igvert_at(self)
        igv1 = None if not self.gedge1 else self.gedge1.get_igvert_at(self)
        igv2 = None if not self.gedge2 else self.gedge2.get_igvert_at(self)
        igv3 = None if not self.gedge3 else self.gedge3.get_igvert_at(self)
        
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
    
    def get_corners(self):
        return (self.corner0, self.corner1, self.corner2, self.corner3)
    
    def is_picked(self, pt):
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
        
        der0 = self.gedge0.get_derivative_at(self).normalized() if self.gedge0 else Vector()
        der1 = self.gedge1.get_derivative_at(self).normalized() if self.gedge1 else Vector()
        der2 = self.gedge2.get_derivative_at(self).normalized() if self.gedge2 else Vector()
        der3 = self.gedge3.get_derivative_at(self).normalized() if self.gedge3 else Vector()
        
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
            angle = (math.pi/2 - der3.angle(der0))*v
            cross = der3.cross(der0).normalized()
            self.gedge3.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge0.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            angle = (math.pi/2 - der0.angle(der1))*v
            cross = der0.cross(der1).normalized()
            self.gedge0.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge1.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            angle = (math.pi/2 - der1.angle(der2))*v
            cross = der1.cross(der2).normalized()
            self.gedge1.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge2.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            angle = (math.pi/2 - der2.angle(der3))*v
            cross = der2.cross(der3).normalized()
            self.gedge2.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge3.rotate_gverts_at(self, Quaternion(cross,  angle))
            
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
        
        gvert0.connect_gedge(self)
        gvert1.connect_gedge_inner(self)
        gvert2.connect_gedge_inner(self)
        gvert3.connect_gedge(self)
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
    
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
        self.gvert3.disconnect_gedge(self)
    
    def gverts(self):
        return [self.gvert0,self.gvert1,self.gvert2,self.gvert3]
    
    def get_derivative_at(self, gv):
        p0,p1,p2,p3 = self.gvert0.position,self.gvert1.position,self.gvert2.position,self.gvert3.position
        if self.gvert0 == gv:
            return cubic_bezier_derivative(p0,p1,p2,p3,0)
        if self.gvert3 == gv:
            return cubic_bezier_derivative(p3,p2,p1,p0,0)
        assert False, "gv is not an endpoint"
    
    def get_inner_gvert_at(self, gv):
        if self.gvert0 == gv: return self.gvert1
        if self.gvert3 == gv: return self.gvert2
        assert False, "gv is not an endpoint"
    
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
        return cubic_bezier_length(p0,p1,p2,p3)
    
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
        s = (r3-r0) / (c-1)
        
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
        l_radii = l_widths
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
        for p0,p1,p2,p3 in self.iter_segments():
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            if c1.cross(c0).dot(n)>0 and c2.cross(c1).dot(n)>0 and c3.cross(c2).dot(n)>0 and c0.cross(c3).dot(n)>0:
                return True
        return False
    
    def iter_segments(self):
        l = len(self.cache_igverts)
        if l == 0:
            cur0,cur1 = self.gvert0.get_corners_of(self)
            cur2,cur3 = self.gvert3.get_corners_of(self)
            yield (cur0,cur1,cur2,cur3)
        else:
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
        r0  = self.length_scale * radius
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
    
    def insert_gedge_from_stroke(self, stroke):
        '''
        stroke: list of tuples (3d location, pressure)
        '''
        
        threshold_tooshort     = self.length_scale / 200 # 0.003
        threshold_junctiondist = self.length_scale / 150 # 0.003
        threshold_splitdist    = self.length_scale / 200
        
        # too short?
        if len(stroke) < 4:
            print('Too few samples in stroke (subsample??)')
            #subsampling function in contour_utils.space_evenly_on_path
            return
        tot_length = sum((s0[0]-s1[0]).length for s0,s1 in zip(stroke[:-1],stroke[1:]))
        if tot_length < threshold_tooshort:
            print('Stroke too short (%f)' % tot_length)
            return
        
        
        # TODO: self intersection tests!
        # check for self-intersections
        #for i0,info0 in enumerate(stroke):
        #    pt0,pr0 = info0
        #    for i1,info1 in enumerate(stroke):
        #        if i1 <= i0: continue
        #        pt1,pr1 = info1
        
        
        sgv0,sgv3 = None,None
        
        # check for junctions
        for i_gedge,gedge in enumerate(self.gedges):
            p0,p1,p2,p3 = gedge.get_positions()
            
            min_i0,min_t,min_d = -1,-1,0
            # find closest distance between stroke and gedge
            for i0,info0 in enumerate(stroke):
                pt0,pr0 = info0
                (split_t,split_d) = cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,pt0)
                if min_i0 == -1 or split_d <= min_d: min_i0,min_t,min_d = i0,split_t,split_d
            if min_i0 == -1 or min_d > max([threshold_junctiondist,threshold_splitdist]): continue
            
            split_bpt = cubic_bezier_blend_t(p0,p1,p2,p3,min_t)
            
            closeto_i0 = (min_i0 < 3)
            closeto_i1 = (min_i0 > len(stroke)-4)
            closeto_p0 = ((split_bpt-p0).length <= threshold_junctiondist)
            closeto_p3 = ((split_bpt-p3).length <= threshold_junctiondist)
            
            if not closeto_p0 and not closeto_p3 and min_d <= threshold_splitdist:
                # not close to endpoint of bezier, so split bezier and recurse
                
                dprint('Splitting gedge %i at %f; Splitting stroke at %i' % (i_gedge,min_t,min_i0))
                
                pt0,pr0 = stroke[min_i0]
                cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3,min_t, self.length_scale)
                
                gv_split = self.create_gvert(cb0[3])
                
                gv0_0 = gedge.gvert0
                gv0_1 = self.create_gvert(cb0[1])
                gv0_2 = self.create_gvert(cb0[2])
                gv0_3 = gv_split
                
                gv1_0 = gv_split
                gv1_1 = self.create_gvert(cb1[1])
                gv1_2 = self.create_gvert(cb1[2])
                gv1_3 = gedge.gvert3
                
                self.disconnect_gedge(gedge)
                ge0 = self.create_gedge(gv0_0,gv0_1,gv0_2,gv0_3)
                ge1 = self.create_gedge(gv1_0,gv1_1,gv1_2,gv1_3)
                
                if closeto_i0:   sgv0 = gv_split
                elif closeto_i1: sgv3 = gv_split
            
            if closeto_p0 or closeto_p3:
                if closeto_i0:
                    sgv0 = gedge.gvert0 if closeto_p0 else gedge.gvert3
                if closeto_i1:
                    sgv3 = gedge.gvert0 if closeto_p0 else gedge.gvert3
            
            if not closeto_i0 and not closeto_i1:
                # break stroke
                self.insert_gedge_from_stroke(stroke[:min_i0])
                self.insert_gedge_from_stroke(stroke[min_i0:])
                return
            
        
        l_bpts = cubic_bezier_fit_points([pt for pt,pr in stroke], self.length_scale)
        pregv,fgv = None,None
        for i,bpts in enumerate(l_bpts):
            t0,t3,bpt0,bpt1,bpt2,bpt3 = bpts
            if i == 0:
                gv0 = self.create_gvert(bpt0) if not sgv0 else sgv0
                fgv = gv0
            else:
                gv0 = pregv
                
            gv1 = self.create_gvert(bpt1)
            gv2 = self.create_gvert(bpt2)
            
            if i == len(l_bpts)-1:
                if (bpt3-l_bpts[0][2]).length < threshold_junctiondist:
                    gv3 = fgv
                else:
                    gv3 = self.create_gvert(bpt3) if not sgv3 else sgv3
            else:
                gv3 = self.create_gvert(bpt3)
            
            self.create_gedge(gv0,gv1,gv2,gv3)
            pregv = gv3
        
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
        gv1 = self.create_gvert(p1)
        gv2 = self.create_gvert(p2)
        gv3 = gedge1.gvert3 if gedge1.gvert0 == gvert else gedge1.gvert0
        
        self.disconnect_gedge(gedge0)
        self.disconnect_gedge(gedge1)
        self.create_gedge(gv0,gv1,gv2,gv3)
    
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



