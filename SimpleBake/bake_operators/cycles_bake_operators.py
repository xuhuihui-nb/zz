from ..utils import get_sb_prefs
import bpy 
import uuid
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, Macro
from bpy.props import StringProperty, BoolProperty

import sys
from ..background_and_progress import BackgroundBakeTasks, BakeInProgress, BakeProgress
from ..utils import (SBConstants, select_only_this,
                     show_message_box, specials_selection_to_list, force_to_object_mode,
                     find_closest_obj)
from ..material_management import SimpleBake_OT_Material_Backup as MatManager
from .specials_bake_operators import add_specials_to_macro, add_specials_to_macro_s2a
from ..messages import print_message
from .common_bake_support import match_high_low_objects, common_prestart, clean_up_after_bg_spawn, CommonBakePrepandFinish


import re
from .. import __package__ as base_package

class SimpleBake_OT_CyclesBake_Bake_Macro(Macro):
    bl_idname = "simplebake.cyclesbake_bake_macro"
    bl_label = "Go"
    bl_options = {'BLOCKING', 'INTERNAL'}
    
    @classmethod
    def clean(cls):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
        bpy.utils.register_class(cls)

class SimpleBake_OT_Bake_Operation_CyclesBake_s2a_Background(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.bake_operation_cyclesbake_s2a_background"
    bl_description = "Commence background bake for CyclesBake S2A"
    bl_label = "Bake (Background)"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)

        if not common_prestart(context):
            return {'CANCELLED'}

        #Start operator call for call back
        start_command = "bpy.ops.simplebake.bake_operation_cyclesbake_s2a()"

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
            if sbp.targetobj_cycles != None:
                append_to_bg_hide_list(sbp.targetobj_cycles, bg_bake_id)

        if sbp.hide_cage_object and context.scene.render.bake.cage_object != None:
            append_to_bg_hide_list(context.scene.render.bake.cage_object, bg_bake_id)

        
        BackgroundBakeTasks(sbp.bgbake_name, sbp.copy_and_apply, start_command, bg_bake_id)
        clean_up_after_bg_spawn(context)
        return{'FINISHED'}


