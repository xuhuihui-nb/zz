#LEGACY FIX - Non SB settings now being stored with their full name relative from context.scene. But previously
#stored with just their last name


import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

import os
import json
from pathlib import Path

from .utils import clean_file_name, SBConstants, show_message_box
from . import utils
from .messages import print_message
from .ui.objects_list import refresh_mat_bake_list

def fix_legacy(d):

    name_mapping = {
    "bake_type": "cycles.bake_type",
    "use_pass_direct": "render.bake.use_pass_direct",
    "use_pass_indirect": "render.bake.use_pass_indirect",
    "use_pass_diffuse": "render.bake.use_pass_diffuse",
    "use_pass_glossy": "render.bake.use_pass_glossy",
    "use_pass_transmission": "render.bake.use_pass_transmission",
    "use_pass_emit": "render.bake.use_pass_emit",
    "samples": "cycles.samples",
    "bake.normal_space": "render.bake.normal_space",
    "normal_r": "render.bake.normal_r",
    "normal_g": "render.bake.normal_g",
    "normal_b": "render.bake.normal_b",
    "use_pass_color": "render.bake.use_pass_color",
    "bake.margin": "render.bake.margin",
    "bake.margin_type": "render.bake.margin_type",
    "exr_codec": "render.image_settings.exr_codec",
    "cycles_denoise": "cycles.use_denoising",
    "cycles_denoiser": "cycles.denoiser",
    "cycles_denoising_input_passes": "cycles.denoising_input_passes",
    "cycles_denoising_prefilter": "cycles.denoising_prefilter"
    }

    new_dict = {}
    for old_key, value in d.items():
        # Use the new key if it exists in the name_mapping, otherwise keep the old key
        new_key = name_mapping.get(old_key, old_key)
        new_dict[new_key] = value
    return new_dict


def deep_setattr(obj, attr, value):
    """Recursively set attributes on an object, including sub-objects."""
    pre, _, post = attr.rpartition('.')
    return setattr(deep_getattr(obj, pre) if pre else obj, post, value)

def deep_getattr(obj, attr):
    """Recursively get attributes from an object, including sub-objects."""
    for part in attr.split('.'):
        obj = getattr(obj, part)
    return obj

basic_props = ([
    "global_mode",
    "ray_distance",
    "cage_and_ray_multiplier",
    "cage_extrusion",
    "auto_match_mode",
    "selected_s2a",
    "s2a_opmode",
    "merged_bake",
    "merged_bake_name",
    "cycles_s2a",
    "imgheight",
    "imgwidth",
    "outputheight",
    "outputwidth",
    "everything32bitfloat",
    #"use_alpha",
    "texture_bg_col",
    "rough_glossy_switch",
    "ccrough_glossy_switch",
    "multiply_diffuse_ao",
    "multiply_diffuse_ao_percent",
    "normal_format_switch",
    "tex_per_mat",
    "selected_col",
    "selected_metal",
    "selected_rough",
    "selected_normal",
    "selected_trans",
    "selected_transrough",
    "selected_emission",
    "selected_emission_strength",
    "selected_sss",
    "selected_sss_scale",
    "selected_ssscol",
    "selected_clearcoat",
    "selected_clearcoat_rough",
    "selected_specular",
    "selected_alpha",
    "selected_col_mats",
    "selected_col_vertex",
    "selected_ao",
    "selected_thickness",
    "selected_curvature",
    "selected_lightmap",
    "selected_displacement",
    "lightmap_apply_colman",
    "new_uv_option",
    "prefer_existing_sbmap",
    "new_uv_method",
    "restore_orig_uv_map",
    "uvpackmargin",
    "average_uv_size",
    "expand_mat_uvs",
    "auto_detect_udims",
    "unwrapmargin",
    "uvcorrectaspect",
    "channelpackfileformat",
    "del_cptex_components",
    "save_bakes_external",
    "export_folder_per_object",
    "export_mesh_individual_or_combined",
    "export_format",
    "jpeg_quality",
    "save_obj_external",
    "merge_export_obj",
    "mesh_export_name",
    "copy_and_apply",
    "apply_bakes_to_original",
    "hide_source_objects",
    "hide_cage_object",
    "preserve_materials",
    "everything_16bit",
    "export_file_format",
    "apply_col_man_to_col",
    "export_cycles_col_space",
    "rundenoise",
    "apply_mods_on_mesh_export",
    "objects_list_index",
    "bgbake",
    "memLimit",
    "batch_name",
    "first_texture_show",
    "bgbake_name",
    "apply_transformation",
    "create_glTF_node",
    "glTF_selection",
    "export_path",
    "move_new_uvs_to_top",
    "selected_bump",
    "cyclesbake_cs",
    #"fbx_preset_name",
    #"gltf_preset_name",
    "export_mesh_preset_name",
    "cyclesbake_copy_and_apply_mat_format",
    "clear_image",
    "cage_smooth_hard",
    "boosted_sample_count",
    "no_force_32bit_normals",
    "bw_to_rgb",
    "keep_internal_after_export",
    "ao_sample_count",
    "isolate_objects",
    "uv_advanced_packing_show",
    "uvp_shape_method",
    "uvp_scale",
    "uvp_rotate",
    "uvp_rotation_method",
    "uvp_margin_method",
    "uvp_lock_pinned",
    "uvp_lock_method",
    "uvp_merge_overlapping",
    "uvp_pack_to",
    "showtips",
    "presets_show",
    "bake_objects_show",
    "pbr_settings_show",
    "aov_settings_show",
    "cyclesbake_settings_show",
    "specials_show",
    "textures_show",
    "export_show",
    "admin_settings_show",
    "uv_show",
    "other_show",
    "channelpacking_show",
    "bg_status_show",
    "image_sequence_enabled",
    "image_sequence_start_frame",
    "image_sequence_end_frame",
    "findreplace_find",
    "findreplace_replace",
    "findreplace_type",
    "do_aa",
    "aa_threshold",
    "aa_contrast_limit",
    "aa_corner_radius",
    "join_objs_to_proxy",
    "available_uv_maps",
    "materials_show",
])

