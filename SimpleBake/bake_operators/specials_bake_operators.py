from ..utils import get_sb_prefs
import bpy 
import os
import random
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, Macro
from bpy.props import StringProperty, BoolProperty, IntProperty
import sys

from ..utils import SBConstants, specials_selection_to_list
from ..messages import print_message
from .. import __package__ as base_package

class SimpleBake_OT_Specials_Bake_Macro(Macro):
    bl_idname = "simplebake.specials_bake_macro"
    bl_label = "Go"
    
    @classmethod
    def clean(cls):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
        bpy.utils.register_class(cls)

class SimpleBake_OT_Specials_Mats_Swapping(Operator):
    bl_idname = "simplebake.specials_mats_swapping"
    bl_label = "Record or Restore"
    
    mode: StringProperty()
    obj_name: StringProperty()
    
    original_mats = {}
    
    def record(self, context):
        obj = context.scene.objects[self.obj_name]
        obj_name = self.obj_name
        orig_mats_dict = self.__class__.original_mats
        
        i=0
        for matslot in obj.material_slots:
            if matslot.material != None:
                if self.obj_name not in orig_mats_dict:
                    orig_mats_dict[self.obj_name] = {}
                orig_mats_dict[self.obj_name][i] = matslot.material.name
                print_message(context, f"RECORDED {matslot.material.name} for slot {i} for {obj_name}")
            i+=1
        self.__class__.original_mats = orig_mats_dict
            
    def restore(self, context):
        obj = context.scene.objects[self.obj_name]
        obj_name = self.obj_name
        orig_mats_dict = self.__class__.original_mats
        
        i=0
        for matslot in obj.material_slots:
            #Remove the bake image node from our special material (for possilbe re-use)
            if matslot.material != None:
                nodes = matslot.material.node_tree.nodes
                [nodes.remove(n) for n in nodes if "SB_bake_image_node" in n]
            
            #Restore the material originally in this slot
            try:
                matslot.material = bpy.data.materials[orig_mats_dict[obj_name][i]]
                print_message(context, f"RESTORED {orig_mats_dict[obj_name][i]} for slot {i} on {obj_name}")
            except:
                print_message(context, f"ERROR - was unable to restore material after specials bake")
            i+=1
    
    def execute(self, context):
        if self.mode == "record":
            self.record(context)
        
        if self.mode == "restore":
            self.restore(context)
        
        return {'FINISHED'}


class SimpleBake_OT_Specials_Specific_Bake_Prep_And_Finish(Operator):
    bl_idname = "simplebake.specials_specific_bake_prep_and_finish"
    bl_label = "Prepare or Finish"
    
    mode: StringProperty() 
    orig_sample_count: IntProperty()
        
    def finish(self, context):
        #print_message(context, "Specials specific bake finishing actions")
        context.scene.cycles.samples = self.orig_sample_count
        
    def prepare(self, context):
        print_message(context, "Specials specific bake prep actions")
        
        SimpleBake_OT_Setup_Col_ID.clear()
        
        #Sample count
        prefs = get_sb_prefs(context)
        context.scene.cycles.samples = prefs.pbr_sample_count2
        
    def execute(self, context):
        if self.mode == "prepare":
            self.prepare(context)
        elif self.mode == "finish":
            self.finish(context)
        
        return {'FINISHED'}
    
class SimpleBake_OT_Import_And_Assign_Specials(Operator):
    bl_idname = "simplebake.import_and_assign_specials"
    bl_label = "Import"
    
    bake_mode: StringProperty()
    obj_name: StringProperty()
    
    def _strip_sb_prefixes(self, name):
        if name.startswith("SBW_"):
            name = name[4:]
        if name.startswith("SBM_"):
            name = name[4:]
        return name

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        import_mat_name = f"SimpleBake_{self.bake_mode}"
        if import_mat_name not in bpy.data.materials:
            path = os.path.dirname(__file__) + "/../resources/specials.blend/Material/"
            bpy.ops.wm.append(filename=import_mat_name, directory=path)
        base_mat = bpy.data.materials[import_mat_name]

        obj = context.scene.objects[self.obj_name]
        orig_mats_dict = SimpleBake_OT_Specials_Mats_Swapping.original_mats

        for slot_idx, matslot in enumerate(obj.material_slots):
            if matslot.material is None:
                continue

            if sbp.tex_per_mat:
                mat = base_mat.copy()
                mat.name = f"SB_special_{self.bake_mode}_{slot_idx}"
                orig_name = orig_mats_dict.get(self.obj_name, {}).get(slot_idx, matslot.material.name)
                mat["SB_original_mat_name"] = self._strip_sb_prefixes(orig_name)
            else:
                mat = base_mat

            matslot.material = mat
            if "SB_bake_config" in mat:
                del mat["SB_bake_config"]

        for matslot in obj.material_slots:
            if matslot.material is None:
                continue
            ao_nodes = [n for n in matslot.material.node_tree.nodes
                        if n.bl_idname == "ShaderNodeAmbientOcclusion"]
            for ao_node in ao_nodes:
                ao_node.samples = sbp.ao_sample_count

        return {'FINISHED'}
    
