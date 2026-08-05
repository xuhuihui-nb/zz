# -*- coding: utf-8 -*-

import bpy
import sys
import subprocess

class RestartBlenderOperator(bpy.types.Operator):
    """重新启动当前的 Blender 实例"""
    bl_idname = "wm.restart_blender"
    bl_label = "重启 Blender"
    
    def execute(self, context):
        try:
            blender_executable = sys.argv[0]
            current_file = bpy.data.filepath

            # 保存当前文件（如有）
            if current_file:
                bpy.ops.wm.save_mainfile()

            # 启动新的实例
            if current_file:
                subprocess.Popen([blender_executable, current_file])
            else:
                subprocess.Popen([blender_executable])
            
            # 关闭当前实例
            bpy.ops.wm.quit_blender()
        except Exception as e:
            self.report({'ERROR'}, f"重启失败: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

# =========================================================================
# UI 绘制函数
# =========================================================================

def draw_restart_ui(layout, context):
    """绘制一键重启界面"""
    layout.label(text="重启选项:")
    
    row = layout.row()
    row.scale_y = 1.5
    row.operator("wm.restart_blender", text="保存并重启 Blender", icon="RECOVER_LAST")

# =========================================================================
# 注册/注销
# =========================================================================

def register():
    bpy.utils.register_class(RestartBlenderOperator)

def unregister():
    bpy.utils.unregister_class(RestartBlenderOperator)
