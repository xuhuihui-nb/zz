# -*- coding: utf-8 -*-

bl_info = {
    "name": "我的工具",
    "author": "Antigravity",
    "version": (1, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > 我的工具",
    "description": "整合对齐工具、插件加载器、一键重启工具、工整的螺旋纤维、窗口切换、智慧挤出、双击切换、TP拓扑和动态拓扑的多功能面板",
    "category": "System",
}

import bpy

# 支持在启用/禁用插件时动态重载子模块，避免缓存问题
if "align" in globals():
    try: importlib.reload(align)
    except Exception as e: print(f"ZZ: Failed to reload align: {e}")
    try: importlib.reload(loader)
    except Exception as e: print(f"ZZ: Failed to reload loader: {e}")
    try: importlib.reload(restart)
    except Exception as e: print(f"ZZ: Failed to reload restart: {e}")
    try: importlib.reload(lxxw)
    except Exception as e: print(f"ZZ: Failed to reload lxxw: {e}")
    try: importlib.reload(mbqh)
    except Exception as e: print(f"ZZ: Failed to reload mbqh: {e}")
    try: importlib.reload(extrude)
    except Exception as e: print(f"ZZ: Failed to reload extrude: {e}")
    try: importlib.reload(sjqh)
    except Exception as e: print(f"ZZ: Failed to reload sjqh: {e}")
    try: importlib.reload(tp)
    except Exception as e: print(f"ZZ: Failed to reload tp: {e}")
    try: importlib.reload(softwrap2)
    except Exception as e: print(f"ZZ: Failed to reload softwrap2: {e}")
    try: importlib.reload(slide_edge)
    except Exception as e: print(f"ZZ: Failed to reload slide_edge: {e}")
    try: importlib.reload(looptools)
    except Exception as e: print(f"ZZ: Failed to reload looptools: {e}")
    try: importlib.reload(light)
    except Exception as e: print(f"ZZ: Failed to reload light: {e}")
    try: importlib.reload(grabdoc)
    except Exception as e: print(f"ZZ: Failed to reload grabdoc: {e}")
    try: importlib.reload(use)
    except Exception as e: print(f"ZZ: Failed to reload use: {e}")
    try: importlib.reload(quad_remesher_1_4)
    except Exception as e: print(f"ZZ: Failed to reload quad_remesher_1_4: {e}")
    try: importlib.reload(SimpleBake)
    except Exception as e: print(f"ZZ: Failed to reload SimpleBake: {e}")

    if "pie_menu_editor" in globals():
        try: importlib.reload(pie_menu_editor)
        except Exception as e: print(f"ZZ: Failed to reload pie_menu_editor: {e}")
    else:
        try: from . import pie_menu_editor
        except Exception as e: print(f"ZZ: Failed to import pie_menu_editor: {e}")
else:
    try: from . import align
    except Exception as e: print(f"ZZ: Failed to import align: {e}")
    try: from . import loader
    except Exception as e: print(f"ZZ: Failed to import loader: {e}")
    try: from . import restart
    except Exception as e: print(f"ZZ: Failed to import restart: {e}")
    try: from . import lxxw
    except Exception as e: print(f"ZZ: Failed to import lxxw: {e}")
    try: from . import mbqh
    except Exception as e: print(f"ZZ: Failed to import mbqh: {e}")
    try: from . import extrude
    except Exception as e: print(f"ZZ: Failed to import extrude: {e}")
    try: from . import sjqh
    except Exception as e: print(f"ZZ: Failed to import sjqh: {e}")
    try: from . import tp
    except Exception as e: print(f"ZZ: Failed to import tp: {e}")
    try: from . import softwrap2
    except Exception as e: print(f"ZZ: Failed to import softwrap2: {e}")
    try: from . import slide_edge
    except Exception as e: print(f"ZZ: Failed to import slide_edge: {e}")
    try: from . import looptools
    except Exception as e: print(f"ZZ: Failed to import looptools: {e}")
    try: from . import light
    except Exception as e: print(f"ZZ: Failed to import light: {e}")
    try: from . import grabdoc
    except Exception as e: print(f"ZZ: Failed to import grabdoc: {e}")
    try: from . import use
    except Exception as e: print(f"ZZ: Failed to import use: {e}")
    try: from . import quad_remesher_1_4
    except Exception as e: print(f"ZZ: Failed to import quad_remesher_1_4: {e}")
    try: from . import SimpleBake
    except Exception as e: print(f"ZZ: Failed to import SimpleBake: {e}")
    try: from . import pie_menu_editor
    except Exception as e: print(f"ZZ: Failed to import pie_menu_editor: {e}")




# =========================================================================
# 1. 偏好设置 (Addon Preferences)
# =========================================================================

def _on_edit_name_buf_update(self, context):
    try:
        scene = getattr(context, "scene", None) if context else None
        if scene:
            editing_row = getattr(scene, "zz_editing_row", 0)
            if editing_row > 0:
                rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
                if 1 <= editing_row <= len(rows_names):
                    new_val = scene.zz_edit_name_buf.strip()
                    if new_val:
                        rows_names[editing_row - 1] = new_val
                        set_rows_data(context, rows_tabs, rows_names, rows_collapsed)
                scene.zz_editing_row = 0
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
    except Exception:
        pass

class ZZ_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__.split('.')[0]

    addon_folder_path: bpy.props.StringProperty(
        name="插件文件夹路径",
        description="选择要加载的插件所在文件夹",
        subtype='DIR_PATH',
        default=""
    )

    pme_data_json: bpy.props.StringProperty(
        name="饼菜单配置数据",
        description="保存导入和自定义的饼菜单配置数据 (跨重启持久化)",
        default=""
    )


    tab_order: bpy.props.StringProperty(
        name="分页排序",
        description="分页在 N 面板上的排列顺序 (逗号分隔)",
        default="ALIGN,LOADER,RESTART,LXXW,MBQH,EXTRUDE,SJQH,TP,DYTOPO"
    )

    rows_tabs_data: bpy.props.StringProperty(
        name="行分页数据",
        default="ALIGN,LOADER,RESTART,LXXW|MBQH,EXTRUDE,SJQH,TP,DYTOPO"
    )

    rows_names_data: bpy.props.StringProperty(
        name="行名称数据",
        default="常用板块|高级板块"
    )

    rows_collapsed_data: bpy.props.StringProperty(
        name="行折叠数据",
        default="0|0"
    )

    mt_executable: bpy.props.StringProperty(
        name="Marmoset EXE Path",
        description="Path to Marmoset Toolbag 3+ executable",
        default="",
        subtype="FILE_PATH"
    )

    render_within_frustrum: bpy.props.BoolProperty(
        name="Render Within Frustrum",
        description="Only render objects within camera viewing frustrum",
        default=False
    )

    exit_camera_preview: bpy.props.BoolProperty(
        name="Auto-exit Preview Camera",
        description="Exit camera when leaving Map Preview",
        default=True
    )

    disable_preview_binds: bpy.props.BoolProperty(
        name="Disable Keybinds in Preview",
        description="Disable escape keybind in Map Preview",
        default=False
    )

    # -------------------------------------------------------------------------
    # 智慧挤出 (Smart Extrude) 偏好设置
    # -------------------------------------------------------------------------
    preview_xray_mode: bpy.props.BoolProperty(
        name="预览透视模式",
        description="在 Blender 4.5+ 上，载入 SE/seFast.blend 而非 SE/se.blend",
        default=True,
        update=lambda self, context: getattr(extrude, "_update_xray_mode", lambda s, c: None)(self, context),
    )

    direction_arrow: bpy.props.BoolProperty(
        name="方向箭头",
        description="显示方向箭头 (控制 GeometryNodes Socket_20)",
        default=True,
    )

    xray_color_object: bpy.props.FloatVectorProperty(
        name="物体", description="物体的预览材质颜色", subtype="COLOR", size=4, min=0.0, max=1.0, default=(0.8, 0.8, 0.8, 0.35),
    )
    xray_color_plus: bpy.props.FloatVectorProperty(
        name="+", description="正向挤出的预览材质颜色", subtype="COLOR", size=4, min=0.0, max=1.0, default=(0.45, 1.0, 0.45, 1.0),
    )
    xray_color_minus: bpy.props.FloatVectorProperty(
        name="-", description="负向挤出的预览材质颜色", subtype="COLOR", size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 0.5),
    )

    snap_key: bpy.props.StringProperty(name="吸附热键", default="B")
    snap_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    snap_shift: bpy.props.BoolProperty(name="Shift", default=False)
    snap_alt: bpy.props.BoolProperty(name="Alt", default=False)

    mode_cycle_key: bpy.props.StringProperty(name="模式切换热键", default="TAB")
    mode_cycle_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    mode_cycle_shift: bpy.props.BoolProperty(name="Shift", default=False)
    mode_cycle_alt: bpy.props.BoolProperty(name="Alt", default=False)

    flip_key: bpy.props.StringProperty(name="翻转热键", default="F")
    flip_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    flip_shift: bpy.props.BoolProperty(name="Shift", default=False)
    flip_alt: bpy.props.BoolProperty(name="Alt", default=False)

    uneven_key: bpy.props.StringProperty(name="不均匀热键", default="D")
    uneven_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    uneven_shift: bpy.props.BoolProperty(name="Shift", default=False)
    uneven_alt: bpy.props.BoolProperty(name="Alt", default=False)

    preview_key: bpy.props.StringProperty(name="预览热键", default="Y")
    preview_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True)
    preview_shift: bpy.props.BoolProperty(name="Shift", default=False)
    preview_alt: bpy.props.BoolProperty(name="Alt", default=False)

    only_manifold_key: bpy.props.StringProperty(name="仅流形热键", default="M")
    only_manifold_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    only_manifold_shift: bpy.props.BoolProperty(name="Shift", default=False)
    only_manifold_alt: bpy.props.BoolProperty(name="Alt", default=False)

    snap_bottom_key: bpy.props.StringProperty(name="底部吸附热键", default="B")
    snap_bottom_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True)
    snap_bottom_shift: bpy.props.BoolProperty(name="Shift", default=False)
    snap_bottom_alt: bpy.props.BoolProperty(name="Alt", default=False)

    quick_menu_key: bpy.props.StringProperty(name="快速菜单热键", default="RET")
    quick_menu_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True)
    quick_menu_shift: bpy.props.BoolProperty(name="Shift", default=False)
    quick_menu_alt: bpy.props.BoolProperty(name="Alt", default=False)

    default_auto_topology: bpy.props.BoolProperty(name="自动拓扑", description="在完成时默认启用三角化/合并/溶解", default=True)
    default_remove_extrude_edge: bpy.props.BoolProperty(name="移除挤出边", description="默认溶解被标记为 ClearEdge 的边上的顶点", default=False)
    default_topology_max_vertex: bpy.props.IntProperty(
        name="拓扑最大顶点数",
        description='Smart Extrude Geometry Nodes 修改器整数输入 ["Socket_28"] 的默认值 (Blender 4.5+)',
        default=16,
        min=0,
        update=lambda self, context: getattr(extrude, "_update_topology_max_vertex", lambda s, c: None)(self, context),
    )

    face_orientation_preview: bpy.props.BoolProperty(name="面朝向", description="执行 Smart Extrude 时启用面朝向叠加层", default=True)
    hide_non_extruded_mesh: bpy.props.BoolProperty(name="隐藏未挤出网格", description="挤出期间隐藏原始网格部分 (控制 GeometryNodes Socket_23)", default=True)
    use_group_normal_mapping: bpy.props.BoolProperty(name="使用群组法线控制", description="通过群组法线映射控制距离，而非仅垂直移动鼠标", default=True)

    edge_action: bpy.props.EnumProperty(
        name="边线动作",
        description="当选取边线但没有选取面时执行的动作",
        items=[
            ("DUPLICATE", "复制边线", "复制边线并移动"),
            ("EXTRUDE", "挤出边线", "挤出边线并移动 (默认)"),
        ],
        default="EXTRUDE",
    )

    show_xray_colors: bpy.props.BoolProperty(name="显示透视颜色", default=False)
    show_shortcuts: bpy.props.BoolProperty(name="显示快捷键", default=False)
    shortcut_text_size: bpy.props.IntProperty(name="快捷键文字大小", description="3D视口中显示的快捷键文字大小", default=20, min=10, max=100)

    def draw(self, context):
        layout = self.layout
        layout.label(text="所有设置与功能已整合至 3D 视口侧边栏 (N 面板) 的「我的工具」标签页中。")

