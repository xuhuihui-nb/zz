# Smart Extrude (Traditional Chinese Version) - Blender add-on
# Copyright (C) 2023-2025 Interior Blender
# SPDX-License-Identifier: GPL-3.0-or-later


import bpy
import bmesh
import math
import time
import mathutils
import gpu
import os
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from typing import Optional, Tuple, Dict, Set

# =============================================================================
# CONSTANTS
# =============================================================================

ADDON_NAME = "Smart Extrude"
ADDON_PACKAGE = __package__ or "Smart Extrude"

# Modifier and vertex group names
MODIFIER_NAME = "TempSmartExtrude"
DATA_CLEAN_MODIFIER = "TempDataClean"

# Vertex group names
VG_TEMP_SELECT = "TempSelect"
VG_ALIGN_POINT = "AlignPoint"
VG_SPLIT_AND_MERGE = "SplitAndMerge"
VG_CLEAN_MESH = "CleanMesh"
VG_CLEAR_MESH = "ClearMesh"
VG_CLEAR_EDGE = "ClearEdge"
VG_DEL_MESH = "DelMesh"

VERTEX_GROUPS = [
    VG_TEMP_SELECT,
    VG_ALIGN_POINT,
    VG_SPLIT_AND_MERGE,
    VG_CLEAN_MESH,
    VG_CLEAR_MESH,
    VG_CLEAR_EDGE,
    VG_DEL_MESH,
]

# Geometry Nodes socket names
SOCKET_DISTANCE = "Socket_2"
SOCKET_INDIVIDUAL = "Socket_5"
SOCKET_FREE_ALIGN = "Socket_6"
SOCKET_UNEVEN = "Socket_8"
SOCKET_FLIP = "Socket_9"
SOCKET_PREVIEW = "Socket_10"
SOCKET_SMART_MODE = "Socket_16"
SOCKET_AUTO_TOPOLOGY_INV = "Socket_17"
SOCKET_REMOVE_EDGE_INV = "Socket_18"
SOCKET_DIRECTION_ARROW = "Socket_20"
SOCKET_ONLY_MANIFOLD = "Socket_22"
SOCKET_HIDE_NON_EXTRUDED_MESH = "Socket_23"
SOCKET_SNAP_TO_BOTTOM = "Socket_25"
SOCKET_TOPOLOGY_MAX_VERTEX = "Socket_28"

# Node group names
NODE_GROUP_SMART_EXTRUDE = "smartextrude"
NODE_GROUP_DATA_CLEAN = "DataClean"

# Blend file names by version
BLEND_FILES = {
    "4.3": {"normal": "se2.blend", "fast": "se2Fast.blend"},
    "4.5": {"normal": "se.blend", "fast": "seFast.blend"},
}

NODE_GROUPS_4_3_4_4 = ["smartextrude", "DataClean"]
NODE_GROUPS_4_5_PLUS = ["smartextrude", "DataClean"]

# Preview material names
MATERIAL_PREVIEW = "Preview"
MATERIAL_PREVIEW_PLUS = "Preview+"
MATERIAL_PREVIEW_MINUS = "Preview-"

# Performance settings
MOUSE_UPDATE_INTERVAL = 0.01
CURSOR_WRAP_THRESHOLD = 10
CACHE_PROJECTION_MIN_LENGTH = 1e-6

# Unit conversion factors
UNIT_FACTORS_METRIC = {
    "KILOMETERS": 1000,
    "METERS": 1,
    "CENTIMETERS": 0.01,
    "MILLIMETERS": 0.001,
    "MICROMETERS": 1e-6,
}

UNIT_FACTORS_IMPERIAL = {
    "MILES": 1609.344,
    "FEET": 0.3048,
    "INCHES": 0.0254,
    "THOU": 2.54e-5,
}

# Auto-merge settings
AUTO_MERGE_THRESHOLD = 0.00015

# Topology settings
TRI_TO_QUAD_ANGLE_FACE = 40
TRI_TO_QUAD_ANGLE_SHAPE = 90
LIMITED_DISSOLVE_ANGLE = 0.1

# Input modes
INPUT_MODE_MOUSE = "MOUSE"
INPUT_MODE_SNAP = "SNAP"
INPUT_MODE_KEYBOARD = "KEYBOARD"

# Extrude modes
MODE_SMART = "SMART"
MODE_ALONG_NORMAL = "ALONG_NORMAL"
MODE_INDIVIDUAL = "INDIVIDUAL"

# Sensitivity settings
SENSITIVITY_NORMAL = 0.01
SENSITIVITY_FINE = 0.001
SENSITIVITY_FINE_MULTIPLIER = 0.1

# =============================================================================
# UTILS
# =============================================================================

_prefs_cache = {}
_prefs_cache_frame = -1



def _get_all_mod_sockets(modifier):
    props = {}
    if not modifier or not getattr(modifier, "node_group", None):
        return props
    ng = modifier.node_group
    if hasattr(ng, "interface"):
        for item in ng.interface.items_tree:
            if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == "INPUT":
                k = item.identifier
                props[k] = _get_mod_socket(modifier, k)
    elif hasattr(ng, "inputs"):
        for inp in ng.inputs:
            k = getattr(inp, "identifier", None)
            if k:
                props[k] = _get_mod_socket(modifier, k)
    else:
        try:
            for k in modifier.keys():
                if k != "_RNA_UI":
                    props[k] = _get_mod_socket(modifier, k)
        except Exception:
            pass
    return props

def _get_mod_socket(modifier, key, default=None):
    if modifier is None:
        return default
    try:
        return modifier[key]
    except Exception:
        pass
    try:
        props = getattr(modifier, "properties", None)
        if props and hasattr(props, "inputs"):
            inps = props.inputs
            if hasattr(inps, key):
                sock = getattr(inps, key)
                if hasattr(sock, "value"):
                    return sock.value
            try:
                return inps[key]
            except Exception:
                pass
    except Exception:
        pass
    return default

def _set_mod_socket(modifier, key, value):
    if modifier is None:
        return False
    try:
        modifier[key] = value
        return True
    except Exception:
        pass
    try:
        props = getattr(modifier, "properties", None)
        if props and hasattr(props, "inputs"):
            inps = props.inputs
            if hasattr(inps, key):
                sock = getattr(inps, key)
                if hasattr(sock, "value"):
                    sock.value = value
                    return True
            try:
                inps[key] = value
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def get_addon_preferences(context=None, use_cache=True):
    global _prefs_cache, _prefs_cache_frame
    if context is None:
        context = bpy.context
    
    current_frame = context.scene.frame_current if (context and getattr(context, "scene", None) and hasattr(context.scene, "frame_current")) else -1
    if use_cache and _prefs_cache_frame == current_frame and _prefs_cache:
        for key, p in _prefs_cache.items():
            if p is not None:
                return p
    
    try:
        pkg = __name__.split('.')[0]
        addon = context.preferences.addons.get(pkg)
        if not addon:
            for name, a in context.preferences.addons.items():
                if hasattr(a, "preferences") and a.preferences and (hasattr(a.preferences, "use_group_normal_mapping") or hasattr(a.preferences, "addon_folder_path")):
                    addon = a
                    pkg = name
                    break
        if addon and hasattr(addon, "preferences"):
            prefs = addon.preferences
            if use_cache:
                _prefs_cache[pkg] = prefs
                _prefs_cache_frame = current_frame
            return prefs
    except Exception:
        pass
    return None

def validate_mesh_object(obj, report_func=None) -> bool:
    if not obj:
        if report_func:
            report_func({"WARNING"}, "没有活动对象")
        return False
    if obj.type != "MESH":
        if report_func:
            report_func({"WARNING"}, f"活动对象不是网格 (类型: {obj.type})")
        return False
    return True

# =============================================================================
# CORE LOGIC (Resource Loading)
# =============================================================================

# Assume SE folder is in the same directory as this file
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

def _get_blend_file_path(use_fast: bool = False) -> str:
    if bpy.app.version < (4, 3, 0):
        raise RuntimeError("Smart Extrude 需要 Blender 4.3.0 或更高版本")
    elif bpy.app.version < (4, 5, 0):
        blend_file = BLEND_FILES["4.3"]["fast" if use_fast else "normal"]
    else:
        blend_file = BLEND_FILES["4.5"]["fast" if use_fast else "normal"]
    
    blend_path = os.path.join(_ADDON_DIR, "SE", blend_file)
    if not os.path.exists(blend_path):
        # Fallback for development structure if needed
        pass
    if not os.path.exists(blend_path):
        raise FileNotFoundError(f"找不到檔案 {blend_file} 於 {blend_path}")
    
    return blend_path

def _apply_xray_colors() -> None:
    prefs = get_addon_preferences()
    if not prefs:
        return
    try:
        materials = {
            MATERIAL_PREVIEW: getattr(prefs, "xray_color_object", (0.8, 0.8, 0.8, 0.35)),
            MATERIAL_PREVIEW_PLUS: getattr(prefs, "xray_color_plus", (0.45, 1.0, 0.45, 1.0)),
            MATERIAL_PREVIEW_MINUS: getattr(prefs, "xray_color_minus", (1.0, 0.0, 0.0, 0.5)),
        }
        for mat_name, color in materials.items():
            mat = bpy.data.materials.get(mat_name)
            if mat:
                mat.diffuse_color = color
    except Exception:
        pass

def _load_node_groups() -> Tuple[Optional[bpy.types.NodeTree], Optional[bpy.types.NodeTree]]:
    node_group = bpy.data.node_groups.get(NODE_GROUP_SMART_EXTRUDE)
    data_clean_group = bpy.data.node_groups.get(NODE_GROUP_DATA_CLEAN)
    if node_group and data_clean_group:
        return node_group, data_clean_group

    prefs = get_addon_preferences()
    use_fast = bool(prefs.preview_xray_mode) if prefs else False
    
    blend_path = _get_blend_file_path(use_fast)
    
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        to_load = []
        if NODE_GROUP_SMART_EXTRUDE in data_from.node_groups:
            to_load.append(NODE_GROUP_SMART_EXTRUDE)
        if NODE_GROUP_DATA_CLEAN in data_from.node_groups:
            to_load.append(NODE_GROUP_DATA_CLEAN)
        data_to.node_groups = to_load
    
    node_group = bpy.data.node_groups.get(NODE_GROUP_SMART_EXTRUDE)
    data_clean_group = bpy.data.node_groups.get(NODE_GROUP_DATA_CLEAN)
    
    if not node_group:
        raise RuntimeError(f"無法從 '{blend_path}' 載入 '{NODE_GROUP_SMART_EXTRUDE}'")

    _apply_xray_colors()
    return node_group, data_clean_group

def _ensure_vertex_groups(obj: bpy.types.Object) -> dict:
    created = {}
    for name in VERTEX_GROUPS:
        group = obj.vertex_groups.get(name)
        if not group:
            group = obj.vertex_groups.new(name=name)
        created[name] = group
    return created



def _purge_working_vertex_groups(obj: bpy.types.Object) -> None:
    for name in VERTEX_GROUPS:
        grp = obj.vertex_groups.get(name)
        if grp:
            try:
                obj.vertex_groups.remove(grp)
            except Exception:
                pass

