import bpy
from bpy.props import (FloatProperty, StringProperty, BoolProperty, 
                       EnumProperty, PointerProperty, IntProperty, CollectionProperty, FloatVectorProperty)
from bpy.types import PropertyGroup
from bpy.utils import register_class, unregister_class
import os
import getpass
import tempfile
from pathlib import Path

from .utils import SBConstants, show_message_box, get_cs_list, select_only_this, disable_impossible, blender_default_colorspace
from . import __package__ as base_package

from .aov import get_list_enabled_aov_names, get_aov_number


suppress_for_preset_load = False


class ZZ_ObjectListItem(PropertyGroup):
    """Group of properties representing an item in the list."""

    obj_point:   PointerProperty(
            name="Bake Object",
            description="An object in the scene to be baked",
            type=bpy.types.Object)

    name: StringProperty(
           name="Name",
           description="A name for this item",
           default= "Untitled")

    # target: StringProperty(
    #        name="Target",
    #        description="Target when we are doing an S2A bake",
    #        default= "Untitled")

class PresetItem(PropertyGroup):
    """Group of properties representing a SimpleBake preset."""

    name: bpy.props.StringProperty(
           name="Name",
           description="A name for this item",
           default= "Untitled")

class CPTexItem(PropertyGroup):
    """Group of properties representing a SimpleBake CP Texture."""

    name: StringProperty(
           name="Name",
           description="A name for this item",
           default= "Untitled")
    R: StringProperty(
           name="R",
           description="Bake type for R channel")
    G: StringProperty(
           name="G",
           description="Bake type for G channel")
    B: StringProperty(
           name="B",
           description="Bake type for B channel")
    A: StringProperty(
           name="A",
           description="Bake type for A channel")
    file_format: StringProperty(
           name="File Format",
           description="File format for CP texture")
    exr_codec: StringProperty()
    png_compression: IntProperty()


