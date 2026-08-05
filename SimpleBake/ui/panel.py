import bpy
import os
from pathlib import Path
from bpy.utils import register_class, unregister_class
from bpy.types import Panel, Operator

from ..utils import SBConstants, pbr_selections_to_list, specials_selection_to_list, is_blend_saved, conflicting_addons, get_cached_udim_tiles
from .objects_list import SIMPLEBAKE_UL_Objects_List, refresh_mat_bake_list
from .channel_packing_list import SIMPLEBAKE_UL_CPTexList
from ..background_and_progress import BackgroundBakeTasks, BakeInProgress
from .panel_helpers import check_for_render_inactive_modifiers, check_for_convertible_shaders, check_for_auto_cage, check_for_viewport_inactive_modifiers
try:
    from ..auto_update import VersionControl
except:
    VersionControl = None

from ..messages import print_message
from .. import __package__ as base_package

space = ""
region = ""
context = ""
cat = ""
TOGGLES = True
ALIGN = False
SCALE = 1.3

def read_settings():
    global space, region, context, cat, TOGGLES, ALIGN, SCALE

    p = Path(bpy.utils.script_path_user())
    p = p.parents[1]
    p = p / "data" / "SimpleBake" / "settings"

    filename = "panel_location.txt"
    content = ""
    try:
        with open(str(p / filename), 'r') as file:
            content = file.read()
    except Exception as e:
        content = "renderpanel"

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

    filename = "toggles.txt"
    try:
        with open(str(p / filename), 'r') as file:
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
                current_segment += " "
            current_segment += word

    if current_segment:
        segments.append(current_segment)

    return segments


def monkey_tip(context, message_lines, box):
    sbp = context.scene.SimpleBake_Props
    row = box.row(align=ALIGN)
    row.alert = True
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
    message_lines = ["PBR DECALS MODE"]
    message_lines.extend(monkey_tip_formatter(
        "Add the decal objects to the list, and specify your target "
        "object in the Target Object box. If using the 'Copy objects and "
        "apply bakes' option, a suitable decals material will be created"))
    monkey_tip(context, message_lines, box)
    box.row(align=ALIGN).label(text="")


def standard_s2a_tips(context, box):
    message_lines = ["STANDARD BAKE TO TARGET MODE"]
    message_lines.extend(monkey_tip_formatter(
        "Add source objects to the list and specify the "
        "target object in the target box"))
    monkey_tip(context, message_lines, box)


def auto_match_high_low_tips(context, box):
    sbp = context.scene.SimpleBake_Props
    if sbp.auto_match_mode == "name":
        message_lines = ["AUTO MATCH HIGH/LOW", "NAME MODE"]
        message_lines.extend(monkey_tip_formatter(
            "Only objects with \"_high\" as a suffix to their name can be added to the list. "
            "Each object's icon indicates if a corresponding \"_low\" object for baking "
            "can be found in the scene. Cage objects are also auto detected with the "
            "suffix \"_cage\""))
    else:
        message_lines = ["AUTO MATCH HIGH/LOW", "POSITION MODE"]
        message_lines.extend(monkey_tip_formatter(
            "Add your high poly objects to the list "
            "Low poly detected by position (<0.5 BU) "
            "Each object's icon indicates if a "
            "corresponding low poly object for baking "
            "can be found in the scene"))
    monkey_tip(context, message_lines, box)
    box.row(align=ALIGN).label(text="")


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
        box.row(align=ALIGN).prop(C.scene.cycles, "denoiser")
        box.row(align=ALIGN).prop(C.scene.cycles, "denoising_input_passes")
        box.row(align=ALIGN).prop(C.scene.cycles, "denoising_prefilter")


def disable_row_if_image_sequence(context, row, box):
    # Image sequence baking is driven by a modal operator
    # (SimpleBake_OT_Image_Sequence) which needs Blender's event loop.
    # Background baking launches a headless subprocess and exits, so the
    # two modes are architecturally incompatible — disable the row here.
    sbp = context.scene.SimpleBake_Props

    if sbp.image_sequence_enabled:
        row.enabled = False
        for t in ("Image sequence selected", "Unfortunately, this can only be", "baked in the foreground"):
            r = box.row(align=ALIGN)
            r.alert = True
            r.alignment = 'CENTER'
            r.scale_y = 0.5
            r.label(text=t)
        return True


# ---------------------------------------------------------------------------
# Layout helper functions
# ---------------------------------------------------------------------------

def prop_row(box, data, prop, enabled=True, small_row=False, **kwargs):
    """Single standard-scale prop row. Returns the row so callers can set .enabled."""

    row = box.row(align=ALIGN)

    element = None
    if small_row:
        row.scale_y = 1
        row.use_property_split = True
        row.use_property_decorate = False
        element = row
    else:
        row.scale_y = SCALE
        element = row

    element.enabled = enabled
    element.prop(data, prop, toggle=TOGGLES, **kwargs)
    return row


def two_prop_row(box, data, prop_left, prop_right, label_left=None, label_right=None):
    """Two props side-by-side in columns. Returns (row, col_left, col_right)."""
    row = box.row(align=ALIGN)
    row.scale_y = SCALE
    col_l = row.column()
    col_l.prop(data, prop_left, toggle=TOGGLES,
               **({"text": label_left} if label_left is not None else {}))
    col_r = row.column()
    col_r.prop(data, prop_right, toggle=TOGGLES,
               **({"text": label_right} if label_right is not None else {}))
    return row, col_l, col_r


def preview_eye(layout, enabled, bake_type):
    """Eye icon button for bake type preview. Greyed out when enabled=False."""
    col = layout.column()
    col.enabled = enabled
    col.operator("simplebake.preview_bake_type", text="", icon="HIDE_OFF").bake_type = bake_type


def two_prop_row_preview(box, sbp, prop_left, prop_right, type_left, type_right):
    """Two props side-by-side with a preview eye button after each. Returns (row, col_left, col_right)."""
    row = box.row(align=ALIGN)
    row.scale_y = SCALE
    col_l = row.column()
    col_l.prop(sbp, prop_left, toggle=TOGGLES)
    preview_eye(row, getattr(sbp, prop_left), type_left)
    col_r = row.column()
    col_r.prop(sbp, prop_right, toggle=TOGGLES)
    preview_eye(row, getattr(sbp, prop_right), type_right)
    return row, col_l, col_r


def section_header(box, data, show_prop, label, icon_only=False, section_icon='NONE'):
    """Collapsible section header. Returns the row."""
    row = box.row(align=ALIGN)
    tria = "TRIA_DOWN" if getattr(data, show_prop) else "TRIA_RIGHT"
    row.prop(data, show_prop, text="", icon=tria, icon_only=True, emboss=False)
    row.prop(data, show_prop, text=label, icon=section_icon, emboss=False)
    return row