# =============================================================================
# VERTEX EDGE EXTRUDE (Builtin Wrapper)
# =============================================================================

def _collect_transform_ids(wm):
    ids = set()
    try:
        for op in getattr(wm, "operators", []):
            try:
                if op.bl_idname.startswith("TRANSFORM_OT"):
                    ids.add(op.as_pointer())
            except Exception:
                pass
    except Exception:
        pass
    return ids

def _enable_face_orientation(context):
    overlays = []
    try:
        wm = context.window_manager
        for window in wm.windows:
            screen = window.screen
            if not screen: continue
            for area in screen.areas:
                if area.type != "VIEW_3D": continue
                space = area.spaces.active
                if not space: continue
                overlay = getattr(space, "overlay", None)
                if overlay is None: continue
                overlays.append((overlay, overlay.show_face_orientation))
                overlay.show_face_orientation = True
    except Exception:
        return []
    return overlays

def _restore_face_orientation(overlays):
    if not overlays: return
    for overlay, previous in overlays:
        try:
            overlay.show_face_orientation = previous
        except Exception:
            pass

def invoke_builtin_extrude(context, has_edges: bool, has_vertices: bool, force_vertex_mode: bool = False, edge_action: str = "EXTRUDE"):
    ts = context.tool_settings
    wm = context.window_manager
    original_threshold = ts.double_threshold
    pre_transform_ids = _collect_transform_ids(wm)

    scene = context.scene
    unit_scale = getattr(scene.unit_settings, "scale_length", 1.0) or 1.0
    target_threshold = 0.0001 / unit_scale if unit_scale else 0.0001

    ts.use_mesh_automerge = True
    if hasattr(ts, "use_mesh_automerge_and_split"):
        ts.use_mesh_automerge_and_split = True
    ts.double_threshold = target_threshold

    overlays_to_restore = []
    is_vertex_extrude = False
    use_vertex_mode = force_vertex_mode or (has_vertices and not has_edges)
    
    if has_edges and not use_vertex_mode and edge_action == "EXTRUDE":
         overlays_to_restore = _enable_face_orientation(context)

    try:
        if has_edges:
            if use_vertex_mode:
                op_call = bpy.ops.mesh.extrude_vertices_move
                is_vertex_extrude = True
            elif edge_action == "EXTRUDE":
                op_call = bpy.ops.mesh.extrude_edges_move
            else:
                op_call = bpy.ops.mesh.duplicate_move
        elif has_vertices:
            op_call = bpy.ops.mesh.extrude_vertices_move
            is_vertex_extrude = True
        else:
            op_call = bpy.ops.mesh.extrude_region_move

        op_call("INVOKE_DEFAULT")

    except Exception as e:
        print(f"Smart Extrude Error: {e}")
        _restore_face_orientation(overlays_to_restore)
        try:
            ts.use_mesh_automerge = False
            if hasattr(ts, "use_mesh_automerge_and_split"):
                ts.use_mesh_automerge_and_split = False
            ts.double_threshold = original_threshold
        except Exception:
            pass
        return {"CANCELLED"}

    post_transform_ids = _collect_transform_ids(wm)
    target_transform_ids = post_transform_ids - pre_transform_ids

    monitor_state = {
        "target_ids": target_transform_ids,
        "cleanup_attempts": 10,
        "finishing": False,
    }
    start_time = time.time()

    def restore_monitor():
        try:
            curr_wm = bpy.context.window_manager
            current_ids = _collect_transform_ids(curr_wm)

            if not monitor_state["target_ids"]:
                late_candidates = current_ids - pre_transform_ids
                if late_candidates:
                    monitor_state["target_ids"] = late_candidates

            elapsed = time.time() - start_time
            keep_waiting = False

            if not monitor_state["finishing"]:
                if elapsed > 10.0:
                    keep_waiting = False
                elif monitor_state["target_ids"]:
                    if current_ids & monitor_state["target_ids"]:
                        keep_waiting = True
                else:
                    if current_ids and elapsed < 2.0:
                        keep_waiting = True

            if keep_waiting:
                return 0.01

            monitor_state["finishing"] = True
            monitor_state["cleanup_attempts"] -= 1
            
            if monitor_state["cleanup_attempts"] == 9:
                 _restore_face_orientation(overlays_to_restore)

            try:
                ts_restore = bpy.context.tool_settings
                ts_restore.use_mesh_automerge = False
                if hasattr(ts_restore, "use_mesh_automerge_and_split"):
                    ts_restore.use_mesh_automerge_and_split = False
                ts_restore.double_threshold = original_threshold
            except Exception:
                pass

            if is_vertex_extrude and monitor_state["cleanup_attempts"] == 9:
                try:
                    bpy.ops.mesh.select_all(action="SELECT")
                    ts2 = bpy.context.tool_settings
                    ts2.mesh_select_mode = (False, False, True)
                    ts2.mesh_select_mode = (True, False, False)
                    bpy.ops.mesh.select_all(action="INVERT")
                except Exception:
                    pass

            if monitor_state["cleanup_attempts"] > 0:
                return 0.02

            return None

        except Exception:
            _restore_face_orientation(overlays_to_restore)
            try:
                bpy.context.tool_settings.use_mesh_automerge = False
            except Exception:
                pass
            return None

    bpy.app.timers.register(restore_monitor, first_interval=0.01)
    return {"CANCELLED"}


# =============================================================================
# OPERATORS
# =============================================================================

def _draw_callback_3d(op, context):
    if not op or not context.object: return
    if op.mode != "SMART": return
    if getattr(op, "_free_mode", False): return

    try:
        obj = context.object
        matrix = obj.matrix_world
        center_world = matrix @ op._avg_center_local
        normal_world = (matrix.to_3x3() @ op._avg_normal_local).normalized()
        
        extent = 10000.0 
        p1 = center_world - normal_world * extent
        p2 = center_world + normal_world * extent
        
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": [p1, p2]})
        shader.bind()
        shader.uniform_float("color", (0.2, 0.6, 1.0, 1.0))
        batch.draw(shader)
    except Exception:
        pass

def _draw_callback_2d(op, context):
    if not op or getattr(op, "_free_mode", False): return

    try:
        prefs = get_addon_preferences(context)
        font_size = getattr(prefs, "shortcut_text_size", 20)
        
        def get_key_string(prop_name, default):
            try:
                key = getattr(prefs, prop_name, default).upper()
                ctrl = getattr(prefs, prop_name.replace("_key", "_ctrl"), False)
                shift = getattr(prefs, prop_name.replace("_key", "_shift"), False)
                alt = getattr(prefs, prop_name.replace("_key", "_alt"), False)
                parts = []
                if ctrl: parts.append("Ctrl")
                if shift: parts.append("Shift")
                if alt: parts.append("Alt")
                parts.append(key)
                return "+".join(parts)
            except Exception:
                return default

        confirm_msg = "确认: Shift+左键/Shift+Enter" if getattr(op, "_ui_edit_mode", False) else "确认: 左键/Enter"

        shortcuts = [
            f"吸附: {get_key_string('snap_key', 'B')}",
            f"翻转: {get_key_string('flip_key', 'F')}",
            f"不均匀: {get_key_string('uneven_key', 'D')}",
            f"预览: {get_key_string('preview_key', 'Ctrl+Y')}",
            f"仅流形: {get_key_string('only_manifold_key', 'M')}",
            f"底吸: {get_key_string('snap_bottom_key', 'Ctrl+B')}",
            f"模式切换: {get_key_string('mode_cycle_key', 'TAB')}",
            "UI 编辑: Shift+Enter",
            confirm_msg,
            "取消: 右键/Esc"
        ]

        font_id = 0
        blf.size(font_id, font_size)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        
        x = 95
        y = 30
        line_height = font_size * 1.5

        for i, text in enumerate(reversed(shortcuts)):
            blf.position(font_id, x, y + i * line_height, 0)
            blf.draw(font_id, text)
            
    except Exception:
        pass

