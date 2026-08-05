# -*- coding: utf-8 -*-

import bpy
import mathutils
from bpy_extras import view3d_utils

class ZZ_OT_AddAreaLightModal(bpy.types.Operator):
    """添加一个跟随鼠标移动的面光，鼠标移至模型表面时始终垂直照射该面，再次点击左键确定位置"""
    bl_idname = "zz.add_area_light_modal"
    bl_label = "+面光"
    bl_options = {'REGISTER', 'UNDO'}

    def align_light_to_normal(self, normal):
        norm = normal.normalized()
        if norm.length < 0.001:
            norm = mathutils.Vector((0, 0, 1))

        # 灯光的局部 Z 轴为法线方向，则灯光的发射方向 (局部 -Z) 正好垂直指向表面 (-normal)
        Z_axis = norm

        # 选择合适的参考向量构建正交基，避免 Gimbal 翻转
        if abs(Z_axis.z) < 0.999:
            ref = mathutils.Vector((0, 0, 1))
        else:
            ref = mathutils.Vector((0, 1, 0))

        X_axis = ref.cross(Z_axis).normalized()
        Y_axis = Z_axis.cross(X_axis).normalized()

        rot_mat = mathutils.Matrix((X_axis, Y_axis, Z_axis)).transposed()
        return rot_mat.to_euler()

    def update_light_position(self, context, event):
        if not self.light_obj or self.light_obj.name not in context.scene.objects:
            return

        region = None
        for r in context.area.regions:
            if r.type == 'WINDOW':
                region = r
                break
        if not region:
            region = context.region

        rv3d = getattr(context.space_data, "region_3d", None) if context.space_data else None
        if not rv3d or not region:
            return

        # 获取相对 3D 视口 region 的坐标
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)

        # 转换为 3D 视线射线
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        depsgraph = context.evaluated_depsgraph_get()
        hit, location, normal, face_idx, obj, matrix = context.scene.ray_cast(
            depsgraph, ray_origin, ray_vector
        )

        if hit and obj != self.light_obj:
            # 射线击中网格物体表面
            norm = normal.normalized()
            # 放置在表面沿法线偏移的位置（垂直距离）
            self.light_obj.location = location + norm * self.distance
            # 旋转面光，使其发射轴 (-Z) 垂直照射物体的面
            self.light_obj.rotation_euler = self.align_light_to_normal(norm)
        else:
            # 未击中模型时，在 3D 游标平面位置放置面光
            cursor_loc = context.scene.cursor.location
            view_dir = rv3d.view_rotation @ mathutils.Vector((0, 0, -1))
            dist = (cursor_loc - ray_origin).dot(view_dir)
            if abs(dist) < 0.001:
                dist = 5.0
            target_loc = ray_origin + ray_vector * abs(dist)
            self.light_obj.location = target_loc
            self.light_obj.rotation_euler = rv3d.view_rotation.to_euler()

    def update_status_text(self, context):
        if hasattr(context.workspace, "status_text_set"):
            size_str = f"{self.light_obj.data.size:.1f}m" if self.light_obj and self.light_obj.data else "1.0m"
            context.workspace.status_text_set(
                f"面光跟随中 (垂直照射表面) | 左键：确定位置 | 滚轮：尺寸({size_str}) | Shift+滚轮：距面距离({self.distance:.1f}m) | 右键/ESC：取消"
            )

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "请在 3D 视口中使用此功能")
            return {'CANCELLED'}

        # 新建面光对象
        light_data = bpy.data.lights.new(name="面光", type='AREA')
        light_data.energy = 100.0  # 默认能量 100W
        light_data.size = 1.0       # 默认尺寸 1m

        light_object = bpy.data.objects.new(name="面光", object_data=light_data)
        context.collection.objects.link(light_object)

        # 选中新面光
        bpy.ops.object.select_all(action='DESELECT')
        light_object.select_set(True)
        context.view_layer.objects.active = light_object

        self.light_obj = light_object
        self.distance = 2.0  # 默认距模型表面的垂直悬空距离 (2m)
        self.mouse_released_once = False
        self.mouse_has_moved = False

        # 初始更新位置与状态栏
        try:
            self.update_light_position(context, event)
        except Exception as e:
            print(f"ZZ Light: Initial position update error: {e}")

        self.update_status_text(context)
        context.window_manager.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self.mouse_has_moved = True
            try:
                self.update_light_position(context, event)
            except Exception as e:
                print(f"ZZ Light: Position update error: {e}")
            return {'RUNNING_MODAL'}

        elif event.type == 'WHEELUPMOUSE':
            if event.shift:
                self.distance += 0.1
            else:
                if self.light_obj and self.light_obj.data:
                    self.light_obj.data.size += 0.2
            self.update_status_text(context)
            try:
                self.update_light_position(context, event)
            except Exception:
                pass
            return {'RUNNING_MODAL'}

        elif event.type == 'WHEELDOWNMOUSE':
            if event.shift:
                self.distance = max(0.05, self.distance - 0.1)
            else:
                if self.light_obj and self.light_obj.data:
                    self.light_obj.data.size = max(0.1, self.light_obj.data.size - 0.2)
            self.update_status_text(context)
            try:
                self.update_light_position(context, event)
            except Exception:
                pass
            return {'RUNNING_MODAL'}

        elif event.type == 'LEFTMOUSE':
            if event.value == 'RELEASE':
                self.mouse_released_once = True
                return {'RUNNING_MODAL'}
            elif event.value == 'PRESS':
                # 左键点击确定位置
                if self.mouse_released_once or self.mouse_has_moved:
                    if hasattr(context.workspace, "status_text_set"):
                        context.workspace.status_text_set(None)
                    self.report({'INFO'}, "已确定面光位置并垂直照射表面")
                    return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            if hasattr(context.workspace, "status_text_set"):
                context.workspace.status_text_set(None)
            if self.light_obj and self.light_obj.name in context.scene.objects:
                bpy.data.objects.remove(self.light_obj, do_unlink=True)
            self.report({'INFO'}, "已取消添加面光")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


# =========================================================================
# UI 绘制函数
# =========================================================================

def draw_light_ui(layout, context):
    """绘制灯光模块界面"""
    col = layout.column(align=True)

    # 放置面光主按键
    row = col.row(align=True)
    row.scale_y = 1.4
    row.operator("zz.add_area_light_modal", text="+面光", icon="LIGHT_AREA")

    col.separator()

    # 选中灯光参数调节
    active_obj = context.active_object
    if active_obj and active_obj.type == 'LIGHT':
        light_data = active_obj.data
        box = layout.box()
        box.label(text=f"当前灯光: {active_obj.name}", icon='LIGHT')

        b_col = box.column(align=True)
        b_col.prop(light_data, "type", text="类型")
        b_col.prop(light_data, "color", text="颜色")
        b_col.prop(light_data, "energy", text="能量 (W)")

        if light_data.type == 'AREA':
            b_col.prop(light_data, "shape", text="形状")
            if light_data.shape in {'SQUARE', 'DISK'}:
                b_col.prop(light_data, "size", text="尺寸")
            else:
                b_col.prop(light_data, "size", text="尺寸 X")
                b_col.prop(light_data, "size_y", text="尺寸 Y")
    else:
        info_box = layout.box()
        info_box.label(text="点击「+面光」创建面光", icon='INFO')
        info_box.label(text="移动至网格物体表面时始终垂直照射", icon='HELP')
        info_box.label(text="点击左键确定放置，ESC/右键取消", icon='RESTRICT_SELECT_OFF')


# =========================================================================
# 注册/注销
# =========================================================================

classes = (
    ZZ_OT_AddAreaLightModal,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