def draw_version_info(context, layout):
    if VersionControl is None:
        row = layout.row(align=ALIGN)
        row.alignment = 'CENTER'
        row.scale_y = 0.6
        row.label(text="DEMO MODE")
        return

    from .preferences import get_sb_prefs
    prefs = get_sb_prefs(context)

    def print_installed_ver():
        row = layout.row(align=ALIGN)
        row.alignment = 'CENTER'
        row.scale_y = 0.6
        row.label(text=f"Installed version: {VersionControl.installed_version_str}")

    if getattr(prefs, "no_update_check", False):
        print_installed_ver()
        row = layout.row(align=ALIGN)
        row.alert = True
        row.alignment = 'CENTER'
        row.scale_y = 0.6
        row.label(text="(Update checking disabled)")
        return

    if VersionControl.was_error:
        for text, icon in (("Simplebake wasn't able to check", "ERROR"), ("for updates", 'NONE')):
            row = layout.row(align=ALIGN)
            row.alignment = 'CENTER'
            row.scale_y = 0.6
            if icon != 'NONE':
                row.label(text=text, icon=icon)
            else:
                row.label(text=text)
        print_installed_ver()
        return

    if not VersionControl.at_current:
        for text, alert in (
            ("", True),
            ("Newer version of SimpleBake available", True),
            ("Update automatically in addon preferences", True),
        ):
            row = layout.row(align=ALIGN)
            row.alignment = 'CENTER'
            row.scale_y = 0.6
            row.alert = alert
            row.label(text=text, icon="MOD_WAVE" if text == "" else 'NONE')
        print_installed_ver()
        row = layout.row(align=ALIGN)
        row.alignment = 'CENTER'
        row.scale_y = 0.6
        row.label(text=f"Available Version: {VersionControl.current_version_str}")
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