class SmartExtrudeOperator(bpy.types.Operator):
    """
    主要智慧挤出操作 (简体中文版)。
    支持模式：智慧挤出、沿法线、个别面。
    """
    bl_idname = "mesh.smart_extrude"
    bl_label = "智慧挤出"
    bl_options = {"UNDO"}

    mode: bpy.props.EnumProperty(
        name="模式",
        items=(
            (MODE_SMART, "智慧挤出", ""),
            (MODE_ALONG_NORMAL, "沿法线智慧挤出", ""),
            (MODE_INDIVIDUAL, "个别面智慧挤出", ""),
        ),
        default=MODE_SMART,
        options={"HIDDEN"},
    )

    _mod_name = MODIFIER_NAME
    _await_transform_done = False
    _await_kind = None
    _finalized = False

    def _ensure_edit_mesh(self, context):
        if context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")

    def _enable_face_orientation_preview(self, context):
        self._face_orientation_overlays = []
        try:
            prefs = get_addon_preferences(context)
            if not getattr(prefs, "face_orientation_preview", True):
                return
        except Exception:
            return

        overlays = []
        wm = context.window_manager
        for window in wm.windows:
            screen = window.screen
            if not screen: continue
            for area in screen.areas:
                if area.type != "VIEW_3D": continue
                space = area.spaces.active
                if not space: continue
                overlay = getattr(space, "overlay", None)
                if overlay is None: continue
                overlays.append((overlay, overlay.show_face_orientation))
                overlay.show_face_orientation = True
        self._face_orientation_overlays = overlays

    def _restore_face_orientation_preview(self):
        overlays = getattr(self, "_face_orientation_overlays", None)
        if not overlays: return
        for overlay, previous in overlays:
            try:
                overlay.show_face_orientation = previous
            except Exception:
                pass
        self._face_orientation_overlays = []

    def _invoke_builtin_extrude(self, context, has_edges, has_vertices, force_vertex_mode=False):
        edge_action = "EXTRUDE"
        try:
            prefs = get_addon_preferences(context)
            edge_action = getattr(prefs, "edge_action", "EXTRUDE")
        except Exception:
            pass
        return invoke_builtin_extrude(context, has_edges, has_vertices, force_vertex_mode, edge_action)

    def _setup_preflight(self, context) -> tuple:
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"WARNING"}, "未选择网格对象！")
            return None, None

        self._original_automerge_global = context.tool_settings.use_mesh_automerge
        context.tool_settings.use_mesh_automerge = False

        bpy.ops.object.mode_set(mode="OBJECT")
        _purge_working_vertex_groups(obj)
        _ensure_vertex_groups(obj)
        bpy.ops.object.mode_set(mode="EDIT")

        self._orig_mat_slots = len(obj.material_slots)

        bm = bmesh.from_edit_mesh(obj.data)
        if not any(f.select for f in bm.faces):
            self.report({"WARNING"}, "未选择任何面！")
            return None, None

        layer = bm.faces.layers.int.get("OrigFace") or bm.faces.layers.int.new("OrigFace")
        mat_layer = bm.faces.layers.int.get("OrigMat") or bm.faces.layers.int.new("OrigMat")
        for f in bm.faces:
            if f.select:
                f[layer] = 1
                f[mat_layer] = f.material_index
            else:
                f[layer] = 0
                f[mat_layer] = -1
        bmesh.update_edit_mesh(obj.data)

        bpy.ops.mesh.duplicate()
        
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.faces.layers.int.get("OrigFace")
        for f in bm.faces:
            if f.select:
                f[layer] = 0
        bmesh.update_edit_mesh(obj.data)

        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v.index for v in bm.verts if v.select]
        sel_faces = [f for f in bm.faces if f.select]
        
        centers = mathutils.Vector((0.0, 0.0, 0.0))
        normal_accum = mathutils.Vector((0.0, 0.0, 0.0))
        
        if sel_faces:
            for f in sel_faces:
                centers += f.calc_center_median()
                normal_accum += f.normal
            centers /= len(sel_faces)
            self._avg_center_local = centers.copy()
            self._avg_normal_local = (normal_accum.normalized() if normal_accum.length > 0 else mathutils.Vector((0, 0, 1)))
        else:
            self._avg_center_local = mathutils.Vector((0, 0, 0))
            self._avg_normal_local = mathutils.Vector((0, 0, 1))

        min_proj = 0.0
        max_proj = 0.0
        for v in bm.verts:
            if v.select:
                proj = (v.co - self._avg_center_local).dot(self._avg_normal_local)
                min_proj = min(min_proj, proj)
                max_proj = max(max_proj, proj)
        self._max_extent_local = max_proj - min_proj

        bpy.ops.object.mode_set(mode="OBJECT")
        if "TempSelect" in obj.vertex_groups:
            obj.vertex_groups.remove(obj.vertex_groups["TempSelect"])
        temp_group = obj.vertex_groups.new(name="TempSelect")
        if selected_verts:
            temp_group.add(selected_verts, 1.0, "REPLACE")
        bpy.ops.object.mode_set(mode="EDIT")

        bpy.ops.object.mode_set(mode="EDIT")

        try:
            node_group, data_clean = _load_node_groups()
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return None, None

        bpy.ops.object.mode_set(mode="OBJECT")
        existing = obj.modifiers.get(self._mod_name)
        if existing:
            obj.modifiers.remove(existing)
        mod = obj.modifiers.new(name=self._mod_name, type="NODES")
        mod.node_group = node_group
        mod.show_in_editmode = True
        mod.show_viewport = True
        try:
            bpy.ops.object.modifier_move_to_index(modifier=self._mod_name, index=0)
        except Exception:
            pass
        bpy.ops.object.mode_set(mode="EDIT")

        return mod, data_clean

    def _init_sockets_by_mode(self, modifier: bpy.types.Modifier):
        _set_mod_socket(modifier, "Socket_2", _get_mod_socket(modifier, "Socket_2", 0.0))
        _set_mod_socket(modifier, "Socket_5", False)
        _set_mod_socket(modifier, "Socket_6", False)
        _set_mod_socket(modifier, "Socket_8", False)
        _set_mod_socket(modifier, "Socket_9", False)
        _set_mod_socket(modifier, "Socket_10", True)
        _set_mod_socket(modifier, "Socket_16", False)
        _set_mod_socket(modifier, "Socket_22", False)
        _set_mod_socket(modifier, "Socket_25", False)

        try:
            prefs = get_addon_preferences()
            default_auto_topology = bool(getattr(prefs, "default_auto_topology", True))
            _set_mod_socket(modifier, "Socket_17", not default_auto_topology)
            default_remove_extrude_edge = bool(getattr(prefs, "default_remove_extrude_edge", False))
            _set_mod_socket(modifier, "Socket_18", not default_remove_extrude_edge)
            _set_mod_socket(modifier, "Socket_23", bool(getattr(prefs, "hide_non_extruded_mesh", True)))

            try:
                _set_mod_socket(modifier, "Socket_28", max(0, int(getattr(prefs, "default_topology_max_vertex", 16))))
            except Exception:
                _set_mod_socket(modifier, "Socket_28", 16)

            use_group_normal = bool(getattr(prefs, "use_group_normal_mapping", True))
            if use_group_normal:
                _set_mod_socket(modifier, "Socket_20", bool(getattr(prefs, "direction_arrow", True)))
            else:
                _set_mod_socket(modifier, "Socket_20", False)
        except Exception:
            _set_mod_socket(modifier, "Socket_17", False)
            _set_mod_socket(modifier, "Socket_18", True)
            _set_mod_socket(modifier, "Socket_23", True)
            try:
                _set_mod_socket(modifier, "Socket_28", 16)
            except Exception:
                pass
            try:
                _set_mod_socket(modifier, "Socket_20", True)
            except Exception:
                pass

        if self.mode == "SMART":
            _set_mod_socket(modifier, "Socket_16", True)
        elif self.mode == "ALONG_NORMAL":
            pass
        elif self.mode == "INDIVIDUAL":
            if bpy.app.version >= (4, 5, 0):
                _set_mod_socket(modifier, "Socket_5", True)
            else:
                _set_mod_socket(modifier, "Socket_5", False)
                _set_mod_socket(modifier, "Socket_16", True)
                self.mode = "SMART"

    def _update_cursor(self, context):
        try:
            if self.mode in {"ALONG_NORMAL", "INDIVIDUAL"}:
                context.window.cursor_modal_set("SCROLL_Y")
            else:
                context.window.cursor_modal_set("DEFAULT")
        except Exception:
            pass

    def invoke(self, context, event):
        if hasattr(context.scene, "smart_extrude_mode"):
            self.mode = context.scene.smart_extrude_mode
        self._ensure_edit_mesh(context)
        obj = context.active_object
        if not validate_mesh_object(obj, self.report):
            return {"CANCELLED"}

        bm_check = bmesh.from_edit_mesh(obj.data)
        has_faces = any(f.select for f in bm_check.faces)
        has_edges = any(e.select for e in bm_check.edges)
        has_verts = any(v.select for v in bm_check.verts)
        if not has_faces and (has_edges or has_verts):
            ts = context.tool_settings
            select_mode = ts.mesh_select_mode[:]
            force_vertex_mode = bool(select_mode[0]) and not select_mode[1] and not select_mode[2]
            return self._invoke_builtin_extrude(context, has_edges, has_verts, force_vertex_mode=force_vertex_mode)

        self._is_open_mesh = False
        if has_faces:
            sel_faces_check = [f for f in bm_check.faces if f.select]
            islands = set(sel_faces_check)
            stack = list(sel_faces_check)
            while stack:
                curr = stack.pop()
                for e in curr.edges:
                    for lf in e.link_faces:
                        if lf not in islands:
                            islands.add(lf)
                            stack.append(lf)
                            
            has_boundary = any(e.is_boundary for f in islands for e in f.edges)
            if has_boundary:
                try:
                    first_normal = next(iter(islands)).normal
                    is_flat = all(abs(f.normal.dot(first_normal)) > 0.95 for f in islands)
                except Exception:
                    is_flat = False
                
                sel_edges_check = {e for f in sel_faces_check for e in f.edges}
                all_boundary = sel_edges_check and all(e.is_boundary for e in sel_edges_check)
                
                if all_boundary or is_flat:
                    self.mode = "ALONG_NORMAL"
                    self._is_open_mesh = True

        setup = self._setup_preflight(context)
        if not setup: return {"CANCELLED"}
        modifier, data_clean = setup
        if not modifier: return {"CANCELLED"}

        self._data_clean_group = data_clean
        self._init_sockets_by_mode(modifier)
        self._enable_face_orientation_preview(context)
        
        try:
            modifier["_operator_mode"] = self.mode
        except Exception:
            pass

        self._input_name = "Socket_2"
        try:
            _set_mod_socket(modifier, self._input_name, 0.0)
        except Exception:
            pass
        obj.data.update()

        self._initial_mouse_x = event.mouse_x if event else None
        self._initial_mouse_y = event.mouse_y if event else None
        self._current_value = 0.0
        self._initial_value = 0.0
        self._last_shift = False
        self._input_mode = "MOUSE"
        self._input_string = ""
        self._last_update_time = time.time()
        self._update_interval = 0.01
        self._timer = None
        self._free_mode = False
        self._await_transform_done = False
        self._await_kind = None
        self._finalized = False
        self._cache_valid = False

        self._status_text_timer = context.window_manager.event_timer_add(0.1, window=context.window)

        ts = context.tool_settings
        self._orig_use_snap = ts.use_snap
        self._orig_snap_elements = set(ts.snap_elements)
        self._orig_snap_target = ts.snap_target
        self._orig_select_mode = ts.mesh_select_mode[:]

        self._update_cursor(context)
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback_3d, (self, context), "WINDOW", "POST_VIEW"
        )
        self._draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback_2d, (self, context), "WINDOW", "POST_PIXEL"
        )

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _get_display_distance(self, context) -> str:
        current_dist = getattr(self, "_current_value", 0.0)
        dist_str = f"{current_dist:.3f}"
        try:
            unit_settings = context.scene.unit_settings
            system = unit_settings.system
            
            if system == 'NONE':
                dist_str = f"{current_dist:.3f}"
            else:
                scale = getattr(unit_settings, "scale_length", 1.0)
                length_unit = getattr(unit_settings, "length_unit", 'ADAPTIVE')
                
                # Check for specific unit override (Property Panel style)
                unit_suffix = ""
                unit_factor = 1.0
                
                # Manual map since to_string doesn't support forcing non-adaptive units well
                if length_unit == 'CENTIMETERS':
                    unit_suffix = "cm"
                    unit_factor = 100.0
                elif length_unit == 'METERS':
                    unit_suffix = "m"
                    unit_factor = 1.0
                elif length_unit == 'MILLIMETERS':
                    unit_suffix = "mm"
                    unit_factor = 1000.0
                elif length_unit == 'KILOMETERS':
                    unit_suffix = "km"
                    unit_factor = 0.001
                elif length_unit == 'FEET':
                    unit_suffix = "'"
                    unit_factor = 3.28084
                elif length_unit == 'INCHES':
                    unit_suffix = '"'
                    unit_factor = 39.3701
                    
                if unit_suffix:
                    # Calculate value in target unit (Meter value * factor)
                    # current_dist is in Blender Units (Scaled?)
                    # No, current_dist is in Blender Units.
                    # Real Meters = current_dist * scale
                    val_in_unit = (current_dist * scale) * unit_factor
                    dist_str = f"{val_in_unit:.3f} {unit_suffix}"
                else:
                    # Fallback to Blender's adaptive formatting
                    dist_str = bpy.utils.units.to_string(system, "LENGTH", current_dist * scale, precision=3)
        except Exception:
            pass
        return dist_str

    def _update_status_bar(self, context, modifier):
        def get_key_string(prop_name, default):
            try:
                prefs = get_addon_preferences(context)
                key = getattr(prefs, prop_name, default).upper()
                ctrl = getattr(prefs, prop_name.replace("_key", "_ctrl"), False)
                shift = getattr(prefs, prop_name.replace("_key", "_shift"), False)
                alt = getattr(prefs, prop_name.replace("_key", "_alt"), False)
                parts = []
                if ctrl: parts.append("Ctrl")
                if shift: parts.append("Shift")
                if alt: parts.append("Alt")
                parts.append(key)
                return "+".join(parts)
            except Exception:
                return default

        key_snap = get_key_string("snap_key", "B")
        key_flip = get_key_string("flip_key", "F") 
        key_uneven = get_key_string("uneven_key", "D")
        key_preview = get_key_string("preview_key", "Ctrl+Y")
        key_only_manifold = get_key_string("only_manifold_key", "M")
        key_snap_bottom = get_key_string("snap_bottom_key", "Ctrl+B")
        key_mode = get_key_string("mode_cycle_key", "TAB")
        key_ui_edit = "Shift+Enter"

        is_snap = self._input_mode == "SNAP"
        val_flip = bool(_get_mod_socket(modifier, "Socket_9", False))
        val_uneven = bool(_get_mod_socket(modifier, "Socket_8", False))
        val_preview = bool(_get_mod_socket(modifier, "Socket_10", True))
        val_only_manifold = bool(_get_mod_socket(modifier, "Socket_22", False))
        val_snap_bottom = bool(_get_mod_socket(modifier, "Socket_25", False))
        
        dist_str = self._get_display_distance(context)
        mode_str = self.mode
        if mode_str == "ALONG_NORMAL": mode_str = "法线"
        elif mode_str == "INDIVIDUAL": mode_str = "个别"
        else: mode_str = "智慧"

        ui_edit_str = "开启" if getattr(self, "_ui_edit_mode", False) else "关闭"

        if not getattr(self, "_free_mode", False):
            context.area.header_text_set(f"距离: {dist_str} | 模式: {mode_str}")

        confirm_msg = "确认: Shift+左键/Shift+Enter" if getattr(self, "_ui_edit_mode", False) else "确认: 左键/Enter"

        status_items = [
            f"距离: {dist_str}",
            f"模式({key_mode}): {mode_str}",
            f"吸附({key_snap}): {'开启' if is_snap else '关闭'}",
            f"翻转({key_flip}): {'开启' if val_flip else '关闭'}",
            f"不均匀({key_uneven}): {'开启' if val_uneven else '关闭'}",
            f"仅流形({key_only_manifold}): {'开启' if val_only_manifold else '关闭'}",
            f"底吸({key_snap_bottom}): {'开启' if val_snap_bottom else '关闭'}",
            f"预览({key_preview}): {'开启' if val_preview else '关闭'}",
            f"UI 编辑({key_ui_edit}): {ui_edit_str}",
            confirm_msg,
            "取消: 右键/Esc"
        ]
        context.workspace.status_text_set(" | ".join(status_items))

    def _clear_status_bar(self, context):
        context.workspace.status_text_set(None)
        context.area.header_text_set(None)
        if hasattr(self, "_status_text_timer") and self._status_text_timer:
            context.window_manager.event_timer_remove(self._status_text_timer)
            self._status_text_timer = None

    def execute(self, context):
        return self.invoke(context, None)

    def _apply_value(self, context, obj, modifier):
        try:
            _set_mod_socket(modifier, self._input_name, self._current_value)
        except TypeError:
            try:
                del modifier[self._input_name]
                _set_mod_socket(modifier, self._input_name, float(self._current_value))
            except Exception:
                pass
        except Exception:
            pass
        obj.data.update()
        if not getattr(self, "_free_mode", False):
            try:
                dist_str = self._get_display_distance(context)
                mode_str = self.mode
                if mode_str == "ALONG_NORMAL": mode_str = "法线"
                elif mode_str == "INDIVIDUAL": mode_str = "个别"
                else: mode_str = "智慧"
                context.area.header_text_set(f"距离: {dist_str} | 模式: {mode_str}")
            except Exception:
                pass
        try:
            context.area.tag_redraw()
        except Exception:
            pass

    def _enter_snap(self, context, obj, modifier):
        self._input_mode = "SNAP"
        bm = bmesh.from_edit_mesh(obj.data)
        self._temp_vert = bm.verts.new(self._avg_center_local)
        bm.verts.ensure_lookup_table()
        self._temp_vert_index = self._temp_vert.index
        for f in bm.faces: f.select = False
        for e in bm.edges: e.select = False
        for v in bm.verts: v.select = False
        self._temp_vert.select = True
        bmesh.update_edit_mesh(obj.data)
        ts = context.tool_settings
        self._orig_select_mode = ts.mesh_select_mode[:]
        ts.mesh_select_mode = (True, False, False)
        self._orig_use_snap = ts.use_snap
        ts.use_snap = True
        ts.snap_elements = {"VERTEX", "EDGE", "FACE", "EDGE_MIDPOINT"}
        self._orig_snap_target = ts.snap_target
        ts.snap_target = "CENTER"
        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        bpy.ops.transform.translate("INVOKE_DEFAULT")
        self._await_transform_done = True
        self._await_kind = "SNAP"

    def _exit_snap_commit(self, context, obj, modifier):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        temp_vert = bm.verts[self._temp_vert_index]
        vec_local = temp_vert.co - self._avg_center_local
        dist = vec_local.dot(self._avg_normal_local)
        try:
            if modifier and bool(_get_mod_socket(modifier, "Socket_9", False)):
                dist = -dist
        except Exception:
            pass
        if dist > 0:
            self._current_value = max(dist, self._max_extent_local)
        else:
            self._current_value = min(dist, -self._max_extent_local)
        self._apply_value(context, obj, modifier)
        bm.verts.remove(temp_vert)
        bmesh.update_edit_mesh(obj.data)
        self._restore_snap(context)
        self._input_mode = "MOUSE"

    def _restore_snap(self, context):
        ts = context.tool_settings
        ts.use_snap = self._orig_use_snap
        ts.snap_elements = self._orig_snap_elements
        ts.snap_target = self._orig_snap_target
        ts.mesh_select_mode = self._orig_select_mode
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def _cancel_snap(self, context, obj):
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            if hasattr(self, "_temp_vert_index") and 0 <= self._temp_vert_index < len(bm.verts):
                temp_vert = bm.verts[self._temp_vert_index]
                bm.verts.remove(temp_vert)
                bmesh.update_edit_mesh(obj.data)
        except Exception:
            pass
        self._restore_snap(context)
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
            if "TempSelect" in obj.vertex_groups:
                obj.vertex_groups.active_index = obj.vertex_groups["TempSelect"].index
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.vertex_group_select()
        except Exception:
            pass

    def _enter_free_align(self, context, obj, modifier):
        self._free_mode = True
        _set_mod_socket(modifier, "Socket_6", True)
        _set_mod_socket(modifier, "Socket_16", False)
        bpy.ops.object.mode_set(mode="OBJECT")
        align_name = "AlignPoint"
        if align_name in obj.vertex_groups:
            obj.vertex_groups.remove(obj.vertex_groups[align_name])
        align_group = obj.vertex_groups.new(name=align_name)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.object.mode_set(mode="OBJECT")
        if "TempSelect" in obj.vertex_groups:
            obj.vertex_groups.active_index = obj.vertex_groups["TempSelect"].index
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.object.vertex_group_select()
        bpy.ops.mesh.duplicate()
        bm = bmesh.from_edit_mesh(obj.data)
        align_indices = [v.index for v in bm.verts if v.select]
        bpy.ops.object.mode_set(mode="OBJECT")
        align_group.add(align_indices, 1.0, "REPLACE")
        bpy.ops.object.mode_set(mode="EDIT")
        context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.transform.translate("INVOKE_DEFAULT")
        self._await_transform_done = True
        self._await_kind = "FREE"

    def _is_transform_running(self, context):
        return False

    def _cleanup_align_group(self, obj):
        bpy.ops.object.mode_set(mode="EDIT")
        if "AlignPoint" in obj.vertex_groups:
            bpy.ops.object.mode_set(mode="OBJECT")
            obj.vertex_groups.active_index = obj.vertex_groups["AlignPoint"].index
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.vertex_group_select()
            bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        if "AlignPoint" in obj.vertex_groups:
            obj.vertex_groups.remove(obj.vertex_groups["AlignPoint"])
        bpy.ops.object.mode_set(mode="EDIT")

    def modal(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return {"CANCELLED"}
        modifier = obj.modifiers.get(self._mod_name)
        if not modifier and event.type not in {"RIGHTMOUSE", "ESC"}:
            self.report({"WARNING"}, "找不到修改器！")
            return {"CANCELLED"}

        def _get_hotkey_settings(base, default_key, default_ctrl=False, default_shift=False, default_alt=False):
            key = default_key
            ctrl = default_ctrl
            shift = default_shift
            alt = default_alt
            try:
                prefs = get_addon_preferences(context)
                key = (getattr(prefs, f"{base}_key", default_key) or default_key).upper()
                ctrl = getattr(prefs, f"{base}_ctrl", default_ctrl)
                shift = getattr(prefs, f"{base}_shift", default_shift)
                alt = getattr(prefs, f"{base}_alt", default_alt)
            except Exception:
                pass
            return key, ctrl, shift, alt

        def _matches_hotkey(event, key, ctrl, shift, alt):
            return (event.type == key and event.value == "PRESS" and 
                    event.ctrl == ctrl and event.shift == shift and event.alt == alt)

        if event.type == 'TIMER' and getattr(self, "_status_text_timer", None):
             self._update_status_bar(context, modifier)
             if not getattr(self, "_cursor_initialized", False):
                 self._update_cursor(context)
                 self._cursor_initialized = True

        if event.type == "F9" and event.value == "PRESS":
            try:
                bpy.context.window_manager.popup_menu(_f9_popup_draw, title="智慧挤出", icon="NONE")
            except Exception:
                pass
            return {"RUNNING_MODAL"}

        if self._free_mode:
            blocked_events = {
                "ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
                "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4", 
                "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
                "PERIOD", "NUMPAD_PERIOD", "MINUS", "NUMPAD_MINUS", 
                "BACK_SPACE", "RET", "NUMPAD_ENTER", "B", "TAB", "MOUSEMOVE"
            }
            if event.type in blocked_events:
                return {"RUNNING_MODAL"}

        is_shift_enter = (event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS" and event.shift)
        
        if is_shift_enter and not self._free_mode:
            if getattr(self, "_ui_edit_mode", False):
                if self._input_mode == "SNAP":
                    self._exit_snap_commit(context, obj, modifier)
                self._finish_and_cleanup(context, apply_now=True)
                return {"FINISHED"}
            else:
                self._ui_edit_mode = True
                self.report({"INFO"}, "UI 編輯模式：使用 Shift+左鍵 或 Shift+Enter 完成")
                return {"RUNNING_MODAL"}

        if getattr(self, "_ui_edit_mode", False):
            if event.type == "LEFTMOUSE" and event.value == "PRESS" and event.shift:
                if self._input_mode == "SNAP":
                    self._exit_snap_commit(context, obj, modifier)
                self._finish_and_cleanup(context, apply_now=True)
                return {"FINISHED"}

            if event.type in {"RIGHTMOUSE", "ESC"}:
                if self._input_mode == "SNAP":
                    self._cancel_snap(context, obj)
                self._cancel_and_cleanup(context)
                return {"CANCELLED"}
            
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._input_mode == "SNAP":
                self._cancel_snap(context, obj)
            self._cancel_and_cleanup(context)
            return {"CANCELLED"}

        if event.type == "MOUSEMOVE":
            region = context.region
            threshold = 10
            region_bottom = region.y
            region_top = region.y + region.height
            region_left = region.x
            region_right = region.x + region.width
            mouse_y = event.mouse_y
            mouse_x = event.mouse_x
            warped = False
            if self._initial_mouse_y is None:
                self._initial_mouse_y = mouse_y
                self._initial_value = self._current_value
            if self._initial_mouse_x is None:
                self._initial_mouse_x = mouse_x

            if mouse_y >= region_top - threshold:
                new_y = region_bottom + threshold
                context.window.cursor_warp(mouse_x, new_y)
                self._initial_mouse_y += new_y - mouse_y
                warped = True
            elif mouse_y <= region_bottom + threshold:
                new_y = region_top - threshold
                context.window.cursor_warp(mouse_x, new_y)
                self._initial_mouse_y += new_y - mouse_y
                warped = True

            try:
                stored_mode = _get_mod_socket(modifier, "_operator_mode", None)
                if stored_mode and stored_mode != self.mode:
                    self.mode = stored_mode
            except Exception:
                pass
                
            if self.mode == "SMART":
                try:
                    prefs = get_addon_preferences(context)
                    use_gn = bool(getattr(prefs, "use_group_normal_mapping", True))
                except Exception:
                    use_gn = True
                if use_gn:
                    if mouse_x >= region_right - threshold:
                        new_x = region_left + threshold
                        context.window.cursor_warp(new_x, event.mouse_y)
                        self._initial_mouse_x += new_x - mouse_x
                        warped = True
                    elif mouse_x <= region_left + threshold:
                        new_x = region_right - threshold
                        context.window.cursor_warp(new_x, event.mouse_y)
                        self._initial_mouse_x += new_x - mouse_x
                        warped = True

            if warped:
                return {"RUNNING_MODAL"}

            now = time.time()
            if now - self._last_update_time < self._update_interval:
                return {"RUNNING_MODAL"}
            if self._input_mode == "MOUSE":
                try:
                    stored_mode = _get_mod_socket(modifier, "_operator_mode", None)
                    if stored_mode and stored_mode != self.mode:
                        self.mode = stored_mode
                        self._cache_valid = False
                except Exception:
                    pass

                handled = False
                try:
                    if not self._cache_valid:
                        rv3d = context.region_data
                        self._cached_center_world = obj.matrix_world @ self._avg_center_local
                        try:
                            normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
                            self._cached_normal_world = (normal_matrix @ self._avg_normal_local).normalized()
                        except Exception:
                            self._cached_normal_world = (obj.matrix_world.to_3x3() @ self._avg_normal_local).normalized()

                        s0 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._cached_center_world)
                        s1 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._cached_center_world + self._cached_normal_world)
                        if s0 is not None and s1 is not None:
                            n = s1 - s0
                            n_len = n.length
                            if n_len > 1e-4:
                                self._cached_n_dir = n / n_len
                                self._cached_n_len = n_len
                                self._cache_valid = True

                    if self._cache_valid:
                        if event.shift != self._last_shift:
                            self._initial_mouse_x = event.mouse_x
                            self._initial_mouse_y = event.mouse_y
                            self._initial_value = self._current_value
                            self._last_shift = event.shift
                        delta_x = event.mouse_x - self._initial_mouse_x
                        delta_y = event.mouse_y - self._initial_mouse_y
                        delta_px = (delta_x * self._cached_n_dir.x + delta_y * self._cached_n_dir.y)
                        delta_units = delta_px / self._cached_n_len
                        if event.shift: delta_units *= 0.1
                        try:
                            if modifier and bool(_get_mod_socket(modifier, "Socket_9", False)):
                                delta_units = -delta_units
                        except Exception:
                            pass
                        self._current_value = self._initial_value + delta_units
                        self._apply_value(context, obj, modifier)
                        self._last_update_time = now
                        handled = True
                except Exception:
                    handled = False

                if not handled:
                    sensitivity = 0.001 if event.shift else 0.01
                    if event.shift != self._last_shift:
                        self._initial_mouse_x = event.mouse_x
                        self._initial_mouse_y = event.mouse_y
                        self._initial_value = self._current_value
                        self._last_shift = event.shift
                    delta = (event.mouse_y - self._initial_mouse_y) * sensitivity
                    self._current_value = self._initial_value + delta
                    self._apply_value(context, obj, modifier)

                self._last_update_time = now
                return {"RUNNING_MODAL"}

        if event.type == "TIMER" and self._input_mode == "SNAP":
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            temp_vert = bm.verts[self._temp_vert_index]
            vec_local = temp_vert.co - self._avg_center_local
            dist = vec_local.dot(self._avg_normal_local)
            try:
                if modifier and bool(_get_mod_socket(modifier, "Socket_9", False)):
                    dist = -dist
            except Exception:
                pass
            if dist > 0:
                dist = max(dist, self._max_extent_local)
            else:
                dist = min(dist, -self._max_extent_local)
            self._current_value = dist
            self._apply_value(context, obj, modifier)
            return {"RUNNING_MODAL"}

        snap_key = "B"
        snap_ctrl = False
        snap_shift = False
        snap_alt = False
        try:
            prefs = get_addon_preferences(context)
            snap_key = getattr(prefs, "snap_key", "B").upper() or "B"
            snap_ctrl = getattr(prefs, "snap_ctrl", False)
            snap_shift = getattr(prefs, "snap_shift", False)
            snap_alt = getattr(prefs, "snap_alt", False)
        except Exception:
            pass
        if (event.type == snap_key and event.value == "PRESS" and 
            event.ctrl == snap_ctrl and event.shift == snap_shift and event.alt == snap_alt):
            if self._input_mode != "SNAP":
                self._enter_snap(context, obj, modifier)
            else:
                self._exit_snap_commit(context, obj, modifier)
            return {"RUNNING_MODAL"}

        mode_key = "TAB"
        mode_ctrl = False
        mode_shift = False
        mode_alt = False
        try:
            prefs = get_addon_preferences(context)
            mode_key = (getattr(prefs, "mode_cycle_key", "TAB") or "TAB").upper()
            mode_ctrl = getattr(prefs, "mode_cycle_ctrl", False)
            mode_shift = getattr(prefs, "mode_cycle_shift", False)
            mode_alt = getattr(prefs, "mode_cycle_alt", False)
        except Exception:
            pass
        if (event.type == mode_key and event.value == "PRESS" and 
            event.ctrl == mode_ctrl and event.shift == mode_shift and event.alt == mode_alt):
            if not self._await_transform_done:
                mode_cycle = (MODE_SMART, MODE_ALONG_NORMAL, MODE_INDIVIDUAL)
                try:
                    idx = mode_cycle.index(self.mode)
                except ValueError:
                    idx = 0
                self.mode = mode_cycle[(idx + 1) % len(mode_cycle)]
                try:
                    self._init_sockets_by_mode(modifier)
                    modifier["_operator_mode"] = self.mode
                except Exception:
                    pass
                self._update_cursor(context)
            obj.data.update()
            return {"RUNNING_MODAL"}

        flip_key, flip_ctrl, flip_shift, flip_alt = _get_hotkey_settings("flip", "F")
        if _matches_hotkey(event, flip_key, flip_ctrl, flip_shift, flip_alt):
            _set_mod_socket(modifier, "Socket_9", not bool(_get_mod_socket(modifier, "Socket_9", False)))
            obj.data.update()
            return {"RUNNING_MODAL"}

        uneven_key, uneven_ctrl, uneven_shift, uneven_alt = _get_hotkey_settings("uneven", "D")
        if _matches_hotkey(event, uneven_key, uneven_ctrl, uneven_shift, uneven_alt):
            _set_mod_socket(modifier, "Socket_8", not bool(_get_mod_socket(modifier, "Socket_8", False)))
            obj.data.update()
            return {"RUNNING_MODAL"}

        preview_key, preview_ctrl, preview_shift, preview_alt = _get_hotkey_settings("preview", "Y", True)
        if _matches_hotkey(event, preview_key, preview_ctrl, preview_shift, preview_alt):
            _set_mod_socket(modifier, "Socket_10", not bool(_get_mod_socket(modifier, "Socket_10", True)))
            obj.data.update()
            return {"RUNNING_MODAL"}

        om_key, om_ctrl, om_shift, om_alt = _get_hotkey_settings("only_manifold", "M")
        if _matches_hotkey(event, om_key, om_ctrl, om_shift, om_alt):
            _set_mod_socket(modifier, "Socket_22", not bool(_get_mod_socket(modifier, "Socket_22", False)))
            obj.data.update()
            return {"RUNNING_MODAL"}

        sb_key, sb_ctrl, sb_shift, sb_alt = _get_hotkey_settings("snap_bottom", "B", True)
        if _matches_hotkey(event, sb_key, sb_ctrl, sb_shift, sb_alt):
            _set_mod_socket(modifier, "Socket_25", not bool(_get_mod_socket(modifier, "Socket_25", False)))
            obj.data.update()
            return {"RUNNING_MODAL"}

        if event.type in {
            "ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4", "NUMPAD_5", 
            "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9", "PERIOD", "NUMPAD_PERIOD", 
            "MINUS", "NUMPAD_MINUS"
        } and event.value == "PRESS":
            self._input_mode = "KEYBOARD"
            ch = event.unicode if event.unicode else ""
            if not ch:
                 # fallback map
                 if "ZERO" in event.type or "_0" in event.type: ch="0"
                 elif "ONE" in event.type or "_1" in event.type: ch="1"
                 elif "TWO" in event.type or "_2" in event.type: ch="2"
                 elif "THREE" in event.type or "_3" in event.type: ch="3"
                 elif "FOUR" in event.type or "_4" in event.type: ch="4"
                 elif "FIVE" in event.type or "_5" in event.type: ch="5"
                 elif "SIX" in event.type or "_6" in event.type: ch="6"
                 elif "SEVEN" in event.type or "_7" in event.type: ch="7"
                 elif "EIGHT" in event.type or "_8" in event.type: ch="8"
                 elif "NINE" in event.type or "_9" in event.type: ch="9"
                 elif "PERIOD" in event.type: ch="."
                 elif "MINUS" in event.type: ch="-"
            
            if ch:
                self._input_string += ch
                try:
                    unit_settings = context.scene.unit_settings
                    scale = getattr(unit_settings, "scale_length", 1.0)
                    system = unit_settings.system
                    length_unit = getattr(unit_settings, "length_unit", 'ADAPTIVE')

                    if system == 'NONE':
                        user_value = float(self._input_string)
                    else:
                        input_to_parse = self._input_string
                        # If input is purely numeric, assume the scene's length unit
                        # Check if any alpha char exists (except 'e' for scientific, but let's keep it simple)
                        # Actually to_value handles "10" as base unit (m). We want "10" as length_unit (e.g. cm)
                        
                        has_unit = False
                        # Simple check: if it ends with digit or dot, it likely has no unit
                        if input_to_parse and (input_to_parse[-1].isdigit() or input_to_parse[-1] == '.'):
                            has_unit = False
                        else:
                            # It might have a unit, or be incomplete. Let to_value decide.
                            # But if user typed "10", has_unit is False.
                            pass
                            
                        # If we suspect no unit, append the scene's unit if fixed
                        if not any(c.isalpha() or c in "'\"" for c in input_to_parse):
                             suffix_map = {
                                 'CENTIMETERS': 'cm',
                                 'METERS': 'm',
                                 'MILLIMETERS': 'mm',
                                 'KILOMETERS': 'km',
                                 'FEET': 'ft',
                                 'INCHES': 'in',
                                 'THOU': 'th',
                                 'MILES': 'mi'
                             }
                             if length_unit in suffix_map:
                                 input_to_parse += suffix_map[length_unit]

                        val_meters = bpy.utils.units.to_value(system, "LENGTH", input_to_parse)
                        user_value = val_meters / scale
                    
                    self._current_value = user_value
                    self._apply_value(context, obj, modifier)
                except Exception:
                    pass
            return {"RUNNING_MODAL"}

        if event.type == "BACK_SPACE" and event.value == "PRESS" and self._input_mode == "KEYBOARD":
            if self._input_string:
                self._input_string = self._input_string[:-1]
                if self._input_string:
                    try:
                        unit_settings = context.scene.unit_settings
                        scale = getattr(unit_settings, "scale_length", 1.0)
                        system = unit_settings.system
                        length_unit = getattr(unit_settings, "length_unit", 'ADAPTIVE')

                        if system == 'NONE':
                            self._current_value = float(self._input_string)
                        else:
                            input_to_parse = self._input_string
                            if not any(c.isalpha() or c in "'\"" for c in input_to_parse):
                                 suffix_map = {
                                     'CENTIMETERS': 'cm',
                                     'METERS': 'm',
                                     'MILLIMETERS': 'mm',
                                     'KILOMETERS': 'km',
                                     'FEET': 'ft',
                                     'INCHES': 'in',
                                     'THOU': 'th',
                                     'MILES': 'mi'
                                 }
                                 if length_unit in suffix_map:
                                     input_to_parse += suffix_map[length_unit]

                            val_meters = bpy.utils.units.to_value(system, "LENGTH", input_to_parse)
                            self._current_value = val_meters / scale

                        self._apply_value(context, obj, modifier)
                    except Exception:
                        pass
                else:
                    self._current_value = float(_get_mod_socket(modifier, self._input_name, 0.0))
                    self._apply_value(context, obj, modifier)
            return {"RUNNING_MODAL"}

        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self._enter_free_align(context, obj, modifier)
            return {"RUNNING_MODAL"}

        if (event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS" and event.shift and not self._free_mode):
            if getattr(self, "_ui_edit_mode", False):
                if self._input_mode == "SNAP":
                    self._exit_snap_commit(context, obj, modifier)
                self._finish_and_cleanup(context, apply_now=True)
                return {"FINISHED"}
            else:
                self._ui_edit_mode = True
                self.report({"INFO"}, "UI 編輯模式：使用 Shift+左鍵 或 Shift+Enter 完成")
                return {"RUNNING_MODAL"}

        if getattr(self, "_ui_edit_mode", False):
            if event.type == "LEFTMOUSE" and event.value == "PRESS" and event.shift:
                if self._input_mode == "SNAP":
                    self._exit_snap_commit(context, obj, modifier)
                self._finish_and_cleanup(context, apply_now=True)
                return {"FINISHED"}
            if event.type in {"RIGHTMOUSE", "ESC"}:
                if self._input_mode == "SNAP":
                    self._cancel_snap(context, obj)
                self._cancel_and_cleanup(context)
                return {"CANCELLED"}
            return {"PASS_THROUGH"}

        if event.type == "LEFTMOUSE":
            if self._await_transform_done:
                if event.value == "RELEASE":
                    if self._await_kind == "SNAP" and self._input_mode == "SNAP":
                        self._exit_snap_commit(context, obj, modifier)
                    self._finish_and_cleanup(context, apply_now=True)
                    self._finalized = True
                    return {"FINISHED"}
                return {"RUNNING_MODAL"}
            if event.value == "PRESS":
                if self._input_mode == "SNAP":
                    self._exit_snap_commit(context, obj, modifier)
                self._finish_and_cleanup(context, apply_now=True)
                return {"FINISHED"}

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._await_transform_done:
                return {"RUNNING_MODAL"}
            if self._input_mode == "SNAP":
                self._exit_snap_commit(context, obj, modifier)
            self._finish_and_cleanup(context, apply_now=True)
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def _apply_modifier_with_realize(self, context):
        obj = context.active_object
        mod = obj.modifiers.get(self._mod_name)
        if not mod: return
        
        original_group = mod.node_group
        temp_group = original_group.copy()
        temp_group.name = "TempRealizeExtrude"
        
        saved_props = _get_all_mod_sockets(mod)
        
        mod.node_group = temp_group
        
        for k, v in saved_props.items():
            _set_mod_socket(mod, k, v)
            
        if not getattr(self, "_is_open_mesh", False):
            try:
                _set_mod_socket(mod, "Socket_10", False)
            except Exception:
                pass
            
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.node_groups.remove(temp_group)

        data_clean = bpy.data.node_groups.get("DataClean") or getattr(self, "_data_clean_group", None)
        if data_clean:
            clean_mod = obj.modifiers.new(name="TempDataClean", type="NODES")
            clean_mod.node_group = data_clean
            bpy.ops.object.modifier_apply(modifier=clean_mod.name)

    def _tail_processing(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data)
        context.tool_settings.mesh_select_mode = (False, False, True)
        bm.verts.layers.deform.verify()
        layer = bm.verts.layers.deform.active

        for f in bm.faces: f.select = False
        for v in bm.verts: v.select = False
        for e in bm.edges: e.select = False

        ts = context.tool_settings
        scene = context.scene
        unit_scale = getattr(scene.unit_settings, "scale_length", 1.0) or 1.0
        o_use_merge = ts.use_mesh_automerge
        o_use_split = ts.use_mesh_automerge_and_split
        o_thresh = ts.double_threshold
        ts.use_mesh_automerge = True
        ts.use_mesh_automerge_and_split = True
        ts.double_threshold = 0.00095

        vg_sm = obj.vertex_groups.get("SplitAndMerge")
        if vg_sm:
            try:
                merge_dist = 0.00095 / unit_scale if unit_scale else 0.00095
                sm_verts = [v for v in bm.verts if vg_sm.index in v[layer] and v[layer][vg_sm.index] > 0]
                if sm_verts:
                    bmesh.ops.remove_doubles(bm, verts=sm_verts, dist=merge_dist)
                    bmesh.update_edit_mesh(obj.data)
                    bm = bmesh.from_edit_mesh(obj.data)
                    bm.verts.layers.deform.verify()
                    layer = bm.verts.layers.deform.active
            except Exception:
                pass

            for v in bm.verts:
                if vg_sm.index not in v[layer] or v[layer][vg_sm.index] == 0:
                    v.hide_set(True)
            for v in bm.verts:
                if vg_sm.index in v[layer] and v[layer][vg_sm.index] > 0:
                    v.select = True
            for f in bm.faces:
                if all(v.select for v in f.verts): f.select = True
            bpy.ops.transform.translate(value=(0, 0, 0))
            for v in bm.verts: v.hide_set(False)

        ts.use_mesh_automerge = o_use_merge
        ts.use_mesh_automerge_and_split = o_use_split
        ts.double_threshold = o_thresh

        for f in bm.faces: f.select = False
        for v in bm.verts: v.select = False
        for e in bm.edges: e.select = False

        vg_clear = obj.vertex_groups.get("ClearMesh")
        if vg_clear:
            for v in bm.verts:
                if vg_clear.index in v[layer] and v[layer][vg_clear.index] > 0:
                    v.select = True
            for f in bm.faces:
                if all(v.select for v in f.verts): f.select = True
        for f in bm.faces: f.select = not f.select

        for f in bm.faces: f.select = False
        for v in bm.verts: v.select = False
        for e in bm.edges: e.select = False
        if vg_clear:
            for v in bm.verts:
                if vg_clear.index in v[layer] and v[layer][vg_clear.index] > 0:
                    v.select = True
            for f in bm.faces:
                if all(v.select for v in f.verts): f.select = True
            for f in bm.faces: f.select = not f.select

        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode="OBJECT")
        for name in ["TempSelect", "AlignPoint", "SplitAndMerge"]:
            if name in obj.vertex_groups:
                obj.vertex_groups.remove(obj.vertex_groups[name])
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")

    def _finish_and_cleanup(self, context, apply_now=False):
        if getattr(self, "_draw_handler", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, "WINDOW")
            self._draw_handler = None
        if getattr(self, "_draw_handler_2d", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler_2d, "WINDOW")
            self._draw_handler_2d = None
        context.window.cursor_modal_restore()
        self._clear_status_bar(context)
        obj = context.active_object
        self._restore_snap(context)
        try:
            context.tool_settings.use_mesh_automerge = self._original_automerge_global
        except Exception:
            pass
        bpy.ops.object.mode_set(mode="OBJECT")
        if apply_now:
            self._apply_modifier_with_realize(context)
        if self._free_mode:
            self._cleanup_align_group(obj)
            
        if getattr(self, "_is_open_mesh", False):
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(obj.data)
            layer = bm.faces.layers.int.get("OrigFace")
            if layer:
                faces_to_delete = [f for f in bm.faces if f[layer] == 1]
                if faces_to_delete:
                    bmesh.ops.delete(bm, geom=faces_to_delete, context="FACES")
                bm.faces.layers.int.remove(layer)
            
            mat_layer = bm.faces.layers.int.get("OrigMat")
            if mat_layer:
                for f in bm.faces:
                    if f[mat_layer] != -1:
                        f.material_index = f[mat_layer]
                bm.faces.layers.int.remove(mat_layer)
                
            bmesh.update_edit_mesh(obj.data)
            
            orig_slots = getattr(self, "_orig_mat_slots", len(obj.material_slots))
            if len(obj.material_slots) > orig_slots:
                bpy.ops.object.mode_set(mode="OBJECT")
                while len(obj.material_slots) > orig_slots:
                    obj.active_material_index = len(obj.material_slots) - 1
                    bpy.ops.object.material_slot_remove()
                bpy.ops.object.mode_set(mode="EDIT")

        if "TempSelect" in obj.vertex_groups:
            obj.vertex_groups.remove(obj.vertex_groups["TempSelect"])
        self._tail_processing(context)
            
        self._restore_face_orientation_preview()
        try:
            bpy.ops.mesh.smart_extrude_finalize("INVOKE_DEFAULT")
        except Exception:
            pass

    def _cancel_and_cleanup(self, context):
        if getattr(self, "_draw_handler", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, "WINDOW")
            self._draw_handler = None
        if getattr(self, "_draw_handler_2d", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler_2d, "WINDOW")
            self._draw_handler_2d = None
        context.window.cursor_modal_restore()
        self._clear_status_bar(context)
        obj = context.active_object
        try:
            context.tool_settings.use_mesh_automerge = self._original_automerge_global
        except Exception:
            pass
        self._restore_snap(context)
        bpy.ops.object.mode_set(mode="OBJECT")
        mod = obj.modifiers.get(self._mod_name)
        if mod: obj.modifiers.remove(mod)
        bpy.ops.object.mode_set(mode="EDIT")
        if "TempSelect" in obj.vertex_groups:
            bpy.ops.object.mode_set(mode="OBJECT")
            obj.vertex_groups.active_index = obj.vertex_groups["TempSelect"].index
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.vertex_group_select()
            bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for name in ["TempSelect", "AlignPoint", "SplitAndMerge", "CleanMesh", "ClearMesh", "DelMesh", "ClearEdge"]:
            if name in obj.vertex_groups:
                obj.vertex_groups.remove(obj.vertex_groups[name])
        bpy.ops.object.mode_set(mode="EDIT")
        self._restore_face_orientation_preview()

