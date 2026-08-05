import bpy 
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

import os
import sys

from .utils import SBConstants
from .messages import print_message
from .background_and_progress import BakeInProgress as Bip

def remove_and_bypass_invert_node(material_name, invert_node_name):
    # Get the material
    mat = bpy.data.materials.get(material_name)
    if not mat:
        print(f"Material '{material_name}' not found")
        return

    # Ensure the material uses nodes
    if not mat.use_nodes:
        print(f"Material '{material_name}' does not use nodes")
        return

    # Get the node tree of the material
    nodes = mat.node_tree.nodes

    # Find the specified invert node by name
    invert_node = nodes.get(invert_node_name)
    if not invert_node:
        print(f"Invert node named '{invert_node_name}' not found")
        return
    if invert_node.type != 'INVERT':
        print(f"The node named '{invert_node_name}' is not an invert node")
        return

    # Check the input connections to the invert node
    if invert_node.inputs['Color'].is_linked:
        input_link = invert_node.inputs['Color'].links[0].from_socket
    else:
        return

    # Check the output connections from the invert node
    if invert_node.outputs['Color'].is_linked:
        # There could be multiple links, handle each one
        output_links = invert_node.outputs['Color'].links
        for link in output_links:
            # Connect each linked output to the original input link's socket
            mat.node_tree.links.new(input_link, link.to_socket)
    else:
        return

    # Delete the invert node
    nodes.remove(invert_node)

def create_aov_nodes(node_tree, bake_operation_id, obj, merged_bake=False):

    #Find them all
    aov_images = []
    for i in bpy.data.images:
        if "SB_this_bake" in i and "SB_bake_operation_id" in i:
            if i["SB_bake_operation_id"] ==  bake_operation_id and "AOV_" in i["SB_this_bake"]:
                aov_images.append(i)

    #If this isn't a merged bake we only want the images for this object
    if not merged_bake:
        aov_images = [img for img in aov_images if img['SB_bake_object'] == obj['SB_copy_and_apply_from']]

    #Keep this names only
    aov_images = [img.name for img in aov_images]


    #Find MO node
    mo_node = [n for n in node_tree.nodes if n.bl_idname == 'ShaderNodeOutputMaterial' and n.is_active_output]
    assert(len(mo_node)==1)
    mo_node = mo_node[0]

    base_x, base_y = mo_node.location

    i=0
    for aov in aov_images:
        img = bpy.data.images.get(aov)
        if not img:
            continue

        img_node = node_tree.nodes.new("ShaderNodeTexImage")
        img_node.hide = True  # collapsed
        img_node.location = (base_x, base_y - 160 - i * 40)
        img_node.image = img
        i+=1


class SimpleBake_OT_Apply_Bakes_To_Original(Operator):
    """Apply the baked textures to the original objects"""
    bl_idname = "simplebake.apply_bakes_to_original"
    bl_description = "Apply the baked textures to the original objects"
    bl_label = "Apply bakes to original"

    bake_operation_id: StringProperty()

    def execute(self, context):

        if not Bip.Sequence.should_run_teardown():
            return {'FINISHED'} #Nope out if this is part of a sequence unless last

        for m in bpy.data.materials:
            if ("SB_baked_orig_objects" in m) and ("SB_bake_operation_id" in m):
                if m["SB_bake_operation_id"] == self.bake_operation_id:
                    os = list(m["SB_baked_orig_objects"])
                    for o_name in os:
                        if (obj:=context.scene.objects.get(o_name)):

                            actual_obj = None
                            #Is this a proxy object for sidestep?
                            if "SB_proxy_bake_object" in obj:
                                actual_obj_name = obj["SB_proxy_bake_object"]

                                #Find a sidestepped object with this tag
                                for o in context.scene.objects:
                                    if "SB_replaced_orig_name" in o and o["SB_replaced_orig_name"] == actual_obj_name:
                                        actual_obj = o
                            else:
                                actual_obj = obj

                            if actual_obj == None:
                                print_message(context, "ERROR: Apply bakes to original object operator couldn't locate original object!!")
                                return {'CANCELLED'}

                            for slot in actual_obj.material_slots:
                                slot.material = m
        return {'FINISHED'}

                
