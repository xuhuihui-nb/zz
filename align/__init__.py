# -*- coding: utf-8 -*-

import bpy
import bmesh
import bpy_extras
import mathutils

def align_objects_viewport(context, axis_index, is_max):
    """
    在视口空间对齐物体或顶点
    axis_index: 0 代表 X 轴 (左右), 1 代表 Y 轴 (上下)
    is_max: True 代表向右/向上, False 代表向左/向下
    """
    area = context.area
    region = None
    rv3d = None
    
    for r in area.regions:
        if r.type == 'WINDOW':
            region = r
            rv3d = area.spaces.active.region_3d
            break
    
    if not region or not rv3d:
        return {'CANCELLED'}, "未找到 3D 视口区域"

    if context.mode == 'OBJECT':
        selected_objects = context.selected_objects
        if not selected_objects:
            return {'CANCELLED'}, "未选择物体"
            
        data = []
        for obj in selected_objects:
            co2d = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, obj.matrix_world.translation)
            if co2d:
                data.append((obj, co2d))
        
        if not data:
            return {'CANCELLED'}, "投影失败"

        values = [item[1][axis_index] for item in data]
        target_val = max(values) if is_max else min(values)
        
        count = 0
        for obj, co2d in data:
            if abs(co2d[axis_index] - target_val) > 0.01:
                new_co2d = list(co2d)
                new_co2d[axis_index] = target_val
                
                new_location = bpy_extras.view3d_utils.region_2d_to_location_3d(region, rv3d, new_co2d, obj.matrix_world.translation)
                obj.matrix_world.translation = new_location
                count += 1
                
        return {'FINISHED'}, count

    elif context.mode == 'EDIT_MESH':
        objects = context.objects_in_mode
        if not objects:
             return {'CANCELLED'}, "编辑模式下没有有效的网格物体"

        all_verts_data = []
        bmeshes = {} 

        for obj in objects:
            if obj.type != 'MESH':
                continue
            
            bm = bmesh.from_edit_mesh(obj.data)
            bmeshes[obj] = bm
            mat_world = obj.matrix_world
            
            for v in bm.verts:
                if v.select:
                    world_co = mat_world @ v.co
                    co2d = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, world_co)
                    
                    if co2d:
                        all_verts_data.append({
                            'obj': obj,
                            'bm': bm,
                            'vert': v,
                            'co2d': co2d,
                            'world_co': world_co
                        })
        
        if not all_verts_data:
             return {'CANCELLED'}, "未选择任何顶点"

        values = [item['co2d'][axis_index] for item in all_verts_data]
        target_val = max(values) if is_max else min(values)
        
        count = 0
        for item in all_verts_data:
            co2d = item['co2d']
            if abs(co2d[axis_index] - target_val) > 0.01:
                new_co2d = list(co2d)
                new_co2d[axis_index] = target_val
                
                new_world_loc = bpy_extras.view3d_utils.region_2d_to_location_3d(region, rv3d, new_co2d, item['world_co'])
                item['vert'].co = item['obj'].matrix_world.inverted() @ new_world_loc
                count += 1
        
        for obj, bm in bmeshes.items():
            bmesh.update_edit_mesh(obj.data)
            
        return {'FINISHED'}, count

    return {'CANCELLED'}, "不支持的模式"


class OBJECT_OT_align_selected_to_active(bpy.types.Operator):
    """将选中的物体或顶点移动到活动物体或活动顶点的位置"""
    bl_idname = "object.align_selected_to_active"
    bl_label = "所选到活动项"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
            return context.active_object is not None and len(context.selected_objects) > 0
        elif context.mode == 'EDIT_MESH':
            return context.active_object is not None and context.active_object.type == 'MESH'
        return False

    def execute(self, context):
        active_obj = context.active_object
        
        if context.mode == 'OBJECT':
            if not active_obj:
                self.report({'WARNING'}, "未找到活动物体")
                return {'CANCELLED'}
                
            target_location = active_obj.location.copy()
            
            count = 0
            for obj in context.selected_objects:
                if obj != active_obj:
                    obj.location = target_location
                    count += 1
                    
            self.report({'INFO'}, f"已移动 {count} 个物体到 {active_obj.name}")
            return {'FINISHED'}
            
        elif context.mode == 'EDIT_MESH':
            obj = active_obj
            bm = bmesh.from_edit_mesh(obj.data)
            active_elem = bm.select_history.active
            
            if not active_elem:
                self.report({'WARNING'}, "未找到活动元素")
                return {'CANCELLED'}
            
            if isinstance(active_elem, bmesh.types.BMVert):
                target_loc = active_elem.co.copy()
            elif isinstance(active_elem, bmesh.types.BMEdge):
                target_loc = sum((v.co for v in active_elem.verts), mathutils.Vector()) / 2
            elif isinstance(active_elem, bmesh.types.BMFace):
                target_loc = active_elem.calc_center_median()
            else:
                self.report({'WARNING'}, "活动元素类型未知")
                return {'CANCELLED'}

            count = 0
            for v in bm.verts:
                if v.select and v != active_elem:
                    v.co = target_loc
                    count += 1
            
            bmesh.update_edit_mesh(obj.data)
            self.report({'INFO'}, f"已移动 {count} 个顶点到活动元素")
            return {'FINISHED'}
            
        return {'CANCELLED'}