# ---------------------------------------------------------------------------
# Main panel class
class SIMPLEBAKE_PT_main_panel:
    bl_label = "SimpleBake"
    bl_space_type = f"{space}"
    bl_region_type = f"{region}"
    bl_context = f"{context}"
    bl_category = f"{cat}"

    # -----------------------------------------------------------------------
    def draw_version_info(self, context, layout):
        draw_version_info(context, layout)

    # -----------------------------------------------------------------------
    def draw_global_mode_buttons(self, context, box):
        sbp = context.scene.SimpleBake_Props
        row = box.row(align=ALIGN)
        row.scale_y = 1.5
        row.prop(sbp, "global_mode", icon="SETTINGS", expand=True)
        row = box.row(align=ALIGN)
        row.operator("simplebake.panel_hide_all", icon='PROP_OFF', text="Hide all")
        row.operator("simplebake.panel_show_all", icon='PROP_ON', text="Show all")

    # -----------------------------------------------------------------------
    def draw_presets(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "presets_show", "Settings presets", section_icon='PRESET')

        if not sbp.presets_show:
            return

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

        prop_row(box, sbp, "preset_load_clear_obj")
        box.row(align=ALIGN).label(text="")

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

    # -----------------------------------------------------------------------
    def draw_objects_list(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "bake_objects_show", "Bake objects", section_icon='OUTLINER_OB_MESH')

        if not sbp.bake_objects_show:
            return

        row = box.row(align=ALIGN)
        col = row.column()
        col.template_list("SIMPLEBAKE_UL_Objects_List", "Bake Objects List", sbp,
                          "objects_list", sbp, "objects_list_index")
        col = row.column()
        col.scale_x = 0.32
        col.operator("simplebake.highlight_bake_objects", text="", icon="LIGHT_SPOT")
        col.operator("simplebake.remove_highlight", text="", icon="SHADING_BBOX")
        col.prop(sbp, "highlight_col", text="")

        row = box.row(align=ALIGN)
        row.operator('simplebake.add_bake_object', text='Add', icon="PRESET_NEW")
        row.operator('simplebake.remove_bake_object', text='Remove', icon="CANCEL")
        row.operator('simplebake.clear_bake_objects_list', text='Clear', icon="MATPLANE")

        row = box.row(align=ALIGN)
        row.operator('simplebake.move_bake_object_list', text='Up', icon="TRIA_UP").direction = "UP"
        row.operator('simplebake.move_bake_object_list', text='Down', icon="TRIA_DOWN").direction = "DOWN"
        row.operator('simplebake.refresh_bake_object_list', text='Refresh', icon="FILE_REFRESH")

        if sbp.highlight_on:
            monkey_tip(context, monkey_tip_formatter(
                "Objects are highlighted when viewport set to \"Solid\" shading. "
                "Must be re-enabled after Blender restart"), box)

        if sbp.global_mode == SBConstants.PBR:
            row, col_l, col_r = two_prop_row(box, sbp, "selected_s2a", "isolate_objects",
                                             "Bake to target", "Isolate objects")
            if sbp.tex_per_mat:
                col_l.enabled = False
            if sbp.join_objs_to_proxy:
                col_r.enabled = False
            if sbp.selected_s2a:
                self._draw_s2a_pbr(context, box, sbp)

        if sbp.global_mode == SBConstants.CYCLESBAKE:
            row, col_l, col_r = two_prop_row(box, sbp, "cycles_s2a", "isolate_objects",
                                             "Bake to target", "Isolate objects")
            if sbp.tex_per_mat:
                col_l.enabled = False
            if sbp.join_objs_to_proxy:
                col_r.enabled = False
            if sbp.cycles_s2a:
                self._draw_s2a_cycles(context, box, sbp)

        if check_for_render_inactive_modifiers(context):
            monkey_tip(context, [
                "One or more selected objects",
                "has a modifier enabled for",
                "render (and so baking), but disabled in",
                "viewport. May cause unexpected results"
            ], box)

        if check_for_viewport_inactive_modifiers(context):
            monkey_tip(context, [
                "One or more selected objects",
                "has a modifier enabled in the",
                "viewport, but disabled for",
                "render (and so baking).",
                "May cause unexpected results"
            ], box)

    def _draw_s2a_pbr(self, context, box, sbp):
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
            ##TODO - Move---------------------------------------------------------------------------------
            row.enabled = False if check_for_auto_cage(context) else True


            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.auto_cage", icon='ADD', text="Auto-generate cage")
            row.operator("simplebake.remove_auto_cage", icon='REMOVE', text="Remove auto-generated cage")

            if context.scene.render.bake.cage_object is not None:
                if 'SB_AUTO_CAGE' in context.scene.render.bake.cage_object.modifiers:
                    prop_row(box, sbp, "auto_cage_extrusion", text="Auto generated cage extrusion")

            if sbp.s2a_opmode == "decals":
                decals_tips(context, box)
            if sbp.s2a_opmode == "single":
                standard_s2a_tips(context, box)

        if sbp.s2a_opmode == "automatch":
            row = box.row(align=ALIGN)
            row.alignment = "RIGHT"
            row.prop(sbp, "auto_match_mode")
            auto_match_high_low_tips(context, box)

        self._draw_cage_settings(context, box, sbp)

    def _draw_s2a_cycles(self, context, box, sbp):
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
            row.enabled = False if check_for_auto_cage(context) else True

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.operator("simplebake.auto_cage", icon='ADD', text="Auto-generate cage")
            row.operator("simplebake.remove_auto_cage", icon='REMOVE', text="Remove auto-generated cage")

            if context.scene.render.bake.cage_object is not None:
                if 'SB_AUTO_CAGE' in context.scene.render.bake.cage_object.modifiers:
                    prop_row(box, sbp, "auto_cage_extrusion", text="Auto generated cage extrusion")

            standard_s2a_tips(context, box)

        if sbp.s2a_opmode in ["automatch"]:
            row = box.row(align=ALIGN)
            row.alignment = "RIGHT"
            row.prop(sbp, "auto_match_mode")
            auto_match_high_low_tips(context, box)

        self._draw_cage_settings(context, box, sbp)

    def _draw_cage_settings(self, context, box, sbp):
        cage_obj = context.scene.render.bake.cage_object

        row = box.row(align=ALIGN)
        row.alignment = "RIGHT"
        row.prop(sbp, "cage_smooth_hard")
        if cage_obj is not None:
            row.enabled = False

        row = box.row(align=ALIGN)
        row.use_property_split = True
        row.prop(sbp, "cage_extrusion")
        if cage_obj is not None:
            row.enabled = False

        row = box.row(align=ALIGN)
        row.use_property_split = True
        row.prop(sbp, "ray_distance")

        row = box.row(align=ALIGN)
        row.use_property_split = True
        row.prop(sbp, "cage_and_ray_multiplier")

    # -----------------------------------------------------------------------
    def draw_materials_section(self, context, box):
        sbp = context.scene.SimpleBake_Props

        section_header(box, sbp, "materials_show", "Materials", section_icon='MATERIAL')


        if not sbp.materials_show:
            return

        if not sbp.objects_list:
            box.label(text="No objects in the bake objects list", icon="INFO")
            return

        monkey_tip(context, monkey_tip_formatter(
            "Each object's materials are listed below. Use the checkboxes to "
            "include or exclude individual materials from the bake. Excluded "
            "materials will be skipped — no texture will be created for them."), box)

        row = box.row()
        row.scale_y = SCALE
        row.operator("simplebake.refresh_bake_object_list", text="Refresh Materials", icon="FILE_REFRESH")

        # tex_per_mat and expand_mat_uvs toggles
        prop_row(box, sbp, "tex_per_mat", enabled=not sbp.merged_bake and not sbp.selected_s2a and not sbp.cycles_s2a, text="Texture per material")


        box.separator(factor=0.5)

        row = box.row(align=True)
        row.scale_y = SCALE
        row.operator("simplebake.materials_expand_all", text="Expand All", icon="TRIA_DOWN")
        row.operator("simplebake.materials_collapse_all", text="Collapse All", icon="TRIA_RIGHT")

        # Per-object material lists
        for item in sbp.objects_list:
            if item.obj_point is None:
                continue
            obj = item.obj_point

            # Arrow + plain label — label is always left-aligned and unaffected by toggle mode
            row = box.row(align=True)
            row.scale_y = SCALE
            icon = "TRIA_DOWN" if item.expanded else "TRIA_RIGHT"
            row.prop(item, "expanded", text="", icon=icon, emboss=False)
            row.label(text=obj.name, icon="OBJECT_DATA")

            if item.expanded:
                mat_entries = [e for e in sbp.mat_bake_list if e.obj_name == obj.name]
                if not mat_entries:
                    box.label(text="No materials", icon="INFO")
                else:
                    col = box.column(align=True)
                    col.scale_y = 0.9
                    for entry in mat_entries:
                        row2 = col.row(align=True)
                        # Checkbox style — clearer as an include/exclude control than a toggle
                        row2.prop(entry, "enabled", text=entry.mat_name, icon="MATERIAL")

    # -----------------------------------------------------------------------
    def draw_pbr_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "pbr_settings_show", "PBR Bakes", section_icon='NODE_MATERIAL')

        if not sbp.pbr_settings_show:
            return

        if sbp.preview_active:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert = True
            row.operator("simplebake.restore_preview", icon="LOOP_BACK")

        two_prop_row_preview(box, sbp, "selected_col", "selected_metal",
                             SBConstants.PBR_DIFFUSE, SBConstants.PBR_METAL)

        # Roughness / Normal — Normal has no preview
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        col_l = row.column()
        col_l.prop(sbp, "selected_rough", toggle=TOGGLES)
        preview_eye(row, sbp.selected_rough, sbp.rough_glossy_switch)
        col_r = row.column()
        col_r.prop(sbp, "selected_normal", toggle=TOGGLES)
        # Placeholder to match the preview eye column width on other rows
        col_placeholder = row.column()
        col_placeholder.label(text="", icon="BLANK1")

        # Transmission row — right col disabled on Blender 4+
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        col_l = row.column()
        col_l.prop(sbp, "selected_trans", toggle=TOGGLES)
        preview_eye(row, sbp.selected_trans, SBConstants.PBR_TRANSMISSION)
        col_r = row.column()
        t = "                " if bpy.app.version >= (4, 0, 0) else "Transmission Roughness"
        col_r.prop(sbp, "selected_transrough", toggle=TOGGLES, text=t)
        if bpy.app.version >= (4, 0, 0):
            col_r.enabled = False
        preview_eye(row, sbp.selected_transrough and bpy.app.version < (4, 0, 0), SBConstants.PBR_TRANSMISSION_ROUGH)

        two_prop_row_preview(box, sbp, "selected_clearcoat", "selected_clearcoat_rough",
                             SBConstants.PBR_CLEARCOAT, sbp.ccrough_glossy_switch)
        two_prop_row_preview(box, sbp, "selected_emission", "selected_emission_strength",
                             SBConstants.PBR_EMISSION, SBConstants.PBR_EMISSION_STRENGTH)

        # Specular / Alpha — alpha disabled for decals
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        col_l = row.column()
        col_l.prop(sbp, "selected_specular", toggle=TOGGLES)
        preview_eye(row, sbp.selected_specular, SBConstants.PBR_SPECULAR)
        col_r = row.column()
        col_r.prop(sbp, "selected_alpha", toggle=TOGGLES)
        if sbp.selected_s2a and sbp.s2a_opmode == "decals":
            col_r.enabled = False
        preview_eye(row, sbp.selected_alpha and not (sbp.selected_s2a and sbp.s2a_opmode == "decals"), SBConstants.PBR_ALPHA)

        two_prop_row_preview(box, sbp, "selected_sss", "selected_sss_scale",
                             SBConstants.PBR_SSS, SBConstants.PBR_SSS_SCALE)
        two_prop_row_preview(box, sbp, "selected_bump", "selected_displacement",
                             SBConstants.PBR_BUMP, SBConstants.PBR_DISPLACEMENT)

        row = box.row(align=ALIGN)
        row.scale_y = 0.2
        row.label(text="")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.selectall_pbr", icon='ADD')
        row.operator("simplebake.selectnone_pbr", icon='REMOVE')
        row.operator("simplebake.autodetect_pbr_channels", icon='LIGHT', text="Attempt to auto-detect")

        # Extra options
        #All extra options need us to be saving externally

        enabled = sbp.save_bakes_external
        if sbp.selected_col or sbp.selected_rough or sbp.selected_normal:
            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.label(text="Extra Options:")
            if not sbp.save_bakes_external:
                monkey_tip(context, [
                    "These options are greyed out",
                    "because you are not exporting",
                    "your bakes externally"
                ], box)

        if sbp.selected_col and sbp.s2a_opmode != "decals":
            prop_row(box, sbp, "multiply_diffuse_ao", enabled=enabled, small_row=True, text="Diffuse")
            if sbp.multiply_diffuse_ao == "diffusexao":
                prop_row(box, sbp, "multiply_diffuse_ao_percent", small_row=True)

        if sbp.selected_rough:
            prop_row(box, sbp, "rough_glossy_switch", enabled=enabled, small_row=True, text="Rough/Gloss")

        if sbp.selected_clearcoat_rough:
            prop_row(box, sbp, "ccrough_glossy_switch", enabled=enabled, small_row=True, text="CC Rough/Gloss")

        if sbp.selected_normal:
            prop_row(box, sbp, "normal_format_switch", enabled=enabled, small_row=True, text="Normal Format")
            prop_row(box, context.scene.render.bake, "normal_space", enabled=enabled, text="Normal Space", small_row=True)
            prop_row(box, context.scene.render.bake, "normal_r", enabled=enabled, text="Swizzle R", small_row=True)
            prop_row(box, context.scene.render.bake, "normal_g", enabled=enabled, text="G", small_row=True)
            prop_row(box, context.scene.render.bake, "normal_b", enabled=enabled, text="B", small_row=True)
            if context.scene.render.bake.normal_space == 'OBJECT':
                prop_row(box, context.scene.render.bake, "margin_type", enabled=enabled, text="Normal Margin", small_row=True)



        if check_for_convertible_shaders(context) and not sbp.preview_active:
            monkey_tip(context, monkey_tip_formatter(
                "WARNING: Some materials on your bake objects use non-PBR shader nodes "
                "(e.g., Diffuse, Glossy). SimpleBake will TRY to match them for PBR, but "
                "results may vary. It's recommended to use the 'Attempt to auto-detect' button, "
                "as you may not expect the PBR maps needed after conversion. You will always get "
                "the best results from reworking your materials to be based around the Principled BSDF"
            ), box)

    # -----------------------------------------------------------------------
    def draw_aov_bakes(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "aov_settings_show", "AOV Bakes", section_icon='RENDERLAYERS')

        if not sbp.aov_settings_show:
            return

        row = box.row()
        row.scale_y = SCALE
        row.operator("simplebake.refresh_aov_list", text="Refresh AOVs", icon="FILE_REFRESH")

        if len(sbp.aov_items) == 0:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.label(text="No AOV Output nodes found in your bake object(s)' materials'")
        else:
            for item in sbp.aov_items:
                row = box.row(align=ALIGN)
                row.scale_y = SCALE
                name = item.name if item.name != "" else "Untitled"
                row.prop(item, "enabled", text=name, toggle=TOGGLES)
                row.prop(item, "cs")
                row = box.row(align=ALIGN)
                row.scale_y = 0.1
                row.label(text=f"(Object: \"{item.object_name}\", Material: \"{item.mat_name}\")")

        monkey_tip(context, monkey_tip_formatter(
            "You can use AOV Output Nodes in your materials to capture specific outputs and "
            "effectively create custom bake maps. "
            "Whatever you connect to an AOV Output Node's input will be baked as a separate map."
        ), box)

    # -----------------------------------------------------------------------
    def draw_cyclesbake_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "cyclesbake_settings_show", "CyclesBake", section_icon='RENDER_RESULT')

        if not sbp.cyclesbake_settings_show:
            return

        cscene = context.scene.cycles
        cbk = context.scene.render.bake

        box.row(align=ALIGN).prop(cscene, "bake_type")
        box.row(align=ALIGN).prop(context.scene.render.bake, "view_from")

        if cscene.bake_type == 'NORMAL':
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(cbk, "normal_space", text="Space")
            sub = col.column()
            sub.prop(cbk, "normal_r", text="Swizzle R")
            sub.prop(cbk, "normal_g", text="Swizzle G")
            sub.prop(cbk, "normal_b", text="Swizzle B")

        elif cscene.bake_type == 'COMBINED':
            two_prop_row(box, cbk, "use_pass_direct", "use_pass_indirect")
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.active = cbk.use_pass_direct or cbk.use_pass_indirect
            two_prop_row(box, cbk, "use_pass_diffuse", "use_pass_glossy")
            two_prop_row(box, cbk, "use_pass_transmission", "use_pass_emit")

        elif cscene.bake_type in {'DIFFUSE', 'GLOSSY', 'TRANSMISSION'}:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.column().prop(cbk, "use_pass_direct", toggle=TOGGLES)
            row.column().prop(cbk, "use_pass_indirect", toggle=TOGGLES)
            row.column().prop(cbk, "use_pass_color", toggle=TOGGLES)

        row = box.row(align=ALIGN)
        row.column().prop(context.scene.cycles, "samples")

        if sbp.global_mode == SBConstants.CYCLESBAKE and cscene.bake_type != "NORMAL":
            box.row(align=ALIGN).prop(sbp, "cyclesbake_cs")

        denoise_options(box)

    # -----------------------------------------------------------------------
    def draw_specials_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "specials_show", "Special bakes", section_icon='EXPERIMENTAL')
        need_denoise_options = False

        if not sbp.specials_show:
            return

        if sbp.preview_active:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert = True
            row.operator("simplebake.restore_preview", icon="LOOP_BACK")

        # Colour ID / Vertex Colour
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        col_l = row.column()
        col_l.prop(sbp, "selected_col_mats", toggle=TOGGLES)
        if sbp.selected_s2a or sbp.cycles_s2a:
            col_l.enabled = False
        preview_eye(row, sbp.selected_col_mats and not (sbp.selected_s2a or sbp.cycles_s2a), SBConstants.COLOURID)
        col_r = row.column()
        col_r.prop(sbp, "selected_col_vertex", toggle=TOGGLES)
        preview_eye(row, sbp.selected_col_vertex, SBConstants.VERTEXCOL)

        two_prop_row_preview(box, sbp, "selected_curvature", "selected_thickness",
                             SBConstants.CURVATURE, SBConstants.THICKNESS)

        # AO / Lightmap
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        col_l = row.column()
        col_l.prop(sbp, "selected_ao", toggle=TOGGLES)
        if sbp.global_mode == SBConstants.PBR and sbp.multiply_diffuse_ao == "diffusexao":
            col_l.enabled = False
        preview_eye(row, sbp.selected_ao and not (sbp.global_mode == SBConstants.PBR and sbp.multiply_diffuse_ao == "diffusexao"), SBConstants.AO)
        col_r = row.column()
        col_r.prop(sbp, "selected_lightmap", toggle=TOGGLES)
        if sbp.selected_s2a or sbp.cycles_s2a:
            col_r.enabled = False
        preview_eye(row, sbp.selected_lightmap and not (sbp.selected_s2a or sbp.cycles_s2a), SBConstants.LIGHTMAP)

        if sbp.selected_ao or sbp.selected_thickness or sbp.selected_lightmap:
            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.label(text="Extra options:")

        if sbp.selected_ao or sbp.selected_thickness:
            box.row(align=ALIGN).prop(sbp, "ao_sample_count")
            if sbp.global_mode == SBConstants.PBR:
                need_denoise_options = True

        if sbp.selected_lightmap and sbp.global_mode == SBConstants.PBR:
            prop_row(box, context.scene.cycles, "samples", text="Lightmap Sample Count")
            need_denoise_options = True

        if sbp.selected_lightmap:
            row = prop_row(box, sbp, "lightmap_apply_colman", text="Lightmap apply colour management")
            if not sbp.save_bakes_external:
                row.enabled = False

        if need_denoise_options:
            box.row(align=ALIGN)
            denoise_options(box)

        # Tips
        if (sbp.selected_lightmap or sbp.selected_ao or sbp.selected_thickness) and sbp.global_mode == SBConstants.PBR:
            monkey_tip(context, monkey_tip_formatter(
                f"Sample count and denoise are not normally relevant for PBR Bake, but they are for "
                f"{SBConstants.LIGHTMAP}, {SBConstants.AO} and {SBConstants.THICKNESS}"
            ), box)

        if sbp.selected_lightmap and sbp.global_mode == SBConstants.CYCLESBAKE:
            monkey_tip(context, monkey_tip_formatter(
                "Lightmap will have sample count and denoise settings that you have set for CyclesBake above"
            ), box)

        if (sbp.selected_ao or sbp.selected_thickness) and sbp.global_mode == SBConstants.CYCLESBAKE:
            monkey_tip(context, [
                "AO and thickness will have",
                "denoise settings that",
                "you have set for CyclesBake above"
            ], box)

        if sbp.selected_s2a or sbp.cycles_s2a:
            monkey_tip(context, ["Lightmap is unavailable when", "baking to target object for now"], box)

        monkey_tip(context, monkey_tip_formatter(
            "Use the eye icon next to a specials bake type to preview it. "
            "You can then edit the material directly (e.g. adjust curvature strength). "
            "Your changes will be used for all bakes of that type in this file."
        ), box)

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.reset_specials_materials", icon="TRASH")

    # -----------------------------------------------------------------------
    def draw_texture_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "textures_show", "Texture settings", section_icon='TEXTURE')

        if not sbp.textures_show:
            return

        row = box.row(align=ALIGN)
        row.scale_y = 0.5
        row.label(text="Bake at:")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.prop(sbp, "imgwidth")
        row.prop(sbp, "imgheight")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.decrease_texture_res", icon="TRIA_DOWN")
        row.operator("simplebake.increase_texture_res", icon="TRIA_UP")

        box.row(align=ALIGN)

        row = box.row(align=ALIGN)
        row.scale_y = 0.5
        row.label(text="Output at:")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.prop(sbp, "outputwidth")
        row.prop(sbp, "outputheight")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.decrease_output_res", icon="TRIA_DOWN")
        row.operator("simplebake.increase_output_res", icon="TRIA_UP")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.alignment = "RIGHT"
        row.prop(context.scene.render.bake, "margin", text="Bake Margin")

        try:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alignment = "RIGHT"
            row.prop(context.scene.render.bake, "margin_type", text="Margin Type")
        except:
            pass

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.prop(sbp, "texture_bg_col", text="Texture BG Colour")

        if (sbp.texture_bg_col[3] < 1.0) and sbp.save_bakes_external:
            monkey_tip(context, monkey_tip_formatter(
                "NOTE: Normally, for 'non-color' textures (e.g. metalness, roughness etc), the custom background "
                "colour will be lost when exporting, as these are saved as single-channel greyscale. "
                "However, as you have set an alpha value below 1.0, ALL textures will be exported as RGBA and the "
                "background colour + alpha will be preserved."
            ), box)

        row, col_l, col_r = two_prop_row(box, sbp, "everything32bitfloat", "clear_image",
                                         label_right="Clear image before bake")
        if sbp.export_file_format == "JPEG" or not sbp.clear_image:
            col_l.enabled = False

        row = prop_row(box, sbp, "merged_bake")
        if sbp.tex_per_mat:
            row.enabled = False

        if sbp.merged_bake:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.column().prop(sbp, "merged_bake_name", text="Texture set name")
            row.column().prop(sbp, "join_objs_to_proxy", text="Join bake objects", toggle=TOGGLES)

            if sbp.join_objs_to_proxy:
                monkey_tip(context, monkey_tip_formatter(
                    "WARNING: When using the option to join objects before baking, any materials "
                    "that rely on 'Generated' (or 'Object') texture coordinates may appear "
                    "differently after the join. This can cause baked textures to look incorrect. "
                    "Consider disabling this option if your materials use these coordinates. "
                    "Also note that the 'Isolate Objects' option will not function when objects are "
                    "joined, as individual objects cannot be hidden from each other once combined."
                ), box)

        if len(sbp.objects_list) < 2 and sbp.merged_bake or \
                ((sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode != "automatch"):
            monkey_tip(context, [
                "You are baking multiple objects to one",
                "texture set, but have fewer then 2",
                "in the bake list. This is OK, but",
                "might not be what you wanted"
            ], box)

        row = box.row(align=ALIGN)
        col = row.column()
        col.scale_y = SCALE
        col.prop(sbp, "do_aa", text="Anti-aliasing", toggle=TOGGLES)
        if not sbp.save_bakes_external:
            col.enabled = False
        row.column().scale_y = SCALE  # spacer column

        if sbp.do_aa:
            box.row(align=ALIGN).prop(sbp, "aa_threshold", text="AA Threshold")
            box.row(align=ALIGN).prop(sbp, "aa_contrast_limit", text="AA Contrast limit")
            box.row(align=ALIGN).prop(sbp, "aa_corner_radius", text="AA Corner radius")

    # -----------------------------------------------------------------------
    def draw_export_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "export_show", "Export settings", section_icon='EXPORT')

        if not sbp.export_show:
            return

        if not is_blend_saved():
            box.row(align=ALIGN).label(text="Unavailable - Blend file not saved")
            return

        _, _, col_obj = two_prop_row(box, sbp, "save_bakes_external", "save_obj_external")
        col_obj.enabled = sbp.save_bakes_external

        if sbp.save_bakes_external or sbp.save_obj_external:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "export_path", text="Export Path")
            row.column().operator("simplebake.export_path_to_blend_location", text="", icon="UV_SYNC_SELECT")
            prop_row(box, sbp, "export_folder_per_object")

        if sbp.save_bakes_external:
            if sbp.global_mode == SBConstants.PBR:
                row = prop_row(box, sbp, "apply_col_man_to_col")
                if not sbp.selected_col:
                    row.enabled = False

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            if sbp.export_file_format not in ("OPEN_EXR", "JPEG", "TARGA"):
                row.prop(sbp, "everything_16bit", toggle=TOGGLES)

            if sbp.global_mode == SBConstants.CYCLESBAKE:
                row = prop_row(box, sbp, "export_cycles_col_space")
                if context.scene.cycles.bake_type == "NORMAL":
                    row.enabled = False

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "export_file_format", text="Format")
            if sbp.export_file_format == "OPEN_EXR":
                row.column().prop(sbp, "exr_codec_export")
            if sbp.export_file_format == "JPEG":
                row.column().prop(sbp, "jpeg_quality", slider=True)

            prop_row(box, sbp, "keep_internal_after_export")

        if sbp.save_obj_external:
            prop_row(box, sbp, "export_mesh_individual_or_combined", text="Mesh objects")
            if sbp.export_mesh_individual_or_combined == "combined":
                prop_row(box, sbp, "merge_export_obj", text="Combine objects within export file")
            prop_row(box, sbp, "export_format")
            prop_row(box, sbp, "apply_mods_on_mesh_export")
            if sbp.export_format == "fbx":
                prop_row(box, sbp, "apply_transformation")
            if sbp.export_mesh_individual_or_combined == "combined":
                prop_row(box, sbp, "mesh_export_name", text="Mesh name")
            prop_row(box, sbp, "export_mesh_preset_name")

        if sbp.everything32bitfloat and not sbp.save_bakes_external:
            monkey_tip(context, [
                "You are baking in 32bit float",
                "but not exporting externally.",
                "You may want to export to EXR",
                "to preserve your 32bit image(s)"
            ], box)

        if sbp.export_file_format == "OPEN_EXR" and sbp.save_bakes_external:
            monkey_tip(context, [
                "Note: EXR files cannot be exported",
                "with colour management settings.",
                "EXR doesn't support them. Even",
                "Blender defaults will be ignored"
            ], box)

    # -----------------------------------------------------------------------
    def draw_uv_settings(self, context, box):

        sbp = context.scene.SimpleBake_Props


        section_header(box, sbp, "uv_show", "UV settings", section_icon='UV_DATA')

        if sbp.uv_show:

            #Tex per mat is a special case with just one option
            if sbp.tex_per_mat:
                prop_row(box, sbp, "expand_mat_uvs")


            # row = box.row(align=ALIGN)
            # row.scale_y = SCALE
            # if sbp.new_uv_option:
            #     row.label(text="Going to create new UVs")
            # else:
            #     row.label(text="Will use existing UVs")

            if not sbp.tex_per_mat:
                prop_row(box, sbp, "new_uv_option")

            if not sbp.new_uv_option:
                prop_row(box, sbp, "auto_detect_udims")

                if sbp.auto_detect_udims:
                    message_lines = monkey_tip_formatter("UDIM tiles are detected when UVs extend beyond standard UV space. Objects with and without UDIM tiles can be baked together. \
                        When using 'Multiple objects to one texture set,' if any object has UDIM tiles, all objects will be baked to that UDIM set")
                    monkey_tip(context, message_lines, box)

                    if sbp.selected_s2a and sbp.targetobj is not None:
                        udim_objs = [sbp.targetobj.name]
                    elif sbp.selected_s2a and sbp.targetobj_cycles is not None:
                        udim_objs = [sbp.targetobj_cycles.name]
                    else:
                        udim_objs = [i.name for i in sbp.objects_list]

                    udim_n = 0
                    for obj_name in udim_objs:
                        try:
                            r = get_cached_udim_tiles(context, obj_name, threshold=0.001)
                            if r["bbox_tiles"] > udim_n:
                                udim_n = r["bbox_tiles"]
                        except:
                            pass

                    row = box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.label(text=f"UDIM tiles to bake: {udim_n}")

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
                        prop_row(box, sbp, "uvcorrectaspect")
                else: #Combine
                    row = box.row(align=ALIGN)
                    row.alignment = "RIGHT"

                #Advanced UV packing options
                n = int(''.join(c for c in bpy.app.version_string if c.isdigit()))
                if sbp.new_uv_method in ["CombineExisting"] and n >= 360:

                    row=box.row(align=ALIGN)
                    row.scale_y = SCALE
                    row.prop(sbp, "average_uv_size", text="Average UV island size")

                    two_prop_row(box, sbp, "uvp_rotate", "uvp_scale")

                    two_prop_row(box, sbp, "uvp_lock_pinned", "uvp_merge_overlapping")

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
                if sbp.expand_mat_uvs:
                    #No options
                    pass
                elif (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch" and len(viable_high_low) >1:
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
                two_prop_row(box, sbp, "prefer_existing_sbmap", "restore_orig_uv_map",
                             label_left="Prefer existing UVs called SimpleBake", label_right="Restore original UVs")

            if sbp.new_uv_option:
                two_prop_row(box, sbp, "move_new_uvs_to_top", "restore_orig_uv_map",
                             label_right="Restore original UVs")

            #List for when we are using existing UVs
            if not sbp.new_uv_option or (sbp.new_uv_option and sbp.new_uv_method == 'CombineExisting') or sbp.expand_mat_uvs:

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
                monkey_tip(context, message_lines, box)


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

    # -----------------------------------------------------------------------
    def draw_other_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "other_show", "Other settings", section_icon='SETTINGS')

        if not sbp.other_show:
            return

        prop_row(box, sbp, "batch_name")
        prop_row(box, sbp, "image_sequence_enabled")

        if sbp.image_sequence_enabled:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.prop(sbp, "image_sequence_start_frame")
            row.prop(sbp, "image_sequence_end_frame")
            monkey_tip(context, monkey_tip_formatter(
                "NOTE: If you haven't added %FRAME% to your image format "
                "string in the SimpleBake addon preferences, it will "
                "be added automatically to the end of the names of your baked images"
            ), box)

        dt = False
        t = "Copy objects and apply bakes"
        t = f"{t} (after import)" if sbp.bgbake == "bg" else t
        row = prop_row(box, sbp, "copy_and_apply", text=t)
        if not sbp.keep_internal_after_export:
            dt = True
            row.enabled = False

        if sbp.copy_and_apply:
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            t = "Hide source objects after bake"
            t = f"{t} (after import)" if sbp.bgbake == "bg" else t
            col.prop(sbp, "hide_source_objects", text=t, toggle=TOGGLES)
            if sbp.selected_s2a or sbp.cycles_s2a:
                t2 = "Hide cage object after bake"
                t2 = f"{t2} (after import)" if sbp.bgbake == "bg" else t2
                row.column().prop(sbp, "hide_cage_object", text=t2, toggle=TOGGLES)

            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            col = row.column()
            col.prop(sbp, "create_glTF_node", toggle=TOGGLES)
            if sbp.create_glTF_node:
                row.column().prop(sbp, "glTF_selection", text="", toggle=TOGGLES)

            if sbp.global_mode == SBConstants.CYCLESBAKE:
                prop_row(box, sbp, "cyclesbake_copy_and_apply_mat_format", text="Material")

        row = prop_row(box, sbp, "apply_bakes_to_original", text="Apply bakes to original objects")
        if sbp.bgbake == "bg" or not sbp.keep_internal_after_export or sbp.tex_per_mat:
            dt = True
            row.enabled = False

        if dt:
            if sbp.tex_per_mat:
                monkey_tip(context, monkey_tip_formatter(
                    "'Apply bakes to original objects' is not available when Texture Per Material is enabled"
                ), box)
            elif not sbp.keep_internal_after_export:
                monkey_tip(context, monkey_tip_formatter(
                    "'Copy objects and apply bakes' and 'Apply bakes to original objects' aren't "
                    "available as you have chosen not to keep bakes internally after export. "
                    "Turn that back on under 'Export Settings' to use these options"
                ), box)

        if sbp.apply_bakes_to_original:
            monkey_tip(context, [
                "Be careful when applying bakes to",
                "original objects. Original materials won't",
                "be deleted, BUT they will have no users",
                "and may be purged on next save"
            ], box)

        if sbp.apply_bakes_to_original and sbp.restore_orig_uv_map:
            monkey_tip(context, [
                "You are restoring your original UVs",
                "after bake, but also applying the baked",
                "textures to original objects. The textures",
                "may not look right with original UVs"
            ], box)

        row, col_l, col_r = two_prop_row(box, sbp, "no_force_32bit_normals", "boosted_sample_count")
        if sbp.global_mode != SBConstants.PBR:
            col_r.enabled = False

        prop_row(box, sbp, "bw_to_rgb")

        if context.preferences.addons["cycles"].preferences.has_active_device():
            box.row(align=ALIGN).prop(context.scene.cycles, "device")
        else:
            box.row(align=ALIGN).label(text="No valid GPU device in Blender Preferences. Using CPU.")

        if (context.preferences.addons["cycles"].preferences.compute_device_type == "OPTIX" and
                context.preferences.addons["cycles"].preferences.has_active_device()):
            monkey_tip(context, [
                "Other users have reported problems baking",
                "with GPU and OptiX. This is a Blender issue",
                "If you encounter problems bake with CPU"
            ], box)

        if (sbp.global_mode == SBConstants.PBR and sbp.copy_and_apply and
                len(pbr_selections_to_list(context)) == 0 and
                len(specials_selection_to_list(context)) > 0):
            monkey_tip(context, [
                "You are baking only special maps (no primary)",
                "while using 'Copy objects and apply bakes'",
                "Special maps will be in the new object(s)",
                "material(s), but disconnected"
            ], box)

    # -----------------------------------------------------------------------
    def draw_channel_packing(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "channelpacking_show", "Channel packing", section_icon='NODE_COMPOSITING')

        if not sbp.channelpacking_show:
            return

        if not is_blend_saved():
            box.row(align=ALIGN).label(text="Unavailable - Blend file not saved")
            return

        if not sbp.save_bakes_external:
            box.row(align=ALIGN).label(text="Unavailable - You must be exporting your bakes")
            return

        row = box.row(align=ALIGN)
        col = row.column()
        col.template_list("SIMPLEBAKE_UL_CPTexList", "CP Textures List", sbp,
                          "cp_list", sbp, "cp_list_index")
        col = row.column()
        col.operator("simplebake.cptex_delete", text="", icon="CANCEL")
        col.operator("simplebake.cptex_set_defaults", text="", icon="FILE_REFRESH")

        # Name field and RGBA channel selectors always shown (needed to create or edit entries)
        prop_row(box, sbp, "cp_name")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.prop(sbp, "channelpackfileformat", text="Format")
        if sbp.channelpackfileformat == "OPEN_EXR":
            row.prop(sbp, "exr_codec_cpts")
        if sbp.channelpackfileformat == "PNG":
            row.prop(sbp, "png_compression", text="Compression")

        for channel, prop in (("R", "cptex_R"), ("G", "cptex_G"),
                              ("B", "cptex_B"), ("A", "cptex_A")):
            row = box.row(align=ALIGN)
            row.scale_y = 0.7
            row.prop(sbp, prop, text=channel)

        # Save/update button logic: check if cp_name already exists in the list
        cp_list = sbp.cp_list
        current_name = sbp.cp_name
        if current_name in cp_list:
            # Editing an existing saved entry — show update button only if something changed
            index = cp_list.find(current_name)
            cpt = cp_list[index]
            if (cpt.R != sbp.cptex_R or cpt.G != sbp.cptex_G or
                    cpt.B != sbp.cptex_B or cpt.A != sbp.cptex_A or
                    cpt.file_format != sbp.channelpackfileformat or
                    cpt.exr_codec != sbp.exr_codec_cpts or
                    cpt.png_compression != sbp.png_compression):
                row = box.row(align=ALIGN)
                row.alert = True
                row.operator("simplebake.cptex_add", text=f"Update {current_name} (!!not saved!!)", icon="ADD")
            else:
                row = box.row(align=ALIGN)
                row.label(text=f"Editing {current_name}")
                row.alignment = 'CENTER'
        else:
            # New entry
            row = box.row(align=ALIGN)
            row.alert = True
            row.operator("simplebake.cptex_add", text="Add new (!!not saved!!)", icon="ADD")

        if sbp.cptex_R == "" or sbp.cptex_G == "" or sbp.cptex_B == "" or sbp.cptex_A == "":
            row.enabled = False

        row = prop_row(box, sbp, "del_cptex_components")
        if sbp.copy_and_apply or sbp.apply_bakes_to_original:
            row.enabled = False

    # -----------------------------------------------------------------------
    def draw_admin_settings(self, context, box):
        sbp = context.scene.SimpleBake_Props
        section_header(box, sbp, "admin_settings_show", "Utilities", section_icon='TOOL_SETTINGS')

        if not sbp.admin_settings_show:
            return

        for op_id, label in (
            ("simplebake.purge_settings",   "x-- SETTINGS --x"),
            ("simplebake.restorematerials", "x-- MATERIALS --x"),
            ("simplebake.purge_images",     "X-- IMAGES --X"),
            ("simplebake.purge_objects",    "X-- OBJECTS --X"),
        ):
            row = box.row(align=ALIGN)
            row.scale_y = SCALE
            row.alert = True
            row.operator(op_id, text=label, icon="ERROR")

        prop_row(box, sbp, "tex_override")
        if sbp.tex_override:
            prop_row(box, sbp, "tex_override_tex")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.label(text="Find and replace")
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.prop(sbp, "findreplace_find", toggle=TOGGLES)
        row.prop(sbp, "findreplace_replace", toggle=TOGGLES)
        prop_row(box, sbp, "findreplace_type")
        prop_row(box, sbp, "limit_findandreplace_to_sb", text="Limit to SB data")
        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.findandreplace", text="Find and replace", icon="VIEWZOOM")

        row = box.row(align=ALIGN)
        row.scale_y = SCALE
        row.operator("simplebake.copy_settings_clipboard", icon='COPYDOWN')
        row.operator("simplebake.paste_settings_clipboard", icon='PASTEDOWN')

    # -----------------------------------------------------------------------
    def draw_bake_buttons(self, context, box):

        sbp = context.scene.SimpleBake_Props
        n = 0
        if sbp.selected_s2a and sbp.targetobj!=None: objs = [sbp.targetobj.name]
        elif sbp.selected_s2a and sbp.targetobj_cycles!=None: objs = [sbp.targetobj_cycles.name]
        else: objs = [i.name for i in sbp.objects_list]

        for obj_name in objs:
            try:
                result = get_cached_udim_tiles(context, obj_name, threshold=0.001)
                if result["bbox_tiles"] > n:
                    n = result["bbox_tiles"]
            except:
                pass

        if n>20 and sbp.auto_detect_udims:
            def alert_row(text, icon=None):
                row = box.row(align=ALIGN)
                row.alignment = 'CENTER'
                row.scale_y = 0.6
                row.alert = True
                row.label(text=text, **({"icon": icon} if icon else {}))

            alert_row(f"WARNING: You are about to bake at least {n} UDIM tiles!!!", icon="ERROR")
            alert_row("This is high. If intentional, that's fine.")
            alert_row("However, it often means UVs are not suitable for baking.")
            alert_row("In the worst case, Blender may run out of memory or crash.")
            alert_row("PLEASE CHECK YOUR UV MAPS!")


        # Determine operator, icon, text and flags
        bg = sbp.bgbake == "bg"
        s2a = sbp.selected_s2a or sbp.cycles_s2a
        disable_if_is = False
        bg_name = False

        if s2a and sbp.s2a_opmode == "decals":
            if bg:
                op, icon, text = "simplebake.bake_operation_decals_background", 'RENDER_RESULT', "Bake! (Decals) (Background)"
                bg_name = disable_if_is = True
            else:
                op, icon, text = "simplebake.bake_operation_decals", 'RENDER_RESULT', "Bake! (Decals)"

        elif s2a and sbp.s2a_opmode == "automatch":
            if bg:
                op, icon, text = "simplebake.automatch_operation_background", 'RENDER_RESULT', "Bake! (Auto Match) (Background)"
                bg_name = disable_if_is = True
            else:
                op, icon, text = "simplebake.automatch_operation", 'RENDER_RESULT', "Bake! (Auto Match)"

        elif sbp.global_mode == SBConstants.PBR and not sbp.selected_s2a:
            if bg:
                op, icon, text = "simplebake.bake_operation_pbr_background", 'RENDER_RESULT', "Bake! (in background)"
                bg_name = disable_if_is = True
            else:
                op, icon, text = "simplebake.bake_operation_pbr", 'RENDER_RESULT', "Bake!"

        elif sbp.global_mode == SBConstants.PBR and sbp.selected_s2a:
            if bg:
                op, icon, text = "simplebake.bake_operation_pbrs2a_background", 'RENDER_RESULT', "Bake! (in background)"
                bg_name = disable_if_is = True
            else:
                op, icon, text = "simplebake.bake_operation_pbrs2a", 'RENDER_RESULT', "Bake! (to target)"

        elif sbp.global_mode == SBConstants.CYCLESBAKE and not sbp.cycles_s2a:
            if bg:
                op, icon, text = "simplebake.bake_operation_cyclesbake_background", 'RENDER_RESULT', "Bake! (in background)"
                bg_name = True
            else:
                op, icon, text = "simplebake.bake_operation_cyclesbake", 'RENDER_RESULT', "Bake!"

        elif sbp.global_mode == SBConstants.CYCLESBAKE and sbp.cycles_s2a:
            if bg:
                op, icon, text = "simplebake.bake_operation_cyclesbake_s2a_background", 'RENDER_RESULT', "Bake! (in background)"
                bg_name = disable_if_is = True
            else:
                op, icon, text = "simplebake.bake_operation_cyclesbake_s2a", 'RENDER_RESULT', "Bake! (to target)"

        else:
            op, icon, text = "simplebake.bake_operation_pbr", 'RENDER_RESULT', "Bake!"

        # FG/BG switch — always shown at the bottom of the bake box
        row = box.row(align=ALIGN)
        row.scale_y = 1.5
        row.prop(sbp, "bgbake", expand=True)

        if bg_name:
            prop_row(box, sbp, "bgbake_name")

        row = box.row(align=ALIGN)
        row.scale_y = 2
        # Sequence bakes require the image_sequence modal operator (see note
        # in disable_row_if_image_sequence). Background mode is mutually
        # exclusive and is already blocked by disable_row_if_image_sequence.
        if sbp.image_sequence_enabled and not bg:
            row.operator("simplebake.image_sequence", icon='RENDER_RESULT', text="Bake, image sequence").cmd = op
        else:
            row.operator(op, icon=icon, text=text)

        if BakeInProgress.is_baking:
            row.enabled = False
        if disable_if_is: disable_row_if_image_sequence(context, row, box)

        if space == 'VIEW_3D':
            monkey_tip(context, monkey_tip_formatter(
                "WARNING: Based on my testing, Blender crashes WAY more when SimpleBake "
                "is displayed in the N-Panel. I haven't been able to find out why. "
                "Use with extreme caution!"
            ), box)

    # -----------------------------------------------------------------------
    def draw_fg_bake_status(self, context, box):
        sbp = context.scene.SimpleBake_Props
        for text, alert in (("FOREGROUND BAKE", True), ("IN PROGRESS", True), ("Please wait", False)):
            row = box.row(align=ALIGN)
            row.scale_y = 0.5
            row.alignment = 'CENTER'
            row.alert = alert
            row.label(text=text)
        row = box.row(align=ALIGN)
        row.alignment = 'CENTER'
        row.label(text=f"{sbp.percent_complete}% complete")

    # -----------------------------------------------------------------------
    def draw_background_bakes(self, context, box):
        sbp = context.scene.SimpleBake_Props
        active = BackgroundBakeTasks.active_tasks
        queued = BackgroundBakeTasks.queued_tasks
        completed = BackgroundBakeTasks.completed_tasks

        section_header(box, sbp, "bg_status_show", "Background bakes", section_icon='RENDER_ANIMATION')

        if not sbp.bg_status_show:
            return

        box.row(align=ALIGN).label(text="Completed:")
        for bgt in completed:
            row = box.row(align=ALIGN)
            row.scale_y = 0.7
            row.label(text=f"{bgt.name} - finished", icon="GHOST_ENABLED")
            row.operator("simplebake.import_bgbake", icon='IMPORT', text="").pid = str(bgt.pid)
            row.operator("simplebake.discard_bgbake", icon="CANCEL", text="").pid = str(bgt.pid)

        box.row(align=ALIGN).label(text="Active:")
        for bgt in active:
            row = box.row(align=ALIGN)
            row.scale_y = 0.7
            row.label(text=f"{bgt.name} - baking in progress {BackgroundBakeTasks.get_bgbake_status(bgt)}%",
                      icon="GHOST_DISABLED")
            row.operator("simplebake.kill_active_bgbake", icon="CANCEL", text="").pid = str(bgt.pid)

        box.row(align=ALIGN).label(text="Queued:")
        for bgt in queued:
            row = box.row(align=ALIGN)
            row.scale_y = 0.7
            row.label(text=f"{bgt.name} - queued", icon="GHOST_DISABLED")
            row.operator("simplebake.delete_queued_bgbake", icon='CANCEL', text="").id = bgt.id

    # -----------------------------------------------------------------------
    def draw_sketchfab_upload(self, context, box):
        box.row(align=ALIGN).operator("simplebake.sketchfab_upload", icon='IMPORT', text="Sketchfab Upload")

    # -----------------------------------------------------------------------
    def draw(self, context):
        sbp = context.scene.SimpleBake_Props
        layout = self.layout

        if (not BakeInProgress.is_baking) or space == 'VIEW_3D':
            box = layout.box()
            self.draw_global_mode_buttons(context, box)

            box = layout.box()
            self.draw_presets(context, box)

            box = layout.box()
            self.draw_objects_list(context, box)

            box = layout.box()
            self.draw_materials_section(context, box)

            if sbp.global_mode == SBConstants.PBR:
                box = layout.box()
                self.draw_pbr_settings(context, box)

                box = layout.box()
                self.draw_aov_bakes(context, box)

            if sbp.global_mode == SBConstants.CYCLESBAKE:
                box = layout.box()
                self.draw_cyclesbake_settings(context, box)

            box = layout.box()
            self.draw_specials_settings(context, box)

            box = layout.box()
            self.draw_texture_settings(context, box)

            box = layout.box()
            self.draw_export_settings(context, box)

            box = layout.box()
            self.draw_uv_settings(context, box)

            box = layout.box()
            self.draw_other_settings(context, box)

            if sbp.global_mode == SBConstants.PBR:
                box = layout.box()
                self.draw_channel_packing(context, box)

            box = layout.box()
            self.draw_admin_settings(context, box)

            box = layout.box()
            self.draw_bake_buttons(context, box)

        else:
            box = layout.box()
            self.draw_fg_bake_status(context, box)

        box = layout.box()
        self.draw_background_bakes(context, box)

        from .preferences import get_sb_prefs
        prefs = get_sb_prefs(context)
        if getattr(prefs, "apikey", "") != "":
            box = layout.box()
            self.draw_sketchfab_upload(context, box)


def draw_simplebake_ui(layout, context):
    scene = context.scene

    # 顶栏子分页切换 (烘焙面板 / 设置)
    row = layout.row(align=True)
    row.prop(scene, "simplebake_active_subtab", expand=True)

    if getattr(scene, "simplebake_active_subtab", 'PANEL') == 'SETTINGS':
        from .preferences import draw_preferences_ui, get_sb_prefs
        prefs = get_sb_prefs(context)
        draw_preferences_ui(layout, context, prefs)
    else:
        panel = SIMPLEBAKE_PT_main_panel()
        panel.layout = layout
        panel.draw(context)


classes = ([])


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
