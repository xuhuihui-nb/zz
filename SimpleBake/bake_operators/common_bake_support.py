from ..utils import get_sb_prefs
import bpy

from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty

import os
from pathlib import Path
import tempfile
from datetime import datetime
from math import floor
import sys
import shutil

from ..utils import SBConstants, transfer_tags, show_message_box, object_list_to_names_list, find_closest_obj, get_bake_objects, blender_refresh, is_blend_saved, find_3d_viewport, disable_impossible, specials_selection_to_list, force_to_object_mode
from ..ui.objects_list import refresh_mat_bake_list
from ..material_management import SimpleBake_OT_Material_Backup as MatManager
from ..background_and_progress import BakeInProgress as Bip
from ..messages import print_message
import re
from .. import __package__ as base_package


class PrestartFailed(Exception):
    pass

def re_enable_addons(context):
    for addon in CommonBakePrepandFinish.disabled_addons:
        try:
            bpy.ops.preferences.addon_enable(module=addon)
            print_message(context, f"Renabled addon {addon}")
        except:
            print_message(context, f"Error trying to renable addon {addon}")
    CommonBakePrepandFinish.disabled_addons = []


def common_prestart(context, decals=False, automatch=False):

    sbp = context.scene.SimpleBake_Props
    prefs = get_sb_prefs(context)

    pbr_bake = True if sbp.global_mode == "PBR" else False

    def prestart_actions():

        #Get rid of any active previews
        bpy.ops.simplebake.restore_preview()

        #Take snapshot of the panel to restore at the end
        bpy.ops.simplebake.local_preset_save_override(name_override="TMP_Panel_Initial_State")

        #Record state of all mesh objects
        CommonBakePrepandFinish.orig_objects_visible = [[o.name, o.hide_viewport] for o in bpy.data.objects if o.type=="MESH"]
        CommonBakePrepandFinish.orig_objects_visible_render = [[o.name, o.hide_render] for o in bpy.data.objects if o.type == "MESH"]

        #Disable other addons?
        if prefs.disable_other_addons2 and sbp.bgbake!="bg":
            p = context.preferences;
            allowed_addons = ['io_anim_bvh', 'io_curve_svg', 'io_mesh_uv_layout', 'io_scene_fbx', 'io_scene_gltf2', 'cycles', 'pose_library', 'bl_pkg', 'SimpleBake'];
            CommonBakePrepandFinish.disabled_addons = []
            for addon in p.addons.keys():
                if addon not in allowed_addons:
                    try:
                        bpy.ops.preferences.addon_disable(module=addon)
                        CommonBakePrepandFinish.disabled_addons.append(addon)
                        print_message(context, f"Disabled {addon}")
                    except:
                        print_message(context, f"Error while disabling {addon}")

        Bip.was_error = False

        #Refresh objects list
        bpy.ops.simplebake.refresh_bake_object_list()

        disable_impossible(context)

        #Things are much easier if we fix this
        if (to:=sbp.targetobj)!=None and (i:=sbp.objects_list.find(to.name))!=-1:
            print_message(context,f"Removing target object {to.name} from bake list")
            sbp.objects_list.remove(i)
            refresh_mat_bake_list(context)

        #Save file?
        if prefs.saveonbake and is_blend_saved():
            try:
                bpy.ops.wm.save_mainfile()
            except:
                print_message(context, "ERROR: Was unable to save Blend file")

        #Switch to solid shading?
        if prefs.solidshadingonbake:
            for screen in bpy.data.screens:
                for space in find_3d_viewport(screen=screen):
                    space.shading.type = "SOLID"

        #Sidestep any geometary nodes (before starting checks so materials becomme "real")
        if pbr_bake or len(specials_selection_to_list(context))>0:
            bpy.ops.simplebake.sidestep_geo_nodes()
            #if decals and sbp.targetobj!=None:
                #bpy.ops.simplebake.sidestep_geo_nodes(decals_target_name = sbp.targetobj.name)

        #Starting checks
        if automatch:
            match_mode = "NAME" if sbp.auto_match_mode=="name" else "POSITION"
            hl_matches = {}
            orig_objects_list=[]
            result = match_high_low_objects(context, hl_matches, orig_objects_list, match_mode)
            if not result:
                raise PrestartFailed

            #Starting checks
            for lo in hl_matches.keys():
                if pbr_bake:
                    sbp.targetobj = context.scene.objects[lo]
                else:
                    sbp.targetobj_cycles = context.scene.objects[lo]
                if 'CANCELLED' in bpy.ops.simplebake.starting_checks():
                    raise PrestartFailed

                if pbr_bake:
                    sbp.targetobj = None
                else:
                    sbp.targetobj_cycles = None
        else:
            if 'CANCELLED' in bpy.ops.simplebake.starting_checks():
                raise PrestartFailed("Starting checks failed!")

        #Fresh start for materials
        bpy.ops.simplebake.material_backup(mode=MatManager.MODE_INITIALISE)

        #If newer than Blender 4.0, run this before the Macro!! But after existing material tags have been wiped and after starting checks
        if bpy.app.version >= (4,1,0) and pbr_bake:
            bpy.ops.simplebake.pbr_pre_bake()
            if decals:
                bpy.ops.simplebake.pbr_pre_bake(override_target_object_name = sbp.targetobj.name)

        #Process UVs
        #Do this near to last, as it's not really possible to reverse it if anything else in the prestart fails
        #Snapshot UV state BEFORE process_uvs() changes it, so restore_orig_uv_map has the correct originals
        if (sbp.selected_s2a or sbp.cycles_s2a) and automatch:
            _pre_uv_objs = list(set(list(hl_matches.keys()) + list(hl_matches.values())))
        else:
            _pre_uv_objs = [o.obj_point.name for o in sbp.objects_list]
        if sbp.targetobj is not None and sbp.targetobj.name not in _pre_uv_objs:
            _pre_uv_objs.append(sbp.targetobj.name)
        if sbp.targetobj_cycles is not None and sbp.targetobj_cycles.name not in _pre_uv_objs:
            _pre_uv_objs.append(sbp.targetobj_cycles.name)
        CommonBakePrepandFinish.orig_object_uvs = {}
        CommonBakePrepandFinish.orig_object_uvs_render = {}
        CommonBakePrepandFinish.new_uv_option = sbp.new_uv_option
        for _o_name in _pre_uv_objs:
            _obj = context.scene.objects.get(_o_name)
            if not _obj: continue
            if _obj.data.uv_layers.active is not None:
                CommonBakePrepandFinish.orig_object_uvs[_o_name] = _obj.data.uv_layers.active.name
            for _uv in _obj.data.uv_layers:
                if _uv.active_render:
                    CommonBakePrepandFinish.orig_object_uvs_render[_o_name] = _uv.name
        bpy.ops.simplebake.process_uvs()

        #Merged bake proxy must come after UVs
        #Grab a copy of the original bake objects list
        sbp['SB_orig_bake_objects'] = [o.name for o in sbp.objects_list]
        if sbp.join_objs_to_proxy:
            bpy.ops.simplebake.merged_bake_proxy_create()


    try:
        prestart_actions()
    except PrestartFailed as e:
        print_message(context, "BAKE ABORTED - Check pop-up for errors")
        Bip.is_baking = False
        Bip.was_error = True

        #Undo actions from sidestep and also pre-bake
        bpy.ops.simplebake.material_backup(mode="working_restore")
        bpy.ops.simplebake.material_backup(mode="master_restore")
        bpy.ops.simplebake.reverse_geo_nodes_sidestep()

        #Re-enable addons we might have disabled
        re_enable_addons(context)

        #Restore panel state
        bpy.ops.simplebake.local_preset_load_override(name_override="TMP_Panel_Initial_State")

        return False

    print_message(context,"Common Prestart Actions Complete")
    return True

