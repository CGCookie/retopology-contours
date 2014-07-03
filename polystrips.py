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
from general_utilities import iter_running_sum

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
    
    def connect_gedge(self, gedge):
        if self.is_unconnected():
            # first to be connected
            self.gedge0 = gedge
            self.update()
            return
        
        if self.is_endpoint():
            vec0 = self.gedge0.get_derivative_at(self).normalized()
            vec1 = gedge.get_derivative_at(self).normalized()
            dot01 = vec0.dot(vec1)
            print('dot = %f' % dot01)
            if dot01 < -0.9:
                print('end-to-end')
                self.gedge2 = gedge
            elif vec0.cross(vec1).dot(self.normal) > 0:
                print('l-junction with swap')
                self.gedge1 = self.gedge0
                self.gedge0 = gedge
            else:
                print('l-junction')
                self.gedge1 = gedge
            self.update()
            return
        
        # TODO: handle other cases
        assert False
    
    def update(self):
        mx = self.obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        l,n,i = self.obj.closest_point_on_mesh(imx*self.position)
        self.snap_pos  = mx * l
        self.snap_norm = (mx3x3 * n).normalized()
        self.snap_tanx = self.tangent_x.normalized()
        self.snap_tany = self.snap_norm.cross(self.tangent_x).normalized()
        
        for gedge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3]:
            if not gedge: continue
            gedge.recalc_igverts_approx()
            gedge.snap_igverts_to_object()
        
        if self.is_unconnected():
            self.corner0 = self.snap_pos + self.snap_tanx*self.radius + self.snap_tany*self.radius
            self.corner1 = self.snap_pos - self.snap_tanx*self.radius + self.snap_tany*self.radius
            self.corner2 = self.snap_pos - self.snap_tanx*self.radius - self.snap_tany*self.radius
            self.corner3 = self.snap_pos + self.snap_tanx*self.radius - self.snap_tany*self.radius
            return
        
        self.tangent_x = self.gedge0.get_derivative_at(self).normalized()
        self.tangent_y = self.normal.cross(self.tangent_x).normalized()
        self.snap_tanx = self.tangent_x.normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        
        if self.is_endpoint():
            print('update endpoint')
            igv0 = self.gedge0.get_igvert_at(self)
            flip0 = 1 if igv0.tangent_x.dot(self.snap_tanx)>0 else -1
            r0 = igv0.radius*flip0
            self.corner1 = igv0.position - igv0.tangent_y*r0
            self.corner0 = igv0.position + igv0.tangent_y*r0
            self.corner3 = self.snap_pos - self.snap_tanx*self.radius + self.snap_tany*self.radius
            self.corner2 = self.snap_pos - self.snap_tanx*self.radius - self.snap_tany*self.radius
            return
        
        if self.is_endtoend():
            print('update end-to-end')
            igv0 = self.gedge0.get_igvert_at(self)
            igv2 = self.gedge2.get_igvert_at(self)
            flip0 = 1 if igv0.tangent_x.dot(self.snap_tanx)>0 else -1
            flip2 = 1 if igv2.tangent_x.dot(self.snap_tanx)>0 else -1
            r0 = igv0.radius*flip0
            r2 = igv2.radius*flip2
            self.corner1 = igv0.position - igv0.tangent_y*r0
            self.corner0 = igv0.position + igv0.tangent_y*r0
            self.corner3 = igv2.position + igv2.tangent_y*r2
            self.corner2 = igv2.position - igv2.tangent_y*r2
            return
        
        if self.is_ljunction():
            print('update l-junction')
            igv0 = self.gedge0.get_igvert_at(self)
            igv1 = self.gedge1.get_igvert_at(self)
            der0 = self.gedge0.get_derivative_at(self).normalized()
            der1 = self.gedge1.get_derivative_at(self).normalized()
            flip0 = 1 if igv0.tangent_x.dot(self.snap_tanx)>0 else -1
            flip1 = 1 if igv1.tangent_x.dot(self.snap_tany)>0 else -1
            r0 = igv0.radius*flip0
            r1 = igv1.radius*flip1
            self.corner0 = igv0.position + igv0.tangent_y*r0
            self.corner1 = ((igv0.position - igv0.tangent_y*r0) + (igv1.position - igv1.tangent_y*r1)) / 2
            self.corner2 = igv1.position + igv1.tangent_y*r1
            self.corner3 = self.snap_pos - self.snap_tanx*self.radius + self.snap_tany*self.radius
            return
        
        assert False, "other junctions not handled, yet"
    
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
    
    def get_derivative_at(self, gv):
        p0,p1,p2,p3 = self.gvert0.position,self.gvert1.position,self.gvert2.position,self.gvert3.position
        if self.gvert0 == gv:
            return cubic_bezier_derivative(p0,p1,p2,p3,0)
        if self.gvert3 == gv:
            return -cubic_bezier_derivative(p0,p1,p2,p3,1)
        assert False, "gv is not an endpoint"
    
    def get_vector_from(self, gv):
        is_0 = (self.gvert0==gv)
        gv0 = self.gvert0 if is_0 else self.gvert3
        gv1 = self.gvert2 if is_0 else self.gvert1
        return gv1.position - gv0.position
    
    def get_igvert_at(self, gv):
        if self.gvert0 == gv:
            return self.cache_igverts[1]
        if self.gvert3 == gv:
            return self.cache_igverts[-2]
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
    
    def recalc_igverts_approx(self, debug=False):
        '''
        recomputes interval gverts along gedge
        note: considering only the radii of end points
        note: approx => not snapped to surface
        '''
        
        p0,p1,p2,p3 = self.get_positions()
        r0,r1,r2,r3 = self.get_radii()
        n0,n1,n2,n3 = self.get_normals()
        if debug:
            print('r0 = %f' % r0)
            print('r3 = %f' % r3)
        
        # get bezier length
        l = self.get_length()
        if debug:
            print('l = %f' % l)
        
        # find "optimal" count for subdividing spline
        cmin,cmax = int(math.floor(l/max(r0,r3))),int(math.floor(l/min(r0,r3)))
        if debug:
            print('cmin = %i' % cmin)
            print('cmax = %i' % cmax)
        c = 0
        for ctest in range(max(4,cmin-2),cmax+2):
            s = (r3-r0) / (ctest-1)
            tot = r0*(ctest+1) + s*(ctest+1)*ctest/2
            if tot > l:
                break
            if ctest % 2 == 1:
                c = ctest
        if debug:
            print('c = ' + str(c))
        if c <= 1:
            print('TOO BIG!')
            self.cache_igverts = []
            return
        
        # compute difference for smoothly interpolating radii
        s = (r3-r0) / (c-1)
        if debug:
            print('s = %f' % s)
        
        # compute how much space is left over (to be added to each interval)
        tot = r0*(c+1) + s*(c+1)*c/2
        o = l - tot
        oc = o / (c+1)
        if debug:
            print('tot = %f' % tot)
            print('o = %f' % o)
            print('oc = %f' % oc)
        
        # compute interval lengths, ts, blend weights
        l_widths = [0] + [r0+oc+i*s for i in range(c+1)]
        l_ts = [p/l for w,p in iter_running_sum(l_widths)]
        l_weights = [cubic_bezier_weights(t) for t in l_ts]
        if debug:
            print(l_ts)
            print(len(l_ts))
        
        # compute interval pos, rad, norm, tangent x, tangent y
        l_pos   = [cubic_bezier_blend_weights(p0,p1,p2,p3,weights) for weights in l_weights]
        l_radii = l_widths
        l_norms = [cubic_bezier_blend_weights(n0,n1,n2,n3,weights).normalized() for weights in l_weights]
        l_tanx  = [cubic_bezier_derivative(p0,p1,p2,p3,t).normalized() for t in l_ts]
        l_tany  = [t.cross(n).normalized() for t,n in zip(l_tanx,l_norms)]
        
        # create igverts!
        self.cache_igverts = [GVert(self.obj,p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
    
    def snap_igverts_to_object(self):
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


class PolyStrips(object):
    def __init__(self, context, obj):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        
        self.obj = obj
    