class OBJECT_OT_align_to_top(bpy.types.Operator):
    """向视口中最顶部的点对齐所选物体或网格顶点"""
    bl_idname = "object.align_to_top"
    bl_label = "向上对齐"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
           return len(context.selected_objects) > 1
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        status, res = align_objects_viewport(context, axis_index=1, is_max=True)
        if status == {'FINISHED'}:
            self.report({'INFO'}, f"向上对齐了 {res} 个元素")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, str(res))
            return status


class OBJECT_OT_align_to_bottom(bpy.types.Operator):
    """向视口中最底部的点对齐所选物体或网格顶点"""
    bl_idname = "object.align_to_bottom"
    bl_label = "向下对齐"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
           return len(context.selected_objects) > 1
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        status, res = align_objects_viewport(context, axis_index=1, is_max=False)
        if status == {'FINISHED'}:
            self.report({'INFO'}, f"向下对齐了 {res} 个元素")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, str(res))
            return status


class OBJECT_OT_align_to_left(bpy.types.Operator):
    """向视口中最左侧的点对齐所选物体或网格顶点"""
    bl_idname = "object.align_to_left"
    bl_label = "向左对齐"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
           return len(context.selected_objects) > 1
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        status, res = align_objects_viewport(context, axis_index=0, is_max=False)
        if status == {'FINISHED'}:
            self.report({'INFO'}, f"向左对齐了 {res} 个元素")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, str(res))
            return status


class OBJECT_OT_align_to_right(bpy.types.Operator):
    """向视口中最右侧的点对齐所选物体或网格顶点"""
    bl_idname = "object.align_to_right"
    bl_label = "向右对齐"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
           return len(context.selected_objects) > 1
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        status, res = align_objects_viewport(context, axis_index=0, is_max=True)
        if status == {'FINISHED'}:
            self.report({'INFO'}, f"向右对齐了 {res} 个元素")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, str(res))
            return status


