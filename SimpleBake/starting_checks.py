from .utils import get_sb_prefs
import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class

from .utils import show_message_box, clean_file_name, SBConstants, specials_selection_to_list, pbr_selections_to_list, blender_refresh, get_cached_udim_tiles
from .messages import print_message
from .ui.objects_list import refresh_bake_objects_list
from pathlib import Path
from .utils import can_write_to_location
from .bake_operators.pbr_bake_support_operators import has_node_groups, convertable_shaders
from . import __package__ as base_package




def check_mat_valid_for_displacement(mat_name, obj_name, messages):

    mat = bpy.data.materials.get(mat_name)
    if mat == None:
        return True

    node_tree = mat.node_tree
    nodes = node_tree.nodes

    valid = False

    #groups = [n.name for n in this_node_set if n.bl_idname == "ShaderNodeGroup"]

    #Find our MO node
    mo = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output]
    assert len(mo)==1, "Couldn't find the Material Output node"
    mo = mo[0]

    #Empty is OK
    if len(mo.inputs["Displacement"].links)==0:
        valid = True

    if len(mo.inputs["Displacement"].links)>0 and not valid:
        from_node = mo.inputs["Displacement"].links[0].from_node

        #Check if this is straightforward
        if from_node.bl_idname in ["ShaderNodeDisplacement", "ShaderNodeVectorDisplacement"]:
            valid = True

        #Maybe it's in a node group
        elif from_node.bl_idname == "ShaderNodeGroup":
            #Recursive search for the nodes we want
            trees = [from_node.node_tree]
            for tree in trees:
                for node in tree.nodes:
                    if node.bl_idname == "ShaderNodeGroup":
                        trees.append(node.node_tree)
                        continue

                    if node.bl_idname in ["ShaderNodeDisplacement", "ShaderNodeVectorDisplacement"]:
                        if len(node.outputs[0].links)>0:
                            if node.outputs[0].links[0].to_node.bl_idname == "NodeGroupOutput":
                                valid = True
    if valid:
        return True
    else:
        messages.append(f"ERROR: Baking Displacement map, but material \"{mat_name}\" on object \"{obj_name}\" has an")
        messages.append("invalid node plugged into the Material Output displacement socket.")
        messages.append("SimpleBake can only bake a single Displacement node or Vector Displacement node")
        messages.append("connected to the Displacement socket of the active Material Output node.")
        messages.append("If such a node is inside a node group, it must be connected directly to the Group Output node.")
        return False


def find_shader_node_editor():

    found_space = False

    for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == 'NODE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'NODE_EDITOR' and space.tree_type == 'ShaderNodeTree':
                            found_space = True
                            break
                    if found_space:
                        break
            if found_space:
                break


    return found_space


def check_for_connected_viewer_node(context, mat):
    sbp = context.scene.SimpleBake_Props
    
    mat.use_nodes = True
    
    node_tree = mat.node_tree
    nodes = node_tree.nodes
    #onode = find_onode(node_tree)
    
    #Get all nodes with label "Viewer"
    viewer_nodes = [n for n in nodes if n.label == "Viewer"]
    
    #Check if any of those viewer nodes are connected to the Material Output
    for n in viewer_nodes:        
        #if n.name == onode.inputs[0].links[0].from_node.name:
        if len(n.outputs[0].links)>1:
            if n.outputs[0].links[0].to_node.type == "OUTPUT_MATERIAL":
                return True
    
    return False

