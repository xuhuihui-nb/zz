import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, PropertyGroup, UIList
from bpy.props import EnumProperty

def find_existing_local_presets(context):
    """
    Returns a list of all existing SimpleBake local presets
    """
    sbp = context.scene.SimpleBake_Props

    #Get existing presets
    existing_presets = []
    for k in list(sbp.keys()):
        if k.startswith("SB_local_preset_"):
            existing_presets.append(k.replace("SB_local_preset_", ""))

    existing_presets = sorted(existing_presets)

    return existing_presets

def del_preset(context, all=False, friendly_name=""):
    """
    Deletes either a specified preset or all presets
    """
    sbp = context.scene.SimpleBake_Props

    del_list = []
    name = "SB_local_preset_" if all else f"SB_local_preset_{friendly_name}"

    for k in list(sbp.keys()):
        if k == name:
            del_list.append(k)
    for d in del_list:
        del sbp[d]


class SIMPLEBAKE_UL_Local_Presets_List(UIList):
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

class SimpleBake_OT_local_preset_refresh(Operator):
    """Refresh list of local SimpleBake presets"""
    bl_idname = "simplebake.local_preset_refresh"
    bl_label = "Local Refresh"
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        sbp.local_presets_list.clear()
            
        for preset in find_existing_local_presets(context):
            #List should be clear
            i = sbp.local_presets_list.add()
            i.name = preset
        
        return {'FINISHED'} 

class SimpleBake_OT_local_preset_delete(Operator):
    """Delete selected SimpleBake preset"""
    bl_idname = "simplebake.local_preset_delete"
    bl_label = "Delete local preset"
    
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        try:
            sbp.local_presets_list[sbp.local_presets_list_index].name
            return True
        except:
            return False

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        index = sbp.local_presets_list_index
        item = sbp.local_presets_list[index]
        del_preset(context, friendly_name = item.name)

        #Refreh the list
        
        bpy.ops.simplebake.local_preset_refresh()

            
        return {'FINISHED'} 


classes = ([
    SIMPLEBAKE_UL_Local_Presets_List,
    SimpleBake_OT_local_preset_refresh,
    SimpleBake_OT_local_preset_delete
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