def clean_up_after_bg_spawn(context):
    print_message(context, "Cleaning up after BG spawn")
    sbp = context.scene.SimpleBake_Props

    #Undo actions from sidestep and also pre-bake
    bpy.ops.simplebake.material_backup(mode="master_restore")
    bpy.ops.simplebake.reverse_geo_nodes_sidestep()

    # If a merged proxy was created for this bake, remove it from the foreground scene.
    # common_bake_finishing (which normally handles this) only runs in the background
    # process, so we must clean up here.
    for name in [o.name for o in bpy.data.objects if "SB_merged_proxy" in o]:
        if obj := bpy.data.objects.get(name):
            bpy.data.objects.remove(obj)

    # Restore sbp.objects_list to the original bake objects (proxy creation replaced it).
    orig_names = list(sbp.get('SB_orig_bake_objects', []))
    if orig_names:
        sbp.objects_list.clear()
        for n in orig_names:
            bpy.ops.simplebake.add_bake_object_by_name(override_target_obj_name=n)
        bpy.ops.simplebake.refresh_bake_object_list()

    # Restore render visibility on all objects.
    # Proxy creation sets hide_render=True on the originals; common_bake_finishing
    # restores this, but only runs in the background process.
    for name, hide_render_state in CommonBakePrepandFinish.orig_objects_visible_render:
        if ob := context.scene.objects.get(name):
            ob.hide_render = hide_render_state

    # Restore active UV and active_render on the original objects.
    # common_bake_finishing handles this for foreground bakes; we replicate it here.
    for o_name, orig_active in CommonBakePrepandFinish.orig_object_uvs.items():
        obj = context.scene.objects.get(o_name)
        if not obj: continue
        idx = next((i for i, l in enumerate(obj.data.uv_layers) if l.name == orig_active), None)
        if idx is not None:
            obj.data.uv_layers.active_index = idx
    for o_name, orig_render in CommonBakePrepandFinish.orig_object_uvs_render.items():
        obj = context.scene.objects.get(o_name)
        if not obj: continue
        for layer in obj.data.uv_layers:
            layer.active_render = (layer.name == orig_render)

    return True



def match_high_low_objects(context, hl_matches, orig_objects_list, match_mode):
    print_message(context, "Matching high and low poly objects commencing")
    sbp = context.scene.SimpleBake_Props

    #Refresh the bake objects list (couldn't hurt)
    bpy.ops.simplebake.refresh_bake_object_list()

    #If name mode, remove invalid before we consider anything else
    if match_mode == "NAME":
        #Remove invalid
        to_remove = []
        for o in sbp.objects_list:
            if "_high" not in o.name.lower():
                to_remove.append(o.name)
        for r in to_remove:
            i = sbp.objects_list.find(r)
            sbp.objects_list.remove(i)

    hl_matches.clear()
    objs = [i.obj_point for i in sbp.objects_list]
    orig_objects_list.clear()
    orig_objects_list.extend(objs)

    if match_mode == "NAME":

        hs = [o.name for o in objs if o.name.lower().endswith("_high")]
        hs_dict = {}#Lowcase to real
        for i in hs:
            hs_dict[i.lower()] = i

        #ls = [o.name for o in context.scene.objects] #Every object is a potential low at this point
        ls = [o.name for o in context.scene.objects if o.name.lower().endswith("_low")]
        ls_dict = {}#Lowcase to real
        for i in ls:
            ls_dict[i.lower()] = i

        matched_ls = []

        for i in hs_dict.keys(): #LOWER names of high poly objects
            if i.replace("_high", "_low") in ls_dict.keys():
                hl_matches[ls_dict[i.replace("_high", "_low")]] = hs_dict[i]

        # Create a normalized version of lows to map to highs
        #normalized_to_original = {re.sub(r'_low$', '', s, flags=re.IGNORECASE): s for s in ls}

        #for high in hs:
            #base_string = re.sub(r'_high$', '', high, flags=re.IGNORECASE)
            #if base_string in normalized_to_original:
                # low_string = normalized_to_original[base_string]
                # hl_matches[low_string] = high
                # matched_ls.append(low_string)



        ls = matched_ls

    if match_mode == "POSITION":
        hs = [o.name for o in sbp.objects_list]
        ls = []
        #Detect low by position for every high object
        for h in hs:
            l = find_closest_obj(context, h)
            if l != None:
                ls.append(l.name)
                hl_matches[l.name] = h

    #If there were actually no matches, abort here:
    if len(hl_matches) <1:
        print_message(context, "BAKE ABORTED (AUTO) - Check pop-up for errors")
        messages = ([
            "ERROR: You are trying to bake auto match",
            "high and low poly, but there are no matches!"
            ])
        show_message_box(context, messages, "Errors occured", icon = 'ERROR')
        Bip.is_baking = False
        return False


    #Now we have our list, purge all low objects from the bake objects list
    #Not sure it's useful, but you could have an object being both a high and a low. Only remove if not also a high
    ls_unique = [lo for lo in ls if lo not in hs]
    # for lo in ls_unique:
    #     i = sbp.objects_list.find(lo)
    #     if i>-1: sbp.objects_list.remove(i)

    for lo in ls:
        i = sbp.objects_list.find(lo)
        if i>-1: sbp.objects_list.remove(i)


    #Dry run for starting checks
    for lo in ls:
        if sbp.global_mode == SBConstants.PBR: sbp.targetobj = context.scene.objects[lo]
        else: sbp.targetobj_cycles = context.scene.objects[lo]
        if 'CANCELLED' in bpy.ops.simplebake.starting_checks(): #Should work out it's own mode from panel selections
            print_message(context, "BAKE ABORTED (AUTO) - Check pop-up for errors")
            Bip.is_baking = False
            return False
    return True



