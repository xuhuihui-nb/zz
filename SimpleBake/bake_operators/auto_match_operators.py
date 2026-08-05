from ..utils import get_sb_prefs
#TODO - Background?

import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, Macro
import uuid
import sys

from .common_bake_support import CommonBakePrepandFinish, match_high_low_objects, clean_up_after_bg_spawn, common_prestart
from ..utils import pbr_selections_to_list, specials_selection_to_list, SBConstants, is_blend_saved, force_to_object_mode, find_3d_viewport
from ..background_and_progress import BakeInProgress, BakeProgress, BackgroundBakeTasks
from ..material_management import SimpleBake_OT_Material_Backup as MatManager
from .pbr_bake_support_operators import sample_nodes_present
from .specials_bake_operators import add_specials_to_macro, add_specials_to_macro_s2a
from .. import __package__ as base_package
from ..messages import print_message


def determine_cage_settings(context, op, lo, MACRO):

    sbp = context.scene.SimpleBake_Props

    #Cage---------
    #If we are auto matching in name mode, try to auto assign a cage
    if sbp.auto_match_mode == "name":
        parts = lo.split("_")
        base_name = '_'.join(parts[:-1]).lower()
        for o in context.scene.objects:
            if o.name.lower() == f"{base_name}_cage":
                op.properties.use_cage = True
                op.properties.cage_object = o.name
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Using cage object {o.name}"
                return True

    #Wasn't name more, or didn't find a cage
    if sbp.cage_smooth_hard == "smooth":
        op.properties.use_cage = True
        op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Using auto-cage (smooth)"
    elif sbp.cage_smooth_hard == "hard":
        op.properties.use_cage = False
        op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Using auto-cage (hard)"

    return True

def set_bake_op_settings(context, op, master_switch, bake_mode):

    sbp = context.scene.SimpleBake_Props

    op.properties.use_clear = False
    op.properties.target = "IMAGE_TEXTURES"
    op.properties.use_selected_to_active=True
    op.properties.margin = context.scene.render.bake.margin
    try: op.properties.margin_type = context.scene.render.bake.margin_type
    except:pass

    #PBR
    if master_switch=="P":
        op.properties.type = "NORMAL" if bake_mode == SBConstants.PBR_NORMAL else "EMIT"

    #CycesBake
    else:
        op.properties.type = context.scene.cycles.bake_type
        op.properties.normal_space = context.scene.render.bake.normal_space
        op.properties.normal_r = context.scene.render.bake.normal_r
        op.properties.normal_g = context.scene.render.bake.normal_g
        op.properties.normal_b = context.scene.render.bake.normal_b

    op.properties.max_ray_distance = (sbp.ray_distance * sbp.cage_and_ray_multiplier)

def image_post_processing(context, MACRO, bake_mode, bake_operation_id, master_switch):

    sbp = context.scene.SimpleBake_Props

    #Scale all baked images if needed (catching this latest one)
    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Scaling images if needed"
    op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
    op.properties.bake_operation_id = bake_operation_id

    #Pack them
    op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
    op.properties.bake_operation_id = bake_operation_id
    op.properties.bake_mode = bake_mode


    #Denoise if requested and CB
    if master_switch=="C" and sbp.rundenoise:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Running compositor denoiser"
        op = MACRO.define("SIMPLEBAKE_OT_compositor_denoise")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.bake_type = context.scene.cycles.bake_type


    #Save bakes external
    if sbp.save_bakes_external:
        op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.bake_mode = bake_mode

    #MUST COME AFTER SAVE EXTERNAL
    #Glossiness and DirectX
    if master_switch == "P":
        #if sbp.rough_glossy_switch == SBConstants.PBR_GLOSSY:

        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Inverting roughness to create glossy"
        op = MACRO.define("SIMPLEBAKE_OT_invert_roughness_to_glossy")
        op.properties.bake_operation_id = bake_operation_id

        if sbp.normal_format_switch == SBConstants.NORMAL_DIRECTX:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Creating DirectX normal from OpenGL map"
            op = MACRO.define("SIMPLEBAKE_OT_create_directx_normal")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.bake_mode = bake_mode


