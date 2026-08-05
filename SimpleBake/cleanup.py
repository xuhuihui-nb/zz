import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.props import StringProperty

from . import property_group

import re

def format_to_regex(user_input):
    # Escape all regex special characters except for *
    escaped_input = re.escape(user_input)
    # Replace the escaped * with .*
    regex_pattern = escaped_input.replace(r'\*', '.*')

    # If the original input ends with *, modify the pattern to end with .*$
    if user_input.endswith('*'):
        regex_pattern = regex_pattern[:-2] + '.*$'

    # Check if the original input starts with *
    if user_input.startswith('*'):
        regex_pattern = '^.*' + regex_pattern[2:]

    return regex_pattern

def replace_pattern(text, pattern, replacement):
    # Format the pattern to include wildcards
    formatted_pattern = format_to_regex(pattern)

    # Use re.sub to replace all occurrences of the formatted pattern with the replacement string
    result = re.sub(formatted_pattern, replacement, text)
    return result

def find_and_replace(col, find, replace, limit_to_sb=False):
    for item in col:
        if limit_to_sb and "SB_bake_operation_id" not in item:
            continue

        original_name = item.name
        new_name = original_name.replace(find, replace)
        # If the new name is different, apply the change
        if new_name != original_name:
            item.name = new_name
            print(f"Renamed '{original_name}' to '{new_name}'")
        else:
            print(f"No change for '{original_name}'")


def find_and_replace_wildcard(context, col, find, replace, limit_to_sb=False):
    sbp = context.scene.SimpleBake_Props

    for item in col:
        if limit_to_sb and "SB_bake_operation_id" not in item:
            continue
        item.name = replace_pattern(item.name, find, replace)




class SimpleBake_OT_Purge_Settings(Operator):
    bl_idname = "simplebake.purge_settings"
    bl_label = "Purge Settings"
    bl_description = "WARNING - Purge ALL SimpleBake settings from this Blend file and reset to DEFAULTS. CANNOT BE UNDONE. INCLUDES BLEND FILE PRESETS (but not global presets)"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        #del context.scene["SimpleBake_Props"]
        context.scene.property_unset("SimpleBake_Props")

        self.report({'INFO'}, "SimpleBake settings restored to defaults")

        return {'FINISHED'}

class SimpleBake_OT_Purge_Images(Operator):
    bl_idname = "simplebake.purge_images"
    bl_label = "Purge Images"
    bl_description = "WARNING - Purge all SimpleBake created IMAGES from this blend file. CANNOT BE UNDONE"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        to_remove = []
        for i in bpy.data.images:
            if "SB_bake_operation_id" in i:
                to_remove.append(i.name)

        for name in to_remove:
            im = bpy.data.images.get(name)
            if im != None:
                bpy.data.images.remove(im, do_unlink=True)


        self.report({'INFO'}, "SimpleBake images have been purged")


        return {'FINISHED'}

class SimpleBake_OT_Purge_Objects(Operator):
    bl_idname = "simplebake.purge_objects"
    bl_label = "Purge Objects"
    bl_description = "WARNING - Purge all SimpleBake created OBJECTS from this blend file. CANNOT BE UNDONE"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        bpy.ops.simplebake.reverse_geo_nodes_sidestep()

        to_remove = []
        for o in context.scene.objects:
            if "SB_bake_operation_id" in o:
                to_remove.append(o.name)

        for name in to_remove:
            ob = context.scene.objects.get(name)
            if ob != None:
                if "SB_copy_and_apply_from" in ob:
                    uh = context.scene.objects.get(ob["SB_copy_and_apply_from"])
                    if uh !=None:
                        uh.hide_set(False)

                bpy.data.objects.remove(ob, do_unlink=True)

        if "SimpleBake_Bakes" in bpy.data.collections:
            bpy.data.collections.remove(bpy.data.collections["SimpleBake_Bakes"])


        bpy.ops.simplebake.reverse_geo_nodes_sidestep()


        self.report({'INFO'}, "SimpleBake objects have been purged")


        return {'FINISHED'}

class SimpleBake_OT_restorematerials(Operator):
    bl_idname = "simplebake.restorematerials"
    bl_label = "Restore"
    bl_description = "WARNING - Attempt to restore all materials and purge SimpleBake created MATERIALS from this blend file. CANNOT BE UNDONE"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        bpy.ops.simplebake.material_backup(mode="working_restore")
        bpy.ops.simplebake.material_backup(mode="master_restore")

        to_del= []
        for m in bpy.data.materials:
            if "SB_bake_operation_id" in m:
                to_del.append(m.name)

        for m_name in to_del:
            m = bpy.data.materials.get(m_name)
            if m !=None:
                bpy.data.materials.remove(m)

        self.report({'INFO'}, "Materials restored")


        return {'FINISHED'}


class SimpleBake_OT_findandreplace(Operator):
    bl_idname = "simplebake.findandreplace"
    bl_label = "Find and replace"
    bl_description = "Find and replace names for the given data type. Basic wildcards are supported as *"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        find = sbp.findreplace_find
        replace = sbp.findreplace_replace

        if sbp.findreplace_type == "image":
            col = bpy.data.images
        if sbp.findreplace_type == "object":
            col = context.scene.objects
        if sbp.findreplace_type == "material":
            col = bpy.data.materials


        if "*" in find:
            find_and_replace_wildcard(context, col, find, replace, limit_to_sb=sbp.limit_findandreplace_to_sb)
        else:
            find_and_replace(col, find, replace, limit_to_sb=sbp.limit_findandreplace_to_sb)

        self.report({'INFO'}, "Find and replace done")


        return {'FINISHED'}
classes = ([
    SimpleBake_OT_Purge_Settings,
    SimpleBake_OT_Purge_Images,
    SimpleBake_OT_Purge_Objects,
    SimpleBake_OT_findandreplace,
    SimpleBake_OT_restorematerials
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

