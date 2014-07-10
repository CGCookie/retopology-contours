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
from general_utilities import frange, get_object_length_scale, profiler
from contour_utilities import draw_circle

from polystrips import *

# Create a class that contains all location information for addons
AL = general_utilities.AddonLocator()

#a place to store stokes for later
global contour_cache

#store any temporary triangulated objects
#store the bmesh to prevent recalcing bmesh
#each time :-)
global contour_mesh_cache


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
    
    def get_event_details(self, context, event):
        event_ctrl    = 'CTRL+'  if event.ctrl  else ''
        event_shift   = 'SHIFT+' if event.shift else ''
        event_alt     = 'ALT+'   if event.alt   else ''
        event_ftype   = event_ctrl + event_shift + event_alt + event.type
        
        return {
            'context':  context,
            
            'ctrl':     event.ctrl,
            'shift':    event.shift,
            'alt':      event.alt,
            'value':    event.value,
            'type':     event.type,
            'ftype':    event_ftype,
            'press':    event_ftype if event.value=='PRESS'   else None,
            'release':  event_ftype if event.value=='RELEASE' else None,
            
            'mouse':    (float(event.mouse_region_x), float(event.mouse_region_y)),
            }
    
    
    def draw_callback(self, context):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        cols = [(1,.5,.5,.8),(.5,1,.5,.8),(.5,.5,1,.8),(1,1,.5,.8)]
        
        draw_original_strokes   = False
        draw_bezier_directions  = False
        draw_gvert_orientations = False
        draw_unconnected_gverts = False
        
        color_selected          = (.5,1,.5,.8)
        
        color_gedge             = (1,.5,.5,.8)
        color_gedge_nocuts      = (.5,.2,.2,.8)
        
        color_gvert_unconnected = (.2,.2,.2,.8)
        color_gvert_endpoint    = (.2,.2,.5,.8)
        color_gvert_endtoend    = (.5,.5,1,.8)
        color_gvert_ljunction   = (1,.5,1,.8)
        color_gvert_tjunction   = (1,1,.5,.8)
        color_gvert_cross       = (1,1,1,.8)
        color_gvert_midpoints   = (.7,1,.7,.8)
        
        sel_on = True #(int(time.time()*2)%2 == 1)
        
        if draw_original_strokes:
            for stroke in self.strokes_original:
                #p3d = [pt for pt,pr in stroke]
                #contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.7,.7,.7,.8), 3, "GL_LINE_SMOOTH")
                draw_circle(context, stroke[0][0], Vector((0,0,1)),0.003,(.2,.2,.2,.8))
                draw_circle(context, stroke[-1][0], Vector((0,1,0)),0.003,(.5,.5,.5,.8))
        
        
        for ind,gedge in enumerate(self.polystrips.gedges):
            col = color_gedge if len(gedge.cache_igverts) else color_gedge_nocuts
            if gedge == self.sel_gedge and sel_on: col = color_selected
            
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
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 3, "GL_LINE_SMOOTH")
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
            
            if not draw_unconnected_gverts and gv.is_unconnected() and gv != self.sel_gvert: continue
            
            col = color_gvert_unconnected
            if gv.is_endpoint(): col = color_gvert_endpoint
            elif gv.is_endtoend(): col = color_gvert_endtoend
            elif gv.is_ljunction(): col = color_gvert_ljunction
            elif gv.is_tjunction(): col = color_gvert_tjunction
            elif gv.is_cross(): col = color_gvert_cross
            
            if gv == self.sel_gvert and sel_on: col = color_selected
            
            p3d = [p0,p1,p2,p3,p0]
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
            
            if draw_gvert_orientations:
                p,x,y = gv.snap_pos,gv.snap_tanx,gv.snap_tany
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+x*0.005], (1,0,0,1), 1, "GL_LINE_SMOOTH")
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+y*0.005], (0,1,0,1), 1, "GL_LINE_SMOOTH")
        
        if self.sel_gedge:
            col = color_gvert_midpoints
            for gv in [self.sel_gedge.gvert1,self.sel_gedge.gvert2]:
                p0,p1,p2,p3 = gv.get_corners()
                p3d = [p0,p1,p2,p3,p0]
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
        
        if self.sel_gvert:
            col = color_gvert_midpoints
            for ge in [self.sel_gvert.gedge0,self.sel_gvert.gedge1,self.sel_gvert.gedge2,self.sel_gvert.gedge3]:
                if not ge: continue
                gv = ge.gvert1 if ge.gvert0 == self.sel_gvert else ge.gvert2
                p0,p1,p2,p3 = gv.get_corners()
                p3d = [p0,p1,p2,p3,p0]
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
        
        if self.mode == 'sketch':
            contour_utilities.draw_polyline_from_points(context, [self.sketch_curpos, self.sketch[-1]], (0.5,0.5,0.2,0.8), 1, "GL_LINE_SMOOTH")
            contour_utilities.draw_polyline_from_points(context, self.sketch, (1,1,.5,.8), 2, "GL_LINE_SMOOTH")
    
    
    def create_mesh(self, context):
        verts,quads = self.polystrips.create_mesh()
        bm = bmesh.new()
        for v in verts: bm.verts.new(v)
        for q in quads: bm.faces.new([bm.verts[i] for i in q])
        
        dest_me  = bpy.data.meshes.new( self.obj.name + "_polystrips")
        dest_obj = bpy.data.objects.new(self.obj.name + "_polystrips", dest_me)
        dest_obj.matrix_world = self.obj.matrix_world
        dest_obj.update_tag()
        dest_obj.show_all_edges = True
        dest_obj.show_wire = True
        dest_obj.show_x_ray = True
        
        bm.to_mesh(dest_me)
        
        context.scene.objects.link(dest_obj)
        dest_obj.select = True
        context.scene.objects.active = dest_obj
    
    
    def modal_nav(self, eventd):
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
            'NUMPAD_PLUS', 'NUMPAD_MINUS', # CTRL+NUMPAD_PLUS and CTRL+NUMPAD_MINUS are used elsewhere
            'NUMPAD_PERIOD',
        }
        
        handle_nav = False
        handle_nav |= eventd['type'] == 'MIDDLEMOUSE'
        handle_nav |= eventd['type'] == 'MOUSEMOVE' and self.is_navigating
        handle_nav |= eventd['type'].startswith('NDOF_')
        handle_nav |= eventd['type'].startswith('TRACKPAD')
        handle_nav |= eventd['ftype'] in events_numpad
        handle_nav |= eventd['ftype'] in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
        
        if handle_nav:
            self.post_update = True
            return 'nav' if eventd['value'] == 'PRESS' else 'nav done'
        
        return ''
        
    
    def modal_main(self, eventd):
        
        #############################################
        # general navigation
        
        nav = self.modal_nav(eventd)
        if nav:
            return 'nav' if nav=='nav' else ''
        
        ########################################
        # accept / cancel
        
        if eventd['press'] in {'RET', 'NUMPAD_ENTER'}:
            self.create_mesh(eventd['context'])
            return 'finish'
        
        if eventd['press'] in {'ESC'}:
            return 'cancel'
        
        
        #####################################
        # general
        
        if eventd['press'] == 'Q':                                                  # profiler printout
            profiler.printout()
            return ''
        
        if eventd['press'] == 'P':                                                  # grease pencil => strokes
            for gpl in self.obj.grease_pencil.layers: gpl.hide = True
            for stroke in self.strokes_original:
                self.polystrips.insert_gedge_from_stroke(stroke)
            self.polystrips.remove_unconnected_gverts()
            return ''
        
        
        if eventd['press'] == 'LEFTMOUSE':                                          # start sketching
            x,y = eventd['mouse']
            self.sketch_curpos = (x,y)
            self.sketch = [(x,y)]
            self.sel_gvert = None
            self.sel_gedge = None
            return 'sketch'
        
        if eventd['press'] == 'RIGHTMOUSE':                                         # picking
            x,y = eventd['mouse']
            pts = general_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
            if not pts: return ''
            pt = pts[0]
            i,ge,t,d = self.polystrips.closest_gedge_to_point(pt)
            self.sel_gedge,self.sel_gvert = None,None
            if d < self.length_scale * .005:
                if (pt-ge.gvert0.position).length < self.length_scale * .005:
                    self.sel_gvert = ge.gvert0
                elif (pt-ge.gvert3.position).length < self.length_scale * .005:
                    self.sel_gvert = ge.gvert3
                else:
                    self.sel_gedge = ge
            return ''
        
        
        ###################################
        # selected gedge commands
        
        if self.sel_gedge:
            if eventd['press'] == 'X':
                self.polystrips.disconnect_gedge(self.sel_gedge)
                self.sel_gedge = None
                self.polystrips.remove_unconnected_gverts()
                return ''
        
        
        ###################################
        # selected gvert commands
        
        if self.sel_gvert:
            if eventd['press'] == 'CTRL+NUMPAD_PLUS':
                self.sel_gvert.radius *= 1.1
                self.sel_gvert.update()
                return ''
            
            if eventd['press'] == 'CTRL+NUMPAD_MINUS':
                self.sel_gvert.radius /= 1.1
                self.sel_gvert.update()
                return ''
                
            if eventd['press'] == 'CTRL+D':
                self.polystrips.dissolve_gvert(self.sel_gvert)
                self.sel_gvert = None
                self.polystrips.remove_unconnected_gverts()
                return ''
            
            if eventd['press'] == 'CTRL+C':
                self.sel_gvert.toggle_corner()
                return ''
            
            if eventd['press'] == 'X':
                self.polystrips.disconnect_gvert(self.sel_gvert)
                self.sel_gvert = None
                self.polystrips.remove_unconnected_gverts()
                return ''
            
            if eventd['press'] == 'C':
                self.sel_gvert.smooth()
                return ''
            
            if eventd['press'] == 'S':
                rgn   = eventd['context'].region
                r3d   = eventd['context'].space_data.region_3d
                loc   = self.sel_gvert.position
                mx,my = eventd['mouse']
                cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
                rad   = math.sqrt((mx-cx)**2 + (my-cy)**2)
                
                self.action_center = (cx,cy)
                self.action_radius = rad
                self.mode_radius   = rad
                self.mode_pos      = (mx,my)
                
                return 'scale gvert'
        
        return ''
    
    def modal_sketching(self, eventd):
        
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            lx,ly = self.sketch[-1]
            self.sketch_curpos = (x,y)
            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]
            return ''
        
        if eventd['release'] == 'LEFTMOUSE':
            p3d = general_utilities.ray_cast_path(eventd['context'], self.obj, self.sketch) if len(self.sketch) > 1 else []
            if len(p3d) <= 1: return 'main'
            
            # tessellate stroke (if needed) so we have good stroke sampling
            length_tess = self.length_scale / 700
            p3d = [(p0+(p1-p0).normalized()*x) for p0,p1 in zip(p3d[:-1],p3d[1:]) for x in frange(0,(p0-p1).length,length_tess)] + [p3d[-1]]
            stroke = [(p,1) for p in p3d]
            self.sketch = []
            self.polystrips.insert_gedge_from_stroke(stroke)
            self.polystrips.remove_unconnected_gverts()
            return 'main'
        
        return ''
    
    
    def modal_scale_gvert(self, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        ar = self.action_radius
        pr = self.mode_radius
        cr = math.sqrt((mx-cx)**2 + (my-cy)**2)
        
        def update(sgv, m):
            p = sgv.position
            for ge in sgv.get_gedges():
                if not ge: continue
                gv = ge.gvert1 if ge.gvert0 == self.sel_gvert else ge.gvert2
                gv.position = p + (gv.position-p) * m
                gv.update()
            sgv.update()
        
        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            return 'main'
        
        if eventd['press'] == 'ESC':
            update(self.sel_gvert, ar / cr)
            return 'main'
        
        if eventd['type'] == 'MOUSEMOVE':
            update(self.sel_gvert, cr / pr)
            self.mode_pos    = (mx,my)
            self.mode_radius = cr
            return ''
        
        return ''
    
    
    def modal(self, context, event):
        context.area.tag_redraw()
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        eventd = self.get_event_details(context, event)
        
        FSM = {}
        FSM['main']        = self.modal_main
        FSM['sketch']      = self.modal_sketching
        FSM['scale gvert'] = self.modal_scale_gvert
        
        nmode = FSM[self.mode](eventd)
        
        self.is_navigating = (nmode == 'nav')
        if nmode == 'nav': return {'PASS_THROUGH'}
        
        if nmode in {'finish','cancel'}:
            contour_utilities.callback_cleanup(self, context)
            return {'FINISHED'} if nmode == 'finish' else {'CANCELLED'}
        
        if nmode: self.mode = nmode
        
        return {'RUNNING_MODAL'}
    
    
    def create_polystrips_from_bezier(self, ob_bezier):
        data  = ob_bezier.data
        mx    = ob_bezier.matrix_world
        
        def create_gvert(self, mx, co, radius):
            p0  = mx * co
            r0  = radius
            n0  = Vector((0,0,1))
            tx0 = Vector((1,0,0))
            ty0 = Vector((0,1,0))
            return GVert(self.obj,p0,r0,n0,tx0,ty0)
        
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
    
    def create_polystrips_from_greasepencil(self):
        Mx = self.obj.matrix_world
        gp = self.obj.grease_pencil
        gp_layers = gp.layers
        #for gpl in gp_layers: gpl.hide = True
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for frame in layer.frames for stroke in frame.strokes]
        self.strokes_original = strokes
        
        #for stroke in strokes:
        #    self.polystrips.insert_gedge_from_stroke(stroke)
    
    def invoke(self, context, event):
        #settings = context.user_preferences.addons[AL.FolderName].preferences
        #return {'CANCELLED'}
        #return {'RUNNING_MODAL'}
        
        self.mode = 'main'
        self.mode_pos      = (0,0)
        self.mode_radius   = 0
        self.action_center = (0,0)
        self.action_radius = 0
        self.is_navigating = False
        self.sketch_curpos = (0,0)
        self.sketch = []
        
        self.stroke_smoothing = 0.5          # 0: no smoothing. 1: no change
        
        self.obj = context.object
        self.length_scale = get_object_length_scale(self.obj)
        me = self.obj.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
        me.update()
        self.bme = bmesh.new()
        self.bme.from_mesh(me)
        
        self.sel_gedge = None
        self.sel_gvert = None
        
        self.polystrips = PolyStrips(context, self.obj)
        
        if self.obj.grease_pencil:
            self.create_polystrips_from_greasepencil()
        elif 'BezierCurve' in bpy.data.objects:
            self.create_polystrips_from_bezier(bpy.data.objects['BezierCurve'])
        
        
        # switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback,
            (context, ),
            'WINDOW',
            'POST_PIXEL'
            )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}