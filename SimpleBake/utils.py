import bpy
from bpy.types import Operator, Macro
from bpy.props import StringProperty, BoolProperty
from bpy.utils import register_class, unregister_class
import sys
from pathlib import Path
import base64
import mathutils
import tempfile
import os
import numpy as np


suppress_for_preset_load = False
_disable_impossible_running = False

def get_sb_prefs(context=None):
    from .ui.preferences import get_sb_prefs as _get_prefs
    return _get_prefs(context)

def blender_refresh():

    return True
    # print_message(context, "Blender refresh")
    # bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    # for area in context.screen.areas:
    #     area.tag_redraw()
    # context.view_layer.update()
    # context.view_layer.depsgraph.update()


#Takes a path object
def can_write_to_location(dir_path):
    #First check if the folder already exists or not
    if not os.path.exists(str(dir_path)):
        #Find the first parent that does exist, see if we can write there
        last = ""
        while not os.path.exists(str(dir_path)):
            dir_path = dir_path.parent

            if str(dir_path) == last:
                break
            last = str(dir_path)

    test_file_path = dir_path / "test_file.tmp"

    try:
        # Attempt to create a temporary file in the directory
        with open(str(test_file_path), 'w') as temp_file:
            temp_file.write("Test")
        # If successful, remove the test file
        os.remove(str(test_file_path))
        return True
    except PermissionError:
        # Permission denied
        return False
    except Exception as e:
        # Other exceptions could be handled differently if needed
        print(f"An error occurred: {e}")
        return False



def disable_impossible(context):
    global suppress_for_preset_load, _disable_impossible_running
    if _disable_impossible_running:
        return
    _disable_impossible_running = True
    try:
        sbp = context.scene.SimpleBake_Props
        suppress_for_preset_load = True

        #Start with a refresh of the objects list
        bpy.ops.simplebake.refresh_bake_object_list()
        #And AOVs
        bpy.ops.simplebake.refresh_aov_list()
        #And UVs
        bpy.ops.simplebake.sync_uv_list()

        if bpy.app.version >= (4,0,0):
            sbp.selected_transrough = False
            sbp.selected_ssscol = False

        if not sbp.save_bakes_external:
            sbp.rundenoise = False
            sbp.rough_glossy_switch = SBConstants.PBR_ROUGHNESS
            sbp.ccrough_glossy_switch = SBConstants.PBR_CLEARCOAT_ROUGH
            sbp.normal_format_switch = SBConstants.NORMAL_OPENGL
            sbp.multiply_diffuse_ao = "purediffuse"
            sbp.do_aa = False
            sbp.save_obj_external = False

        for cpt in sbp.cp_list:
            if "png_compression" not in cpt:
                cpt.png_compression = 15

        #if sbp.fbx_preset_name == "":
            #sbp.fbx_preset_name = "None"

        if sbp.multiply_diffuse_ao == "diffusexao" and sbp.global_mode == SBConstants.PBR:
            sbp.selected_ao = True

        if sbp.s2a_opmode == "decals":
            sbp.multiply_diffuse_ao = "purediffuse"

        if not sbp.keep_internal_after_export:
            sbp.copy_and_apply = False

        if sbp.tex_per_mat and (sbp.selected_s2a or sbp.cycles_s2a):
            sbp.tex_per_mat = False

        if sbp.tex_per_mat and sbp.expand_mat_uvs:
            sbp.new_uv_option = True
        if sbp.tex_per_mat and not sbp.expand_mat_uvs:
            sbp.new_uv_option = False

        if not sbp.merged_bake or not (sbp.export_mesh_individual_or_combined == "combined"):
            sbp.merge_export_obj = False

        if not sbp.merged_bake:
            sbp.join_objs_to_proxy = False

    finally:
        suppress_for_preset_load = False
        _disable_impossible_running = False


def get_bake_objects(context):
    sbp = context.scene.SimpleBake_Props
    #Work out our object selection
    objects = []

    if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
        from .bake_operators.auto_match_operators import SimpleBake_OT_AutoMatch_Operation as amo
        #objects = [context.scene.objects[i] for i in list(amo.hl_matches.keys())]
        objects = list(amo.hl_matches.keys())

    elif sbp.selected_s2a: #Standard S2A bake or Decals
        objects = [sbp.targetobj.name] if sbp.targetobj != None else []

    elif sbp.cycles_s2a: #Standard S2A bake
        objects = [sbp.targetobj_cycles.name] if sbp.targetobj_cycles != None else []

    else:
        objects = [i.obj_point.name for i in sbp.objects_list]

    return objects



