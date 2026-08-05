import bpy
from ..utils.registration import register_cls
from ..utils.state import S


@register_cls
class OBJECT_OT_set_source_softwrap(bpy.types.Operator):
    bl_idname = 'object.set_source_softwrap'
    bl_label = 'Source Mesh'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = 'Set the active mesh as the source mesh'

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        S().source_ob = context.active_object
        return {'FINISHED'}


@register_cls
class OBJECT_OT_set_target_softwrap(bpy.types.Operator):
    bl_idname = 'object.set_target_softwrap'
    bl_label = 'Target Mesh'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = 'Set the active mesh as the target mesh'

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        S().target_ob = context.active_object
        return {'FINISHED'}