scene_props = ([
    "cycles.bake_type",
    "render.bake.use_pass_direct",
    "render.bake.use_pass_indirect",
    "render.bake.use_pass_diffuse",
    "render.bake.use_pass_glossy",
    "render.bake.use_pass_transmission",
    "render.bake.use_pass_emit",
    "render.bake.view_from",
    "cycles.samples",
    "render.bake.normal_space",
    "render.bake.normal_r",
    "render.bake.normal_g",
    "render.bake.normal_b",
    "render.bake.use_pass_color",
    "render.bake.margin",
    "render.bake.margin_type",
    "render.image_settings.exr_codec",
    "cycles.use_denoising",
    "cycles.denoiser",
    "cycles.denoising_input_passes",
    "cycles.denoising_prefilter"
])



class SimpleBake_OT_preset_save(Operator):
    """Save current SimpleBake settings to preset"""
    bl_idname = "simplebake.preset_save"
    bl_label = "Save"

    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        return sbp.preset_name != ""

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        if sbp.preset_name != clean_file_name(sbp.preset_name):
            message_items = ["ERROR: Preset name can only contain characters that",
                             "are valid for the external file system"]
            show_message_box(context, message_items, "ERROR", icon = "ERROR")
            return {'CANCELLED'}

        d = {}

        for p in basic_props:
            try:
                val = getattr(sbp, p)
            except UnicodeDecodeError as e:
                print(f"[SimpleBake] UnicodeDecodeError on prop '{p}': {e}")

            if isinstance(val, bpy.types.bpy_prop_array):
                d[p] = list(val)
            else:
                d[p] = val

        for p in scene_props:
            d[p] = deep_getattr(context.scene, p)

        #Grab the objects in the advanced list (if any)
        d["objects_list"] = [o.name for o in sbp.objects_list]
        d["mat_bake_list"] = [(e.obj_name, e.mat_name, e.enabled) for e in sbp.mat_bake_list]
        #Grab the target objects if there is one
        if sbp.targetobj != None:
            d["pbr_target_obj"] =  sbp.targetobj.name
        else:
            d["pbr_target_obj"] = None
        if sbp.targetobj_cycles != None:
            d["cycles_target_obj"] = sbp.targetobj_cycles.name
        else:
            d["cycles_target_obj"] = None
        #Cage object if there is one
        if context.scene.render.bake.cage_object != None:
            d["cage_object"] = context.scene.render.bake.cage_object.name
        else:
            d["cage_object"] = None

        #Channel packed images
        cp_images_dict = {}
        for cpt in sbp.cp_list:
            thiscpt_dict = {}
            thiscpt_dict["R"] = cpt.R
            thiscpt_dict["G"] = cpt.G
            thiscpt_dict["B"] = cpt.B
            thiscpt_dict["A"] = cpt.A

            thiscpt_dict["file_format"] = cpt.file_format
            thiscpt_dict["exr_codec"] = cpt.exr_codec
            thiscpt_dict["png_compression"] = cpt.png_compression

            cp_images_dict[cpt.name] = thiscpt_dict
        if len(cp_images_dict)>0:
            d["channel_packed_images"] = cp_images_dict


        #AOVs
        aovs = []
        for aov in sbp.aov_items:
            aovs.append([aov.name, aov.cs, aov.enabled])
        d["aovs"] = aovs

        #UV map list
        d["uvs"] = [(i.name, i.uv_name) for i in sbp.uv_items]


        #Find where we want to save
        p = Path(bpy.utils.script_path_user())
        p = p.parents[1]
        p = p / "data" / "SimpleBake"
        savename = clean_file_name(sbp.preset_name)

        if not os.path.isdir(str(p)):
            os.makedirs(str(p))

        print_message(context, f"Saving preset to {str(p)}")

        jsonString = json.dumps(d)
        jsonFile = open(str(p / savename), "w")
        jsonFile.write(jsonString)
        jsonFile.close()

        #Refreh the list
        bpy.ops.simplebake.preset_refresh()

        self.report({"INFO"}, "Preset saved")
        return {'FINISHED'}