#active_tiles is sorted list of UDIM numbers (1001, 1002 etc.)
#total_tiles is highest tile index (e.g. 11 if the highest numbered active tile is 1011)
def get_udim_tiles(context, object_name, threshold=0.001):
    import numpy as np

    obj = context.scene.objects.get(object_name)
    if not obj or not hasattr(obj.data, 'uv_layers') or not obj.data.uv_layers:
        return {"active_tiles": [], "total_tiles": 0, "bbox_tiles": 0}

    uv_layer = obj.data.uv_layers.active
    if uv_layer is None:
        return {"active_tiles": [], "total_tiles": 0, "bbox_tiles": 0}

    n = len(uv_layer.data)
    if n == 0:
        return {"active_tiles": [], "total_tiles": 0, "bbox_tiles": 0}

    buf = np.empty(n * 2, dtype=np.float64)
    uv_layer.data.foreach_get("uv", buf)
    uvs = buf.reshape(-1, 2)

    u = uvs[:, 0].copy()
    v = uvs[:, 1].copy()

    # Snap UV coordinates that sit very close to the upper edge of a tile back
    # into that tile, to avoid a vertex at e.g. v=0.9999 being counted as tile 1.
    frac_u = u % 1.0
    frac_v = v % 1.0
    u[frac_u > 1.0 - threshold] -= threshold
    v[frac_v > 1.0 - threshold] -= threshold

    # Subtract a tiny epsilon before flooring so that vertices sitting exactly
    # on an integer boundary (e.g. v=1.0, where 1.0 % 1.0 == 0.0) snap to the
    # tile below rather than the tile above.
    tu = np.floor(u - 1e-9).astype(np.int32)
    tv = np.floor(v - 1e-9).astype(np.int32)

    mask = (tu >= 0) & (tu <= 9) & (tv >= 0) & (tv <= 9)
    tile_nums = 1001 + tu[mask] + 10 * tv[mask]

    import math
    u_extent = math.ceil(float(np.max(u))) - math.floor(float(np.min(u)))
    v_extent = math.ceil(float(np.max(v))) - math.floor(float(np.min(v)))
    bbox_tiles = max(1, u_extent) * max(1, v_extent)

    if tile_nums.size == 0:
        return {"active_tiles": [], "total_tiles": 0, "bbox_tiles": bbox_tiles}

    udim_tiles = set(np.unique(tile_nums).tolist())

    return {
        "active_tiles": sorted(udim_tiles),
        "total_tiles": max(udim_tiles) - 1000,
        "bbox_tiles": bbox_tiles
    }

# def get_max_udim_tiles_from_bake_objects(context):
#     sbp = context.scene.SimpleBake_Props
#     objs = [i.name for i in sbp.objects_list]
#
#     max = 0
#
#     for obj_name in objs:
#         try:
#             d = get_udim_tiles(context, obj_name)
#             if len(d["active_tiles"]) > max:
#                 max = len(d["active_tiles"])
#         except:
#             pass
#
#     return max

# --- UDIM tile cache -----------------------------------------------------------
# Keyed by object name. Dirty set contains names needing recompute.
_udim_tile_cache: dict = {}
_udim_dirty_objects: set = set()


def invalidate_udim_cache(object_names=None):
    """Mark objects as needing recompute. Pass None to invalidate everything."""
    global _udim_dirty_objects, _udim_tile_cache
    if object_names is None:
        _udim_tile_cache.clear()
        _udim_dirty_objects.clear()
    else:
        for name in object_names:
            _udim_dirty_objects.add(name)


@bpy.app.handlers.persistent
def _sb_udim_depsgraph_handler(scene, depsgraph):
    for update in depsgraph.updates:
        if not update.is_updated_geometry:
            continue
        id_data = update.id
        if isinstance(id_data, bpy.types.Object) and id_data.type == 'MESH':
            # Topology change on the object itself
            _udim_dirty_objects.add(id_data.name)
        elif isinstance(id_data, bpy.types.Mesh):
            # UV edits come through as mesh data-block updates —
            # find all objects that use this mesh and dirty them
            for obj in scene.objects:
                if obj.type == 'MESH' and obj.data == id_data:
                    _udim_dirty_objects.add(obj.name)


def get_cached_udim_tiles(context, object_name, threshold=0.001):
    global _udim_tile_cache, _udim_dirty_objects
    if object_name in _udim_dirty_objects or object_name not in _udim_tile_cache:
        #Cache result from the "real" method
        _udim_tile_cache[object_name] = get_udim_tiles(context, object_name, threshold)
        #Now clean
        _udim_dirty_objects.discard(object_name)
    return _udim_tile_cache[object_name]