class SimpleBake_OT_Bake_Operation_CyclesBake_S2A(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.bake_operation_cyclesbake_s2a"
    bl_description = "Commence bake for CyclesBake S2A"
    bl_label = "Bake"

    first_run: BoolProperty(default=True)
    last_run: BoolProperty(default=False)
    bake_id_override: StringProperty(default="")
    
    _timer = None 
    hl_matches = {}
    orig_objects_list = []
    was_error = False
    objects_list_restored = False
        
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        if BakeInProgress.is_baking: return False
        else: return True
    

    def modal(self, context, event):
        sbp = context.scene.SimpleBake_Props
        if event.type == 'TIMER':
            #Always remove the timer if we are not baking
            if not BakeInProgress.is_baking:
                 context.window_manager.event_timer_remove(self._timer)

        return {'PASS_THROUGH'}
    
    def execute(self, context):

        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False

        if not self.in_background:
            if not common_prestart(context):
                return {'CANCELLED'}

        #Set bake ID, override if needed
        if self.bake_id_override != "":
            self.bake_operation_id = self.bake_id_override
        else:
            self.bake_operation_id = str(uuid.uuid4())

        #Objects
        bake_objects_names = [o.obj_point.name for o in sbp.objects_list]
        if sbp.targetobj_cycles != None: #Starting checks will catch this later if it's None
            target_object_name = sbp.targetobj_cycles.name
            if target_object_name in bake_objects_names:
                bake_objects_names.remove(target_object_name)



        BakeProgress(SBConstants.CYCLESBAKE_S2A, 1)

        #-----------------------------------------------------

        #Sidestep any geometary nodes
        bpy.ops.simplebake.sidestep_geo_nodes()

        force_to_object_mode(context)

        MACRO = SimpleBake_OT_CyclesBake_Bake_Macro
        
        #Clean macro
        MACRO.clean()
        
        #Common bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake prep starting"
        MACRO.define("SIMPLEBAKE_OT_common_bake_prep")
        
        #CyclesBake specific bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake prep starting"
        op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
        op.properties.mode="prepare"
        
        #Process UVs (target object only)
        #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Processing UVs"
        #op = MACRO.define("SIMPLEBAKE_OT_process_uvs")

        #Backup all materials on object
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (S2A target object)"
        op = MACRO.define("SIMPLEBAKE_OT_material_backup")
        op.properties.target_object_name = target_object_name #!!!
        op.properties.mode = MatManager.MODE_WORKING_BACKUP
            
        #Create bake image if needed for TARGET OBJECT and this bake mode
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Bake image creation (target object)"
        op = MACRO.define("SIMPLEBAKE_OT_bake_image")
        op.properties.bake_operation_id = self.bake_operation_id
        op.properties.this_bake = context.scene.cycles.bake_type
        op.properties.target_object_name = target_object_name #!!
        op.properties.global_mode = SBConstants.CYCLESBAKE_S2A
            
        #Set bake image on TARGET OBJECT
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Object preperation (target object)"
        op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
        op.properties.bake_operation_id = self.bake_operation_id
        op.properties.target_name = target_object_name #!!!
        op.properties.this_bake = context.scene.cycles.bake_type
        op.properties.only_bake_image_node = True
        
        #Select objects
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Select objects for S2A bake setup"
        op = MACRO.define("SIMPLEBAKE_OT_select_selected_to_active")
        op.properties.mode = SBConstants.CYCLESBAKE_S2A
        if sbp.isolate_objects:
            #Isolate S2A causes a return which doesn't actually mess with the selection
            op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
            op.properties.target_object_name = target_object_name
            op.properties.isolate_s2a = True
        
        #Bake
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Starting bake operation"
        def do_bake():
            op = MACRO.define("OBJECT_OT_bake")
            op.properties.use_clear = False
            op.properties.target = "IMAGE_TEXTURES"
            op.properties.use_selected_to_active=True
            op.properties.margin = context.scene.render.bake.margin
            try: #Magin type added after Blender 3.0
                op.properties.margin_type = context.scene.render.bake.margin_type
            except:
                pass
            op.properties.type = context.scene.cycles.bake_type
            op.properties.normal_space = context.scene.render.bake.normal_space
            op.properties.normal_r = context.scene.render.bake.normal_r
            op.properties.normal_g = context.scene.render.bake.normal_g
            op.properties.normal_b = context.scene.render.bake.normal_b
            op.properties.max_ray_distance = (sbp.ray_distance * sbp.cage_and_ray_multiplier)
            op.properties.cage_extrusion = (sbp.cage_extrusion * sbp.cage_and_ray_multiplier)
            #Cage---------
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
                
                
        #Restore all materials (scene wide) for next bake mode (if any)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Materials restore (working mode)"
        op = MACRO.define("SIMPLEBAKE_OT_material_backup")
        op.properties.mode=MatManager.MODE_WORKING_RESTORE
            
        

        #Scale all baked images if needed (catching this latest one)
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Scaling images if needed"
        op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
        op.properties.bake_operation_id = self.bake_operation_id

        #Pack
        #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Packing images into blend file"
        op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
        op.properties.bake_operation_id = self.bake_operation_id
        op.properties.bake_mode = context.scene.cycles.bake_type

        #Save bakes external?
        if sbp.save_bakes_external:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving bake externally"
            op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
            op.properties.bake_operation_id = self.bake_operation_id
            op.properties.bake_mode = context.scene.cycles.bake_type

        #Denoise if requested MUST COME AFTER SAVE EXTERNAL
        if sbp.rundenoise:
            op = MACRO.define("SIMPLEBAKE_OT_compositor_denoise")
            op.properties.bake_operation_id = self.bake_operation_id

        #Cycles specific bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake specific bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
        op.properties.mode="finish"

        #Add specials to the macro queue
        if len(specials_selection_to_list(context))> 0:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Adding specials to macro queue (CB S2A)"
            add_specials_to_macro_s2a(MACRO, context, self.bake_operation_id)#!!

        #All bakes done, copy and apply, save_obj_external or in background??
        if sbp.copy_and_apply or sbp.save_obj_external or self.in_background or sbp.apply_bakes_to_original:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="All bakes done, creating copy and apply object"
            op = MACRO.define("SIMPLEBAKE_OT_copy_and_apply")
            op.properties.target_object_name = target_object_name
            op.properties.bake_operation_id = self.bake_operation_id
            op.properties.global_mode = SBConstants.CYCLESBAKE_S2A

        #Are we applying bakes to original objects?
        if sbp.apply_bakes_to_original:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Applyig bakes to original objects"
            op = MACRO.define("SIMPLEBAKE_OT_apply_bakes_to_original")
            op.properties.bake_operation_id = self.bake_operation_id

        if sbp.save_obj_external:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving mesh object externally"
            #Export obj? (Will also remove copy and apply object if not needed)
            op = MACRO.define("SIMPLEBAKE_OT_save_objects_externally")
            op.properties.bake_operation_id = self.bake_operation_id

        #Common bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_common_bake_finishing")
        #op.properties.baked_number = sbp.total_bake_images_number
        op.properties.bake_operation_id = self.bake_operation_id
        
        #--------------------------------------------------------------------------------
        # if not self.in_background: #Cases a crash in background!
        #     message_list=([
        #         "Foreground bake has started",
        #         "Please wait...."
        #         ])
        #     show_message_box(context, message_list, "SIMPLEBAKE - FOREGROUND BAKE STARTED", icon = 'INFO')
        
        BakeInProgress.is_baking = True
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1, window=context.window)
        
        bpy.ops.simplebake.cyclesbake_bake_macro('INVOKE_DEFAULT')

        return {'RUNNING_MODAL'}



