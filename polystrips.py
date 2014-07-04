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
from general_utilities import iter_running_sum, dprint

#Make the addon name and location accessible
AL = general_utilities.AddonLocator()



class GVert:
    def __init__(self, obj, position, radius, normal, tangent_x, tangent_y):
        # store info
        self.obj       = obj
        
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
    
    def _set_gedges(self, ge0, ge1, ge2, ge3):
        self.gedge0,self.gedge1,self.gedge2,self.gedge3 = ge0,ge1,ge2,ge3
    
    def disconnect_gedge(self, gedge):
        gedges = [ge for ge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3] if ge]
        assert gedge in gedges
        gedges = [ge for ge in gedges if ge != gedge]
        self._set_gedges(None,None,None,None)
        for ge in gedges:
            self.connect_gedge(ge)
    
    def connect_gedge(self, gedge):
        gedge0,gedge1,gedge2,gedge3 = self.gedge0,self.gedge1,self.gedge2,self.gedge3
        connect_count = sum([self.has_0(),self.has_1(),self.has_2(),self.has_3()])+1
        vec  = gedge.get_derivative_at(self).normalized()
        vec0 = None if not gedge0 else gedge0.get_derivative_at(self).normalized()
        vec1 = None if not gedge1 else gedge1.get_derivative_at(self).normalized()
        vec2 = None if not gedge2 else gedge2.get_derivative_at(self).normalized()
        vec3 = None if not gedge3 else gedge3.get_derivative_at(self).normalized()
        norm = self.snap_norm
        
        threshold_endtoend = -0.8
        
        if connect_count == 1:
            # first to be connected
            dprint('unconnected => endpoint')
            self._set_gedges(gedge,None,None,None)
            assert self.is_endpoint()
        elif connect_count == 2:
            if vec0.dot(vec) < threshold_endtoend:
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
                if vec0.cross(vec).dot(norm)<0 and vec.cross(vec2).dot(norm)<0:
                    self._set_gedges(gedge,gedge2,None,gedge0)
                else:
                    self._set_gedges(gedge,gedge0,None,gedge2)
            else:
                dprint('l-junction => t-junction')
                if vec0.dot(vec) < threshold_endtoend:
                    self._set_gedges(gedge1,gedge,None,gedge0)
                else:
                    self._set_gedges(gedge0,gedge1,None,gedge)
            assert self.is_tjunction()
        elif connect_count == 4:
            dprint('t-junction => cross-junction')
            if vec0.dot(vec) < threshold_endtoend:
                self._set_gedges(gedge0,gedge1,gedge,gedge3)
            elif vec1.dot(vec) < threshold_endtoend:
                self._set_gedges(gedge1,gedge3,gedge,gedge0)
            else:
                self._set_gedges(gedge3,gedge0,gedge,gedge1)
            assert self.is_cross()
        else:
            assert False
        
        assert self.gedge0 == gedge or self.gedge1 == gedge or self.gedge2 == gedge or self.gedge3 == gedge
        self.update()
    
    def snap_corners(self):
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        self.corner0 = mx * self.obj.closest_point_on_mesh(imx*self.corner0)[0]
        self.corner1 = mx * self.obj.closest_point_on_mesh(imx*self.corner1)[0]
        self.corner2 = mx * self.obj.closest_point_on_mesh(imx*self.corner2)[0]
        self.corner3 = mx * self.obj.closest_point_on_mesh(imx*self.corner3)[0]
        
    def update(self, do_edges=True):
        if self.doing_update: return
        
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        l,n,i = self.obj.closest_point_on_mesh(imx*self.position)
        self.snap_pos  = mx * l
        self.snap_norm = (mx3x3 * n).normalized()
        self.snap_tanx = self.tangent_x.normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        
        if do_edges:
            self.doing_update = True
            for gedge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3]:
                if gedge: gedge.update()
            self.doing_update = False
        
        self.snap_tanx = (Vector((0.2,0.1,0.5)) if not self.gedge0 else self.gedge0.get_derivative_at(self)).normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        
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
    
    def get_corners(self):
        return (self.corner0, self.corner1, self.corner2, self.corner3)
    
    def get_corners_of(self, gedge):
        if gedge == self.gedge0: return (self.corner0, self.corner1)
        if gedge == self.gedge1: return (self.corner1, self.corner2)
        if gedge == self.gedge2: return (self.corner2, self.corner3)
        if gedge == self.gedge3: return (self.corner3, self.corner0)
        assert False, "gedge is not connected"


class GEdge:
    '''
    Graph Edge (GEdge) stores end points and "way points" (cubic bezier)
    '''
    def __init__(self, obj, gvert0, gvert1, gvert2, gvert3):
        # store end gvertices
        self.obj = obj
        self.gvert0 = gvert0
        self.gvert1 = gvert1
        self.gvert2 = gvert2
        self.gvert3 = gvert3
        
        gvert0.connect_gedge(self)
        gvert3.connect_gedge(self)
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
    
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
            print('GEdge too small for GVert radii!')
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
        self.cache_igverts = [GVert(self.obj,p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
        
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
        self.gvert3.update(do_edges=False)


class PolyStrips(object):
    def __init__(self, context, obj):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        
        self.obj = obj
    
    def disconnect_gedge(self, gedge):
        assert gedge in self.gedges
        gedge.disconnect()
        self.gedges = [ge for ge in self.gedges if ge != gedge]
        gvs = [gv for gv in gedge.gverts() if gv.is_unconnected()]
        self.gverts = [gv for gv in self.gverts if gv not in gvs]