class SimpleBake_OT_preset_load(Operator):
    """Load selected SimpleBake preset"""
    bl_idname = "simplebake.preset_load"
    bl_label = "Load"

    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        try:
            sbp.presets_list[sbp.presets_list_index].name
            return True
        except:
            return False


    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        s = context.scene
        utils.suppress_for_preset_load = True

        #Load it
        loadname = clean_file_name(sbp.presets_list[sbp.presets_list_index].name)

        p = Path(bpy.utils.script_path_user())
        p = p.parents[1]
        p = p /  "data" / "SimpleBake" / loadname

        print_message(context, f"Loading preset from {str(p)}")

        try:
            fileObject = open(str(p), "r")
        except:
            bpy.ops.simplebake.preset_refresh()
            self.report({"ERROR"}, f"Preset {loadname} no longer exists")
            return {'CANCELLED'}


        json_content = fileObject.read()
        d = json.loads(json_content)

        #Fix the legacy entries
        d = fix_legacy(d)


        for p in basic_props:
            try:
                cur = getattr(sbp, p)   # what's there now?
                val = d[p]

                if hasattr(cur, "to_list"):
                    setattr(sbp, p, tuple(val))   # tuple/list both work; tuple is safe
                else:
                    setattr(sbp, p, val)

                setattr(sbp, p, d[p])
            except Exception as e:
                print(f"Unable to load preset value for {p}: {e}")

        for p in scene_props:
            try:
                deep_setattr(context.scene, p, d[p])
            except Exception as e:
                print(f"Unable to load preset value for {p}")
                print(e)

        #Channel packing images
        sbp.cp_list.clear()


        if "channel_packed_images" in d:
            channel_packed_images = d["channel_packed_images"]

            if len(channel_packed_images) > 0:
                sbp.cp_list.clear()

            for imgname in channel_packed_images:

                thiscpt_dict = channel_packed_images[imgname]

                #Create the list item
                li = sbp.cp_list.add()
                li.name = imgname

                #Set the list item properies
                li.R = thiscpt_dict["R"]
                li.G = thiscpt_dict["G"]
                li.B = thiscpt_dict["B"]
                li.A = thiscpt_dict["A"]

                li.file_format = thiscpt_dict["file_format"]
                li.exr_codec = thiscpt_dict["exr_codec"]
                if "png_compression" in thiscpt_dict:
                    li.png_compression = thiscpt_dict["png_compression"]
                else:
                    li.png_compression = 15



        #Refresh the set values in the packed textures list (so it doesn't look like it hasn't been saved)
        #Go to first item (just in case the preset loads fewer than we already had
        if len(sbp.cp_list) > 0:
            sbp.cp_list_index = 0


        #And now the objects, if they are here

        #Clear list if that was asked for
        if sbp.preset_load_clear_obj:
            sbp.objects_list.clear()

            for obj_name in d["objects_list"]:
                if obj_name in context.scene.objects:
                    #Find where name attribute of each object in the advanced selection list matches the name
                    l = [o.name for o in sbp.objects_list if o.name == obj_name]
                    if len(l) == 0:
                        #Not already in the list
                        i = sbp.objects_list.add()
                        i.name = obj_name #Advanced object list has a name and pointers arritbute
                        i.obj_point = context.scene.objects[obj_name]

            if d["pbr_target_obj"] != None and d["pbr_target_obj"] in context.scene.objects:
                sbp.targetobj = context.scene.objects[d["pbr_target_obj"]]
            if d["cycles_target_obj"] != None and d["cycles_target_obj"] in context.scene.objects:
                sbp.targetobj_cycles = context.scene.objects[d["cycles_target_obj"]]
            #Cage object
            if d["cage_object"] != None and d["cage_object"] in context.scene.objects:
                context.scene.render.bake.cage_object = context.scene.objects[d["cage_object"]]

            #Mat bake list — refresh first to populate all materials, then apply saved enabled states
            refresh_mat_bake_list(context)
            if "mat_bake_list" in d:
                saved_states = {(obj_name, mat_name): enabled for obj_name, mat_name, enabled in d["mat_bake_list"]}
                for entry in sbp.mat_bake_list:
                    key = (entry.obj_name, entry.mat_name)
                    if key in saved_states:
                        entry.enabled = saved_states[key]


        #AOVs
        bpy.ops.simplebake.refresh_aov_list()
        if "aovs" in d:
            aovs = d["aovs"]
            for aov in aovs:
                name = aov[0]
                cs = aov[1]
                enabled = aov[2]

                if name in sbp.aov_items:
                    i = sbp.aov_items[name]
                    i.cs = cs
                    i.enabled = enabled

        utils.suppress_for_preset_load = False
        self.report({"INFO"}, f"Preset {loadname} loaded")

        #UVlist (Must come after the object list is populated)
        if "uvs" in d:
            bpy.ops.simplebake.sync_uv_list()
            for n, uvn in d["uvs"]:
                if (i:=sbp.uv_items.find(n)) != -1:
                    sbp.uv_items[i].uv_name = uvn


        return {'FINISHED'}

classes = ([
    SimpleBake_OT_preset_load,
    SimpleBake_OT_preset_save
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
