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
    def __init__(self, position, radius, normal, tangent_x, tangent_y):
        # store info
        self.position  = position
        self.radius    = radius
        self.normal    = normal
        self.tangent_x = tangent_x
        self.tangent_y = tangent_y

class GEdge:
    '''
    Graph Edge (GEdge) stores end points and "way points" (cubic bezier)
    '''
    def __init__(self, gvert0, gvert1, gvert2, gvert3):
        # store end gvertices
        self.gvert0 = gvert0
        self.gvert1 = gvert1
        self.gvert2 = gvert2
        self.gvert3 = gvert3
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
    
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
    
    def recalc_igverts_approx(self):
        '''
        recomputes interval gverts along gedge
        note: considering only the radii of end points
        note: approx => not snapped to surface
        '''
        
        p0,p1,p2,p3 = self.get_positions()
        r0,r1,r2,r3 = self.get_radii()
        n0,n1,n2,n3 = self.get_normals()
        print('r0 = %f' % r0)
        print('r3 = %f' % r3)
        
        # get bezier length
        l = self.get_length()
        print('l = %f' % l)
        
        cmin,cmax = int(math.floor(l/max(r0,r3))),int(math.floor(l/min(r0,r3)))
        print('cmin = %i' % cmin)
        print('cmax = %i' % cmax)
        c = 0
        for ctest in range(max(4,cmin-2),cmax+1):
            s = (r3-r0) / (ctest-1)
            tot = r0*(ctest+1) + s*(ctest+1)*ctest/2
            if tot > l:
                break
            if ctest % 2 == 1:
                c = ctest
        if c <= 1:
            print('TOO BIG!')
            self.cache_igverts = []
            return
        print('c = ' + str(c))
        
        # compute difference for smoothly interpolating radii
        s = (r3-r0) / (c-1)
        print('s = %f' % s)
        
        # compute how much space is left over (to be added to each interval)
        tot = r0*(c+1) + s*(c+1)*c/2
        o = l - tot
        oc = o / (c+1)
        print('tot = %f' % tot)
        print('o = %f' % o)
        print('oc = %f' % oc)
        
        # compute interval lengths, ts, blend weights
        l_widths = [0] + [r0+oc+i*s for i in range(c+1)]
        l_ts = [p/l for w,p in iter_running_sum(l_widths)]
        l_weights = [cubic_bezier_weights(t) for t in l_ts]
        print(l_ts)
        print(len(l_ts))
        
        # compute interval pos, rad, norm, tangent x, tangent y
        l_pos   = [cubic_bezier_blend_weights(p0,p1,p2,p3,weights) for weights in l_weights]
        l_radii = l_widths
        l_norms = [cubic_bezier_blend_weights(n0,n1,n2,n3,weights).normalized() for weights in l_weights]
        l_tanx  = [cubic_bezier_derivative(p0,p1,p2,p3,t).normalized() for t in l_ts]
        l_tany  = [t.cross(n).normalized() for t,n in zip(l_tanx,l_norms)]
        
        # create igverts!
        self.cache_igverts = [GVert(p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
    
    def snap_igverts_to_object(self, obj):
        '''
        snaps already computed igverts to surface of object ob
        '''
        mx = obj.matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        for igv in self.cache_igverts:
            l,n,i = obj.closest_point_on_mesh(imx * igv.position)
            igv.position = mx * l
            igv.normal = (mx3x3 * n).normalized()
            igv.tangent_y = igv.tangent_x.cross(igv.normal).normalized()



class PolyStrips(object):
    def __init__(self, context, obj):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        
        self.obj = obj
    
