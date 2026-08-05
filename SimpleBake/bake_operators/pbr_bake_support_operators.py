from ..utils import get_sb_prefs
import bpy 
import numpy as np
import os
from pathlib import Path
import tempfile
import shutil
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

from ..utils import SBConstants, pbr_selections_to_list, select_only_this, force_to_object_mode, blender_refresh, object_list_to_names_list
from ..material_management import SimpleBake_OT_Material_Backup as MatManager
from ..messages import print_message
from ..background_and_progress import BakeInProgress as Bip
from .. import __package__ as base_package
from ..aov import get_list_enabled_aov_names

convertable_shaders = [
    "ShaderNodeBsdfDiffuse",
    "ShaderNodeBsdfGlass",
    "ShaderNodeBsdfAnisotropic",
    "ShaderNodeEmission",
    "ShaderNodeBsdfTransparent",
    "ShaderNodeSubsurfaceScattering",
    "ShaderNodeBsdfRefraction",
    "ShaderNodeBsdfToon",
    "ShaderNodeBsdfTranslucent",
    "ShaderNodeBsdfSheen"
    ]


def sample_nodes_present(context, obj_name):
    
    seeking = ["ShaderNodeBevel", "ShaderNodeAmbientOcclusion"]
    
    def hunt(node_tree):
        result = False
        if hasattr(node_tree, "nodes"):
            nodes = node_tree.nodes
            for n in nodes:
                if n.bl_idname in seeking:
                    for o in n.outputs:
                        if len(o.links)>0:
                            result = True
                            #May as well return here. One positive ends the game
                            return result

                if n.bl_idname == "ShaderNodeGroup":
                    result = hunt(n.node_tree)
                    #Again, may as well return here if there was a positive
                    if result:
                        return True
        
        #Because of the above returns, this will be False if we get here
        return result
        
    
    obj = context.scene.objects[obj_name]
    for slot in obj.material_slots:
        mat = slot.material
        result = hunt(mat.node_tree)
        
        if result:
            return True

    return False


def create_node_group_dummy_nodes(node, node_tree):

    # print(f"---------Creating dummy nodes for {node.name}")
    
    nodes = node_tree.nodes
    
    # col_input_sockets = [s for s in node.inputs if s.bl_idname == "NodeSocketColor" and len(s.links) == 0]
    # int_input_sockets = [s for s in node.inputs if s.bl_idname in ["NodeSocketInt", "NodeSocketIntFactor"] and len(s.links) == 0]
    # float_input_sockets = [s for s in node.inputs if s.bl_idname in ["NodeSocketFloatFactor", "NodeSocketFloat"] and len(s.links) == 0]
    # vector_input_sockets = [s for s in node.inputs if s.bl_idname in ["NodeSocketVector", "NodeSocketVectorXYZ", "NodeSocketVectorDirection"] and len(s.links) == 0]
    # bool_input_sockets = [s for s in node.inputs if s.bl_idname == "NodeSocketBool" and len(s.links) == 0]

    # print(f"-----------------No. of col sockets {len(col_input_sockets)}")
    # print(f"-----------------No. of int sockets {len(int_input_sockets)}")
    # print(f"-----------------No. of float sockets {len(float_input_sockets)}")
    # print(f"-----------------No. of vector sockets {len(vector_input_sockets)}")
    # print(f"-----------------No. of bool sockets {len(bool_input_sockets)}")

    # Pattern-matched, unlinked sockets
    col_input_sockets    = [s for s in node.inputs if s.bl_idname == "NodeSocketColor" and not s.is_linked]
    int_input_sockets    = [s for s in node.inputs if s.bl_idname.startswith("NodeSocketInt") and not s.is_linked]
    float_input_sockets  = [s for s in node.inputs if s.bl_idname.startswith("NodeSocketFloat") and not s.is_linked]
    vector_input_sockets = [s for s in node.inputs if s.bl_idname.startswith("NodeSocketVector") and not s.is_linked]
    bool_input_sockets   = [s for s in node.inputs if s.bl_idname == "NodeSocketBool"  and not s.is_linked]


    for s in col_input_sockets:
        # print(f"-----------------RGB node for {s.name}")
        val = s.default_value
        rgb = node_tree.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = val
        node_tree.links.new(rgb.outputs[0], s)
        
    for s in float_input_sockets:
        # print(f"-----------------Value node for {s.name}")
        val = s.default_value
        vnode = node_tree.nodes.new("ShaderNodeValue")
        vnode.outputs[0].default_value = val
        node_tree.links.new(vnode.outputs[0], s)

    for s in int_input_sockets:
        # print(f"-----------------Value node for {s.name}")
        val = s.default_value
        vnode = node_tree.nodes.new("ShaderNodeValue")
        vnode.outputs[0].default_value = val
        node_tree.links.new(vnode.outputs[0], s)

    for s in vector_input_sockets:
        # print(f"-----------------Vector node for {s.name}")
        x = s.default_value[0]
        y = s.default_value[1]
        z = s.default_value[2]
        vnode = node_tree.nodes.new("ShaderNodeCombineXYZ")
        vnode.inputs[0].default_value = x
        vnode.inputs[1].default_value = y
        vnode.inputs[2].default_value = z
        node_tree.links.new(vnode.outputs[0], s)

    for s in bool_input_sockets:
        val = s.default_value
        vnode = node_tree.nodes.new("ShaderNodeValue")

        vnode.outputs[0].default_value = 1 if val else 0
        node_tree.links.new(vnode.outputs[0], s)

        
    return True