class OBJECT_OT_drop_to_floor(bpy.types.Operator):
    """将选中的物体贴地到下方物体或网格表面（若下方无物体则贴到 Z=0 面）"""
    bl_idname = "object.drop_to_floor"
    bl_label = "贴地/对齐下方"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and len(context.selected_objects) > 0

    def execute(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        scene = context.scene
        count_hit = 0
        count_ground = 0
        
        for obj in context.selected_objects:
            bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
            min_z = min(v.z for v in bbox_corners)
            
            center_x = sum(v.x for v in bbox_corners) / 8
            center_y = sum(v.y for v in bbox_corners) / 8
            
            ray_origin = mathutils.Vector((center_x, center_y, min_z + 0.1))
            ray_direction = mathutils.Vector((0, 0, -1))
            
            obj.hide_set(True)
            result, location, normal, index, hit_obj, matrix = scene.ray_cast(depsgraph, ray_origin, ray_direction)
            obj.hide_set(False)
            
            if result:
                offset_z = min_z - location.z
                obj.location.z -= offset_z
                count_hit += 1
            else:
                offset_z = min_z - 0.0
                obj.location.z -= offset_z
                count_ground += 1
                
        self.report({'INFO'}, f"对齐结果: {count_hit} 个贴于物体上, {count_ground} 个贴于地面")
        return {'FINISHED'}


class OBJECT_OT_cursor_to_selected(bpy.types.Operator):
    """将 3D 游标定位到所选元素的中心点"""
    bl_idname = "object.cursor_to_selected"
    bl_label = "游标到所选"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
             return len(context.selected_objects) > 0
        elif context.mode == 'EDIT_MESH':
             return context.active_object is not None and context.active_object.type == 'MESH'
        return False

    def execute(self, context):
        if context.mode == 'OBJECT':
            selected_objects = context.selected_objects
            if not selected_objects:
                return {'CANCELLED'}
            
            avg_loc = mathutils.Vector((0.0, 0.0, 0.0))
            for obj in selected_objects:
                avg_loc += obj.matrix_world.translation
            avg_loc /= len(selected_objects)
            
            context.scene.cursor.location = avg_loc
            self.report({'INFO'}, "游标已移动到所选物体中心")
            return {'FINISHED'}

        elif context.mode == 'EDIT_MESH':
            obj = context.active_object
            bm = bmesh.from_edit_mesh(obj.data)
            
            selected_verts = [v for v in bm.verts if v.select]
            if not selected_verts:
                self.report({'WARNING'}, "未选择任何顶点")
                return {'CANCELLED'}
            
            center_local = sum((v.co for v in selected_verts), mathutils.Vector()) / len(selected_verts)
            center_world = obj.matrix_world @ center_local
            
            context.scene.cursor.location = center_world
            self.report({'INFO'}, "游标已移动到所选顶点中心")
            return {'FINISHED'}
            
        return {'CANCELLED'}


class OBJECT_OT_origin_to_selected(bpy.types.Operator):
    """将物体的原点/质心移动到网格的所选元素中心（编辑模式）或活动物体的位置（物体模式）"""
    bl_idname = "object.origin_to_selected"
    bl_label = "质心到所选"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
             return context.active_object is not None
        elif context.mode == 'EDIT_MESH':
             return context.active_object is not None and context.active_object.type == 'MESH'
        return False

    def execute(self, context):
        if context.mode == 'OBJECT':
            target_obj = context.active_object
            if not target_obj:
                return {'CANCELLED'}
            
            target_loc = target_obj.location.copy()
            
            count = 0
            for obj in context.selected_objects:
                if obj == target_obj: 
                    continue
                    
                mat_old = obj.matrix_world.copy()
                obj.location = target_loc
                context.view_layer.update()
                mat_new = obj.matrix_world.copy()
                
                transform_mat = mat_new.inverted() @ mat_old
                obj.data.transform(transform_mat)
                count += 1
            
            self.report({'INFO'}, f"成功设置 {count} 个物体的原点")
            return {'FINISHED'}

        elif context.mode == 'EDIT_MESH':
            obj = context.active_object
            bm = bmesh.from_edit_mesh(obj.data)
            
            selected_verts = [v for v in bm.verts if v.select]
            if not selected_verts:
                self.report({'WARNING'}, "未选择任何顶点")
                return {'CANCELLED'}
            
            center_local = sum((v.co for v in selected_verts), mathutils.Vector()) / len(selected_verts)
            new_origin_world = obj.matrix_world @ center_local
            
            bmesh.ops.translate(bm, verts=bm.verts, vec=-center_local)
            bmesh.update_edit_mesh(obj.data)
            
            obj.matrix_world.translation = new_origin_world
            self.report({'INFO'}, "物体的原点已成功移动到所选顶点中心")
            return {'FINISHED'}
            
        return {'CANCELLED'}

# =========================================================================
# UI 绘制函数
# =========================================================================

def draw_align_ui(layout, context):
    """绘制对齐工具界面"""
    row = layout.row()
    row.scale_y = 1.3
    row.operator("object.align_selected_to_active", text="对齐到活动项")
    
    layout.separator()
    
    # 视口空间对齐九宫格
    layout.label(text="视口对齐:")
    col = layout.column(align=True)
    
    # 上
    row_top = col.row(align=True)
    row_top.scale_y = 1.2
    row_top.operator("object.align_to_top", text="上", icon="TRIA_UP")
    
    # 左、右
    row_mid = col.row(align=True)
    row_mid.scale_y = 1.2
    row_mid.operator("object.align_to_left", text="左", icon="TRIA_LEFT")
    row_mid.operator("object.align_to_right", text="右", icon="TRIA_RIGHT")
    
    # 下
    row_bot = col.row(align=True)
    row_bot.scale_y = 1.2
    row_bot.operator("object.align_to_bottom", text="下", icon="TRIA_DOWN")
    
    layout.separator()
    
    # 游标质心对齐
    col_tools = layout.column(align=True)
    col_tools.scale_y = 1.2
    col_tools.operator("object.origin_to_selected", text="原点到所选", icon="OBJECT_ORIGIN")
    col_tools.operator("object.cursor_to_selected", text="游标到所选", icon="CURSOR")
    
    layout.separator()
    
    # 贴地操作
    row_drop = layout.row()
    row_drop.scale_y = 1.3
    row_drop.operator("object.drop_to_floor", text="吸附贴地 (Drop)", icon="SNAP_GRID")

# =========================================================================
# 注册/注销
# =========================================================================

classes = (
    OBJECT_OT_align_selected_to_active,
    OBJECT_OT_align_to_top,
    OBJECT_OT_align_to_bottom,
    OBJECT_OT_align_to_left,
    OBJECT_OT_align_to_right,
    OBJECT_OT_drop_to_floor,
    OBJECT_OT_cursor_to_selected,
    OBJECT_OT_origin_to_selected,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
