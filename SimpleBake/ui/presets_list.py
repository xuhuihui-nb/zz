import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, PropertyGroup, UIList
from bpy.props import EnumProperty

import os
from pathlib import Path

class SIMPLEBAKE_UL_Presets_List(UIList):
    """UIList."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):

        # We could write some code to decide which icon to use here...
        custom_icon = 'PACKAGE'

        # Make sure your code supports all 3 layout types
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name, icon = custom_icon)

        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon = custom_icon) 

class SimpleBake_OT_preset_refresh(Operator):
    """Refresh list of SimpleBake presets"""
    bl_idname = "simplebake.preset_refresh"
    bl_label = "Refresh"
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        sbp.presets_list.clear()
        
        p = Path(bpy.utils.script_path_user())
        p = p.parents[1]
        p = p /  "data" / "SimpleBake"

        try:
            presets = sorted(os.listdir(str(p)))
            presets = [pr for pr in presets if not os.path.isdir(str(p / pr))]
        except Exception as e:
            print(repr(e))
            self.report({"INFO"}, "No presets found")
            return {'CANCELLED'}

        if len(presets) == 0:
            self.report({"INFO"}, "No presets found")
            return {'CANCELLED'}
            
        for preset in presets:
            #List should be clear
            i = sbp.presets_list.add()
            i.name = preset
        
        return {'FINISHED'} 

class SimpleBake_OT_preset_delete(Operator):
    """Delete selected SimpleBake preset"""
    bl_idname = "simplebake.preset_delete"
    bl_label = "Delete"
    
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        try:
            sbp.presets_list[sbp.presets_list_index].name
            return True
        except:
            return False

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        p = Path(bpy.utils.script_path_user())
        p = p.parents[1]
        p = p /  "data" / "SimpleBake"
        
        index = sbp.presets_list_index
        item = sbp.presets_list[index]
        p = p / item.name
        
        os.remove(str(p))
        
        #Refreh the list
        
        bpy.ops.simplebake.preset_refresh()
            
        return {'FINISHED'} 


classes = ([
    SIMPLEBAKE_UL_Presets_List,
    SimpleBake_OT_preset_refresh,
    SimpleBake_OT_preset_delete
        ])

def register():
    global classes
    for cls in classes:
        try:
            unregister_class(cls)
        except Exception:
            pass
        try:
            register_class(cls)
        except Exception as e:
            pass

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)