def has_node_groups(context, mat_name):
    if not (mat:=bpy.data.materials.get(mat_name)):
        print(f"ERROR - Couldn't find material {mat_name}")

    #print_message(context, f"Testing {mat.name} for node groups")
    node_tree = mat.node_tree
    nodes = node_tree.nodes
    
    prefs = get_sb_prefs(context)
    ungroup_all = prefs.ungroup_all_node_groups
    ungroup_all = True if get_list_enabled_aov_names(context) else ungroup_all
    ungroup_all = True if context.scene.SimpleBake_Props.selected_displacement else ungroup_all

    #Ungroup all keeps forcing this function to return True until you can't populate a list of node groups

    result = False

    node_group_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeGroup"]
    for n in node_group_nodes:
        ss = [s for s in n.outputs if s.bl_idname == "NodeSocketShader"
                and len(s.links)>0]
        if len(ss)>0 or ungroup_all: result = True

    return result

def has_convertible_shaders(mat_name):

    if not (m:=bpy.data.materials.get(mat_name)):
        print(f"ERROR - Couldn't find material {mat_name}")
        return False

    node_tree = m.node_tree
    result=[False] #Mutable

    def check_nodes(node_tree):
        if not hasattr(node_tree, "nodes"):
            return False
        #nonlocal result
        nodes = node_tree.nodes
        for n in nodes:
            if n.bl_idname in convertable_shaders and len(n.outputs[0].links)>0:
                result[0] = True
            if n.bl_idname == "ShaderNodeGroup":
                check_nodes(n.node_tree)


    check_nodes(node_tree)

    return result[0]


def process_socket(tnode_name, tnode_sname, pnode_name, pnode_sname, nodes, node_tree):

    #Get the nodes we want
    if not (tnode:=nodes.get(tnode_name)):
        print(f"Failed to find node {tnode_name}")
        return False
    if not (pnode:=nodes.get(pnode_name)):
        print(f"Failed to find node {pnode_name}")
        return False

    #Get sockets
    tnode_socket = tnode.inputs.get(tnode_sname)
    pnode_socket = pnode.inputs.get(pnode_sname)

    #If it's plugged, transfer to pnode
    if len(tnode_socket.links)>0:
        from_socket = tnode_socket.links[0].from_socket
        node_tree.links.new(from_socket, pnode_socket)

    #Not plugged
    else:
        pnode_socket.default_value = tnode_socket.default_value