class SimpleBake_OT_Set_Sample_Count(Operator):
    bl_idname = "simplebake.set_sample_count"
    bl_label = "Set the sample count"
    
    sample_count: IntProperty()
    
    def execute(self, context):
        context.scene.cycles.samples = self.sample_count
        print_message(context, f"Sample count now {self.sample_count}")
        return {'FINISHED'}

class SimpleBake_OT_Compositor_Denoise(Operator):
    """Run the target image through compositor denoise"""
    bl_idname = "simplebake.compositor_denoise"
    bl_label = "Denoise"
    
    bake_operation_id: StringProperty()
    #bake_type: StringProperty()
    
    def execute(self, context):
        
        print_message(context, "Running compositor denoiser")
        
        imgs = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
                 and i["SB_bake_operation_id"] == self.bake_operation_id
                 and i["SB_this_bake"] not in SBConstants.ALL_PBR_MODES #Never denoise PBR
                 and i["SB_this_bake"] not in SBConstants.COMP_NODENOISE_SPECIALS #Only certian specials get denoise
                 and i["SB_denoised"] == False
                 ])

        if len(imgs)== 0:
            print_message(context, "No images for compositor denoiser")
            return {'FINISHED'}

        print_message(context, f"Compositor denoise for {[i.name for i in imgs]}")

        #[bpy.data.scenes.remove(s) for s in bpy.data.scenes if s.name == "compositor_denoise"]
        s = bpy.data.scenes.get("compositor_denoise")
        if s!=None:
            bpy.data.scenes.remove(s)

        path = os.path.dirname(__file__) + "/../resources/denoise.blend/Scene/"
        bpy.ops.wm.append(filename="compositor_denoise", directory=path)

        s = bpy.data.scenes.get("compositor_denoise")
        if s==None:
            return {'CANCELLED'}

        
        #Should all be same size
        s.render.resolution_x = imgs[0].size[0]
        s.render.resolution_y = imgs[0].size[1]

        if bpy.app.version >= (5, 0, 0):
            nodes = s.compositing_node_group.nodes
        else:
            nodes = s.node_tree.nodes
        
        i_node = [n for n in nodes if n.label == "image"]
        assert(len(i_node) == 1)
        i_node= i_node[0]
        
        temp_dir = Path(tempfile.TemporaryDirectory().name)

        
        for img in imgs:

            #Get some settings
            #s.render.image_settings.color_management = "OVERRIDE"
            s.render.image_settings.file_format = img.file_format
            s.render.image_settings.color_depth = img["SB_bit_depth"]
            s.render.image_settings.color_mode = img["SB_channels"]
            s.render.image_settings.exr_codec = img["SB_exr_codec"]
            #s.view_settings.view_transform = img["SB_view_transform"]
            s.view_settings.view_transform = "Standard"

            name = img.name
            external_path = img.filepath

            #Save the image to tmp dir
            #img.save_render(str(temp_dir / f"{name}.exr"), scene=s)

            tiles_nums = [t.number for t in img.tiles]
            for tile_num in tiles_nums:
                #Load the tile in as an individual image
                i = bpy.data.images.load(external_path.replace("<UDIM>", str(tile_num)))
                #i.colorspace_settings.name = img.colorspace_settings.name
                i_node.image =i

                #Render and get result
                bpy.ops.render.render(use_viewport=False, scene=s.name)
                render_result_image = bpy.data.images["Render Result"]

                #File should already exist. Remove it or will silently fail.
                if os.path.exists(bpy.path.abspath(external_path)):
                    os.remove(bpy.path.abspath(external_path))

                #Save this over the file path of the tile image
                #Only seems to work for abspath?
                external_path = bpy.path.abspath(external_path)
                render_result_image.save_render(external_path.replace("<UDIM>", str(tile_num)), scene=s)

                #Remove the tile image we loaded individually
                bpy.data.images.remove(i)

            #All tiles done for this image, reload the UDIM image
            img.reload() #We've updated 1 or more tiles and Blender still has them in the buffer'
            #img.save()
            img["SB_denoised"] = True

            #transfer_tags(img, new_img)

        #All done
        [bpy.data.scenes.remove(s) for s in bpy.data.scenes if s.name == "compositor_denoise"]

        return {'FINISHED'}