# ------------------------------------------------------------------------------




def find_closest_obj(context, object_name, max_distance=0.5):

    ref_obj = context.scene.objects.get(object_name)
    if not ref_obj:
        raise ValueError(f"No object found with the name '{object_name}'")

    closest_mesh = None
    closest_distance = float('inf')

    for obj in context.scene.objects:
        if obj.type == 'MESH' and obj != ref_obj and "SB_replaced_orig_name" not in obj:
            distance = (ref_obj.location - obj.location).length
            if distance < closest_distance:
                closest_distance = distance
                closest_mesh = obj

    return closest_mesh if closest_distance <= max_distance else None





class SBConstants:
    
    #Constants
    PBR = "PBR"
    PBRS2A = "PBR StoA"
    PBRS2A_AUTOMATCH = "PBR StoA AutoMatch"
    PBRS2A_DECALS = "PBR StoA Decals"
    CYCLESBAKE = "CyclesBake"
    CYCLESBAKE_S2A = "CyclesBake S2A"
    CYCLESBAKES2A_AUTOMATCH = "CyclesBake S2A Auto"
    SPECIALS = "Specials"
    SPECIALS_PBR_TARGET_ONLY = "specials_pbr_targetonly"
    SPECIALS_CYCLES_TARGET_ONLY = "specials_cycles_targetonly"
    PBRAOVS = "AOV"

    
    #PBR Names
    PBR_DIFFUSE = "Diffuse"
    PBR_METAL = "Metalness"
    PBR_SSS = "SSS"
    PBR_SSS_SCALE = "SSS Scale"
    PBR_SSSCOL = "SSS Colour"
    PBR_ROUGHNESS = "Roughness"
    PBR_GLOSSY = "Glossiness"
    PBR_NORMAL = "Normal"
    PBR_TRANSMISSION = "Transmission"
    PBR_TRANSMISSION_ROUGH = "Transmission Roughness"
    PBR_CLEARCOAT = "Clearcoat"
    PBR_CLEARCOAT_ROUGH = "Clearcoat Roughness"
    PBR_CLEARCOAT_GLOSS = "Clearcoat Glossiness"
    PBR_EMISSION = "Emission"
    PBR_EMISSION_STRENGTH = "Emission Strength"
    PBR_SPECULAR = "Specular"
    PBR_ALPHA = "Alpha"
    PBR_BUMP = "Bump"
    PBR_DISPLACEMENT = "Displacement"
    
    ALL_PBR_MODES = ([PBR_DIFFUSE, PBR_METAL, PBR_SSS,PBR_SSS_SCALE, PBR_SSSCOL, PBR_ROUGHNESS, PBR_GLOSSY,
                      PBR_NORMAL, PBR_TRANSMISSION, PBR_TRANSMISSION_ROUGH, PBR_CLEARCOAT,
                      PBR_CLEARCOAT_ROUGH, PBR_CLEARCOAT_GLOSS, PBR_EMISSION, PBR_EMISSION_STRENGTH, PBR_SPECULAR, PBR_ALPHA, PBR_BUMP, PBR_DISPLACEMENT])
    
    #Specials names
    THICKNESS = "Thickness"
    AO = "Ambient Occlusion"
    CURVATURE = "Curvature"
    COLOURID = "Colour ID"
    VERTEXCOL = "Vertex Colour"
    LIGHTMAP = "Lightmap"
    
    ALL_SPECIALS = ([THICKNESS, AO, CURVATURE,COLOURID, VERTEXCOL, LIGHTMAP])
    COMP_DENOISE_SPECIALS = ([THICKNESS, AO, LIGHTMAP])
    COMP_NODENOISE_SPECIALS = ([CURVATURE, VERTEXCOL, COLOURID])
    
    #UVs
    NEWUV_SMART_INDIVIDUAL = "SmartUVProject_Individual"
    NEWUV_SMART_ATLAS = "SmartUVProject_Atlas"
    NEWUV_COMBINE_EXISTING = "CombineExisting"
    
    #Normals
    NORMAL_OPENGL = "OpenGL"
    NORMAL_DIRECTX = "DirectX"

    @classmethod
    def get_socket_names(cls):

        v = bpy.app.version

        if v >= (4,0,0):
            return {
                cls.PBR_DIFFUSE: "Base Color",
                cls.PBR_METAL: "Metallic",
                cls.PBR_SSS: "Subsurface Weight",
                cls.PBR_SSS_SCALE: "Subsurface Scale",
                cls.PBR_SSSCOL: None,
                cls.PBR_ROUGHNESS: "Roughness",
                cls.PBR_GLOSSY: "Roughness",
                cls.PBR_NORMAL: "Normal",
                cls.PBR_TRANSMISSION: "Transmission Weight",
                cls.PBR_TRANSMISSION_ROUGH: None,
                cls.PBR_CLEARCOAT: "Coat Weight",
                cls.PBR_CLEARCOAT_ROUGH: "Coat Roughness",
                cls.PBR_CLEARCOAT_GLOSS: "Coat Roughness",
                cls.PBR_EMISSION: "Emission Color",
                cls.PBR_EMISSION_STRENGTH: "Emission Strength",
                cls.PBR_SPECULAR: "Specular IOR Level",
                cls.PBR_ALPHA: "Alpha"
            }

        else:

            #Principled socket names
            return {
                cls.PBR_DIFFUSE: "Base Color",
                cls.PBR_METAL: "Metallic",
                cls.PBR_SSS: "Subsurface",
                cls.PBR_SSS_SCALE: "Subsurface Scale",
                cls.PBR_SSSCOL: "Subsurface Color",
                cls.PBR_ROUGHNESS: "Roughness",
                cls.PBR_GLOSSY: "Roughness",
                cls.PBR_NORMAL: "Normal",
                cls.PBR_TRANSMISSION: "Transmission",
                cls.PBR_TRANSMISSION_ROUGH: "Transmission Roughness",
                cls.PBR_CLEARCOAT: "Clearcoat",
                cls.PBR_CLEARCOAT_ROUGH: "Clearcoat Roughness",
                cls.PBR_CLEARCOAT_GLOSS: "Clearcoat Glossiness",
                cls.PBR_EMISSION: "Emission",
                cls.PBR_EMISSION_STRENGTH: "Emission Strength",
                cls.PBR_SPECULAR: "Specular",
                cls.PBR_ALPHA: "Alpha"
            }

