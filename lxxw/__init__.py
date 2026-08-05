# -*- coding: utf-8 -*-

import bpy
import math
import numpy as np
from mathutils import Vector
from bpy.props import FloatProperty, PointerProperty, IntProperty, BoolProperty
from bpy.types import PropertyGroup
from bpy.app.handlers import persistent

# =========================================================================
# 1. 属性组定义 (Property Group)
# =========================================================================

class SpiralProperties(PropertyGroup):
    turns: IntProperty(
        name="螺旋圈数",
        description="螺旋线缠绕的圈数（偶数）",
        default=20,
        min=2,
        max=500,
        step=2,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    radius: FloatProperty(
        name="螺旋半径",
        description="螺旋线的半径（无上限）",
        default=0.1,
        min=0.01,
        precision=4,
        step=0.01,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    thickness: FloatProperty(
        name="线条粗细",
        description="螺旋线的粗细（无上限）",
        default=0.02,
        min=0.001,
        precision=3,
        step=0.005,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    spiral_count: IntProperty(
        name="螺旋线数量",
        description="同时生成的螺旋线数量",
        default=1,
        min=1,
        max=12,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    resolution: FloatProperty(
        name="分辨率",
        description="螺旋线的分辨率（每单位长度的点数）",
        default=10.0,
        min=1.0,
        max=50.0,
        precision=1,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    points_per_turn: IntProperty(
        name="每圈点数",
        description="每圈螺旋线使用的点数（值越大螺旋线越平滑）",
        default=12,
        min=4,
        max=36,
        update=lambda self, context: update_all_spirals(self, context)
    )
    
    align_ends: BoolProperty(
        name="两端对齐",
        description="使螺旋线的两端在同一轴线上",
        default=True,
        update=lambda self, context: update_all_spirals(self, context)
    )

# 存储每条曲线的螺旋线参数
class CurveSpiralParams:
    def __init__(self, turns=20, radius=0.1, thickness=0.02, spiral_count=1, resolution=10.0, points_per_turn=12, align_ends=True):
        self.turns = turns
        self.radius = radius
        self.thickness = thickness
        self.spiral_count = spiral_count
        self.resolution = resolution
        self.points_per_turn = points_per_turn
        self.align_ends = align_ends

# 存储原始曲线和螺旋线的关系，格式：{curve_obj: (spiral_obj, params)}
spiral_relationships = {}

# 存储上一次的参数值，用于检测变化
last_params = {
    'turns': 2,
    'radius': 0.1,
    'thickness': 0.02,
    'spiral_count': 1,
    'resolution': 12,
    'points_per_turn': 8,
    'align_ends': True
}

# =========================================================================
# 2. 核心计算与更新函数
# =========================================================================

def update_all_spirals(self, context):
    if not spiral_relationships:
        return
    
    selected_curves = [obj for obj in bpy.context.selected_objects if obj.type == 'CURVE']
    active_curve = None
    if selected_curves and selected_curves[0] in spiral_relationships:
        active_curve = selected_curves[0]
    
    selected_objects = bpy.context.selected_objects
    selected_spiral = None
    corresponding_curve = None
    
    for obj in selected_objects:
        for curve, (spiral, params) in spiral_relationships.items():
            if obj == spiral:
                selected_spiral = obj
                corresponding_curve = curve
                break
        if selected_spiral:
            break
    
    props = context.scene.spiral_props
    turns = props.turns
    radius = props.radius
    thickness = props.thickness
    resolution = props.resolution
    points_per_turn = props.points_per_turn
    align_ends = props.align_ends
    spiral_count = props.spiral_count
    
    global last_params
    last_params = {
        'turns': turns,
        'radius': radius,
        'thickness': thickness,
        'spiral_count': spiral_count,
        'resolution': resolution,
        'points_per_turn': points_per_turn,
        'align_ends': align_ends
    }
    
    if active_curve:
        try:
            spiral_obj, params = spiral_relationships[active_curve]
            if spiral_obj is None or active_curve.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                if active_curve in spiral_relationships:
                    del spiral_relationships[active_curve]
                return
            
            params.turns = turns
            params.radius = radius
            params.thickness = thickness
            params.resolution = resolution
            params.points_per_turn = points_per_turn
            params.align_ends = align_ends
            params.spiral_count = spiral_count
            
            spiral_obj.data.bevel_depth = thickness
            generate_spiral(active_curve, spiral_obj, params.turns, params.radius, 
                           params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
        except (ReferenceError, KeyError):
            if active_curve in spiral_relationships:
                del spiral_relationships[active_curve]
        return
    elif selected_spiral and corresponding_curve:
        try:
            spiral_obj, params = spiral_relationships[corresponding_curve]
            if spiral_obj is None or corresponding_curve.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                if corresponding_curve in spiral_relationships:
                    del spiral_relationships[corresponding_curve]
                return
            
            params.turns = turns
            params.radius = radius
            params.thickness = thickness
            params.resolution = resolution
            params.points_per_turn = points_per_turn
            params.align_ends = align_ends
            params.spiral_count = spiral_count
            
            spiral_obj.data.bevel_depth = thickness
            generate_spiral(corresponding_curve, spiral_obj, params.turns, params.radius, 
                           params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
        except (ReferenceError, KeyError):
            if corresponding_curve in spiral_relationships:
                del spiral_relationships[corresponding_curve]
        return
    
    for curve_obj, (spiral_obj, params) in list(spiral_relationships.items()):
        try:
            if curve_obj is None or spiral_obj is None:
                if curve_obj in spiral_relationships:
                    del spiral_relationships[curve_obj]
                continue
                
            if curve_obj.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                if curve_obj in spiral_relationships:
                    del spiral_relationships[curve_obj]
                continue
            
            spiral_obj.data.bevel_depth = params.thickness
            generate_spiral(curve_obj, spiral_obj, params.turns, params.radius, 
                           params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
        except ReferenceError:
            if curve_obj in spiral_relationships:
                del spiral_relationships[curve_obj]


def generate_spiral(curve_obj, spiral_obj, turns, radius, resolution, points_per_turn, align_ends=True, spiral_count=1):
    spiral_data = spiral_obj.data
    spiral_data.splines.clear()
    
    smooth_points = evaluate_curve(curve_obj, resolution, turns, points_per_turn)
    if not smooth_points:
        return
    
    curve_length = calculate_curve_length(smooth_points)
    
    actual_turns = turns
    if actual_turns % 2 != 0:
        actual_turns += 1
        
    N = len(smooth_points)
    if N < 2:
        return
        
    # 提取点和长度到 NumPy 数组
    P = np.array([pt[0] for pt in smooth_points], dtype=np.float32)  # 形状 (N, 3)
    L = np.array([pt[1] for pt in smooth_points], dtype=np.float32)  # 形状 (N,)
    
    # 向量化计算方向向量
    D = P[1:] - P[:-1]  # 形状 (N-1, 3)
    norms = np.linalg.norm(D, axis=1, keepdims=True)
    norms[norms == 0.0] = 1e-6  # 避免除以零
    D_norm = D / norms  # 形状 (N-1, 3)
    
    # 向量化计算上方向向量 up
    up = np.zeros_like(D_norm)
    mask = np.abs(D_norm[:, 2]) < 0.9
    up[mask] = [0.0, 0.0, 1.0]
    up[~mask] = [1.0, 0.0, 0.0]
    
    # 计算右方向向量 right
    right = np.cross(D_norm, up)
    right_norms = np.linalg.norm(right, axis=1, keepdims=True)
    right_norms[right_norms == 0.0] = 1e-6
    right = right / right_norms
    
    # 重新计算 up 以确保完全正交
    up = np.cross(right, D_norm)
    
    angle_offset_rad = 0.0
    
    for spiral_index in range(spiral_count):
        current_angle_offset = angle_offset_rad + (2 * np.pi * spiral_index / spiral_count if spiral_count > 1 else 0)
        
        # 向量化计算前 N-1 个螺旋点对应的角度
        t = L[:-1] / curve_length
        angle = t * actual_turns * 2 * np.pi + current_angle_offset
        
        cos_a = np.cos(angle)[:, np.newaxis]
        sin_a = np.sin(angle)[:, np.newaxis]
        
        # 计算偏移
        offset = right * cos_a * radius + up * sin_a * radius
        spiral_points_N1 = P[:-1] + offset
        
        # 计算最后一个螺旋点
        angle_last = actual_turns * 2 * np.pi + current_angle_offset
        offset_last = right[-1] * np.cos(angle_last) * radius + up[-1] * np.sin(angle_last) * radius
        last_point_spiral = P[-1] + offset_last
        
        # 合并所有螺旋点坐标 (N, 3)
        all_spiral_points = np.vstack([spiral_points_N1, last_point_spiral])
        
        # 创建样条曲线
        spline = spiral_data.splines.new('BEZIER')
        spline.bezier_points.add(N - 1)
        
        # 使用 C 层级的 foreach_set 进行超高速属性赋值
        flat_coords = all_spiral_points.ravel()
        spline.bezier_points.foreach_set("co", flat_coords)
        
        # 批量设置控制点类型以自适应曲线平滑
        for bp in spline.bezier_points:
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'


def evaluate_curve(curve_obj, resolution, turns, points_per_turn):
    curve_data = curve_obj.data
    world_matrix = curve_obj.matrix_world
    
    evaluated_points = []
    accumulated_length = 0.0
    prev_point = None
    
    for spline_index, spline in enumerate(curve_data.splines):
        if spline.type == 'BEZIER':
            points_count = len(spline.bezier_points)
        else:
            points_count = len(spline.points)
        
        if points_count < 2:
            continue
        
        spline_length = 0
        if spline.type == 'BEZIER':
            for i in range(points_count - 1):
                p1 = world_matrix @ spline.bezier_points[i].co
                p2 = world_matrix @ spline.bezier_points[i+1].co
                spline_length += (p2 - p1).length
        else:
            for i in range(points_count - 1):
                p1 = world_matrix @ spline.points[i].co.xyz
                p2 = world_matrix @ spline.points[i+1].co.xyz
                spline_length += (p2 - p1).length
        
        base_points = max(int(spline_length * resolution), 10)
        turns_factor = max(1, min(turns / 10, 10))
        points_num = int(base_points * turns_factor)
        
        min_points = int(turns * points_per_turn)
        points_num = max(points_num, min_points)
        
        max_points = 10000
        points_num = min(points_num, max_points)
        
        for i in range(points_num):
            t = i / (points_num - 1) if points_num > 1 else 0
            
            if spline.type == 'BEZIER':
                point = evaluate_bezier_point(spline, t, world_matrix)
            else:
                point = evaluate_nurbs_point(spline, t, world_matrix)
            
            if prev_point is not None:
                segment_length = (point - prev_point).length
                accumulated_length += segment_length
            
            evaluated_points.append((point, accumulated_length))
            prev_point = point
    
    return evaluated_points


def evaluate_bezier_point(spline, t, world_matrix):
    points = spline.bezier_points
    n = len(points) - 1
    
    segment_t = t * n
    segment_index = min(int(segment_t), n - 1)
    local_t = segment_t - segment_index
    
    p0 = points[segment_index].co
    p1 = points[segment_index].handle_right
    p2 = points[segment_index + 1].handle_left
    p3 = points[segment_index + 1].co
    
    t2 = local_t * local_t
    t3 = t2 * local_t
    
    point = (1 - local_t)**3 * p0 + 3 * (1 - local_t)**2 * local_t * p1 + 3 * (1 - local_t) * local_t**2 * p2 + local_t**3 * p3
    return world_matrix @ point


def evaluate_nurbs_point(spline, t, world_matrix):
    points = spline.points
    n = len(points) - 1
    
    segment_t = t * n
    segment_index = min(int(segment_t), n - 1)
    local_t = segment_t - segment_index
    
    p0 = points[segment_index].co.xyz
    p1 = points[segment_index + 1].co.xyz
    point = p0 * (1 - local_t) + p1 * local_t
    return world_matrix @ point


def calculate_curve_length(points):
    if not points:
        return 0.0
    return points[-1][1]


def check_and_update_spirals(scene=None):
    if not spiral_relationships:
        return
    
    for curve_obj, (spiral_obj, params) in list(spiral_relationships.items()):
        try:
            if curve_obj is None or spiral_obj is None:
                if curve_obj in spiral_relationships:
                    del spiral_relationships[curve_obj]
                continue
                
            if curve_obj.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                if curve_obj in spiral_relationships:
                    del spiral_relationships[curve_obj]
                continue
            
            generate_spiral(curve_obj, spiral_obj, params.turns, params.radius, 
                           params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
        except ReferenceError:
            if curve_obj in spiral_relationships:
                del spiral_relationships[curve_obj]

# =========================================================================
# 3. 监听处理器 (Persistent Handlers)
# =========================================================================

# 用于在 depsgraph 更新时防范重入循环
_is_updating_spirals = False

@persistent
def curve_update_handler(depsgraph):
    global _is_updating_spirals
    if _is_updating_spirals or not spiral_relationships:
        return
        
    # depsgraph_update_post 传递的是 depsgraph 实例
    # 我们只对真正发生改变的源曲线进行螺旋线更新
    updated_ids = {update.id for update in depsgraph.updates}
    
    for curve_obj, (spiral_obj, params) in list(spiral_relationships.items()):
        if not curve_obj or not spiral_obj:
            continue
        # 如果对应的曲线对象或其数据块被更新
        if curve_obj in updated_ids or curve_obj.data in updated_ids:
            try:
                _is_updating_spirals = True
                generate_spiral(
                    curve_obj, spiral_obj, 
                    params.turns, params.radius, params.resolution, 
                    params.points_per_turn, params.align_ends, params.spiral_count
                )
            except ReferenceError:
                pass
            finally:
                _is_updating_spirals = False

@persistent
def selection_change_handler(depsgraph):
    if not spiral_relationships:
        return
    
    selected_curves = [obj for obj in bpy.context.selected_objects if obj.type == 'CURVE']
    active_curve = None
    if selected_curves and selected_curves[0] in spiral_relationships:
        active_curve = selected_curves[0]
    
    selected_objects = bpy.context.selected_objects
    selected_spiral = None
    corresponding_curve = None
    
    for obj in selected_objects:
        for curve, (spiral, params) in spiral_relationships.items():
            if obj == spiral:
                selected_spiral = obj
                corresponding_curve = curve
                break
        if selected_spiral:
            break
            
    # 获取需要同步参数的目标
    target_curve = active_curve if active_curve else (corresponding_curve if selected_spiral else None)
    
    if target_curve:
        try:
            spiral_obj, params = spiral_relationships[target_curve]
            if spiral_obj and target_curve.name in bpy.data.objects and spiral_obj.name in bpy.data.objects:
                props = bpy.context.scene.spiral_props
                # 只有当参数不一致时才写回 UI，防止死循环触发 update
                if props.turns != params.turns:
                    props.turns = params.turns
                if props.radius != params.radius:
                    props.radius = params.radius
                if props.thickness != params.thickness:
                    props.thickness = params.thickness
                if props.resolution != params.resolution:
                    props.resolution = params.resolution
                if props.points_per_turn != params.points_per_turn:
                    props.points_per_turn = params.points_per_turn
                if props.align_ends != params.align_ends:
                    props.align_ends = params.align_ends
                if props.spiral_count != params.spiral_count:
                    props.spiral_count = params.spiral_count
        except (ReferenceError, KeyError):
            pass

# =========================================================================
# 4. 操作符 (Operators)
# =========================================================================

class LXXW_OT_AddSpiral(bpy.types.Operator):
    """为所选曲线添加一个缠绕的螺旋线"""
    bl_idname = "lxxw.add_spiral"
    bl_label = "添加螺旋线"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        selected_objects = [obj for obj in bpy.context.selected_objects if obj.type == 'CURVE']
        
        if not selected_objects:
            self.report({'ERROR'}, "请先选择一条曲线对象")
            return {'CANCELLED'}
        
        props = context.scene.spiral_props
        turns = props.turns
        radius = props.radius
        thickness = props.thickness
        resolution = props.resolution
        points_per_turn = props.points_per_turn
        align_ends = props.align_ends
        spiral_count = props.spiral_count
        
        for curve_obj in selected_objects:
            valid_existing_spiral = False
            if curve_obj in spiral_relationships and spiral_relationships[curve_obj] is not None:
                try:
                    spiral_obj, params = spiral_relationships[curve_obj]
                    if spiral_obj.name in bpy.data.objects:
                        params.turns = turns
                        params.radius = radius
                        params.thickness = thickness
                        params.resolution = resolution
                        params.points_per_turn = points_per_turn
                        params.align_ends = align_ends
                        params.spiral_count = spiral_count
                        
                        spiral_obj.data.bevel_depth = thickness
                        generate_spiral(curve_obj, spiral_obj, params.turns, params.radius, 
                                       params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
                        valid_existing_spiral = True
                except ReferenceError:
                    del spiral_relationships[curve_obj]
            
            if not valid_existing_spiral:
                spiral_data = bpy.data.curves.new(name=f"{curve_obj.name}_螺旋线", type='CURVE')
                spiral_data.dimensions = '3D'
                spiral_data.resolution_u = 12
                spiral_data.fill_mode = 'FULL'
                spiral_data.bevel_depth = thickness
                
                spiral_obj = bpy.data.objects.new(f"{curve_obj.name}_螺旋线", spiral_data)
                bpy.context.collection.objects.link(spiral_obj)
                
                params = CurveSpiralParams(
                    turns=turns,
                    radius=radius,
                    thickness=thickness,
                    spiral_count=spiral_count,
                    resolution=resolution,
                    points_per_turn=points_per_turn,
                    align_ends=align_ends
                )
                
                spiral_relationships[curve_obj] = (spiral_obj, params)
                generate_spiral(curve_obj, spiral_obj, params.turns, params.radius, 
                               params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
                
                spiral_obj.select_set(True)
        
        return {'FINISHED'}


class LXXW_OT_UpdateSpirals(bpy.types.Operator):
    """更新所有已创建的螺旋线"""
    bl_idname = "lxxw.update_spirals"
    bl_label = "更新所有螺旋线"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.spiral_props
        turns = props.turns
        radius = props.radius
        thickness = props.thickness
        resolution = props.resolution
        points_per_turn = props.points_per_turn
        align_ends = props.align_ends
        spiral_count = props.spiral_count
        
        selected_curves = [obj for obj in bpy.context.selected_objects if obj.type == 'CURVE']
        active_curve = None
        if selected_curves and selected_curves[0] in spiral_relationships:
            active_curve = selected_curves[0]
        
        if active_curve:
            try:
                spiral_obj, params = spiral_relationships[active_curve]
                if spiral_obj is None or active_curve.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                    if active_curve in spiral_relationships:
                        del spiral_relationships[active_curve]
                    return {'FINISHED'}
                
                params.turns = turns
                params.radius = radius
                params.thickness = thickness
                params.resolution = resolution
                params.points_per_turn = points_per_turn
                params.align_ends = align_ends
                params.spiral_count = spiral_count
                
                spiral_obj.data.bevel_depth = thickness
                generate_spiral(active_curve, spiral_obj, params.turns, params.radius, 
                               params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
            except (ReferenceError, KeyError):
                if active_curve in spiral_relationships:
                    del spiral_relationships[active_curve]
            return {'FINISHED'}
        
        for curve_obj, (spiral_obj, params) in list(spiral_relationships.items()):
            if curve_obj is None or spiral_obj is None or curve_obj.name not in bpy.data.objects or spiral_obj.name not in bpy.data.objects:
                if curve_obj in spiral_relationships:
                    del spiral_relationships[curve_obj]
                continue
            
            spiral_obj.data.bevel_depth = thickness
            generate_spiral(curve_obj, spiral_obj, params.turns, params.radius, 
                           params.resolution, params.points_per_turn, params.align_ends, params.spiral_count)
        
        return {'FINISHED'}


class LXXW_OT_ClearSpirals(bpy.types.Operator):
    """清除所有已创建的螺旋线"""
    bl_idname = "lxxw.clear_spirals"
    bl_label = "清除所有螺旋线"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        for curve_obj, (spiral_obj, params) in list(spiral_relationships.items()):
            try:
                if spiral_obj is not None and spiral_obj.name in bpy.data.objects:
                    bpy.data.objects.remove(spiral_obj)
            except ReferenceError:
                pass
        
        spiral_relationships.clear()
        return {'FINISHED'}

# =========================================================================
# UI 绘制函数
# =========================================================================

def draw_lxxw_ui(layout, context):
    """绘制工整的螺旋纤维界面"""
    props = context.scene.spiral_props
    
    box = layout.box()
    box.label(text="螺旋线参数设置:")
    
    row = box.row()
    row.prop(props, "turns", text="圈数")
    
    row = box.row()
    row.prop(props, "radius", text="半径")
    
    row = box.row()
    row.prop(props, "thickness", text="线条粗细")
    
    row = box.row()
    row.prop(props, "align_ends", text="两端对齐")
    
    box = layout.box()
    box.label(text="多螺旋线设置:")
    
    row = box.row()
    row.prop(props, "spiral_count", text="螺旋线数量")
    
    box = layout.box()
    box.label(text="高级设置:")
    
    row = box.row()
    row.prop(props, "resolution", text="分辨率")
    
    row = box.row()
    row.prop(props, "points_per_turn", text="每圈点数")
    
    row = layout.row()
    row.scale_y = 1.3
    row.operator("lxxw.add_spiral", text="添加螺旋线", icon="CURVE_PATH")
    
    if spiral_relationships:
        row = layout.row()
        row.scale_y = 1.1
        row.operator("lxxw.update_spirals", text="更新所有螺旋线", icon="FILE_REFRESH")
        
        row = layout.row()
        row.scale_y = 1.1
        row.operator("lxxw.clear_spirals", text="清除所有螺旋线", icon="TRASH")

# =========================================================================
# 注册/注销
# =========================================================================

def register():
    bpy.utils.register_class(SpiralProperties)
    bpy.utils.register_class(LXXW_OT_AddSpiral)
    bpy.utils.register_class(LXXW_OT_UpdateSpirals)
    bpy.utils.register_class(LXXW_OT_ClearSpirals)
    
    bpy.types.Scene.spiral_props = PointerProperty(type=SpiralProperties)
    
    # 注册处理器
    if curve_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(curve_update_handler)
    
    if selection_change_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(selection_change_handler)

def unregister():
    if curve_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(curve_update_handler)
    
    if selection_change_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(selection_change_handler)
        
    if hasattr(bpy.types.Scene, "spiral_props"):
        del bpy.types.Scene.spiral_props
        
    bpy.utils.unregister_class(LXXW_OT_ClearSpirals)
    bpy.utils.unregister_class(LXXW_OT_UpdateSpirals)
    bpy.utils.unregister_class(LXXW_OT_AddSpiral)
    bpy.utils.unregister_class(SpiralProperties)