def swap_shaders_for_p(mat_name):

    to_del = []

    if not (mat:=bpy.data.materials.get(mat_name)):
        print(f"ERROR: Material {mat_name} not found")
        return False

    node_tree = mat.node_tree
    nodes = node_tree.nodes

    rel_nodes = [n.name for n in nodes if n.bl_idname in convertable_shaders]

    for t_name in rel_nodes:
        if not (tnode:=nodes.get(t_name)):
            continue #Couldn't find this one, skip

        if len(tnode.outputs[0].links) == 0:
            continue #Output not connected


        #Create a pnode at the same location
        pnode = nodes.new(type='ShaderNodeBsdfPrincipled')
        pnode.location = tnode.location

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfDiffuse":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfGlass":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "IOR", pnode.name, "IOR", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Transmission Weight"].default_value = 1.0
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfAnisotropic": #Actually glossy....???
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "Anisotropy", pnode.name, "Anisotropic", nodes, node_tree)
            process_socket(t_name, "Rotation", pnode.name, "Anisotropic Rotation", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            process_socket(t_name, "Tangent", pnode.name, "Tangent", nodes, node_tree)
            pnode.inputs["Metallic"].default_value = 1.0
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeEmission":
            process_socket(t_name, "Color", pnode.name, "Emission Color", nodes, node_tree)
            process_socket(t_name, "Strength", pnode.name, "Emission Strength", nodes, node_tree)
            pnode.inputs["Base Color"].default_value = (0,0,0,1)
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfTransparent":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            pnode.inputs["Alpha"].default_value = 0
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeSubsurfaceScattering":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Scale", pnode.name, "Subsurface Scale", nodes, node_tree)
            process_socket(t_name, "Radius", pnode.name, "Subsurface Radius", nodes, node_tree)
            process_socket(t_name, "IOR", pnode.name, "IOR", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "Anisotropy", pnode.name, "Subsurface Anisotropy", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Subsurface Weight"].default_value = 1
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfRefraction":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "IOR", pnode.name, "IOR", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Transmission Weight"].default_value = 1.0
            to_del.append(t_name)

        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfToon":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Roughness"].default_value = 1.0
            to_del.append(t_name)



        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfTranslucent":
            process_socket(t_name, "Color", pnode.name, "Emission Color", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Subsurface Weight"].default_value = 1.0
            pnode.inputs["Subsurface Radius"].default_value = (1,1,1)
            to_del.append(t_name)


        #What node are we talking about?
        if tnode.bl_idname == "ShaderNodeBsdfSheen":
            process_socket(t_name, "Color", pnode.name, "Base Color", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Sheen Roughness", nodes, node_tree)
            process_socket(t_name, "Roughness", pnode.name, "Roughness", nodes, node_tree)
            process_socket(t_name, "Normal", pnode.name, "Normal", nodes, node_tree)
            pnode.inputs["Sheen Weight"].default_value = 1.0
            pnode.inputs["Roughness"].default_value = 1.0
            to_del.append(t_name)


        for name in to_del:
            if (n:=nodes.get(name)):
                #Transfer output and remove
                output_dest_socket = n.outputs[0].links[0].to_socket
                node_tree.links.new(pnode.outputs[0], output_dest_socket)
                nodes.remove(n)

    return True



class SimpleBake_OT_PBR_Pre_Bake(Operator):
    """Master backup and remove node groups"""
    bl_idname = "simplebake.pbr_pre_bake"
    bl_label = "Pre bake for PBR (remove node groups)"

    override_target_object_name: StringProperty(default="")

    def pop_node_group(self, context, mat_name):

        material = bpy.data.materials[mat_name]
        node_tree = material.node_tree


        # Find an object using the material
        found_object = None
        for obj in context.scene.objects:
            if material.name in [slot.material.name for slot in obj.material_slots if slot.material]:
                found_object = obj
                break

        if not found_object:
            return False

        # Select and activate the object
        context.view_layer.objects.active = found_object
        for obj in context.selected_objects:
            obj.select_set(False)
        found_object.select_set(True)

        found_space = None
        found_area = None
        found_screen = None
        found_region = None


        for screen in bpy.data.screens:
                for area in screen.areas:
                    if area.type == 'NODE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'NODE_EDITOR' and space.tree_type == 'ShaderNodeTree':
                                for region in area.regions:
                                    if region.type == 'WINDOW':
                                        found_space = space
                                        found_screen = screen
                                        found_area = area
                                        found_region = region
                                        break
                            if found_region:
                                break
                    if found_region:
                        break
                if found_region:
                    break

        # Ensure a Node Editor space was found
        if not found_space or not found_area or not found_screen or not found_region:
            return False

        found_space.node_tree = node_tree


        # Select all node groups
        prefs = get_sb_prefs(context)
        ungroup_all = prefs.ungroup_all_node_groups
        ungroup_all = True if get_list_enabled_aov_names(context) else ungroup_all
        ungroup_all = True if context.scene.SimpleBake_Props.selected_displacement else ungroup_all

        for n in list(node_tree.nodes):
            ss = [s for s in n.outputs if s.bl_idname == "NodeSocketShader"
                and len(s.links)>0]
            if n.bl_idname == "ShaderNodeGroup" and (len(ss)>0 or ungroup_all) and n.select == False:
                create_node_group_dummy_nodes(n, node_tree)
                n.select = True
            else:
                if n.select == True:
                    n.select = False

        with context.temp_override(
            area=found_area,
            screen=found_screen,
            space_data=found_space,
            region=found_region,          # explicit WINDOW region, not blind [-1]
            window=context.window,
            edit_tree=node_tree,
            active_object=found_object
        ):
            bpy.ops.node.group_ungroup()

        blender_refresh()

        return True


    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        #Quick refresh of the bake objects list
        bpy.ops.simplebake.refresh_bake_object_list()

        #Get the list of relevant objects
        if self.override_target_object_name != "":
            objs = [context.scene.objects[self.override_target_object_name]]
        else:
            objs = [l.obj_point for l in sbp.objects_list]

        #Backup of all materials
        #We ALWAYS want a master backup, so put this ahead of any possible return
        for obj in objs:
            bpy.ops.simplebake.material_backup(
                    target_object_name = obj.name,
                    mode = MatManager.MODE_MASTER_BACKUP)

        #Force us into object mode
        force_to_object_mode(context)

        #Get all relevant material names
        mats = []
        for o in objs:
            for slot in o.material_slots:
                if slot.material != None:
                    mats.append(slot.material.name)
        mats = list(set(mats))

        #Do we actually have any node groups at all? Also skip entirely for Cycles bake
        result = False
        for m_name in mats:
            result = True if has_node_groups(context, m_name) else result
            result = True if has_convertible_shaders(m_name) else result

        if not result:
            print_message(context, "No node groups or convertible shaders are in play. Proceeding to bake")
            return{'FINISHED'}
        else:
            print_message(context, "Node groups or convertible shaders detected. Proceeding to remove them")

        for m_name in mats:
            mat = bpy.data.materials[m_name]

            while has_node_groups(context, m_name):

                self.pop_node_group(context, m_name)


        #No more node groups. Swap out the non-PBR nodes that we want to
        prefs = get_sb_prefs(context)
        if not prefs.dont_replace_nonpbr_shaders:
            for m_name in mats:
                swap_shaders_for_p(m_name)


        return {'FINISHED'}





class SimpleBake_OT_PBR_Pre_Bake_Old(Operator):
    """Pre bake actions for PBR (remove node groups)"""
    bl_idname = "simplebake.pbr_pre_bake_old"
    bl_label = "Pre bake for PBR (remove node groups) OLD VERSION"

    _timer = None

    #orig_active_mat_indexes = {}

    original_uitype = None
    slot_index = 0
    object_index = 0
    ready_to_bake = False

    @classmethod
    def go_to_bake(cls):
        pass


    def modal(self, context, event):
        sbp = context.scene.SimpleBake_Props

        if event.type == 'TIMER': #Only respond to timer events

            #We are ready to bake
            if self.__class__.ready_to_bake:
                #Remove timer
                wm = context.window_manager
                wm.event_timer_remove(self._timer)

                #Bake
                self.go_to_bake()

                return {'FINISHED'}

            #Finished - no more objects in list
            if self.__class__.object_index > len(sbp.objects_list)-1:

                #Restore the UI
                context.area.ui_type = self.__class__.original_uitype
                #Bake on next come back
                self.__class__.ready_to_bake = True
                return {'RUNNING_MODAL'}

            #Current obj has more slots, or more objs in list. Either way, press on
            obj = sbp.objects_list[self.__class__.object_index].obj_point
            #If the object we want to work on isn't selected, select it and wait for next timer
            if context.active_object != obj:
                select_only_this(context, obj)
                return {'RUNNING_MODAL'}

            #Object we want must be selected - press on

            l = len(obj.material_slots)
            #We've reached the end of the slots - we are done with this object, set for the next and wait for come back
            if self.__class__.slot_index == l:
                self.__class__.slot_index = 0
                self.__class__.object_index += 1
                print_message(context, f"Finished popping node groups for object '{obj.name}'")
                return {'RUNNING_MODAL'}

            #If the correct mat slot is active, pop the node groups
            elif obj.active_material_index == self.__class__.slot_index:
                mat = obj.material_slots[self.__class__.slot_index].material

                #Ignore empty slot
                if mat == None:
                    self.__class__.slot_index += 1
                    return {'RUNNING_MODAL'}

                print_message(context, f"Popping node groups for material '{mat.name}' in slot {obj.active_material_index} on object '{obj.name}'")
                node_tree = mat.node_tree
                nodes = node_tree.nodes

                for node in nodes:
                    node.select = False

                for node in nodes:
                    if node.bl_idname == "ShaderNodeGroup":
                        #Get all output sockets that are type shader and linked to something
                        prefs = get_sb_prefs(context)
                        ungroup_all = prefs.ungroup_all_node_groups
                        ungroup_all = True if get_list_enabled_aov_names() else ungroup_all
                        ungroup_all = True if context.scene.SimpleBake_Props.selected_displacement else ungroup_all

                        if ungroup_all:
                            ss = [True] #Hacky! :-(
                        else:
                            ss = [s for s in node.outputs if s.bl_idname == "NodeSocketShader" and len(s.links)>0]

                        if len(ss)>0:
                            #We care about this node group node
                            create_node_group_dummy_nodes(node, node_tree)
                            node.select = True
                            nodes.active = node
                            bpy.ops.node.group_ungroup('INVOKE_DEFAULT')
                            break #Just one per cycle or Blender gets grumpy

                if not has_node_groups(context, mat): # Only move on when all node groups are gone
                    self.__class__.slot_index += 1 #Incrament slot index by 1 for next time

                return {'RUNNING_MODAL'}

            #If correct mat slot not set, set it and wait to come back
            else:
                obj.active_material_index = self.__class__.slot_index
                return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        print_message(context, "Falling back to old method for ungrouping node groups (Blender 4.0 bug)")


        #Quick refresh of the bake objects list
        bpy.ops.simplebake.refresh_bake_object_list()

        #Force us into object mode
        force_to_object_mode(context)

        #Get the list of relevant objects
        objs = [l.obj_point for l in sbp.objects_list]

        #Do we actually have any node groups at all? Also skip entirely for Cycles bake
        ngs_present = False
        for obj in objs:
            for slot in obj.material_slots:
                if slot.material != None:
                    if has_node_groups(context, slot.material.name):
                        ngs_present = True
        #Start fresh
        for obj in objs:
            for slot in obj.material_slots:
                if slot.material != None:
                    if "SB_master_dup" in slot.material: del slot.material["SB_master_dup"]


        #Backup of all materials
        #We always want a master backup, so put this ahead of any possible return
        for obj in objs:
            bpy.ops.simplebake.material_backup(
                    target_object_name = obj.name,
                    mode = MatManager.MODE_MASTER_BACKUP)

        if not ngs_present:
            print_message(context, "No node groups are in play. Proceeding to bake")
            self.go_to_bake()
            return{'FINISHED'}

        print_message(context, "Going to process materials to remove node groups")



        #Reset variables
        self.__class__.original_uitype = context.area.ui_type
        self.__class__.slot_index = 0
        self.__class__.object_index = 0
        self.__class__.ready_to_bake = False

        #Set timer and away we go
        context.area.ui_type = "ShaderNodeTree"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}



class SimpleBake_OT_Invert_Roughness_To_Glossy(Operator):
    """Preperation shared by all types of bake"""
    bl_idname = "simplebake.invert_roughness_to_glossy"
    bl_description = "Invert roughness map to create glossy map"
    bl_label = "Invert"
    
    bake_operation_id: StringProperty()
    bake_mode: StringProperty(default="")
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        print_message(context, "Creating glossy image from roughness if required")


        this_bake_glossy_types = []
        if sbp.rough_glossy_switch != SBConstants.PBR_ROUGHNESS:
            print_message(context, "Glossiness map requested")
            this_bake_glossy_types.append(SBConstants.PBR_GLOSSY)
        if sbp.ccrough_glossy_switch != SBConstants.PBR_CLEARCOAT_ROUGH:
            print_message(context, "Clearcoat Glossiness map requested")
            this_bake_glossy_types.append(SBConstants.PBR_CLEARCOAT_GLOSS)

        #Find all images that are glossy bakes
        input_images = ([
            i for i in bpy.data.images if
            "SB_bake_operation_id" in i and
            i["SB_bake_operation_id"] == self.bake_operation_id and
            (("SB_glossy_converted" in i and i["SB_glossy_converted"] == False) or
            "SB_glossy_converted" not in i) and
            "SB_this_bake" in i and i["SB_this_bake"] in this_bake_glossy_types
        ])


        # #If we are being bake_mode specific, then filter for that
        # if self.bake_mode != "":
        #     input_images = [i for i in input_images if "SB_this_bake" in i and i["SB_this_bake"] == self.bake_mode]

        if len(input_images) == 0:
            print_message(context, "Didn't find any glossy images that needed to be converted")
            return {'FINISHED'}


        for input_image in input_images:
            #Will have been saved externally. Maybe udim, maybe not
            # external_path = input_image.filepath
            # print(f"--------------------{external_path}")
            # print(f"--------------------{input_image['SB_full_save_path']}")


            if 'SB_full_save_path' not in input_image:
                print_message(context, f"WARNING: {input_image.name} is missing SB_full_save_path, falling back to filepath")
                external_path = bpy.path.abspath(input_image.filepath)
            else:
                external_path = input_image['SB_full_save_path']

            tiled = True if "<UDIM>" in external_path else False

            # if tiled:
            tiles_nums = [t.number for t in input_image.tiles]
            for tile_num in tiles_nums:
                i = bpy.data.images.load(external_path.replace("<UDIM>", str(tile_num)))
                i.colorspace_settings.name = input_image.colorspace_settings.name
                w, h = i.size
                pixel_data = np.zeros((w, h, 4), 'f')
                # Fast copy of pixel data from bpy.data to numpy array.
                i.pixels.foreach_get(pixel_data.ravel())
                #Invert RGB channels
                pixel_data[:, :, :3] = 1.0 - pixel_data[:, :, :3]
                #Output the result and update
                i.pixels.foreach_set(pixel_data.ravel())
                i.update()
                i.save()
                bpy.data.images.remove(i)

            # else:
            #     #Edit the image directly as it already exists
            #     w, h = input_image.size
            #     pixel_data = np.zeros((w, h, 4), 'f')
            #     input_image.pixels.foreach_get(pixel_data.ravel())
            #     pixel_data[:, :, :3] = 1.0 - pixel_data[:, :, :3]
            #     input_image.pixels.foreach_set(pixel_data.ravel())
            #     input_image.save()

            #Either way, this image isn't caputred again
            input_image.update()
            input_image.reload()
            input_image["SB_glossy_converted"] = True
        
        return {'FINISHED'}

class SimpleBake_OT_Create_Directx_Normal(Operator):
    """Preperation shared by all types of bake"""
    bl_idname = "simplebake.create_directx_normal"
    bl_description = "Flip Y to create DirectX normal map"
    bl_label = "Create"

    bake_operation_id: StringProperty()
    bake_mode: StringProperty(default="")

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        if sbp.normal_format_switch == "OpenGL":
            print_message(context,"No DirectX conversion needed")
            return {'FINISHED'}

        print_message(context, "Creating DirectX normal maps")

        #Find all images that are normal bakes
        input_images = ([
            i for i in bpy.data.images if
            "SB_bake_operation_id" in i and
            i["SB_bake_operation_id"] == self.bake_operation_id and
            (("SB_directx_converted" in i and i["SB_directx_converted"] == False) or
            "SB_directx_converted" not in i) and
            "SB_this_bake" in i and i["SB_this_bake"] == SBConstants.PBR_NORMAL
        ])

        #If we are being bake_mode specific, then filter for that
        if self.bake_mode != "":
            input_images = [i for i in input_images if "SB_this_bake" in i and i["SB_this_bake"] == self.bake_mode]

        if len(input_images) == 0:
            return {'FINISHED'}

        print_message(context, f"DirectX conversion needed for {input_images}")

        for input_image in input_images:
            #Will have been saved externally. Maybe udim, maybe not
            if 'SB_full_save_path' not in input_image:
                print_message(context, f"WARNING: {input_image.name} is missing SB_full_save_path, falling back to filepath")
                external_path = bpy.path.abspath(input_image.filepath)
            else:
                external_path = input_image['SB_full_save_path']

            #tiled = True if "<UDIM>" in external_path else False

            #if tiled:
            tiles_nums = [t.number for t in input_image.tiles]
            for tile_num in tiles_nums:
                i = bpy.data.images.load(external_path.replace("<UDIM>", str(tile_num)))
                i.colorspace_settings.name = input_image.colorspace_settings.name
                w, h = i.size
                pixel_data = np.zeros((w, h, 4), 'f')
                # Fast copy of pixel data from bpy.data to numpy array.
                i.pixels.foreach_get(pixel_data.ravel())
                #Invert G channel
                pixel_data[:, :, 1] = 1.0 - pixel_data[:, :, 1]
                #Output the result and update
                i.pixels.foreach_set(pixel_data.ravel())
                i.save()
                bpy.data.images.remove(i)

            # else:
            #     #Edit the image directly as it already exists
            #     w, h = input_image.size
            #     pixel_data = np.zeros((w, h, 4), 'f')
            #     input_image.pixels.foreach_get(pixel_data.ravel())
            #     #Invert G channel
            #     pixel_data[:, :, 1] = 1.0 - pixel_data[:, :, 1]
            #     input_image.pixels.foreach_set(pixel_data.ravel())
            #     input_image.save()

            #Either way, this image isn't caputred again
            input_image.update()
            input_image.reload()
            input_image["SB_directx_converted"] = True

        return {'FINISHED'}



class SimpleBake_OT_PBR_Specific_Bake_Prep_And_Finish(Operator):
    """Preperation and finishing specific to PBR baking"""
    bl_idname = "simplebake.pbr_specific_bake_prep_and_finish"
    bl_description = "Preperation or Finish for PBR bake type"
    bl_label = "Prepare or Finish"
    
    mode: StringProperty()
    
    orig_sample_count = 0
    
    def finish(self, context):
        #print_message(context, "PBR specific bake finishing actions")
        #Restore original sample count
        context.scene.cycles.samples = self.__class__.orig_sample_count
        
    def prepare(self, context):
        sbp = context.scene.SimpleBake_Props

        #Store original sample count
        self.__class__.orig_sample_count = context.scene.cycles.samples        
        
        #S2A must be off if not S2A
        if not sbp.selected_s2a:
            context.scene.render.bake.use_selected_to_active=False
    
    def execute(self, context):
        if self.mode == "prepare":
            self.prepare(context)
        elif self.mode == "finish":
            self.finish(context)
    
        return {'FINISHED'}

class SimpleBake_OT_Remove_Reroutes(Operator):
    bl_idname = "simplebake.remove_reroutes"
    bl_label = "Remove"
    
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        #Setup
        bpy.ops.simplebake.refresh_bake_object_list()
        force_to_object_mode(context)
        objs = [l.obj_point for l in sbp.objects_list]
        
        for obj in objs:
            for matslot in obj.material_slots:
                mat = matslot.material
                print_message(context, f"Removing reroute nodes for material {mat.name}")
                node_tree = mat.node_tree
                nodes = node_tree.nodes
    
                reroute_nodes = [n for n in nodes if n.bl_idname == "NodeReroute"]
    
                for node in reroute_nodes:
                    #Nothing plugged in
                    if len(node.inputs[0].links) == 0:
                        nodes.remove(node)
                        continue
                    
                    #Otherwise...
                    origin_socket = node.inputs[0].links[0].from_socket #Can only be one input
                    output_links = [l for l in node.outputs[0].links]
        
                    for l in output_links:
                        dest_socket = l.to_socket
                        node_tree.links.new(origin_socket, dest_socket)
        
                #Remove all reroute nodes, as now all bypassed
                [nodes.remove(n) for n in nodes if n.bl_idname == "NodeReroute"]
        return {'FINISHED'}

class SimpleBake_OT_Multiply_AO(Operator):
    """Multiple Diffuse by AO"""
    bl_idname = "simplebake.multiply_ao"
    bl_description = "Multiply Diffuse by AO"
    bl_label = "Multiply"

    bake_operation_id: StringProperty()

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        #Find all diffuse images for this bake operation ID
        diffuse_images = [i for i in bpy.data.images if\
            "SB_bake_operation_id" in i and\
                i["SB_bake_operation_id"] == self.bake_operation_id and\
                    "SB_this_bake" in i and\
                        i["SB_this_bake"] == SBConstants.PBR_DIFFUSE]

        #Find the AO image
        ao_images = [i for i in bpy.data.images if\
            "SB_bake_operation_id" in i and\
                i["SB_bake_operation_id"] == self.bake_operation_id and\
                    "SB_this_bake" in i and\
                        i["SB_this_bake"] == SBConstants.AO]

        #Pair them up (this also works for merged bake, apprently)
        paired = {}
        for d in diffuse_images:
            o = d["SB_bake_object"]
            matched = [a for a in ao_images if "SB_bake_object" in a and a["SB_bake_object"] == o]
            assert(len(matched) == 1), f"Didn't find exactly one matching AO image for {d.name}"
            paired[d] = matched[0]

        #Import the compositing scene that we needed
        path = os.path.dirname(__file__) + "/../resources/multiply.blend/Scene/"
        if "SBCompositing_Multiply" in bpy.data.scenes:
            bpy.data.scenes.remove(bpy.data.scenes["SBCompositing_Multiply"])
        bpy.ops.wm.append(filename="SBCompositing_Multiply", directory=path)

        s = bpy.data.scenes["SBCompositing_Multiply"]
        s.render.resolution_x = diffuse_images[0].size[0]
        s.render.resolution_y = diffuse_images[0].size[1]

        if bpy.app.version >= (5, 0, 0):
            node_tree = s.compositing_node_group
            nodes = s.compositing_node_group.nodes
        else:
            node_tree = s.node_tree
            nodes = node_tree.nodes

        for d in paired:

            #Set up our scene
            #Get some settings
            if "SB_bit_depth" not in d or "SB_channels" not in d or "SB_view_transform" not in d:
                print_message(context, f"WARNING: {d.name} is missing external save metadata, skipping diffuse x AO multiply")
                continue
            s.render.image_settings.file_format = d.file_format
            s.render.image_settings.color_depth = d["SB_bit_depth"]
            s.render.image_settings.color_mode = d["SB_channels"]
            s.view_settings.view_transform = d["SB_view_transform"]


            tiles_nums = [t.number for t in d.tiles]
            for tile_num in tiles_nums:
                path_d = d.filepath.replace("<UDIM>", str(tile_num))
                path_ao = paired[d].filepath.replace("<UDIM>", str(tile_num))

                #Load the tiles in as an individual images
                img_d = bpy.data.images.load(path_d.replace("<UDIM>", str(tile_num)))
                img_ao = bpy.data.images.load(path_ao.replace("<UDIM>", str(tile_num)))

                #Setup the nodes
                nodes["Base"].image = img_d
                nodes["Multiplant"].image = img_ao
                nodes["Mix"].inputs[0].default_value = (sbp.multiply_diffuse_ao_percent/100)

                #Render and get result
                bpy.ops.render.render(use_viewport=False, scene=s.name)
                render_result_image = bpy.data.images["Render Result"]

                #File should already exist. Remove it or will silently fail.
                if os.path.exists(bpy.path.abspath(path_d)):
                    os.remove(bpy.path.abspath(path_d))

                #Save this over the file path of the tile image
                #Only seems to work for abspath?
                path_d = bpy.path.abspath(path_d)
                render_result_image.save_render(path_d.replace("<UDIM>", str(tile_num)), scene=s)

                #Remove the tile image we loaded individually
                bpy.data.images.remove(img_d)
                bpy.data.images.remove(img_ao)

            #All tiles done for this image, reload the UDIM image
            d.reload() #We've updated 1 or more tiles and Blender still has them in the buffer'
            d.save()
            #img["SB_denoised"] = True

            #transfer_tags(img, new_img)

        #All done
        [bpy.data.scenes.remove(s) for s in bpy.data.scenes if s.name == "SBCompositing_Multiply"]

        return {'FINISHED'}


class SimpleBake_OT_autodetect_pbr_channels(Operator):
    bl_idname = "simplebake.autodetect_pbr_channels"
    bl_label = "Autodetect"
    bl_description = "Try to identify the necessary maps based on the materials applied to your selected bake objects. If your materials are disorganized (e.g., disconnected nodes not connected to the material output), it might suggest more maps than needed. It should not suggest fewer maps than necessary."

    default_values = {
        "Base Color": (0.8,0.8,0.8,1),
        "Metallic": 0.0,
        "Roughness": 0.5,
        "Alpha": 1.0,
        "Subsurface Weight": 0.0,
        "Transmission Weight": 0.0,
        "Coat Weight": 0.0,
        "Coat Roughness": 0.0,
        "Emission Color": (1,1,1,1),
        "Emission Strength": 0.0,
        "Specular IOR Level": 0.5
        }


    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        #Sidestep
        bpy.ops.simplebake.sidestep_geo_nodes()

        #Clear the bake types list
        #bpy.ops.simplebake.selectnone_pbr()

        #Get a list of objects
        o_names = object_list_to_names_list(context)

        bpy.ops.simplebake.pbr_pre_bake()

        #Add target object if it's not none and we are in DECALS mode
        if sbp.selected_s2a and sbp.targetobj!=None and sbp.s2a_opmode=="decals":
            bpy.ops.simplebake.pbr_pre_bake(override_target_object_name=sbp.targetobj.name)
            o_names.append(sbp.targetobj.name)

        #Get all materials
        mat_names = []
        for name in o_names:
            o = context.scene.objects.get(name)
            if o!=None:
                for slot in o.material_slots:
                    if slot.material != None:
                        mat_names.append(slot.material.name)

        found_socket_names = []
        def check_node_tree(node_tree):
            nodes = node_tree.nodes
            for n in nodes:
                if n.bl_idname == "ShaderNodeGroup":
                    check_node_tree(n.node_tree)

                if n.bl_idname == "ShaderNodeBsdfPrincipled" and len(n.outputs[0].links)>0:
                    for i in n.inputs:

                        #Something plugged in
                        if len(i.links)>0:
                            test=None
                            from_n = i.links[0].from_node
                            if i.bl_idname in ["NodeSocketFloatFactor", "NodeSocketFloat"]:
                                if from_n.bl_idname == "ShaderNodeValue":
                                    test = round(from_n.outputs[0].default_value, 1)
                            if i.bl_idname == "NodeSocketColor":
                                if from_n.bl_idname == "ShaderNodeRGB":
                                    dv = from_n.outputs[0].default_value
                                    test = (round(dv[0], 1),round(dv[1], 1),round(dv[2], 1),round(dv[3], 1))

                            if test!=None and i.name in self.default_values and test == self.default_values[i.name]:
                                pass
                            else:
                                found_socket_names.append(i.name)

                        #Nothing plugged in, but default value may have changed
                        else:
                            test=None
                            if i.bl_idname == "NodeSocketColor":
                                dv = i.default_value
                                test = (round(dv[0], 1),round(dv[1], 1),round(dv[2], 1),round(dv[3], 1))
                            elif i.bl_idname in ["NodeSocketFloatFactor", "NodeSocketFloat"]:
                                test = round(i.default_value, 1)

                            if test!=None and i.name in self.default_values and test != self.default_values[i.name]:
                                found_socket_names.append(i.name)

                if n.bl_idname == "ShaderNodeBump" and len(n.outputs[0].links)>0:
                    #Just assume we need it if it's there and plugged in
                    found_socket_names.append("Bump")

        for name in mat_names:
            m = bpy.data.materials.get(name)
            if m!=None:
                check_node_tree(m.node_tree)

                #And a special check for displacement
                mos = [n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output == True]
                for mo in mos:
                    if len(mo.inputs["Displacement"].links)>0:
                        found_socket_names.append("Displacement")


        sbp.selected_col = True if "Base Color" in found_socket_names else False
        sbp.selected_metal = True if "Metallic" in found_socket_names else False
        sbp.selected_rough = True if "Roughness" in found_socket_names else False
        sbp.selected_trans = True if "Transmission Weight" in found_socket_names else False
        sbp.selected_clearcoat = True if "Coat Weight" in found_socket_names else False
        sbp.selected_clearcoat_rough = True if "Coat Roughness" in found_socket_names else False
        sbp.selected_emission = True if "Emission Color" in found_socket_names else False
        sbp.selected_emission_strength = True if "Emission Strength" in found_socket_names else False
        sbp.selected_specular = True if "Specular IOR Level" in found_socket_names else False
        sbp.selected_sss = True if "Subsurface Weight" in found_socket_names else False
        sbp.selected_sss_scale = True if "Subsurface Scale" in found_socket_names else False
        sbp.selected_alpha = True if "Alpha" in found_socket_names else False
        sbp.selected_normal = True if "Normal" in found_socket_names else False
        sbp.selected_bump = True if "Bump" in found_socket_names else False
        sbp.selected_displacement = True if "Displacement" in found_socket_names else False

        bpy.ops.simplebake.material_backup(mode="working_restore")
        bpy.ops.simplebake.material_backup(mode="master_restore")

        #Reverse sidestep
        bpy.ops.simplebake.reverse_geo_nodes_sidestep()

        return {'FINISHED'}

class SimpleBake_OT_Sidestep_Geo_Nodes(Operator):



    bl_idname = "simplebake.sidestep_geo_nodes"
    bl_label = "Go"
    bl_description = "Replace objects with geo nodes with an applied proxy"

    #decals_target_name: StringProperty(default="")

    def execute(self, context):


        sbp = context.scene.SimpleBake_Props
        #decals = True if self.decals_target_name!="" else False

        # #Start fresh
        # for o in context.scene.objects:
        #     if "SB_proxy_bake_object" in o:
        #         del o["SB_proxy_bake_object"]
        #     if "SB_replaced_orig_name" in o:
        #         del o["SB_replaced_orig_name"]


        object_names = [i.name for i in sbp.objects_list]
        if sbp.selected_s2a and sbp.targetobj != None:
            object_names.append(sbp.targetobj.name)
            sbp.targetobj["SB_sidestepd_orig_target"] = True
        if sbp.cycles_s2a and sbp.targetobj_cycles != None:
            object_names.append(sbp.targetobj_cycles.name)
            sbp.targetobj_cycles["SB_sidestepd_orig_target"] = True


        # List to store new objects
        new_objects = []

        for obj_name in object_names:
            obj = bpy.data.objects.get(obj_name)

            if not obj:
                continue

            # Check if the object has any geometry node modifiers
            geo_modifiers = [mod for mod in obj.modifiers if mod.type == 'NODES']

            #Are we interested in this object?
            if not geo_modifiers:
                continue

            #Record the name
            orig_name = obj.name

            #Remove the original object from the bake list if it's there
            i = sbp.objects_list.find(orig_name)
            if i!=-1:
                sbp.objects_list.remove(i)

            # Duplicate the object
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            bpy.context.collection.objects.link(new_obj)

            # Hide the original object from rendering
            obj.hide_render = True

            # Tags
            new_obj["SB_proxy_bake_object"] = orig_name
            obj["SB_replaced_orig_name"] = orig_name

            # Add the new object to the list
            new_objects.append(new_obj)

            #Steal the original objects's name
            obj.name = f"SB_sidestepd"
            new_obj.name = orig_name

            #Add our new object to the bake list in it's place (unless it was decals target)
            if "SB_sidestepd_orig_target" not in new_obj:
#            if not decals:
                bpy.ops.simplebake.add_bake_object_by_name(override_target_obj_name=f"{new_obj.name}")
            else:
                #Change the target object to proxy instead
                if sbp.selected_s2a:
                    sbp.targetobj = new_obj
                if sbp.cycles_s2a:
                    sbp.targetobj_cycles = new_obj

            #Make sure new object is visible for rendering
            new_obj.hide_render = False


        for new_obj in new_objects:
            # Loop over each geometry node modifier and try to apply it
            #geo_modifiers = [mod for mod in new_obj.modifiers if mod.type == 'NODES']

            select_only_this(context, new_obj)
            bpy.ops.object.convert(target='MESH')

            # #for mod in geo_modifiers:
            # for mod in new_obj.modifiers:
            #     try:
            #         if mod.show_render:
            #             # Try to apply the modifier
            #             bpy.context.view_layer.objects.active = new_obj
            #             bpy.ops.object.modifier_apply(modifier=mod.name)
            #         else:
            #             new_obj.modifiers.remove(mod)
            #     except Exception as e:
            #         # Remove the modifier if application fails
            #         new_obj.modifiers.remove(mod)

        for new_obj in new_objects:
            materials_to_remove = []
            # Iterate through material slots
            for i, mat_slot in enumerate(new_obj.material_slots):
                # Check if the material is used by any face
                material_used = False
                for poly in new_obj.data.polygons:
                    if poly.material_index == i:
                        material_used = True
                        break
                # If the material is not used, mark it for removal
                if not material_used:
                    materials_to_remove.append(i)

            #Cannot beleive we have to do a context override just to remove mat slot
            # Create a context override dictionary
            override = {
                'object': new_obj,
                'active_object': new_obj,
                'selected_objects': [new_obj],
                'selected_editable_objects': [new_obj],
                'window': bpy.context.window,
                'screen': bpy.context.screen,
                'area': None,
                'region': None
            }

            # Look for the Properties editor with the 'MATERIAL' context
            for area in bpy.context.screen.areas:
                if area.type == 'PROPERTIES':
                    override['area'] = area
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override['region'] = region
                    for space in area.spaces:
                        if space.type == 'PROPERTIES' and space.context == 'MATERIAL':
                            override['space_data'] = space
                            break
                    break

            # Remove the materials that aren't used
            for index in reversed(materials_to_remove):
                new_obj.active_material_index = index
                with bpy.context.temp_override(**override):
                    bpy.ops.object.material_slot_remove()


        return {'FINISHED'}

class SimpleBake_OT_Reverse_Geo_Nodes_Sidestep(Operator):
    bl_idname = "simplebake.reverse_geo_nodes_sidestep"
    bl_label = "Go"
    bl_description = "Reverse the side stepping of objects with geo nodes"

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        to_del = []
        for o in context.scene.objects:
            if "SB_proxy_bake_object" in o:

                #Remove from bake object list
                i = sbp.objects_list.find(o.name)
                if i!=-1:
                    sbp.objects_list.remove(i)

                o.name = "SB_to_del"
                to_del.append(o.name)


        for o in context.scene.objects:
            if "SB_replaced_orig_name" in o:
                #Restore original name
                o.name = o["SB_replaced_orig_name"]

                #Restore to bake objects list
                if sbp.objects_list.find(o.name) == -1 and "SB_sidestepd_orig_target" not in o:
                    bpy.ops.simplebake.add_bake_object_by_name(override_target_obj_name=f"{o.name}")

                #Make sure to unhide for rendering
                o.hide_render = False

                #Remove tag
                del o["SB_replaced_orig_name"]



        for td in to_del:
            if o:= bpy.data.objects.get(td):
                bpy.data.objects.remove(o)

        for o in context.scene.objects: #Only works AFTER to_del objects have been deleted
            if "SB_sidestepd_orig_target" in o:
                sbp.targetobj = o
                del o["SB_sidestepd_orig_target"]

        # #Let's be sure
        # for o in context.scene.objects:
        #     if "SB_proxy_bake_object" in o:
        #         del o["SB_proxy_bake_object"]
        #     if "SB_replaced_orig_name" in o:
        #         del o["SB_replaced_orig_name"]

        return {'FINISHED'}


classes = ([
    SimpleBake_OT_Invert_Roughness_To_Glossy,
    SimpleBake_OT_Create_Directx_Normal,
    SimpleBake_OT_PBR_Specific_Bake_Prep_And_Finish,
    SimpleBake_OT_PBR_Pre_Bake,
    SimpleBake_OT_PBR_Pre_Bake_Old,
    SimpleBake_OT_Remove_Reroutes,
    SimpleBake_OT_Multiply_AO,
    SimpleBake_OT_autodetect_pbr_channels,
    SimpleBake_OT_Sidestep_Geo_Nodes,
    SimpleBake_OT_Reverse_Geo_Nodes_Sidestep
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
