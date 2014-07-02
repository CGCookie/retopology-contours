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

def quadratic_bezier_weights(t):
    t0,t1 = t,(1-t)
    b0 = t1*t1
    b1 = 2*t0*t1
    b2 = t0*t0
    return (b0,b1,b2)

def cubic_bezier_weights(t):
    t0,t1 = t,(1-t)
    b0 = t1*t1*t1
    b1 = 3*t0*t1*t1
    b2 = 3*t0*t0*t1
    b3 = t0*t0*t0
    return (b0,b1,b2,b3)

def quadratic_bezier_blend_t(v0, v1, v2, t):
    b0,b1,b2 = quadratic_bezier_weights(t)
    return v0*b0 + v1*b1 + v2*b2

def quadratic_bezier_blend_weights(v0, v1, v2, weights):
    b0,b1,b2 = weights
    return v0*b0 + v1*b1 + v2*b2

def cubic_bezier_blend_t(v0, v1, v2, v3, t):
    b0,b1,b2,b3 = cubic_bezier_weights(t)
    return v0*b0 + v1*b1 + v2*b2 + v3*b3

def cubic_bezier_blend_weights(v0, v1, v2, v3, weights):
    b0,b1,b2,b3 = weights
    return v0*b0 + v1*b1 + v2*b2 + v3*b3

def cubic_bezier_length(p0, p1, p2, p3, threshold=0.05):
    '''
    compute (approximate) length of cubic bezier spline
    if end points of spline are "close enough", approximate curve length as distance between end points
    otherwise, subdivide spline return the sum of their recursively-computed lengths
    '''
    l = (p3-p0).length
    if l < threshold: return l
    # use De Casteljau subdivision
    q0,q1,q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
    r0,r1    = (q0+q1)/2, (q1+q2)/2
    s        = (r0+r1)/2
    l0 = cubic_bezier_length(p0,q0,r0,s)
    l1 = cubic_bezier_length(s,r1,q2,p3)
    return l0+l1

def cubic_bezier_derivative(p0, p1, p2, p3, t):
    q0 = 3*(p1-p0)
    q1 = 3*(p2-p1)
    q2 = 3*(p3-p2)
    return quadratic_bezier_blend_t(q0, q1, q2, t)