class SimpleBake_OT_Copy_And_Apply(Operator):
    """Copy the baked objects and apply baked textures"""
    bl_idname = "simplebake.copy_and_apply"
    bl_description = "Copy baked objects and apply bakes"
    bl_label = "Copy and apply"
    
    target_object_name: StringProperty()
    bake_operation_id: StringProperty()
    global_mode: StringProperty()
    decals_override: BoolProperty(default=False)

    def import_cyclesbake_mat_setup(self, context, new_obj, merged=False):


        if self.cyclesbake_mat_format == "emission":
            import_mat_name = "SB_cyclesbake_e"
        elif self.cyclesbake_mat_format == "background":
            import_mat_name = "SB_cyclesbake_b"
        else:
            import_mat_name = "SB_cyclesbake_p"

        rm_list = [mat.name for mat in bpy.data.materials if mat.name == import_mat_name]
        for rm_name in rm_list:
            mat = bpy.data.materials.get(rm_name)
            if mat != None:
                bpy.data.materials.remove(mat)

        path = os.path.dirname(__file__) + "/resources/copy_and_apply_mats.blend/Material/"
        bpy.ops.wm.append(filename=import_mat_name, directory=path)
        mat = bpy.data.materials[import_mat_name]
        
        if merged:
            mat.name = f"{self.merged_bake_name}_Baked"
            mat["SB_bake_operation_id"] = self.bake_operation_id
            mat["SB_merged_copy_and_apply_mat"] = True
        elif not self.mat_only:
            mat.name = f"{new_obj.name}" #Already includes "_baked"
        else:
            mat.name = f"{self.target_object_name}_baked"

        if new_obj !=None:
            #Assign to object
            new_obj.data.materials.append(mat)

        return mat

    
    def import_pbr_mat_setup(self, context, new_obj, merged=False):
        sbp = context.scene.SimpleBake_Props
        
        #Decals
        if self.decals_override:
            if self.used_directx:
                import_mat_name = "SB_pbr_directx_decals"
            else:
                import_mat_name = "SB_standard_pbr_decals"

        #Not decals
        else:
            if self.used_directx:
                import_mat_name = "SB_pbr_directx"
            else:
                import_mat_name = "SB_standard_pbr"
        

        #Import the PBR node setup that we need and assign to object
        rm_list = [mat.name for mat in bpy.data.materials if mat.name == import_mat_name]
        for rm_name in rm_list:
            mat = bpy.data.materials.get(rm_name)
            if mat != None:
                bpy.data.materials.remove(mat)


        path = os.path.dirname(__file__) + "/resources/copy_and_apply_mats.blend/Material/"
        bpy.ops.wm.append(filename=import_mat_name, directory=path)
        mat = bpy.data.materials[import_mat_name]
        
        #Deal with the case where the user has selected glossy
        if not self.used_glossy:
            remove_and_bypass_invert_node(import_mat_name, "invert_roughgloss")
            remove_and_bypass_invert_node(import_mat_name, "decal_invert_roughgloss")
        if not self.used_ccglossy:
            remove_and_bypass_invert_node(import_mat_name, "invert_ccroughgloss")
            remove_and_bypass_invert_node(import_mat_name, "decal_invert_ccroughgloss")

        if self.used_glossy:
            gns = [n for n in mat.node_tree.nodes if n.label == SBConstants.PBR_ROUGHNESS]
            for n in gns:
                n.label = SBConstants.PBR_GLOSSY
            gns = [n for n in mat.node_tree.nodes if n.label == f"Decal_{SBConstants.PBR_ROUGHNESS}"]
            for n in gns:
                n.label = f"Decal_{SBConstants.PBR_GLOSSY}"

        if self.used_ccglossy:
            gns = [n for n in mat.node_tree.nodes if n.label == SBConstants.PBR_CLEARCOAT_ROUGH]
            for n in gns:
                n.label = SBConstants.PBR_CLEARCOAT_GLOSS
            gns = [n for n in mat.node_tree.nodes if n.label == f"Decal_{SBConstants.PBR_CLEARCOAT_ROUGH}"]
            for n in gns:
                n.label = f"Decal_{SBConstants.PBR_CLEARCOAT_GLOSS}"

        #Assign to object
        if new_obj != None:
            new_obj.data.materials.append(mat)
        
        if merged:
            mat.name = f"{self.merged_bake_name}_Baked"
            mat["SB_bake_operation_id"] = self.bake_operation_id
            mat["SB_merged_copy_and_apply_mat"] = True
        elif not self.mat_only:
            mat.name = f"{new_obj.name}" #Already includes "_baked"
        else:
            mat.name = f"{self.target_object_name}_baked"

        #If we are baking alpha or transparency, set the blend mode
        if sbp.selected_alpha or sbp.selected_trans:
            mat.blend_method = "BLEND"

        return mat
        
    def create_cyclesbake_setup(self, context, new_obj):
        mat = self.import_cyclesbake_mat_setup(context, new_obj)
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        #The non-specials texture
        tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                and i["SB_bake_operation_id"] == self.bake_operation_id
                and "SB_this_bake" in i and i["SB_this_bake"] not in SBConstants.ALL_SPECIALS
                and i["SB_bake_object"] == self.target_object_name
                ])
        assert len(tex) == 1
        tex = tex[0]
        
        node = [n for n in nodes if n.label=="cyclesbake"]
        assert len(node) == 1
        node = node[0]
        node.image = tex
        
        #The specials textures
        for bake_type in SBConstants.ALL_SPECIALS:
            node = [n for n in nodes if n.label==bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                            and i["SB_bake_operation_id"] == self.bake_operation_id
                            and "SB_this_bake" in i and i["SB_this_bake"] == bake_type
                            and i["SB_bake_object"] == self.target_object_name
                            ])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)
        return mat
    
    def create_cyclesbake_setup_merged(self, context, new_obj):
        
        #Check if we already have the merged texture
        for mat in bpy.data.materials:
            if "SB_merged_copy_and_apply_mat" in mat\
                    and "SB_bake_operation_id" in mat\
                    and mat["SB_bake_operation_id"] == self.bake_operation_id:
                #Assign existing merged mat to object and leave
                new_obj.data.materials.append(mat)
                return mat
