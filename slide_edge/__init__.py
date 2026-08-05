# -*- coding: utf-8 -*-

import bpy
import importlib

from . import slide_edge
from . import gui

def menu_func(self, context):
    self.layout.operator_context = "INVOKE_DEFAULT"
    self.layout.operator(slide_edge.SlideEdgeOperator.bl_idname, text="边滑动 (Slide Edge)", icon="EDGESEL")

def draw_slide_edge_ui(layout, context):
    """在 ZZ 主面板的『边滑动』分页中绘制界面"""
    header_box = layout.box()
    row_title = header_box.row(align=True)
    row_title.label(text="边滑动 (Slide Edge)", icon="EDGESEL")
    
    layout.separator()
    
    is_edit_mode = (context.mode == 'EDIT_MESH')
    if not is_edit_mode:
        warn_box = layout.box()
        warn_box.label(text="请在编辑模式下选择边线使用", icon='INFO')
    
    btn_row = layout.row(align=True)
    btn_row.scale_y = 1.5
    btn_row.enabled = is_edit_mode
    op = btn_row.operator("mesh.slide_edge_operator", text="启动 边滑动", icon="EDGESEL")
    
    layout.separator()

    # 操作说明与快捷键提示
    box = layout.box()
    box.label(text="操作指南与快捷键:", icon='HELP')
    
    col = box.column(align=True)
    col.scale_y = 0.95
    col.label(text="• 移动鼠标: 交互式沿网格表面滑动边线")
    col.label(text="• 按住 Shift: 启用慢速微调模式")
    col.label(text="• 鼠标左键 / Q 键: 确认并提交滑动修改")
    col.label(text="• Esc 键: 取消滑动并还原修改")

classes = (
    slide_edge.SlideEdgeOperator,
)

def register():
    importlib.reload(slide_edge)
    importlib.reload(gui)
    
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"ZZ SlideEdge: Failed to register {cls.__name__}: {e}")

    try:
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(menu_func)
    except Exception as e:
        print(f"ZZ SlideEdge: Failed to append context menu: {e}")

def unregister():
    try:
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(menu_func)
    except Exception as e:
        print(f"ZZ SlideEdge: Failed to remove context menu: {e}")

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"ZZ SlideEdge: Failed to unregister {cls.__name__}: {e}")