# =========================================================================
# 2. 帮助函数与操作符 (Helper Functions & Operators)
# =========================================================================

TAB_INFO = {
    'ALIGN': "对齐 (Align)",
    'LOADER': "插件加载",
    'RESTART': "一键重启",
    'LXXW': "工整的螺旋纤维",
    'MBQH': "窗口切换",
    'EXTRUDE': "挤出",
    'SJQH': "双击切换",
    'TP': "TP拓扑",
    'DYTOPO': "动态拓扑",
    'SLIDE_EDGE': "边滑动",
    'LOOPTOOLS': "LoopTools ",
    'LIGHT': "灯光",
    'TEXTURE_SCENE': "纹理场景",
    'USE_TRANS': "use翻译",
    'AUTO_REMESH': "自动重构",
    'SIMPLE_BAKE': "简单烘焙",
    'PIE_MENU': "饼菜单",
}

import json
import os

DEFAULT_ROWS_TABS = [
    ["ALIGN", "RESTART", "EXTRUDE", "MBQH", "LOADER", "SJQH", "LOOPTOOLS", "PIE_MENU"],
    ["TP", "DYTOPO", "AUTO_REMESH", "LXXW", "SLIDE_EDGE"],
    ["LIGHT", "TEXTURE_SCENE", "USE_TRANS", "SIMPLE_BAKE"]
]
DEFAULT_ROWS_NAMES = ["系统性工具", "建模", "布景"]

