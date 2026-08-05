import bpy
from .utils import SBConstants, blender_default_colorspace#, get_cs_list
from .messages import print_message

from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty

def get_aov_name(context, num):
    sbp = context.scene.SimpleBake_Props
    aov_collection = sbp.aov_items

    num = str(num)
    num = int(num.replace(f"{SBConstants.PBRAOVS}_", ""))

    for aov in aov_collection:
        if aov.aov_number == num:
            return aov.name
    print_message(context, "ERROR: Could not find AOV when looking for AOV name")
    return False

def get_aov_number(context, name):
    sbp = context.scene.SimpleBake_Props
    aov_collection = sbp.aov_items

    for aov in aov_collection:
        if aov.name == name:
            return aov.aov_number

    return False

def get_aov_colspace(context, name):
    sbp = context.scene.SimpleBake_Props
    aov_collection = sbp.aov_items

    num = int(name.replace(f"{SBConstants.PBRAOVS}_", ""))

    for aov in aov_collection:
        if aov.aov_number == num:
            return aov.cs
    print_message(context, "ERROR: Could not find AOV when looking for Color Space")
    return False

def get_aov_type(context, name):
    sbp = context.scene.SimpleBake_Props
    aov_collection = sbp.aov_items

    num = int(name.replace(f"{SBConstants.PBRAOVS}_", ""))

    for aov in aov_collection:
        if aov.aov_number == num:
            return aov.aov_type
    print_message(context, "ERROR: Could not find AOV when looking for Type")
    return False

def get_list_enabled_aov_names(context):
    sbp = context.scene.SimpleBake_Props
    aov_collection = sbp.aov_items

    names = []

    for i in aov_collection:
        if i.enabled:
            names.append(i.name)

    return names



class SimpleBake_OT_RefreshAOVList(bpy.types.Operator):
    bl_idname = "simplebake.refresh_aov_list"
    bl_label = "Refresh AOV List"
    bl_description = "Scan objects in bake objects list for AOV Output nodes and update the AOV list"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        aov_collection = sbp.aov_items

        #So we can renable them at the emd
        original_state = [[i.name, i.cs, i.enabled] for i in aov_collection]

        # Clear existing list
        aov_collection.clear()

        aov_names = [] #Really only used to check for duplicates

        obj_names = [i.obj_point.name for i in sbp.objects_list]

        #As always, declas is an annoying excpetion
        if sbp.s2a_opmode == 'decals' and sbp.targetobj!=None:
            obj_names.append(sbp.targetobj.name)


        for obj_name in obj_names:
            obj = bpy.data.objects.get(obj_name)
            if not obj:
                continue

            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes:
                    continue

                node_trees = []
                node_trees.append(mat.node_tree)

                for node_tree in node_trees:
                    if not hasattr(node_tree, "nodes"):
                        continue #Avoiding error reported on Discord. Not sure how this happens

                    for node in node_tree.nodes:

                        if node.bl_idname == "ShaderNodeGroup":
                            node_trees.append(node.node_tree)

                        elif node.bl_idname == "ShaderNodeOutputAOV":
                            if len(node.inputs['Color'].links)>0 or len(node.inputs['Value'].links)>0:
                                aov_name = node.aov_name
                                if aov_name not in aov_names:  # avoid duplicates
                                    aov_names.append(aov_name)

                                    #Get the CS names only so we can find the index later
                                    #cs_list = [i[0] for i in get_cs_list(self, context)]

                                    item = aov_collection.add()
                                    item.name = aov_name
                                    item.enabled = False
                                    item.aov_number = (aov_names.index(aov_name)+1)
                                    if len(node.inputs['Color'].links)>0:
                                        item.aov_type = "C"
                                        #item.cs = "s#RGB"
                                        item.cs = blender_default_colorspace(float_buffer=False, col=True)[1]
                                    else:
                                        item.aov_type = "V"
                                        #item.cs = "Non#-Color"
                                        item.cs = blender_default_colorspace(float_buffer=False, col=False)[1]
                                    item.object_name = obj_name
                                    item.mat_name = mat.name


        #Renable if originally enabled
        for i in aov_collection:
            for o in original_state:
                name = o[0]
                if i.name == name:
                    i.cs=o[1]
                    i.enabled = o[2]



        return {'FINISHED'}


classes = ([
    SimpleBake_OT_RefreshAOVList
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
