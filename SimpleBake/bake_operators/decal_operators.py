from ..utils import get_sb_prefs
#TODO - Background?

import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, Macro
import uuid
import sys

from .common_bake_support import CommonBakePrepandFinish, common_prestart, clean_up_after_bg_spawn
from ..utils import (pbr_selections_to_list, specials_selection_to_list, SBConstants, force_to_object_mode)
from ..background_and_progress import BakeInProgress, BakeProgress, BackgroundBakeTasks
from ..material_management import SimpleBake_OT_Material_Backup as MatManager
from .pbr_bake_support_operators import sample_nodes_present
from .specials_bake_operators import add_specials_to_macro_s2a
from ..messages import print_message
from .. import __package__ as base_package

def determine_cage_settings(context, op, lo, MACRO):

    sbp = context.scene.SimpleBake_Props

    #Cage---------
    #If we are auto matching in name mode, try to auto assign a cage
    if context.scene.render.bake.cage_object != None:
        op.properties.use_cage = True
        op.properties.cage_object = context.scene.render.bake.cage_object.name
    elif sbp.cage_smooth_hard == "smooth":
        op.properties.use_cage = True
        op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
    elif sbp.cage_smooth_hard == "hard":
        op.properties.use_cage = False
        op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)

    return True

def set_bake_op_settings(context, op, bake_mode, s2a=True):

    sbp = context.scene.SimpleBake_Props

    if s2a:
        op.properties.use_selected_to_active=True

    op.properties.use_clear = False
    op.properties.target = "IMAGE_TEXTURES"
    op.properties.margin = context.scene.render.bake.margin
    try: op.properties.margin_type = context.scene.render.bake.margin_type
    except:pass

    op.properties.type = "NORMAL" if bake_mode == SBConstants.PBR_NORMAL else "EMIT"
    op.properties.max_ray_distance = (sbp.ray_distance * sbp.cage_and_ray_multiplier)

def image_post_processing(context, MACRO, bake_mode, bake_operation_id):

    sbp = context.scene.SimpleBake_Props


    #Scale all baked images if needed (catching this latest one)
    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Scaling images if needed"
    op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
    op.properties.bake_operation_id = bake_operation_id

    #Pack them
    op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
    op.properties.bake_operation_id = bake_operation_id
    op.properties.bake_mode = bake_mode

    #Save bakes external
    if sbp.save_bakes_external:
        op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
        op.properties.bake_operation_id = bake_operation_id
        op.properties.bake_mode = bake_mode

    #MUST COME AFTER SAVE EXTERNAL
    #Glossiness and DirectX
    #if sbp.rough_glossy_switch == SBConstants.PBR_GLOSSY:

    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Inverting roughness to create glossy"
    op = MACRO.define("SIMPLEBAKE_OT_invert_roughness_to_glossy")
    op.properties.bake_operation_id = bake_operation_id

    if sbp.normal_format_switch == SBConstants.NORMAL_DIRECTX:
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Creating DirectX normal from OpenGL map"
        op = MACRO.define("SIMPLEBAKE_OT_create_directx_normal")
        op.properties.bake_operation_id = bake_operation_id

class SimpleBake_OT_Decals_Operation_Background(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.bake_operation_decals_background"
    bl_description = "Commence background bake for Decals"
    bl_label = "Bake (Background)"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)

        if not common_prestart(context, decals=True):
            return {'CANCELLED'}

        #Start operator call for call back
        start_command = "bpy.ops.simplebake.bake_operation_decals()"

        #Tag objects in case we want to hide them later
        bg_bake_id = str(uuid.uuid4())
        def append_to_bg_hide_list(obj, bg_bake_id):
            if "SB_BG_HIDE" in obj:
                existing = obj["SB_BG_HIDE"]
                existing.append(bg_bake_id)
                obj["SB_BG_HIDE"] = existing
            else:
                obj["SB_BG_HIDE"] = [bg_bake_id]

        if sbp.hide_source_objects:
            for obj in sbp.objects_list:
                o = obj.obj_point
                append_to_bg_hide_list(o, bg_bake_id)
            #Also hide target object
            if sbp.targetobj != None:
                append_to_bg_hide_list(sbp.targetobj, bg_bake_id)

        if sbp.hide_cage_object and context.scene.render.bake.cage_object != None:
            append_to_bg_hide_list(context.scene.render.bake.cage_object, bg_bake_id)


        BackgroundBakeTasks(sbp.bgbake_name, sbp.copy_and_apply, start_command, bg_bake_id)
        clean_up_after_bg_spawn(context)
        return{'FINISHED'}


