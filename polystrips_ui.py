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

import bpy
import bmesh
import blf
import math
import sys
import copy
import time
from mathutils import Vector, Matrix
from math import sqrt
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d
import contour_utilities, general_utilities
from contour_classes import ContourCutLine, ExistingVertList, CutLineManipulatorWidget, PolySkecthLine, ContourCutSeries, ContourStatePreserver
from polystrips import PolyStrips, GVert, GEdge
from mathutils.geometry import intersect_line_plane, intersect_point_line
from bpy.props import EnumProperty, StringProperty,BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences
import random

from polystrips import *

# Create a class that contains all location information for addons
AL = general_utilities.AddonLocator()

#a place to store stokes for later
global contour_cache 

#store any temporary triangulated objects
#store the bmesh to prevent recalcing bmesh
#each time :-)
global contour_mesh_cache

def draw_circle(context, c,n,r,col,step=10):
    x = Vector((0.42,-0.42,0.42)).cross(n).normalized() * r
    y = n.cross(x).normalized() * r
    d2r = math.pi/180
    p3d = [c+x*math.cos(i*d2r)+y*math.sin(i*d2r) for i in range(0,360+step,step)]
    contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 1, "GL_LINE_SMOOTH")

def polystrips_draw_callback(self, context):
    settings = context.user_preferences.addons[AL.FolderName].preferences
    cols = [(1,.5,.5,.8),(.5,1,.5,.8),(.5,.5,1,.8),(1,1,.5,.8)]
    
    draw_original_strokes = False
    draw_bezier_directions = False
    draw_gvert_orientations = False
    
    if draw_original_strokes:
        for stroke in self.strokes_original:
            #p3d = [pt for pt,pr in stroke]
            #contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.7,.7,.7,.8), 3, "GL_LINE_SMOOTH")
            draw_circle(context, stroke[0][0], Vector((0,0,1)),0.003,(.2,.2,.2,.8))
            draw_circle(context, stroke[-1][0], Vector((0,1,0)),0.003,(.5,.5,.5,.8))
    
    
    for ind,gedge in enumerate(self.polystrips.gedges):
        if ind == self.mod_ind:
            col = (.5,1,.5,.8)
        else:
            col = (1,.5,.5,.8)
        
        p0,p1,p2,p3 = gedge.gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
        
        if draw_bezier_directions:
            n0,n1,n2,n3 = gedge.gvert0.snap_norm, gedge.gvert1.snap_norm, gedge.gvert2.snap_norm, gedge.gvert3.snap_norm
            pm = cubic_bezier_blend_t(p0,p1,p2,p3,0.5)
            px = cubic_bezier_derivative(p0,p1,p2,p3,0.5).normalized()
            pn = (n0+n3).normalized()
            py = pn.cross(px).normalized()
            rs = 0.0015
            rl = 0.0007
            p3d = [pm,pm+px*rs,pm+px*(rs-rl)+py*rl,pm+px*rs,pm+px*(rs-rl)-py*rl]
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, (0.8,0.8,0.8,0.8),1, "GL_LINE_SMOOTH")
        
        l = len(gedge.cache_igverts)
        if l == 0:
            # draw bezier for uncut segments!
            #p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16) for t in range(17)]
            #contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.7,.1,.1,.8), 5, "GL_LINE_SMOOTH")
            cur0,cur1 = gedge.gvert0.get_corners_of(gedge)
            cur2,cur3 = gedge.gvert3.get_corners_of(gedge)
            p3d = [cur0,cur1,cur2,cur3,cur0]
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.7,.1,.1,.8), 3, "GL_LINE_SMOOTH")
        else:
            p3d = []
            prev0,prev1 = None,None
            for i,gvert in enumerate(gedge.cache_igverts):
                if i%2 == 0: continue
                
                if i == 1:
                    gv0 = gedge.gvert0
                    cur0,cur1 = gv0.get_corners_of(gedge)
                elif i == l-2:
                    gv3 = gedge.gvert3
                    cur1,cur0 = gv3.get_corners_of(gedge)
                else:
                    cur0 = gvert.position+gvert.tangent_y*gvert.radius
                    cur1 = gvert.position-gvert.tangent_y*gvert.radius
                
                if prev0 and prev1:
                    p3d += [prev0,cur0,cur1,prev1,cur1,cur0]
                else:
                    p3d = [cur1,cur0]
                prev0,prev1 = cur0,cur1
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
        
    
    for gv in self.polystrips.gverts:
        p0,p1,p2,p3 = gv.get_corners()
        
        if gv.is_unconnected(): continue
        
        if gv.is_unconnected(): col = (.2,.2,.2,.8)
        elif gv.is_endpoint():  col = (.2,.2,.5,.8)
        elif gv.is_endtoend():  col = (.5,.5,1,.8)
        elif gv.is_ljunction(): col = (1,.5,1,.8)
        elif gv.is_tjunction(): col = (1,1,.5,.8)
        elif gv.is_cross():     col = (1,1,1,.8)
        else: assert False, "unhandled GVert type"
        
        p3d = [p0,p1,p2,p3,p0]
        contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
        
        if draw_gvert_orientations:
            p,x,y = gv.snap_pos,gv.snap_tanx,gv.snap_tany
            contour_utilities.draw_polyline_from_3dpoints(context, [p,p+x*0.005], (1,0,0,1), 1, "GL_LINE_SMOOTH")
            contour_utilities.draw_polyline_from_3dpoints(context, [p,p+y*0.005], (0,1,0,1), 1, "GL_LINE_SMOOTH")


