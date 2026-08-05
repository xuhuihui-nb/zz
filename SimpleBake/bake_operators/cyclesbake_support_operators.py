import bpy 
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty

from ..utils import SBConstants
from ..messages import print_message

class SimpleBake_OT_CyclesBake_Specific_Bake_Prep_And_Finish(Operator):
    """Preperation and finishing specific to PBR baking"""
    bl_idname = "simplebake.cyclesbake_specific_bake_prep_and_finish"
    bl_description = "Preperation or Finish for CyclesBake bake type"
    bl_label = "Prepare or Finish"
    
    mode: StringProperty()
    
    orig_sample_count = 0
    orig_object_render_vis = {}
    
    def finish(self, context):
        print_message(context, "CyclesBake specific bake finishing actions")
        
        #Restore original object visibility
        for obj in context.scene.objects:
            if obj.name in __class__.orig_object_render_vis:
                obj.hide_render = __class__.orig_object_render_vis[obj.name]
        
    def prepare(self, context):
        print_message(context, "CyclesBake specific bake prep actions")
        
        #Record original object visibility
        for obj in context.scene.objects:
            __class__.orig_object_render_vis[obj.name] = obj.hide_render
        
    
    def execute(self, context):
        if self.mode == "prepare":
            self.prepare(context)
        elif self.mode == "finish":
            self.finish(context)
    
        return {'FINISHED'}



classes = ([
    SimpleBake_OT_CyclesBake_Specific_Bake_Prep_And_Finish
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