def check_mats_valid_for_pbr(context, mat):
    prefs = get_sb_prefs(context)
    skip = prefs.skip_pbr_nodes_check

    allowed_list = convertable_shaders + [
                "ShaderNodeBsdfPrincipled", "ShaderNodeMixShader",
                "ShaderNodeEmission", "NodeReroute", "ShaderNodeGroup",
                "NodeGroupInput", "NodeGroupOutput"]


    if skip:
        print_message(context, "Skipping check for invalid PBR nodes")
        return []

    sbp = context.scene.SimpleBake_Props
    node_sets = [mat.node_tree.nodes]
    invalid_node_names = []
    
    i = 0
    while i < len(node_sets):
        this_node_set = node_sets[i]
        
        #Find any node groups, and add their node_set to the list
        groups = [n.name for n in this_node_set if n.bl_idname == "ShaderNodeGroup"]
        for n_name in groups:
            if(n:=this_node_set.get(n_name)):
                if hasattr(n, "node_tree"):
                    node_tree = n.node_tree
                    if hasattr(node_tree, "nodes"):
                        node_sets.append(n.node_tree.nodes)
        
        #Now check for offending nodes in this node set
        offending = [n for n in this_node_set if
            len(n.outputs)>0 and 
            n.outputs[0].type == "SHADER" and
            len(n.outputs[0].links) > 0 and
            n.bl_idname not in allowed_list]
        for o in offending:
            invalid_node_names.append(o.name)

        #Second case, the shader to RGB node
        offending = ([n for n in this_node_set if
            len(n.outputs)>0 and
            len(n.outputs[0].links) > 0 and
            n.bl_idname == "ShaderNodeShaderToRGB"
            ])
        for o in offending:
            invalid_node_names.append(o.name)
        
        i+=1
    
    return invalid_node_names

def ensure_valid_material_config(context, obj):

    sbp = context.scene.SimpleBake_Props
    
    if "SimpleBake_Placeholder" in bpy.data.materials:
        mat = bpy.data.materials["SimpleBake_Placeholder"]
    else:
        mat = bpy.data.materials.new("SimpleBake_Placeholder")
        bpy.data.materials["SimpleBake_Placeholder"].use_nodes = True

    # Assign it to object
    if len(obj.material_slots) > 0:
        #Assign it to every empty slot
        for slot in obj.material_slots:
            if slot.material == None:
                slot.material = mat
    else:
        # no slots
        obj.data.materials.append(mat)
    
    #All materials must use nodes
    for slot in obj.material_slots:
        mat = slot.material
        if mat.use_nodes == False:
            mat.use_nodes = True
            
    return True