class SimpleBake_OT_AutoMatch_Operation_Background(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.automatch_operation_background"
    bl_description = "Commence background bake for AutoMatch"
    bl_label = "Bake (Background)"

    hl_matches = {}

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)

        if not common_prestart(context, automatch=True):
            return {'CANCELLED'}

        #Get the high to low matches dict. Abort if no matches
        orig_objects_list = []
        match_mode = "NAME" if sbp.auto_match_mode=="name" else "POSITION"
        dummy = match_high_low_objects(context, __class__.hl_matches, orig_objects_list, match_mode)


        #If only one match, we shouldn't do a merged bake
        if len(__class__.hl_matches)==1:
            sbp.merged_bake = False

        #Start operator call for call back
        start_command = "bpy.ops.simplebake.automatch_operation()"

        #Tag objects in case we want to hide them later
        bg_bake_id = str(uuid.uuid4())
        def append_to_bg_hide_list(obj, bg_bake_id):
            if "SB_BG_HIDE" in obj:
                existing = obj["SB_BG_HIDE"]
                existing.append(bg_bake_id)
                obj["SB_BG_HIDE"] = existing
            else:
                obj["SB_BG_HIDE"] = [bg_bake_id]

        for l in list(__class__.hl_matches.keys()):
            l = context.scene.objects[l]
            append_to_bg_hide_list(l, bg_bake_id)

        for h in list(__class__.hl_matches.values()):
            h = context.scene.objects[h]
            append_to_bg_hide_list(h, bg_bake_id)

        if sbp.hide_cage_object and context.scene.render.bake.cage_object != None:
            append_to_bg_hide_list(context.scene.render.bake.cage_object, bg_bake_id)

        BackgroundBakeTasks(sbp.bgbake_name, sbp.copy_and_apply, start_command, bg_bake_id)
        clean_up_after_bg_spawn(context)

        return{'FINISHED'}


class SimpleBake_OT_AutoMatch_Macro(Macro):
    bl_idname = "simplebake.pbr_automatch_macro"
    bl_options = {'BLOCKING', 'INTERNAL'}
    bl_label = "Go"

    @classmethod
    def clean(cls):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
        bpy.utils.register_class(cls)