def get_config_filepath():
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, "config.json")

def load_config_from_disk():
    try:
        path = get_config_filepath()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"ZZ: Failed to load config.json: {e}")
    return None

def save_config_to_disk(rows_tabs=None, rows_names=None, rows_collapsed=None, active_tab=None, active_category_idx=None):
    try:
        path = get_config_filepath()
        data = load_config_from_disk() or {}
        if rows_tabs is not None:
            data["rows_tabs"] = rows_tabs
        if rows_names is not None:
            data["rows_names"] = rows_names
        if rows_collapsed is not None:
            data["rows_collapsed"] = rows_collapsed
        if active_tab is not None:
            data["last_active_tab"] = active_tab
        if active_category_idx is not None:
            data["last_active_category_idx"] = active_category_idx

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"ZZ: Failed to save config.json: {e}")

def get_saved_active_tab():
    cfg = load_config_from_disk()
    if cfg:
        tab = cfg.get("last_active_tab", "ALIGN")
        if tab in TAB_INFO:
            return tab
    return 'ALIGN'

def get_saved_active_category_idx():
    cfg = load_config_from_disk()
    if cfg:
        cat = cfg.get("last_active_category_idx", 0)
        if isinstance(cat, int) and cat >= 0:
            return cat
    return 0

from bpy.app.handlers import persistent

@persistent
def _on_blend_load_post(dummy):
    try:
        saved_tab = get_saved_active_tab()
        saved_cat = get_saved_active_category_idx()
        for scene in bpy.data.scenes:
            if hasattr(scene, "zz_active_category_idx"):
                scene.zz_active_category_idx = saved_cat
            if hasattr(scene, "zz_active_tab"):
                scene.zz_active_tab = saved_tab
    except Exception as e:
        print(f"ZZ: Failed on load_post restore: {e}")

def _on_active_tab_update(self, context):
    try:
        active_tab = getattr(self, "zz_active_tab", "")
        active_cat = getattr(self, "zz_active_category_idx", 0)
        if active_tab:
            save_config_to_disk(active_tab=active_tab, active_category_idx=active_cat)
    except Exception:
        pass

def _on_active_category_idx_update(self, context):
    try:
        active_tab = getattr(self, "zz_active_tab", "")
        active_cat = getattr(self, "zz_active_category_idx", 0)
        save_config_to_disk(active_tab=active_tab, active_category_idx=active_cat)
    except Exception:
        pass

def get_package_name():
    return __name__.split('.')[0]

def get_addon_preferences(context):
    try:
        pkg = get_package_name()
        addon = context.preferences.addons.get(pkg)
        if addon and hasattr(addon, "preferences"):
            return addon.preferences
    except Exception:
        pass
    return None

def get_rows_data(context):
    scene = getattr(context, "scene", None) if context else None
    prefs = get_addon_preferences(context)

    t_str = getattr(scene, "zz_rows_tabs_data", "") if scene else ""
    n_str = getattr(scene, "zz_rows_names_data", "") if scene else ""
    c_str = getattr(scene, "zz_rows_collapsed_data", "") if scene else ""

    # 如果 Scene 内存中未初始化，优先尝试从 config.json 硬盘文件读取
    if not t_str:
        cfg = load_config_from_disk()
        if cfg and "rows_tabs" in cfg:
            rows_tabs = cfg.get("rows_tabs", [])
            rows_names = cfg.get("rows_names", [])
            rows_collapsed = cfg.get("rows_collapsed", [])

            present = set()
            for r in rows_tabs:
                present.update(r)
            for t in TAB_INFO.keys():
                if t not in present:
                    if not rows_tabs:
                        rows_tabs.append([])
                        rows_names.append("系统性工具")
                        rows_collapsed.append(False)
                    if t in {"LIGHT", "TEXTURE_SCENE"}:
                        target_row = -1
                        for r_i, r_name in enumerate(rows_names):
                            if "布景" in r_name:
                                target_row = r_i
                                break
                        if target_row != -1:
                            rows_tabs[target_row].append(t)
                        else:
                            rows_tabs[-1].append(t)
                    else:
                        rows_tabs[0].append(t)

            set_rows_data(context, rows_tabs, rows_names, rows_collapsed, save_disk=False)
            return rows_tabs, rows_names, rows_collapsed

    if not t_str and prefs:
        t_str = getattr(prefs, "rows_tabs_data", "")
        n_str = getattr(prefs, "rows_names_data", "")
        c_str = getattr(prefs, "rows_collapsed_data", "")

    if t_str:
        raw_rows = t_str.split("|")
        rows_tabs = []
        for r in raw_rows:
            items = [t.strip() for t in r.split(",") if t.strip() in TAB_INFO]
            rows_tabs.append(items)
    else:
        rows_tabs = [list(r) for r in DEFAULT_ROWS_TABS]

    if n_str:
        rows_names = [n.strip() for n in n_str.split("|")]
    else:
        rows_names = list(DEFAULT_ROWS_NAMES)

    while len(rows_names) < len(rows_tabs):
        rows_names.append(f"分组 {len(rows_names) + 1}")

    if c_str:
        rows_collapsed = [c == "1" for c in c_str.split("|")]
    else:
        rows_collapsed = [False] * len(rows_tabs)

    while len(rows_collapsed) < len(rows_tabs):
        rows_collapsed.append(False)

    # 补全可能遗漏的标签
    present = set()
    for r in rows_tabs:
        present.update(r)
    for t in TAB_INFO.keys():
        if t not in present:
            if not rows_tabs:
                rows_tabs.append([])
                rows_names.append("系统性工具")
                rows_collapsed.append(False)
            if t in {"LIGHT", "TEXTURE_SCENE"}:
                target_row = -1
                for r_i, r_name in enumerate(rows_names):
                    if "布景" in r_name:
                        target_row = r_i
                        break
                if target_row != -1:
                    rows_tabs[target_row].append(t)
                else:
                    rows_tabs[-1].append(t)
            else:
                rows_tabs[0].append(t)

    return rows_tabs, rows_names, rows_collapsed