def auto_set_bake_margin(context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    
    multiplier = 4
    
    current_width = sbp.imgwidth
    margin = (current_width / 1024) * multiplier
    margin = round(margin, 0)
    
    context.scene.render.bake.margin = int(margin)

    return True

def selected_col_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    
    if not sbp.selected_col:
        sbp.apply_col_man_to_col = False
        sbp.multiply_diffuse_ao = "purediffuse"
    disable_impossible(context)

def tex_per_mat_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.tex_per_mat == True:
        sbp.copy_and_apply = False
        sbp.hide_source_objects = False
        sbp.hide_cage_object = False
        sbp.expand_mat_uvs = False
    disable_impossible(context)
    
def expand_mat_uvs_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.expand_mat_uvs:
        sbp.new_uv_option = False
        sbp.prefer_existing_sbmap = False
    disable_impossible(context)

def copy_and_apply_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.copy_and_apply == False:
        sbp.hide_source_objects = False
        sbp.hide_cage_object = False
        sbp.create_glTF_node = False
    else:
        sbp.hide_source_objects = True
        sbp.hide_cage_object = True
        sbp.apply_bakes_to_original = False
        sbp.del_cptex_components = False
    #disable_impossible(context)
    
def apply_bakes_to_original_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.apply_bakes_to_original:
        sbp.copy_and_apply = False
        sbp.del_cptex_components = False
    disable_impossible(context)


def export_file_format_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.export_file_format == "JPEG" or sbp.export_file_format == "TARGA":
        sbp.everything_16bit = False
        #sbp.use_alpha = False
    disable_impossible(context)
    
def save_bakes_external_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.save_bakes_external == False:
        sbp.everything_16bit = False
        #sbp.rundenoise = False
        sbp.export_folder_per_object = False
        sbp.cp_list.clear()

        sbp.rough_glossy_switch = SBConstants.PBR_ROUGHNESS
        sbp.ccrough_glossy_switch = SBConstants.PBR_CLEARCOAT_ROUGH
        sbp.normal_format_switch = SBConstants.NORMAL_OPENGL

        sbp.do_aa = False
        
    disable_impossible(context)

def new_uv_option_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.new_uv_option == True:
        sbp.prefer_existing_sbmap = False
        sbp.auto_detect_udims = False
    else:
        sbp.auto_detect_udims = True

    disable_impossible(context)

def global_mode_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    
    if not sbp.global_mode == SBConstants.CYCLESBAKE:
        sbp.tex_per_mat = False
        sbp.expand_mat_uvs = False
        sbp.cycles_s2a = False
        sbp.targetobj_cycles = None

    
    if not sbp.global_mode == SBConstants.PBR:
        sbp.selected_s2a = False
        sbp.targetobj = None
        sbp.s2a_opmode = "single"

    disable_impossible(context)

        
def selected_rough_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if not sbp.selected_rough:
        sbp.rough_glossy_switch = SBConstants.PBR_ROUGHNESS
    disable_impossible(context)

def selected_ccrough_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if not sbp.selected_clearcoat_rough:
        sbp.ccrough_glossy_switch = SBConstants.PBR_CLEARCOAT_ROUGH
    disable_impossible(context)
        
def selected_normal_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if not sbp.selected_normal:
        sbp.normal_format_switch = SBConstants.NORMAL_OPENGL
    disable_impossible(context)
        
        
def presets_list_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    
    index = sbp.presets_list_index
    item = sbp.presets_list[index]
    
    sbp.preset_name = item.name
    disable_impossible(context)
    
def local_presets_list_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props

    index = sbp.local_presets_list_index
    item = sbp.local_presets_list[index]

    sbp.local_preset_name = item.name
    disable_impossible(context)

def presets_show_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    bpy.ops.simplebake.preset_refresh()
    disable_impossible(context)
 
def imgheight_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    sbp.outputheight = sbp.imgheight
    disable_impossible(context)
 
def imgwidth_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    sbp.outputwidth = sbp.imgwidth
    disable_impossible(context)

def textures_show_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    
    if sbp.first_texture_show:
        auto_set_bake_margin(context)
        sbp.first_texture_show = False
    disable_impossible(context)
        
def bake_objects_show_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.first_texture_show:
        auto_set_bake_margin(context)
        sbp.first_texture_show = False
    disable_impossible(context)

def selected_s2a_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if not sbp.selected_s2a:
        sbp.targetobj = None
        sbp.s2a_opmode = 'single'

    
    if sbp.selected_s2a:
        sbp.selected_col_mats = False
        sbp.selected_lightmap  = False
    disable_impossible(context)
        
def cycles_s2a_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if not sbp.cycles_s2a:
        sbp.targetobj_cycles = None
        
    if sbp.cycles_s2a:
        sbp.selected_col_mats = False
        sbp.selected_lightmap  = False
    disable_impossible(context)

def cp_list_index_update(self, context):
    if suppress_for_preset_load:
        return True
    sbp = context.scene.SimpleBake_Props
    index = sbp.cp_list_index
    cpt = sbp.cp_list[index]
    
    messages = []
    try: #EXR no longer an option, but old presets and the examples may contain it
        sbp.channelpackfileformat = cpt.file_format
        sbp.exr_codec_cpts = cpt.exr_codec
    except:
        pass

    if "png_compression" in cpt:
        sbp.png_compression = cpt.png_compression

    try:
        sbp.cptex_R = cpt.R
    except:
        messages.append(f"WARNING: {cpt.name} depends on {cpt.R} for the Red channel, but you are not baking it")
        messages.append("You can enable the required bake, or change the bake for that channel")
    try:
        sbp.cptex_G = cpt.G
    except:
        messages.append(f"WARNING: {cpt.name} depends on {cpt.G} for the Green channel, but you are not baking it")
        messages.append("You can enable the required bake, or change the bake for that channel")
    try:
        sbp.cptex_B = cpt.B
    except:
        messages.append(f"WARNING: {cpt.name} depends on {cpt.B} for the Blue channel, but you are not baking it")
        messages.append("You can enable the required bake, or change the bake for that channel")
    try:
        sbp.cptex_A = cpt.A
    except:
        messages.append(f"WARNING: {cpt.name} depends on {cpt.A} for the Alpha channel, but you are not baking it")
        messages.append("You can enable the required bake, or change the bake for that channel")

    sbp.cp_name = cpt.name

    try:
        context.scene.render.image_settings.exr_codec = cpt.exr_codec
    except:
        pass

    #Show messages
    if len(messages)>0:
        show_message_box(context, messages, title = "Warning", icon = "ERROR")
    disable_impossible(context)

def clear_image_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    #if not sbp.clear_image:
        #sbp.use_alpha = False
    disable_impossible(context)

def bgbake_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.bgbake == "bg":
        sbp.apply_bakes_to_original = False
    disable_impossible(context)


def s2a_opmode_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.s2a_opmode == "decals":
        sbp.selected_alpha = True
    disable_impossible(context)


def auto_match_mode_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    disable_impossible(context)


def objects_list_index_update(self, context):

    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    i = sbp.objects_list_index
    if i != -1: #Not sure what causes this, but at least one bug report flagged it
        if len(sbp.objects_list)>0:
            o = sbp.objects_list[i]
            if o.obj_point != None:
                select_only_this(context, o.obj_point)

    disable_impossible(context)

def keep_internal_after_export_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props

    if not sbp.keep_internal_after_export:
        sbp.copy_and_apply = False

def merged_bake_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props

    if not sbp.merged_bake:
        sbp.merge_export_obj = False
        sbp.join_objs_to_proxy = False


def join_objs_to_proxy_update(self, context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props
    if sbp.join_objs_to_proxy:
        sbp.showtips = True
        sbp.isolate_objects = False


def batch_name_update(self, context):
    prefs = context.preferences.addons[base_package].preferences
    maxlen = prefs.batch_name_max_length
    if len(self.batch_name) > maxlen:
        self.batch_name = self.batch_name[:maxlen]



def multiply_diffuse_ao_update(self,context):
    if suppress_for_preset_load: return True
    sbp = context.scene.SimpleBake_Props

    if sbp.multiply_diffuse_ao == "diffusexao":
        sbp.selected_ao = True


    #disable_impossible(context) #Recursion error...?

def auto_cage_extrusion_update(self,context):
    sbp = context.scene.SimpleBake_Props

    to = None
    if sbp.global_mode == "PBR":
        to = sbp.targetobj
    else:
        to = sbp.targetobj_cycles

    if to == None:
        return False

    #Find the auto cage object
    co = [o for o in context.scene.objects if "SB_auto_cage" in o and o["SB_auto_cage"] == to.name]
    if len(co) != 1:
        #ERROR
        return False
    else:
        co = co[0]

    #Adjust the modifier
    if 'SB_AUTO_CAGE' in co.modifiers:
        co.modifiers['SB_AUTO_CAGE'].mid_level = 1-sbp.auto_cage_extrusion




#-------------------------------------------------------------------

def get_selected_bakes_dropdown(self, context):
    sbp = context.scene.SimpleBake_Props
    items = []
    
    items.append(("none", "None",""))
    
    if sbp.selected_col:
        items.append((SBConstants.PBR_DIFFUSE, SBConstants.PBR_DIFFUSE,""))
    if sbp.selected_metal:
        items.append((SBConstants.PBR_METAL, SBConstants.PBR_METAL,""))
    if sbp.selected_sss:
        items.append((SBConstants.PBR_SSS, SBConstants.PBR_SSS,""))
    if sbp.selected_sss_scale:
        items.append((SBConstants.PBR_SSS_SCALE, SBConstants.PBR_SSS_SCALE,""))
    if sbp.selected_ssscol:
        items.append((SBConstants.PBR_SSSCOL, SBConstants.PBR_SSSCOL,""))
    if sbp.selected_rough:
        if sbp.rough_glossy_switch == SBConstants.PBR_GLOSSY:
            items.append((SBConstants.PBR_GLOSSY, SBConstants.PBR_GLOSSY,""))
        else:
            items.append((SBConstants.PBR_ROUGHNESS, SBConstants.PBR_ROUGHNESS,""))
    if sbp.selected_normal:
        items.append((SBConstants.PBR_NORMAL, SBConstants.PBR_NORMAL,""))
    if sbp.selected_trans:
        items.append((SBConstants.PBR_TRANSMISSION, SBConstants.PBR_TRANSMISSION,""))
    if sbp.selected_transrough:
        items.append((SBConstants.PBR_TRANSMISSION_ROUGH, SBConstants.PBR_TRANSMISSION_ROUGH,""))
    if sbp.selected_clearcoat:
        items.append((SBConstants.PBR_CLEARCOAT, SBConstants.PBR_CLEARCOAT,""))
    if sbp.selected_clearcoat_rough:
        if sbp.ccrough_glossy_switch == SBConstants.PBR_CLEARCOAT_GLOSS:
            items.append((SBConstants.PBR_CLEARCOAT_GLOSS, SBConstants.PBR_CLEARCOAT_GLOSS,""))
        else:
            items.append((SBConstants.PBR_CLEARCOAT_ROUGH, SBConstants.PBR_CLEARCOAT_ROUGH,""))
    if sbp.selected_emission:
        items.append((SBConstants.PBR_EMISSION, SBConstants.PBR_EMISSION,""))
    if sbp.selected_emission_strength:
        items.append((SBConstants.PBR_EMISSION_STRENGTH, SBConstants.PBR_EMISSION_STRENGTH,""))
    if sbp.selected_specular:
        items.append((SBConstants.PBR_SPECULAR, SBConstants.PBR_SPECULAR,""))
    if sbp.selected_alpha:
        items.append((SBConstants.PBR_ALPHA, SBConstants.PBR_ALPHA,""))
    if sbp.selected_bump:
        items.append((SBConstants.PBR_BUMP, SBConstants.PBR_BUMP,""))
    if sbp.selected_displacement:
        items.append((SBConstants.PBR_DISPLACEMENT, SBConstants.PBR_DISPLACEMENT,""))
        
    if sbp.selected_col_mats:
        items.append((SBConstants.COLOURID, SBConstants.COLOURID,""))
    if sbp.selected_col_vertex:
        items.append((SBConstants.VERTEXCOL, SBConstants.VERTEXCOL,""))
    if sbp.selected_ao:
        items.append((SBConstants.AO, SBConstants.AO,""))
    if sbp.selected_thickness:
        items.append((SBConstants.THICKNESS, SBConstants.THICKNESS,""))
    if sbp.selected_curvature:
        items.append((SBConstants.CURVATURE, SBConstants.CURVATURE,""))
    if sbp.selected_lightmap:
        items.append((SBConstants.LIGHTMAP, SBConstants.LIGHTMAP,""))

    #AOVs
    aov_names = get_list_enabled_aov_names(context)
    for name in aov_names:
        ident =  f"{SBConstants.PBRAOVS}_{get_aov_number(context, name)}"
        des = ""
        items.append((ident, f"AOV: {name}", des))

    return items

def get_presets_dropdown(self, context):
    sbp = context.scene.SimpleBake_Props
    path = ""
    if sbp.export_format == "fbx":
        path = 'operator/export_scene.fbx/'
    if sbp.export_format == "obj":
        path = 'operator/wm.obj_export/'
    if sbp.export_format == "gltf":
        path = 'operator/export_scene.gltf/'
    if sbp.export_format == "dae":
        path = 'operator/wm.collada_export/'

    preset_paths = bpy.utils.preset_paths(path)

    if preset_paths:
        items = []
        for d in preset_paths:
            entries = os.listdir(d)
            for e in entries:
                if not os.path.isdir(d + e):
                    items.append((d+e, e.replace(".py",""), "", 'EXPORT', len(items)))

        items.insert(0, ("None", "None", "", 'CANCEL', len(items)))
        return items

    else:
        return [("None", "None", "")]

def get_uv_options_dropdown(self, context):
    sbp = context.scene.SimpleBake_Props

    uv_options = []
    names = [i.name for i in sbp.objects_list]
    for name in names:
        if o:=bpy.data.objects.get(name):
            uv_options.extend([l.name for l in o.data.uv_layers])

    if len(uv_options) == 0:
        return [("None", "None", "")]
    else:
        return [(n, n, "") for n in sorted(set(uv_options))]


# def get_obj_presets_dropdown(self, context):
#     preset_path = bpy.utils.preset_paths('operator/wm.obj_export/')
#
#     if preset_path:
#         items = os.listdir(preset_path[0])
#         items = [ (i, i.replace(".py", ""), "") for i in items if not os.path.isdir(preset_path[0] + i)]
#         items.insert(0, ("None", "None", ""))
#
#         return items
#
#     else:
#         return [("None", "None", "")]
#
# def get_fbx_presets_dropdown(self, context):
#     preset_path = bpy.utils.preset_paths('operator/export_scene.fbx/')
#
#     if preset_path:
#         items = os.listdir(preset_path[0])
#         items = [ (i, i.replace(".py", ""), "") for i in items if not os.path.isdir(preset_path[0] + i)]
#         items.insert(0, ("None", "None", ""))
#
#         return items
#
#     else:
#         return [("None", "None", "")]
#
# def get_gltf_presets_dropdown(self, context):
#     preset_path = bpy.utils.preset_paths('operator/export_scene.gltf/')
#
#     if preset_path:
#         items = os.listdir(preset_path[0])
#         items = [ (i, i.replace(".py", ""), "") for i in items if not os.path.isdir(preset_path[0] + i)]
#         items.insert(0, ("None", "None", ""))
#
#         return items
#
#     else:
#         return [("None", "None", "")]

def get_cpt_format_dropdown(self,context):
    items = [("PNG", "PNG", ""), ("TARGA", "TGA", "")]
    prefs = context.preferences.addons[base_package].preferences
    if prefs.use_old_channel_packing:
        items.append(("OPEN_EXR", "Open EXR", ""))
    return items



def get_s2aopmode_options(self, context):
    sbp = context.scene.SimpleBake_Props

    items=[
        ("single", "Standard (bake list to target)", ""),
        ("automatch", "Auto-match high to low", "")
        ]

    if sbp.global_mode == SBConstants.PBR:
        items.append(("decals", "Decals to target", ""))

    return items

# 1. Define a PropertyGroup for each AOV item
class ZZ_AOVItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    aov_type: bpy.props.StringProperty(default="C")
    aov_number: bpy.props.IntProperty()
    enabled: bpy.props.BoolProperty(name="Enabled")
    cs: bpy.props.EnumProperty(name="", items=get_cs_list, default=blender_default_colorspace(float_buffer=False, col=True)[0])
    object_name: bpy.props.StringProperty()
    mat_name: bpy.props.StringProperty()

def _set_edit_active_uv_by_name(ob: bpy.types.Object, uv_name: str):
    me = getattr(ob, "data", None)
    if not me or not getattr(me, "uv_layers", None):
        return
    for i, l in enumerate(me.uv_layers):
        if l.name == uv_name:
            # Prefer index setter for robustness
            try:
                me.uv_layers.active_index = i
            except Exception:
                # Fallback toggles if index setter isn't available
                for ll in me.uv_layers:
                    try: ll.active = False
                    except Exception: pass
                try: l.active = True
                except Exception: pass
            break

class ZZ_SimpleBakeUVItem(PropertyGroup):
    #object_name: StringProperty(name="Object"
    name: StringProperty(name="Object")
    uv_name: StringProperty(
        name="Edit-Active UV",
        description="Select the UV map to be edit-active for this object",
        update=lambda self, context: _set_edit_active_uv_by_name(
            #bpy.data.objects.get(self.object_name, None), self.uv_name
            bpy.data.objects.get(self.name, None), self.uv_name
        )
    )


class ZZ_SimpleBakePropGroup(bpy.types.PropertyGroup):

    
    uv_items: CollectionProperty(type=ZZ_SimpleBakeUVItem)
    uv_items_index: IntProperty(default=0)

    des = "Global Baking Mode"
    global_mode: EnumProperty(name="Bake Mode", default=SBConstants.PBR, description="", items=[\
    (SBConstants.PBR, "PBR Bake", "Bake PBR maps from materials created around the Principled BSDF and Emission shaders"),\
    (SBConstants.CYCLESBAKE, "Cycles Bake", "Bake the 'traditional' cycles bake modes")\
    ], update = global_mode_update)
    
    
    des = "Distance to cast rays from target object to selected object(s)"
    ray_distance: FloatProperty(name="Ray Distance", default = 0.0, min=0, description=des)
    des = "A multiplier for BOTH Cage Extrusion and Ray Distance. This can help you more easily dial in the correct values"
    cage_and_ray_multiplier: FloatProperty(name="Multiplier", default = 1, min=0, description=des)
    des = "Adjust this value to inflate or deflate the auto cage object"
    auto_cage_extrusion: FloatProperty(name="Extrusion", default = 0, min=0, max=1, description=des, update=auto_cage_extrusion_update)
    
    des = "The distance for Blender to extrude the automatically generated cage for baking to target. See the tooltip for the \"Auto extruded cage type\" option for more info. NOTE: If you are auto-matching high poly to low poly objects in name mode, this setting will only be relevant where a cage object is not detected for that low object. It will be ignored whenever a cage is present. See the Monkey Tip."
    cage_extrusion: FloatProperty(name="Cage Extrusion", default = 0.1, min=0, description=des)
    
    
    #CyclesBake settings
    des = "Select the colour space for the baked texture"
    cyclesbake_cs: EnumProperty(name="Colour Space", description=des, items=get_cs_list, default=blender_default_colorspace(float_buffer=False, col=True)[0])
    des = "Bake each object on its own, hiding the others so they don't influence the bake. When baking to target, this hides the influence of all objects *except those in your bake list*, so they no longer influence the objects that are in the list. Lights are unaffected"
    isolate_objects: BoolProperty(name="Isolate objects from each other during baking", description=des)
    
    #Bake mechanics (S2A etc)
    des = "Bake maps from one or more  source objects (usually high poly) to a single target object (usually low poly). Source and target objects must be in the same location (overlapping). See Blender documentation on selected to active baking for more details"
    selected_s2a: BoolProperty(name="Bake selected objects to target object", description=des, update=selected_s2a_update)
    des = "Specify the target object for the baking. Note, this need not be part of your selection in the viewport (though it can be)"
    targetobj: PointerProperty(name="Target Object", description=des, type=bpy.types.Object)
    des=("Choose the mode for detecting low poly objects. This can either be by name (\"obj_low\" and \"obj_high\") or by position (the closest object to the one in the bake list)")
    auto_match_mode: EnumProperty(name="Auto match mode", default="position", update=auto_match_mode_update,
    description=des, items=[
        ("name", "By name", ""),
        ("position", "By position", "")
        ])
    
    des = "If you are not using a custom cage object, Blender will automatically extrude a cage from your target object when baking to target. That automatically extruded cage can be either smooth or hard. NOTE: If you are auto-matching high poly to low poly objects in name mode, this setting will only be relevant where a cage object is not detected for that low object. It will be ignored whenever a cage is present. See the Monkey Tip."
    cage_smooth_hard: EnumProperty(name="Auto extruded cage type", default="smooth", 
        description=des, items=[
            ("smooth", "Smooth", ""),
            ("hard", "Hard", "")
            ])
    
    des = "Bake multiple objects to one set of textures. Not available with 'Bake maps to target object' (would not make sense), UNLESS you are using the \"Auto match high and low poly\" option. You must be baking more than one object."
    merged_bake: BoolProperty(name="Multiple objects to one texture set", default = False, description=des, update=merged_bake_update)
    des = (
    "Join bake objects into one to speed up the baking process. "
    "Note: Any modifiers will be applied for baking (not permanently). "
    "⚠️ WARNING ⚠️: If your materials use Generated or Object texture coordinates, "
    "these will change when objects are combined, so the baked result may not "
    "match the original material appearance."
    )
    join_objs_to_proxy: BoolProperty(name="Join objects for bake", default = False, description=des, update=join_objs_to_proxy_update)


    des = "When baking one object at a time, the object's name is used in the texture name. Baking multiple objects to one texture set, however requires you to proivde a name for the textures"
    merged_bake_name: StringProperty(name="Texture name for multiple bake", default = "MergedBake", description=des)
    des = "Bake using the Cycles selected to active option"
    cycles_s2a: BoolProperty(name="Selected to Active", description=des, update=cycles_s2a_update)
    des = "Specify the target object to bake to (this would be the active object with vanilla Blender baking)"
    targetobj_cycles: PointerProperty(name="Target Object", description=des, type=bpy.types.Object)

    #S2A op mode
    des="SimpleBake offers different ways of baking to a target object"
    s2a_opmode: EnumProperty(name="Bake to target mode", default=0,
        description=des, items=get_s2aopmode_options, update=s2a_opmode_update)
    
    #Texture settings related
    des="Bake to an existing image, override all other texture related settings"
    tex_override: BoolProperty(name="Override and bake to existing image", default = False, description=des)
    des="Existing image to bake to"
    tex_override_tex: PointerProperty(name="Existing Image:", description=des, type=bpy.types.Image)


    des = "Set the height of the baked image that will be produced"
    imgheight: IntProperty(name="Bake height", default=1024, description=des, update=imgheight_update)
    des = "Set the width of the baked image that will be produced"
    imgwidth: IntProperty(name="Bake width", default=1024, description=des, update=imgwidth_update)
    des = "Set the height of the baked image that will be ouput"
    outputheight: IntProperty(name="Output Height", default=1024, description=des)
    des = "Set the width of the baked image that will be output"
    outputwidth: IntProperty(name="Output Width", default=1024, description=des)
    des = "Normal maps are always created as 32bit float images, but this option causes all images to be created as 32bit float. Image quality is theoretically increased, but often it will not be noticable."
    everything32bitfloat: BoolProperty(name="All internal 32bit float", default = False, description=des)
    #des = "Baked images have a transparent background (else Black)"
    #use_alpha: BoolProperty(name="Transparent background", default = False, description=des)
    des = "Clear the existing bake image (if any) before baking to it. Keeping this enabled will ensure that SimpleBake starts with a blank image for each bake. Turn this off to allow iterative baking where each bake will add to the existing image."
    clear_image: BoolProperty(name="Clear existing bake image before bake", default = True, description=des, update=clear_image_update)
    des="Switch between roughness and glossiness (inverts of each other). NOTE: Roughness is the default for Blender so, if you change this, texture probably won't look right when used in Blender. Only available if you are exporting your bakes (see the \"Export settings\" section.)"
    rough_glossy_switch: EnumProperty(name="", default=SBConstants.PBR_ROUGHNESS, 
        description=des, items=[
            (SBConstants.PBR_ROUGHNESS, "Rough", ""),
            (SBConstants.PBR_GLOSSY, "Glossy", "")
            ])
    des="Switch between roughness and glossiness for CLEARCOAT (inverts of each other). NOTE: Roughness is the default for Blender so, if you change this, texture probably won't look right when used in Blender. Only available if you are exporting your bakes (see the \"Export settings\" section.)"
    ccrough_glossy_switch: EnumProperty(name="", default=SBConstants.PBR_CLEARCOAT_ROUGH,
        description=des, items=[
            (SBConstants.PBR_CLEARCOAT_ROUGH, "Rough", ""),
            (SBConstants.PBR_CLEARCOAT_GLOSS, "Glossy", "")
            ])

    des="Switch between OpenGL and DirectX formats for normal map. NOTE: Opengl is the default for Blender so, if you change this, texture probably won't look right when used in Blender.  Only available if you are exporting your bakes (see the \"Export settings\" section.)"
    normal_format_switch: EnumProperty(name="", default=SBConstants.NORMAL_OPENGL, 
        description=des, items=[
            (SBConstants.NORMAL_OPENGL, "OpenGL", ""),
            (SBConstants.NORMAL_DIRECTX, "DirectX", "")
            ])
    des = "Bake each material into its own texture (for export to virtual worlds like Second Life"
    tex_per_mat: BoolProperty(name="Texture per material", description=des)

    des = "Run baked textures through the compositor anti-aliasing node. Must be exporting your bakes or this will be greyed out. Does not operate on normal map images"
    do_aa: BoolProperty(name="Anti-aliasing", description=des)
    des = "Threshold to use for compositor anti-aliasing"
    aa_threshold: FloatProperty(name="AA threshold", description=des, default=1.0, max=1.0, min=0.0, subtype='FACTOR')
    des = "Contrast limit to use for compositor anti-aliasing"
    aa_contrast_limit: FloatProperty(name="AA contrast limit", description=des, default=0.2, max=1.0, min=0.0, subtype='FACTOR')
    des = "Corner radius to use for compositor anti-aliasing"
    aa_corner_radius: FloatProperty(name="AA corner radius", description=des, default=0.250, max=1.0, min=0.0, subtype='FACTOR')

    #PBR bake types selection
    des = "Bake a PBR Colour map"
    selected_col: BoolProperty(name=SBConstants.PBR_DIFFUSE, default = True, description=des, update=selected_col_update)
    des = "Choose between either pure colour/diffuse or multiply colour/diffuse with AO. Must also be baking AO (will be auto-enabled if you choose the multiply option). Must be exporting your bakes or this will be greyed out"
    multiply_diffuse_ao: EnumProperty(name="", default="purediffuse", update=multiply_diffuse_ao_update,
        description=des, items=[
            ("purediffuse", "Diffuse only", ""),
            ("diffusexao", "Diffuse with AO", "")
            ])
    des = "Percentage to multiply the AO with the colour/diffuse"
    multiply_diffuse_ao_percent: IntProperty(name="%", default=50, min=0, max=100)



    des = "Bake a PBR Metalness map"
    selected_metal: BoolProperty(name=SBConstants.PBR_METAL, description=des)
    des = "Bake a PBR Roughness or Glossy map"
    selected_rough: BoolProperty(name="Roughness/Glossy", description=des, update=selected_rough_update)
    des = "Bake a Normal map"
    selected_normal: BoolProperty(name=SBConstants.PBR_NORMAL, description=des, update=selected_normal_update)
    des = "Bake a PBR Transmission map"
    selected_trans: BoolProperty(name=SBConstants.PBR_TRANSMISSION, description=des)
    des = "Bake a PBR Transmission Roughness map"
    selected_transrough: BoolProperty(name=SBConstants.PBR_TRANSMISSION_ROUGH, description=des)
    des = "Bake an Emission map"
    selected_emission: BoolProperty(name=SBConstants.PBR_EMISSION, description=des)
    des = "Bake an Emission Strength map"
    selected_emission_strength: BoolProperty(name=SBConstants.PBR_EMISSION_STRENGTH, description=des)
    des = "Bake a Subsurface map"
    selected_sss: BoolProperty(name=SBConstants.PBR_SSS, description=des)
    des = "Bake a Subsurface scale map"
    selected_sss_scale: BoolProperty(name=SBConstants.PBR_SSS_SCALE, description=des)
    des = "Bake a Subsurface colour map"
    selected_ssscol: BoolProperty(name=SBConstants.PBR_SSSCOL, description=des)
    des = "Bake a PBR Clearcoat Map"
    selected_clearcoat: BoolProperty(name=SBConstants.PBR_CLEARCOAT, description=des)
    des = "Bake a PBR Clearcoat Roughness or Glossy map"
    selected_clearcoat_rough: BoolProperty(name="Clearcoat Roughness/Glossy", description=des, update=selected_ccrough_update)
    des = "Bake a Specular/Reflection map"
    selected_specular: BoolProperty(name=SBConstants.PBR_SPECULAR, description=des)
    des = "Bake a PBR Alpha map"
    selected_alpha: BoolProperty(name=SBConstants.PBR_ALPHA, description=des)
    des = "Bakes the Heigh input for Bump nodes used in your material. Bump node must be plugged into the normal input of the Principled BSDF(s)"
    selected_bump: BoolProperty(name=SBConstants.PBR_BUMP, description=des)
    des = "Bakes either the \"Height\" input for a Displacement node, or the \"Vector\" input for a Vector Displacement node, in either case plugged into the \"Displacement\" socket of the Material Output node. Only works with a single Displacement or Vector Displacement node plugged in (Vector Math nodes not supported)"
    selected_displacement: BoolProperty(name=SBConstants.PBR_DISPLACEMENT, description=des)
    
    #Specials bake types selection
    des = "ColourID Map based on random colour per material"
    selected_col_mats: BoolProperty(name=SBConstants.COLOURID, description=des)
    des = "Bake the active vertex colours to a texture"
    selected_col_vertex: BoolProperty(name=SBConstants.VERTEXCOL, description=des)
    des = "Ambient Occlusion"
    selected_ao: BoolProperty(name=SBConstants.AO, description=des)
    des = "Thickness map"
    selected_thickness: BoolProperty(name=SBConstants.THICKNESS, description=des)
    des = "Curvature map"
    selected_curvature: BoolProperty(name=SBConstants.CURVATURE, description=des)
    des = "Lightmap map"
    selected_lightmap: BoolProperty(name=SBConstants.LIGHTMAP, description=des)
    des = "Apply the colour management settings you have set in the render properties panel to the lightmap. Only available when you are exporting your bakes. Will be ignored if exporting to EXR files as these don't support colour management"
    lightmap_apply_colman: BoolProperty(name="Export with colour management settings", default=False, description=des)
    des = "Sample count to be used for all specials materials with an AO component (thickness, and AO itself"
    ao_sample_count: IntProperty(name="AO Sample Count", description=des, default = 16)
    
    #UV related
    des = "Use Smart UV Project to create a new UV map for your objects (or target object if baking to a target). See Blender Market FAQs for more details"
    new_uv_option: BoolProperty(name="New UV Map(s)", description=des, update=new_uv_option_update)
    des = "If one exists for the object being baked, use any existing UV maps called 'SimpleBake' for baking (rather than the active UV map)"
    prefer_existing_sbmap: BoolProperty(name="Prefer existing UV maps called SimpleBake", description=des)
    des = "New UV Method"
    new_uv_method: EnumProperty(name="New UV Method", default="SmartUVProject_Atlas", description=des, items=[
    ("SmartUVProject_Individual", "Smart UV Project (Individual)", "Each object gets a new UV map using Smart UV Project"),
    ("SmartUVProject_Atlas", "Smart UV Project (Atlas)", "Create a combined UV map (atlas map) using Smart UV Project"),
    ("CombineExisting", "Combine Active UVs (Atlas)", "Create a combined UV map (atlas map) by combining the existing, active UV maps on each object")
    ])
    des = "If you are creating new UVs, or preferring an existing UV map called SimpleBake, the UV map used for baking may not be the one you had displayed in the viewport before baking. This option restores what you had active before baking"
    restore_orig_uv_map: BoolProperty(name="Restore originally active UV map at end", description=des, default=True)
    des = "Margin to use when packing combined UVs into Atlas map"
    uvpackmargin: FloatProperty(name="Pack Margin", default=0.03, description=des)
    des = "Average the size of the UV islands when combining them into the atlas map"
    average_uv_size: BoolProperty(name="Average UV Island Size", default=True, description=des)
    des = "When using 'Texture per material', Create a new UV map, and expand the UVs from each material to fill that map using Smart UV Project"
    expand_mat_uvs: BoolProperty(name="New UVs per material, expanded to bounds", description=des, update=expand_mat_uvs_update)
    des = "Automatically detect where each bake object's UV map is using UDIM tiles, and bake to those tiles. Disable to bake regular UV space (i.e. the first tile) only"
    auto_detect_udims: BoolProperty(name="Auto detect UDIMs", default=True, description=des)
    des = "Margin between islands to use for Smart UV Project"
    unwrapmargin: FloatProperty(name="UV Unwrap Margin", default=0.03, description=des)
    des = "Use the correct aspect option for SmartUVProject"
    uvcorrectaspect: BoolProperty(name="Correct aspect", default=True, description=des)
    des = "Move the newly generated UV map to be the first item in the UV maps list"
    move_new_uvs_to_top: BoolProperty(name="Move new UVs to top", description=des)
    des="A list of available UV maps"
    available_uv_maps: EnumProperty(name="UV Maps", description=des, items=get_uv_options_dropdown)
    
    #UV packing related
    des=""
    uvp_shape_method: EnumProperty(name="Shape method", default="CONCAVE",
    description=des, items=[
        ("CONCAVE", "Concave", ""),
        ("CONVEX", "Convex", "")
        ])

    des=""
    uvp_scale: BoolProperty(name="Scale", default = True, description=des)
    des=""
    uvp_rotate: BoolProperty(name="Rotate", default = True, description=des)

    des=""
    uvp_rotation_method: EnumProperty(name="Rotation method", default="ANY",
    description=des, items=[
        ("AXIS_ALIGNED", "Axis Aligned", ""),
        ("CARDINAL", "Cardinal", ""),
        ("ANY", "Any", "")
        ])

    des=""
    uvp_margin_method: EnumProperty(name="Margin method", default="SCALED",
    description=des, items=[
        ("SCALED", "Scaled", ""),
        ("ADD", "Add", ""),
        ("FRACTION", "Fraction", "")
        ])

    #des=""
    #uvp_margin: FloatProperty(name="Margin", default = 0.1, description=des)

    des=""
    uvp_lock_pinned: BoolProperty(name="Lock pinned", default = False, description=des)

    des=""
    uvp_lock_method: EnumProperty(name="Lock method", default="LOCKED",
    description=des, items=[
        ("SCALE", "Scale", ""),
        ("ROTATION", "Rotation", ""),
        ("ROTATION_SCALE", "Rotation Scale", ""),
        ("LOCKED", "All", "")
        ])

    des=""
    uvp_merge_overlapping: BoolProperty(name="Merge overlapping", default = False, description=des)

    des=""
    uvp_pack_to: EnumProperty(name="Pack to", default="CLOSEST_UDIM",
    description=des, items=[
        ("CLOSEST_UDIM", "Closest UDIM", ""),
        ("ACTIVE_UDIM", "Active UDIM", ""),
        ("ORIGINAL_AABB", "Original", "")
        ])

    #Export related
    des = "Export your bakes to the folder specified below, under the same folder where your .blend file is saved. Not available if .blend file not saved"
    save_bakes_external: BoolProperty(name="Export bakes", default = False, description=des, update = save_bakes_external_update)
    des = "Create a sub-folder for the textures and mesh file of each baked object. Only available if you are exporting bakes and/or mesh."
    export_folder_per_object: BoolProperty(name="Sub-folder per object", default = False, description=des)
    des="Either export to a single file or export each object to its own file"
    export_mesh_individual_or_combined: EnumProperty(name="Export mesh single or combined", default="individual",
    description=des, items=[
        ("individual", "Individual mesh files", ""),
        ("combined", "Combined mesh file", "")
        ])

    des = "Export your mesh with a single texture and the UV map used for baking (i.e. ready for import somewhere else. File is saved in the folder specified below, under the folder where your blend file is saved. Not available if .blend file not saved"
    save_obj_external: BoolProperty(name="Export mesh", default = False, description=des)

    des = "Merge objects into single object within the export file. Must be used in combination with 'Multiple Objects to One Texture Set'. Must also be using the 'Combined mesh file' option above"
    merge_export_obj: BoolProperty(name="Merge mesh on export", default=False, description=des)

    des = "File name of the mesh export. NOTE: To maintain compatibility, only MS Windows acceptable characters will be used. You can use %blend_file_name% to have this be automatically set to the name of the current blend file"
    mesh_export_name: StringProperty(name="File name", description=des, default="%blend_file_name%", maxlen=50)

    des = "Create a copy of your selected objects in Blender (or target object if baking to a target) and apply the baked textures to it. If you are baking in the background, this happens after you import/ Cannot be used at the same time as 'Apply bakes to original objects'. You cannot use this option if you have deselected 'Keep internal images after export' as you need them for the new material"
    copy_and_apply: BoolProperty(name="Copy objects and apply bakes", default = False, description=des, update=copy_and_apply_update)
    des = "Apply the baked textures to the original objects. Cannot be used at the same time as 'Copy objects and apply bakes'. Cannot be used when baking in the background"
    apply_bakes_to_original: BoolProperty(name="Apply bakes to original object", default = False, description=des, update=apply_bakes_to_original_update)
    des = "Material on your Copy and Apply object based around Principled BSDF, Emission BSDF or Background node"
    cyclesbake_copy_and_apply_mat_format: EnumProperty(name="Material format", default="emission", 
    description=des, items=[
        ("principled", "Principled BSDF", ""),
        ("emission", "Emission", ""),
        ("background", "Background", "")
        ])
    des = "Hide the source object that you baked from in the viewport after baking. If you are baking in the background, this happens after you import"
    hide_source_objects: BoolProperty(name="Hide source objects after bake", default = False, description=des)
    des = "Hide the cage object that you baked from in the viewport after baking. If you are baking in the background, this happens after you import"
    hide_cage_object: BoolProperty(name="Hide cage object after bake", default = False, description=des)
    des="Preserve original material assignments for baked objects (NOTE: all materials will be identical, and point to the baked texture set, but face assignments for each material will be preserved)"
    preserve_materials: BoolProperty(name="Preserve object original materials (BETA)", description=des)
    des = "Normal maps are always exported as 16bit, but this option causes all images to be exported 16bit. This should probably stay enabled unless file sizes are an issue"
    everything_16bit: BoolProperty(name="All exports 16bit", default = True, description=des)
    des="Select the file format for exported bakes. Also applies to Sketchfab upload images"
    export_file_format: EnumProperty(name="Export File Format", update=export_file_format_update, default="PNG", 
    description=des, items=[
        ("PNG", "PNG", ""),
        ("JPEG", "JPG", ""),
        ("TIFF", "TIFF", ""),
        ("TARGA", "TGA", ""),
        ("TARGA_RAW", "TGA RAW", ""),
        ("OPEN_EXR", "Open EXR", "")
        ])
    des = "Codec for EXR file"
    exr_codec_export: EnumProperty(name="Codec", default="ZIP", description=des, items=[
        ("NONE", "NONE", ""),
        ("PXR24", "PXR24", ""),
        ("ZIP", "ZIP", ""),
        ("PIZ", "PIZ", ""),
        ("RLE", "RLE", ""),
        ("ZIPS", "ZIPS", ""),
        ("DWAA", "DWAA", "")
        ])
    des = "Quality for JPEG as it uses lossy compression. Same as native Blender setting"
    jpeg_quality: IntProperty(name = "JPEG quality", default = 90, description=des, min=0, max=100)

    #des="Name of the folder to create and save the bakes/mesh into. Created in the folder where you blend file is saved. NOTE: To maintain compatibility, only MS Windows acceptable characters will be used"
    #save_external_folder: StringProperty(name="Save folder name", description=des, default="SimpleBake_Bakes", maxlen=20)
    des = "Apply colour space settings (exposure, gamma etc.) from current scene when saving the diffuse image externally. Only available if you are exporting baked images. Will be ignored if exporting to EXR files as these don't support colour management"
    apply_col_man_to_col: BoolProperty(name="Export diffuse with col management settings", default = False, description=des)
    des = "Apply colour space settings (exposure, gamma etc.) from current scene when saving the image externally. Only available if you are exporting baked images. Not available if you have Cycles bake mode set to Normal.  Will be ignored if exporting to EXR files as these don't support colour management"
    export_cycles_col_space: BoolProperty(name="Export with col management settings", default = True, description=des)
    #des="Append date and time to folder name. If you turn this off there is a risk that you will accidentally overwrite bakes you did before if you forget to change the folder name"
    #folder_date_time: BoolProperty(name="Append date and time to folder", description=des, default=True)
    des="Run baked images through the compositor. Your blend file must be saved, and you must be exporting your bakes"
    rundenoise: BoolProperty(name="Denoise", description=des, default=False)
    des = "Apply modifiers to object on export of the mesh"
    apply_mods_on_mesh_export: BoolProperty(name="Apply object modifiers", description=des, default=True)
    des = "Use the 'Apply Transformation' option when exporting"
    apply_transformation: BoolProperty(name="Apply transformation", description=des, default=False)
    des = ("Filepath to export to. NOTE: Blender uses '//' to denote the folder that your Blend file is saved (e.g. '//SimpleBake_Bakes/').\
        However, you can also type a full path if you prefer. Either will work.")

    if bpy.app.version >= (4, 5, 0):
        export_path: StringProperty(subtype="DIR_PATH", description=des, default="//SimpleBake_Bakes", options={'PATH_SUPPORTS_BLEND_RELATIVE'})
    else:
        export_path: StringProperty(subtype="DIR_PATH", description=des, default="//SimpleBake_Bakes")

    des="Keep baked images internal within Blender after exporting"
    keep_internal_after_export: BoolProperty(name="Keep internal images after export", description=des, default=True, update=keep_internal_after_export_update)
    
    des="Enter the name of an existing export preset to use that for mesh export"
    export_mesh_preset_name: EnumProperty(name = "Use export preset", items=get_presets_dropdown, description=des, default=0)

    # des="Enter the name of an existing OBJ export preset to use that for mesh export"
    # obj_preset_name: EnumProperty(name = "OBJ Export Preset", items=get_obj_presets_dropdown, description=des, default=0)
    # des="Enter the name of an existing FBX export preset to use that for mesh export"
    # fbx_preset_name: EnumProperty(name = "FBX Export Preset", items=get_fbx_presets_dropdown, description=des, default=0)
    # des="Enter the name of an existing GLTF export preset to use that for mesh export"
    # gltf_preset_name: EnumProperty(name = "GLTF Export Preset", items=get_gltf_presets_dropdown, description=des, default=0)
    
    des="Format of the exported mesh"
    export_format: EnumProperty(name="Export format", default="fbx", description=des, items=[
        ("fbx", "FBX", ""),
        ("obj", "OBJ", ""),
        ("gltf", "GLTF", ""),
        ("dae", "DAE", "")
        ])
    
    #Advanced object selection list
    des="When turned on, you will bake the objects added to the bake list. When turned off, you will bake objects selected in the viewport"
    objects_list: CollectionProperty(type = ZZ_ObjectListItem)
    objects_list_index: IntProperty(name = "Index for bake objects list", default = 0, update=objects_list_index_update)
    
    #Background baking
    bgbake: EnumProperty(name="Background Bake", default="fg", items=[
    ("fg", "Foreground", "Perform baking in the foreground. Blender will lock up until baking is complete"),
    ("bg", "Background", "Perform baking in the background, leaving you free to continue to work in Blender while the baking is being carried out")
    ], update=bgbake_update)
    des="Name to help you identify the background bake task. This can be anything, and is only to help keep track of multiple background bake tasks. The name will show in the list below."
    bgbake_name: StringProperty(name="Background bake task name", description=des) 
    
    
    #Misc
    memLimit: EnumProperty(name="GPU Memory Limit", default="4096", 
    description="Limit memory usage by limiting render tile size. More memory means faster bake times, but it is possible to exceed the capabilities of your computer which will lead to a crash or slow bake times", items=[
        ("512", "Ultra Low", "Ultra Low memory usage (max 512 tile size)"),
        ("1024", "Low", "Low memory usage (max 1024 tile size)"),
        ("2048", "Medium", "Medium memory usage (max 2048 tile size)"),
        ("4096", "Normal", "Normal memory usage, for a reasonably modern computer (max 4096 tile size)"),
        ("Off", "No Limit", "Don't limit memory usage (tile size matches render image size)")
        ])
    des="Name to apply to these bakes (is incorporated into the bakes file name, provided you have included this in the image format string - see addon preferences). NOTE: To maintain compatibility, only MS Windows acceptable characters will be used"
    batch_name: StringProperty(name="Batch name", description=des, default="Bake1", update=batch_name_update)
    des="Create the glTF settings node group"
    create_glTF_node: BoolProperty(name="Create glTF settings", description=des, default=False)
    glTF_selection: EnumProperty(name="glTF selection", default=SBConstants.AO, 
    description="Which map should be plugged into the glTF settings node", items=[
        (SBConstants.AO, SBConstants.AO, "Use ambient occlusion"),
        (SBConstants.LIGHTMAP, SBConstants.LIGHTMAP, "Use lightmap")
        ])
    des="PBR bakes are done at 2 samples by default (as they are baked as emission and noise should not be possible). However, sample count needs to be boosted for materials containing Bevel or AO nodes. If those nodes are detected in your material(s), this count is used"
    boosted_sample_count: IntProperty(name="Boosted sample count (AO and Bevel)", description=des, default=50)
    des="Usually, normal maps are treated as a special case. Regardless of your other settings, they are ALWAYS 32 bit floats internally and 16/32 bit external exports (maximum for chosen file type). Enabling this option turns off that special treatment. Normal maps will follow the same rules as other textures, and be affected by the \"All internal 32bit float\" and \"All exports 16 bit\" options"
    no_force_32bit_normals: BoolProperty(name="Don't force high bit-depth normal maps", default=False, description=des)
    
    
    #Advanced functions
    des="Text to search for"
    findreplace_find: StringProperty(name="Find", default="", description=des)
    des="Text to find"
    findreplace_replace: StringProperty(name="Replace", default="", description=des)
    des="Type of data on which to do the find and replace"
    findreplace_type: EnumProperty(name="Data type", default="image",
    description=des, items=[
        ("image", "Images", ""),
        ("object", "Objects", ""),
        ("material", "Materials", "")
        ])
    des="Limit the find and replace operation to objects/materials/images created by SimpleBake"
    limit_findandreplace_to_sb: BoolProperty("Limit", default=False, description=des)

    #Presets
    des="List of global presets"
    presets_list: CollectionProperty(type=PresetItem, name="Presets", description="Presets")
    presets_list_index: IntProperty(name = "Index for bake presets list", default = 0, update=presets_list_update)
    des = "Name to save this preset under"
    preset_name: StringProperty(name="Name: ", description=des, default="Preset Name", maxlen=64)
    des="Clear the bake object list when loading a preset. Any bake objects list stored in the preset will be applied instead"
    preset_load_clear_obj: BoolProperty(name="Replace bake objects list with preset", description=des, default=True)

    des="List of local presets"
    local_presets_list: CollectionProperty(type=PresetItem, name="Local Presets", description="Local Presets")
    local_presets_list_index: IntProperty(name = "Index for local bake presets list", default = 0, update=local_presets_list_update)
    des = "Name to save this preset under"
    local_preset_name: StringProperty(name="Name: ", description=des, default="Preset Name", maxlen=64)
    
    #Show/Hide
    showtips: BoolProperty(name="", default=False)
    des = "Show SimpleBake presets"
    presets_show: BoolProperty(name="", description=des, default=False, update=presets_show_update)
    des = "Show bake objects"
    bake_objects_show: BoolProperty(name="", description=des, default=False, update=bake_objects_show_update)
    des = "Show PBR settings"
    pbr_settings_show: BoolProperty(name="", description=des, default=False)
    des = "Show AOV settings"
    aov_settings_show: BoolProperty(name="", description=des, default=False)
    des = "Show CyclesBake settings"
    cyclesbake_settings_show: BoolProperty(name="", description=des, default=False)
    des = "Show Specials settings"
    specials_show: BoolProperty(name="", description=des, default=False)
    des = "Show Texture settings"
    textures_show: BoolProperty(name="", description=des, default=False, update=textures_show_update)
    des = "Show Export settings"
    export_show: BoolProperty(name="", description=des, default=False)
    des = "Show UV settings"
    uv_show: BoolProperty(name="", description=des, default=False)
    des = "Show Other settings"
    other_show: BoolProperty(name="", description=des, default=False)
    des = "Show Channel Packing settings"
    channelpacking_show: BoolProperty(name="", description=des, default=False)
    des = "Show Admin Settings"
    admin_settings_show: BoolProperty(name="", description=des, default=False)
    des = "Show status of currently running background bakes"
    bg_status_show: BoolProperty(name="BG Bakes Status", description=des, default=True)
    des = "Show advanced UV packing options"
    uv_advanced_packing_show: BoolProperty(name="Advanced UV packing options", description=des, default=False)
    
    #Behind the scenes
    first_texture_show: BoolProperty(name="", description=des, default=True)
    
    #Channel packing
    des = "Bake type to use for the Red channel of the channel packed image"
    cptex_R: EnumProperty(items=get_selected_bakes_dropdown, description=des)
    des = "Bake type to use for the Greeb channel of the channel packed image"
    cptex_G: EnumProperty(items=get_selected_bakes_dropdown, description=des)
    des = "Bake type to use for the Blue channel of the channel packed image"
    cptex_B: EnumProperty(items=get_selected_bakes_dropdown, description=des)
    des = "Bake type to use for the Alpha channel of the channel packed image"
    cptex_A: EnumProperty(items=get_selected_bakes_dropdown, description=des)
    cp_name: StringProperty(name="Name: ", default="PackedTex", maxlen=30, description=des)
    des="List of Channel Packed Textures"
    cp_list: CollectionProperty(type=CPTexItem, name="CP Textures", description="CP Textures")
    cp_list_index: IntProperty(name = "Index for CP Textures list", default = 0, update=cp_list_index_update)
    des = "Codec for EXR file"
    exr_codec_cpts: EnumProperty(name="Codec", default="ZIP", description=des, items=[
        ("NONE", "NONE", ""),
        ("PXR24", "PXR24", ""),
        ("ZIP", "ZIP", ""),
        ("PIZ", "PIZ", ""),
        ("RLE", "RLE", ""),
        ("ZIPS", "ZIPS", ""),
        ("DWAA", "DWAA", "")
        ])
    des="PNG compression to use when saving the channel packed image"
    png_compression: IntProperty(default=15, description=des, min=0, max=100)
    
    des = "File format for channel pack image"
    channelpackfileformat: EnumProperty(name="Export File Format for Channel Packing",
    description=des, items=get_cpt_format_dropdown)

    des=("Delete bakes (internal and external) after the packed texture has been created in the external file system. Unavailable if you are also using the Copy "
    "Objects and Apply Bakes option or the Apply Bakes to Original Objects option, as in both cases you need the individual textures for the new materials")
    del_cptex_components: BoolProperty(name="Delete bakes after channel pack", description=des, default=False)

    des="Repeat the bake process between the specified frames of the scene, creating an images sequence. Make sure that you have the frame number as part of the image format string\
    in the SimpleBake addon preferences"
    bake_sequence: BoolProperty(name="Image sequence", default=False, description=des)
    des="The first frame of the image sequence"
    bake_sequence_start_frame: IntProperty(name="Start", default = 1, description = des, min = 0)
    des="The first frame of the image sequence"
    bake_sequence_end_frame: IntProperty(name="End", description = des)

    highlight_col: FloatVectorProperty(
        name="Col",
        subtype='COLOR',
        min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0),
        description="Choose an RGB color",
        size=3  # Only allow 3 elements: R, G, B
    )

    texture_bg_col: FloatVectorProperty(
        name="Col",
        subtype='COLOR',
        min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        description="Choose an RGB color",
        size=4
    )

    aov_items: bpy.props.CollectionProperty(type=ZZ_AOVItem)


    #Internal
    #is_baking: BoolProperty(default=False)
    t = Path(tempfile.TemporaryDirectory().name).as_posix()
    bgbake_temp_dir: StringProperty(default=t)
    total_bake_images_number: IntProperty()
    current_bake_image_number: IntProperty(default=0)
    base_folder_override: StringProperty(default = "")
    fg_status_message: StringProperty()
    percent_complete: IntProperty()
    testing: StringProperty(maxlen=0)
    #bake_done: BoolProperty(default=False)
    highlight_on: BoolProperty(default=False)
    suppress_report: BoolProperty(default=False)
    fake_background: BoolProperty(default=False)
    try:
        l = getpass.getuser()
        safe_context_check: StringProperty(default=l)
    except:
        safe_context_check: StringProperty(default="")
        
    #just_updated: BoolProperty()

classes = ([
        ZZ_ObjectListItem,
        ZZ_SimpleBakeUVItem,
        PresetItem,
        CPTexItem,
        ZZ_AOVItem,
        ZZ_SimpleBakePropGroup
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
    #Register property group
    bpy.types.Scene.SimpleBake_Props = bpy.props.PointerProperty(type=ZZ_SimpleBakePropGroup)

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)

