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
import bgl
import math
import sys
import copy
import time
from mathutils import Vector, Matrix
from math import sqrt
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d
import contour_utilities, general_utilities
from contour_classes import ContourCutLine, ExistingVertList, CutLineManipulatorWidget, PolySkecthLine, ContourCutSeries, ContourStatePreserver, SketchBrush
from polystrips import PolyStrips, GVert, GEdge
from mathutils.geometry import intersect_line_plane, intersect_point_line
from bpy.props import EnumProperty, StringProperty,BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences
import random
from general_utilities import frange, get_object_length_scale, profiler
from contour_utilities import draw_circle
from polystrips_draw import *

from polystrips import *

# Create a class that contains all location information for addons
AL = general_utilities.AddonLocator()

#a place to store stokes for later
global contour_cache

#store any temporary triangulated objects
#store the bmesh to prevent recalcing bmesh
#each time :-)
global contour_mesh_cache


#TODO...find a home for this!
def rad_press_mix(r, p, map = 3):
    
    if map == 0:
        p = max(0.25,p)
        
    elif map == 1:
        p = 0.25 + .75 * p
        
    elif map == 2:
        p = max(0.05,p)
    
    elif map == 3:
        p = .7 * (2.25*p-1)/((2.25*p-1)**2 +1)**.5 + .55
    
    return r*p