class SimpleBake_OT_Bake_Operation_CyclesBake_Background(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.bake_operation_cyclesbake_background"
    bl_description = "Commence background bake for CyclesBake (non S2A)"
    bl_label = "Bake (Background)"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)

        if not common_prestart(context):
            return {'CANCELLED'}
        
        #Start operator call for call back
        start_command = "bpy.ops.simplebake.bake_operation_cyclesbake()"

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
        
        BackgroundBakeTasks(sbp.bgbake_name, sbp.copy_and_apply, start_command, bg_bake_id)
        clean_up_after_bg_spawn(context)
        return{'FINISHED'}
        

class SimpleBake_OT_Bake_Operation_CyclesBake(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.bake_operation_cyclesbake"
    bl_description = "Commence bake for CyclesBake (non S2A)"
    bl_label = "Bake"
    
    _timer = None 
        
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        if BakeInProgress.is_baking: return False
        else: return True
    
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
            if not common_prestart(context):
                return {'CANCELLED'}

        bake_operation_id = str(uuid.uuid4())
        bake_objects_names = [o.obj_point.name for o in sbp.objects_list]
        #if sbp.everything_16bit: s8or16 = "16"
        #else: s8or16 = "8"



        #Progress Tracking
        BakeProgress(SBConstants.CYCLESBAKE, len(bake_objects_names))

        #-----------------------------------------------------

        force_to_object_mode(context)

        MACRO = SimpleBake_OT_CyclesBake_Bake_Macro

        #Clean macro
        MACRO.clean()
        
        #Common bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake prep starting"
        MACRO.define("SIMPLEBAKE_OT_common_bake_prep")
        
        #CyclesBake specific bake prep
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake specific bake prep starting"
        op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
        op.properties.mode="prepare"
        
        #Process UVs
        #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Processing UVs"
        #op = MACRO.define("SIMPLEBAKE_OT_process_uvs")

        obj_counter = 1
        for obj_name in bake_objects_names:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting object: {obj_name}"
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Starting bake mode: {context.scene.cycles.bake_type}"

            last_obj = True if obj_counter == len(bake_objects_names) else False
            
            #Backup all materials on object
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Material backup (working mode)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.target_object_name = obj_name
            op.properties.mode = MatManager.MODE_WORKING_BACKUP
                
            #Create bake image if needed for this object and this bake mode
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Creating bake image"
            op = MACRO.define("SIMPLEBAKE_OT_bake_image")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.this_bake = context.scene.cycles.bake_type
            op.properties.target_object_name = obj_name
            op.properties.global_mode = SBConstants.CYCLESBAKE
            
            #Configure all object materials for this bake mode
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message=f"Material prep for {context.scene.cycles.bake_type}"
            op = MACRO.define("SIMPLEBAKE_OT_prepare_object_mats_pbr")
            op.properties.bake_operation_id = bake_operation_id
            op.properties.target_name = obj_name
            op.properties.this_bake = context.scene.cycles.bake_type
            op.properties.only_bake_image_node = True
                            
            #Bake
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Starting bake operation"
            op = MACRO.define("SIMPLEBAKE_OT_select_only_this")
            op.properties.target_object_name = obj_name
            if sbp.isolate_objects:
                op.properties.isolate = True
            def do_bake():
                op = MACRO.define("OBJECT_OT_bake")
                op.properties.use_clear = False
                op.properties.target = "IMAGE_TEXTURES"
                op.properties.type = context.scene.cycles.bake_type
                op.properties.normal_space = context.scene.render.bake.normal_space
                op.properties.normal_r = context.scene.render.bake.normal_r
                op.properties.normal_g = context.scene.render.bake.normal_g
                op.properties.normal_b = context.scene.render.bake.normal_b
                op.properties.margin = context.scene.render.bake.margin
                try: #Magin type added after Blender 3.0
                    op.properties.margin_type = context.scene.render.bake.margin_type
                except:
                    pass
                op = MACRO.define("SIMPLEBAKE_OT_update_progress")

            do_bake()

            #Restore all materials (scene wide) for next bake mode (if any)
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Materials restore (working mode)"
            op = MACRO.define("SIMPLEBAKE_OT_material_backup")
            op.properties.mode=MatManager.MODE_WORKING_RESTORE
                
                #-----------If not a merged bake, done with this image. 
                #-----------If merged bake, only done if this is last object
            if not sbp.merged_bake or (sbp.merged_bake and last_obj):
                #LAST OPERATION
                    

                    

                #Scale all baked images if needed
                MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Scaling images if needed"
                op = MACRO.define("SIMPLEBAKE_OT_scale_images_if_needed")
                op.properties.bake_operation_id = bake_operation_id

                #Pack
                #MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Packing images into blend file"
                op = MACRO.define("SIMPLEBAKE_OT_pack_baked_images")
                op.properties.bake_operation_id = bake_operation_id
                op.properties.bake_mode = context.scene.cycles.bake_type

                #Save bakes external?
                if sbp.save_bakes_external:
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving bake externally"
                    op = MACRO.define("SIMPLEBAKE_OT_save_images_externally")
                    op.properties.bake_operation_id = bake_operation_id
                    op.properties.bake_mode = context.scene.cycles.bake_type

                #Denoise if requested MUST COME AFTER SAVE EXTERNAL
                if sbp.rundenoise:
                    MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Running compositor denoiser"
                    op = MACRO.define("SIMPLEBAKE_OT_compositor_denoise")
                    op.properties.bake_operation_id = bake_operation_id

                #AA if requested MUST COME AFTER SAVE EXTERNAL
                # if sbp.do_aa:
                #     MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Running compositor aa"
                #     op = MACRO.define("SIMPLEBAKE_OT_compositor_aa")
                #     op.properties.bake_operation_id = bake_operation_id

            #---Done with this object---
            obj_counter += 1
                
        #---Done with all objects---

        
        #CyclesBake specific bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="CyclesBake specific bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_cyclesbake_specific_bake_prep_and_finish")
        op.properties.mode="finish"

        #Add specials to the macro queue
        if len(specials_selection_to_list(context))> 0:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Adding specials to macro queue"
            add_specials_to_macro(MACRO, context, bake_operation_id, bake_objects_names)

        #All bakes done, copy and apply, save_obj_external or in background??
        if sbp.copy_and_apply or sbp.save_obj_external or self.in_background or sbp.apply_bakes_to_original:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="All bakes done, creating copy and apply"
            for obj_name in list(sbp['SB_orig_bake_objects']):
                op = MACRO.define("SIMPLEBAKE_OT_copy_and_apply")
                op.properties.target_object_name = obj_name
                op.properties.bake_operation_id = bake_operation_id
                op.properties.global_mode = SBConstants.CYCLESBAKE

        #Are we applying bakes to original objects?
        if sbp.apply_bakes_to_original:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Applyig bakes to original objects"
            op = MACRO.define("SIMPLEBAKE_OT_apply_bakes_to_original")
            op.properties.bake_operation_id = bake_operation_id

        if sbp.save_obj_external:
            MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Saving mesh object externally"
            #Export obj? (Will also remove copy and apply object if not needed)
            op = MACRO.define("SIMPLEBAKE_OT_save_objects_externally")
            op.properties.bake_operation_id = bake_operation_id

        #Common bake finishing
        MACRO.define("SIMPLEBAKE_OT_print_message").properties.message="Common bake finishing"
        op = MACRO.define("SIMPLEBAKE_OT_common_bake_finishing")
        #op.properties.baked_number = sbp.total_bake_images_number
        op.properties.bake_operation_id = bake_operation_id
        
        #--------------------------------------------------------------------------------
        if not self.in_background: #Cases a crash in background!
            message_list=([
                "Foreground bake has started",
                "Please wait...."
                ])
            show_message_box(context, message_list, "SIMPLEBAKE - FOREGROUND BAKE STARTED", icon = 'INFO')
        
        BakeInProgress.is_baking = True
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1, window=context.window)
        
        bpy.ops.simplebake.cyclesbake_bake_macro('INVOKE_DEFAULT')
        
        
        
        return {'RUNNING_MODAL'}

classes = ([
    SimpleBake_OT_Bake_Operation_CyclesBake,
    SimpleBake_OT_Bake_Operation_CyclesBake_S2A,
    SimpleBake_OT_CyclesBake_Bake_Macro,
    SimpleBake_OT_Bake_Operation_CyclesBake_Background,
    SimpleBake_OT_Bake_Operation_CyclesBake_s2a_Background
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