def set_rows_data(context, rows_tabs, rows_names=None, rows_collapsed=None, save_disk=True):
    if rows_names is None or rows_collapsed is None:
        old_tabs, old_names, old_collapsed = get_rows_data(context)
        if rows_names is None:
            rows_names = old_names
        if rows_collapsed is None:
            rows_collapsed = old_collapsed

    while len(rows_names) < len(rows_tabs):
        rows_names.append(f"分组 {len(rows_names) + 1}")
    while len(rows_collapsed) < len(rows_tabs):
        rows_collapsed.append(False)

    t_str = "|".join(",".join(r) for r in rows_tabs)
    n_str = "|".join(rows_names[:len(rows_tabs)])
    c_str = "|".join("1" if c else "0" for c in rows_collapsed[:len(rows_tabs)])

    scene = getattr(context, "scene", None) if context else None
    if scene:
        try:
            scene.zz_rows_tabs_data = t_str
            scene.zz_rows_names_data = n_str
            scene.zz_rows_collapsed_data = c_str
        except Exception:
            pass

    prefs = get_addon_preferences(context)
    if prefs:
        try:
            prefs.rows_tabs_data = t_str
            prefs.rows_names_data = n_str
            prefs.rows_collapsed_data = c_str
        except Exception:
            pass

    if save_disk:
        save_config_to_disk(rows_tabs, rows_names[:len(rows_tabs)], rows_collapsed[:len(rows_tabs)])

def get_all_rows_tabs(context):
    rows_tabs, _, _ = get_rows_data(context)
    res = []
    for r in rows_tabs:
        res.extend(r)
    return res

def set_all_rows_tabs(context, r1, r2):
    set_rows_data(context, [r1, r2])

def get_current_tab_order(context):
    return get_all_rows_tabs(context)

def set_current_tab_order(context, new_order):
    pass

def _move_active_tab(context, direction):
    rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
    active_tab = getattr(context.scene, "zz_active_tab", "ALIGN")

    curr_row = -1
    curr_idx = -1
    for r_i, r_list in enumerate(rows_tabs):
        if active_tab in r_list:
            curr_row = r_i
            curr_idx = r_list.index(active_tab)
            break

    if curr_row == -1:
        active_cat_idx = getattr(context.scene, "zz_active_category_idx", 0)
        if 0 <= active_cat_idx < len(rows_names):
            curr_row = active_cat_idx
        else:
            curr_row = 0

    is_cat_move_mode = getattr(context.scene, "zz_category_move_mode", False)

    if is_cat_move_mode:
        if len(rows_names) > 1:
            if direction == 'LEFT':
                prev_r = (curr_row - 1) % len(rows_names)
                rows_names[curr_row], rows_names[prev_r] = rows_names[prev_r], rows_names[curr_row]
                rows_tabs[curr_row], rows_tabs[prev_r] = rows_tabs[prev_r], rows_tabs[curr_row]
                rows_collapsed[curr_row], rows_collapsed[prev_r] = rows_collapsed[prev_r], rows_collapsed[curr_row]
                context.scene.zz_active_category_idx = prev_r
            elif direction == 'RIGHT':
                next_r = (curr_row + 1) % len(rows_names)
                rows_names[curr_row], rows_names[next_r] = rows_names[next_r], rows_names[curr_row]
                rows_tabs[curr_row], rows_tabs[next_r] = rows_tabs[next_r], rows_tabs[curr_row]
                rows_collapsed[curr_row], rows_collapsed[next_r] = rows_collapsed[next_r], rows_collapsed[curr_row]
                context.scene.zz_active_category_idx = next_r
    else:
        if 0 <= curr_row < len(rows_tabs):
            curr_list = rows_tabs[curr_row]
            if direction == 'LEFT':
                is_far_left = (curr_idx % 4 == 0)
                if not is_far_left and curr_idx > 0:
                    curr_list[curr_idx], curr_list[curr_idx - 1] = curr_list[curr_idx - 1], curr_list[curr_idx]
                elif is_far_left and len(rows_tabs) > 1:
                    prev_row = (curr_row - 1) % len(rows_tabs)
                    curr_list.remove(active_tab)
                    rows_tabs[prev_row].append(active_tab)
                    context.scene.zz_active_category_idx = prev_row
            elif direction == 'RIGHT':
                is_far_right = (curr_idx % 4 == 3) or (curr_idx == len(curr_list) - 1)
                if not is_far_right and curr_idx < len(curr_list) - 1:
                    curr_list[curr_idx], curr_list[curr_idx + 1] = curr_list[curr_idx + 1], curr_list[curr_idx]
                elif is_far_right and len(rows_tabs) > 1:
                    next_row = (curr_row + 1) % len(rows_tabs)
                    curr_list.remove(active_tab)
                    rows_tabs[next_row].insert(0, active_tab)
                    context.scene.zz_active_category_idx = next_row
            elif direction == 'UP':
                if curr_row > 0:
                    curr_list.remove(active_tab)
                    rows_tabs[curr_row - 1].append(active_tab)
                    context.scene.zz_active_category_idx = curr_row - 1
            elif direction == 'DOWN':
                if curr_row < len(rows_tabs) - 1:
                    curr_list.remove(active_tab)
                    rows_tabs[curr_row + 1].append(active_tab)
                    context.scene.zz_active_category_idx = curr_row + 1

    set_rows_data(context, rows_tabs, rows_names, rows_collapsed)

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

