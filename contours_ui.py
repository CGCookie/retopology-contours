'''
Created on Jul 19, 2014

@author: Patrick
'''
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
import random
import time
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d
import contour_utilities, general_utilities
from contour_classes import ContourCutLine, ExistingVertList, CutLineManipulatorWidget, PolySkecthLine, ContourCutSeries, ContourStatePreserver
from mathutils.geometry import intersect_line_plane, intersect_point_line
from bpy.props import EnumProperty, StringProperty,BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences


# Create a class that contains all location information for addons
AL = general_utilities.AddonLocator()

#a place to store strokes for later
global contour_cache
contour_cache = {}
#store any temporary triangulated objects
#store the bmesh to prevent recalcing bmesh
#each time
global contour_mesh_cache
contour_mesh_cache = {}
#TODO move this over to shared utilities
def object_validation(ob):
    me = ob.data
    
    # get object data to act as a hash
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
    bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
    vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
    
    return (ob.name, counts, bbox, vsum)

def is_object_valid(ob):
    global contour_mesh_cache
    if 'valid' not in contour_mesh_cache: return False
    return contour_mesh_cache['valid'] == object_validation(ob)

def write_mesh_cache(orig_ob,tmp_ob, bme):
    print('writing mesh cache')
    global contour_mesh_cache
    clear_mesh_cache()
    contour_mesh_cache['valid'] = object_validation(orig_ob)
    contour_mesh_cache['bme'] = bme
    contour_mesh_cache['tmp'] = tmp_ob
    
def clear_mesh_cache():
    print('clearing mesh cache')
    
    global contour_mesh_cache
    
    if 'valid' in contour_mesh_cache and contour_mesh_cache['valid']:
        del contour_mesh_cache['valid']
        
    if 'bme' in contour_mesh_cache and contour_mesh_cache['bme']:
        bme_old = contour_mesh_cache['bme']
        bme_old.free()
        del contour_mesh_cache['bme']
    
    if 'tmp' in contour_mesh_cache and contour_mesh_cache['tmp']:
        old_obj = contour_mesh_cache['tmp']
        #context.scene.objects.unlink(self.tmp_ob)
        old_me = old_obj.data
        old_obj.user_clear()
        if old_obj and old_obj.name in bpy.data.objects:
            bpy.data.objects.remove(old_obj)
        if old_me and old_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(old_me)
        del contour_mesh_cache['tmp']
        
           
