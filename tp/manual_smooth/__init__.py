# -*- coding: utf-8 -*-
bl_info = {
    "name": "手动平滑",
    "description": "RetopoFlow 手动拓扑/手动平滑整合工具",
    "author": "Orange Turbine",
    "version": (4, 0, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > 我的工具",
    "category": "3D View",
}

import bpy
from .retopoflow.rftool_tweak.tweak import RFBrush_Tweak
from .retopoflow.rftool_relax.relax import RFBrush_Relax
from .retopoflow.common.operator import wrap_property
from .retopoflow.preferences import RF_Prefs


class RF_Tweak_Props(bpy.types.PropertyGroup):
    brush_radius: wrap_property(
        RFBrush_Tweak, 'radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units',
        subtype='PIXEL',
        min=1,
        max=1000,
        default=100,
    )
    brush_falloff: wrap_property(
        RFBrush_Tweak, 'falloff', 'float',
        name='Falloff',
        description='Brush falloff',
        min=0.0,
        max=1.00,
        default=1.00,
    )
    brush_strength: wrap_property(
        RFBrush_Tweak, 'strength', 'float',
        name='Strength',
        description='Strength of the brush',
        min=0.01,
        max=1.00,
        default=0.75,
    )
    include_corners: bpy.props.BoolProperty(
        name='Corners',
        description='Include corners',
        default=True,
    )
    include_occluded: bpy.props.BoolProperty(
        name='Occluded',
        description='Include occluded vertices',
        default=False,
    )
    mask_boundary: bpy.props.EnumProperty(
        name='Mask: Boundary',
        items=[
            ('INCLUDE', 'Include', 'Tweak boundary vertices', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Slide along boundary', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not tweak boundary vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_symmetry: bpy.props.EnumProperty(
        name='Mask: Symmetry',
        items=[
            ('INCLUDE', 'Include', 'Tweak symmetry vertices', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Slide along symmetry plane', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not tweak symmetry vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='SLIDE',
    )
    mask_selected: bpy.props.EnumProperty(
        name='Mask: Selected',
        items=[
            ('ALL',     'All',     'Tweak all vertices', 'SELECT_EXTEND', 2),
            ('ONLY',    'Only',    'Tweak selected vertices only', 'SELECT_INTERSECT', 1),
            ('EXCLUDE', 'Exclude', 'Exclude selected vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='ALL',
    )


class RF_Relax_Props(bpy.types.PropertyGroup):
    brush_radius: wrap_property(
        RFBrush_Relax, 'radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units',
        subtype='PIXEL',
        min=1,
        max=1000,
        default=100,
    )
    brush_falloff: wrap_property(
        RFBrush_Relax, 'falloff', 'float',
        name='Falloff',
        description='Brush falloff',
        min=0.0,
        max=1.00,
        default=1.00,
    )
    brush_strength: wrap_property(
        RFBrush_Relax, 'strength', 'float',
        name='Strength',
        description='Strength of the brush',
        min=0.01,
        max=1.00,
        default=0.5,
    )
    algorithm_method: bpy.props.EnumProperty(
        name='Algorithm: Method',
        items=[
            ('STEPS', 'Steps', 'Integration: Steps'),
            ('RK4',   'RK4',   'Integration: RK4'),
        ],
        default='STEPS',
    )
    algorithm_iterations: bpy.props.IntProperty(
        name='Algorithm: Iterations',
        min=1,
        max=10,
        default=2,
    )
    algorithm_max_distance_radius: bpy.props.FloatProperty(
        name='Algorithm: Max Distance (Radius)',
        min=0.001,
        max=1.0,
        default=0.10,
    )
    algorithm_max_distance_edges: bpy.props.FloatProperty(
        name='Algorithm: Max Distance (Edges)',
        min=0.001,
        max=1.0,
        default=0.05,
    )
    algorithm_prevent_bounce: bpy.props.BoolProperty(
        name='Algorithm: Prevent Bounce',
        default=False,
    )
    algorithm_average_edge_lengths: bpy.props.BoolProperty(
        name='Algorithm: Average Edge Lengths',
        default=True,
    )
    algorithm_straighten_edges: bpy.props.BoolProperty(
        name='Algorithm: Straighten Edges',
        default=True,
    )
    algorithm_average_face_radius: bpy.props.BoolProperty(
        name='Algorithm: Average Face Radius',
        default=True,
    )
    algorithm_average_face_lengths: bpy.props.BoolProperty(
        name='Algorithm: Average Face-Edge Lengths',
        default=False,
    )
    algorithm_average_face_angles: bpy.props.BoolProperty(
        name='Algorithm: Average Face Angles',
        default=True,
    )
    algorithm_correct_flipped_faces: bpy.props.BoolProperty(
        name='Algorithm: Correct Flipped Faces',
        default=False,
    )
    include_corners: bpy.props.BoolProperty(
        name='Corners',
        default=True,
    )
    include_occluded: bpy.props.BoolProperty(
        name='Occluded',
        default=False,
    )
    mask_boundary: bpy.props.EnumProperty(
        name='Mask: Boundary',
        items=[
            ('INCLUDE', 'Include', 'Relax boundary vertices', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Slide along boundary', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not relax boundary vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_symmetry: bpy.props.EnumProperty(
        name='Mask: Symmetry',
        items=[
            ('INCLUDE', 'Include', 'Relax symmetry vertices', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Slide along symmetry plane', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not relax symmetry vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='SLIDE',
    )
    mask_selected: bpy.props.EnumProperty(
        name='Mask: Selected',
        items=[
            ('ALL',     'All',     'Relax all vertices', 'SELECT_EXTEND', 2),
            ('ONLY',    'Only',    'Relax selected vertices only', 'SELECT_INTERSECT', 1),
            ('EXCLUDE', 'Exclude', 'Exclude selected vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='ALL',
    )


class ZZ_OT_ActivateTweakTool(bpy.types.Operator):
    """激活/退出 RetopoFlow 调整 (Tweak) 拓扑工具"""
    bl_idname = "zz.activate_tweak_tool"
    bl_label = "调整 (Tweak)"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        wm = context.window_manager
        if hasattr(context.scene, "tp_straight_mode"):
            context.scene.tp_straight_mode = False
        if getattr(wm, "tp_topology_running", False):
            try:
                bpy.ops.object.tp_topology_draw()
            except Exception:
                wm.tp_topology_running = False

        if hasattr(context.scene, "tp_active_subtab"):
            context.scene.tp_active_subtab = 'TWEAK'

        if context.mode != 'EDIT_MESH':
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except Exception as e:
                self.report({'WARNING'}, f"无法切换到编辑模式: {e}")
                return {'CANCELLED'}
        try:
            from .retopoflow.rfcore import RFCore
            if RFCore.selected_RFTool_idname == 'retopoflow.tweak':
                RFCore.tool_changed(context, 'VIEW_3D', '')
                RFCore.stop()
            else:
                RFCore.tool_changed(context, 'VIEW_3D', 'retopoflow.tweak')
        except Exception as e:
            self.report({'ERROR'}, f"操作调整工具失败: {e}")
            return {'CANCELLED'}
        
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class ZZ_OT_ActivateRelaxTool(bpy.types.Operator):
    """激活/退出 RetopoFlow 松弛 (Relax) 拓扑工具"""
    bl_idname = "zz.activate_relax_tool"
    bl_label = "松弛 (Relax)"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        wm = context.window_manager
        if hasattr(context.scene, "tp_straight_mode"):
            context.scene.tp_straight_mode = False
        if getattr(wm, "tp_topology_running", False):
            try:
                bpy.ops.object.tp_topology_draw()
            except Exception:
                wm.tp_topology_running = False

        if hasattr(context.scene, "tp_active_subtab"):
            context.scene.tp_active_subtab = 'RELAX'

        if context.mode != 'EDIT_MESH':
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except Exception as e:
                self.report({'WARNING'}, f"无法切换到编辑模式: {e}")
                return {'CANCELLED'}
        try:
            from .retopoflow.rfcore import RFCore
            if RFCore.selected_RFTool_idname == 'retopoflow.relax':
                RFCore.tool_changed(context, 'VIEW_3D', '')
                RFCore.stop()
            else:
                RFCore.tool_changed(context, 'VIEW_3D', 'retopoflow.relax')
        except Exception as e:
            self.report({'ERROR'}, f"操作松弛工具失败: {e}")
            return {'CANCELLED'}
        
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class ZZ_OT_SwitchToEditMode(bpy.types.Operator):
    """切换至编辑模式"""
    bl_idname = "zz.switch_to_edit_mode"
    bl_label = "进入编辑模式"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        try:
            bpy.ops.object.mode_set(mode='EDIT')
        except Exception as e:
            self.report({'WARNING'}, f"无法切换到编辑模式: {e}")
        return {'FINISHED'}


classes = (
    RF_Prefs,
    RF_Tweak_Props,
    RF_Relax_Props,
    ZZ_OT_ActivateTweakTool,
    ZZ_OT_ActivateRelaxTool,
    ZZ_OT_SwitchToEditMode,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"ZZ: Failed to register class {cls.__name__}: {e}")

    bpy.types.Scene.retopoflow_prefs = bpy.props.PointerProperty(type=RF_Prefs)
    bpy.types.Scene.retopoflow_tweak = bpy.props.PointerProperty(type=RF_Tweak_Props)
    bpy.types.Scene.retopoflow_relax = bpy.props.PointerProperty(type=RF_Relax_Props)

    if getattr(bpy.app, "background", False):
        return
    try:
        from .retopoflow.rfcore import RFCore
        RFCore.register()
    except Exception as e:
        import traceback
        print(f"ZZ: Failed to register manual_smooth RFCore: {e}")
        traceback.print_exc()


def unregister():
    if getattr(bpy.app, "background", False):
        pass
    else:
        try:
            from .retopoflow.rfcore import RFCore
            RFCore.unregister()
        except Exception as e:
            import traceback
            print(f"ZZ: Failed to unregister manual_smooth RFCore: {e}")
            traceback.print_exc()

    if hasattr(bpy.types.Scene, "retopoflow_prefs"):
        del bpy.types.Scene.retopoflow_prefs
    if hasattr(bpy.types.Scene, "retopoflow_tweak"):
        del bpy.types.Scene.retopoflow_tweak
    if hasattr(bpy.types.Scene, "retopoflow_relax"):
        del bpy.types.Scene.retopoflow_relax

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"ZZ: Failed to unregister class {cls.__name__}: {e}")


def draw_manual_smooth_ui(layout, context):
    # 1. 查询当前 RetopoFlow 激活的工具 ID
    active_tool_id = ""
    try:
        from .retopoflow.rfcore import RFCore
        active_tool_id = RFCore.selected_RFTool_idname or ""
    except Exception:
        pass

    is_tweak = (active_tool_id == 'retopoflow.tweak')
    is_relax = (active_tool_id == 'retopoflow.relax')

    # 2. 工具选择与激活按键组（物体模式与编辑模式均可直接显示与点击）
    box_tools = layout.box()
    
    row = box_tools.row(align=True)
    row.scale_y = 2.8

    row.operator("zz.activate_tweak_tool", text="调整 (Tweak)", depress=is_tweak)
    row.operator("zz.activate_relax_tool", text="松弛 (Relax)", depress=is_relax)

    layout.separator()

    # 3. 当前选中工具的参数设置渲染
    box_settings = layout.box()

    try:
        from .retopoflow.rftool_tweak.tweak import RFTool_Tweak
        from .retopoflow.rftool_relax.relax import RFTool_Relax

        if is_tweak:
            RFTool_Tweak.draw_settings(context, box_settings)
        elif is_relax:
            RFTool_Relax.draw_settings(context, box_settings)
        else:
            box_settings.label(text="点击上方 [调整] 或 [松弛] 按钮激活工具，再次点击可退出模式", icon='INFO')
    except Exception as e:
        import traceback
        traceback.print_exc()
        box_settings.label(text=f"无法加载工具设置: {e}", icon='ERROR')
