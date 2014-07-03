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

def cubic_bezier_fit_value(l_v):
    v0 = l_v[0]
    v1 = l_v[int(len(l_v)*1/3)]
    v2 = l_v[int(len(l_v)*2/3)]
    v3 = l_v[-1]
    
    chk_t0 = 0.35
    chk_t1 = 1.00-chk_t0
    
    l_dists = [abs(v0-v1) for v0,v1 in zip(l_v[:-1],l_v[1:])]
    dist    = sum(l_dists)
    l_t = [0] + [s/dist for d,s in general_utilities.iter_running_sum(l_dists)]
    ind_q0,ind_mid,ind_q1  = -1,-1,-1
    for i,t in enumerate(l_t):
        if t > 0.50 and ind_mid == -1: ind_mid = i
        if t > chk_t0 and ind_q0 == -1:
            ind_q0 = i
            chk_t0 = t
        if t > chk_t1 and ind_q1 == -1:
            ind_q1 = i
            chk_t1 = t
    assert ind_mid != -1
    assert ind_q0 != -1
    assert ind_q1 != -1
    v_q0,v_mid,v_q1  = l_v[ind_q0],l_v[ind_mid],l_v[ind_q1]
    
    nl_v,nl_t = [],[]
    cur_t = -1
    for v,t in zip(l_v,l_t):
        if t-cur_t<0.1: continue
        nl_v += [v]
        nl_t += [t]
        cur_t = t
    print('len(l_v) = %i, len(nl_v) = %i' % (len(l_v),len(nl_v)))
    print(str(nl_t))
    l_v,l_t = nl_v,nl_t
    
    def compute_errors(v0,v1,v2,v3,l_v,l_t):
        error_left  = sum(((cubic_bezier_blend_t(v0,v1,v2,v3,t)-v))**2 for v,t in zip(l_v,l_t) if t < 0.5)
        error_right = sum(((cubic_bezier_blend_t(v0,v1,v2,v3,t)-v))**2 for v,t in zip(l_v,l_t) if t > 0.5)
        return (math.sqrt(error_left)/len(l_v),math.sqrt(error_right)/len(l_v))
    
    #print('---------------')
    b25 = cubic_bezier_weights(chk_t0)
    b50 = cubic_bezier_weights(0.50)
    b75 = cubic_bezier_weights(chk_t1)
    for iters in range(1000):
        v_q0_diff  = v_q0  - cubic_bezier_blend_weights(v0,v1,v2,v3,b25)
        v_mid_diff = v_mid - cubic_bezier_blend_weights(v0,v1,v2,v3,b50)
        v_q1_diff  = v_q1  - cubic_bezier_blend_weights(v0,v1,v2,v3,b75)
        err0,err1 = compute_errors(v0,v1,v2,v3,l_v,l_t)
        error_tot = err0+err1
        
        #if abs(v_q0_diff) < 0.00001 and abs(v_mid_diff) < 0.0001 and abs(v_q1_diff) < 0.00001: break
        if error_tot < 0.0001:
            break
        
        mult = 1.0
        while mult > 0.1:
            nv1,nv2 = v1,v2
            nv1 += mult * (v_q0_diff + v_mid_diff * err0/error_tot)
            nv2 += mult * (v_q1_diff + v_mid_diff * err1/error_tot)
            nerr0,nerr1 = compute_errors(v0,nv1,nv2,v3,l_v,l_t)
            if nerr0+nerr1 < error_tot:
                print('%f, %f, %f.  %f, %f (%f)  %f' % (v_q0_diff,v_mid_diff,v_q1_diff,err0/error_tot,err1/error_tot,error_tot,mult))
                v1,v2 = nv1,nv2
                break
            mult -= 0.05
    
    err0,err1 = compute_errors(v0,v1,v2,v3,l_v,l_t)
    
    return (err0+err1,v0,v1,v2,v3)

def cubic_bezier_fit_points(l_co, depth=0, t0=0, t3=1):
    ex,x0,x1,x2,x3 = cubic_bezier_fit_value([co[0] for co in l_co])
    ey,y0,y1,y2,y3 = cubic_bezier_fit_value([co[1] for co in l_co])
    ez,z0,z1,z2,z3 = cubic_bezier_fit_value([co[2] for co in l_co])
    
    #print('%f %f %f' % (ex,ey,ez))
    if ex+ey+ez < 0.01 or depth == 4 or len(l_co)<16:
        p0,p1,p2,p3 = Vector((x0,y0,z0)),Vector((x1,y1,z1)),Vector((x2,y2,z2)),Vector((x3,y3,z3))
        return [(t0,t3,p0,p1,p2,p3)]
    
    #print('split!')
    ind_split = 16
    mindot = 1.0
    for ind in range(16,len(l_co)-16):
        v0 = l_co[ind-8]
        v1 = l_co[ind+0]
        v2 = l_co[ind+8]
        d0 = (v1-v0).normalized()
        d1 = (v2-v1).normalized()
        dot01 = d0.dot(d1)
        if dot01 < mindot:
            ind_split = ind
            mindot = dot01
    l_co_left = l_co[:ind_split]
    l_co_right = l_co[ind_split:]
    tsplit = ind_split / (len(l_co)-1)
    return cubic_bezier_fit_points(l_co_left, depth+1, t0, tsplit) + cubic_bezier_fit_points(l_co_right, depth+1, tsplit, t3)