def get_texture_channels(context, tex):
    sbp = context.scene.SimpleBake_Props

    if sbp.global_mode in [SBConstants.CYCLESBAKE, SBConstants.CYCLESBAKE_S2A]:
        return "RGB"
    elif tex in [SBConstants.PBR_DIFFUSE, SBConstants.PBR_SSSCOL, SBConstants.PBR_EMISSION, SBConstants.PBR_NORMAL, SBConstants.COLOURID, SBConstants.VERTEXCOL, SBConstants.LIGHTMAP]:
        return "RGB"
    elif SBConstants.PBRAOVS in tex:
        num = int(tex.replace(f"{SBConstants.PBRAOVS}_", ""))
        aov = [i for i in sbp.aov_items if i.aov_number == num]
        assert len(aov)>0, "Unable to find matching AOV"
        aov = aov[0]
        if aov.aov_type == "C":
            return "RGB"
        else:
            return "RGB" if sbp.bw_to_rgb else "BW"

    else:
        return "RGB" if sbp.bw_to_rgb else "BW"

def object_list_to_names_list(context):
    sbp = context.scene.SimpleBake_Props
    names = sbp.objects_list.items()
    names = [n[0] for n in names]
    
    return names

def get_base_folder_patho(context):
    sbp = context.scene.SimpleBake_Props
    if "--background" in sys.argv or sbp.fake_background:
        base_folder = Path(sbp.base_folder_override)
    else:
        base_folder = Path(bpy.data.filepath).parent
        
    return base_folder


def force_to_object_mode(context):
    if context.active_object == None:
        context.view_layer.objects.active = context.view_layer.objects[0] #Pick arbitary
    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        
# def check_for_safe_context_class(context):
#     sbp = context.scene.SimpleBake_Props
#     t = []
#     #t.append(base64.b64decode("bGV3aXM=").decode("utf-8"))
#     if sbp.safe_context_check in t:
#         print_message(context, "Warning - Safe context class check failed. This is not fatal. Continuing")
#         return False
#     else:
#         return True
#
#     return True

# def select_selected_to_active(context, selected_objs, active_obj):
#     bpy.ops.object.select_all(action="DESELECT")
#
#     for obj in selected_objs:
#         obj.select_set(state=True)
#     active_obj.select_set(state=True)
#     context.view_layer.objects.active = active_obj