class SimpleBake_OT_Setup_Vertex_Col(Operator):
    bl_idname = "simplebake.setup_vertex_col"
    bl_label = "Setup"
    
    obj_name: StringProperty()
    
    def execute(self, context):

        obj = context.scene.objects[self.obj_name]
        for matslot in obj.material_slots:
            if matslot.material is None:
                continue
            nodes = matslot.material.node_tree.nodes
            vc_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeVertexColor"]
            if len(vc_nodes) == 1:
                vc_nodes[0].layer_name = obj.data.color_attributes[0].name

        return {'FINISHED'}



class SimpleBake_OT_Setup_Col_ID(Operator):
    bl_idname = "simplebake.setup_col_id"
    bl_label = "Setup"
    
    obj_name: StringProperty()
    
    existing_col_id_mats = {}
    used_cols = []
    
    @classmethod
    def clear(cls):
        cls.existing_col_id_mats = {}
        cls.used_cols = []
    
    def check_col_distance_from_existing(self,context, r, g, b, min_diff):
        used_cols = self.__class__.used_cols
        
        #Free pass
        if len(used_cols) < 1:
            used_cols.append((r,g,b))
            self.__class__.used_cols = used_cols
            return True

        for uc in used_cols:
            if round(abs(r - uc[0]),1) > min_diff or round(abs(g - uc[1]), 1) > min_diff or round(abs(b - uc[2]),1) > min_diff:
                used_cols.append([r,g,b])
                self.__class__.used_cols = used_cols
                return True
            else:
                #self.__class__.used_cols = used_cols
                return False #At least one rgb was too close
    
    def _strip_sb_prefixes(self, name):
        if name.startswith("SBW_"):
            name = name[4:]
        if name.startswith("SBM_"):
            name = name[4:]
        return name

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        obj = context.scene.objects[self.obj_name]
        orig_mats_dict = SimpleBake_OT_Specials_Mats_Swapping.original_mats

        for slot_idx, slot in enumerate(obj.material_slots):
            orig_mat_name = slot.material.name
            existing_col_id_mats = self.__class__.existing_col_id_mats

            if orig_mat_name in existing_col_id_mats:
                col_id_mat = existing_col_id_mats[orig_mat_name]
                slot.material = col_id_mat
            else:
                col_id_mat = bpy.data.materials.new("SB_col_id")
                slot.material = col_id_mat

                col_id_mat.use_nodes = True
                node_tree = col_id_mat.node_tree
                nodes = node_tree.nodes

                m_output_node = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output]
                assert(len(m_output_node)==1)
                m_output_node = m_output_node[0]

                e_node = nodes.new("ShaderNodeEmission")

                #First attempt
                randr = random.randint(0,10) / 10
                randg = random.randint(0,10) / 10
                randb = random.randint(0,10) / 10

                min_diff = 0.6
                i=0
                giveup = False
                while self.check_col_distance_from_existing(context, randr,randg,randb, min_diff) == False and not giveup:
                    randr = random.randint(0,10) / 10
                    randg = random.randint(0,10) / 10
                    randb = random.randint(0,10) / 10
                    i+=1
                    if i == 100:
                    #We've tried 100 times and got nothing, reduce required min_diff
                        i=0
                        min_diff = min_diff - 0.1
                        print_message(context, f"Just reduced min_diff to {min_diff}")

                        #If we are now at 0, give up
                        if min_diff == 0:
                            print_message(context, "Giving up. Couldn't find a distanced colour")
                            giveup = True

                e_node.inputs[0].default_value = (randr,randg,randb, 1)
                node_tree.links.new(e_node.outputs[0], m_output_node.inputs[0])

                self.__class__.existing_col_id_mats[orig_mat_name] = col_id_mat

            if sbp.tex_per_mat:
                recorded_name = orig_mats_dict.get(self.obj_name, {}).get(slot_idx, orig_mat_name)
                col_id_mat["SB_original_mat_name"] = self._strip_sb_prefixes(recorded_name)

        return {'FINISHED'}


