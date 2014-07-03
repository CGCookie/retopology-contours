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
    
    for ind,gedge in enumerate(self.polystrips.gedges):
        if ind == self.mod_ind:
            col = (.5,1,.5,.8)
        else:
            col = (1,.5,.5,.8)
        p3d = []
        prev0,prev1 = None,None
        l = len(gedge.cache_igverts)
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
        
        p0,p1,p2,p3 = gedge.gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
        p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16) for t in range(17)]
        contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.1,.1,.1,.8), 1, "GL_LINE_SMOOTH")
    
    for gv in self.polystrips.gverts:
        p0,p1,p2,p3 = gv.get_corners()
        
        #if gv.is_unconnected(): continue
        
        if gv.is_unconnected(): col = (.2,.2,.2,.8)
        elif gv.is_endpoint():  col = (.2,.2,.5,.8)
        elif gv.is_endtoend():  col = (.5,.5,1,.8)
        elif gv.is_ljunction(): col = (1,.5,1,.8)
        elif gv.is_tjunction(): col = (1,1,.5,.8)
        elif gv.is_cross():     col = (1,1,1,.8)
        else: assert False, "unhandled GVert type"
        
        p3d = [p0,p1,p2,p3,p0]
        contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")


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
        gp_layers = [gp.layers[0]]
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for stroke in layer.frames[0].strokes]
        
        self.polystrips = PolyStrips(context, self.obj)
        
        for stroke in strokes:
            print('='*80)
            print('='*80)
            print('='*80)
            dist = sum((p0[0]-p1[0]).length for p0,p1 in zip(stroke[:-1],stroke[1:]))
            if dist < 0.01: continue
            l_p = cubic_bezier_fit_points([pt for pt,pr in stroke])
            r0,r3 = 0.01,0.01
            pregv = None
            for t0,t3,p0,p1,p2,p3 in l_p:
                #r0,r3 = stroke[0][1],stroke[-1][1]
                
                gv0 = pregv if pregv else self.create_gvert(mx, p0, sqrt(r0)*0.01)
                gv1 = self.create_gvert(mx, p1, 0.01)
                gv2 = self.create_gvert(mx, p2, 0.01)
                gv3 = self.create_gvert(mx, p3, sqrt(r3)*0.01)
                
                ge0 = GEdge(self.obj, gv0, gv1, gv2, gv3)
                ge0.recalc_igverts_approx()
                ge0.snap_igverts_to_object()
                
                self.polystrips.gverts += ([gv0] if not pregv else []) + [gv1,gv2,gv3]
                self.polystrips.gedges += [ge0]
                
                pregv = gv3
    
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