class CGCOOKIE_OT_polystrips(bpy.types.Operator):
    bl_idname = "cgcookie.polystrips"
    bl_label  = "PolyStrips"
    
    @classmethod
    def poll(cls,context):
        if context.mode not in {'EDIT_MESH','OBJECT'}:
            return False
        
        if context.active_object:
            if context.mode == 'EDIT_MESH':
                if len(context.selected_objects) > 1:
                    return True
                else:
                    return False
            else:
                return context.object.type == 'MESH'
        else:
            return False
    
    def modal(self, context, event):
        context.area.tag_redraw()
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        # event details
        event_ctrl    = 'CTRL+'  if event.ctrl  else ''
        event_shift   = 'SHIFT+' if event.shift else ''
        event_alt     = 'ALT+'   if event.alt   else ''
        event_value   = event_ctrl + event_shift + event_alt + event.type
        event_press   = event_value if event.value == 'PRESS'   else None
        event_release = event_value if event.value == 'RELEASE' else None
        
        ####################################
        # general navigation event handling
        
        events_numpad = {
            'NUMPAD_1',       'NUMPAD_2',       'NUMPAD_3',
            'NUMPAD_4',       'NUMPAD_5',       'NUMPAD_6',
            'NUMPAD_7',       'NUMPAD_8',       'NUMPAD_9',
            'CTRL+NUMPAD_1',  'CTRL+NUMPAD_2',  'CTRL+NUMPAD_3',
            'CTRL+NUMPAD_4',  'CTRL+NUMPAD_5',  'CTRL+NUMPAD_6',
            'CTRL+NUMPAD_7',  'CTRL+NUMPAD_8',  'CTRL+NUMPAD_9',
            'SHIFT+NUMPAD_1', 'SHIFT+NUMPAD_2', 'SHIFT+NUMPAD_3',
            'SHIFT+NUMPAD_4', 'SHIFT+NUMPAD_5', 'SHIFT+NUMPAD_6',
            'SHIFT+NUMPAD_7', 'SHIFT+NUMPAD_8', 'SHIFT+NUMPAD_9',
            'NUMPAD_PLUS', 'NUMPAD_MINUS', # CTRL+NUMPAD_PLUS and CTRL+NUMPAD_MINUS are used later
            'NUMPAD_PERIOD',
        }
        handle_nav = False
        handle_nav |= event.type == 'MIDDLEMOUSE'
        handle_nav |= event.type == 'MOUSEMOVE' and self.is_navigating
        handle_nav |= event_value in events_numpad      # note: event_value handles ctrl,shift,alt
        handle_nav |= event.type.startswith('NDOF_')
        handle_nav |= event.type.startswith('TRACKPAD')
        handle_nav |= event_value in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} # note: event_value handles ctrl,shift,alt
        if handle_nav:
            self.is_navigating = (event.value == 'PRESS')
            self.post_update = True
            return {'PASS_THROUGH'}
        self.is_navigating = False
        
        if event_press in {'RET', 'NUMPAD_ENTER', 'ESC'}:
            contour_utilities.callback_cleanup(self, context)
            return {'CANCELLED'}
        
        if self.mod_ind < len(self.polystrips.gedges):
            gv0 = self.polystrips.gedges[self.mod_ind].gvert0
            gv3 = self.polystrips.gedges[self.mod_ind].gvert3
            if event_press == 'CTRL+NUMPAD_PLUS':
                gv0.radius *= 1.1
                gv0.update()
                return {'RUNNING_MODAL'}
            if event_press == 'CTRL+NUMPAD_MINUS':
                gv0.radius /= 1.1
                gv0.update()
                return {'RUNNING_MODAL'}
            if event_press == 'CTRL+SHIFT+NUMPAD_PLUS':
                gv3.radius *= 1.1
                gv3.update()
                return {'RUNNING_MODAL'}
            if event_press == 'CTRL+SHIFT+NUMPAD_MINUS':
                gv3.radius /= 1.1
                gv3.update()
                return {'RUNNING_MODAL'}
        
        if event_press == 'N':
            self.mod_ind = min(len(self.polystrips.gedges)-1,self.mod_ind+1)
        elif event_press == 'P':
            self.mod_ind = max(0, self.mod_ind-1)
        
        if event_press == 'X':
            self.polystrips.disconnect_gedge(self.polystrips.gedges[self.mod_ind])
            self.mod_ind = max(0, self.mod_ind-1)
        
        return{'RUNNING_MODAL'}
    
    def create_gvert(self, mx, co, radius):
        p0  = mx * co
        r0  = radius
        n0  = Vector((0,0,1))
        tx0 = Vector((1,0,0))
        ty0 = Vector((0,1,0))
        return GVert(self.obj,p0,r0,n0,tx0,ty0)
    
    def create_polystrips_from_bezier(self, context, ob_bezier):
        data  = ob_bezier.data
        mx    = ob_bezier.matrix_world
        
        self.polystrips = PolyStrips(context, self.obj)
        
        for spline in data.splines:
            pregv = None
            for bp0,bp1 in zip(spline.bezier_points[:-1],spline.bezier_points[1:]):
                gv0 = pregv if pregv else self.create_gvert(mx, bp0.co, 0.2)
                gv1 = self.create_gvert(mx, bp0.handle_right, 0.2)
                gv2 = self.create_gvert(mx, bp1.handle_left, 0.2)
                gv3 = self.create_gvert(mx, bp1.co, 0.2)
                
                ge0 = GEdge(self.obj, gv0, gv1, gv2, gv3)
                ge0.recalc_igverts_approx()
                ge0.snap_igverts_to_object()
                
                if pregv:
                    self.polystrips.gverts += [gv1,gv2,gv3]
                else:
                    self.polystrips.gverts += [gv0,gv1,gv2,gv3]
                self.polystrips.gedges += [ge0]
                pregv = gv3
    
    def create_polystrips_from_greasepencil(self, context):
        mx = Matrix()
        
        gp = self.obj.grease_pencil
        gp_layers = gp.layers
        #gp_layers = [gp.layers[0]]
        for gpl in gp_layers: gpl.hide = True
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for stroke in layer.frames[0].strokes]
        self.strokes_original = strokes
        
        # kill short strokes
        strokes = [stroke for stroke in strokes if sum((p0[0]-p1[0]).length for p0,p1 in zip(stroke[:-1],stroke[1:])) > 0.01]
        
        # check for t-junctions
        split_stroke = True
        while split_stroke:
            split_stroke = False
            for i0,stroke0 in enumerate(strokes):
                p00,p01 = stroke0[0][0],stroke0[-1][0]
                for i1,stroke1 in enumerate(strokes):
                    p10,p11 = stroke1[0][0],stroke1[-1][0]
                    if i0 == i1: continue
                    min_ind,min_dist = -1,1000
                    for ind,data in enumerate(stroke1):
                        pt1,pr1 = data
                        # too close to an end??
                        if (p10-pt1).length < 0.007 or (p11-pt1).length < 0.007: continue
                        
                        d = min((p00-pt1).length, (p01-pt1).length)
                        if d > 0.005: continue
                        if min_ind == -1 or d < min_dist:
                            min_ind = ind
                            min_dist = d
                            split_stroke = True
                    if split_stroke:
                        print('splitting stroke[%i] at %i' % (i1,min_ind))
                        strokes[i1] = stroke1[:min_ind]
                        strokes += [stroke1[min_ind:]]
                        break
                if split_stroke: break
            if split_stroke: continue
        
        # check if indiv strokes create junctions
        connect = {}
        def do_connect(connect, t0, t1):
            if t0[0] < t1[0]:
                if t1 not in connect: connect[t1] = t0
            elif t1[0] < t0[0]:
                if t0 not in connect: connect[t0] = t1
            else:
                if t0[1] < t1[1]:
                    if t1 not in connect: connect[t1] = t0
                elif t1[1] < t0[1]:
                    if t0 not in connect: connect[t0] = t1
        for i0,stroke0 in enumerate(strokes):
            p00,p01 = stroke0[0][0],stroke0[-1][0]
            for i1,stroke1 in enumerate(strokes):
                p10,p11 = stroke1[0][0],stroke1[-1][0]
                if (p00-p10).length < 0.005:
                    do_connect(connect, (i0,0), (i1,0))
                if (p00-p11).length < 0.005:
                    do_connect(connect, (i0,0), (i1,1))
                if (p01-p10).length < 0.005:
                    do_connect(connect, (i0,1), (i1,0))
                if (p01-p11).length < 0.005:
                    do_connect(connect, (i0,1), (i1,1))
        
        self.polystrips = PolyStrips(context, self.obj)
        
        ends = {}
        for i0,stroke in enumerate(strokes):
            print('fitting stroke %i' % i0)
            l_p = cubic_bezier_fit_points([pt for pt,pr in stroke])
            print('%i pieces' % len(l_p))
            if (i0,0) not in connect:
                ends[(i0,0)] = self.create_gvert(mx,l_p[0][2],0.001)
            else:
                ends[(i0,0)] = ends[connect[(i0,0)]]
            if (i0,1) not in connect:
                ends[(i0,1)] = self.create_gvert(mx,l_p[-1][5],0.001)
            else:
                ends[(i0,1)] = ends[connect[(i0,1)]]
            
            pregv = None
            for i,data in enumerate(l_p):
                t0,t3,p0,p1,p2,p3 = data
                
                gv0 = ends[(i0,0)] if i == 0 else (pregv if pregv else self.create_gvert(mx, p0, 0.001))
                gv1 = self.create_gvert(mx, p1, 0.01)
                gv2 = self.create_gvert(mx, p2, 0.01)
                gv3 = ends[(i0,1)] if i == len(l_p)-1 else self.create_gvert(mx, p3, 0.001)
                
                ge0 = GEdge(self.obj, gv0, gv1, gv2, gv3)
                ge0.update()
                
                self.polystrips.gverts += [gv0,gv1,gv2,gv3]
                self.polystrips.gedges += [ge0]
                
                pregv = gv3
        self.polystrips.gverts = list(set(self.polystrips.gverts))
        print('Done converting GP to strokes')
    
    def invoke(self, context, event):
        #settings = context.user_preferences.addons[AL.FolderName].preferences
        #return {'CANCELLED'}
        #return {'RUNNING_MODAL'}
        
        self.is_navigating = False
        
        self.obj = context.object
        me = self.obj.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
        me.update()
        self.bme = bmesh.new()
        self.bme.from_mesh(me)
        
        self.mod_ind = 0
        #self.create_polystrips_from_bezier(context, bpy.data.objects['BezierCurve'])
        self.create_polystrips_from_greasepencil(context)
        
        # switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            polystrips_draw_callback,
            (self, context),
            'WINDOW',
            'POST_PIXEL'
            )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