class ZZ_OT_ToggleCategoryMoveMode(bpy.types.Operator):
    """切换 1 级分类移动模式 (点击 [X] 进入/退出模式)"""
    bl_idname = "zz.toggle_category_move_mode"
    bl_label = "1级分类移动模式"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        scene.zz_category_move_mode = not scene.zz_category_move_mode
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}

class ZZ_OT_MoveTabLeft(bpy.types.Operator):
    """向左移动当前分页"""
    bl_idname = "zz.move_tab_left"
    bl_label = "向左移动"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        _move_active_tab(context, 'LEFT')
        return {'FINISHED'}

class ZZ_OT_MoveTabRight(bpy.types.Operator):
    """向右移动当前分页"""
    bl_idname = "zz.move_tab_right"
    bl_label = "向右移动"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        _move_active_tab(context, 'RIGHT')
        return {'FINISHED'}

class ZZ_OT_MoveTabUp(bpy.types.Operator):
    """向上移动当前分页"""
    bl_idname = "zz.move_tab_up"
    bl_label = "向上移动"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        _move_active_tab(context, 'UP')
        return {'FINISHED'}

class ZZ_OT_MoveTabDown(bpy.types.Operator):
    """向下移动当前分页"""
    bl_idname = "zz.move_tab_down"
    bl_label = "向下移动"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        _move_active_tab(context, 'DOWN')
        return {'FINISHED'}

class ZZ_OT_SmartRowAction(bpy.types.Operator):
    """智能行操作：没有空行时在最下方新增一行；有空行时清理无分页的空行"""
    bl_idname = "zz.smart_row_action"
    bl_label = "新增/清理行 (O)"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
        has_empty = any(len(r) == 0 for r in rows_tabs)

        if has_empty:
            # 如果存在空行，则不新增，修改行为为删除无分页的空行
            new_tabs, new_names, new_collapsed = [], [], []
            for t_list, name, col in zip(rows_tabs, rows_names, rows_collapsed):
                if len(t_list) > 0:
                    new_tabs.append(t_list)
                    new_names.append(name)
                    new_collapsed.append(col)
            if not new_tabs:
                new_tabs = [[]]
                new_names = ["常用板块"]
                new_collapsed = [False]
            set_rows_data(context, new_tabs, new_names, new_collapsed)
        else:
            # 如果没有空行，则在最下方新增一行
            rows_tabs.append([])
            rows_names.append(f"分组 {len(rows_tabs)}")
            rows_collapsed.append(False)
            set_rows_data(context, rows_tabs, rows_names, rows_collapsed)

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}

class ZZ_OT_MoveTab(bpy.types.Operator):
    """在面板中上下左右移动当前分页的位置"""
    bl_idname = "zz.move_tab"
    bl_label = "移动分页"
    bl_options = {'INTERNAL', 'UNDO'}

    direction: bpy.props.EnumProperty(
        items=[
            ('LEFT', "向左移动", ""),
            ('RIGHT', "向右移动", ""),
            ('UP', "向上移动", ""),
            ('DOWN', "向下移动", "")
        ],
        default='LEFT'
    )

    def execute(self, context):
        _move_active_tab(context, self.direction)
        return {'FINISHED'}

class ZZ_OT_ResetTabOrder(bpy.types.Operator):
    """将分页显示顺序恢复为默认状态"""
    bl_idname = "zz.reset_tab_order"
    bl_label = "重置分页排序"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        set_rows_data(context, [list(r) for r in DEFAULT_ROWS_TABS], list(DEFAULT_ROWS_NAMES), [False, False])
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        self.report({'INFO'}, "分页排序已恢复默认")
        return {'FINISHED'}

class ZZ_OT_Dummy(bpy.types.Operator):
    """无功能的占位操作符"""
    bl_idname = "zz.dummy"
    bl_label = ""
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'CANCELLED'}

import time

_CLICK_STATE = {"time": 0.0, "row": -1}

class ZZ_OT_ClickRowName(bpy.types.Operator):
    """单击切换分类，双击编辑分类名称"""
    bl_idname = "zz.click_row_name"
    bl_label = "选择/重命名分类"
    bl_options = {'INTERNAL'}

    row_index: bpy.props.IntProperty(default=1)

    def execute(self, context):
        now = time.time()
        last_time = _CLICK_STATE["time"]
        last_row = _CLICK_STATE["row"]

        is_double = (now - last_time < 0.6) and (last_row == self.row_index)
        rows_tabs, rows_names, _ = get_rows_data(context)

        if is_double:
            if 1 <= self.row_index <= len(rows_names):
                context.scene.zz_editing_row = 0
                context.scene.zz_edit_name_buf = rows_names[self.row_index - 1]
                context.scene.zz_editing_row = self.row_index
            _CLICK_STATE["time"] = 0.0
            _CLICK_STATE["row"] = -1
        else:
            idx = self.row_index - 1
            if 0 <= idx < len(rows_tabs):
                context.scene.zz_active_category_idx = idx
                r_list = rows_tabs[idx]
                if r_list:
                    curr_tab = getattr(context.scene, "zz_active_tab", "")
                    if curr_tab not in r_list:
                        context.scene.zz_active_tab = r_list[0]
            _CLICK_STATE["time"] = now
            _CLICK_STATE["row"] = self.row_index

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}

class ZZ_OT_ToggleRowCollapse(bpy.types.Operator):
    """折叠/展开当前行"""
    bl_idname = "zz.toggle_row_collapse"
    bl_label = "折叠行"
    bl_options = {'INTERNAL'}

    row_index: bpy.props.IntProperty(default=1)

    def execute(self, context):
        rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
        idx = self.row_index - 1
        if 0 <= idx < len(rows_collapsed):
            rows_collapsed[idx] = not rows_collapsed[idx]
            set_rows_data(context, rows_tabs, rows_names, rows_collapsed)
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return {'FINISHED'}

_MOVE_TO_CAT_ITEMS_CACHE = []