def select_only_these(context, objs):
    #When running an image sequence, this sometimes gets called with an empty list and I don't know why
    if len(objs) < 1:
        return False
    #bpy.ops.object.select_all(action="DESELECT")
    [o.select_set(state=False) for o in context.scene.objects]
    for obj in objs:
        obj.select_set(state=True)
    context.view_layer.objects.active = objs[0] #arbitary

def select_only_this(context, obj):
    #bpy.ops.object.select_all(action="DESELECT")
    [o.select_set(state=False) for o in context.scene.objects]
    obj.select_set(state=True)
    context.view_layer.objects.active = obj

def pbr_selections_to_list(context):
    sbp = context.scene.SimpleBake_Props
    
    selectedbakes = []
    selectedbakes.append(SBConstants.PBR_DIFFUSE) if sbp.selected_col else False
    selectedbakes.append(SBConstants.PBR_METAL) if sbp.selected_metal else False
    selectedbakes.append(SBConstants.PBR_ROUGHNESS) if sbp.selected_rough and sbp.rough_glossy_switch==SBConstants.PBR_ROUGHNESS else False
    selectedbakes.append(SBConstants.PBR_GLOSSY) if sbp.selected_rough and sbp.rough_glossy_switch==SBConstants.PBR_GLOSSY else False
    selectedbakes.append(SBConstants.PBR_NORMAL) if sbp.selected_normal else False
    selectedbakes.append(SBConstants.PBR_TRANSMISSION) if sbp.selected_trans else False
    selectedbakes.append(SBConstants.PBR_TRANSMISSION_ROUGH) if sbp.selected_transrough else False
    selectedbakes.append(SBConstants.PBR_CLEARCOAT) if sbp.selected_clearcoat else False
    selectedbakes.append(SBConstants.PBR_CLEARCOAT_ROUGH) if sbp.selected_clearcoat_rough and sbp.ccrough_glossy_switch==SBConstants.PBR_CLEARCOAT_ROUGH else False
    selectedbakes.append(SBConstants.PBR_CLEARCOAT_GLOSS) if sbp.selected_clearcoat_rough and sbp.ccrough_glossy_switch==SBConstants.PBR_CLEARCOAT_GLOSS else False
    selectedbakes.append(SBConstants.PBR_EMISSION) if sbp.selected_emission else False
    selectedbakes.append(SBConstants.PBR_EMISSION_STRENGTH) if sbp.selected_emission_strength else False
    selectedbakes.append(SBConstants.PBR_SPECULAR) if sbp.selected_specular else False
    selectedbakes.append(SBConstants.PBR_ALPHA) if sbp.selected_alpha else False
    selectedbakes.append(SBConstants.PBR_SSS) if sbp.selected_sss else False
    selectedbakes.append(SBConstants.PBR_SSS_SCALE) if sbp.selected_sss_scale else False
    selectedbakes.append(SBConstants.PBR_SSSCOL) if sbp.selected_ssscol else False
    selectedbakes.append(SBConstants.PBR_BUMP) if sbp.selected_bump else False
    selectedbakes.append(SBConstants.PBR_DISPLACEMENT) if sbp.selected_displacement else False

    for aov in sbp.aov_items:
        if aov.enabled:
            selectedbakes.append(SBConstants.PBRAOVS + f"_{aov.aov_number}")

    return selectedbakes

def specials_selection_to_list(context):
    sbp = context.scene.SimpleBake_Props
    selected_specials = []
    selected_specials.append(SBConstants.THICKNESS) if sbp.selected_thickness else False
    selected_specials.append(SBConstants.COLOURID) if sbp.selected_col_mats else False
    selected_specials.append(SBConstants.VERTEXCOL) if sbp.selected_col_vertex else False
    selected_specials.append(SBConstants.CURVATURE) if sbp.selected_curvature else False                    
    selected_specials.append(SBConstants.LIGHTMAP) if sbp.selected_lightmap else False
    selected_specials.append(SBConstants.AO) if sbp.selected_ao else False
                             
    return selected_specials

def blender_default_colorspace(float_buffer: bool, col: bool):
    try:
        cs_items = bpy.types.Image.bl_rna.properties['colorspace_settings'].fixed_type.bl_rna.properties['name'].enum_items
        cs_names = [cs.identifier for cs in cs_items]
    except Exception:
        cs_names = []

    if not cs_names:
        return (0, "sRGB")

    srgb_idx = 0
    non_color_idx = 0
    for idx, name in enumerate(cs_names):
        name_lower = name.lower()
        if "srgb" in name_lower and srgb_idx == 0:
            srgb_idx = idx
        if ("non-color" in name_lower or "non_color" in name_lower or "raw" in name_lower) and non_color_idx == 0:
            non_color_idx = idx

    if float_buffer or not col:
        idx = non_color_idx if non_color_idx < len(cs_names) else 0
    else:
        idx = srgb_idx if srgb_idx < len(cs_names) else 0

    return (idx, cs_names[idx])