class ApplySmartExtrudeOperator(bpy.types.Operator):
    bl_idname = "object.apply_smart_extrude"
    bl_label = "应用智慧挤出"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "未选择网格对象！")
            return {"CANCELLED"}
        if context.mode == "EDIT_MESH":
            bpy.ops.object.mode_set(mode="OBJECT")
        mod = obj.modifiers.get("TempSmartExtrude")
        if not mod:
            self.report({"WARNING"}, "找不到 TempSmartExtrude 修改器！")
            bpy.ops.object.mode_set(mode="EDIT")
            return {"CANCELLED"}
        original_group = mod.node_group
        temp_group = original_group.copy()
        temp_group.name = "TempRealizeExtrude"
        mod.node_group = temp_group
        _set_mod_socket(mod, "Socket_10", False)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.node_groups.remove(temp_group)
        data_clean = bpy.data.node_groups.get("DataClean")
        if data_clean:
            clean_mod = obj.modifiers.new(name="TempDataClean", type="NODES")
            clean_mod.node_group = data_clean
            bpy.ops.object.modifier_apply(modifier=clean_mod.name)
        bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}

class SmartExtrudeToggleFlipOperator(bpy.types.Operator):
    bl_idname = "mesh.smart_extrude_toggle_flip"
    bl_label = "智慧挤出: 切换翻转"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH": return {"CANCELLED"}
        mod = obj.modifiers.get("TempSmartExtrude")
        if not mod: return {"CANCELLED"}
        _set_mod_socket(mod, "Socket_9", not bool(_get_mod_socket(mod, "Socket_9", False)))
        obj.data.update()
        return {"FINISHED"}