def get_move_to_cat_enum_items(self, context):
    global _MOVE_TO_CAT_ITEMS_CACHE
    try:
        rows_tabs, rows_names, _ = get_rows_data(context)
        scene = getattr(context, "scene", None)
        active_tab = getattr(scene, "zz_active_tab", "ALIGN") if scene else "ALIGN"

        curr_row = -1
        for r_i, r_list in enumerate(rows_tabs):
            if active_tab in r_list:
                curr_row = r_i
                break

        if curr_row == -1 and scene:
            active_cat_idx = getattr(scene, "zz_active_category_idx", 0)
            if 0 <= active_cat_idx < len(rows_names):
                curr_row = active_cat_idx
            else:
                curr_row = 0

        curr_cat_name = rows_names[curr_row] if (0 <= curr_row < len(rows_names)) else "未指定分类"

        items = [("-1", curr_cat_name, f"当前分类：{curr_cat_name}", "", 0)]

        for i, name in enumerate(rows_names):
            if i == curr_row:
                continue  # 不在下拉列表中重复显示当前所在的 1 级分类名称
            identifier = str(i)
            display_name = name
            description = f"移动至「{name}」分类"
            items.append((identifier, display_name, description, "", i + 1))

        _MOVE_TO_CAT_ITEMS_CACHE = items
        return _MOVE_TO_CAT_ITEMS_CACHE
    except Exception:
        _MOVE_TO_CAT_ITEMS_CACHE = [("-1", "1 级分类", "", "", 0)]
        return _MOVE_TO_CAT_ITEMS_CACHE

def _on_move_to_category_update(self, context):
    val = getattr(self, "zz_move_to_category_target", "-1")
    if not val or val == "-1":
        return

    try:
        target_idx = int(val)
        self["zz_move_to_category_target"] = 0
    except Exception:
        return

    rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
    active_tab = getattr(context.scene, "zz_active_tab", "ALIGN")

    curr_row = -1
    for r_i, r_list in enumerate(rows_tabs):
        if active_tab in r_list:
            curr_row = r_i
            r_list.remove(active_tab)
            break

    if 0 <= target_idx < len(rows_tabs):
        rows_tabs[target_idx].append(active_tab)

    set_rows_data(context, rows_tabs, rows_names, rows_collapsed)

    if curr_row != -1 and 0 <= curr_row < len(rows_tabs):
        context.scene.zz_active_category_idx = curr_row
        remain_list = rows_tabs[curr_row]
        if remain_list:
            context.scene.zz_active_tab = remain_list[0]

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

class ZZ_OT_MoveToCategory(bpy.types.Operator):
    """将当前 2 级功能板块移动至所选 1 级分类中，并保持当前分类显示"""
    bl_idname = "zz.move_to_category"
    bl_label = "移动至 1 级分类"
    bl_options = {'INTERNAL', 'UNDO'}

    target_category: bpy.props.EnumProperty(
        name="目标分类",
        description="选择要移动到的 1 级分类",
        items=get_move_to_cat_enum_items
    )

    def execute(self, context):
        try:
            target_idx = int(self.target_category)
        except ValueError:
            return {'CANCELLED'}

        rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
        active_tab = getattr(context.scene, "zz_active_tab", "ALIGN")

        curr_row = -1
        for r_i, r_list in enumerate(rows_tabs):
            if active_tab in r_list:
                curr_row = r_i
                r_list.remove(active_tab)
                break

        if 0 <= target_idx < len(rows_tabs):
            rows_tabs[target_idx].append(active_tab)

        set_rows_data(context, rows_tabs, rows_names, rows_collapsed)

        # 保持显示当前的 1 级分类
        if curr_row != -1 and 0 <= curr_row < len(rows_tabs):
            context.scene.zz_active_category_idx = curr_row
            remain_list = rows_tabs[curr_row]
            if remain_list:
                context.scene.zz_active_tab = remain_list[0]

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}

# =========================================================================
# 3. 整合 UI 面板
# =========================================================================

