from .preferences import get_sb_prefs
import bpy
import os
from pathlib import Path
from bpy.utils import register_class, unregister_class
from bpy.types import Panel, Operator

from ..utils import SBConstants, pbr_selections_to_list, specials_selection_to_list, is_blend_saved, conflicting_addons, get_cached_udim_tiles, get_cached_max_udim_tiles_from_bake_objects
from .objects_list import SIMPLEBAKE_UL_Objects_List
from .channel_packing_list import SIMPLEBAKE_UL_CPTexList
from ..background_and_progress import BackgroundBakeTasks, BakeInProgress
try:
    from ..auto_update import VersionControl
except:
    VersionControl = None
from ..bake_operators.pbr_bake_support_operators import has_convertible_shaders
from ..messages import print_message
from .. import __package__ as base_package
space = ""
region = ""
context = ""
cat = ""
TOGGLES = True
ALIGN= False
SCALE = 1.3

def read_settings():

    global space, region, context, cat, TOGGLES, ALIGN, SCALE

    p = Path(bpy.utils.script_path_user())
    p = p.parents[1]
    p = p / "data" / "SimpleBake" / "settings"

    #----------------Panel location-----------------------------
    filename = "panel_location.txt"
    content  = ""
    try:
        with open(str(p / filename), 'r') as file:
            # Read the content of the file
            content = file.read()
    except Exception as e:
        content = "renderpanel"

    #Can be renderpanel or npanel
    if content == "renderpanel":
        space = 'PROPERTIES'
        region = 'WINDOW'
        context = "render"
        cat = ""
    else:
        space = 'VIEW_3D'
        region = 'UI'
        context = ""
        cat = 'SimpleBake'

    #----------------Appearance-----------------------------
    filename = "toggles.txt"
    try:
        with open(str(p / filename), 'r') as file:
            # Read the content of the file
            content = file.read()
    except Exception as e:
        content = "toggles"

    TOGGLES = True if content == "toggles" else False
read_settings()


def monkey_tip_formatter(text, max_length=32):
    words = text.split()
    segments = []
    current_segment = ""

    for word in words:
        if len(current_segment) + len(word) + 1 > max_length:
            segments.append(current_segment)
            current_segment = word
        else:
            if current_segment:
                # Add a space before the word if it's not the beginning of a segment
                current_segment += " "
            current_segment += word

    # Add the last segment if it's not empty
    if current_segment:
        segments.append(current_segment)

    return segments

def monkey_tip(context, message_lines, box):
    sbp = context.scene.SimpleBake_Props
    row = box.row(align=ALIGN)
    row.alert=True
    row.prop(sbp, "showtips", icon="TRIA_DOWN" if sbp.showtips else "TRIA_RIGHT", icon_only=True, emboss=False)
    row.label(text=f'{"Tip" if sbp.showtips else "Tip available"}', icon="MONKEY")
    row.alignment = 'CENTER'

    if sbp.showtips:
        for line in message_lines:
            row = box.row(align=ALIGN)
            row.alignment = 'CENTER'
            row.scale_y = 0.5
            row.label(text=line)

def decals_tips(context, box):
    sbp = context.scene.SimpleBake_Props

    message_lines = ["PBR DECALS MODE"]
    message_lines.extend(monkey_tip_formatter("\
        Add the decal objects to the list, and specify your target\
        object in the Target Object box. If using the 'Copy objects and\
        apply bakes' option, a suitable decals material will be created"))
    monkey_tip(context, message_lines, box)

    row=box.row(align=ALIGN)
    row.label(text="")


def standard_s2a_tips(context, box):
    sbp = context.scene.SimpleBake_Props

    message_lines = ["STANDARD BAKE TO TARGET MODE"]
    message_lines.extend(monkey_tip_formatter("\
        Add source objects to the list and specify the\
        target object in the target box"))
    monkey_tip(context, message_lines, box)



def auto_match_high_low_tips(context, box):
    sbp = context.scene.SimpleBake_Props
    if sbp.auto_match_mode == "name":

        message_lines = ["AUTO MATCH HIGH/LOW"]
        message_lines.append("NAME MODE")
        message_lines.extend(monkey_tip_formatter("\
            Only objects with \"_high\" as a suffix to their name can be added to the list. \
            Each object's icon indicates if a corresponding \"_low\" object for baking\
            can be found in the scene. Cage objects are also auto detected with the\
            suffix \"_cage\""))
        monkey_tip(context, message_lines, box)


    if sbp.auto_match_mode == "position":

        message_lines = ["AUTO MATCH HIGH/LOW"]
        message_lines.append("POSITION MODE")
        message_lines.extend(monkey_tip_formatter("\
            Add your high poly objects to the list\
            Low poly detected by position (<0.5 BU)\
            Each object's icon indicates if a\
            corresponding low poly object for baking\
            can be found in the scene\
            "))
        monkey_tip(context, message_lines, box)

    row=box.row(align=ALIGN)
    row.label(text="")


def denoise_options(box):
    C = bpy.context
    sbp = C.scene.SimpleBake_Props

    row = box.row(align=ALIGN)
    row.scale_y = SCALE
    row.prop(sbp, "rundenoise", text="Denoise (Compositor)", toggle=TOGGLES)
    if not sbp.save_bakes_external:
        row.enabled = False

    row = box.row(align=ALIGN)
    row.scale_y = SCALE
    row.prop(C.scene.cycles, "use_denoising", text="Denoise (Cycles)", toggle=TOGGLES)

    if C.scene.cycles.use_denoising:
        row=box.row(align=ALIGN)
        #row.alignment = "RIGHT"
        row.prop(C.scene.cycles, "denoiser")
        row=box.row(align=ALIGN)
        #row.alignment = "RIGHT"
        row.prop(C.scene.cycles, "denoising_input_passes")
        row=box.row(align=ALIGN)
        #row.alignment = "RIGHT"
        row.prop(C.scene.cycles, "denoising_prefilter")

def check_for_render_inactive_modifiers(context):

    sbp = context.scene.SimpleBake_Props
    objects = [i.obj_point for i in sbp.objects_list if i.obj_point != None]

    for obj in objects:
        for mod in obj.modifiers:
            if mod.show_render and not mod.show_viewport:
                return True
    if sbp.selected_s2a and sbp.targetobj != None:
        for mod in sbp.targetobj.modifiers:
            if mod.show_render and not mod.show_viewport:
                return True

    if sbp.cycles_s2a and sbp.targetobj_cycles != None:
        for mod in sbp.targetobj_cycles.modifiers:
            if mod.show_render and not mod.show_viewport:
                return True

    return False

def check_for_viewport_inactive_modifiers(context):

    sbp = context.scene.SimpleBake_Props
    objects = [i.obj_point for i in sbp.objects_list if i.obj_point != None]

    for obj in objects:
        for mod in obj.modifiers:
            if mod.show_viewport and not mod.show_render:
                return True
    if sbp.selected_s2a and sbp.targetobj != None:
        for mod in sbp.targetobj.modifiers:
            if mod.show_viewport and not mod.show_render:
                return True

    if sbp.cycles_s2a and sbp.targetobj_cycles != None:
        for mod in sbp.targetobj_cycles.modifiers:
            if mod.show_viewport and not mod.show_render:
                return True

    return False

def disable_row_if_udims(context, row, box):
    sbp = context.scene.SimpleBake_Props

    if bpy.context.mode != 'OBJECT':
        return False

    objects_list = []
    if sbp.selected_s2a:
        if (o:=sbp.targetobj):
            objects_list = [sbp.targetobj.name]
    elif sbp.cycles_s2a:
        if (o:=sbp.targetobj_cycles):
            objects_list = [sbp.targetobj_cycles.name]
    else:
        objects_list = [i.name for i in sbp.objects_list]

    for obj_name in objects_list:

        result = get_cached_udim_tiles(context, obj_name, threshold=0.001)

        if result["total_tiles"]>1:

            row.enabled = False

            row = box.row(align=ALIGN)
            row.alert = True
            row.alignment = 'CENTER'
            row.scale_y = 0.5
            row.label(text="Bake objects have UDIMs!")
            row = box.row(align=ALIGN)
            row.alert = True
            row.alignment = 'CENTER'
            row.scale_y = 0.5
            row.label(text="Can only bake in background if")
            row = box.row(align=ALIGN)
            row.alert = True
            row.alignment = 'CENTER'
            row.scale_y = 0.5
            row.label(text="\"Export Bakes\" also turned on")

            return True

