# -*- coding: utf-8 -*-

import bpy
from bpy_extras import view3d_utils

addon_keymaps = []

class DoubleClickSwitchModeOperator(bpy.types.Operator):
    """双击切换模式的自定义操作"""
    bl_idname = "view3d.double_click_switch_mode"
    bl_label = "双击切换模式"

    @classmethod
    def poll(cls, context):
        """确保操作在开启状态且在支持的模式下生效"""
        if not getattr(context.scene, "enable_double_click_switch", True):
            return False
        supported_modes = (
            'OBJECT',           # 物体模式
            'EDIT_MESH',       # 网格编辑模式
            'EDIT_ARMATURE',   # 骨架编辑模式
            'EDIT_CURVE',      # 曲线编辑模式
            'EDIT_SURFACE',    # 曲面编辑模式
            'EDIT_TEXT',       # 文本编辑模式
            'EDIT_METABALL',   # 元球编辑模式
            'EDIT_LATTICE',    # 晶格编辑模式
            'POSE'             # 姿态模式
        )
        return context.mode in supported_modes

    def invoke(self, context, event):
        # 获取鼠标在3D视图中的位置
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y

        # 根据当前模式处理双击行为
        if context.mode == 'OBJECT':
            # 在物体模式下，尝试选择鼠标下的对象
            prev_selected = context.selected_objects[:]
            bpy.ops.object.select_all(action='DESELECT')
            bpy.ops.view3d.select(extend=False, location=coord)
            selected_obj = context.object
            if selected_obj:
                # 双击选择了对象
                if selected_obj.type == 'ARMATURE':
                    bpy.ops.object.mode_set(mode='POSE')  # 切换到姿态模式
                # 检查对象是否支持编辑模式
                elif selected_obj.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE'}:
                    bpy.ops.object.mode_set(mode='EDIT')  # 切换到编辑模式
                # 处理集合实例对象
                elif selected_obj.type == 'EMPTY' and selected_obj.instance_type == 'COLLECTION':
                    if selected_obj.instance_collection:
                        # 实例独立化
                        bpy.ops.object.duplicates_make_real()
                        # 显示操作成功信息
                        self.report({'INFO'}, "实例已独立化")
                # 其他类型的对象可能不支持编辑模式
            # 双击空白处，无操作
        elif context.mode in ('EDIT_MESH', 'EDIT_ARMATURE', 'EDIT_CURVE', 'EDIT_SURFACE', 'EDIT_TEXT', 'EDIT_METABALL', 'EDIT_LATTICE', 'POSE'):
            # 在编辑模式或姿态模式下，检测是否双击空白处
            depsgraph = context.evaluated_depsgraph_get()
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            result, _, _, _, _, _ = bpy.context.scene.ray_cast(depsgraph, origin, direction)
            if not result:
                # 双击空白处，切换到物体模式
                bpy.ops.object.mode_set(mode='OBJECT')

        return {'FINISHED'}

def draw_sjqh_ui(layout, context):
    """绘制双击切换页面 UI"""
    scene = context.scene
    
    col = layout.column(align=True)
    col.scale_y = 1.2
    col.prop(scene, "enable_double_click_switch", toggle=True, text="双击切换已启用" if scene.enable_double_click_switch else "双击切换已禁用")
    
    layout.separator()
    
    box = layout.box()
    box.label(text="功能说明:")
    col_info = box.column(align=True)
    col_info.label(text="• 物体模式下:")
    col_info.label(text="   - 双击物体: 进入编辑模式")
    col_info.label(text="   - 双击骨骼: 进入姿态模式")
    col_info.label(text="   - 双击集合实例: 独立化实例")
    col_info.separator()
    col_info.label(text="• 编辑 / 姿态模式下:")
    col_info.label(text="   - 双击空白处: 快速切回物体模式")

classes = (
    DoubleClickSwitchModeOperator,
)

def register():
    """注册类、快捷键和全局属性"""
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Scene.enable_double_click_switch = bpy.props.BoolProperty(
        name="启用双击切换",
        description="勾选以启用 3D 视图鼠标左键双击快速切换模式功能",
        default=True
    )

    try:
        wm = bpy.context.window_manager
        if wm and hasattr(wm, "keyconfigs") and wm.keyconfigs and hasattr(wm.keyconfigs, "addon") and wm.keyconfigs.addon:
            km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
            kmi = km.keymap_items.new(
                DoubleClickSwitchModeOperator.bl_idname,
                type='LEFTMOUSE',
                value='DOUBLE_CLICK'
            )
            addon_keymaps.append((km, kmi))
    except Exception:
        pass

def unregister():
    """注销类、快捷键和全局属性"""
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()
    
    if hasattr(bpy.types.Scene, "enable_double_click_switch"):
        del bpy.types.Scene.enable_double_click_switch

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