class SimpleBake_OT_Decals_Macro(Macro):
    bl_idname = "simplebake.decals_macro"
    bl_options = {'BLOCKING', 'INTERNAL'}
    bl_label = "Go"

    @classmethod
    def clean(cls):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
        bpy.utils.register_class(cls)

class SimpleBake_OT_Decals_Operation(Operator):
    """Start PBR Decals Bake"""
    bl_idname = "simplebake.bake_operation_decals"
    bl_description = "Commence Decals Bake"
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

        if not self.in_background:
            if not common_prestart(context, decals=True):
                return {'CANCELLED'}

        orig_objects_list = [i.obj_point for i in sbp.objects_list]


        force_to_object_mode(context)

        #Run after starting checks (and disable impossible)
        bake_modes = pbr_selections_to_list(context)

        #Set up our macro
        MACRO = SimpleBake_OT_Decals_Macro
        MACRO.clean()

        #Bake op ID
        bake_operation_id = str(uuid.uuid4())


        #Now we know what we are doing, call bake progress
        mode = SBConstants.PBRS2A_DECALS
        BakeProgress(mode, len(orig_objects_list))

        #Common bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake prep starting"
        MACRO.define("SIMPLEBAKE_OT_common_bake_prep")

        #Pre-bake (node groups and then reroute nodes)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Pre bake starting"
        if not bpy.app.version >= (4,1,0):
            MACRO.define("SIMPLEBAKE_OT_pbr_pre_bake_old")
        MACRO.define("SIMPLEBAKE_OT_remove_reroutes")

        #PBR specific bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="PBR specific bake prep starting"
        op = MACRO.define("SIMPLEBAKE_OT_pbr_specific_bake_prep_and_finish")
        op.properties.mode="prepare"

        #Process UVs (Op will adjust for auto match)
        #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Processing UVs"
        #op = MACRO.define("SIMPLEBAKE_OT_process_uvs")

        #Will boost be needed for later on?
        boost_needed = False
        for o in orig_objects_list:
            boost_needed = True if sample_nodes_present(context, o.name) else boost_needed

        #Do the S2A element of the bake
        #
        for bake_mode in bake_modes:

            #Create image for this bake mode
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Bake image creation (target object)"
            op = MACRO.define("SIMPLEBAKE_OT_bake_image")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.this_bake = bake_mode
            op.properties.target_object_name = sbp.targetobj.name
            op.properties.global_mode = SBConstants.PBRS2A #Just used for the image name

            #Backup all materials on target object
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (S2A source objects)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.target_object_name = sbp.targetobj.name
            op.properties.mode = MatManager.MODE_WORKING_BACKUP

            #Prepare (create the image node)
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Object preparation (Auto Match Lows)"
            op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.target_name = sbp.targetobj.name
            op.properties.this_bake = bake_mode
            op.properties.only_bake_image_node = True

            #Now prepare the decal objects
            for obj in orig_objects_list:
                #Backup all materials on object
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (Decal Objects)"
                op = MACRO.define("SIMPLEBAKE_OT_material_backup")
                op.properties.target_object_name = obj.name
                op.properties.mode = MatManager.MODE_WORKING_BACKUP

                #Prepare high for this bake mode (no image)
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material prep (Decal objects)"
                op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.target_name = obj.name
                op.properties.this_bake = bake_mode
                op.properties.no_bake_image_node = True

                #Done preparing Decal objects

            #Select specific high and low objects
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Select objects for S2A auto match setup"
            op = MACRO.define("SIMPLEBAKE_OT_select_selected_to_active")
            op.properties.mode = SBConstants.PBRS2A
            if sbp.isolate_objects:
                #Isolate S2A causes a return which doesn't actually mess with the selection
                op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
                op.properties.target_object_name = sbp.targetobj.name
                op.properties.isolate_s2a = True

            #Bake
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Starting bake operation"
            def do_bake():
                op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                op.properties.sample_count = sbp.boosted_sample_count if boost_needed else prefs.pbr_sample_count2

                op = MACRO.define("OBJECT_OT_bake")
                #Set the core bake options for the bake operation
                set_bake_op_settings(context, op, bake_mode)
                #Work out cage settings
                determine_cage_settings(context, op, sbp.targetobj.name, MACRO)

                op = MACRO.define("SIMPLEBAKE_OT_update_progress")

            do_bake()

            #Do scale, glossiness, directx, pack, denoise, export etc.
            image_post_processing(context, MACRO, bake_mode, bake_operation_id)

            #Restore the materials WORKING MODE
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Materials restore (working mode)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.mode=MatManager.MODE_WORKING_RESTORE

        #And now the non-S2A element of the bake

        #orig_bake_operation_id = bake_operation_id
        bake_operation_id = "DECALSBASE_" + bake_operation_id

        for bake_mode in bake_modes:

            #Create image for this bake mode
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Bake image creation (target object)"
            op = MACRO.define("SIMPLEBAKE_OT_bake_image")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.this_bake = bake_mode
            op.properties.target_object_name = sbp.targetobj.name
            op.properties.global_mode = SBConstants.PBR #Just used for the image name

            #Backup all materials on target object
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (S2A source objects)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.target_object_name = sbp.targetobj.name
            op.properties.mode = MatManager.MODE_WORKING_BACKUP

            #Prepare
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Object preparation (Auto Match Lows)"
            op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.target_name = sbp.targetobj.name
            op.properties.this_bake = bake_mode

            #Select
            op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
            op.properties.target_object_name = sbp.targetobj.name
            if sbp.isolate_objects:
                op.properties.isolate = True

            #Bake
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Starting bake operation (Non-S2A)"
            def do_bake():
                op = MACRO.define("SIMPLEBAKE_OT_set_sample_count")
                op.properties.sample_count = sbp.boosted_sample_count if boost_needed else prefs.pbr_sample_count2

                op = MACRO.define("OBJECT_OT_bake")
                #Set the core bake options for the bake operation
                set_bake_op_settings(context, op, bake_mode, s2a=False)

                op = MACRO.define("SIMPLEBAKE_OT_update_progress")

            do_bake()

            #Do scale, glossiness, directx, pack, denoise, export etc.
            image_post_processing(context, MACRO, bake_mode, bake_operation_id)

            #Restore the materials WORKING MODE
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Materials restore (working mode)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.mode=MatManager.MODE_WORKING_RESTORE

        #Add specials to the macro queue
        if len(specials_selection_to_list(context))> 0:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Adding specials to macro queue"
            add_specials_to_macro_s2a(MACRO, context, bake_operation_id)#!!

        #Copy and apply
        if sbp.copy_and_apply or sbp.save_obj_external or sbp.apply_bakes_to_original or self.in_background:
            op = MACRO.define("SIMPLEBAKE_OT_copy_and_apply")
            op.properties.target_object_name = sbp.targetobj.name
            op.properties.bake_operation_id = bake_operation_id
            op.properties.global_mode = SBConstants.PBRS2A
            op.properties.decals_override = True
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

        #PBR specific bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="PBR specific bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_pbr_specific_bake_prep_and_finish")
        op.properties.mode="finish"

        #Common bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_common_bake_finishing")
        op.properties.bake_operation_id = bake_operation_id


        # #Multiply Diffuse by AO?
        # if sbp.multiply_diffuse_ao == "diffusexao":
        #     op = MACRO.define("SIMPLEBAKE_OT_multiply_ao")
        #     op.properties.bake_operation_id = bake_operation_id

        #Channel packing x2
        cp_op = "SIMPLEBAKE_OT_channel_packing"
        op = MACRO.define(cp_op)
        op.properties.bake_operation_id = bake_operation_id
        op.properties.global_mode = "BaseObject" #Only used for the texture name
        op = MACRO.define(cp_op)
        op.properties.bake_operation_id = bake_operation_id.replace("DECALSBASE_","")
        op.properties.global_mode = "Decals" #Only used for the texture name



        #----------------------------------------------------------------------------------

        #Setup and then start the Macro
        BakeInProgress.is_baking = True
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1, window=context.window)

        #Run macro
        bpy.ops.simplebake.decals_macro('INVOKE_DEFAULT')
        return {'RUNNING_MODAL'}


classes = ([
    SimpleBake_OT_Decals_Operation,
    SimpleBake_OT_Decals_Macro,
    SimpleBake_OT_Decals_Operation_Background
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