class SmartExtrudeToggleUnevenOperator(bpy.types.Operator):
    bl_idname = "mesh.smart_extrude_toggle_uneven"
    bl_label = "智慧挤出: 切换不均匀"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH": return {"CANCELLED"}
        mod = obj.modifiers.get("TempSmartExtrude")
        if not mod: return {"CANCELLED"}
        _set_mod_socket(mod, "Socket_8", not bool(_get_mod_socket(mod, "Socket_8", False)))
        obj.data.update()
        return {"FINISHED"}

class SmartExtrudeTogglePreviewOperator(bpy.types.Operator):
    bl_idname = "mesh.smart_extrude_toggle_preview"
    bl_label = "智慧挤出: 切换预览"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH": return {"CANCELLED"}
        mod = obj.modifiers.get("TempSmartExtrude")
        if not mod: return {"CANCELLED"}
        _set_mod_socket(mod, "Socket_10", not bool(_get_mod_socket(mod, "Socket_10", True)))
        obj.data.update()
        return {"FINISHED"}

class SmartExtrudeToggleOnlyManifoldOperator(bpy.types.Operator):
    bl_idname = "mesh.smart_extrude_toggle_only_manifold"
    bl_label = "智慧挤出: 切换仅流形"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH": return {"CANCELLED"}
        mod = obj.modifiers.get("TempSmartExtrude")
        if not mod: return {"CANCELLED"}
        _set_mod_socket(mod, "Socket_22", not bool(_get_mod_socket(mod, "Socket_22", False)))
        obj.data.update()
        return {"FINISHED"}