class PolystripsUI:
    def __init__(self):
        pass
    
    def get_event_details(self, context, event):
        event_ctrl    = 'CTRL+'  if event.ctrl  else ''
        event_shift   = 'SHIFT+' if event.shift else ''
        event_alt     = 'ALT+'   if event.alt   else ''
        event_ftype   = event_ctrl + event_shift + event_alt + event.type
        
        
        return {
            'context':  context,
            'region':   context.region,
            'r3d':      context.space_data.region_3d,
            
            'ctrl':     event.ctrl,
            'shift':    event.shift,
            'alt':      event.alt,
            'value':    event.value,
            'type':     event.type,
            'ftype':    event_ftype,
            'press':    event_ftype if event.value=='PRESS'   else None,
            'release':  event_ftype if event.value=='RELEASE' else None,
            
            'mouse':    (float(event.mouse_region_x), float(event.mouse_region_y)),
            'pressure': 1 if not hasattr(event, 'pressure') else event.pressure
            }
    
    def draw_callback(self, context):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        region,r3d = context.region,context.space_data.region_3d
        
        new_matrix = [v for l in r3d.view_matrix for v in l]
        if self.post_update or self.last_matrix != new_matrix:
            for gv in self.polystrips.gverts:
                gv.update_visibility(r3d)
            for ge in self.polystrips.gedges:
                ge.update_visibility(r3d)
            if self.sel_gedge:
                for gv in [self.sel_gedge.gvert1, self.sel_gedge.gvert2]:
                    gv.update_visibility(r3d)
            if self.sel_gvert:
                for gv in self.sel_gvert.get_inner_gverts():
                    gv.update_visibility(r3d)
            self.post_update = False
            self.last_matrix = new_matrix
        
        if settings.debug < 3:
            self.draw_callback_themed(context)
        else:
            self.draw_callback_debug(context)
    
    def draw_callback_themed(self, context):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        region,r3d = context.region,context.space_data.region_3d
        
        theme_number = 2
        
        color_inactive  = (0,0,0)
        color_selection = [(  5,196,255),(255,206, 82),(255,183,  0)][theme_number]
        color_active    = [(156,236,255),(255,240,189),(255,217,120)][theme_number]     # not used at the moment
        
        for i_ge,gedge in enumerate(self.polystrips.gedges):
            if gedge == self.sel_gedge:
                color_border = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 1.00)
                color_fill   = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 0.20)
            else:
                color_border = (color_inactive[0]/255.0, color_inactive[1]/255.0, color_inactive[2]/255.0, 1.00)
                color_fill   = (0.5, 0.5, 0.5, 0.2)
            
            for c0,c1,c2,c3 in gedge.iter_segments(only_visible=True):
                contour_utilities.draw_quads_from_3dpoints(context, [c0,c1,c2,c3], color_fill)
                contour_utilities.draw_polyline_from_3dpoints(context, [c0,c1,c2,c3,c0], color_border, 2, "GL_LINE_SMOOTH")
        
        for i_gv,gv in enumerate(self.polystrips.gverts):
            if not gv.is_visible(): continue
            p0,p1,p2,p3 = gv.get_corners()
            
            if gv.is_unconnected(): continue
            
            is_selected = False
            is_selected |= gv == self.sel_gvert
            is_selected |= self.sel_gedge!=None and (self.sel_gedge.gvert0 == gv or self.sel_gedge.gvert1 == gv)
            is_selected |= self.sel_gedge!=None and (self.sel_gedge.gvert2 == gv or self.sel_gedge.gvert3 == gv)
            if is_selected:
                color_border = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 1.00)
                color_fill   = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 0.20)
            else:
                color_border = (color_inactive[0]/255.0, color_inactive[1]/255.0, color_inactive[2]/255.0, 1.00)
                color_fill   = (0.5, 0.5, 0.5, 0.2)
            
            p3d = [p0,p1,p2,p3,p0]
            contour_utilities.draw_quads_from_3dpoints(context, [p0,p1,p2,p3], color_fill)
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, color_border, 2, "GL_LINE_SMOOTH")
        
        p3d = [gvert.position for gvert in self.polystrips.gverts if not gvert.is_unconnected() and gvert.is_visible()]
        color = (color_inactive[0]/255.0, color_inactive[1]/255.0, color_inactive[2]/255.0, 1.00)
        contour_utilities.draw_3d_points(context, p3d, color, 4)
        
        if self.sel_gvert:
            color = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 1.00)
            gv = self.sel_gvert
            p0 = gv.position
            if gv.is_inner():
                p1 = gv.gedge_inner.get_outer_gvert_at(gv).position
                contour_utilities.draw_3d_points(context, [p0], color, 8)
                contour_utilities.draw_polyline_from_3dpoints(context, [p0,p1], color, 2, "GL_LINE_SMOOTH")
            else:
                p3d = [ge.get_inner_gvert_at(gv).position for ge in gv.get_gedges_notnone()]
                contour_utilities.draw_3d_points(context, [p0] + p3d, color, 8)
                for p1 in p3d:
                    contour_utilities.draw_polyline_from_3dpoints(context, [p0,p1], color, 2, "GL_LINE_SMOOTH")
        
        if self.sel_gedge:
            color = (color_selection[0]/255.0, color_selection[1]/255.0, color_selection[2]/255.0, 1.00)
            ge = self.sel_gedge
            if self.sel_gedge.is_zippered():
                p3d = [ge.gvert0.position, ge.gvert3.position]
                contour_utilities.draw_3d_points(context, p3d, color, 8)
            else:
                p3d = [gv.position for gv in ge.gverts()]
                contour_utilities.draw_3d_points(context, p3d, color, 8)
                contour_utilities.draw_polyline_from_3dpoints(context, [p3d[0], p3d[1]], color, 2, "GL_LINE_SMOOTH")
                contour_utilities.draw_polyline_from_3dpoints(context, [p3d[2], p3d[3]], color, 2, "GL_LINE_SMOOTH")
        
        if self.act_gvert:
            color = (color_active[0]/255.0, color_active[1]/255.0, color_active[2]/255.0, 1.00)
            gv = self.act_gvert
            p0 = gv.position
            contour_utilities.draw_3d_points(context, [p0], color, 8)
        
        if self.mode == 'sketch':
            contour_utilities.draw_polyline_from_points(context, [self.sketch_curpos, self.sketch[-1][0]], (0.5,0.5,0.2,0.8), 1, "GL_LINE_SMOOTH")
            contour_utilities.draw_polyline_from_points(context, [co[0] for co in self.sketch], (1,1,.5,.8), 2, "GL_LINE_SMOOTH")
            
            info = str(round(self.sketch_pressure,3))
            ''' draw text '''
            txt_width, txt_height = blf.dimensions(0, info)
            d = self.sketch_brush.pxl_rad
            blf.position(0, self.sketch_curpos[0] - txt_width/2, self.sketch_curpos[1] + d + txt_height, 0)
            blf.draw(0, info)
        
        if self.mode in {'scale tool','rotate tool'}:
            contour_utilities.draw_polyline_from_points(context, [self.action_center, self.mode_pos], (0,0,0,0.5), 1, "GL_LINE_STIPPLE")
        
        bgl.glLineWidth(1)
        
        if self.mode != 'brush scale tool':
            ray,hit = contour_utilities.ray_cast_region2d(region, r3d, self.cur_pos, self.obj, settings)
            hit_p3d,hit_norm,hit_idx = hit
            if hit_idx != -1:
                mx = self.obj.matrix_world
                hit_p3d = mx * hit_p3d
                draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
        
        self.sketch_brush.draw(context)
    
    def draw_callback_debug(self, context):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        region = context.region
        r3d = context.space_data.region_3d
        
        draw_original_strokes   = False
        draw_gedge_directions   = True
        draw_gvert_orientations = False
        draw_unconnected_gverts = False
        draw_gvert_unsnapped    = False
        draw_gedge_bezier       = False
        draw_gedge_index        = False
        draw_gedge_igverts      = False
        
        cols = [(1,.5,.5,.8),(.5,1,.5,.8),(.5,.5,1,.8),(1,1,.5,.8)]
        
        color_selected          = (.5,1,.5,.8)
        
        color_gedge             = (1,.5,.5,.8)
        color_gedge_nocuts      = (.5,.2,.2,.8)
        color_gedge_zipped      = (.5,.7,.7,.8)
        
        color_gvert_unconnected = (.2,.2,.2,.8)
        color_gvert_endpoint    = (.2,.2,.5,.8)
        color_gvert_endtoend    = (.5,.5,1,.8)
        color_gvert_ljunction   = (1,.5,1,.8)
        color_gvert_tjunction   = (1,1,.5,.8)
        color_gvert_cross       = (1,1,1,.8)
        color_gvert_midpoints   = (.7,1,.7,.8)
        
        t = time.time()
        tf = t - int(t)
        tb = tf*2 if tf < 0.5 else 2-(tf*2)
        tb1 = 1-tb
        sel_fn = lambda c: tuple(cv*tb+cs*tb1 for cv,cs in zip(c,color_selected))
        
        if draw_original_strokes:
            for stroke in self.strokes_original:
                #p3d = [pt for pt,pr in stroke]
                #contour_utilities.draw_polyline_from_3dpoints(context, p3d, (.7,.7,.7,.8), 3, "GL_LINE_SMOOTH")
                draw_circle(context, stroke[0][0], Vector((0,0,1)),0.003,(.2,.2,.2,.8))
                draw_circle(context, stroke[-1][0], Vector((0,1,0)),0.003,(.5,.5,.5,.8))
        
        
        for i_ge,gedge in enumerate(self.polystrips.gedges):
            if draw_gedge_directions:
                p0,p1,p2,p3 = gedge.gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
                n0,n1,n2,n3 = gedge.gvert0.snap_norm, gedge.gvert1.snap_norm, gedge.gvert2.snap_norm, gedge.gvert3.snap_norm
                pm = cubic_bezier_blend_t(p0,p1,p2,p3,0.5)
                px = cubic_bezier_derivative(p0,p1,p2,p3,0.5).normalized()
                pn = (n0+n3).normalized()
                py = pn.cross(px).normalized()
                rs = (gedge.gvert0.radius+gedge.gvert3.radius) * 0.35
                rl = rs * 0.75
                p3d = [pm-px*rs,pm+px*rs,pm+px*(rs-rl)+py*rl,pm+px*rs,pm+px*(rs-rl)-py*rl]
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, (0.8,0.8,0.8,0.8),1, "GL_LINE_SMOOTH")
            
            if draw_gedge_bezier:
                p0,p1,p2,p3 = gedge.gvert0.snap_pos, gedge.gvert1.snap_pos, gedge.gvert2.snap_pos, gedge.gvert3.snap_pos
                p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16.0) for t in range(17)]
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, (0.5,0.5,0.5,0.8),1, "GL_LINE_SMOOTH")
            
            col = color_gedge if len(gedge.cache_igverts) else color_gedge_nocuts
            if gedge.zip_to_gedge: col = color_gedge_zipped
            if gedge == self.sel_gedge: col = sel_fn(col)
            w = 2 if len(gedge.cache_igverts) else 5
            for c0,c1,c2,c3 in gedge.iter_segments(only_visible=True):
                contour_utilities.draw_polyline_from_3dpoints(context, [c0,c1,c2,c3,c0], col, w, "GL_LINE_SMOOTH")
            
            if draw_gedge_index:
                draw_gedge_text(gedge, context, str(i_ge))
            
            if draw_gedge_igverts:
                rm = (gedge.gvert0.radius + gedge.gvert3.radius)*0.1
                for igv in gedge.cache_igverts:
                    contour_utilities.draw_circle(context, igv.position, igv.normal, rm, (1,1,1,.3))
        
        for i_gv,gv in enumerate(self.polystrips.gverts):
            if not gv.is_visible(): continue
            p0,p1,p2,p3 = gv.get_corners()
            
            if not draw_unconnected_gverts and gv.is_unconnected() and gv != self.sel_gvert: continue
            
            col = color_gvert_unconnected
            if gv.is_endpoint(): col = color_gvert_endpoint
            elif gv.is_endtoend(): col = color_gvert_endtoend
            elif gv.is_ljunction(): col = color_gvert_ljunction
            elif gv.is_tjunction(): col = color_gvert_tjunction
            elif gv.is_cross(): col = color_gvert_cross
            
            if gv == self.sel_gvert: col = sel_fn(col)
            
            p3d = [p0,p1,p2,p3,p0]
            contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
            
            if draw_gvert_orientations:
                p,x,y = gv.snap_pos,gv.snap_tanx,gv.snap_tany
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+x*0.005], (1,0,0,1), 1, "GL_LINE_SMOOTH")
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+y*0.005], (0,1,0,1), 1, "GL_LINE_SMOOTH")
        
        if draw_gvert_unsnapped:
            for gv in self.polystrips.gverts:
                p,x,y,n = gv.position,gv.snap_tanx,gv.snap_tany,gv.snap_norm
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+x*0.01], (1,0,0,1), 1, "GL_LINE_SMOOTH")
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+y*0.01], (0,1,0,1), 1, "GL_LINE_SMOOTH")
                contour_utilities.draw_polyline_from_3dpoints(context, [p,p+n*0.01], (0,0,1,1), 1, "GL_LINE_SMOOTH")
        
        if self.sel_gedge:
            if not self.sel_gedge.zip_to_gedge:
                col = color_gvert_midpoints
                for gv in self.sel_gedge.get_inner_gverts():
                    if not gv.is_visible(): continue
                    p0,p1,p2,p3 = gv.get_corners()
                    p3d = [p0,p1,p2,p3,p0]
                    contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
            draw_gedge_info(self.sel_gedge, context)
        
        if self.sel_gvert:
            col = color_gvert_midpoints
            for ge in self.sel_gvert.get_gedges_notnone():
                if ge.zip_to_gedge: continue
                gv = ge.get_inner_gvert_at(self.sel_gvert)
                if not gv.is_visible(): continue
                p0,p1,p2,p3 = gv.get_corners()
                p3d = [p0,p1,p2,p3,p0]
                contour_utilities.draw_polyline_from_3dpoints(context, p3d, col, 2, "GL_LINE_SMOOTH")
        
        if self.mode == 'sketch':
            contour_utilities.draw_polyline_from_points(context, [self.sketch_curpos, self.sketch[-1][0]], (0.5,0.5,0.2,0.8), 1, "GL_LINE_SMOOTH")
            contour_utilities.draw_polyline_from_points(context, [co[0] for co in self.sketch], (1,1,.5,.8), 2, "GL_LINE_SMOOTH")
            
            info = str(round(self.sketch_pressure,3))
            ''' draw text '''
            txt_width, txt_height = blf.dimensions(0, info)
            d = self.sketch_brush.pxl_rad
            blf.position(0, self.sketch_curpos[0] - txt_width/2, self.sketch_curpos[1] + d + txt_height, 0)
            blf.draw(0, info)
        
            
        if self.mode in {'scale tool','rotate tool'}:
            contour_utilities.draw_polyline_from_points(context, [self.action_center, self.mode_pos], (0,0,0,0.5), 1, "GL_LINE_STIPPLE")
        
        bgl.glLineWidth(1)
        
        if self.mode != 'brush scale tool':
            ray,hit = contour_utilities.ray_cast_region2d(region, r3d, self.cur_pos, self.obj, settings)
            hit_p3d,hit_norm,hit_idx = hit
            if hit_idx != -1:
                mx = self.obj.matrix_world
                hit_p3d = mx * hit_p3d
                draw_circle(context, hit_p3d, hit_norm.normalized(), self.stroke_radius_pressure, (1,1,1,.5))
        
        self.sketch_brush.draw(context)
    
    
    def create_mesh(self, context):
        verts,quads = self.polystrips.create_mesh()
        bm = bmesh.new()
        for v in verts: bm.verts.new(v)
        for q in quads: bm.faces.new([bm.verts[i] for i in q])
        
        nm_polystrips = self.obj.name + "_polystrips"
        
        dest_me  = bpy.data.meshes.new(nm_polystrips)
        dest_obj = bpy.data.objects.new(nm_polystrips, dest_me)
        
        dest_obj.matrix_world = self.obj.matrix_world
        dest_obj.update_tag()
        dest_obj.show_all_edges = True
        dest_obj.show_wire      = True
        dest_obj.show_x_ray     = True
        
        bm.to_mesh(dest_me)
        
        context.scene.objects.link(dest_obj)
        dest_obj.select = True
        context.scene.objects.active = dest_obj
    
    
    ###########################
    # tool functions
    
    def ready_tool(self, eventd, tool_fn):
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        mx,my = eventd['mouse']
        if self.sel_gvert:
            loc   = self.sel_gvert.position
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        elif self.sel_gedge:
            loc   = (self.sel_gedge.gvert0.position + self.sel_gedge.gvert3.position) / 2.0
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        else:
            cx,cy = mx-100,my
        rad   = math.sqrt((mx-cx)**2 + (my-cy)**2)
        
        self.action_center = (cx,cy)
        self.mode_start    = (mx,my)
        self.action_radius = rad
        self.mode_radius   = rad
        
        # spc = bpy.data.window_managers['WinMan'].windows[0].screen.areas[4].spaces[0]
        # r3d = spc.region_3d
        vrot = r3d.view_rotation
        self.tool_x = (vrot * Vector((1,0,0))).normalized()
        self.tool_y = (vrot * Vector((0,1,0))).normalized()
        
        self.tool_rot = 0.0
        
        self.tool_fn = tool_fn
        self.tool_fn('init', eventd)
    
    def scale_tool_gvert(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling GVerts'
            sgv = self.sel_gvert
            lgv = [ge.gvert1 if ge.gvert0==sgv else ge.gvert2 for ge in sgv.get_gedges() if ge]
            self.tool_data = [(gv,Vector(gv.position)) for gv in lgv]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
            self.sel_gvert.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            m = command
            sgv = self.sel_gvert
            p = sgv.position
            for ge in sgv.get_gedges():
                if not ge: continue
                gv = ge.gvert1 if ge.gvert0 == self.sel_gvert else ge.gvert2
                gv.position = p + (gv.position-p) * m
                gv.update()
            sgv.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
    
    def scale_tool_gvert_radius(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling GVert radius'
            self.tool_data = self.sel_gvert.radius
        elif command == 'commit':
            pass
        elif command == 'undo':
            self.sel_gvert.radius = self.tool_data
            self.sel_gvert.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            m = command
            self.sel_gvert.radius *= m
            self.sel_gvert.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
    
    def scale_tool_stroke_radius(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling Stroke radius'
            self.tool_data = self.stroke_radius
        elif command == 'commit':
            pass
        elif command == 'undo':
            self.stroke_radius = self.tool_data
        else:
            m = command
            self.stroke_radius *= m
    
    def grab_tool_gvert(self, command, eventd):
        if command == 'init':
            self.footer = 'Translating GVert position'
            self.tool_data = self.sel_gvert.position
        elif command == 'commit':
            self.sel_gvert.update_gedges()
            pass
        elif command == 'undo':
            self.sel_gvert.position = self.tool_data
            self.sel_gvert.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
        else:
            dx,dy = command
            self.sel_gvert.position += (self.tool_x*dx + self.tool_y*dy) * self.sel_gvert.radius / 2
            self.sel_gvert.update()
            self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
    
    def grab_tool_gvert_neighbors(self, command, eventd):
        if command == 'init':
            self.footer = 'Translating GVerts positions'
            sgv = self.sel_gvert
            lgv = [ge.gvert1 if ge.gvert0==sgv else ge.gvert2 for ge in sgv.get_gedges() if ge]
            self.tool_data = [(sgv,sgv.position)] + [(gv,Vector(gv.position)) for gv in lgv]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
        else:
            dx,dy = command
            for gv,up in self.tool_data:
                gv.position += (self.tool_x*dx + self.tool_y*dy)*self.length_scale / 1000
                gv.update()
    
    def grab_tool_gedge(self, command, eventd):
        if command == 'init':
            self.footer = 'Translating GEdge positions'
            sge = self.sel_gedge
            lgv = [sge.gvert0, sge.gvert3]
            lgv += [ge.get_inner_gvert_at(gv) for gv in lgv for ge in gv.get_gedges_notnone()]
            self.tool_data = [(gv,Vector(gv.position)) for gv in lgv]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
        else:
            dx,dy = command
            for gv,up in self.tool_data:
                gv.position += (self.tool_x*dx + self.tool_y*dy)*self.length_scale / 1000
                gv.update()
    
    def rotate_tool_gvert_neighbors(self, command, eventd):
        if command == 'init':
            self.footer = 'Rotating GVerts'
            self.tool_data = [(gv,Vector(gv.position)) for gv in self.sel_gvert.get_inner_gverts()]
        elif command == 'commit':
            pass
        elif command == 'undo':
            for gv,p in self.tool_data:
                gv.position = p
                gv.update()
        else:
            ang = command
            q = Quaternion(self.sel_gvert.snap_norm, ang)
            p = self.sel_gvert.position
            for gv,up in self.tool_data:
                gv.position = p+q*(up-p)
                gv.update()
                
    def scale_brush_pixel_radius(self,command, eventd):
        if command == 'init':
            self.footer = 'Scale Brush Pixel Size'
            self.tool_data = self.stroke_radius
            x,y = eventd['mouse']
            self.sketch_brush.brush_pix_size_init(eventd['context'], x, y)
        elif command == 'commit':
            self.sketch_brush.brush_pix_size_confirm(eventd['context'])
            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
        elif command == 'undo':
            self.sketch_brush.brush_pix_size_cancel(eventd['context'])
            self.stroke_radius = self.tool_data
        else:
            x,y = command
            self.sketch_brush.brush_pix_size_interact(x, y, precise = eventd['shift'])
           
    ##############################
    # modal functions
    
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
            self.is_navigating = True
            
            x,y = eventd['mouse']
            self.sketch_brush.update_mouse_move_hover(eventd['context'], x,y)
            self.sketch_brush.make_circles()
            self.sketch_brush.get_brush_world_size(eventd['context'])
            
            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
                self.stroke_radius_pressure = self.sketch_brush.world_width
                
            return 'nav' if eventd['value']=='PRESS' else 'main'
        
        self.is_navigating = False
        return ''
        
    
    def modal_main(self, eventd):
        self.footer = ''
        
        #############################################
        # general navigation
        
        nmode = self.modal_nav(eventd)
        if nmode:
            return nmode
        
        ########################################
        # accept / cancel
        
        if eventd['press'] in {'RET', 'NUMPAD_ENTER'}:
            self.create_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'
        
        if eventd['press'] in {'ESC'}:
            eventd['context'].area.header_text_set()
            return 'cancel'
        
        
        #####################################
        # general
        
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            x,y = eventd['mouse']
            self.sketch_brush.update_mouse_move_hover(eventd['context'], x,y)
            self.sketch_brush.make_circles()
            self.sketch_brush.get_brush_world_size(eventd['context'])
            
            if self.sketch_brush.world_width:
                self.stroke_radius = self.sketch_brush.world_width
                self.stroke_radius_pressure = self.sketch_brush.world_width
            #continue?
        
        if eventd['press'] == 'F':
            self.ready_tool(eventd, self.scale_brush_pixel_radius)
            return 'brush scale tool'
        
        if eventd['press'] == 'Q':                                                  # profiler printout
            profiler.printout()
            return ''
        
        if eventd['press'] == 'P':                                                  # grease pencil => strokes
            # TODO: only convert gpencil strokes that are visible and prevent duplicate conversion
            for gpl in self.obj.grease_pencil.layers: gpl.hide = True
            for stroke in self.strokes_original:
                self.polystrips.insert_gedge_from_stroke(stroke, True)
            self.polystrips.remove_unconnected_gverts()
            self.polystrips.update_visibility(eventd['r3d'])
            return ''
        
        
        if eventd['press'] in {'LEFTMOUSE','SHIFT+LEFTMOUSE'}:                      # start sketching
            self.footer = 'Sketching'
            x,y = eventd['mouse']
            p = eventd['pressure']
            
            
            r = rad_press_mix(self.stroke_radius, p)
            #print('pressure raw: %f, radius: %f, pressure_radius %f' % (p,self.stroke_radius, r))
            self.sketch_curpos = (x,y)
            if eventd['shift'] and self.sel_gvert:
                gvx,gvy = location_3d_to_region_2d(eventd['region'], eventd['r3d'], self.sel_gvert.position)
                self.sketch = [((gvx,gvy),self.sel_gvert.radius), ((x,y),r)]
                
            else:
                self.sketch = [((x,y),r)]

                
            self.sel_gvert = None
            self.sel_gedge = None
            return 'sketch'
        
        if eventd['press'] == 'RIGHTMOUSE':                                         # picking
            x,y = eventd['mouse']
            pts = general_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
            if not pts:
                self.sel_gvert,self.sel_gedge,self.act_gvert = None,None,None
                return ''
            pt = pts[0]
            
            if self.sel_gvert or self.sel_gedge:
                # check if user is picking an inner control point
                if self.sel_gedge and not self.sel_gedge.zip_to_gedge:
                    lcpts = [self.sel_gedge.gvert1,self.sel_gedge.gvert2]
                elif self.sel_gvert:
                    sgv = self.sel_gvert
                    lge = self.sel_gvert.get_gedges()
                    lcpts = [ge.get_inner_gvert_at(sgv) for ge in lge if ge and not ge.zip_to_gedge] + [sgv]
                else:
                    lcpts = []
                
                for cpt in lcpts:
                    if not cpt.is_picked(pt): continue
                    self.sel_gvert = cpt
                    self.sel_gedge = None
                    return ''
            
            for gv in self.polystrips.gverts:
                if gv.is_unconnected(): continue
                if not gv.is_picked(pt): continue
                self.sel_gvert = gv
                self.sel_gedge = None
                return ''
            
            for ge in self.polystrips.gedges:
                if not ge.is_picked(pt): continue
                self.sel_gvert = None
                self.sel_gedge = ge
                return ''
            
            self.sel_gedge,self.sel_gvert = None,None
            return ''
        
        if eventd['press'] == 'CTRL+U':
            for gv in self.polystrips.gverts:
                gv.update_gedges()
        
        
        ###################################
        # selected gedge commands
        
        if self.sel_gedge:
            if eventd['press'] == 'X':
                self.polystrips.disconnect_gedge(self.sel_gedge)
                self.sel_gedge = None
                self.polystrips.remove_unconnected_gverts()
                return ''
            
            if eventd['press'] == 'K':
                x,y = eventd['mouse']
                pts = general_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
                if not pts:
                    return ''
                pt = pts[0]
                t,d = self.sel_gedge.get_closest_point(pt)
                self.polystrips.split_gedge_at_t(self.sel_gedge, t)
                self.sel_gedge = None
            
            if eventd['press'] == 'U':
                self.sel_gedge.gvert0.update_gedges()
                self.sel_gedge.gvert3.update_gedges()
                return ''
            
            if eventd['press']in {'CTRL+WHEELUPMOUSE', 'UP_ARROW'}:
                print('increase quads')
                self.sel_gedge.n_quads += 1
                self.sel_gedge.force_count = True
                self.sel_gedge.update()
                return ''
            
            if eventd['press'] in {'CTRL+WHEELDOWNMOUSE', 'DOWN_ARROW'}:
                print('decrease quads')
                if self.sel_gedge.n_quads > 4:
                    self.sel_gedge.n_quads -= 1
                    self.sel_gedge.force_count = True
                    self.sel_gedge.update()
                return ''
            
            if eventd['press'] == 'Z':
                if self.sel_gedge.zip_to_gedge:
                    self.sel_gedge.unzip()
                    return ''
                
                x,y = eventd['mouse']
                pts = general_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
                if not pts:
                    self.sel_gvert,self.sel_gedge = None,None
                    return ''
                pt = pts[0]
                for ge in self.polystrips.gedges:
                    if ge == self.sel_gedge: continue
                    if not ge.is_picked(pt): continue
                    self.sel_gedge.zip_to(ge)
                    return ''
                return ''
            
            if eventd['press'] == 'G':
                if not self.sel_gedge.is_zippered():
                    self.ready_tool(eventd, self.grab_tool_gedge)
                    return 'grab tool'
                return ''
            
            if eventd['press'] == 'A':
                self.sel_gvert = self.sel_gedge.gvert0
                self.sel_gedge = None
            if eventd['press'] == 'B':
                self.sel_gvert = self.sel_gedge.gvert3
                self.sel_gedge = None
        
        
        ###################################
        # selected gvert commands
        
        if self.sel_gvert:
            
            if eventd['press'] == 'X':
                self.polystrips.disconnect_gvert(self.sel_gvert)
                self.sel_gvert = None
                self.polystrips.remove_unconnected_gverts()
                return ''
            
            if eventd['press'] == 'CTRL+D':
                self.polystrips.dissolve_gvert(self.sel_gvert)
                self.sel_gvert = None
                self.polystrips.remove_unconnected_gverts()
                self.polystrips.update_visibility(eventd['r3d'])
                return ''
            
            if eventd['press'] == 'S':
                self.ready_tool(eventd, self.scale_tool_gvert_radius)
                return 'scale tool'
            
            
            if eventd['press'] == 'CTRL+G':
                self.ready_tool(eventd, self.grab_tool_gvert)
                return 'grab tool'
            
            if eventd['press'] == 'G':
                self.ready_tool(eventd, self.grab_tool_gvert_neighbors)
                return 'grab tool'
            
            
            if eventd['press'] == 'CTRL+C':
                self.sel_gvert.toggle_corner()
                self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
                return ''
            
            
            if eventd['press'] == 'CTRL+S':
                self.ready_tool(eventd, self.scale_tool_gvert)
                return 'scale tool'
            
            if eventd['press'] == 'C':
                self.sel_gvert.smooth()
                self.sel_gvert.update_visibility(eventd['r3d'], update_gedges=True)
                return ''
            
            if eventd['press'] == 'R':
                self.ready_tool(eventd, self.rotate_tool_gvert_neighbors)
                return 'rotate tool'
            
            if eventd['press'] == 'U':
                self.sel_gvert.update_gedges()
                return ''
            
            if eventd['press'] == 'CTRL+R':
                self.polystrips.rip_gvert(self.sel_gvert)
                self.sel_gvert = None
                return ''
            
            if self.sel_gvert.zip_over_gedge:
                gvthis = self.sel_gvert
                gvthat = self.sel_gvert.get_zip_pair()
                
                if eventd['press'] == 'CTRL+NUMPAD_PLUS':
                    max_t = 1 if gvthis.zip_t>gvthat.zip_t else gvthat.zip_t-0.05
                    gvthis.zip_t = min(gvthis.zip_t+0.05, max_t)
                    gvthis.zip_over_gedge.update()
                    dprint('+ %f %f' % (min(gvthis.zip_t, gvthat.zip_t),max(gvthis.zip_t, gvthat.zip_t)), l=4)
                    return ''
                
                if eventd['press'] == 'CTRL+NUMPAD_MINUS':
                    min_t = 0 if gvthis.zip_t<gvthat.zip_t else gvthat.zip_t+0.05
                    gvthis.zip_t = max(gvthis.zip_t-0.05, min_t)
                    gvthis.zip_over_gedge.update()
                    dprint('- %f %f' % (min(gvthis.zip_t, gvthat.zip_t),max(gvthis.zip_t, gvthat.zip_t)), l=4)
                    return ''
                
        return ''
    
    
    def modal_sketching(self, eventd):
        #my_str = eventd['type'] + ' ' + str(round(eventd['pressure'],2)) + ' ' + str(round(self.stroke_radius_pressure,2))
        #print(my_str)
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            p = eventd['pressure']
            stroke_point = self.sketch[-1]

            (lx, ly) = stroke_point[0]
            lr = stroke_point[1]
            self.sketch_curpos = (x,y)
            self.sketch_pressure = p

            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            r = rad_press_mix(self.stroke_radius, self.sketch_pressure)
            #smooth radii
            self.stroke_radius_pressure = lr*ss0 + r*ss1
            
            self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), self.stroke_radius_pressure)]
            
            
            return ''
        
        if eventd['release'] in {'LEFTMOUSE','SHIFT+LEFTMOUSE'}:
            #correct for 0 pressure on release
            if self.sketch[-1][1] == 0:
                self.sketch[-1] = self.sketch[-2]
                
            p3d = general_utilities.ray_cast_stroke(eventd['context'], self.obj, self.sketch) if len(self.sketch) > 1 else []
            if len(p3d) <= 1: return 'main'
            
            # tessellate stroke (if needed) so we have good stroke sampling
            #TODO, tesselate pressure/radius values?
            #length_tess = self.length_scale / 700
            #p3d = [(p0+(p1-p0).normalized()*x) for p0,p1 in zip(p3d[:-1],p3d[1:]) for x in frange(0,(p0-p1).length,length_tess)] + [p3d[-1]]
            #stroke = [(p,self.stroke_radius) for i,p in enumerate(p3d)]
            
            stroke = p3d
            self.sketch = []
            dprint('')
            dprint('')
            dprint('inserting stroke')
            self.polystrips.insert_gedge_from_stroke(stroke, False)
            self.polystrips.remove_unconnected_gverts()
            self.polystrips.update_visibility(eventd['r3d'])
            return 'main'
        
        return ''
    
    
    def modal_scale_tool(self, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        ar = self.action_radius
        pr = self.mode_radius
        cr = math.sqrt((mx-cx)**2 + (my-cy)**2)
        
        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'
        
        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'
        
        if eventd['type'] == 'MOUSEMOVE':
            self.tool_fn(cr / pr, eventd)
            self.mode_radius = cr
            return ''
        
        return ''
    
    def modal_grab_tool(self, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        px,py = self.mode_pos
        sx,sy = self.mode_start
        
        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'
        
        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'
        
        if eventd['type'] == 'MOUSEMOVE':
            self.tool_fn((mx-px,my-py), eventd)
            return ''
        
        return ''
    
    def modal_rotate_tool(self, eventd):
        cx,cy = self.action_center
        mx,my = eventd['mouse']
        px,py = self.mode_pos
        
        if eventd['press'] in {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'
        
        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            return 'main'
        
        if eventd['type'] == 'MOUSEMOVE':
            vp = Vector((px-cx,py-cy,0))
            vm = Vector((mx-cx,my-cy,0))
            ang = vp.angle(vm) * (-1 if vp.cross(vm).z<0 else 1)
            self.tool_rot += ang
            self.tool_fn(self.tool_rot, eventd)
            return ''
        
        return ''
    
    def modal_scale_brush_pixel_tool(self, eventd):
        '''
        This is the pixel brush radius
        self.tool_fn is expected to be self.
        '''
        mx,my = eventd['mouse']

        if eventd['press'] in {'RET','NUMPAD_ENTER','LEFTMOUSE'}:
            self.tool_fn('commit', eventd)
            return 'main'
        
        if eventd['press'] in {'ESC', 'RIGHTMOUSE'}:
            self.tool_fn('undo', eventd)
            
            return 'main'
        
        if eventd['type'] == 'MOUSEMOVE':
            '''
            '''
            self.tool_fn((mx,my), eventd)
            
            return ''
        
        return ''
        
        
    def modal(self, context, event):
        context.area.tag_redraw()
        settings = context.user_preferences.addons[AL.FolderName].preferences
        
        eventd = self.get_event_details(context, event)
        
        if self.footer_last != self.footer:
            context.area.header_text_set('PolyStrips: %s' % self.footer)
            self.footer_last = self.footer
        
        FSM = {}
        FSM['main']         = self.modal_main
        FSM['nav']          = self.modal_nav
        FSM['sketch']       = self.modal_sketching
        FSM['scale tool']   = self.modal_scale_tool
        FSM['grab tool']    = self.modal_grab_tool
        FSM['rotate tool']  = self.modal_rotate_tool
        FSM['brush scale tool'] = self.modal_scale_brush_pixel_tool
        
        self.cur_pos = eventd['mouse']
        nmode = FSM[self.mode](eventd)
        self.mode_pos = eventd['mouse']
        
        self.is_navigating = (nmode == 'nav')
        if nmode == 'nav': return {'PASS_THROUGH'}
        
        if nmode in {'finish','cancel'}:
            self.kill_timer(context)
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
    
    def kill_timer(self, context):
        if not self._timer: return
        context.window_manager.event_timer_remove(self._timer)
        self._timer = None
    
    def invoke(self, context, event):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        #return {'CANCELLED'}
        #return {'RUNNING_MODAL'}
        
        self.mode = 'main'
        self.mode_pos      = (0,0)
        self.cur_pos       = (0,0)
        self.mode_radius   = 0
        self.action_center = (0,0)
        self.action_radius = 0
        self.is_navigating = False
        self.sketch_curpos = (0,0)
        self.sketch_pressure = 1
        self.sketch = []
        
        self.post_update = True
        
        self.footer = ''
        self.footer_last = ''
        
        self.last_matrix = None
        
        self._timer = context.window_manager.event_timer_add(0.1, context.window)
        
        self.stroke_smoothing = 0.5          # 0: no smoothing. 1: no change
        
        self.obj = context.object
        self.scale = self.obj.scale[0]
        self.length_scale = get_object_length_scale(self.obj)
        
        self.me = self.obj.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
        self.me.update()
        self.bme = bmesh.new()
        self.bme.from_mesh(self.me)
        
        #world stroke radius
        self.stroke_radius = 0.01 * self.length_scale
        self.stroke_radius_pressure = 0.01 * self.length_scale
        #screen_stroke_radius
        self.screen_stroke_radius = 20 #TODO, hood to settings
        
        self.sketch_brush = SketchBrush(context, 
                                        settings, 
                                        event.mouse_region_x, event.mouse_region_y, 
                                        settings.quad_prev_radius, 
                                        self.obj)
        
        self.sel_gedge = None                           # selected gedge
        self.sel_gvert = None                           # selected gvert
        self.act_gvert = None                           # active gvert (operated upon)
        
        self.polystrips = PolyStrips(context, self.obj)
        
        if self.obj.grease_pencil:
            self.create_polystrips_from_greasepencil()
        elif 'BezierCurve' in bpy.data.objects:
            self.create_polystrips_from_bezier(bpy.data.objects['BezierCurve'])
        
        context.area.header_text_set('PolyStrips')
        
        return {'RUNNING_MODAL'}