#
#         mat_name = f"{self.merged_bake_name}_Baked"
#         if mat_name in bpy.data.materials:
#             mat = bpy.data.materials[mat_name]
#             if "SB_bake_operation_id" in mat and mat["SB_bake_operation_id"] == self.bake_operation_id:
#                 mat = bpy.data.materials[mat_name]
#                 #Assign existing merged mat to object and leave
#                 if new_obj != None:
#                     new_obj.data.materials.append(mat)
#                 return mat
        
        mat = self.import_cyclesbake_mat_setup(context, new_obj, merged=True)
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        #The non-specials texture
        tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                and i["SB_bake_operation_id"] == self.bake_operation_id
                and "SB_this_bake" in i and i["SB_this_bake"] not in SBConstants.ALL_SPECIALS
                ])
        assert len(tex) == 1
        tex = tex[0]
        
        node = [n for n in nodes if n.label=="cyclesbake"]
        assert len(node) == 1
        node = node[0]
        node.image = tex
        
        #The specials textures
        for bake_type in SBConstants.ALL_SPECIALS:
            node = [n for n in nodes if n.label==bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                            and i["SB_bake_operation_id"] == self.bake_operation_id
                            and "SB_this_bake" in i and i["SB_this_bake"] == bake_type])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)
        return mat

    def create_pbrdecal_setup(self, context, new_obj):


        BAKE_OP_PREFIX = "DECALSBASE_"
        #Called with the prefix. S2A textures will NOT have the prefix


        #Setup
        mat = self.import_pbr_mat_setup(context, new_obj)
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        bake_types = SBConstants.ALL_PBR_MODES #Every possible bake mode for PBR
        bake_types += SBConstants.ALL_SPECIALS #Every possible bake mode for specials


        #Find the master decal alpha
        decal_alpha_tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i
                            and i["SB_bake_operation_id"]== self.bake_operation_id.replace(BAKE_OP_PREFIX, "") and
                            "SB_this_bake" in i and i["SB_this_bake"] == SBConstants.PBR_ALPHA and
                            "SB_global_mode" in i and i["SB_global_mode"] == SBConstants.PBRS2A
                           ])
        assert(len(decal_alpha_tex)==1)
        node = [n for n in nodes if n.label=="Master_Decal_Alpha"]
        assert(len(node)==1)
        node[0].image = decal_alpha_tex[0]


        #Now the base/target object PBR textures:
        for bake_type in bake_types:
            node = [n for n in nodes if n.label==bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i and
                            i["SB_bake_operation_id"] == self.bake_operation_id and
                            "SB_this_bake" in i and i["SB_this_bake"] == bake_type and
                            "SB_bake_object" in i and i["SB_bake_object"] == self.target_object_name])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)



        # #Now the Decal/S2A textures:
        for bake_type in bake_types:
            node = [n for n in nodes if n.label=="Decal_" + bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i and
                            i["SB_bake_operation_id"] == self.bake_operation_id.replace(BAKE_OP_PREFIX, "") and
                            "SB_this_bake" in i and i["SB_this_bake"] == bake_type and
                            "SB_bake_object" in i and i["SB_bake_object"] == self.target_object_name])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)

        #Now get rid of the unused MixRGB nodes
        mnodes = [n for n in nodes if n.bl_idname == "ShaderNodeMix"]
        for mnode in mnodes:
            a_color_input = [i for i in mnode.inputs if i.identifier=="A_Color"][0]
            #factor_float_input = [i for i in mnode.inputs if i.identifier=="Factor_Float"][0]
            #color_output = [o for o in mnode.outputs if o.identifier=="Result_Color"][0]

            if len(a_color_input.links) == 0:
                #fsocket = factor_float_input.links[0].from_socket
                #tsocket = color_output.links[0].to_socket
                #node_tree.links.new(fsocket, tsocket)
                nodes.remove(mnode)

        #Finally the AOVs
        create_aov_nodes(node_tree, self.bake_operation_id, new_obj)

        return mat
        
        
    def create_pbr_setup_tex_per_mat(self, context, new_obj):
        """Create one PBR material per original material slot using per-material baked images."""
        source_obj = context.scene.objects[self.target_object_name]
        original_mat_only = self.mat_only
        self.mat_only = True  # Prevent import_pbr_mat_setup crashing when new_obj is None

        # Save face→material-slot mapping from the source before create_object()'s
        # materials.clear() resets all polygon material_index values to 0.
        if new_obj is not None:
            face_mat_indices = [p.material_index for p in source_obj.data.polygons]

        mats = []
        for slot in source_obj.material_slots:
            if slot.material is None:
                continue
            # master_restore has not run yet when copy_and_apply is called, so slot names
            # still carry the "SBM_" prefix — strip it to match the SB_bake_material tag.
            mat_name = slot.material.name
            if mat_name.startswith("SBM_"):
                mat_name = mat_name[4:]

            mat = self.import_pbr_mat_setup(context, new_obj=None)
            mat.name = f"{self.target_object_name}_{mat_name}_Baked"

            node_tree = mat.node_tree
            nodes = node_tree.nodes

            bake_types = SBConstants.ALL_PBR_MODES + SBConstants.ALL_SPECIALS
            for bake_type in bake_types:
                node = [n for n in nodes if n.label == bake_type]
                if not node:
                    continue
                node = node[0]

                tex = [i for i in bpy.data.images if
                       i.get("SB_bake_operation_id") == self.bake_operation_id and
                       i.get("SB_this_bake") == bake_type and
                       i.get("SB_bake_object") == self.target_object_name and
                       i.get("SB_bake_material") == mat_name]

                if len(tex) == 1:
                    node.image = tex[0]
                else:
                    nodes.remove(node)

            create_aov_nodes(node_tree, self.bake_operation_id, new_obj)

            if new_obj is not None:
                new_obj.data.materials.append(mat)
            mats.append(mat)

        # Restore face→material-slot assignments now that the baked materials are in place.
        if new_obj is not None:
            for poly, idx in zip(new_obj.data.polygons, face_mat_indices):
                poly.material_index = idx

        self.mat_only = original_mat_only
        return mats

    def create_cyclesbake_setup_tex_per_mat(self, context, new_obj):
        """Create one CyclesBake material per original material slot using per-material baked images."""
        source_obj = context.scene.objects[self.target_object_name]
        original_mat_only = self.mat_only
        self.mat_only = True  # Prevent import_cyclesbake_mat_setup crashing when new_obj is None

        # Save face→material-slot mapping from the source before create_object()'s
        # materials.clear() resets all polygon material_index values to 0.
        if new_obj is not None:
            face_mat_indices = [p.material_index for p in source_obj.data.polygons]

        mats = []
        for slot in source_obj.material_slots:
            if slot.material is None:
                continue
            # master_restore has not run yet when copy_and_apply is called, so slot names
            # still carry the "SBM_" prefix — strip it to match the SB_bake_material tag.
            mat_name = slot.material.name
            if mat_name.startswith("SBM_"):
                mat_name = mat_name[4:]

            mat = self.import_cyclesbake_mat_setup(context, new_obj=None)
            mat.name = f"{self.target_object_name}_{mat_name}_Baked"

            node_tree = mat.node_tree
            nodes = node_tree.nodes

            # Non-specials cyclesbake image — per material
            tex = [i for i in bpy.data.images if
                   i.get("SB_bake_operation_id") == self.bake_operation_id and
                   i.get("SB_this_bake") not in SBConstants.ALL_SPECIALS and
                   i.get("SB_bake_object") == self.target_object_name and
                   i.get("SB_bake_material") == mat_name]
            if len(tex) == 1:
                node = [n for n in nodes if n.label == "cyclesbake"]
                if node:
                    node[0].image = tex[0]

            for bake_type in SBConstants.ALL_SPECIALS:
                node = [n for n in nodes if n.label == bake_type]
                if not node:
                    continue
                node = node[0]
                spec_tex = [i for i in bpy.data.images if
                            i.get("SB_bake_operation_id") == self.bake_operation_id and
                            i.get("SB_this_bake") == bake_type and
                            i.get("SB_bake_object") == self.target_object_name and
                            i.get("SB_bake_material") == mat_name]
                if len(spec_tex) == 1:
                    node.image = spec_tex[0]
                else:
                    nodes.remove(node)

            if new_obj is not None:
                new_obj.data.materials.append(mat)
            mats.append(mat)

        # Restore face→material-slot assignments now that the baked materials are in place.
        if new_obj is not None:
            for poly, idx in zip(new_obj.data.polygons, face_mat_indices):
                poly.material_index = idx

        self.mat_only = original_mat_only
        return mats

    def create_pbr_setup(self, context, new_obj):

        
        mat = self.import_pbr_mat_setup(context, new_obj)
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        bake_types = SBConstants.ALL_PBR_MODES #Every possible bake mode for PBR
        bake_types += SBConstants.ALL_SPECIALS #Every possible bake mode for specials
        #Set the textures
        for bake_type in bake_types:
            node = [n for n in nodes if n.label==bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                            and i["SB_bake_operation_id"] == self.bake_operation_id
                            and "SB_this_bake" in i and i["SB_this_bake"] == bake_type
                            and "SB_bake_object" in i and i["SB_bake_object"] == self.target_object_name])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)

        #Finally the AOVs
        create_aov_nodes(node_tree, self.bake_operation_id, new_obj)

        return mat
        
    def create_pbr_setup_merged(self, context, new_obj):


        #Should be the only material with our bake id
        for mat in bpy.data.materials:
            if "SB_merged_copy_and_apply_mat" in mat\
                    and "SB_bake_operation_id" in mat\
                    and mat["SB_bake_operation_id"] == self.bake_operation_id:
                #Assign existing merged mat to object and leave
                new_obj.data.materials.append(mat)
                return mat
        

                
        #No existing merged bake material
        mat = self.import_pbr_mat_setup(context, new_obj, merged=True)
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        bake_types = SBConstants.ALL_PBR_MODES #Every possible bake mode for PBR
        bake_types += SBConstants.ALL_SPECIALS #Every possible bake mode for specials
        #Set the textures
        for bake_type in bake_types:
            node = [n for n in nodes if n.label==bake_type]
            if len(node) == 0: continue #E.g. Glossy will not be there for standard
            else: node = node[0]
            tex = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                            and i["SB_bake_operation_id"] == self.bake_operation_id
                            and "SB_this_bake" in i and i["SB_this_bake"] == bake_type
                            and "SB_merged_bake" in i and i["SB_merged_bake"] == True
                            and "SB_merged_bake_name" in i and i["SB_merged_bake_name"] == self.merged_bake_name
                            ])
            if len(tex) == 1:
                tex = tex[0]
                node.image = tex
            else:
                nodes.remove(node)
        
        #Finally the AOVs
        create_aov_nodes(node_tree, self.bake_operation_id, new_obj, merged_bake=True)

        return mat
        
    def hook_up_glTF_node(self, context, mat):
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        glTF_node = [n for n in nodes if n.label == "gltf"]
        assert(len(glTF_node))
        glTF_node = glTF_node[0]
        
        target_option = self.glTF_option
        
        target_node = [n for n in nodes if n.label == target_option]
        assert(len(target_node))
        target_node = target_node[0]
            
        node_tree.links.new(target_node.outputs[0], glTF_node.inputs[0])
            
    def create_object(self,context):
        sbp = context.scene.SimpleBake_Props

        source_obj = context.scene.objects[self.target_object_name]

        if (source_obj.name + "_Baked") in context.scene.objects:
            bpy.data.objects.remove(context.scene.objects[source_obj.name + "_Baked"])

        new_obj = source_obj.copy()
        new_obj.data = source_obj.data.copy()

        new_obj["SB_copy_and_apply_from"] = source_obj.name
        new_obj["SB_bake_operation_id"] = self.bake_operation_id

        new_obj.name = source_obj.name + "_Baked"

        new_obj.data.materials.clear()

        if "SB_BG_HIDE" in new_obj:
            del new_obj["SB_BG_HIDE"]

        #Create a collection for our baked objects if it doesn't exist
        col_name = "SimpleBake_Bakes_Background" if self.in_background else "SimpleBake_Bakes"

        if col_name not in bpy.data.collections:
            col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(col)
        else:
            col = bpy.data.collections[col_name]
            if col_name not in context.scene.collection.children:
                context.scene.collection.children.link(col)

        try: col.color_tag = "COLOR_05"
        except AttributeError: pass

        #Make sure it's visible and enabled for current view laywer
        context.view_layer.layer_collection.children[col_name].exclude = False
        context.view_layer.layer_collection.children[col_name].hide_viewport = False

        #Link object to our new collection
        col.objects.link(new_obj)

        #Remove tags from geo nodes sidestep
        if "SB_proxy_bake_object" in new_obj:
            del new_obj["SB_proxy_bake_object"]
        if "SB_sidestepd_orig_target" in new_obj:
            del new_obj["SB_sidestepd_orig_target"]
        if "SB_replaced_orig_name" in new_obj:
            del new_obj["SB_replaced_orig_name"]


        #Set active uv to one we used for bake for this object. Remove others.
        bake_uv_name = source_obj.get("SB_uv_used_for_bake")
        if bake_uv_name and bake_uv_name in new_obj.data.uv_layers:
            new_obj.data.uv_layers.active = new_obj.data.uv_layers[bake_uv_name]
            del_list = [uvl.name for uvl in new_obj.data.uv_layers if uvl.name != bake_uv_name]
            [new_obj.data.uv_layers.remove(new_obj.data.uv_layers[name]) for name in del_list]

        #Hide source objects?
        if self.hide_source_objects:
            source_obj.hide_set(True)

        return new_obj


    def remove_unused_pbr(self,context,mat):

        node_tree = mat.node_tree
        nodes = node_tree.nodes

        d_nodes_names = [n.name for n in nodes if n.bl_idname == "ShaderNodeDisplacement"]
        nm_nodes_names = [n.name for n in nodes if n.bl_idname == "ShaderNodeNormalMap"]
        gltf_node_names =[n.name for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.label == "gltf"]

        node_names = d_nodes_names + nm_nodes_names + gltf_node_names

        for name in node_names:
            if (n := nodes.get(name)):
                unused = True
                for i in n.inputs:
                    if len(i.links)>0:
                        unused = False
                if unused:
                    nodes.remove(n)

        rr_nodes = [n.name for n in nodes if n.bl_idname == "NodeReroute"]

        for name in rr_nodes:
            if (n := nodes.get(name)):
                unused = True
                for o in n.outputs:
                    if len(o.links)>0:
                        unused = False
                if unused:
                    nodes.remove(n)


    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        if not Bip.Sequence.should_run_teardown():
            print_message(context, "No object preperation - sequence and not last run")
            return {'FINISHED'} #Nope out if this is part of a sequence

        used_glossy = True if sbp.rough_glossy_switch == SBConstants.PBR_GLOSSY else False
        used_ccglossy = True if sbp.ccrough_glossy_switch == SBConstants.PBR_CLEARCOAT_GLOSS else False

        used_directx = True if sbp.normal_format_switch == SBConstants.NORMAL_DIRECTX else False

        #Grab what we need from the panel
        self.used_glossy = used_glossy
        self.used_ccglossy = used_ccglossy
        self.used_directx = used_directx
        self.hide_source_objects = sbp.hide_source_objects
        self.glTF = sbp.create_glTF_node
        self.glTF_option = sbp.glTF_selection
        self.merged_bake = sbp.merged_bake
        self.cyclesbake_mat_format = sbp.cyclesbake_copy_and_apply_mat_format
        self.merged_bake_name = sbp.merged_bake_name
        self.mat_only = True if sbp.apply_bakes_to_original else False
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False


        print_message(context, f"Creating prepared object {self.target_object_name}")

        tex_per_mat = sbp.tex_per_mat and not self.merged_bake and not self.decals_override

        if self.mat_only and not tex_per_mat:
            new_obj = None
        else:
            new_obj = self.create_object(context)

        if tex_per_mat and self.global_mode in [SBConstants.PBR, SBConstants.PBRS2A]:
            mats = self.create_pbr_setup_tex_per_mat(context, new_obj)
        elif tex_per_mat and self.global_mode in [SBConstants.CYCLESBAKE, SBConstants.CYCLESBAKE_S2A]:
            mats = self.create_cyclesbake_setup_tex_per_mat(context, new_obj)
        else:
            if self.decals_override:
                mat = self.create_pbrdecal_setup(context, new_obj)
            elif self.global_mode in [SBConstants.PBR, SBConstants.PBRS2A] and self.merged_bake:
                mat = self.create_pbr_setup_merged(context, new_obj)
            elif self.global_mode in [SBConstants.PBR, SBConstants.PBRS2A]:
                mat = self.create_pbr_setup(context, new_obj)
            elif self.global_mode in [SBConstants.CYCLESBAKE, SBConstants.CYCLESBAKE_S2A] and self.merged_bake:
                mat = self.create_cyclesbake_setup_merged(context, new_obj)
            elif self.global_mode in [SBConstants.CYCLESBAKE, SBConstants.CYCLESBAKE_S2A]:
                mat = self.create_cyclesbake_setup(context, new_obj)
            else:
                print_message(context, "Something went wrong with Copy and Apply")
                return {'FINISHED'}
            mats = [mat]

        for mat in mats:
            orig_objects = list(mat.get("SB_baked_orig_objects", []))
            orig_objects.append(self.target_object_name)
            mat["SB_baked_orig_objects"] = orig_objects
            mat["SB_bake_operation_id"] = self.bake_operation_id

        if not tex_per_mat:
            mat = mats[0]
            #Hook up glTF node?
            if self.glTF:
                self.hook_up_glTF_node(context, mat)

        #Make sure this happens after the GLTF node is corrected
        if self.global_mode in [SBConstants.PBR, SBConstants.PBRS2A] or self.decals_override:
            for mat in mats:
                self.remove_unused_pbr(context, mat)


        return {'FINISHED'}

classes = ([
    SimpleBake_OT_Copy_And_Apply,
    SimpleBake_OT_Apply_Bakes_To_Original
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