class SimpleBake_OT_Compositor_AA(Operator):
    """Run the target image through compositor anti-aliasing"""
    bl_idname = "simplebake.compositor_aa"
    bl_label = "AA"

    bake_operation_id: StringProperty()

    def execute(self, context):

        sbp = context.scene.SimpleBake_Props
        print_message(context, "Running compositor AA")

        imgs = ([i for i in bpy.data.images if "SB_bake_operation_id" in i
                 and "SB_channel_pack_image" not in i
                 and i["SB_bake_operation_id"] == self.bake_operation_id
                 and i["SB_this_bake"] not in [SBConstants.PBR_NORMAL, "NORMAL"] #Never try to AA a normal map
                 and i["SB_aa"] == False
                 ])

        if len(imgs)== 0:
            print_message(context, "No images for compositor AA")
            return {'FINISHED'}

        print_message(context, f"Compositor AA for {[i.name for i in imgs]}")

        s = bpy.data.scenes.get("compositor_aa")
        if s!=None:
            bpy.data.scenes.remove(s)

        path = os.path.dirname(__file__) + "/../resources/aa.blend/Scene/"
        bpy.ops.wm.append(filename="compositor_aa", directory=path)

        s = bpy.data.scenes.get("compositor_aa")
        if s==None:
            return {'CANCELLED'}

        #Should all be same size
        s.render.resolution_x = imgs[0].size[0]
        s.render.resolution_y = imgs[0].size[1]

        if bpy.app.version >= (5, 0, 0):
            nodes = s.compositing_node_group.nodes
        else:
            nodes = s.node_tree.nodes

        i_node = [n for n in nodes if n.label == "image"]
        assert(len(i_node) == 1)
        i_node= i_node[0]

        aa_node = [n for n in nodes if n.bl_idname == "CompositorNodeAntiAliasing"]
        assert(len(aa_node) == 1)
        aa_node= aa_node[0]

        #Set the aa props
        if bpy.app.version >= (5, 0, 0):
            aa_node.inputs[1].default_value = sbp.aa_threshold
            aa_node.inputs[2].default_value = sbp.aa_contrast_limit
            aa_node.inputs[3].default_value = sbp.aa_corner_radius
        else:
            aa_node.threshold = sbp.aa_threshold
            aa_node.contrast_limit = sbp.aa_contrast_limit
            aa_node.corner_rounding = sbp.aa_corner_radius

        temp_dir = Path(tempfile.TemporaryDirectory().name)


        for img in imgs:

            #Get some settings
            if "SB_bit_depth" not in img or "SB_channels" not in img or "SB_exr_codec" not in img:
                print_message(context, f"WARNING: {img.name} is missing external save metadata, skipping AA")
                continue
            s.render.image_settings.file_format = img.file_format
            s.render.image_settings.color_depth = img["SB_bit_depth"]
            s.render.image_settings.color_mode = img["SB_channels"]
            s.render.image_settings.exr_codec = img["SB_exr_codec"]

            s.view_settings.view_transform = "Standard"

            name = img.name
            external_path = img.filepath


            tiles_nums = [t.number for t in img.tiles]
            for tile_num in tiles_nums:
                #Load the tile in as an individual image
                i = bpy.data.images.load(external_path.replace("<UDIM>", str(tile_num)))
                #i.colorspace_settings.name = img.colorspace_settings.name
                i_node.image =i

                #Render and get result
                bpy.ops.render.render(use_viewport=False, scene=s.name)
                render_result_image = bpy.data.images["Render Result"]

                #File should already exist. Remove it or will silently fail.
                if os.path.exists(bpy.path.abspath(external_path)):
                    os.remove(bpy.path.abspath(external_path))

                #Save this over the file path of the tile image
                #Only seems to work for abspath?
                external_path = bpy.path.abspath(external_path)
                render_result_image.save_render(external_path.replace("<UDIM>", str(tile_num)), scene=s)

                #Remove the tile image we loaded individually
                bpy.data.images.remove(i)

            #All tiles done for this image, reload the UDIM image
            img.reload() #We've updated 1 or more tiles and Blender still has them in the buffer'
            img["SB_aa"] = True

            #transfer_tags(img, new_img)

        #All done
        [bpy.data.scenes.remove(s) for s in bpy.data.scenes if s.name == "compositor_aa"]

        return {'FINISHED'}

class SimpleBake_OT_Select_Only_This(Operator):
    """Select only the specified object"""
    bl_idname = "simplebake.select_only_this"
    bl_label = "Select"
    
    hidden = []
    
    target_object_name: StringProperty()
    high_object_name: StringProperty()
    cage_object_name: StringProperty()
    isolate: BoolProperty(default=False)
    isolate_s2a: BoolProperty(default=False)
    auto_match: BoolProperty(default=False)

    def execute(self, context):

        obj = context.scene.objects[self.target_object_name]

        if self.auto_match:
            #Hide everything (only objects currently visible, to avoid incorrectly restoring pre-hidden objects)
            for o in context.scene.objects:
                if o.type=="MESH" and o.hide_render == False:
                    o.hide_render = True
                    self.__class__.hidden.append(o.name)

            #Unhide target, high, and cage
            context.scene.objects[self.target_object_name].hide_render = False
            context.scene.objects[self.high_object_name].hide_render = False
            if self.cage_object_name:
                cage_obj = context.scene.objects.get(self.cage_object_name)
                if cage_obj:
                    cage_obj.hide_render = False

            #Return here - we don't actually want to mess with the selection
            return {'FINISHED'}


        if self.isolate_s2a:
            bake_objs = object_list_to_names_list(context)
            bake_objs.append(self.target_object_name)

            #Cage object too if there is one
            if context.scene.render.bake.cage_object != None:
                bake_objs.append(context.scene.render.bake.cage_object.name)

            #Hide everything
            for o in context.scene.objects:
                #if o.name not in bake_objs and o.type=="MESH":
                if o.hide_render == False:
                    o.hide_render = True
                    self.__class__.hidden.append(o.name)

            #Unhide object in bake objects list
            for o_name in bake_objs:
                context.scene.objects[o_name].hide_render = False

            #Return here - we don't actually want to mess with the selection
            return {'FINISHED'}

        if self.isolate:
            #Unhide the object we are baking. It may not have been unhidden yet
            obj.hide_render = False

            #Hide all other objects
            for o in context.scene.objects:
                if o.name != self.target_object_name and o.type=="MESH":
                    if o.hide_render == False:
                        o.hide_render = True
                        self.__class__.hidden.append(o.name)


        #bpy.ops.object.select_all(action="DESELECT")
        [o.select_set(state=False) for o in context.scene.objects]
        obj.select_set(state=True)
        context.view_layer.objects.active = obj
        
        return {'FINISHED'}


class SimpleBake_OT_Select_Selected_To_Active(Operator):
    """Select the bake objects as selected, and target object as active"""
    bl_idname = "simplebake.select_selected_to_active"
    bl_label = "Select"
    
    mode: StringProperty()
    specific_high: StringProperty()
    specific_low: StringProperty()
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        objs = [i.obj_point for i in sbp.objects_list]

        bpy.ops.object.select_all(action="DESELECT")

        if self.mode == SBConstants.PBRS2A:
            target_obj = sbp.targetobj

        if self.mode == SBConstants.CYCLESBAKE_S2A:
            target_obj = sbp.targetobj_cycles

        if self.mode == SBConstants.PBRS2A_AUTOMATCH:
            target_obj = context.scene.objects[self.specific_low]
            #Overide objects list for this purpose
            objs = [context.scene.objects[self.specific_high]]

        [obj.select_set(state=True) for obj in objs]
        target_obj.select_set(state=True)
        context.view_layer.objects.active = target_obj
        
        return {'FINISHED'}