class CGCOOKIE_OT_contours_rf(bpy.types.Operator):
    bl_idname = "cgcookie.contours_rf"
    bl_label  = "Contours RF"
    
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
        
        region = context.region
        font_id = 0
        # draw some text
        blf.position(font_id, region.width/2, region.height/2, 0)
        blf.size(font_id, 20, 72)
        blf.draw(font_id, "Hello Word " + self.footer)
    
    
    def create_mesh(self, context):
        print('create it')
    
    
    ###########################
    # tool functions
    
    def ready_tool(self, eventd, tool_fn):
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        mx,my = eventd['mouse']
        if self.sel_gvert:
            loc   = self.sel_gvert.position
            cx,cy = location_3d_to_region_2d(rgn, r3d, loc)
        elif self.sel_gvert:
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
    
    def scale_tool(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling'
            self.tool_data = None
            
        elif command == 'commit':
            pass
        elif command == 'undo':
            #put tool data back
            print('undo me')
        else:
            m = command
            print(m)
            #do the things related to comanding
            
    
    def scale_tool_radius(self, command, eventd):
        if command == 'init':
            self.footer = 'Scaling radius'
            self.tool_data = None
        elif command == 'commit':
            pass
        elif command == 'undo':
            #put tool data back
            print('undo me')
        else:
            m = command
            print(m)
            #do the things related to comanding
    
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
    
    def grab_tool(self, command, eventd):
        if command == 'init':
            self.footer = 'Translating'
            self.tool_data = None
        elif command == 'commit':
            print('we did it')
            pass
        elif command == 'undo':
            print('undo it')
        else:
            dx,dy = command
            #some_position += (self.tool_x*dx + self.tool_y*dy) * self.sel_gvert.radius / 2
            
    def grab_tool_neighbors(self, command, eventd):
        if command == 'init':
            self.footer = 'Translating with neighbors'
            self.tool_data = None
        elif command == 'commit':
            pass
        elif command == 'undo':
            print('undo')
        else:
            dx,dy = command
            #for some_position in self.tool_data:
                #some_position += (self.tool_x*dx + self.tool_y*dy)*self.length_scale / 1000
    
    def rotate_tool_neighbors(self, command, eventd):
        if command == 'init':
            self.footer = 'Rotating with neighbors'
            #self.tool_data = list of initial positions or rotations[(gv,Vector(gv.position)) for gv in self.sel_gvert.get_inner_gverts()]
        elif command == 'commit':
            pass
        elif command == 'undo':
            print('cancel')
            #put the data back
        else:
            print('rotating')
            #ang = command
            #q = Quaternion(self.sel_gvert.snap_norm, ang)
            #p = self.sel_gvert.position
            #for gv,up in self.tool_data:
                #gv.position = p+q*(up-p)
                #gv.update()
                
    def scale_brush_pixel_radius(self,command, eventd):
        if command == 'init':
            self.footer = 'Scale Brush Pixel Size'
            #self.tool_data = self.stroke_radius
            #x,y = eventd['mouse']
            #self.sketch_brush.brush_pix_size_init(eventd['context'], x, y)
        elif command == 'commit':
            print('confirm')
            
        elif command == 'undo':
            print('undo')
            
        else:
            print('interact with brush')
            #x,y = command
            #self.sketch_brush.brush_pix_size_interact(x, y, precise = eventd['shift'])
           
    ##############################
    # modal functions
    
    def modal_nav(self, eventd):
        events_nav = self.keymap['navigate']
        handle_nav = False
        handle_nav |= eventd['ftype'] in events_nav
        handle_nav |= eventd['type'] == 'MOUSEMOVE' and self.is_navigating
        
        if handle_nav:
            self.post_update = True
            self.is_navigating = True
            self.footer = 'NAV'
            return 'nav' if eventd['value']=='PRESS' else self.mode_last
        
        self.is_navigating = False
        return ''
        
    
    def modal_loop(self, eventd): 
        self.footer = 'Loop Mode'
        
        #############################################
        # general navigation
        
        nmode = self.modal_nav(eventd)
        if nmode:
            self.mode_last = 'main loop'
            return nmode
        
        ########################################
        # accept / cancel hard coded
        
        if eventd['press'] in {'RET', 'NUMPAD_ENTER'}:
            self.create_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'
        
        if eventd['press'] in {'ESC'}:
            eventd['context'].area.header_text_set()
            return 'cancel'
        
        
        #####################################
        # general, non modal commands
        if eventd['press'] in self.keymap['mode']:
            self.footer = 'Guide Mode'
            return 'main guide'
     
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            print('hover')
        
        
        
        if eventd['press'] in self.keymap['select']: # selection
            x,y = eventd['mouse']
            
            return ''
        
   
        if eventd['press'] in self.keymap['action']:   # start cutting
            self.footer = 'Cutting'
            x,y = eventd['mouse']
            p = eventd['pressure']
                
            return 'cutting'
        
        if eventd['press'] in self.keymap['new']:
            self.force_new = self.force_new != True
            return ''
        ###################################
        # selected contour loop commands
        
        if self.sel_loop:
            if eventd['press'] in self.keymap['delete']:
                self.sel_loop = None
                return ''
            
            if eventd['press'] in self.keymap['scale']:
                self.ready_tool(eventd, self.scale_tool)
                return 'scale tool'
        
            if eventd['press'] in self.keymap['translate']:
                self.ready_tool(eventd, self.grab_tool)
                return 'grab tool'
            
            if eventd['press'] in self.keymap['rotate']:
                self.ready_tool(eventd, self.rotate_tool_neighbors)
                return 'rotate tool'
            
            if eventd['press'] in self.keymap['align']:
                print('align')
                return ''
            
            if eventd['press'] in self.keymap['shift']:
                print('shift')
                return ''
            
            if eventd['press'] in self.keymap['up count']:
                print('up count')
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                print('down count')
                return ''
            
            if eventd['press'] in self.keymap['rotate']:
                self.ready_tool(eventd, self.rotate_tool_neighbors)
                return ''
                
        return ''
    
    
    def modal_guide(self, eventd):
        self.footer = 'Guide Mode'
        #############################################
        # general navigation
         
        nmode = self.modal_nav(eventd)
        if nmode:
            self.mode_last = 'main guide'
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
         
         
        if eventd['press'] in self.keymap['mode']:
            return 'main loop'
         
        if eventd['press'] in self.keymap['new']:
            self.force_new = self.force_new != True
            return '' 
        #####################################
        # general, non modal commands
         
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            print('hover')
            return ''
         
        if eventd['press'] in self.keymap['action']: #start sketching
            self.footer = 'sketching'
            x,y = eventd['mouse']
            p = eventd['pressure']
             
            return 'sketching'
         
        if eventd['press'] in self.keymap['select']: # selection
            x,y = eventd['mouse']
             
            return ''
         
    
        ###################################
        # selected contour segment commands
         
        if self.sel_path:
            if eventd['press'] in self.keymap['delete']:
                print('delete')
                self.sel_path = None
                return ''
            
            if eventd['press'] in self.keymap['shift']:
                print('shift')
                return ''
            
            if eventd['press'] in self.keymap['up count']:
                print('up count')
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                print('down count')
                return ''
             
        return ''
    
    def modal_cut(self, eventd):
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            p = eventd['pressure']
            print((x,y))            
            return ''
        
        if eventd['release'] in self.keymap['action']:
            print('new cut made')
            
            return 'main loop'
        
    def modal_sketching(self, eventd):

        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            p = eventd['pressure']
            stroke_point = self.sketch[-1]

            (lx, ly) = stroke_point[0]
            lp = stroke_point[1]
            
            self.sketch_curpos = (x,y)
            self.sketch_pressure = p
            
            #on the fly, backwards facing, smoothing
            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), lp*ss0 + p*ss1)]
                        
            return ''
        
        if eventd['release'] in {'LEFTMOUSE','SHIFT+LEFTMOUSE'}:  #why shift?
            #correct for 0 pressure on release
            if self.sketch[-1][1] == 0:
                self.sketch[-1] = self.sketch[-2]
                
            #p3d = general_utilities.ray_cast_stroke(eventd['context'], self.obj, self.sketch) if len(self.sketch) > 1 else []
            #if len(p3d) <= 1: return 'main'
            
            # tessellate stroke (if needed) so we have good stroke sampling
            #TODO, tesselate pressure/radius values?
            #length_tess = self.length_scale / 700
            #p3d = [(p0+(p1-p0).normalized()*x) for p0,p1 in zip(p3d[:-1],p3d[1:]) for x in frange(0,(p0-p1).length,length_tess)] + [p3d[-1]]
            #stroke = [(p,self.stroke_radius) for i,p in enumerate(p3d)]
            
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
            context.area.header_text_set('Contours: %s' % self.footer)
            self.footer_last = self.footer
        
        FSM = {}
        FSM['main loop']    = self.modal_loop
        FSM['main guide']   = self.modal_guide
        FSM['nav']          = self.modal_nav
        FSM['cutting']      = self.modal_cut
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
            contour_utilities.callback_cleanup(self, context)
            self.kill_timer(context)
            return {'FINISHED'} if nmode == 'finish' else {'CANCELLED'}
        
        if nmode: self.mode = nmode
        
        return {'RUNNING_MODAL'}
    
    def kill_timer(self, context):
        if not self._timer: return
        context.window_manager.event_timer_remove(self._timer)
        self._timer = None
    
    
    def new_destination_obj(self,context,name, mx):
        '''
        creates new object for mesh data to enter
        '''
        dest_me = bpy.data.meshes.new(name)
        dest_ob = bpy.data.objects.new(name,dest_me) #this is an empty currently
        dest_ob.matrix_world = mx
        dest_ob.update_tag()
        dest_bme = bmesh.new()
        dest_bme.from_mesh(dest_me)
        
        return dest_ob, dest_me, dest_bme
        
        
    def tmp_obj_and_triangulate(self,context, bme, ngons, mx):
        '''
        ob -  input object
        bme - bmesh extracted from input object <- this will be modified by triangulation
        ngons - list of bmesh faces that are ngons
        '''
        
        if len(ngons):
            new_geom = bmesh.ops.triangulate(bme, faces = ngons, quad_method=0, ngon_method=1)
            new_faces = new_geom['faces']

        new_me = bpy.data.meshes.new('tmp_recontour_mesh')
        bme.to_mesh(new_me)
        new_me.update()
        tmp_ob = bpy.data.objects.new('ContourTMP', new_me)
        
        #ob must be linked to scene for ray casting?
        context.scene.objects.link(tmp_ob)
        tmp_ob.update_tag()
        context.scene.update()
        #however it can be unlinked to prevent user from seeing it?
        context.scene.objects.unlink(tmp_ob)
        tmp_ob.matrix_world = mx
        
        return tmp_ob
    
    def mesh_data_gather_object_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.sel_edge = None
        self.sel_verts = None
        self.existing_cut = None
        ob = context.object
        tmp_ob = None
        
        name = ob.name + '_recontour'
        self.dest_ob, self.dest_me, self.dest_bme = self.new_destination_obj(context, name, ob.matrix_world)
        
        
        is_valid = is_object_valid(context.object)
        has_tmp = 'ContourTMP' in bpy.data.objects and bpy.data.objects['ContourTMP'].data
        
        
        if is_valid and has_tmp:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
            
        else:
            clear_mesh_cache()
            
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob= self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
                
        if tmp_ob:
            self.orignal_form = tmp_ob
        else:
            self.orignal_form = ob
        
        self.tmp_ob = tmp_ob
        
    def mesh_data_gather_edit_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.dest_ob = context.object        
        self.dest_me = self.dest_ob.data
        self.dest_bme = bmesh.from_edit_mesh(self.dest_me)
        
        ob = [obj for obj in context.selected_objects if obj.name != context.object.name][0]
        is_valid = is_object_valid(ob)
        if is_valid:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
        else:
            clear_mesh_cache()
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob = self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
        
        if tmp_ob:
            self.orignal_form = tmp_ob
        else:
            self.orignal_form = ob
        
        self.tmp_ob = tmp_ob
        
        #count and collect the selected edges if any
        ed_inds = [ed.index for ed in self.dest_bme.edges if ed.select]
        
        self.existing_loops = []
        if len(ed_inds):
            vert_loops = contour_utilities.edge_loops_from_bmedges(self.dest_bme, ed_inds)

            if len(vert_loops) > 1:
                self.report({'WARNING'}, 'Only one edge loop will be used for extension')
            print('there are %i edge loops selected' % len(vert_loops))
            
            #for loop in vert_loops:
            #until multi loops are supported, do this    
            loop = vert_loops[0]
            if loop[-1] != loop[0] and len(list(set(loop))) != len(loop):
                self.report({'WARNING'},'Edge loop selection has extra parts!  Excluding this loop')
                
            else:
                lverts = [self.dest_bme.verts[i] for i in loop]
                
                existing_loop =ExistingVertList(context,
                                                lverts, 
                                                loop, 
                                                self.dest_ob.matrix_world,
                                                key_type = 'INDS')
                
                #make a blank path with just an existing head
                path = ContourCutSeries(context, [],
                                cull_factor = self.settings.cull_factor, 
                                smooth_factor = self.settings.smooth_factor,
                                feature_factor = self.settings.feature_factor)
            
                
                path.existing_head = existing_loop
                path.seg_lock = False
                path.ring_lock = True
                path.ring_segments = len(existing_loop.verts_simple)
                path.connect_cuts_to_make_mesh(ob)
                path.update_visibility(context, ob)
            
                #path.update_visibility(context, self.original_form)
                
                self.cut_paths.append(path)
                self.existing_loops.append(existing_loop)
                    
                    
    def invoke(self, context, event):
        settings = context.user_preferences.addons[AL.FolderName].preferences
        self.settings = settings
        self.keymap = contour_utilities.contour_keymap_generate()
        self.mode = 'main loop'
        self.mode_last = 'main loop'
        
        self.is_navigating = False
        self.force_new = False
        self.post_update = True
        
        
        self.mode_pos      = (0,0)
        self.cur_pos       = (0,0)
        self.mode_radius   = 0
        self.action_center = (0,0)
        self.action_radius = 0
        self.sketch_curpos = (0,0)
        self.sketch_pressure = 1
        self.sketch = []
        
        self.footer = ''
        self.footer_last = ''
        
        self.last_matrix = None
        
        self._timer = context.window_manager.event_timer_add(0.1, context.window)
        
        self.stroke_smoothing = 0.5          # 0: no smoothing. 1: no change
        
        if context.mode == 'OBJECT':
            #self.bme, self.dest_bme, self.dest_ob, self.original_form etc are all defined inside
            self.mesh_data_gather_object_mode(context)
        elif context.mode == 'EDIT':
            self.mesh_data_gather_object_mode(context)
            
        
        #here is where we will cache verts edges and faces
        #unti lthe user confirms and we output a real mesh.
        self.verts = []
        self.edges = []
        self.faces = []
        
        self.cuts = []
        self.cut_paths = []    
       
        if settings.use_x_ray:
            self.orig_x_ray = self.destination_ob.show_x_ray
            self.destination_ob.show_x_ray = True     
            

        
        #does the user want to extend an existing cut or make a new segment
        
        
        
        #potential item for snapping in 
        self.snap = []
        self.snap_circle = []
        self.snap_color = (1,0,0,1)
        
        #what is the mouse over top of currently
        self.hover_target = None
        #keep track of selected cut_line and path
        self.sel_loop = None   #TODO: Change this to selected_loop
        if len(self.cut_paths) == 0:
            self.sel_path = None   #TODO: change this to selected_segment
        else:
            print('there is a selected_path')
            self.sel_path = self.cut_paths[-1] #this would be an existing path from selected geom in editmode
        
        self.cut_line_widget = None  #An object of Class "CutLineManipulator" or None
        self.widget_interaction = False  #Being in the state of interacting with a widget o
        self.hot_key = None  #Keep track of which hotkey was pressed
        self.draw = False  #Being in the state of drawing a guide stroke
        
        self.loop_msg = 'LOOP MODE:  LMB: Select Stroke, X: Delete Sroke, , G: Translate, R: Rotate, Ctrl/Shift + A: Align, S: Cursor to Stroke, C: View to Cursor, N: Force New Segment, TAB: toggle Guide mode'
        self.guide_msg = 'GUIDE MODE: LMB to Draw or Select, Ctrl/Shift/ALT + S to smooth, WHEEL or +/- to increase/decrease segments, TAB: toggle Loop mode'
        context.area.header_text_set(self.loop_msg)
        
        if settings.recover and is_valid:
            print('loading cache!')
            self.undo_action()
            
        else:
            contour_undo_cache = []
            
        #timer for temporary messages
        self._timer = None
        self.msg_start_time = time.time()
        self.msg_duration = .75
        
        context.area.header_text_set('Contours')
        
        # switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (context, ), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}