class SimpleBake_OT_AutoMatch_Operation(Operator):
    """Start PBR AutoMatch High Low Bake"""
    bl_idname = "simplebake.automatch_operation"
    bl_description = "Commence AutoMatch Bake"
    bl_label = "Bake"

    hl_matches = {}

    def modal(self, context, event):
        sbp = context.scene.SimpleBake_Props
        if event.type == 'TIMER':
            if not BakeInProgress.is_baking:
                context.window_manager.event_timer_remove(self._timer)
        return {'PASS_THROUGH'}

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False

        #We need to make sure we do this before pre-start because prestart processes UVs and hl_matches needs to be populated by then
        orig_objects_list=[]
        match_mode = "NAME" if sbp.auto_match_mode=="name" else "POSITION"
        dummy = match_high_low_objects(context, __class__.hl_matches, orig_objects_list, match_mode)

        if not self.in_background:
            if not common_prestart(context, automatch=True):
                return {'CANCELLED'}

        #We need to know what overall mode is on the panel
        master_switch = "P" if sbp.global_mode == "PBR" else "C"
        bake_modes = pbr_selections_to_list(context) if master_switch=="P" else [context.scene.cycles.bake_type]

        force_to_object_mode(context)

        #Set up our macro
        MACRO = SimpleBake_OT_AutoMatch_Macro
        MACRO.clean()

        #Bake op ID
        bake_operation_id = str(uuid.uuid4())

        #If only one match, we shouldn't do a merged bake
        if len(__class__.hl_matches)==1:
            sbp.merged_bake = False

        #Now we know what we are doing, call bake progress
        mode = SBConstants.PBRS2A_AUTOMATCH if master_switch=="P" else SBConstants.CYCLESBAKES2A_AUTOMATCH
        BakeProgress(mode, len(orig_objects_list), hl_matches=__class__.hl_matches)

        #Common bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake prep starting"
        MACRO.define("SIMPLEBAKE_OT_common_bake_prep")

        if master_switch=="P":
            #Pre-bake (node groups and then reroute nodes)
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Pre bake starting"
            if not bpy.app.version >= (4,1,0):
                MACRO.define("SIMPLEBAKE_OT_pbr_pre_bake_old")
            MACRO.define("SIMPLEBAKE_OT_remove_reroutes")

        if master_switch=="P":
            #PBR specific bake prep
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="PBR specific bake prep starting"
            op = MACRO.define("SIMPLEBAKE_OT_pbr_specific_bake_prep_and_finish")
        else:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake prep starting"
            op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
        op.properties.mode="prepare"

        #Process UVs (Op will adjust for auto match)
        #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Processing UVs"
        #op = MACRO.define("SIMPLEBAKE_OT_process_uvs")

        #Will boost be needed for later on?
        if master_switch=="P":
            boost_needed = False
            for hi in __class__.hl_matches.values():
                boost_needed = True if sample_nodes_present(context, hi) else boost_needed
        #CyclesBake - just don't use this at all
        else:
            boost_needed = False


        #Need to loop through each pair
        run_count=0
        for lo in __class__.hl_matches.keys():
            run_count += 1
            last_run = True if run_count==(len(__class__.hl_matches.keys())) else False

            if last_run:
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Last run"

            hi = __class__.hl_matches[lo]

            for bake_mode in bake_modes:

                #Create image for this bake mode
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Bake image creation (low objects)"
                op = MACRO.define("SIMPLEBAKE_OT_bake_image")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.this_bake = bake_mode
                op.properties.target_object_name = lo #!!
                op.properties.global_mode = "AutoMatch" #Just used for the image name


                #No setup of high objects for Cycles Bake
                if master_switch=="P":
                    #Setup the high
                    #Backup all materials on object
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (S2A source objects)"
                    op = MACRO.define("SIMPLEBAKE_OT_material_backup")
                    op.properties.target_object_name = hi
                    op.properties.mode = MatManager.MODE_WORKING_BACKUP

                    #Prepare high for this bake mode (no image)
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material prep (Auto Match Highs)"
                    op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
                    op.properties.bake_operation_id = bake_operation_id
                    op.properties.target_name = hi
                    op.properties.this_bake = bake_mode
                    op.properties.no_bake_image_node = True

                #Setup the low
                #Backup all materials on object
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (S2A source objects)"
                op = MACRO.define("SIMPLEBAKE_OT_material_backup")
                op.properties.target_object_name = lo
                op.properties.mode = MatManager.MODE_WORKING_BACKUP

                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Object preparation (Auto Match Lows)"
                op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.target_name = lo #!!!
                op.properties.this_bake = bake_mode
                op.properties.only_bake_image_node = True

                #Select specific high and low objects
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Select objects for S2A auto match setup"
                op = MACRO.define("SIMPLEBAKE_OT_select_selected_to_active")
                op.properties.mode = SBConstants.PBRS2A_AUTOMATCH #TODO - Refactor. Works for CB but name shouldnt be specific
                op.properties.specific_low = lo
                op.properties.specific_high = hi
                if sbp.isolate_objects:
                    #Isolate S2A causes a return which doesn't actually mess with the selection
                    op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
                    op.properties.target_object_name = lo
                    op.properties.high_object_name = hi
                    op.properties.auto_match = True
                    #Find and pass the cage for this pair so it stays visible during the bake
                    if sbp.auto_match_mode == "name":
                        parts = lo.split("_")
                        base_name = '_'.join(parts[:-1]).lower()
                        for scene_obj in context.scene.objects:
                            if scene_obj.name.lower() == f"{base_name}_cage":
                                op.properties.cage_object_name = scene_obj.name
                                break

                #Bake
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Starting bake operation"
                def do_bake():
                    if master_switch=="P": #CyclesBake is just left at scene setting
                        op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                        op.properties.sample_count = sbp.boosted_sample_count if boost_needed else prefs.pbr_sample_count2
                    op = MACRO.define("OBJECT_OT_bake")
                    #Set the core bake options for the bake operation
                    set_bake_op_settings(context, op, master_switch, bake_mode)
                    #Work out cage settings
                    determine_cage_settings(context, op, lo, MACRO)

                    op = MACRO.define("SIMPLEBAKE_OT_update_progress")

                do_bake()

                #Restore the materials WORKING MODE
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Materials restore (working mode)"
                op = MACRO.define("SIMPLEBAKE_OT_material_backup")
                op.properties.mode=MatManager.MODE_WORKING_RESTORE

                #Do scale, glossiness, directx, pack, denoise, export etc.
                if not sbp.merged_bake or (sbp.merged_bake and last_run):
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Last run for {bake_mode}, calling post processing"
                    image_post_processing(context, MACRO, bake_mode, bake_operation_id, master_switch)


                #-----END OF BAKE MODE LOOP---------------------

        #Specials!
        if len(specials_selection_to_list(context))>0:
            for lo in __class__.hl_matches.keys():
                add_specials_to_macro_s2a(MACRO, context, bake_operation_id,
                                          specific_high=__class__.hl_matches[lo], specific_low=lo, mode=SBConstants.PBRS2A_AUTOMATCH) #TODO - Works for CB but name should be changed

        #All images now baked


        #Copy and apply
        if sbp.copy_and_apply or sbp.save_obj_external or sbp.apply_bakes_to_original or self.in_background:
            for lo in __class__.hl_matches.keys():
                op = MACRO.define("SIMPLEBAKE_OT_copy_and_apply")
                op.properties.target_object_name = lo
                op.properties.bake_operation_id = bake_operation_id
                op.properties.global_mode = SBConstants.PBRS2A if master_switch=="P" else SBConstants.CYCLESBAKE_S2A
                        #Just PBR or CB would be OK too

        #Are we applying bakes to original objects?
        if sbp.apply_bakes_to_original:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Applyig bakes to original objects"
            op = MACRO.define("SIMPLEBAKE_OT_apply_bakes_to_original")
            op.properties.bake_operation_id = bake_operation_id

        #Save mesh external
        if sbp.save_obj_external:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving mesh object externally"
            #Export obj? (Will also remove copy and apply object if not needed)
            op = MACRO.define("SIMPLEBAKE_OT_save_objects_externally")
            op.properties.bake_operation_id = bake_operation_id


        if master_switch=="P":
            #PBR specific bake finishing
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="PBR specific bake finishing"
            op = MACRO.define("SIMPLEBAKE_OT_pbr_specific_bake_prep_and_finish")
            op.properties.mode="finish"

            #Multiply Diffuse by AO?
            if sbp.multiply_diffuse_ao == "diffusexao":
                op = MACRO.define("SIMPLEBAKE_OT_multiply_ao")
                op.properties.bake_operation_id = bake_operation_id


            #Channel packing
            cp_op = "SIMPLEBAKE_OT_channel_packing"
            op = MACRO.define(cp_op)
            op.properties.bake_operation_id = bake_operation_id
            op.properties.global_mode = SBConstants.PBRS2A #Only used for the texture name

        #CyclesBake
        else:
            #CyclesBake specific bake finishing
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake specific bake finishing"
            op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
            op.properties.mode="finish"

        #Common bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_common_bake_finishing")
        op.properties.bake_operation_id = bake_operation_id

        #----------------------------------------------------------------------------------

        #Setup and then start the Macro
        BakeInProgress.is_baking = True
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1, window=context.window)

        #Run macro
        bpy.ops.simplebake.pbr_automatch_macro('INVOKE_DEFAULT')
        return {'RUNNING_MODAL'}


classes = ([
    SimpleBake_OT_AutoMatch_Operation,
    SimpleBake_OT_AutoMatch_Macro,
    SimpleBake_OT_AutoMatch_Operation_Background
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