class SmartExtrudeFinalizeOptions(bpy.types.Operator):
    bl_idname = "mesh.smart_extrude_finalize"
    bl_label = "智慧挤出完成选项"
    bl_options = {"REGISTER", "UNDO"}

    auto_topology: bpy.props.BoolProperty(name="自动拓扑", description="执行三角化/合并及有限溶解", default=True)
    remove_extrude_edge: bpy.props.BoolProperty(name="移除挤出边", description="溶解 ClearEdge 群组中的边上的顶点并移除群组", default=False)

    def invoke(self, context, event):
        try:
            prefs = get_addon_preferences(context)
            self.auto_topology = bool(getattr(prefs, "default_auto_topology", True))
            self.remove_extrude_edge = bool(getattr(prefs, "default_remove_extrude_edge", False))
        except Exception:
            pass
        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH": return {"CANCELLED"}
        if context.mode != "EDIT_MESH": bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.layers.deform.verify()
        layer = bm.verts.layers.deform.active

        if self.auto_topology:
            for f in bm.faces: f.select = False
            for v in bm.verts: v.select = False
            for e in bm.edges: e.select = False
            vg_clear = obj.vertex_groups.get("ClearMesh")
            if vg_clear:
                for v in bm.verts:
                    if vg_clear.index in v[layer] and v[layer][vg_clear.index] > 0: v.select = True
                for f in bm.faces:
                    if all(v.select for v in f.verts): f.select = True
            for f in bm.faces: f.select = not f.select
            
            sel_faces = [f for f in bm.faces if f.select]
            if bpy.app.version >= (4, 5, 0):
                if len(sel_faces) > 3:
                    tri_result = bmesh.ops.triangulate(bm, faces=sel_faces, quad_method="BEAUTY", ngon_method="BEAUTY")
                    for f in bm.faces: f.select = False
                    for face in tri_result["faces"]: face.select = True
                    sel_faces = [f for f in bm.faces if f.select]
                if sel_faces:
                    bmesh.ops.join_triangles(bm, faces=sel_faces, angle_face_threshold=math.radians(40), angle_shape_threshold=math.radians(90), cmp_seam=False, cmp_sharp=False, cmp_uvs=False, cmp_vcols=False, cmp_materials=False)
            
            for f in bm.faces: f.select = False
            for v in bm.verts: v.select = False
            for e in bm.edges: e.select = False
            vg_clean = obj.vertex_groups.get("CleanMesh")
            if vg_clean:
                for v in bm.verts:
                    if vg_clean.index in v[layer] and v[layer][vg_clean.index] > 0: v.select = True
                for f in bm.faces:
                    if all(v.select for v in f.verts): f.select = True
            try:
                bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(0.1))
            except Exception:
                pass

        if self.remove_extrude_edge:
            vg = obj.vertex_groups.get("ClearEdge")
            if vg:
                for f in bm.faces: f.select = False
                for e in bm.edges: e.select = False
                for v in bm.verts: v.select = False
                marked = set()
                for v in bm.verts:
                    if vg.index in v[layer] and v[layer][vg.index] > 0: marked.add(v.index)
                for e in bm.edges:
                    if e.verts[0].index in marked and e.verts[1].index in marked: e.select = True
                bmesh.update_edit_mesh(obj.data)
                context.tool_settings.mesh_select_mode = (False, True, False)
                try:
                    bpy.ops.mesh.dissolve_edges(use_verts=True, use_face_split=False)
                except Exception:
                    pass
                context.tool_settings.mesh_select_mode = (False, False, True)

        bpy.ops.mesh.select_all(action="DESELECT")
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode="OBJECT")
        for name in ["CleanMesh", "ClearMesh", "DelMesh", "ClearEdge"]:
            if name in obj.vertex_groups:
                try:
                    obj.vertex_groups.remove(obj.vertex_groups[name])
                except Exception:
                    pass
        bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}