class ZZ_PT_MainPanel(bpy.types.Panel):
    """在 Blender N-Panel (侧边栏) 的统一整合面板"""
    bl_label = ""
    bl_idname = "VIEW3D_PT_zz_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '我的工具'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        try:
            rows_tabs, rows_names, rows_collapsed = get_rows_data(context)
            all_tabs = get_all_rows_tabs(context)

            active_tab = getattr(scene, "zz_active_tab", "ALIGN")
            if active_tab not in all_tabs:
                active_tab = all_tabs[0] if all_tabs else "ALIGN"

            curr_row = -1
            curr_idx = -1
            for r_i, r_list in enumerate(rows_tabs):
                if active_tab in r_list:
                    curr_row = r_i
                    curr_idx = r_list.index(active_tab)
                    break

            if curr_row == -1:
                active_cat_idx = getattr(scene, "zz_active_category_idx", 0)
                if active_cat_idx >= len(rows_tabs):
                    active_cat_idx = max(0, len(rows_tabs) - 1)
                curr_row = active_cat_idx

            is_cat_move_mode = getattr(scene, "zz_category_move_mode", False)

            if is_cat_move_mode:
                can_move_up = False
                can_move_down = False
                can_move_left = (len(rows_names) > 1)
                can_move_right = (len(rows_names) > 1)
            else:
                is_far_left = (curr_idx % 4 == 0)
                is_far_right = (curr_idx % 4 == 3) or (curr_row >= 0 and curr_idx == len(rows_tabs[curr_row]) - 1)
                can_move_left = (curr_row >= 0 and curr_idx >= 0 and (
                    (not is_far_left and curr_idx > 0) or
                    (is_far_left and (curr_row > 0 or len(rows_tabs) > 1))
                ))
                can_move_right = (curr_row >= 0 and curr_idx >= 0 and (
                    (not is_far_right and curr_idx < len(rows_tabs[curr_row]) - 1) or
                    (is_far_right and (curr_row < len(rows_tabs) - 1 or len(rows_tabs) > 1))
                ))
                can_move_up = (curr_row > 0)
                can_move_down = (curr_row >= 0 and curr_row < len(rows_tabs) - 1)

            main_top_row = layout.row(align=False)

            # 左侧：一级分类标签 + 二级功能选项卡
            tabs_col = main_top_row.column(align=True)
            editing_row = getattr(scene, "zz_editing_row", 0)

            # 1. 一级分类标签栏 (Tabbed Category Pages - 始终只保持 1 行)
            cat_box = tabs_col.column(align=True)
            cat_row = cat_box.row(align=True)
            cat_row.scale_y = 1.5
            for i, r_name in enumerate(rows_names):
                row_num = i + 1
                is_active_cat = (i == curr_row)
                col = cat_row.column(align=True)

                if editing_row == row_num:
                    col.prop(scene, "zz_edit_name_buf", text="")
                else:
                    try:
                        op_c = col.operator("zz.click_row_name", text=r_name, emboss=True, depress=is_active_cat)
                        if op_c:
                            op_c.row_index = row_num
                    except Exception:
                        col.label(text=r_name)

            tabs_col.separator()

            # 2. 二级功能选项卡栏 (Sub-tabs of Active Category Page, 固定每行 4 个单元格)
            if 0 <= curr_row < len(rows_tabs):
                active_r_list = rows_tabs[curr_row]
                if active_r_list:
                    for chunk_idx in range(0, len(active_r_list), 4):
                        sub_row = tabs_col.row(align=True)
                        sub_row.scale_y = 1.1
                        for slot in range(4):
                            idx = chunk_idx + slot
                            col = sub_row.column(align=True)
                            if idx < len(active_r_list):
                                tab_id = active_r_list[idx]
                                tab_label = TAB_INFO.get(tab_id, tab_id)
                                col.prop_enum(scene, "zz_active_tab", value=tab_id, text=tab_label)
                            else:
                                col.label(text="")
                else:
                    empty_row = tabs_col.row(align=True)
                    empty_row.label(text="(当前分类为空，请使用 ▲/▼ 调入功能)", icon='INFO')

            # 右侧：固定小尺寸控制按键组 (D-pad 十字方向键 + 底部 [ O ] 新增行 / [ X ] 删除空行)
            ctrl_col = main_top_row.column(align=True)
            ctrl_col.alignment = 'RIGHT'

            # --- 顶部: 1 级分类下拉选择框 (微调对齐下方 3 个按钮的总宽度) ---
            top_pad = ctrl_col.row(align=True)
            top_pad.alignment = 'RIGHT'
            top_pad.scale_x = 0.95
            top_pad.prop(scene, "zz_move_to_category_target", text="")

            # --- 第一行: [ X ] 模式切换键 (位于 [◄] 正上方) + [ ▲ ] 上移按键 ---
            row1 = ctrl_col.row(align=True)
            row1.alignment = 'RIGHT'

            sub_x = row1.row(align=True)
            sub_x.operator("zz.toggle_category_move_mode", text="", icon="ARROW_LEFTRIGHT", depress=is_cat_move_mode)

            sub_up = row1.row(align=True)
            sub_up.enabled = can_move_up
            sub_up.operator("zz.move_tab_up", text="", icon="TRIA_UP")

            row1.label(text="", icon="BLANK1")

            # --- 第二行: [ ◄ ] 左移  +  [ O ] 智能新增/清理行  +  [ ► ] 右移 ---
            row2 = ctrl_col.row(align=True)
            row2.alignment = 'RIGHT'

            sub_l = row2.row(align=True)
            sub_l.enabled = can_move_left
            sub_l.operator("zz.move_tab_left", text="", icon="TRIA_LEFT")

            sub_o = row2.row(align=True)
            sub_o.operator("zz.smart_row_action", text="", icon="EVENT_O")

            sub_r = row2.row(align=True)
            sub_r.enabled = can_move_right
            sub_r.operator("zz.move_tab_right", text="", icon="TRIA_RIGHT")

            # --- 第三行: [ ▼ ] 下移按键 ---
            row3 = ctrl_col.row(align=True)
            row3.alignment = 'RIGHT'
            row3.label(text="", icon="BLANK1")
            sub_dn = row3.row(align=True)
            sub_dn.enabled = can_move_down
            sub_dn.operator("zz.move_tab_down", text="", icon="TRIA_DOWN")
            row3.label(text="", icon="BLANK1")

            # 3. 下方各模块的专属界面
            box = layout.box()
            
            try:
                if active_tab == 'ALIGN':
                    align.draw_align_ui(box, context)
                elif active_tab == 'LOADER':
                    loader.draw_loader_ui(box, context)
                elif active_tab == 'RESTART':
                    restart.draw_restart_ui(box, context)
                elif active_tab == 'LXXW':
                    lxxw.draw_lxxw_ui(box, context)
                elif active_tab == 'MBQH':
                    mbqh.draw_mbqh_ui(box, context)
                elif active_tab == 'EXTRUDE':
                    extrude.draw_extrude_ui(box, context)
                elif active_tab == 'SJQH':
                    sjqh.draw_sjqh_ui(box, context)
                elif active_tab == 'TP':
                    tp.ui.draw_tp_ui(box, context)
                elif active_tab == 'DYTOPO':
                    softwrap2.draw_softwrap_ui(box, context)
                elif active_tab == 'SLIDE_EDGE':
                    slide_edge.draw_slide_edge_ui(box, context)
                elif active_tab == 'LOOPTOOLS':
                    looptools.draw_looptools_ui(box, context)
                elif active_tab == 'LIGHT':
                    light.draw_light_ui(box, context)
                elif active_tab == 'TEXTURE_SCENE':
                    grabdoc.draw_grabdoc_ui(box, context)
                elif active_tab == 'USE_TRANS':
                    use.draw_use_ui(box, context)
                elif active_tab == 'AUTO_REMESH':
                    quad_remesher_1_4.modded_ui.draw_quad_remesher_ui(box, context)
                elif active_tab == 'SIMPLE_BAKE':
                    SimpleBake.ui.panel.draw_simplebake_ui(box, context)
                elif active_tab == 'PIE_MENU':
                    pme_mod = globals().get('pie_menu_editor')
                    if pme_mod is None:
                        try:
                            from . import pie_menu_editor as pme_mod
                        except Exception:
                            pme_mod = None
                    if pme_mod and hasattr(pme_mod, "draw_pie_menu_editor_ui"):
                        pme_mod.draw_pie_menu_editor_ui(box, context)
                    else:
                        box.label(text="饼菜单模块未加载", icon='ERROR')

            except Exception as e:
                box.label(text=f"界面加载错误: {e}", icon='ERROR')
        except Exception as e:
            layout.label(text=f"面板加载错误: {e}", icon='ERROR')

# =========================================================================
# 4. 注册与注销机制 (Register / Unregister)
# =========================================================================

classes = (
    ZZ_Preferences,
    ZZ_OT_MoveTab,
    ZZ_OT_MoveTabLeft,
    ZZ_OT_MoveTabRight,
    ZZ_OT_MoveTabUp,
    ZZ_OT_MoveTabDown,
    ZZ_OT_SmartRowAction,
    ZZ_OT_ResetTabOrder,
    ZZ_OT_Dummy,
    ZZ_OT_ClickRowName,
    ZZ_OT_ToggleRowCollapse,
    ZZ_OT_MoveToCategory,
    ZZ_OT_ToggleCategoryMoveMode,
    ZZ_PT_MainPanel,
)