class CommonBakePrepandFinish:
    #Non-Blender class. No register
    orig_object_selection = []
    orig_active_object = None

    #Can't be here as it isn't carried into the background and it is needed.
    #orig_bake_objects_list = []

    orig_objects_visible = []
    orig_objects_visible_render = []
    
    orig_object_uvs = {}
    orig_object_uvs_render = {}
    new_uv_option = False

    orig_render_engine = None
    #packed_images = []
    start_time = None

    high_low_matching_list = {}

    #Disabled addons
    disabled_addons = []

    #Disabled handlers
    disabled_handlers = []
    
    

class SimpleBake_OT_Pack_Baked_Images(Operator):
    """Preperation shared by all types of bake"""
    bl_idname = "simplebake.pack_baked_images"
    bl_description = "Pack all baked images into blend file"
    bl_label = "Pack"
    
    bake_operation_id: StringProperty()
    bake_mode: StringProperty()
    
    def execute(self, context):

        #BLOCK THIS FOR NOW
        return {'FINISHED'}


        #Get all primary images for this operation
        imgs = ([i for i in bpy.data.images if "SB_bake_operation_id" in i 
            and i["SB_bake_operation_id"] == self.bake_operation_id
            #and i.name not in CommonBakePrepandFinish.packed_images and
            and "SB_this_bake" in i and i["SB_this_bake"] == self.bake_mode
            ])

        for img in imgs:
            #if img.is_dirty == True:
            if img.packed_file == None:
            #if True:
                print_message(context, f"Packing image {img.name} to blend file")
                img.pack()
                img.use_fake_user = True
                #CommonBakePrepandFinish.packed_images.append(img.name)
        
        return {'FINISHED'}
    
class SimpleBake_OT_Scale_Images_If_Needed(Operator):
    """Preperation shared by all types of bake"""
    bl_idname = "simplebake.scale_images_if_needed"
    bl_description = "Scale images if needed"
    bl_label = "Scale"
    
    bake_operation_id: StringProperty()
    this_bake: StringProperty()
    
    def execute(self, context):
        
        #Scale images if needed
        print_message(context, "Scaling images if needed")
        imgs = ([i for i in bpy.data.images
                 if "SB_bake_operation_id" in i and 
                 i["SB_bake_operation_id"] == self.bake_operation_id and
                 "SB_this_bake" in i and
                 "SB_scaled" in i and not i["SB_scaled"]
                 ])
        sbp = context.scene.SimpleBake_Props
        for img in imgs:
            width = img.size[0]
            height = img.size[1]
            #Just gonna assume if one tile has been resized they all have
            if width != sbp.outputwidth or height != sbp.outputheight:
                print_message(context, f"Scaling {img.name} to {sbp.outputwidth} by {sbp.outputheight}")

                i=0
                ts=len(img.tiles)
                while i < ts:
                    img.tiles.active_index = i
                    img.scale(sbp.outputwidth, sbp.outputheight, tile_index=i)
                    i+=1
            #Either way, we considered it
            img["SB_scaled"] = True
        
        
        return {'FINISHED'} 

def disable_auto_smooth(context):


    obj_names = get_bake_objects(context)
    modded_objs = []
    for o_name in obj_names:
        if not (o:=context.scene.objects.get(o_name)):
            continue
        if o.data.has_custom_normals and o.data.use_auto_smooth:
            o.data.use_auto_smooth = False
            print_message(context, f"Disabling auto-smooth setting for object {o.name} (custom split normals)")
            modded_objs.append(o.name)
    yield True

    for o_name in modded_objs:
        if (obj:=context.scene.objects.get(o_name)):
            print_message(context, f"Renabling auto-smooth setting for object {o_name}")
            obj.data.use_auto_smooth = True

    yield True
das_gen = None

class SimpleBake_OT_Common_Bake_Prep(Operator):
    """Preperation shared by all types of bake"""
    bl_idname = "simplebake.common_bake_prep"
    bl_description = "Preperation shared by all types of bake"
    bl_label = "BakePrep"
    
    def execute(self, context):
        
        print_message(context, "================================")
        print_message(context, "--------SIMPLEBAKE START--------")
        print_message(context, "================================")
        
        if "SB_Crash_Log" in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts["SB_Crash_Log"])

        CommonBakePrepandFinish.start_time = datetime.now()
        
        sbp = context.scene.SimpleBake_Props

        #Suspend despgraph access for all other addons, as access during bake process will cause Blender crash
        CommonBakePrepandFinish.disabled_handlers = list(bpy.app.handlers.depsgraph_update_post)
        bpy.app.handlers.depsgraph_update_post.clear()
        handler_names = [h.__name__ for h in CommonBakePrepandFinish.disabled_handlers]
        print_message(context, f"Just disabled handlers: {handler_names}")

        #Disable autosmooth for all objects that are relevant to us and have custom normals
        prefs = get_sb_prefs(context)
        if prefs.disable_auto_smooth_for_split_normals and bpy.app.version < (4,1,0):
            global das_gen
            das_gen=disable_auto_smooth(context)
            next(das_gen)

        #Auto matching high low needs special treatment
        if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            from .auto_match_operators import SimpleBake_OT_AutoMatch_Operation as amo
            hl_matches = amo.hl_matches
            bake_objects_names = []
            bake_objects_names.extend(list(hl_matches.keys()))
            bake_objects_names.extend(list(hl_matches.values()))
            bake_objects_names = list(set(bake_objects_names)) #Just to be sure
        else:
            bake_objects_names = [o.obj_point.name for o in sbp.objects_list]

        
        print_message(context, "Common bake prep starting")
        
        
        #Tracking number reset
        sbp.current_bake_image_number = 0
        sbp.percent_complete = 0
        
        #Render engine
        CommonBakePrepandFinish.orig_render_engine = context.scene.render.engine
        context.scene.render.engine = 'CYCLES'
        
        #Object selection
        CommonBakePrepandFinish.orig_object_selection = context.selected_objects
        CommonBakePrepandFinish.orig_active_object = context.active_object
        
        #Create a new collection, and add selected objects and target objects to it
        c = bpy.data.collections.get("SimpleBake_Working")
        if c!=None:
            bpy.data.collections.remove(c)

        c = bpy.data.collections.new("SimpleBake_Working")
        context.scene.collection.children.link(c)
        for o_name in bake_objects_names:
            obj = context.scene.objects[o_name]
            if o_name not in c.objects:
                c.objects.link(obj)
            if sbp.targetobj != None and sbp.targetobj.name not in c.objects:
                c.objects.link(sbp.targetobj)
            if sbp.targetobj_cycles != None and sbp.targetobj_cycles.name not in c.objects:
                c.objects.link(sbp.targetobj_cycles)
    
        #Every object must have at least camera ray visibility
        for o_name in bake_objects_names:
            obj = context.scene.objects[o_name]
            obj.visible_camera = True
        if sbp.targetobj != None:
            sbp.targetobj.visible_camera = True
        if sbp.targetobj_cycles != None:
            sbp.targetobj_cycles.visible_camera = True
        
        #In case of crash
        for m in bpy.data.materials:
            if "SB_working_dup" in m: del m["SB_working_dup"]

        return {'FINISHED'}
    