class SmartExtrudeApplyXrayColorsOperator(bpy.types.Operator):
    bl_idname = "smart_extrude.apply_xray_colors"
    bl_label = "应用透视颜色"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            prefs = get_addon_preferences(context)
            materials = {
                "Preview": prefs.xray_color_object,
                "Preview+": prefs.xray_color_plus,
                "Preview-": prefs.xray_color_minus,
            }
            applied = []
            for mat_name, color in materials.items():
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    mat.diffuse_color = color
                    applied.append(mat_name)
            if applied:
                self.report({"INFO"}, f"已更新材质: {', '.join(applied)}")
            else:
                self.report({"INFO"}, "找不到预览材质，将在下次使用 Smart Extrude 时应用")
        except Exception as e:
            self.report({"ERROR"}, f"更新颜色失败: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}

class SmartExtrudeReloadNodesOperator(bpy.types.Operator):
    bl_idname = "smart_extrude.reload_nodes"
    bl_label = "重新載入節點群組"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        use_fast = False
        try:
            prefs = get_addon_preferences(context)
            use_fast = bool(getattr(prefs, "preview_xray_mode", False))
        except Exception:
            pass
        
        try:
            blend_path = _get_blend_file_path(use_fast)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if (4, 3, 0) <= bpy.app.version < (4, 5, 0):
            targets = NODE_GROUPS_4_3_4_4
        else:
            targets = NODE_GROUPS_4_5_PLUS

        for name in targets:
            grp = bpy.data.node_groups.get(name)
            if grp:
                try:
                    bpy.data.node_groups.remove(grp)
                except Exception:
                    pass

        loaded_names = []
        try:
            with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
                requested_names = [name for name in targets if name in getattr(data_from, "node_groups", [])]
                loaded_names = list(requested_names)
                data_to.node_groups = requested_names
        except Exception as e:
            self.report({"ERROR"}, f"载入失败: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已重新载入节点群组: {', '.join(loaded_names) if loaded_names else '无'}")
        return {"FINISHED"}

class SmartExtrudeRecordKeybind(bpy.types.Operator):
    bl_idname = "smart_extrude.record_keybind"
    bl_label = "录制按键绑定"
    bl_options = {'INTERNAL'}
    target_base: bpy.props.StringProperty() 

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.value == 'PRESS':
            if event.type == 'ESC': return {'CANCELLED'}
            modifiers = {'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_CTRL', 'RIGHT_ALT', 'RIGHT_SHIFT', 'OSKEY'}
            if event.type in modifiers: return {'RUNNING_MODAL'}
            
            addon_prefs = get_addon_preferences(context)
            if addon_prefs:
                setattr(addon_prefs, f"{self.target_base}_key", event.type)
                setattr(addon_prefs, f"{self.target_base}_ctrl", event.ctrl)
                setattr(addon_prefs, f"{self.target_base}_shift", event.shift)
                setattr(addon_prefs, f"{self.target_base}_alt", event.alt)
                context.area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

class SmartExtrudeSetModeOperator(bpy.types.Operator):
    bl_idname = "smart_extrude.set_mode"
    bl_label = "智慧挤出: 设定模式"
    bl_options = {"INTERNAL"}

    new_mode: bpy.props.EnumProperty(
        name="模式",
        items=(
            ("SMART", "Smart", ""),
            ("ALONG_NORMAL", "Along Normal", ""),
            ("INDIVIDUAL", "Individual Faces", ""),
        ),
        default="SMART",
    )

    def execute(self, context):
        if hasattr(context.scene, "smart_extrude_mode"):
            context.scene.smart_extrude_mode = self.new_mode
        obj = context.active_object
        if obj and obj.type == "MESH":
            mod = obj.modifiers.get(MODIFIER_NAME)
            if mod:
                try:
                    if self.new_mode == "INDIVIDUAL" and bpy.app.version < (4, 5, 0):
                        self.report({"WARNING"}, "Individual 模式仅支持 Blender 4.5+，已切换至 Smart 模式")
                        self.new_mode = "SMART"
                        context.scene.smart_extrude_mode = "SMART"
                    _set_mod_socket(mod, "Socket_5", self.new_mode == "INDIVIDUAL")
                    _set_mod_socket(mod, "Socket_16", self.new_mode == "SMART")
                    obj.data.update()
                    try:
                        mod["_operator_mode"] = self.new_mode
                    except Exception:
                        pass
                except Exception:
                    pass
        return {"FINISHED"}

# =============================================================================
# PREFERENCES
# =============================================================================


def _update_xray_mode(self, context):
    try:
        bpy.ops.smart_extrude.reload_nodes()
    except Exception:
        pass

def _update_topology_max_vertex(self, context):
    try:
        value = int(getattr(self, "default_topology_max_vertex", 16))
    except Exception:
        value = 16
    value = max(0, value)
    try:
        obj = context.active_object if context else None
        if obj and obj.type == "MESH":
            mod = obj.modifiers.get(MODIFIER_NAME)
            if mod and mod.type == "NODES": _set_mod_socket(mod, SOCKET_TOPOLOGY_MAX_VERTEX, value)
    except Exception:
        pass
    try:
        for obj in bpy.data.objects:
            if obj.type != "MESH": continue
            mod = obj.modifiers.get(MODIFIER_NAME)
            if not mod or mod.type != "NODES": continue
            _set_mod_socket(mod, SOCKET_TOPOLOGY_MAX_VERTEX, value)
    except Exception:
        pass

# =============================================================================
# UI & REGISTRATION
# =============================================================================

def on_smart_extrude_mode_update(self, context):
    try:
        obj = context.active_object
        if obj and obj.type == "MESH":
            mod = obj.modifiers.get(MODIFIER_NAME)
            if mod:
                new_mode = getattr(self, "smart_extrude_mode", "SMART")
                if new_mode == "INDIVIDUAL" and bpy.app.version < (4, 5, 0):
                    self.smart_extrude_mode = "SMART"
                    new_mode = "SMART"
                _set_mod_socket(mod, "Socket_5", new_mode == "INDIVIDUAL")
                _set_mod_socket(mod, "Socket_16", new_mode == "SMART")
                obj.data.update()
                try:
                    mod["_operator_mode"] = new_mode
                except Exception:
                    pass
    except Exception:
        pass

def draw_extrude_ui(layout, context):
    """在侧边栏“我的工具”面板中渲染“挤出”选项卡的内容（完整整合 Smart Extrude 的设置与功能）"""
    scene = context.scene
    prefs = get_addon_preferences(context)
    
    # 1. 核心模式选择 (无“启动智慧挤出”多余按钮)
    box_op = layout.box()
    box_op.label(text="模式选择", icon="MOD_SOLIDIFY")
    
    row_modes = box_op.row(align=True)
    row_modes.scale_y = 1.2
    row_modes.column().prop_enum(scene, "smart_extrude_mode", value="SMART")
    row_modes.column().prop_enum(scene, "smart_extrude_mode", value="ALONG_NORMAL")
    if bpy.app.version >= (4, 5, 0):
        row_modes.column().prop_enum(scene, "smart_extrude_mode", value="INDIVIDUAL")

    # 2. 节点维护工具
    box_tools = layout.box()
    box_tools.operator("smart_extrude.reload_nodes", text="重新载入 Smart Extrude 节点库", icon="FILE_REFRESH")

    if not prefs:
        box_warn = layout.box()
        box_warn.label(text="提示: 偏好设置未激活，请在 Blender 插件设置中启用该插件", icon="INFO")
        return

    # 3. 控制参数
    box_ctrl = layout.box()
    box_ctrl.label(text="控制 (Control)", icon="PREFERENCES")
    col_ctrl = box_ctrl.column(align=True)
    col_ctrl.prop(prefs, "use_group_normal_mapping")
    col_ctrl.prop(prefs, "edge_action")

    # 4. 视图与预览
    box_prev = layout.box()
    box_prev.label(text="预览 (Preview)", icon="RESTRICT_VIEW_OFF")
    col_p = box_prev.column(align=True)
    row_p1 = col_p.row(align=True)
    row_p1.prop(prefs, "direction_arrow")
    row_p1.prop(prefs, "face_orientation_preview")
    row_p2 = col_p.row(align=True)
    row_p2.prop(prefs, "hide_non_extruded_mesh")
    
    xray_box = box_prev.box()
    xray_box.label(text="透视预览 (Xray Preview)", icon="SHADING_WIRE")
    xray_col = xray_box.column(align=True)
    xray_col.prop(prefs, "preview_xray_mode")
    
    icon_xray = "DOWNARROW_HLT" if getattr(prefs, "show_xray_colors", False) else "RIGHTARROW"
    xray_col.prop(prefs, "show_xray_colors", text="透视模式颜色", icon=icon_xray, emboss=False)
    if getattr(prefs, "show_xray_colors", False):
        color_box = xray_col.box()
        color_col = color_box.column(align=True)
        row = color_col.row(align=True)
        row.label(text="物体")
        row.prop(prefs, "xray_color_object", text="")
        row = color_col.row(align=True)
        row.label(text="挤出 (+)")
        row.prop(prefs, "xray_color_plus", text="")
        row = color_col.row(align=True)
        row.label(text="挤出 (-)")
        row.prop(prefs, "xray_color_minus", text="")
        color_col.separator()
        color_col.operator("smart_extrude.apply_xray_colors", icon="COLOR", text="应用颜色")

    # 5. 默认值 (Default 4.5+)
    box_topo = layout.box()
    box_topo.label(text="默认值 (Default 4.5+)", icon="MESH_DATA")
    col_t = box_topo.column(align=True)
    row_t1 = col_t.row(align=True)
    row_t1.prop(prefs, "default_auto_topology")
    row_t1.prop(prefs, "default_remove_extrude_edge")
    col_t.prop(prefs, "default_topology_max_vertex")

    # 6. 快捷键配置 (Shortcuts)
    box_keys = layout.box()
    icon_sc = "DOWNARROW_HLT" if getattr(prefs, "show_shortcuts", False) else "RIGHTARROW"
    box_keys.prop(prefs, "show_shortcuts", text="快捷键配置 (Shortcuts)", icon=icon_sc, emboss=False)
    
    if getattr(prefs, "show_shortcuts", False):
        col_k = box_keys.column(align=True)
        col_k.prop(prefs, "shortcut_text_size")
        def draw_shortcut_row(label, base_prop):
            key = getattr(prefs, f"{base_prop}_key", "")
            ctrl = getattr(prefs, f"{base_prop}_ctrl", False)
            shift = getattr(prefs, f"{base_prop}_shift", False)
            alt = getattr(prefs, f"{base_prop}_alt", False)
            parts = []
            if ctrl: parts.append("Ctrl")
            if shift: parts.append("Shift")
            if alt: parts.append("Alt")
            if key: parts.append(key)
            display_str = " + ".join(parts) if parts else "点击分配"
            row = col_k.row(align=True)
            row.label(text=label)
            op = row.operator("smart_extrude.record_keybind", text=display_str)
            op.target_base = base_prop

        draw_shortcut_row("吸附", "snap")
        draw_shortcut_row("翻转", "flip")
        draw_shortcut_row("不均匀", "uneven")
        draw_shortcut_row("预览", "preview")
        draw_shortcut_row("仅流形", "only_manifold")
        draw_shortcut_row("底部吸附", "snap_bottom")
        draw_shortcut_row("模式切换", "mode_cycle")
        draw_shortcut_row("快速菜单", "quick_menu")

def draw_extrude_preferences(layout, prefs):
    draw_extrude_ui(layout, bpy.context)
def _menu_draw(self, context):
    col = self.layout.column()
    op = col.operator("mesh.smart_extrude", text="智慧挤出 (Smart Extrude)")
    op.mode = "SMART"
    op = col.operator("mesh.smart_extrude", text="沿法线智慧挤出")
    op.mode = "ALONG_NORMAL"
    try:
        if bpy.app.version >= (4, 5, 0):
            op = col.operator("mesh.smart_extrude", text="个别面智慧挤出")
            op.mode = "INDIVIDUAL"
    except Exception:
        pass

def _f9_popup_draw(menu, context):
    layout = menu.layout
    col = layout.column(align=True)
    col.label(text="智慧挤出模式")
    row = col.row(align=True)
    op = row.operator("smart_extrude.set_mode", text="群组法线")
    op.new_mode = "SMART"
    op = row.operator("smart_extrude.set_mode", text="法线")
    op.new_mode = "ALONG_NORMAL"
    try:
        if bpy.app.version >= (4, 5, 0):
            op = row.operator("smart_extrude.set_mode", text="个别")
            op.new_mode = "INDIVIDUAL"
    except Exception:
        pass

_addon_keymaps = []

classes = (
    SmartExtrudeOperator,
    ApplySmartExtrudeOperator,
    SmartExtrudeToggleFlipOperator,
    SmartExtrudeToggleUnevenOperator,
    SmartExtrudeTogglePreviewOperator,
    SmartExtrudeToggleOnlyManifoldOperator,
    SmartExtrudeReloadNodesOperator,
    SmartExtrudeRecordKeybind,
    SmartExtrudeSetModeOperator,
    SmartExtrudeFinalizeOptions,
    SmartExtrudeApplyXrayColorsOperator,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    try:
        bpy.types.VIEW3D_MT_edit_mesh_extrude.prepend(_menu_draw)
    except Exception:
        pass

    try:
        wm = bpy.context.window_manager
        if wm and hasattr(wm, "keyconfigs") and wm.keyconfigs and hasattr(wm.keyconfigs, "addon") and wm.keyconfigs.addon:
            km_mesh = wm.keyconfigs.addon.keymaps.new(name="Mesh", space_type="EMPTY")
            kmi = km_mesh.keymap_items.new(SmartExtrudeOperator.bl_idname, "E", "PRESS")
            kmi.properties.mode = "SMART"
            _addon_keymaps.append((km_mesh, kmi))
            kmi_apply = km_mesh.keymap_items.new(ApplySmartExtrudeOperator.bl_idname, "RET", "PRESS", ctrl=True)
            _addon_keymaps.append((km_mesh, kmi_apply))
    except Exception:
        pass

def unregister():
    try:
        bpy.types.VIEW3D_MT_edit_mesh_extrude.remove(_menu_draw)
    except Exception:
        pass
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

if __name__ == "__main__":
    register()