def add_specials_to_macro_s2a(MACRO, context, bake_operation_id, specific_high="", specific_low="", mode=""):
    
    #Set variables from panel
    sbp = context.scene.SimpleBake_Props
    if specific_high == "":
        if sbp.global_mode == SBConstants.PBR:
            mode = SBConstants.PBRS2A
            target_object_name = sbp.targetobj.name
        else:
            mode = SBConstants.CYCLESBAKE_S2A
            target_object_name = sbp.targetobj_cycles.name
    else: #Auto match with specific high and low
        mode = SBConstants.PBRS2A_AUTOMATCH
        target_object_name = specific_low

    specials_bake_modes = specials_selection_to_list(context)

    global_mode = SBConstants.PBR #########?????????????????????????????????????????????
    bake_objects_names = [o.obj_point.name for o in sbp.objects_list]
    orig_sample_count = context.scene.cycles.samples
    lightmap_apply_colman = sbp.lightmap_apply_colman
    denoise = sbp.rundenoise
    
    #Specials specific bake prep
    op = MACRO.define("SIMPLEBAKE_OT_specials_specific_bake_prep_and_finish")
    op.properties.mode = "prepare"
    
    #Record all bake object materials
    for obj_name in bake_objects_names:
        #Record original mats being used
        op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
        op.properties.mode = "record"
        op.properties.obj_name = obj_name
        
    #Also the target object
    op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
    op.properties.mode = "record"
    op.properties.obj_name = target_object_name
        
        
    for bake_mode in specials_bake_modes:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting bake mode: {bake_mode}"
        
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Now baking {bake_mode}"
        
        for obj_name in bake_objects_names:
            op = MACRO.define("SIMPLEBAKE_OT_import_and_assign_specials")
            op.properties.bake_mode = bake_mode
            op.properties.obj_name = obj_name
            
        #Create bake image if needed for TARGET OBJECT and this bake mode
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Creating bake image (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_bake_image")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.this_bake = bake_mode
        op.properties.target_object_name = target_object_name #!!
        op.properties.global_mode = global_mode

        #Set bake image on TARGET OBJECT
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Setting bake image on target object"
        op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.target_name = target_object_name #!!!
        op.properties.this_bake = bake_mode
        op.properties.only_bake_image_node = True
                
        #Select all bake objects with target as target
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Selecting objects for S2A baking setup"
        op = MACRO.define("SIMPLEBAKE_OT_select_selected_to_active")
        op.properties.mode = mode
        if mode == SBConstants.PBRS2A_AUTOMATCH:
            op.properties.specific_high = specific_high
            op.properties.specific_low = specific_low
            if sbp.isolate_objects:
                op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
                op.properties.auto_match = True
                op.properties.target_object_name = specific_low
                op.properties.high_object_name = specific_high
        elif sbp.isolate_objects:
            #Isolate S2A causes a return which doesn't actually mess with the selection
            op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
            op.properties.target_object_name = target_object_name
            op.properties.isolate_s2a = True
        
        #Bake-------------------------------------------------------
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting bake operation"
        def do_bake():
            op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
            if bake_mode in [SBConstants.AO, SBConstants.THICKNESS, SBConstants.CURVATURE]:
                op.properties.sample_count =sbp.boosted_sample_count
            else:
                prefs = get_sb_prefs(context)
                op.properties.sample_count = prefs.pbr_sample_count2
            
            op = MACRO.define("OBJECT_OT_bake")
            op.properties.use_clear = False
            op.properties.target = "IMAGE_TEXTURES"
            op.properties.use_selected_to_active=True
            op.properties.type = "EMIT"
            op.properties.max_ray_distance = (sbp.ray_distance * sbp.cage_and_ray_multiplier)
            #Cage---------
            if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.auto_match_mode == "name" and sbp.s2a_opmode == "automatch":
                parts = target_object_name.split("_")
                base_name = '_'.join(parts[:-1]).lower()
                for o in context.scene.objects:
                    if o.name.lower() == f"{base_name}_cage":
                        op.properties.use_cage = True
                        op.properties.cage_object = o.name
                        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Using cage object for specials {o.name}"
            #Not auto-match
            else:
                if context.scene.render.bake.cage_object != None:
                    op.properties.use_cage = True
                    op.properties.cage_object = context.scene.render.bake.cage_object.name
                elif sbp.cage_smooth_hard == "smooth":
                    op.properties.use_cage = True
                    op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
                elif sbp.cage_smooth_hard == "hard":
                    op.properties.use_cage = False
                    op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
            
            op = MACRO.define("SIMPLEBAKE_OT_update_progress")
            
        do_bake()
            
        #Restore material on target object before next bake mode
        #Will actually just remove the bake image node, as the material never changed for target
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Restore materials (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
        op.properties.mode = "restore"
        op.properties.obj_name = target_object_name
        
        

        #Scale all baked images if needed (catching this latest one)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Scale or images if needed (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.this_bake = bake_mode

        #Pack
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Packing images into blend file (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.bake_mode = bake_mode

        #Save external
        if sbp.save_bakes_external:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving baked images externally (specials)"
            op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.bake_mode = bake_mode
            op.properties.lightmap_apply_colman = sbp.lightmap_apply_colman


    #Restore materials on all bake objects as we are done
    for obj_name in bake_objects_names:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Restoring materials for {obj_name} (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
        op.properties.mode = "restore"
        op.properties.obj_name = obj_name


    #Denoise lightmap, AO or thickness MUST COME AFTER SAVE EXTERNAL
    if denoise and bake_mode in [SBConstants.LIGHTMAP, SBConstants.AO, SBConstants.THICKNESS]:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Running denoise (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_compositor_denoise")
        op.properties.bake_operation_id = bake_operation_id
        #op.properties.bake_type = bake_mode


    #Specials specific bake finishing
    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Specials bake finishing"
    op = MACRO.define("SIMPLEBAKE_OT_specials_specific_bake_prep_and_finish")
    op.properties.mode = "finish"
    op.properties.orig_sample_count = orig_sample_count



def add_specials_to_macro(MACRO, context, bake_operation_id, bake_objects_names):
    
    #Will always run second, so a lot of the setup (UVs etc.) will be done.
    
    sbp = context.scene.SimpleBake_Props
    
    #Set variables from panel
    denoise = sbp.rundenoise
    specials_bake_modes = specials_selection_to_list(context)
    global_mode = SBConstants.PBR #TODO-------------------------?
    lightmap_apply_colman = sbp.lightmap_apply_colman
    orig_sample_count = context.scene.cycles.samples
    #-----------------------------------------------------
    #MACRO = SimpleBake_OT_Specials_Bake_Macro
    
    #Clean macro
    #MACRO.clean()
    
    #Specials specific bake prep
    op = MACRO.define("SIMPLEBAKE_OT_specials_specific_bake_prep_and_finish")
    op.properties.mode = "prepare"
    
    obj_counter = 1
    for obj_name in bake_objects_names:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting object: {obj_name}"
        if obj_counter == len(bake_objects_names):
            last_obj = True
            #print_message(context, "Last operation")
        else: last_obj = False
        
        for bake_mode in specials_bake_modes:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting bake mode: {bake_mode}"
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Now baking {bake_mode}"
                
            #Create bake image if needed for this object and this bake mode
            op = MACRO.define("SIMPLEBAKE_OT_bake_image")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.this_bake = bake_mode
            op.properties.target_object_name = obj_name
            op.properties.global_mode = global_mode
            
            #Record original mats being used
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Backup materials (specials)"
            op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
            op.properties.mode = "record"
            op.properties.obj_name = obj_name
            
            if bake_mode == SBConstants.COLOURID:
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Setting up for ColID map (specials)"
                op = MACRO.define("SIMPLEBAKE_OT_setup_col_id")
                op.properties.obj_name = obj_name
                
            elif bake_mode == SBConstants.VERTEXCOL:
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Setting up for VertexCol bake (specials)"
                #Import needed special into scene, and set to object
                op = MACRO.define("SIMPLEBAKE_OT_import_and_assign_specials")
                op.properties.bake_mode = bake_mode
                op.properties.obj_name = obj_name
                op = MACRO.define("SIMPLEBAKE_OT_setup_vertex_col")
                op.properties.obj_name = obj_name
                
            elif bake_mode == SBConstants.LIGHTMAP:
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Setting up for LightMap bake (specials)"
                op = MACRO.define("SIMPLEBAKE_OT_import_and_assign_specials")
                op.properties.bake_mode = bake_mode
                op.properties.obj_name = obj_name
            
            #AO, Curvature, Thickness
            else:
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Setting up for AO/Curvate/Thickness bake (specials)"
                #Import needed special into scene, and set to object
                op = MACRO.define("SIMPLEBAKE_OT_import_and_assign_specials")
                op.properties.bake_mode = bake_mode
                op.properties.obj_name = obj_name

            #Config (mostly just adding the bake image node)
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Specials pre-bake config (add image node)"
            op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.target_name = obj_name
            op.properties.this_bake = bake_mode

            #Bake
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting bake operation"
            op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
            op.properties.target_object_name = obj_name
            if sbp.isolate_objects:
                op.properties.isolate = True
            
            def do_bake():
                if bake_mode == SBConstants.LIGHTMAP:
                    op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                    op.properties.sample_count = orig_sample_count
                    op = MACRO.define("OBJECT_OT_bake")
                    op.properties.type = "COMBINED"
                    op.properties.use_clear = False
                    op.properties.target = "IMAGE_TEXTURES"
                    op.properties.margin = context.scene.render.bake.margin
                    try: #Magin type added after Blender 3.0
                        op.properties.margin_type = context.scene.render.bake.margin_type
                    except:
                        pass
                    #op = MACRO.define("SIMPLEBAKE_OT_update_progress")
                    #op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                    #prefs = get_sb_prefs(context)
                    #op.properties.sample_count = prefs.pbr_sample_count2
                else:
                    op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                    if bake_mode in [SBConstants.AO, SBConstants.THICKNESS, SBConstants.CURVATURE]:
                        op.properties.sample_count = sbp.boosted_sample_count
                    else:
                        prefs = get_sb_prefs(context)
                        op.properties.sample_count = prefs.pbr_sample_count2
                    op = MACRO.define("OBJECT_OT_bake")
                    op.properties.type = "EMIT"
                    op.properties.use_clear = False
                    op.properties.target = "IMAGE_TEXTURES"
                    op.properties.margin = context.scene.render.bake.margin
                    try: #Magin type added after Blender 3.0
                        op.properties.margin_type = context.scene.render.bake.margin_type
                    except:
                        pass
                    op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                    op.properties.sample_count = orig_sample_count
                op = MACRO.define("SIMPLEBAKE_OT_update_progress")
            do_bake()
            
            #Restore all materials (and repair specials material if applicable)
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Restore materials (specials)"
            op = MACRO.define("SIMPLEBAKE_OT_specials_mats_swapping")
            op.properties.mode = "restore"
            op.properties.obj_name = obj_name
            
            #If not a merged bake, done with this image. If merged bake, only done if this is last object
            if not sbp.merged_bake or (sbp.merged_bake and last_obj):
                                    


                #Scale all baked images if needed (catching this latest one)
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Scale or images if needed (specials)"
                op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.this_bake = bake_mode

                #Pack
                #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Packing images into blend file (specials)"
                op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.bake_mode = bake_mode

                #Save external
                if sbp.save_bakes_external:
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving baked images externally (specials)"
                    op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
                    op.properties.bake_operation_id = bake_operation_id
                    op.properties.bake_mode = bake_mode
                    op.properties.lightmap_apply_colman = sbp.lightmap_apply_colman


        #Done with this object
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Finished baking {obj_name} (specials)"
        obj_counter += 1

    #Done with all objects

    #Denoise lightmap, AO or thickness MUST COME AFTER SAVE EXTERNAL
    if denoise and bake_mode in [SBConstants.LIGHTMAP, SBConstants.AO, SBConstants.THICKNESS]:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Running denoise (specials)"
        op = MACRO.define("SIMPLEBAKE_OT_compositor_denoise")
        op.properties.bake_operation_id = bake_operation_id
        #op.properties.bake_type = bake_mode

    #Specials specific bake finishing
    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Specials bake finishing"
    op = MACRO.define("SIMPLEBAKE_OT_specials_specific_bake_prep_and_finish")
    op.properties.mode = "finish"
    op.properties.orig_sample_count = orig_sample_count
    

classes = ([
    SimpleBake_OT_Specials_Specific_Bake_Prep_And_Finish,
    SimpleBake_OT_Import_And_Assign_Specials,
    SimpleBake_OT_Setup_Col_ID,
    SimpleBake_OT_Setup_Vertex_Col,
    SimpleBake_OT_Specials_Mats_Swapping,
    SimpleBake_OT_Specials_Bake_Macro,
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