def register():
    # 1. 注册本地类
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"ZZ: Failed to register {cls.__name__}: {e}")
        
    # 2. 注册场景级导航属性
    bpy.types.Scene.zz_category_move_mode = bpy.props.BoolProperty(
        name="1级分类移动模式",
        default=False
    )

    bpy.types.Scene.zz_rows_tabs_data = bpy.props.StringProperty(
        name="行分页数据",
        default=""
    )
    bpy.types.Scene.zz_rows_names_data = bpy.props.StringProperty(
        name="行名称数据",
        default=""
    )
    bpy.types.Scene.zz_rows_collapsed_data = bpy.props.StringProperty(
        name="行折叠数据",
        default=""
    )

    bpy.types.Scene.zz_move_to_category_target = bpy.props.EnumProperty(
        name="",
        description="选择要移动到的 1 级分类",
        items=get_move_to_cat_enum_items,
        update=_on_move_to_category_update
    )

    bpy.types.Scene.zz_editing_row = bpy.props.IntProperty(
        name="当前编辑行",
        default=0
    )

    bpy.types.Scene.zz_active_category_idx = bpy.props.IntProperty(
        name="当前分类索引",
        default=get_saved_active_category_idx(),
        update=_on_active_category_idx_update
    )

    bpy.types.Scene.zz_edit_name_buf = bpy.props.StringProperty(
        name="编辑名称缓存",
        default="",
        update=_on_edit_name_buf_update
    )

    bpy.types.Scene.zz_active_tab = bpy.props.EnumProperty(
        name="页面",
        description="选择要管理的功能板块",
        items=[
            ('ALIGN', "对齐 (Align)", "切换至对齐工具板块", "NONE", 0),
            ('LOADER', "插件加载", "切换至插件加载模块板块", "NONE", 1),
            ('RESTART', "一键重启", "切换至快速重启 Blender 板块", "NONE", 2),
            ('LXXW', "工整的螺旋纤维", "切换至螺旋纤维板块", "NONE", 3),
            ('MBQH', "窗口切换", "切换至窗口切换板块", "NONE", 4),
            ('EXTRUDE', "挤出", "切换至智慧挤出工具板块", "NONE", 5),
            ('SJQH', "双击切换", "切换至双击切换模式板块", "NONE", 6),
            ('TP', "TP拓扑", "切换至TP拓扑工具板块", "NONE", 7),
            ('DYTOPO', "动态拓扑", "切换至动态拓扑 (Softwrap) 板块", "NONE", 8),
            ('SLIDE_EDGE', "边滑动", "切换至边滑动 (Slide Edge) 工具板块", "NONE", 9),
            ('LOOPTOOLS', "LoopTools ", "切换至 LoopTools 工具板块", "NONE", 10),
            ('LIGHT', "灯光", "切换至灯光工具板块", "NONE", 11),
            ('TEXTURE_SCENE', "纹理场景", "切换至纹理场景 (GrabDoc) 板块", "NONE", 12),
            ('USE_TRANS', "use翻译", "切换至 USE 全局翻译板块", "NONE", 13),
            ('AUTO_REMESH', "自动重构", "切换至四边面自动重构 (Quad Remesher) 板块", "NONE", 14),
            ('SIMPLE_BAKE', "简单烘焙", "切换至 SimpleBake 简单烘焙板块", "NONE", 15),
            ('PIE_MENU', "饼菜单", "切换至饼菜单编辑器 (Pie Menu Editor) 板块", "NONE", 16),
        ],
        default=get_saved_active_tab(),
        update=_on_active_tab_update
    )

    bpy.types.Scene.smart_extrude_mode = bpy.props.EnumProperty(
        name="智慧挤出模式",
        description="选择按 E 键挤出时的模式",
        items=[
            ('SMART', "群组法线", "按面群组法线方向智能挤出与修剪"),
            ('ALONG_NORMAL', "沿法线", "沿顶点/面法线方向进行挤出"),
            ('INDIVIDUAL', "个别面", "个别独立面按各自法线挤出 (Blender 4.5+)"),
        ],
        default='SMART',
        update=lambda self, context: getattr(extrude, "on_smart_extrude_mode_update", lambda s, c: None)(self, context)
    )
    
    # 3. 注册子模块中的操作符和属性
    _submodule_names = ['align', 'loader', 'restart', 'lxxw', 'mbqh', 'extrude', 'sjqh', 'tp', 'softwrap2', 'slide_edge', 'looptools', 'light', 'grabdoc', 'use', 'quad_remesher_1_4', 'SimpleBake', 'pie_menu_editor']
    for mod_name in _submodule_names:
        mod = globals().get(mod_name)
        if mod is not None:
            try:
                mod.register()
            except Exception as e:
                print(f"ZZ: Failed to register submodule {mod_name}: {e}")

    # 4. 注册 load_post 自动恢复句柄
    if _on_blend_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_blend_load_post)

def unregister():
    # 0. 注销 load_post 自动恢复句柄
    if _on_blend_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_blend_load_post)

    # 1. 注销子模块
    _submodule_names_rev = ['pie_menu_editor', 'SimpleBake', 'quad_remesher_1_4', 'use', 'grabdoc', 'light', 'looptools', 'slide_edge', 'softwrap2', 'tp', 'sjqh', 'extrude', 'mbqh', 'lxxw', 'restart', 'loader', 'align']
    for mod_name in _submodule_names_rev:
        mod = globals().get(mod_name)
        if mod is not None:
            try:
                mod.unregister()
            except Exception as e:
                print(f"ZZ: Failed to unregister submodule {mod_name}: {e}")
    
    # 2. 注销场景导航属性
    for prop in ("smart_extrude_mode", "zz_active_tab", "zz_active_category_idx", "zz_category_move_mode", "zz_move_to_category_target", "zz_editing_row", "zz_edit_name_buf", "zz_rows_tabs_data", "zz_rows_names_data", "zz_rows_collapsed_data"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
        
    # 3. 注销本地类
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"ZZ: Failed to unregister {cls.__name__}: {e}")

if __name__ == "__main__":
    register()