def get_cs_list(self, context):

    cs_items = [(cs.identifier,cs.identifier,"") for cs in bpy.types.Image.bl_rna.properties['colorspace_settings'].fixed_type.bl_rna.properties['name'].enum_items]
    return cs_items

def clean_file_name(filename):
    keepcharacters = (' ','.','_','~',"-", "[", "]")
    return "".join(c for c in filename if c.isalnum() or c in keepcharacters)#.rstrip()

def transfer_tags(old_img, new_img):
    
    tags= ([
        "SB_bake_object",
        "SB_global_mode",
        "SB_this_bake",
        "SB_merged_bake",
        "SB_merged_bake_name",
        "SB_bake_operation_id",
        "SB_float_buffer",
        "SB_scaled",
        "SB_exported_list"
        ])
    
    for tag in tags:
        if tag in old_img: new_img[tag] = old_img[tag]
    
    return True
    
class SimpleBake_OT_Halt(Operator):
    bl_idname = "simplebake.halt"
    bl_label = ""
 
    def execute(self, context):
        
        raise Exception
        return {'FINISHED'}

def show_message_box(context, messageitems_list, title, icon = 'INFO'):


    message=""
    for li in messageitems_list:
        message+=f"{li}|"

    bpy.ops.simplebake.show_message_box('INVOKE_DEFAULT', message=message, centre=True, icon=icon)

    # def draw(self, context):
    #     for m in messageitems_list:
    #         self.layout.label(text=m)
    # context.window_manager.popup_menu(draw, title = title, icon = icon)
    
    return True

class SimpleBake_OT_Show_Message_Box(Operator):
    bl_idname = "simplebake.show_message_box"
    bl_label = ""

    message: StringProperty()
    icon: StringProperty(default="INFO")
    centre: BoolProperty(default=False)

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        self.restored = False
        if self.centre:
            self.orig_x = event.mouse_x
            self.orig_y = event.mouse_y

            w = int(context.window.width/2)
            h = int(context.window.height/2)
            h = h + (20*len(self.message.split("|")))
            context.window.cursor_warp(w, h)

        longest = 0
        for li in self.message.split("|"):
            longest = len(li) if (len(li)>longest) else longest
        width = longest*6 if (longest*6)>=400 else 400

        return context.window_manager.invoke_props_dialog(self, width = width)

    def draw(self, context):
        self.layout.label(text="SIMPLEBAKE", icon=self.icon)
        message_list = self.message.split("|")
        for li in message_list:
            row=self.layout.row()
            row.scale_y = 0.8
            row.alignment = 'LEFT'
            row.label(text=li)
        if not self.restored and self.centre:
            context.window.cursor_warp(self.orig_x, self.orig_y)
            self.restored = True
                             
def find_3d_viewport(context=None, screen=None):
    if context == None:
        context = bpy.context
    if screen == None:
        screen = bpy.context.window.screen

    found = []
    # Iterate through the areas in the current screen
    for area in screen.areas:
        # Check if the area is a 3D viewport
        if area.type == 'VIEW_3D':
            # Optionally, you can access the space data of the area
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    found.append(space)
    return found



def is_blend_saved():
    path = bpy.data.filepath
    if(path=="/" or path==""):
        return False
    else:
        return True

def is_all_black_or_transparent(img: bpy.types.Image, tol=1e-6):
    if not img.has_data:
        img.update()

    # Blender exposes pixels as RGBA floats in [0..1]; length = w*h*4
    px = np.asarray(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    rgb = px[:, :3]
    a   = px[:, 3]

    all_black       = np.all(np.abs(rgb) <= tol)        # R=G=B≈0 everywhere
    all_transparent = np.all(a <= tol)                  # A≈0 everywhere
    return all_black, all_transparent


conflicting_addons = []#"ZenUV"]

classes = ([
    SimpleBake_OT_Show_Message_Box,
    #SimpleBake_OT_Print_Message,
    SimpleBake_OT_Halt
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

    if _sb_udim_depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sb_udim_depsgraph_handler)

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)

    if _sb_udim_depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sb_udim_depsgraph_handler)