class SimpleBake_OT_Common_Bake_Finishing(Operator):
    """Finishing actions shared by all types of bake"""
    bl_idname = "simplebake.common_bake_finishing"
    bl_description = "Finishing shared by all types of bake"
    bl_label = "BakeFinish"
    
    #baked_number: IntProperty()
    bake_operation_id: StringProperty()
    suppress_report: BoolProperty(default=False)

    #Determined from panel setting
    decal_first_run: BoolProperty(default=False)
    #Determined from overide from this function, as panel setting not reliable when baking target object (update function turns it off)
    decal_second_run: BoolProperty(default=False)
    #Class variable
    decal_orig_objects = []
    t_object_name = ""
    baked_images_running_total = 0
    
    def execute(self, context):


        sbp = context.scene.SimpleBake_Props

        #Hook to anti-aliasing operator. Relevant for all bakes if user has requested it
        if sbp.do_aa:
            bpy.ops.simplebake.compositor_aa(bake_operation_id=self.bake_operation_id)


        #Renable autosmooth
        prefs = get_sb_prefs(context)
        if prefs.disable_auto_smooth_for_split_normals and bpy.app.version < (4,1,0):
            global das_gen
            next(das_gen)

        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False
        
        bake_objects_names = [o.obj_point.name for o in sbp.objects_list]
        
        #print_message(context, "Common bake finishing")
        

        #Working collection
        to_del = []
        for c in bpy.data.collections:
            if "SimpleBake_Working" in c.name: to_del.append(c.name)
        for name in to_del:
            c = bpy.data.collections.get(name)
            if c:
                bpy.data.collections.remove(c)

        #Render engine
        context.scene.render.engine = CommonBakePrepandFinish.orig_render_engine

        #Force to object mode
        if context.active_object == None:
            context.view_layer.objects.active = context.view_layer.objects[0] #Pick arbitary
        try: bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
        except Exception as e: pass # Weird crash when SimpleBake is displayed in the n-panel

        #Object selection
        bpy.ops.object.select_all(action="DESELECT")
        for obj in CommonBakePrepandFinish.orig_object_selection:
            try: obj.select_set(True)
            except Exception as e: print(str(e)) #E.g. if user had a copy and apply object selected, and now it's gone
        try: context.view_layer.objects.active = CommonBakePrepandFinish.orig_active_object
        except: pass

        # #If we applied bakes to the original object, let's assume we want that UV map to end up active for render
        # #May be overriden by the next check for the restore option. The user is warned about this on the panel
        if sbp.new_uv_option and sbp.apply_bakes_to_original:
            objs = [o.obj_point for o in sbp.objects_list]
            if sbp.targetobj != None: objs = [sbp.targetobj]
            if sbp.targetobj_cycles != None: objs = [sbp.targetobj_cycles]

            for obj in objs:
                for uvm in obj.data.uv_layers:
                    if uvm.name == "SimpleBake":
                        uvm.active_render = True


        #If we didn't export the bakes, pack them into the Blend file for safe keeping
        if not sbp.save_bakes_external:
            #Don't forget decal images. This is only called by the "regular" bake at the end'
            decal_op_id = self.bake_operation_id.replace("DECALSBASE_", "")
            bis = [i.name for i in bpy.data.images if "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id]
            decal_bis = [i.name for i in bpy.data.images if "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == decal_op_id]
            bis = list(set(bis + decal_bis))
            for iname in bis:
                if i:=bpy.data.images.get(iname):
                    i.pack()

        #Remove SimpleBake_Bakes if it's empty
        c = bpy.data.collections.get("SimpleBake_Bakes")
        if c and len(c.objects) == 0:
            bpy.data.collections.remove(c)

        bpy.ops.simplebake.material_backup(mode=MatManager.MODE_MASTER_RESTORE)

        m = bpy.data.materials.get("SimpleBake_Placeholder")
        if m:
            bpy.data.materials.remove(m, do_unlink=True)

        #Report
        #Get all images with this bake ID
        bis = [i for i in bpy.data.images if "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id]
        for bi in bis:
            if "SB_counted" not in bi or ("SB_counted" in bi and not bi["SB_counted"]):
                __class__.baked_images_running_total+=1
                bi["SB_counted"] = True
        if (not self.in_background and not Bip.was_error and not self.decal_first_run
                and not self.suppress_report and not sbp.suppress_report
                and Bip.Sequence.should_run_teardown()):
            #message=f"Foreground bake is complete|{str(self.baked_number)} images baked"
            message=f"Foreground bake is complete|{__class__.baked_images_running_total} images baked"
            if Bip.Sequence.active and Bip.Sequence.is_last_frame:
                message = message + f" for {Bip.Sequence.total_frames} frames"
                Bip.Sequence.reset()

            icon="INFO"
            centre = True
            bpy.ops.simplebake.show_message_box('INVOKE_DEFAULT', message=message, icon=icon, centre=centre)
            __class__.baked_images_running_total = 0
            for bi in bis:
                bi["SB_counted"] = False
        

        #Always reset this -
        Bip.was_error = False


        if self.in_background:
            bpy.ops.wm.save_mainfile()
            print_message(context, "Saving file")
        
        #If this was an S2A bake, also hide the bake objects (only target will be hidden by Copy and Apply)
        #NOTE: Target may also be in bake objects list
        #NOTE: Target object won't be hidden for first decals run, but that's what we want
        if Bip.Sequence.should_run_teardown():
            if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.hide_source_objects: #Some kind of S2A bake
                hide_obj_names = bake_objects_names
                if sbp.targetobj != None:
                    if sbp.targetobj.name in hide_obj_names:
                        hide_obj_names = [h for h in hide_obj_names if h != sbp.targetobj.name]

                if sbp.targetobj_cycles != None:
                    if sbp.targetobj_cycles.name in hide_obj_names:
                        hide_obj_names = [h for h in hide_obj_names if h != sbp.targetobj_cycles.name]

                for obj_name in hide_obj_names:
                    obj = context.scene.objects[obj_name]
                    obj.hide_set(True)

        ##If this was an S2A bake, also hide the cage object if user requested this
        if Bip.Sequence.should_run_teardown():
            if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.copy_and_apply and sbp.hide_cage_object:
                obj = context.scene.render.bake.cage_object
                if obj != None: #May not have a cage object actually set
                    obj.hide_set(True)

                
        #Restore render state visibility
        for name, hide_render_state in CommonBakePrepandFinish.orig_objects_visible_render:
            if ob:= bpy.data.objects.get(name):  # Make sure the object still exists
                ob.hide_render = hide_render_state

        #Do we want to keep the internal images after export?
        #Will not affect background bakes anyway, as we are being called after the file save
        del_list = []
        if sbp.save_bakes_external and not sbp.keep_internal_after_export:# and not self.in_background:
            print_message(context, "Deleting internal baked images")
            del_list = [i.name for i in bpy.data.images if "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id]

            for name in del_list:
                i = bpy.data.images.get(name)
                if i!=None:
                    print_message(context, f"Deleting {i.name}")
                    bpy.data.images.remove(i)
        
        #Unhide for rendering any objects we hid for the isolation function and clear
        for o_name in SimpleBake_OT_Select_Only_This.hidden:
            context.scene.objects[o_name].hide_render = False
        SimpleBake_OT_Select_Only_This.hidden = []
        
        #Reload all baked images
        imgs = [i for i in bpy.data.images if ("SB_bake_operation_id" in i and 
                                               i["SB_bake_operation_id"] == self.bake_operation_id)]
        for i in imgs:
            try:
                i.reload()
            except:
                pass

        #Unhide all objects in SimpleBake bakes
        if (c:=bpy.data.collections.get("SimpleBake_Bakes")):
            for o in c.objects:
                if "SB_bake_operation_id" in o and o["SB_bake_operation_id"] == self.bake_operation_id:
                    o.hide_render = False

        start_time = CommonBakePrepandFinish.start_time
        finish_time = datetime.now()
        s = (finish_time-start_time).seconds
        print_message(context, f"Time taken - {s} seconds ({floor(s/60)} minutes, {s%60} seconds)")

        Bip.is_baking = False

        blender_refresh()

        #Reverse any sidestepping of geo nodes objects
        bpy.ops.simplebake.reverse_geo_nodes_sidestep()

        #Renable any addons we disabled
        if not self.in_background:
            re_enable_addons(context)

        #Restore any handlers that we disabled
        for h in CommonBakePrepandFinish.disabled_handlers:
            try:
                bpy.app.handlers.depsgraph_update_post.append(h)
                print_message(context,f"Restored handler {h.__name__}")
            except:
                print_message(context,f"Failed to restore handler {h.__name__}")

        # Remove merged proxy objects
        for n in [o.name for o in bpy.data.objects if "SB_merged_proxy" in o]:
            if o:= bpy.data.objects.get(n):
                bpy.data.objects.remove(o)

        # Remove excluded-material dummy image
        dummy = bpy.data.images.get("SB_excluded_mat_dummy")
        if dummy is not None:
            bpy.data.images.remove(dummy)

        bpy.ops.simplebake.refresh_bake_object_list()

        #Purge unused data from blend file
        prefs = get_sb_prefs(context)
        if prefs.purge_after_bake:
            try:
                bpy.ops.outliner.orphans_purge()
            except:
                pass

        #Restore panel state
        bpy.ops.simplebake.local_preset_load_override(name_override="TMP_Panel_Initial_State")
        tpn = 'TMP_Panel_Initial_State'
        if tpn in sbp:
            del sbp[tpn]

        # active_index and active_render restoration — must run AFTER local preset load.
        # The preset callback sets active_index based on the panel's uvs property (which was
        # snapshotted at bake start), but that may differ from the object's actual active UV
        # at bake start (e.g. user had a non-panel UV active). We always restore from the
        # snapshotted object state so both paths are consistent.
        #
        # Two name lists are needed:
        #   _cur_objs  — current sbp.objects_list (proxy name if join_objs_to_proxy was used)
        #   _orig_objs — original bake object names before proxy creation (from SB_orig_bake_objects)
        # restore=True must act on the originals; restore=False acts on the current/proxy object.
        _cur_objs = list(bake_objects_names)
        if sbp.targetobj is not None: _cur_objs.append(sbp.targetobj.name)
        if sbp.targetobj_cycles is not None: _cur_objs.append(sbp.targetobj_cycles.name)

        _orig_objs = list(sbp.get('SB_orig_bake_objects', _cur_objs))
        if sbp.targetobj is not None and sbp.targetobj.name not in _orig_objs:
            _orig_objs.append(sbp.targetobj.name)
        if sbp.targetobj_cycles is not None and sbp.targetobj_cycles.name not in _orig_objs:
            _orig_objs.append(sbp.targetobj_cycles.name)

        if sbp.restore_orig_uv_map:
            # Restore both active_index and active_render from pre-bake snapshot on the
            # original objects (not the proxy, which is a temporary bake artefact).
            for o_name in _orig_objs:
                obj = context.scene.objects.get(o_name)
                if not obj: continue
                orig_active = CommonBakePrepandFinish.orig_object_uvs.get(o_name)
                if orig_active:
                    idx = next((i for i, l in enumerate(obj.data.uv_layers) if l.name == orig_active), None)
                    if idx is not None:
                        obj.data.uv_layers.active_index = idx
                orig_render = CommonBakePrepandFinish.orig_object_uvs_render.get(o_name)
                if orig_render:
                    for layer in obj.data.uv_layers:
                        layer.active_render = (layer.name == orig_render)
        else:
            # restore=False: set both active_index and active_render to the baked UV.
            # active_render was intentionally NOT set before the bake (to avoid garbling
            # material texture sampling); we set it here now that the bake is complete.
            if CommonBakePrepandFinish.new_uv_option:
                for o_name in _cur_objs:
                    obj = context.scene.objects.get(o_name)
                    if not obj: continue
                    baked_uv = obj.get("SB_uv_used_for_bake")
                    if baked_uv:
                        idx = next((i for i, l in enumerate(obj.data.uv_layers) if l.name == baked_uv), None)
                        if idx is not None:
                            obj.data.uv_layers.active_index = idx
                        for layer in obj.data.uv_layers:
                            layer.active_render = (layer.name == baked_uv)

        try: context.view_layer.objects.active = CommonBakePrepandFinish.orig_active_object
        except: pass

        return {'FINISHED'}


class SimpleBake_OT_Merged_Proxy_Create(Operator):
    """Create the merged bake proxy for baking multiple objects"""
    bl_idname = "simplebake.merged_bake_proxy_create"
    bl_description = "Create the merged bake proxy from the bake objects list"
    bl_label = "MergedBakeProxy"

    def execute(self, context):

        if not True:
            print_message(context, "No need to create merged proxy - finishing")
            return {'FINISHED'}

        sbp = context.scene.SimpleBake_Props
        scene = context.scene

        # Get originals by name (ignore any missing)
        names = [o.name for o in sbp.objects_list]
        originals = [bpy.data.objects.get(n) for n in names if bpy.data.objects.get(n)]

        force_to_object_mode(context)
        bpy.ops.object.select_all(action='DESELECT')

        if originals:
            # Select originals and make one active
            context.view_layer.objects.active = originals[0]
            for ob in originals:
                ob.select_set(True)
                ob.hide_render = True

            # Duplicate; Blender keeps the NEW duplicates selected
            bpy.ops.object.duplicate()

            # Capture the duplicates
            duplicates = list(context.selected_objects)

            # --- REVISED: unify *edit-active* UV names on all duplicates (for baking) ----------
            TARGET_UV_NAME = "SimpleBake_Merged_Proxy"

            def _unique_uv_name(uv_layers, base):
                existing = {l.name for l in uv_layers}
                if base not in existing:
                    return base
                i = 1
                while f"{base}_{i}" in existing:
                    i += 1
                return f"{base}_{i}"

            for ob in duplicates:
                me = getattr(ob, "data", None)
                if not me or not getattr(me, "uv_layers", None) or len(me.uv_layers) == 0:
                    continue

                uvs = me.uv_layers

                # Pick the EDIT-active layer (fallback to first if none flagged for any reason)
                layer = next((l for l in uvs if getattr(l, "active", False)), None) or uvs[0]

                # If some *other* layer already has the target name, move it aside to avoid a clash
                existing_named = next((l for l in uvs if l.name == TARGET_UV_NAME), None)
                if existing_named and existing_named is not layer:
                    existing_named.name = _unique_uv_name(uvs, TARGET_UV_NAME + "_replaced")

                # Rename the edit-active layer to the target name
                layer.name = TARGET_UV_NAME

                # Ensure it remains the edit-active layer (so baking uses it)
                # Use index-based setter for robustness across Blender versions
                idx = next((i for i, l in enumerate(uvs) if l is layer), None)
                if idx is not None:
                    try:
                        uvs.active_index = idx
                    except Exception:
                        # Fallback toggles
                        for l in uvs:
                            try: l.active = False
                            except Exception: pass
                        try: layer.active = True
                        except Exception: pass

                # Do NOT delete other UV layers (e.g. "UVMap").  The joined proxy's
                # materials may contain UV Map nodes that reference those layers by name —
                # removing them causes those nodes to fall back to wrong/zero coordinates,
                # garbling the bake.  The proxy only needs TARGET_UV_NAME as the *active*
                # (bake-target) UV; all other user UV maps are kept so material sampling works.
                # active_render stays on whichever layer the user had it on (typically "UVMap"),
                # which is correct: Cycles samples the material via active_render, then writes
                # the result to the active (edit-active) TARGET_UV_NAME layout.
            # -----------------------------------------------------------------------------------

            # Apply all modifiers (in order) on each duplicate
            for ob in duplicates:
                context.view_layer.objects.active = ob
                for mod in ob.modifiers[:]:  # iterate over a copy
                    try:
                        bpy.ops.object.modifier_apply(modifier=mod.name)
                    except Exception:
                        pass

            # Join the duplicates
            if duplicates:
                context.view_layer.objects.active = duplicates[0]
                for ob in duplicates:
                    ob.select_set(True)
                bpy.ops.object.join()

            # Rename the joined result
            context.active_object.name = "SB_Merged_Proxy"
            context.active_object["SB_merged_proxy"] = True
            context.active_object["SB_uv_used_for_bake"] = TARGET_UV_NAME
            context.active_object.hide_render = False

            #Alter the bake objects list
            sbp.objects_list.clear()
            bpy.ops.simplebake.add_bake_object_by_name(override_target_obj_name=context.active_object.name)
            bpy.ops.simplebake.refresh_bake_object_list()

        return {'FINISHED'}


class SimpleBake_OT_Reset_Specials_Materials(Operator):
    bl_idname = "simplebake.reset_specials_materials"
    bl_label = "Reset All Specials Materials"
    bl_description = "Reset all Specials Materials to their SimpleBake default. Takes effect on next bake or preview of that Specials material"

    def execute(self, context):
        bpy.ops.simplebake.restore_preview()
        removed = 0
        target_names = [f"SimpleBake_{m}" for m in SBConstants.ALL_SPECIALS] + ["SB_col_id"]
        for name in target_names:
            mat = bpy.data.materials.get(name)
            if mat is not None:
                bpy.data.materials.remove(mat, do_unlink=True)
                removed += 1
        self.report({'INFO'}, f"Removed {removed} SimpleBake specials material(s)")
        return {'FINISHED'}


classes = ([
    SimpleBake_OT_Pack_Baked_Images,
    SimpleBake_OT_Scale_Images_If_Needed,
    SimpleBake_OT_Common_Bake_Prep,
    SimpleBake_OT_Common_Bake_Finishing,
    SimpleBake_OT_Select_Only_This,
    SimpleBake_OT_Compositor_Denoise,
    SimpleBake_OT_Select_Selected_To_Active,
    SimpleBake_OT_Set_Sample_Count,
    SimpleBake_OT_Compositor_AA,
    SimpleBake_OT_Merged_Proxy_Create,
    SimpleBake_OT_Reset_Specials_Materials,
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
    