def disable_row_if_image_sequence(context, row, box):
    sbp = context.scene.SimpleBake_Props

    if sbp.bake_sequence:
        row.enabled = False

        row = box.row(align=ALIGN)
        row.alert = True
        row.alignment = 'CENTER'
        row.scale_y = 0.5
        row.label(text="Image sequence selected")
        row = box.row(align=ALIGN)
        row.alert = True
        row.alignment = 'CENTER'
        row.scale_y = 0.5
        row.label(text="Unfortunately, this can only be")
        row = box.row(align=ALIGN)
        row.alert = True
        row.alignment = 'CENTER'
        row.scale_y = 0.5
        row.label(text="baked in the foreground")

        return True

def check_for_convertible_shaders(context):

    sbp = context.scene.SimpleBake_Props

    bake_objects = [i.obj_point.name for i in sbp.objects_list]
    if sbp.selected_s2a and sbp.s2a_opmode == "decals" and sbp.targetobj !=None:
        bake_objects.append(sbp.targetobj.name)
    mats = []

    for obj_name in bake_objects:
        if not (o:=context.scene.objects.get(obj_name)):
            continue
        for slot in o.material_slots:
            if slot.material != None:
                mats.append(slot.material.name)

    result = False
    mats = set(list(mats))
    for m_name in mats:
        if has_convertible_shaders(m_name):
            result = True

    return result



