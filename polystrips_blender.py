'''
Copyright (C) 2014 CG Cookie
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

bl_info = {
    "name": "Polystrips Retopology Tool",
    "description": "A tool to retopologize forms quickly.",
    "author": "Patrick Moore",
    "version": (1, 1, 0),
    "blender": (2, 7, 1),
    "location": "View 3D > Tool Shelf",
    "warning": '',  # used for warning icon and text in addons panel
    "wiki_url": "http://cgcookie.com/blender/docs/contour-retopology/",
    "tracker_url": "https://github.com/CGCookie/retopology/issues?labels=Bug&milestone=1&state=open",
    "category": "3D View"
    }

# Add the current __file__ path to the search path
import sys,os
sys.path.append(os.path.dirname(__file__))

import bpy
import bmesh
import blf
import math
import sys
import copy
import time
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d
import contour_utilities, general_utilities
from contour_classes import ContourCutLine, ExistingVertList, CutLineManipulatorWidget, PolySkecthLine, ContourCutSeries, ContourStatePreserver
from mathutils.geometry import intersect_line_plane, intersect_point_line
from bpy.props import EnumProperty, StringProperty,BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences

from polystrips_ui import PolystripsUI


# Create a class that contains all location information for addons
AL = general_utilities.AddonLocator()


class PolystripsToolsAddonPreferences(AddonPreferences):
    bl_idname = __name__
    
    theme = IntProperty(
        name='Theme',
        description='Color theme to use',
        default=2,
        min=0,
        max=2
        )
    
    def draw(self, context):
        layout = self.layout
        
        row = layout.row(align=True)
        row.prop(self, "theme")



class CGCOOKIE_OT_retopo_polystrips_panel(bpy.types.Panel):
    '''Retopologize Forms with polygon strips'''
    bl_category = "Retopology"
    bl_label = "Polystrips Retopology"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    @classmethod
    def poll(cls, context):
        mode = bpy.context.mode
        obj = context.active_object
        return (obj and obj.type == 'MESH' and mode in ('OBJECT', 'EDIT_MESH'))
    
    def draw(self, context):
        layout = self.layout
        box = layout.box()
        
        if 'EDIT' in context.mode and len(context.selected_objects) != 2:
            col = box.column()
            col.label(text='No 2nd Object!')
        col = box.column()
        col.operator("cgcookie.polystrips", icon="MESH_UVSPHERE")


class CGCOOKIE_OT_polystrips(bpy.types.Operator):
    bl_idname = "cgcookie.polystrips"
    bl_label  = "Polystrips"
    
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
    
    def draw_callback(self, context):
        return self.ui.draw_callback(context)
    
    def modal(self, context, event):
        ret = self.ui.modal(context, event)
        if 'FINISHED' in ret or 'CANCELLED' in ret:
            contour_utilities.callback_cleanup(self, context)
        return ret
    
    def invoke(self, context, event):
        self.ui = PolystripsUI(context, event)
        
        # switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (context, ), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(PolystripsToolsAddonPreferences)
    bpy.utils.register_class(CGCOOKIE_OT_retopo_polystrips_panel)
    bpy.utils.register_class(CGCOOKIE_OT_polystrips)

def unregister():
    bpy.utils.unregister_class(PolystripsToolsAddonPreferences)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopo_polystrips_panel)
    bpy.utils.unregister_class(CGCOOKIE_OT_polystrips)