class SimpleBake_OT_Starting_Checks(Operator):
    """Perform pre-bake starting checks"""
    bl_idname = "simplebake.starting_checks"
    bl_description = "Perform bake starting checks"
    bl_label = "Go"
    
    def universal_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "Universal pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []
        
        #Universal Checks
        if(context.mode != "OBJECT"):
            messages.append("ERROR: Not in object mode")
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}
    
        #If exporting, check we can write to the folder given
        if sbp.save_bakes_external or sbp.save_obj_external:
            path = Path(bpy.path.abspath(sbp.export_path))
            #path = path.parent
            if not can_write_to_location(path):
                messages.append(f"ERROR: Blender reports that it cannot write to the Export Path you have")
                messages.append(f'specified under Export settings')
                messages.append(f'CANNOT WRITE TO: "{bpy.path.abspath(str(path))}"')
                messages.append(f"Try specifying a different export path")
                show_message_box(context, messages, "Errors occured", icon = 'ERROR')
                return {'CANCELLED'}

        #Check no cp textures rely on bakes that are no longer enabled
        if sbp.global_mode == SBConstants.PBR:
            pbr_bakes = pbr_selections_to_list(context)
            special_bakes = specials_selection_to_list(context)
            bakes = pbr_bakes + special_bakes
            bakes.append("none")
            def cp_channel_invalid(value):
                """Return True if this channel value can't be satisfied by the current bake settings."""
                if value == "none":
                    return False
                if "||" in value:
                    # Per-material value — only valid when tex_per_mat is on
                    if not sbp.tex_per_mat:
                        return True
                    bake_type = value.split("||", 1)[0]
                else:
                    bake_type = value
                return bake_type not in bakes
            def cp_display(value):
                """Human-readable form of a channel value, safe for the | -delimited message box."""
                return value.replace("||", " - ")
            for cpt in sbp.cp_list:
                if cp_channel_invalid(cpt.R):
                    messages.append(f"ERROR: Channel packed texture \"{cpt.name}\" depends on {cp_display(cpt.R)}, but you are no longer baking it")
                if cp_channel_invalid(cpt.G):
                    messages.append(f"ERROR: Channel packed texture \"{cpt.name}\" depends on {cp_display(cpt.G)}, but you are no longer baking it")
                if cp_channel_invalid(cpt.B):
                    messages.append(f"ERROR: Channel packed texture \"{cpt.name}\" depends on {cp_display(cpt.B)}, but you are no longer baking it")
                if cp_channel_invalid(cpt.A):
                    messages.append(f"ERROR: Channel packed texture \"{cpt.name}\" depends on {cp_display(cpt.A)}, but you are no longer baking it")
            messages = list(set(messages)) #Remove duplicates
            if len(messages) >0:
                show_message_box(context, messages, "Errors occured", icon = 'ERROR')
                return {'CANCELLED'}
        
        #Is anything seleccted at all for bake?
        if len(bake_objects) == 0:
            messages.append("ERROR: Nothing in the bake objects list!")
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}
        
        #Check everything selected (or target) is mesh
        l = [bpy.data.objects.get(name) for name in bake_objects]
        l = [o for o in l if o!=None and o.type != "MESH"]

        if len(l)>0:
            ([messages.append(f"ERROR: Object '{obj.name}' is not mesh") for obj in l])
        if sbp.selected_s2a and targetobj != None and targetobj.type != "MESH":
            messages.append(f"ERROR: Object '{targetobj.name}' (your target object) is not mesh")
        if sbp.cycles_s2a and targetobj_cycles != None and targetobj_cycles.type != "MESH":
            messages.append(f"ERROR: Object '{targetobj.name}' (your target object) is not mesh")
        if len(messages) > 0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}
    
        #if sbp.save_bakes_external or sbp.save_obj_external:
            #if sbp.save_external_folder != clean_file_name(sbp.save_external_folder):
                #message_items = ["ERROR: Folder name can only contain characters that",
                             #"are valid for the external file system"]
                #show_message_box(context, message_items, "ERROR", icon = "ERROR")
                #return {'CANCELLED'}
            
        
        #Ensure valid material config
        objs = [bpy.data.objects.get(name) for name in bake_objects]
        objs = [o for o in objs if o!=None]
        for obj in objs:
            ensure_valid_material_config(context, obj)
        if targetobj!=None: ensure_valid_material_config(context, targetobj)
        if targetobj_cycles!=None: ensure_valid_material_config(context, targetobj_cycles)
        
        #Check object visibility
        if len([o for o in context.view_layer.objects if o.type=="MESH"])==0:
            messages.append("There must be at least one mesh object visible in the current view layer")
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}    
            
        obj_test_list = bake_objects.copy()
        if sbp.selected_s2a and sbp.targetobj != None:
            obj_test_list.append(sbp.targetobj.name)
        if sbp.cycles_s2a and sbp.targetobj_cycles != None:
            obj_test_list.append(sbp.targetobj_cycles.name)
        
        for obj_name in obj_test_list:
            if (o:=bpy.data.objects.get(obj_name)):
                if o.hide_viewport == True:
                    messages.append(f"Object '{o.name}' is hidden in viewport (monitor icon in outliner)")
                if o.hide_render == True:
                    messages.append(f"Object '{o.name}' is hidden for render (camera icon in outliner)")
                if o.hide_get() == True:
                    messages.append(f"Object '{o.name}' is hidden in viewport eye (eye icon in outliner)")
                if o.hide_select == True:
                    messages.append(f"Object '{o.name}' is hidden for selection (arrow icon in outliner)")
        
        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}    
    
        #None of the objects can have zero faces
        for obj_name in bake_objects:
            o = bpy.data.objects.get(obj_name)
            if o!= None and len(o.data.polygons) < 1: messages.append(f"ERROR: Object '{o.name}' has no faces")
        if sbp.selected_s2a and targetobj != None:
            if len(targetobj.data.polygons) < 1: messages.append(f"ERROR: Object '{targetobj.name}' has no faces")
        if sbp.cycles_s2a and targetobj_cycles != None:
            if len(targetobj_cycles.data.polygons) < 1: messages.append(f"ERROR: Object '{targetobj_cycles.name}' has no faces")
        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}    
            
        #Check for viewer nodes still connected
        for obj_name in bake_objects:
            if (o:=bpy.data.objects.get(obj_name)):
                for slot in o.material_slots:
                    mat = slot.material
                    if mat != None: #It'll get a placeholder material later on if it's none
                        if check_for_connected_viewer_node(context, mat):
                            messages.append(f"ERROR: Material '{mat.name}' on object '{o.name}' has a Viewer node connected to the Material Output")
        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}    
                    
        #glTF
        if sbp.create_glTF_node:
            if sbp.glTF_selection == SBConstants.AO and not sbp.selected_ao:
                messages.append(f"ERROR: You have selected AO for glTF settings (in the 'Other Settings' section), but you aren't baking AO")
            if sbp.glTF_selection == SBConstants.LIGHTMAP and not sbp.selected_lightmap:
                messages.append(f"ERROR: You have selected Lightmap for glTF settings (in the 'Other Settings' section), but you aren't baking Lightmap")
        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}    
    
        prefs = get_sb_prefs(context)
        for obj_name in bake_objects:
            if (o:=bpy.data.objects.get(obj_name)):
                if o.name != clean_file_name(o.name) and sbp.save_bakes_external and "%OBJ%" in prefs.img_name_format:
                    messages.append(f"ERROR: You are trying to save external images, but object with name \"{o.name}\" contains invalid characters for saving externally.")
                    show_message_box(context, messages, "Errors occured", icon = 'ERROR')
                    return {'CANCELLED'}
                
        #Merged bake checks
        if sbp.merged_bake and sbp.merged_bake_name == "":
            messages.append(f"ERROR: You are baking multiple objects to one texture set, but the texture name is blank")
        if (sbp.merged_bake_name != clean_file_name(sbp.merged_bake_name)) and sbp.save_bakes_external:
            messages.append(f"ERROR: The texture name you inputted for baking multiple objects to one texture set (\"{sbp.merged_bake_name}\") contains invalid characters for saving externally.")

        if sbp.merged_bake:
            if sbp.selected_s2a or sbp.cycles_s2a:
                if sbp.s2a_opmode!="automatch":
                    messages.append("You can't use the Bake Multiple Objects to One Texture Set option when baking to target")

        #Export bakes checkes
        if (sbp.save_bakes_external or sbp.save_obj_external) and sbp.export_path == "":
            messages.append(f"You are saving your bakes and/or mesh externally, but your "
                            "Export Path (under the Export settings section) is blank")
            
        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}

        # Background bake + UDIMs requires external save to be enabled
        if sbp.bgbake == "bg" and not sbp.save_bakes_external:
            if sbp.selected_s2a:
                udim_check_objects = [targetobj.name] if targetobj else []
            elif sbp.cycles_s2a:
                udim_check_objects = [targetobj_cycles.name] if targetobj_cycles else []
            else:
                udim_check_objects = list(bake_objects)

            for obj_name in udim_check_objects:
                result = get_cached_udim_tiles(context, obj_name, threshold=0.001)
                if result["total_tiles"] > 1:
                    messages.append("ERROR: Bake objects have UDIMs. Background baking with UDIMs")
                    messages.append('requires "Export Bakes" to be enabled in the Export settings.')
                    show_message_box(context, messages, "Errors occurred", icon='ERROR')
                    return {'CANCELLED'}

        return {'FINISHED'}

    def pbr_no_s2a_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "PBR no S2A pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []

        #Check if we have a shader node editor to use_nodes
        ngs = False
        for obj_name in bake_objects:
            if (o:=bpy.data.objects.get(obj_name)):
                for slot in o.material_slots:
                    if slot.material != None:
                        ngs = has_node_groups(context, slot.material.name)
                        break
                if ngs:
                    break
        if ngs and not find_shader_node_editor():
            messages.append(f"Some or all of your materials have node groups. To process node groups, SimpleBake needs there")
            messages.append(f"to be a Shader Node Editor open somewhere in one of your Blender workspaces. You don't seem to have")
            messages.append(f"one open anywhere! Open a Shader Node Editor (as if you were editing a material) somewhere in one of")
            messages.append(f"your Blender workspaces, then try again")
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}

        #If baking displacement, do all materials meet the rules
        if sbp.selected_displacement:
            mats = {}
            for obj_name in bake_objects:
                if (o:=bpy.data.objects.get(obj_name)):
                    for slot in o.material_slots:
                        if slot.material != None:
                            mats[obj_name] = slot.material.name
            for m in mats:
                if not check_mat_valid_for_displacement(mats[m], m, messages):
                    show_message_box(context, messages, "Errors occured", "ERROR")
                    return {'CANCELLED'}

        for obj_name in bake_objects:

            if not (o:=bpy.data.objects.get(obj_name)):
                break

            #Are UVs OK?
            generating_uvs = sbp.new_uv_option or (sbp.tex_per_mat and sbp.expand_mat_uvs)
            if not generating_uvs and len(o.data.uv_layers) == 0:
                messages.append(f"ERROR: Object {o.name} has no UVs, and you aren't generating new ones")

            if sbp.new_uv_option and sbp.new_uv_method=='CombineExisting' and len(o.data.uv_layers) == 0:
                messages.append(f"ERROR: You are combining existing UVs, but object {o.name} has no UVs")

            
            #Do all materials have valid PBR config?
            for slot in o.material_slots:
                mat = slot.material
                result = check_mats_valid_for_pbr(context, mat)
                warn = False
                if len(result) > 0:
                    for node_name in result:
                        messages.append(f"ERROR: Node '{node_name}' in material '{mat.name}' on object '{o.name}' is not valid for PBR bake. Principled BSDFs and/or Emission only!")
                        warn = True
            if warn:
                messages.append("NOTE: There is an option to disable this check in the SimpleBake addon preferences, but it is not recommended. Baking PBR with nodes that are not PBR compatible may give unexpected results, Black bakes or even CRASHES!")

            #Checked for invalid nodes, now let's check for just absent any useful nodes:
            else:

                #Do all materials have at least one material output node?
                for slot in o.material_slots:
                    mat = slot.material
                    mos = [node for node in mat.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial"\
                        and len(node.inputs[0].links)>0]
                    if len(mos) == 0:
                        messages.append(f"ERROR: Material '{mat.name}' on object '{o.name}' is broken. Must have at least one Material Output node that's plugged in!")

        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}
            
        return {'FINISHED'}
    
    def pbr_s2a_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "PBR S2A pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []

        ngs = False
        for obj_name in bake_objects:
            if(o:=bpy.data.objects.get(obj_name)):
                for slot in o.material_slots:
                    if slot.material != None:
                        ngs = has_node_groups(context, slot.material.name)
                        break
            if ngs:
                break
        if ngs and not find_shader_node_editor():
            messages.append(f"Some or all of your materials have node groups. To process node groups, SimpleBake needs there")
            messages.append(f"to be a Shader Node Editor open somewhere in one of your Blender workspaces. You don't seem to have")
            messages.append(f"one open anywhere! Open a Shader Node Editor (as if you were editing a material) somewhere in one of")
            messages.append(f"your Blender workspaces, then try again")
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}


        #Do all materials have valid PBR config?
        warn = False
        for obj_name in bake_objects:
            if(o:=bpy.data.objects.get(obj_name)):
                for slot in o.material_slots:
                    mat = slot.material
                    result = check_mats_valid_for_pbr(context, mat)
                    if len(result) > 0:
                        for node_name in result:
                            messages.append(f"ERROR: Node '{node_name}' in material '{mat.name}' on object '{o.name}' is not valid for PBR bake. Principled BSDFs and/or Emission only!")
                            warn = True
        if warn:
            messages.append("NOTE: There is an option to disable this check in the SimpleBake addon preferences, but it is not recommended. Baking PBR with nodes that are not PBR compatible may give unexpected results, Black bakes or even CRASHES!")

        #Checked for invalid nodes, now let's check for just absent any useful nodes:
        else:
            #Do all materials have at least one material output node?
            for obj_name in bake_objects:
                if (o:=bpy.data.objects.get(obj_name)):
                    for slot in o.material_slots:
                        mat = slot.material
                        mos = [node for node in mat.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial"\
                            and len(node.inputs[0].links)>0]
                        if len(mos) == 0:
                            messages.append(f"ERROR: Material '{mat.name}' on object '{o.name}' is broken. Must have at least one Material Output node that's plugged in!")

        #Checks for baking displacement
        for obj_name in bake_objects:
            if (o:=bpy.data.objects.get(obj_name)):
                for slot in o.material_slots:
                    if slot.material!=None:
                        mat = slot.material
                        if not check_mat_valid_for_displacement(mat.name, o.name, messages):
                            show_message_box(context, messages, "Errors occured", "ERROR")
                            return {'CANCELLED'}

        if len(messages)>0:
            show_message_box(context, messages, "Errors occured", icon = 'ERROR')
            return {'CANCELLED'}
    
        #From this point onward, we only care about the target object
        #-------------------------------------------------------------------------

        #Do we have a target object?
        if targetobj == None:
            messages.append("ERROR: You are trying to bake to a target object with PBR Bake, but you have not selected one in the SimpleBake panel")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}

        #If declas, need to do the displacement check again as the target object materials get baked
        for slot in targetobj.material_slots:
            if slot.material!=None:
                mat = slot.material
                if not check_mat_valid_for_displacement(mat.name, targetobj.name, messages):
                    show_message_box(context, messages, "Errors occured", "ERROR")
                    return {'CANCELLED'}


        #Have we got more selected than just the target object?
        if len(bake_objects) == 1 and bake_objects[0] == targetobj.name:
            messages.append("ERROR: You are trying to bake to a target object, but the only object you have selected is your target")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}
        
        #If the target object is in the bake objects list, remove it now
        i = sbp.objects_list.find(targetobj.name)
        if i>-1: sbp.objects_list.remove(i)

        #Are UVs OK?
        if sbp.new_uv_option == False and len(targetobj.data.uv_layers) == 0:
            messages.append(f"ERROR: Object {targetobj.name} has no UVs, and you aren't generating new ones")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}
        
        #All existing materials must use nodes
        for slot in targetobj.material_slots:
            if slot.material != None:
                if not slot.material.use_nodes:
                    slot.material.use_nodes = True

        return {'FINISHED'}
    
    
    def cyclesbake_no_s2a_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "CyclesBake no S2A pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []
        
            
        for obj_name in bake_objects:
            if (o:=bpy.data.objects.get(obj_name)):
                #Are UVs OK?
                if not sbp.tex_per_mat:
                    if sbp.new_uv_option == False and len(o.data.uv_layers) == 0:
                        messages.append(f"ERROR: Object {o.name} has no UVs, and you aren't generating new ones")
                        show_message_box(context, messages, "Errors occured", "ERROR")
                        return {'CANCELLED'}

                    if sbp.new_uv_option and sbp.new_uv_method=='CombineExisting' and len(o.data.uv_layers) == 0:
                        messages.append(f"ERROR: You are combining existing UVs, but object {o.name} has no UVs")
                        show_message_box(context, messages, "Errors occured", "ERROR")
                        return {'CANCELLED'}
                else:
                    if sbp.expand_mat_uvs == False and len(o.data.uv_layers) == 0:
                        messages.append(f"ERROR: Object {o.name} has no UVs, and you aren't generating new ones")
                        show_message_box(context, messages, "Errors occured", "ERROR")
                        return {'CANCELLED'}
        
        return {'FINISHED'}
    
    def cyclesbake_s2a_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "CyclesBake S2A pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []
        
        #Do we actually have a target object?
        if targetobj_cycles == None:
            messages.append(f"ERROR: You are trying to bake to target with CyclesBake, but there is no target object selected on the SimpleBake panel")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}
        
        #Have we got more selected than just the target object?
        elif len(bake_objects) == 1 and bake_objects[0] == targetobj_cycles.name:
            messages.append("ERROR: You are trying to bake selected to active with CyclesBake, but the only object you have selected is your active (target) object")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}

        #If the target object is in the bake objects list, remove it now
        i = sbp.objects_list.find(targetobj_cycles.name)
        if i>-1: sbp.objects_list.remove(i)
    
        #Are UVs OK?
        elif not sbp.new_uv_option and len(targetobj_cycles.data.uv_layers) == 0:
            messages.append(f"ERROR: Object {targetobj_cycles.name} has no UVs, and you aren't generating new ones")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}
    
        
        return {'FINISHED'}
    
    def specials_checks(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "Specials pre-bake checks")
        bake_objects = self.bake_objects
        targetobj = self.targetobj
        targetobj_cycles = self.targetobj_cycles
        messages = []

        if sbp.selected_col_vertex:
        
            if not sbp.selected_s2a and not sbp.cycles_s2a:
                for obj_name in bake_objects:
                    if (o:=bpy.data.objects.get(obj_name)):
                        if len(o.data.color_attributes) == 0:
                            messages.append(f"You are trying to bake the active vertex colours, but object {o.name} doesn't have vertex colours")
                            show_message_box(context, messages, "Errors occured", "ERROR")
                            return {'CANCELLED'}
            
            if sbp.cycles_s2a or sbp.selected_s2a:
                if sbp.selected_s2a: target_obj = sbp.targetobj
                else: target_obj = sbp.targetobj_cycles
                target_obj_name = target_obj.name
                
                obj_names = [o.obj_point.name for o in sbp.objects_list]
                if target_obj_name in obj_names:
                    obj_names.remove(target_obj_name)
                
                for o_name in obj_names:
                    if(o:=context.scene.objects.get(o_name)):
                        if len(o.data.color_attributes) == 0:
                            messages.append(f"You are trying to bake the active vertex colours, but object {o.name} doesn't have vertex colours")
                if len(messages)>0:
                    show_message_box(context, messages, "Errors occured", "ERROR")
                    return {'CANCELLED'}
        
        return {'FINISHED'}

    def image_sequence_checks(self,context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "Image sequence pre-bake checks")
        messages = []
        if  not sbp.image_sequence_start_frame <  sbp.image_sequence_end_frame:
            messages.append("When baking an image sequence, the starting frame must be before the end frame. Change this in the Other Settings section of SimpleBake")
            show_message_box(context, messages, "Errors occured", "ERROR")
            return {'CANCELLED'}

        return {'FINISHED'}

        
    
    def execute(self, context):
        blender_refresh()
        sbp = context.scene.SimpleBake_Props
        refresh_bake_objects_list(context)
        #disable_impossible(context)

        #sbp.bake_done = False
        
        #Get objects
        self.bake_objects = [i.name for i in sbp.objects_list]
        self.targetobj = sbp.targetobj
        self.targetobj_cycles = sbp.targetobj_cycles

        print_message(context, "Starting checks operator")

        
        
        #Universal checks
        r = self.universal_checks(context)
        if 'CANCELLED' in r: return{'CANCELLED'}
        
        #PBR Bake Checks - No S2A
        if sbp.global_mode == SBConstants.PBR and not sbp.selected_s2a:
            r = self.pbr_no_s2a_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}
        
        #PBR Bake - S2A
        if sbp.global_mode == SBConstants.PBR and sbp.selected_s2a:
            r = self.pbr_s2a_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}

            #If decals, need to do a normal PBR check on the target object
            if sbp.s2a_opmode == "decals":
                self.bake_objects= [sbp.targetobj.name]
                r = self.pbr_no_s2a_checks(context)
                if 'CANCELLED' in r: return{'CANCELLED'}


        #CyclesBake - no S2A
        if sbp.global_mode == SBConstants.CYCLESBAKE and not sbp.cycles_s2a:
            r = self.cyclesbake_no_s2a_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}
        
        #CyclesBake - S2A
        if sbp.global_mode == SBConstants.CYCLESBAKE and sbp.cycles_s2a:
            r = self.cyclesbake_s2a_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}
        
        #Specials
        if len(specials_selection_to_list(context)) >0:
            r = self.specials_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}
            
        #Image sequence
        if  sbp.image_sequence_enabled:
            r = self.image_sequence_checks(context)
            if 'CANCELLED' in r: return{'CANCELLED'}


        #Fix that weird context incorrect error
        #Selected object at start must be something and must be mesh
        #Find a nominal object that is a mesh and in the current view layer
        if context.active_object == None or context.active_object.type != "MESH":
            nominal = None
            for o in context.view_layer.objects:
                if o.type == "MESH":
                    nominal  = o
                    break
            assert(nominal!=None)
            
            bpy.ops.simplebake.select_only_this(target_object_name=nominal.name)
            
        
        #Guess everything was OK
        return {'FINISHED'}
            
            
"""
    #Specials Bake
     #CAGE OBJECT BROKEN? CHECK IF NOT NONE AND, IF NOT, FLIP THE SWITdisable_impossibleCH TO USE CAGE
    
"""
    

classes = ([
    SimpleBake_OT_Starting_Checks
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