class SIMPLEBAKE_PT_main_panel(Panel):
    bl_label = "SimpleBake"
    bl_space_type = f"{space}"
    bl_region_type = f"{region}"
    bl_context = f"{context}"
    bl_category = f"{cat}"

    def draw_version_info(self, context, layout):
        if VersionControl == None:
            row = layout.row(align=ALIGN)
            row.alignment = 'CENTER'
            row.scale_y = 0.6
            row.label(text=f"DEMO MODE")
            return

        prefs = get_sb_prefs(context)

        def print_installed_ver():
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                iv = VersionControl.installed_version_str
                row.label(text=f"Installed version: {iv}")

        if prefs.no_update_check:
            print_installed_ver()

            row = layout.row(align=ALIGN)
            row.alert=True
            row.alignment = 'CENTER'
            row.scale_y = 0.6
            iv = VersionControl.installed_version_str
            row.label(text=f"(Update checking disabled)")


        else:

            if VersionControl.was_error:

                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.label(text="Simplebake wasn't able to check", icon="ERROR")
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.label(text="for updates")
                print_installed_ver()

                # row = layout.row(align=ALIGN)
                # row.operator("simplebake.protect_clear", icon='URL', text="Yes I *AM* online!!")
                # row.scale_y = 1.5
                # print_installed_ver()
                return

            elif not VersionControl.at_current:
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.alert=True
                row.label(text="", icon="MOD_WAVE")

                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.alert=True
                row.label(text="Newer version of SimpleBake available")
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.alert=True
                row.label(text="Update automatically in addon preferences")
                print_installed_ver()
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.label(text=f"Available Version: {VersionControl.current_version_str}")

                return

            else:
                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.label(text="", icon="CHECKMARK")

                row = layout.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.label(text="SimpleBake is up-to-date")
                print_installed_ver()
                return

    def draw_global_mode_buttons(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.scale_y = 1.5
        row.prop(sbp, "global_mode", icon="SETTINGS", expand=True)

        row = box.row(align=ALIGN)
        row.operator("simplebake.panel_hide_all", icon='PROP_OFF', text="Hide all")
        row.operator("simplebake.panel_show_all", icon='PROP_ON', text="Show all")

    def draw_presets(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.prop(sbp, "presets_show", text="Settings presets", icon="PROP_ON" if sbp.presets_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.presets_show:

            row = box.row(align=ALIGN)
            row.alignment = "CENTER"
            row.label(text="Global Presets", icon="WORLD_DATA")

            row = box.row(align=ALIGN)
            col = row.column()
            col.template_list("SIMPLEBAKE_UL_Presets_List", "Presets List", sbp,
                              "presets_list", sbp, "presets_list_index")

            col = row.column()
            col.operator("simplebake.preset_refresh", text="", icon="FILE_REFRESH")
            col.operator("simplebake.preset_load", text="", icon="CHECKMARK")
            col.operator("simplebake.preset_delete", text="", icon="CANCEL")


            row = box.row(align=ALIGN)
            row.prop(sbp, "preset_name")
            row.operator("simplebake.preset_save", text="", icon="FUND")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "preset_load_clear_obj", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.label(text="")
            row = box.row(align=ALIGN)
            row.alignment = "CENTER"
            row.label(text="Blend File Presets", icon="FILE_BLEND")

            row = box.row(align=ALIGN)
            col = row.column()
            col.template_list("SIMPLEBAKE_UL_Local_Presets_List", "Local Presets List", sbp,
                              "local_presets_list", sbp, "local_presets_list_index")

            col = row.column()
            col.operator("simplebake.local_preset_refresh", text="", icon="FILE_REFRESH")
            col.operator("simplebake.local_preset_load", text="", icon="CHECKMARK")
            col.operator("simplebake.local_preset_delete", text="", icon="CANCEL")


            row = box.row(align=ALIGN)
            row.prop(sbp, "local_preset_name")
            row.operator("simplebake.local_preset_save", text="", icon="FUND")



    def draw_objects_list(self, context, box):
        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.prop(sbp, "bake_objects_show", text="Bake objects", icon="PROP_ON"
                 if sbp.bake_objects_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.bake_objects_show:

            row = box.row(align=ALIGN)
            col = row.column()
            col.template_list("SIMPLEBAKE_UL_Objects_List", "Bake Objects List", sbp,
                          "objects_list", sbp, "objects_list_index")

            col = row.column()
            col.scale_x = 0.32
            col.operator("simplebake.highlight_bake_objects" , text="", icon="LIGHT_SPOT")
            col.operator("simplebake.remove_highlight", text="", icon="SHADING_BBOX")
            col.prop(sbp, "highlight_col", text="")



            row = box.row(align=ALIGN)
            row.operator('simplebake.add_bake_object', text='Add', icon="PRESET_NEW")
            row.operator('simplebake.remove_bake_object', text='Remove', icon="CANCEL")
            row.operator('simplebake.clear_bake_objects_list', text='Clear', icon="MATPLANE")
            row = box.row(align=ALIGN)
            row.operator('simplebake.move_bake_object_list', text='Up', icon="TRIA_UP").direction="UP"
            row.operator('simplebake.move_bake_object_list', text='Down', icon="TRIA_DOWN").direction="DOWN"
            row.operator('simplebake.refresh_bake_object_list', text='Refresh', icon="FILE_REFRESH")

            if sbp.highlight_on:
                message_lines = monkey_tip_formatter("\
                Objects are highlighted when viewport set to \"Solid\" shading. Must be re-enabled after Blender restart")
                monkey_tip(context, message_lines, box)

            if sbp.global_mode == SBConstants.PBR:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "selected_s2a", toggle=TOGGLES, text="Bake to target")
                col = row.column()
                col.prop(sbp, "isolate_objects", toggle=TOGGLES, text="Isolate objects")
                if sbp.join_objs_to_proxy:
                    col.enabled = False

                if(sbp.selected_s2a):

                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"
                    row.prop(sbp, "s2a_opmode")

                    if sbp.s2a_opmode in ["single", "decals"]:

                        row = box.row(align=ALIGN)
                        split = row.split(factor=0.25)
                        split.alignment = "LEFT"
                        split.label(text="Target")
                        split.prop(sbp, "targetobj", text="")

                        row = box.row(align=ALIGN)
                        split = row.split(factor=0.25)
                        split.alignment = "LEFT"
                        split.label(text="Cage (optional)")
                        split.prop(context.scene.render.bake, "cage_object", text="")
                        if sbp.targetobj != None:
                            t = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == sbp.targetobj.name]
                            if len(t)>0: row.enabled = False


                        row = box.row(align=ALIGN)
                        row.scale_y = SCALE
                        #row.alignment = "RIGHT"
                        row.operator("simplebake.auto_cage", icon='ADD', text="Auto-generate cage")
                        row.operator("simplebake.remove_auto_cage", icon='REMOVE', text="Remove auto-generated cage")

                        if context.scene.render.bake.cage_object != None:
                            if 'SB_AUTO_CAGE' in context.scene.render.bake.cage_object.modifiers:
                                row = box.row(align=ALIGN)
                                row.scale_y = SCALE
                                row.prop(sbp, "auto_cage_extrusion", text="Auto generated cage extrusion")


                        if sbp.s2a_opmode == "decals":
                            decals_tips(context, box)

                        if sbp.s2a_opmode == "single":
                            standard_s2a_tips(context, box)

                    if sbp.s2a_opmode == "automatch":
                        row=box.row(align=ALIGN)
                        row.alignment = "RIGHT"
                        row.prop(sbp, "auto_match_mode")

                        auto_match_high_low_tips(context, box)

                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"
                    row.prop(sbp, "cage_smooth_hard")
                    if context.scene.render.bake.cage_object != None:
                        row.enabled = False
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "cage_extrusion")
                    if context.scene.render.bake.cage_object != None:
                        row.enabled = False
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "ray_distance")
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "cage_and_ray_multiplier")


            if sbp.global_mode == SBConstants.CYCLESBAKE:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "cycles_s2a", text="Bake to target", toggle=TOGGLES)
                col = row.column()
                col.prop(sbp, "isolate_objects", toggle=TOGGLES, text="Isolate objects")
                if sbp.join_objs_to_proxy:
                    col.enabled = False

                if sbp.cycles_s2a:
                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"
                    row.prop(sbp, "s2a_opmode")

                    if sbp.s2a_opmode in ["single"]:

                        row = box.row(align=ALIGN)
                        split = row.split(factor=0.25)
                        split.alignment = "LEFT"
                        split.label(text="Target")
                        split.prop(sbp, "targetobj_cycles", text="")

                        row = box.row(align=ALIGN)
                        split = row.split(factor=0.25)
                        split.alignment = "LEFT"
                        split.label(text="Cage (optional)")
                        split.prop(context.scene.render.bake, "cage_object", text="")
                        if sbp.targetobj_cycles != None:
                            t = [o.name for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == sbp.targetobj_cycles.name]
                            if len(t)>0: row.enabled = False

                        row = box.row(align=ALIGN)
                        row.scale_y = SCALE
                        #row.alignment = "RIGHT"
                        row.operator("simplebake.auto_cage", icon='ADD', text="Auto-generate cage")
                        row.operator("simplebake.remove_auto_cage", icon='REMOVE', text="Remove auto-generated cage")

                        if context.scene.render.bake.cage_object != None:
                            if 'SB_AUTO_CAGE' in context.scene.render.bake.cage_object.modifiers:
                                row = box.row(align=ALIGN)
                                row.scale_y = SCALE
                                row.prop(sbp, "auto_cage_extrusion", text="Auto generated cage extrusion")


                        standard_s2a_tips(context, box)

                    if sbp.s2a_opmode in ["automatch"]:
                        row=box.row(align=ALIGN)
                        row.alignment = "RIGHT"
                        row.prop(sbp, "auto_match_mode")

                        auto_match_high_low_tips(context, box)

                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"
                    row.prop(sbp, "cage_smooth_hard")
                    if context.scene.render.bake.cage_object != None:
                        row.enabled = False
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "cage_extrusion")
                    if context.scene.render.bake.cage_object != None:
                        row.enabled = False
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "ray_distance")
                    row = box.row(align=ALIGN)
                    row.use_property_split = True
                    row.prop(sbp, "cage_and_ray_multiplier")



            if check_for_render_inactive_modifiers(context):

                message_lines = [
                "One or more selected objects",
                "has a modifier enabled for",
                "render (and so baking), but disabled in",
                "viewport. May cause unexpected results"
                ]
                monkey_tip(context, message_lines, box)

            if check_for_viewport_inactive_modifiers(context):

                message_lines = [
                "One or more selected objects",
                "has a modifier enabled in the",
                "viewport, but disabled for",
                "render (and so baking).",
                "May cause unexpected results"
                ]
                monkey_tip(context, message_lines, box)


    def draw_pbr_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.prop(sbp, "pbr_settings_show", text="PBR Bakes", icon="PROP_ON"
                 if sbp.pbr_settings_show else "PROP_OFF", icon_only=True, emboss=False)

        if sbp.pbr_settings_show:

            row = box.row(align=ALIGN)
            col = row.column()
            col.prop(sbp, "selected_col", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "selected_metal", toggle=TOGGLES)
            row.scale_y = SCALE

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "selected_rough", toggle=TOGGLES)
            row.prop(sbp, "selected_normal", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_trans", toggle=TOGGLES)
            col = row.column()
            t="                " if bpy.app.version >= (4, 0, 0) else "Transmission Roughness"
            col.prop(sbp, "selected_transrough", toggle=TOGGLES, text=t)
            if bpy.app.version >= (4, 0, 0):
                col.enabled=False

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "selected_clearcoat", toggle=TOGGLES)
            row.prop(sbp, "selected_clearcoat_rough", toggle=TOGGLES)
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "selected_emission", toggle=TOGGLES)
            row.prop(sbp, "selected_emission_strength", toggle=TOGGLES)
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_specular", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "selected_alpha", toggle=TOGGLES)
            if sbp.selected_s2a == True and sbp.s2a_opmode == "decals":
                col.enabled = False

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_sss", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "selected_sss_scale", toggle=TOGGLES)


            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_bump", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "selected_displacement", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.label(text="")
            row.scale_y = 0.2


            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.selectall_pbr", icon='ADD')
            row.operator("simplebake.selectnone_pbr", icon='REMOVE')

            #row = box.row(align=ALIGN)
            #row.scale_y = SCALE
            row.operator("simplebake.autodetect_pbr_channels", icon='LIGHT', text="Attempt to auto-detect")


            #Extra options
            if sbp.selected_col or sbp.selected_rough or sbp.selected_normal:
                row = box.row(align=ALIGN)
                row.scale_y = 0.5
                row.label(text="Extra Options:")

            t=False
            if sbp.selected_col and sbp.s2a_opmode != "decals":
                t = True
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                #row.alignment = "LEFT"
                col.prop(sbp, "multiply_diffuse_ao", text="Diffuse option")
                col.enabled = True if sbp.save_bakes_external else False

                if sbp.multiply_diffuse_ao == "diffusexao":
                    col = row.column()#align=True)
                    #row.alignment = "LEFT"
                    #row.use_property_split = True
                    col.prop(sbp, "multiply_diffuse_ao_percent", text="AO Mix %")

            if sbp.selected_rough:
                t = True
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                #row.alignment = "LEFT"
                row.prop(sbp, "rough_glossy_switch", text="Rough/Glossy")
                row.enabled = True if sbp.save_bakes_external else False

            if sbp.selected_clearcoat_rough:
                t = True
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                #row.alignment = "LEFT"
                row.prop(sbp, "ccrough_glossy_switch", text="CC Rough/Glossy")
                row.enabled = True if sbp.save_bakes_external else False

            if sbp.selected_normal:
                t = True
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                #row.alignment = "LEFT"
                row.prop(sbp, "normal_format_switch", text="Normal format")
                row.enabled = True if sbp.save_bakes_external else False

            if not sbp.save_bakes_external and t:
                message_lines = monkey_tip_formatter("\
                Extra options above are not available because you are not exporting your bakes. Enable the Export Bakes  option below to access the extra options")
                monkey_tip(context, message_lines, box)

            if check_for_convertible_shaders(context):
                message_lines = monkey_tip_formatter("\
                    WARNING: Some materials on your bake objects use non-PBR shader nodes (e.g., Diffuse, Glossy). SimpleBake will TRY to match them for PBR, but results may vary. It's recommended to use the 'Attempt to auto-detect' button, as you may not expect the PBR maps needed after conversion. You will always get the best results from reworking your materials to be based around the Principled BSDF")
                monkey_tip(context, message_lines, box)

    def draw_aov_bakes(self, context, box):
        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.prop(sbp, "aov_settings_show", text="AOV Bakes", icon="PROP_ON" if sbp.aov_settings_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.aov_settings_show:
            row = box.row()
            row.scale_y = SCALE
            row.operator("simplebake.refresh_aov_list", text="Refresh AOVs", icon="FILE_REFRESH")

            if len(sbp.aov_items)==0:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.label(text="No AOV Output nodes found in your bake object(s)' materials'")

            for item in sbp.aov_items:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                name = item.name if item.name != "" else "Untitled"
                row.prop(item, "enabled", text=name, toggle=TOGGLES)
                row.prop(item, "cs")

                row = box.row(align=ALIGN)
                row.scale_y = 0.1
                des = f"(Object: \"{item.object_name}\", Material: \"{item.mat_name}\")"
                row.label(text=des)

            message_lines = []
            message_lines.extend(monkey_tip_formatter("\
                You can use AOV Output Nodes in your materials\
                to capture specific outputs and effectively create\
                custom bake maps. Whatever you connect to an AOV Output\
                Node’s input will be baked as a separate map."))
            monkey_tip(context, message_lines, box)

    def draw_cyclesbake_settings(self, context, box):

        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.prop(sbp, "cyclesbake_settings_show", text="CyclesBake", icon="PROP_ON" if sbp.cyclesbake_settings_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.cyclesbake_settings_show:
            cscene = context.scene.cycles
            cbk = context.scene.render.bake

            row=box.row(align=ALIGN)
            row.prop(cscene, "bake_type")

            row = box.row(align=ALIGN)
            row.prop(context.scene.render.bake, "view_from")

            if cscene.bake_type == 'NORMAL':
                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(cbk, "normal_space", text="Space")

                sub = col.column()
                sub.prop(cbk, "normal_r", text="Swizzle R")
                sub.prop(cbk, "normal_g", text="Swizzle G")
                sub.prop(cbk, "normal_b", text="Swizzle B")

            elif cscene.bake_type == 'COMBINED':

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(cbk, "use_pass_direct", toggle=TOGGLES)
                col = row.column()
                col.prop(cbk, "use_pass_indirect", toggle=TOGGLES)

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.active = cbk.use_pass_direct or cbk.use_pass_indirect

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(cbk, "use_pass_diffuse", toggle=TOGGLES)
                col = row.column()
                col.prop(cbk, "use_pass_glossy", toggle=TOGGLES)

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(cbk, "use_pass_transmission", toggle=TOGGLES)
                col = row.column()
                col.prop(cbk, "use_pass_emit", toggle=TOGGLES)

            elif cscene.bake_type in {'DIFFUSE', 'GLOSSY', 'TRANSMISSION'}:
                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(cbk, "use_pass_direct", toggle=TOGGLES)
                col = row.column()
                col.prop(cbk, "use_pass_indirect", toggle=TOGGLES)
                col = row.column()
                col.prop(cbk, "use_pass_color", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            col = row.column()
            col.prop(context.scene.cycles, "samples")
            #row = box.row(align=ALIGN)

            if (sbp.global_mode == SBConstants.CYCLESBAKE and
                    context.scene.cycles.bake_type != "NORMAL"):
                row = box.row(align=ALIGN)
                row.prop(sbp, "cyclesbake_cs")

            denoise_options(box)


    def draw_specials_settings(self, context, box):

        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.prop(sbp, "specials_show", text="Special bakes", icon="PROP_ON" if sbp.specials_show else "PROP_OFF", icon_only=False, emboss=False)
        need_denoise_options = False

        if sbp.specials_show:

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_col_mats", toggle=TOGGLES)
            if sbp.selected_s2a or sbp.cycles_s2a:
                col.enabled = False
            col = row.column()
            col.prop(sbp, "selected_col_vertex", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_curvature", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "selected_thickness", toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "selected_ao", toggle=TOGGLES)
            if sbp.global_mode == SBConstants.PBR and sbp.multiply_diffuse_ao == "diffusexao":
                col.enabled = False
            col = row.column()
            col.prop(sbp, "selected_lightmap", toggle=TOGGLES)
            if sbp.selected_s2a or sbp.cycles_s2a:
                col.enabled = False

            if sbp.selected_ao or sbp.selected_thickness or sbp.selected_lightmap:
                row = box.row(align=ALIGN)
                row.scale_y = 0.5
                row.label(text="Extra options:")

            if sbp.selected_ao or sbp.selected_thickness:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                #row.alignment="LEFT"
                #row.use_property_split = True
                #col = row.column()
                row.prop(sbp, "ao_sample_count")
                #col = row.column()
                #col.label(text="")
                if sbp.global_mode == SBConstants.PBR:
                    need_denoise_options = True

            if sbp.selected_lightmap and sbp.global_mode == SBConstants.PBR:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(context.scene.cycles, "samples", text="Lightmap Sample Count")
                need_denoise_options = True

            if sbp.selected_lightmap:
                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "lightmap_apply_colman", text="Lightmap apply colour management")
                if not sbp.save_bakes_external: row.enabled = False

            if need_denoise_options:
                row = box.row(align=ALIGN)
                denoise_options(box)


            if (sbp.selected_lightmap or sbp.selected_ao or sbp.selected_thickness) and sbp.global_mode == SBConstants.PBR:

                message_lines = monkey_tip_formatter(f"Sample count and denoise are not normally\
                relevant for PBR Bake, but they are for {SBConstants.LIGHTMAP},\
                {SBConstants.AO} and {SBConstants.THICKNESS}")
                monkey_tip(context, message_lines, box)

            if sbp.selected_lightmap and sbp.global_mode == SBConstants.CYCLESBAKE:
                message_lines = monkey_tip_formatter("Lightmap will have sample count\
                and denoise settings that you have set for CyclesBake above")
                monkey_tip(context, message_lines, box)

            if (sbp.selected_ao or sbp.selected_thickness) and sbp.global_mode == SBConstants.CYCLESBAKE:
                message_lines = [
                "AO and thickness will have",
                "denoise settings that",
                "you have set for CyclesBake above"
                ]
                monkey_tip(context, message_lines, box)

            if sbp.selected_s2a or sbp.cycles_s2a:
                message_lines = [
                "Lightmap is unavailable when",
                "baking to target object for now"
                ]
                monkey_tip(context, message_lines, box)

            monkey_tip(context, monkey_tip_formatter(
                "Use the eye icon next to a specials bake type to preview it. "
                "You can then edit the material directly (e.g. adjust curvature strength). "
                "Your changes will be used for all bakes of that type in this file."
            ), box)



    def draw_texture_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props

        row=box.row(align=ALIGN)
        row.prop(sbp, "textures_show", text="Texture settings", icon="PROP_ON"
                 if sbp.textures_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.textures_show:



            row = box.row(align=ALIGN)
            row.label(text="Bake at:")
            row.scale_y = 0.5

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "imgwidth")
            row.prop(sbp, "imgheight")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.decrease_texture_res", icon = "TRIA_DOWN")
            row.operator("simplebake.increase_texture_res", icon = "TRIA_UP")

            row=box.row(align=ALIGN)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.label(text="Output at:")
            row.scale_y = 0.5

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "outputwidth")
            row.prop(sbp, "outputheight")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.decrease_output_res", icon = "TRIA_DOWN")
            row.operator("simplebake.increase_output_res", icon = "TRIA_UP")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alignment = "RIGHT"
            row.prop(context.scene.render.bake, "margin", text="Bake Margin")

            try: #Margin type was added after Blender 3.0, apparently
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.alignment = "RIGHT"
                row.prop(context.scene.render.bake, "margin_type", text="Margin Type")
            except:
                pass

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "texture_bg_col", text="Texture BG Colour")  # no toggle

            if (sbp.texture_bg_col[3] <1.0) and sbp.save_bakes_external:
                message_lines = monkey_tip_formatter(
                "NOTE: Normally, for 'non-color' textures (e.g. metalness, roughness etc), the custom background "
                "colour will be lost when exporting, as these are saved as single-channel greyscale. "
                "However, as you have set an alpha value below 1.0, ALL textures will be exported as RGBA and the "
                "background colour + alpha will be preserved.")
                monkey_tip(context, message_lines, box)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "everything32bitfloat", toggle=TOGGLES)
            if sbp.export_file_format == "JPEG" or not sbp.clear_image:
                col.enabled = False
            col = row.column()
            col.prop(sbp, "clear_image", toggle=TOGGLES, text="Clear image before bake")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "merged_bake", toggle=TOGGLES)

            if sbp.merged_bake:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE

                col = row.column()
                col.prop(sbp, "merged_bake_name", text="Texture set name")
                col = row.column()
                col.prop(sbp, "join_objs_to_proxy", text="Join bake objects", toggle=TOGGLES)

                if sbp.join_objs_to_proxy:
                    message_lines = monkey_tip_formatter(
                        "WARNING: When using the option to join objects before baking, any materials "
                        "that rely on 'Generated' (or 'Object') texture coordinates may appear "
                        "differently after the join. This can cause baked textures to look incorrect. "
                        "Consider disabling this option if your materials use these coordinates. "
                        "Also note that the 'Isolate Objects' option will not function when objects are joined, "
                        "as individual objects cannot be hidden from each other once combined."
                    )
                    monkey_tip(context, message_lines, box)


            if len(sbp.objects_list) < 2 and sbp.merged_bake or ((sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode!="automatch"):

                message_lines = [
                    "You are baking multiple objects to one",
                    "texture set, but have fewer then 2",
                    "in the bake list. This is OK, but",
                    "might not be what you wanted"
                        ]
                monkey_tip(context, message_lines, box)

            row = box.row(align=ALIGN)
            col = row.column()
            col.scale_y = SCALE
            col.prop(sbp, "do_aa", text="Anti-aliasing", toggle=TOGGLES)
            if not sbp.save_bakes_external:
                col.enabled = False

            col = row.column()
            col.scale_y = SCALE
            col.label(text="")



            if sbp.do_aa:
                row = box.row(align=ALIGN)
                row.prop(sbp, "aa_threshold", text="AA Threshold")
                row = box.row(align=ALIGN)
                row.prop(sbp, "aa_contrast_limit", text="AA Contrast limit")
                row = box.row(align=ALIGN)
                row.prop(sbp, "aa_corner_radius", text="AA Threshold")



    def draw_export_settings(self, context, box):
        row = box.row(align=ALIGN)
        sbp = context.scene.SimpleBake_Props

        row.prop(sbp, "export_show", text="Export settings", icon="PROP_ON" if sbp.export_show else "PROP_OFF", icon_only=False, emboss=False)


        if sbp.export_show:
            if not is_blend_saved():
                row=box.row(align=ALIGN)
                row.label(text="Unavailable - Blend file not saved")
                return True

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "save_bakes_external", toggle=TOGGLES)
            col = row.column()
            col.prop(sbp, "save_obj_external", toggle=TOGGLES)

            #Relevant for both saving object and saving textures
            if sbp.save_bakes_external or sbp.save_obj_external:

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "export_path", text="Export Path")
                col = row.column()
                col.operator("simplebake.export_path_to_blend_location", text="", icon="UV_SYNC_SELECT")

                row = box.row(align=ALIGN)
                row.prop(sbp, "export_folder_per_object", toggle=TOGGLES)
                row.scale_y = SCALE


            #Relevant if exporting textures
            if sbp.save_bakes_external:

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                if(sbp.global_mode == SBConstants.PBR):
                    row.prop(sbp, "apply_col_man_to_col", toggle=TOGGLES)
                    if not sbp.selected_col:
                        row.enabled = False

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                if sbp.export_file_format == "OPEN_EXR":
                    #row.label(text="EXR exported as (max) 32bit")
                    pass
                elif sbp.export_file_format == "JPEG" or sbp.export_file_format == "TARGA":
                    pass
                else:
                    row.prop(sbp, "everything_16bit", toggle=TOGGLES)


                if(sbp.global_mode == SBConstants.CYCLESBAKE):
                    row.prop(sbp, "export_cycles_col_space", toggle=TOGGLES)
                    if context.scene.cycles.bake_type == "NORMAL":
                        row.enabled = False

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "export_file_format", text="Format")
                if sbp.export_file_format == "OPEN_EXR":
                    col = row.column()
                    col.prop(sbp, "exr_codec_export")
                if sbp.export_file_format == "JPEG":
                    col = row.column()
                    col.prop(sbp, "jpeg_quality", slider=True)

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "keep_internal_after_export", toggle=TOGGLES)

            #Relevant if saving object
            if sbp.save_obj_external:

                row = box.row(align=ALIGN)
                row.prop(sbp, "export_mesh_individual_or_combined", toggle=TOGGLES, text="Mesh objects")
                row.scale_y = SCALE

                #Merge mesh option
                if sbp.export_mesh_individual_or_combined == "combined":
                    row = box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.prop(sbp, "merge_export_obj", toggle=TOGGLES, text="Combine objects within export file")
                    if not sbp.merged_bake:
                        row.enabled = False

                row=box.row(align=ALIGN)
                #row.alignment = "RIGHT"
                row.prop(sbp, "export_format")

                #FBX
                if sbp.export_format == "fbx":
                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col = row.column()
                    col.prop(sbp, "apply_mods_on_mesh_export", toggle=TOGGLES)
                    col = row.column()
                    col.prop(sbp, "apply_transformation", toggle=TOGGLES)

                #OBJ
                if sbp.export_format == "obj":
                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col = row.column()
                    col.prop(sbp, "apply_mods_on_mesh_export", toggle=TOGGLES)


                if sbp.export_mesh_individual_or_combined == "combined":
                    row = box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.prop(sbp, "mesh_export_name", toggle=TOGGLES)

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "export_mesh_preset_name", toggle=TOGGLES)



            if sbp.everything32bitfloat and sbp.save_bakes_external and sbp.export_file_format != "OPEN_EXR":
                #Tip alert
                message_lines = [
                    "You are creating all images as 32bit float.",
                    "You may want to export to EXR",
                    "to preserve your 32bit image(s)"
                    ]
                monkey_tip(context, message_lines, box)

            if sbp.export_file_format == "OPEN_EXR" and sbp.save_bakes_external:
                #Tip alert
                message_lines = [
                    "Note: EXR files cannot be exported",
                    "with colour management settings.",
                    "EXR doesn't support them. Even",
                    "Blender defaults will be ignored"
                    ]
                monkey_tip(context, message_lines, box)


    def draw_uv_settings(self, context, box):

        sbp = context.scene.SimpleBake_Props


        row = box.row(align=ALIGN)
        row.prop(sbp, "uv_show", text="UV settings", icon="PROP_ON" if sbp.uv_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.uv_show:

            # row = box.row(align=ALIGN)
            # row.scale_y = SCALE
            # if sbp.new_uv_option:
            #     row.label(text="Going to create new UVs")
            # else:
            #     row.label(text="Will use existing UVs")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "new_uv_option", toggle=TOGGLES)

            if not sbp.new_uv_option:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "auto_detect_udims", toggle=TOGGLES)

            if sbp.auto_detect_udims:
                message_lines = monkey_tip_formatter("UDIM tiles are detected when UVs extend beyond standard UV space. Objects with and without UDIM tiles can be baked together. \
                    When using 'Multiple objects to one texture set,' if any object has UDIM tiles, all objects will be baked to that UDIM set")
                monkey_tip(context, message_lines, box)

            #-----------------------------------
            def multi_object_options(box):
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                #row.alignment = "RIGHT"
                row.prop(sbp, "new_uv_method")
                if sbp.new_uv_method in ["SmartUVProject_Atlas", "SmartUVProject_Individual"]:
                        row = box.row(align=ALIGN)
                        row.alignment = "RIGHT"
                        row.scale_y=SCALE
                        row.prop(sbp, "unwrapmargin")
                        row = box.row(align=ALIGN)
                        row.scale_y=SCALE
                        #row.alignment = "RIGHT"
                        row.prop(sbp, "uvcorrectaspect", toggle=TOGGLES)
                else: #Combine
                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"

                #Advanced UV packing options
                n = int(''.join(c for c in bpy.app.version_string if c.isdigit()))
                if sbp.new_uv_method in ["CombineExisting"] and n >= 360:

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.prop(sbp, "average_uv_size", text="Average UV island size")

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_rotate", toggle=TOGGLES)
                    col=row.column()
                    col.prop(sbp, "uvp_scale", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_lock_pinned", toggle=TOGGLES)
                    col=row.column()
                    col.prop(sbp, "uvp_merge_overlapping", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvpackmargin", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_shape_method", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_rotation_method", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_margin_method", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_lock_method", toggle=TOGGLES)

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    col=row.column()
                    col.prop(sbp, "uvp_pack_to", toggle=TOGGLES)


            def single_object_options(box):
                    #One object selected
                    row = box.row(align=ALIGN)
                    row.scale_y=SCALE
                    row.alignment = "RIGHT"
                    row.label(text="Smart UV Project: ")
                    row.prop(sbp, "unwrapmargin", toggle=TOGGLES)
                    row = box.row(align=ALIGN)
                    row.scale_y=SCALE
                    row.alignment = "RIGHT"
                    row.prop(sbp, "uvcorrectaspect")
            #-----------------------------------

            #Print the options if requesting new UVs
            if sbp.new_uv_option:
                objects = [obj.name for obj in sbp.objects_list]
                viable_high_low = SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes
                if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch" and len(viable_high_low) >1:
                    multi_object_options(box)
                elif (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch" and len(viable_high_low) ==1:
                    single_object_options(box)
                elif (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="decals":
                    single_object_options(box)

                elif sbp.selected_s2a and sbp.targetobj!=None:
                    single_object_options(box)
                elif sbp.cycles_s2a and sbp.targetobj_cycles!=None:
                    single_object_options(box)

                elif len(objects) >1 and not (sbp.selected_s2a or sbp.cycles_s2a):
                    multi_object_options(box)
                elif len(objects) ==1:
                    single_object_options(box)

                else:
                    row = box.row(align=ALIGN)
                    row.label(text="No objects selected for bake")


            if not sbp.new_uv_option:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "prefer_existing_sbmap", toggle=TOGGLES, text="Prefer existing UVs called SimpleBake")

            if sbp.new_uv_option:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "move_new_uvs_to_top", toggle=TOGGLES)

            #Always there
            col = row.column()
            col.prop(sbp, "restore_orig_uv_map", toggle=TOGGLES, text="Restore original UVs")

            #List for when we are using existing UVs
            if not sbp.new_uv_option or (sbp.new_uv_option and sbp.new_uv_method == 'CombineExisting'):

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                if (sbp.new_uv_option and sbp.new_uv_method == 'CombineExisting'):
                    row.label(text="We are combining existing UVs:", icon="MOD_BOOLEAN")
                else:
                    row.label(text="We are baking from existing UVs:", icon="UV_VERTEXSEL")

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.operator("simplebake.sync_uv_list", text="Refresh UVs list", icon='FILE_REFRESH')

                row = box.row(align=ALIGN)
                row.template_list(
                    "SIMPLEBAKE_UL_UVItems", "",           # UIList type and list_id
                    sbp, "uv_items",                       # data ptr + collection prop
                    sbp, "uv_items_index",                 # active data ptr + index prop
                    rows=6
                )

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "available_uv_maps", text="Available UV Maps")
                row.operator("simplebake.uv_set_all_name", icon='OUTLINER_DATA_MESH')

            #------------------------------------Tips---------------------------------------------------------

            if sbp.new_uv_option and sbp.restore_orig_uv_map and not sbp.copy_and_apply:
                #Tip alert
                message_lines = [
                "Generating new UVs, but restoring originals",
                "after bake. Baked textures won't align with the",
                "original UVs. Manually change active UV map ",
                "after bake"
                ]


            if sbp.new_uv_option and sbp.new_uv_method == "SmartUVProject_Individual" and sbp.merged_bake:
                #Tip alert
                message_lines = [
                "Current settings will unwrap objects",
                "individually but bake to one texture set",
                "Bakes will be on top of each other!"
                ]
                monkey_tip(context, message_lines, box)


            if not sbp.new_uv_option  and sbp.merged_bake:
                #Tip alert
                message_lines = monkey_tip_formatter(
                "ALERT: You are baking multiple objects to one texture \
                set with existing UVs. You will need to manually \
                make sure those UVs don't overlap!"
                )
                monkey_tip(context, message_lines, box)


            if sbp.new_uv_option and not sbp.save_obj_external and not sbp.copy_and_apply and sbp.bgbake == "bg":
                #Tip alert
                message_lines = [
                "You are baking in background with new UVs, but",
                "not exporting FBX or using 'Copy Objects and Apply Bakes'",
                "You will recieve the baked textures on import, but you will",
                "have no access to an object with the new UV map!"
                ]
                monkey_tip(context, message_lines, box)

    def draw_other_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.prop(sbp, "other_show", text="Other settings", icon="PROP_ON" if sbp.other_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.other_show:

            row=box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "batch_name")

            row=box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "bake_sequence", toggle=TOGGLES)
            if sbp.bake_sequence:
                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "bake_sequence_start_frame")
                row.prop(sbp, "bake_sequence_end_frame")

                message_lines = monkey_tip_formatter("\
                    NOTE: If you haven't added %FRAME% to your image format'\
                    string in the SimpleBake addon preferences, it will\
                    be added automatically to the end of the names of your baked images")
                monkey_tip(context, message_lines, box)


            dt = False
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            t = "Copy objects and apply bakes"
            t = f"{t} (after import)" if sbp.bgbake == "bg" else t
            row.prop(sbp, "copy_and_apply", text=t, toggle=TOGGLES)
            if not sbp.keep_internal_after_export:
                dt = True
                row.enabled = False

            if sbp.copy_and_apply:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col=row.column()
                t = "Hide source objects after bake"
                t = f"{t} (after import)" if sbp.bgbake == "bg" else t
                col.prop(sbp, "hide_source_objects", text=t, toggle=TOGGLES)
                if sbp.selected_s2a or sbp.cycles_s2a:
                    t = "Hide cage object after bake"
                    t = f"{t} (after import)" if sbp.bgbake == "bg" else t
                    col=row.column()
                    col.prop(sbp, "hide_cage_object", text=t, toggle=TOGGLES)

                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                col = row.column()
                col.prop(sbp, "create_glTF_node", toggle=TOGGLES)
                if sbp.create_glTF_node:
                    col = row.column()
                    col.prop(sbp, "glTF_selection", text="",toggle=TOGGLES)
                if sbp.global_mode == SBConstants.CYCLESBAKE:
                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.prop(sbp, "cyclesbake_copy_and_apply_mat_format", text = "Material")


            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "apply_bakes_to_original", text="Apply bakes to original objects", toggle=TOGGLES)
            if sbp.bgbake == "bg":
                row.enabled = False
            if not sbp.keep_internal_after_export:
                dt = True
                row.enabled = False

            if dt:
                message_lines = monkey_tip_formatter("'Copy objects and apply bakes' and 'Apply bakes to original objects' aren't available as you have chosen not to keep bakes internally after export. Turn that back on under 'Export Settings' to use these options")
                monkey_tip(context, message_lines, box)

            if sbp.apply_bakes_to_original:
                message_lines = [
                "Be careful when applying bakes to",
                "original objects. Original materials won't",
                "be deleted, BUT they will have no users",
                "and may be purged on next save"
                ]
                monkey_tip(context, message_lines, box)

            if sbp.apply_bakes_to_original and sbp.restore_orig_uv_map:
                message_lines = [
                "You are restoring your original UVs",
                "after bake, but also applying the baked",
                "textures to original objects. The textures",
                "may not look right with original UVs"
                ]
                monkey_tip(context, message_lines, box)


            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col=row.column()
            col.prop(sbp, "no_force_32bit_normals",toggle=TOGGLES)
            if sbp.global_mode == SBConstants.PBR:
                col=row.column()
                col.prop(sbp, "boosted_sample_count", toggle=TOGGLES)



            if context.preferences.addons["cycles"].preferences.has_active_device():
                row=box.row(align=ALIGN)
                row.prop(context.scene.cycles, "device")
            else:
                row=box.row(align=ALIGN)
                row.label(text="No valid GPU device in Blender Preferences. Using CPU.")








            if context.preferences.addons["cycles"].preferences.compute_device_type == "OPTIX" and context.preferences.addons["cycles"].preferences.has_active_device():
                #Tip alert
                message_lines = [
                "Other users have reported problems baking",
                "with GPU and OptiX. This is a Blender issue",
                "If you encounter problems bake with CPU"
                ]
                monkey_tip(context, message_lines, box)


            if (sbp.global_mode == SBConstants.PBR and sbp.copy_and_apply and
                len(pbr_selections_to_list(context)) == 0 and len(specials_selection_to_list(context)) > 0):

                message_lines = ([
                    "You are baking only special maps (no primary)",
                    "while using 'Copy objects and apply bakes'",
                    "Special maps will be in the new object(s)",
                    "material(s), but disconnected"
                    ])
                monkey_tip(context, message_lines, box)


    def draw_admin_settings(self, context, box):

        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.prop(sbp, "admin_settings_show", text="Utilities", icon="PROP_ON" if sbp.admin_settings_show else "PROP_OFF", icon_only=False, emboss=False)
        if sbp.admin_settings_show:

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert=True
            row.operator("simplebake.purge_settings", text="x-- SETTINGS --x", icon="ERROR")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert=True
            row.operator("simplebake.restorematerials", text="x-- MATERIALS --x", icon="ERROR")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert=True
            row.operator("simplebake.purge_images", text="X-- IMAGES --X", icon="ERROR")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert=True
            row.operator("simplebake.purge_objects", text="X-- OBJECTS --X", icon="ERROR")

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.label(text="Find and replace")
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "findreplace_find",toggle=TOGGLES)
            row.prop(sbp, "findreplace_replace",toggle=TOGGLES)
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "findreplace_type",toggle=TOGGLES)
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "limit_findandreplace_to_sb", text="Limit to SB data", toggle=TOGGLES)
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.findandreplace", text="Find and replace", icon="VIEWZOOM")

    def draw_channel_packing(self, context, box):

        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.prop(sbp, "channelpacking_show", text="Channel packing", icon="PROP_ON" if sbp.channelpacking_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.channelpacking_show:

            if not is_blend_saved():

                row=box.row(align=ALIGN)
                row.label(text="Unavailable - Blend file not saved")

            elif not sbp.save_bakes_external:

                row=box.row(align=ALIGN)
                row.label(text="Unavailable - You must be exporting your bakes")

            else:

                row=box.row(align=ALIGN)
                col = row.column()

                col.template_list("SIMPLEBAKE_UL_CPTexList", "CP Textures List", sbp,
                                        "cp_list", sbp, "cp_list_index")
                col = row.column()
                col.operator("simplebake.cptex_delete", text="", icon="CANCEL")
                col.operator("simplebake.cptex_set_defaults", text="", icon="MONKEY")

                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "cp_name")
                row=box.row(align=ALIGN)
                row.scale_y = SCALE
                row.prop(sbp, "channelpackfileformat", text="Format")
                if sbp.channelpackfileformat == "OPEN_EXR":
                    row.prop(sbp, "exr_codec_cpts")
                if sbp.channelpackfileformat == "PNG":
                    row.prop(sbp, "png_compression", text="Compression")
                row=box.row(align=ALIGN)
                row.scale_y=0.7
                row.prop(sbp, "cptex_R", text="R")
                row=box.row(align=ALIGN)
                row.scale_y=0.7
                row.prop(sbp, "cptex_G", text="G")
                row=box.row(align=ALIGN)
                row.scale_y=0.7
                row.prop(sbp, "cptex_B", text="B")
                row=box.row(align=ALIGN)
                row.scale_y=0.7
                row.prop(sbp, "cptex_A", text="A")


                cp_list = sbp.cp_list
                current_name = sbp.cp_name
                if current_name in cp_list: #Editing a cpt that is already there
                    index = cp_list.find(current_name)
                    cpt = cp_list[index]

                    if cpt.R != sbp.cptex_R or\
                        cpt.G != sbp.cptex_G or\
                        cpt.B != sbp.cptex_B or\
                        cpt.A != sbp.cptex_A or\
                        cpt.file_format != sbp.channelpackfileformat or\
                        cpt.exr_codec != sbp.exr_codec_cpts or\
                        cpt.png_compression != sbp.png_compression:

                            row = box.row(align=ALIGN)
                            row.alert=True
                            text = f"Update {current_name} (!!not saved!!)"
                            row.operator("simplebake.cptex_add", text=text, icon="ADD")
                    else: #No changes, no button
                        text = f"Editing {current_name}"
                        row = box.row(align=ALIGN)
                        row.label(text=text)
                        row.alignment = 'CENTER'

                else: #New item
                    row = box.row(align=ALIGN)
                    text = "Add new (!!not saved!!)"
                    row.alert = True
                    row.operator("simplebake.cptex_add", text=text, icon="ADD")

                if sbp.cptex_R == "" or\
                    sbp.cptex_G == "" or\
                    sbp.cptex_B == "" or\
                    sbp.cptex_A == "":
                        row.enabled = False

                row=box.row(align=ALIGN)
                row.prop(sbp, "del_cptex_components", toggle=TOGGLES)
                row.scale_y = SCALE
                if sbp.copy_and_apply or sbp.apply_bakes_to_original:
                    row.enabled = False


                prefs = get_sb_prefs(context)
                if not prefs.use_old_channel_packing:
                    message_lines = monkey_tip_formatter("\
                        Currently using the new method for channel packing. This works better with PNG and TGA, but doesn't work for EXR (and hence why you cannot select it). If you\
                        need EXR, enable the old method in SimpleBake addon preferences")
                    monkey_tip(context, message_lines, box)



    def draw_bake_buttons(self, context, box):

        sbp = context.scene.SimpleBake_Props
        n =  get_cached_max_udim_tiles_from_bake_objects(context)
        if n > 20 and sbp.auto_detect_udims:

            def alert_row(text, icon=None):
                row = box.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.alert = True
                if icon:
                    row.label(text=text, icon=icon)
                else:
                    row.label(text=text)

            alert_row(f"WARNING: You are about to bake {n} UDIM tiles!!!", icon="ERROR")
            alert_row("This is high. If intentional, that's fine.")
            alert_row("However, it often means UVs are not suitable for baking.")
            alert_row("In the worst case, Blender may run out of memory or crash.")
            alert_row("PLEASE CHECK YOUR UV MAPS!", icon = "ERROR")

            row = box.row(align=ALIGN)
            row.alignment = 'CENTER'
            row.scale_y = 0.6
            row.alert = True
            row.label(text="See SimpleBake's help page for guidance:")

            row = box.row()
            row.scale_y = 1
            row.operator("simplebake.support", icon="HELP")


        row = box.row(align=ALIGN)
        row.scale_y = 1.5
        row.prop(sbp, "bgbake", expand=True)

        row = box.row(align=ALIGN)

        prefs = get_sb_prefs(context)
        if prefs.check_for_conflicting_addons and not prefs.disable_other_addons2:
            enabled_addons = [addon.module for addon in bpy.context.preferences.addons]
            for ea in enabled_addons:
                for ca in conflicting_addons:
                    if ca in ea:
                        row=box.row(align=ALIGN)
                        row.scale_y = 0.5
                        row.alignment = 'CENTER'
                        row.alert=True
                        row.label(text="CANNOT PROCEED TO BAKE", icon="ERROR")
                        row=box.row(align=ALIGN)
                        row.scale_y = 0.5
                        row.alignment = 'CENTER'
                        row.alert=True
                        row.label(text=f"Addon '{ea}'")
                        row=box.row(align=ALIGN)
                        row.scale_y = 0.5
                        row.alignment = 'CENTER'
                        row.alert=True
                        row.label(text=f"conflicts with SimpleBake")
                        row=box.row(align=ALIGN)
                        row.scale_y = 0.5
                        row.alignment = 'CENTER'
                        row.alert=True
                        row.label(text=f"and will cause Blender to crash!")
                        row=box.row(align=ALIGN)
                        row.scale_y = 0.5
                        row.alignment = 'CENTER'
                        row.alert=True
                        row.label(text=f"Disable {ea} first")

                        return False

        #prefs = get_sb_prefs(context)
        if bpy.context.preferences.addons["cycles"].preferences.compute_device_type == 'OPTIX' and not prefs.override_optix_block and context.scene.cycles.device != "CPU":
            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="CANNOT PROCEED TO BAKE", icon="ERROR")

            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="Blender is set to use OptiX for rendering")

            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="OptiX baking is unstable")

            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="and often causes broken or failed bakes")

            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="Switch to CUDA or CPU to continue")

            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = True
            row.label(text="(You can override this in SimpleBake Preferences)")

            return False


        disable_if_is = False
        disable_if_udims = False
        bg_name = False
        op = ""
        text = ""
        icon = ""


        #Requesting Decals FG
        if sbp.bgbake == "fg" and (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="decals":
            op = "simplebake.bake_operation_decals"
            icon = 'RENDER_RESULT'
            text = "Bake! (Decals)"

        #Requesting Decals BG
        elif sbp.bgbake == "bg" and (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="decals":
            op = "simplebake.bake_operation_decals_background"
            icon = 'RENDER_RESULT'
            text = "Bake! (Decals) (Background)"
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        #Requesting Auto Match FG
        elif sbp.bgbake == "fg" and (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            op = "simplebake.automatch_operation"
            icon='RENDER_RESULT'
            text="Bake! (Auto Match)"

        #Requesting Auto Match BG
        elif sbp.bgbake == "bg" and (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            op = "simplebake.automatch_operation_background"
            icon='RENDER_RESULT'
            text="Bake! (Auto Match) (Background)"
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        #Requesting PBR foreground
        elif sbp.bgbake == "fg" and sbp.global_mode == SBConstants.PBR and not sbp.selected_s2a:
            op = "simplebake.bake_operation_pbr"
            icon = 'RENDER_RESULT'
            text = "Bake!"

        #Requesting PBR background
        elif sbp.bgbake == "bg" and sbp.global_mode == SBConstants.PBR and not sbp.selected_s2a:
            op = "simplebake.bake_operation_pbr_background"
            icon = 'RENDER_RESULT'
            text = "Bake! (in background)"
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        #Requesting PBRS2A foreground
        elif sbp.bgbake == "fg" and sbp.global_mode == SBConstants.PBR and sbp.selected_s2a:
            op = "simplebake.bake_operation_pbrs2a"
            icon = 'RENDER_RESULT'
            text = "Bake! (to target)"

        #Requesting  PBRS2A background
        elif sbp.bgbake == "bg" and sbp.global_mode == SBConstants.PBR and sbp.selected_s2a:
            op = "simplebake.bake_operation_pbrs2a_background"
            icon='RENDER_RESULT'
            text="Bake! (in background)"
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        #------------------------
        #Requesting CyclesBake foreground
        elif sbp.bgbake == "fg" and sbp.global_mode == SBConstants.CYCLESBAKE and not sbp.cycles_s2a:
            op = "simplebake.bake_operation_cyclesbake"
            icon='RENDER_RESULT'
            text="Bake!"
        #Requesting CyclesBake background
        elif sbp.bgbake == "bg" and sbp.global_mode == SBConstants.CYCLESBAKE and not sbp.cycles_s2a:
            op = "simplebake.bake_operation_cyclesbake_background"
            icon = 'RENDER_RESULT'
            text = "Bake! (in background)"
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        #Requesting CyclesBake S2A foreground
        elif sbp.bgbake == "fg" and sbp.global_mode == SBConstants.CYCLESBAKE and sbp.cycles_s2a:
            op = "simplebake.bake_operation_cyclesbake_s2a"
            icon='RENDER_RESULT'
            text="Bake! (to target)"

        #Requesting CyclesBake S2A background
        elif sbp.bgbake == "bg" and sbp.global_mode == SBConstants.CYCLESBAKE and sbp.cycles_s2a:
            op = "simplebake.bake_operation_cyclesbake_s2a_background"
            icon='RENDER_RESULT'
            text="Bake! (in background)"
            #disable_if_am = True
            bg_name = True
            disable_if_is = True
            disable_if_udims = True if not sbp.save_bakes_external else disable_if_udims

        row = box.row(align=ALIGN)

        #Requesting image sequence - override the buttons entirely
        if sbp.bake_sequence:
            row.operator("simplebake.image_sequence", icon='RENDER_RESULT', text="Bake, image sequence").cmd=op
        else:
            row.operator(op, icon=icon, text=text)

        if disable_if_is: disable_row_if_image_sequence(context, row, box)
        if disable_if_udims: disable_row_if_udims(context, row, box)

        if BakeInProgress.is_baking:
            row.enabled = False
        row.scale_y = 2

        if bg_name:
            row = box.row(align=ALIGN)
            row.prop(sbp, "bgbake_name", text="Name: ")

        if space == 'VIEW_3D':
            message_lines = monkey_tip_formatter("\
                WARNING: Based on my testing, Blender crashes WAY more when SimpleBake\
                is displayed in the N-Panel. I haven't been able to find out why\
                Use with extreme caution!")
            monkey_tip(context, message_lines, box)



    def draw_fg_bake_status(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row=box.row(align=ALIGN)
        row.scale_y = 0.5
        row.alignment = 'CENTER'
        row.alert=True
        row.label(text="FOREGROUND BAKE")
        row=box.row(align=ALIGN)
        row.scale_y = 0.5
        row.alignment = 'CENTER'
        row.alert=True
        row.label(text="IN PROGRESS")
        row=box.row(align=ALIGN)
        row.scale_y = 0.5
        row.alignment = 'CENTER'
        row.label(text="Please wait")

        # row=box.row(align=ALIGN)
        # row.alignment = 'CENTER'
        # row.label(text=sbp.fg_status_message)

        row=box.row(align=ALIGN)
        row.alignment = 'CENTER'
        row.label(text=f"{sbp.percent_complete}% complete")

    def draw_background_bakes(self, context, box):
        sbp = context.scene.SimpleBake_Props

        active = BackgroundBakeTasks.active_tasks
        queued = BackgroundBakeTasks.queued_tasks
        completed = BackgroundBakeTasks.completed_tasks

        row = box.row(align=ALIGN)
        row.prop(sbp, "bg_status_show", text="Background bakes", icon="PROP_ON" if sbp.bg_status_show else "PROP_OFF", icon_only=False, emboss=False)

        if sbp.bg_status_show:

            row = box.row(align=ALIGN)
            row.label(text="Completed:")
            for bgt in completed:
                row = box.row(align=ALIGN)
                row.scale_y = 0.7
                row.label(text=f"{bgt.name} - finished", icon="GHOST_ENABLED")
                row.operator("simplebake.import_bgbake", icon='IMPORT', text = "").pid = str(bgt.pid)
                row.operator("simplebake.discard_bgbake", icon="CANCEL", text="").pid = str(bgt.pid)

            row = box.row(align=ALIGN)
            row.label(text="Active:")
            for bgt in active:
                row = box.row(align=ALIGN)
                row.scale_y = 0.7
                row.label(text=f"{bgt.name} - baking in progress {BackgroundBakeTasks.get_bgbake_status(bgt)}%", icon="GHOST_DISABLED")
                row.operator("simplebake.kill_active_bgbake", icon="CANCEL", text="").pid = str(bgt.pid)

            row = box.row(align=ALIGN)
            row.label(text="Queued:")
            for bgt in queued:
                row = box.row(align=ALIGN)
                row.scale_y = 0.7
                row.label(text=f"{bgt.name} - queued", icon="GHOST_DISABLED")
                row.operator("simplebake.delete_queued_bgbake", icon='CANCEL', text="").id = bgt.id

    def draw_sketchfab_upload(self, context, box):
        sbp = context.scene.SimpleBake_Props

        row = box.row(align=ALIGN)
        row.operator("simplebake.sketchfab_upload", icon='IMPORT', text = "Sketchfab Upload")

        return True

    def draw(self, context):
        sbp = context.scene.SimpleBake_Props

        layout = self.layout

        self.draw_version_info(context, layout)

        if (not BakeInProgress.is_baking) or space == 'VIEW_3D':
            box = layout.box()
            self.draw_global_mode_buttons(context, box)

            box = layout.box()
            self.draw_presets(context, box)

            box = layout.box()
            self.draw_objects_list(context, box)

            if sbp.global_mode == SBConstants.PBR:
                box = layout.box()
                self.draw_pbr_settings(context, box)

                box = layout.box()
                self.draw_aov_bakes(context, box)

            if sbp.global_mode == SBConstants.CYCLESBAKE:
                box = layout.box()
                self.draw_cyclesbake_settings(context, box)

            #row=layout.row()
            #row.scale_y = 0.05
            #row.label(text="")
            box = layout.box()
            self.draw_specials_settings(context, box)

            box = layout.box()
            self.draw_texture_settings(context, box)

            box = layout.box()
            self.draw_export_settings(context, box)

            box = layout.box()
            self.draw_uv_settings(context, box)

            box = layout.box()
            self.draw_other_settings(context,box)

            if sbp.global_mode == SBConstants.PBR:
                box = layout.box()
                self.draw_channel_packing(context,box)

            box = layout.box()
            self.draw_admin_settings(context, box)

            box = layout.box()
            self.draw_bake_buttons(context, box)

        else:
            box = layout.box()
            self.draw_fg_bake_status(context, box)

        box = layout.box()
        self.draw_background_bakes(context, box)


        prefs = get_sb_prefs(context)
        if prefs.apikey != "":
            box = layout.box()
            self.draw_sketchfab_upload(context, box)




classes = ([
        SIMPLEBAKE_PT_main_panel
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
