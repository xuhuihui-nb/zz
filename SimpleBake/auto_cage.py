import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.props import StringProperty

from .utils import select_only_this


def set_parent(context, child_name, parent_name):
    """
    Sets the parent of the specified child object to the specified parent object.

    :param child_name: The name of the child object.
    :param parent_name: The name of the parent object.
    """
    # Get the child and parent objects
    child = context.scene.objects.get(child_name)
    parent = context.scene.objects.get(parent_name)

    # Check if both objects exist
    if child is None:
        print(f"Child object '{child_name}' not found.")
        return
    if parent is None:
        print(f"Parent object '{parent_name}' not found.")
        return

    original_matrix = child.matrix_world.copy()

    # Set the parent
    child.parent = parent

    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = original_matrix

# Function to duplicate an object and apply all modifiers
def duplicate_and_apply_modifiers(context, obj_name):
    obj = context.scene.objects.get(obj_name)
    if obj is None:
        print(f"Object '{obj_name}' not found")
        return None

    # Duplicate the object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()

    new_obj = context.view_layer.objects.active
    new_obj.name = f"{obj_name}_cage"
    new_obj["SB_bake_operation_id"] = "Blah"

    #new_obj.location = obj.location.copy()
    #new_obj.rotation_euler = obj.rotation_euler.copy()
    #new_obj.scale = obj.scale.copy()

    # Apply all modifiers
    for modifier in new_obj.modifiers:
        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except:
            new_obj.modifiers.remove(modifier)

    new_obj.hide_select = True

    return new_obj.name

# Function to remove all materials from an object
def remove_all_materials(obj):
    obj.data.materials.clear()

# Function to add a new material to an object and set its viewport color
def add_new_material(obj, mat_name, color, alpha):
    # Create a new material
    mat = bpy.data.materials.new(name=mat_name)

    # Set the diffuse color
    mat.diffuse_color = (color[0], color[1], color[2], alpha)
    mat.use_nodes = True

    if (pnode:= mat.node_tree.nodes.get("Principled BSDF")):
        pnode.inputs["Base Color"].default_value = (color[0], color[1], color[2], alpha)
        pnode.inputs["Alpha"].default_value = 0.5

    # Assign the material to the object
    obj.data.materials.append(mat)

    # Set Viewport Display color
    obj.color = (color[0], color[1], color[2], alpha)
    obj.show_transparent = True

# Function to add a displacement modifier to an object
def add_displacement_modifier(obj):
    displace = obj.modifiers.new(name='Displace', type='DISPLACE')
    displace.texture = None  # Set the texture to None
    displace.mid_level = 1  # Set the midlevel to 1
    displace.name = "SB_AUTO_CAGE"



class SimpleBake_OT_Auto_Cage(Operator):
    bl_idname = "simplebake.auto_cage"
    bl_label = "Auto-Cage"
    bl_description = "Automatically create a cage object *for selected Target Object*. Must be in object mode to run"

    target_name: StringProperty()

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False

        sbp = context.scene.SimpleBake_Props
        if sbp.global_mode == "PBR":
            if sbp.targetobj == None: return False
            if sbp.targetobj.type != "MESH": return False
            if sbp.targetobj.name not in context.view_layer.objects: return False

            #Is there already an auto cage object?
            t = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == sbp.targetobj.name]
            if len(t) > 0:
                return False

        elif sbp.global_mode == "CyclesBake":
            if sbp.targetobj_cycles == None: return False
            if sbp.targetobj_cycles.type != "MESH": return False
            if sbp.targetobj_cycles.name not in context.view_layer.objects: return False

            #Is there already an auto cage object?
            t = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == sbp.targetobj_cycles.name]
            if len(t) > 0:
                return False

        return True

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        # Main script
        if self.target_name != "":
            obj_name = self.target_name
        elif sbp.global_mode == "PBR" and sbp.targetobj != None:
            obj_name = sbp.targetobj.name
        elif sbp.global_mode == "CyclesBake" and sbp.targetobj_cycles != None:
            obj_name = sbp.targetobj_cycles.name
        else:
            #Something has gone very wrong
            return {'CANCELLED'}

        new_obj_name = duplicate_and_apply_modifiers(context, obj_name)
        if new_obj_name:
            new_obj = context.scene.objects.get(new_obj_name)
            remove_all_materials(new_obj)
            add_new_material(new_obj, 'SB_Cage_Mat', (1.0, 0.0, 0.0), 0.5)  # Red color with 50% alpha
            add_displacement_modifier(new_obj)
            set_parent(context, new_obj_name, obj_name)
            new_obj["SB_auto_cage"] = obj_name

            context.scene.render.bake.cage_object = new_obj

        #Return selection to the actual target object
        select_only_this(context, context.scene.objects.get(obj_name))



        return {'FINISHED'}

class SimpleBake_OT_Remove_Auto_Cage(Operator):
    bl_idname = "simplebake.remove_auto_cage"
    bl_label = "Remove Auto-Cage Object *for selected Target Object*"
    bl_description = "Remove automatically created cage object  *for selected Target Object*. Must be in object mode to run"

    target_name: StringProperty()

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False

        sbp = context.scene.SimpleBake_Props
        to_name = ""
        if sbp.global_mode == "PBR":
            if sbp.targetobj == None: return False
            if sbp.targetobj.type != "MESH": return False
            if sbp.targetobj.name not in context.view_layer.objects: return False
            to_name = sbp.targetobj.name
        elif sbp.global_mode == "CyclesBake":
            if sbp.targetobj_cycles == None: return False
            if sbp.targetobj_cycles.type != "MESH": return False
            if sbp.targetobj_cycles.name not in context.view_layer.objects: return False
            to_name = sbp.targetobj_cycles.name

        #Make sure there is a cage object to remove
        t = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == to_name]
        if len(t) == 0:
            return False

        return True

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        if self.target_name != "":
            obj_name = self.target_name
        elif sbp.global_mode == "PBR" and sbp.targetobj != None:
            obj_name = sbp.targetobj.name
        elif sbp.global_mode == "CyclesBake" and sbp.targetobj_cycles != None:
            obj_name = sbp.targetobj_cycles.name
        else:
            #Something has gone very wrong
            return {'CANCELLED'}

        to_remove = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == obj_name]
        for o_name in to_remove:
            o = context.scene.objects.get(o_name)
            if o != None:
                bpy.data.objects.remove(o)
        return {'FINISHED'}

classes = ([
        SimpleBake_OT_Auto_Cage,
        SimpleBake_OT_Remove_Auto_Cage
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

