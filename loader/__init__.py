# -*- coding: utf-8 -*-

import bpy
import os

# 获取基础包名
package_name = __name__.split('.')[0]

def get_folder_addons(folder_path):
    if not folder_path or not os.path.exists(folder_path):
        return []
    
    addon_modules = []
    try:
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isdir(item_path) and "__init__.py" in os.listdir(item_path):
                addon_modules.append(item)
    except Exception:
        pass
    return addon_modules

def get_addon_items(self, context):
    addon = context.preferences.addons.get(package_name)
    if addon and addon.preferences:
        addon_folder_path = addon.preferences.addon_folder_path
        addon_modules = get_folder_addons(addon_folder_path)
        if addon_modules:
            return [(addon_name, addon_name, f"重新加载 {addon_name}") for addon_name in addon_modules]
    return [("", "无可用插件", "")]

def update_selected_addon(self, context):
    if self.selected_addon not in bpy.context.preferences.addons.keys():
        self.selected_addon = ""

class ReloadAddonOperator(bpy.types.Operator):
    bl_idname = "wm.reload_addon"
    bl_label = "重新加载插件"
    bl_description = "卸载并重新加载选中的插件"
    
    addon_name: bpy.props.StringProperty()
    
    def execute(self, context):
        if not self.addon_name:
            self.report({'WARNING'}, "未选择有效的插件")
            return {'CANCELLED'}
            
        if self.addon_name in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_disable(module=self.addon_name)
            bpy.ops.preferences.addon_enable(module=self.addon_name)
            self.report({'INFO'}, f"插件 {self.addon_name} 已重新加载")
        else:
            self.report({'ERROR'}, f"插件 {self.addon_name} 未安装或未启用")
        return {'FINISHED'}

# =========================================================================
# UI 绘制函数
# =========================================================================

def draw_loader_ui(layout, context):
    """绘制插件加载界面"""
    addon = context.preferences.addons.get(package_name)
    pref = addon.preferences if addon else None

    if not pref:
        layout.label(text="未检测到插件偏好设置", icon="ERROR")
        return
        
    layout.label(text="偏好设置路径:")
    layout.prop(pref, "addon_folder_path", text="")

    layout.separator()
    
    # 获取并列出插件列表
    addon_modules = get_folder_addons(pref.addon_folder_path)

    if not addon_modules:
        layout.label(text="所选文件夹中未发现有效插件", icon="INFO")
        return

    layout.label(text="选择插件模块:")
    layout.prop(context.scene, "selected_addon", text="")

    layout.separator()
    
    row = layout.row()
    row.scale_y = 1.3
    row.operator("wm.reload_addon", text="重新加载插件", icon="FILE_REFRESH").addon_name = context.scene.selected_addon

# =========================================================================
# 注册/注销
# =========================================================================

def register():
    bpy.utils.register_class(ReloadAddonOperator)
    
    bpy.types.Scene.selected_addon = bpy.props.EnumProperty(
        name="已选择插件",
        description="在指定的插件文件夹中检测到的可用插件",
        items=get_addon_items,
        update=update_selected_addon
    )

def unregister():
    if hasattr(bpy.types.Scene, "selected_addon"):
        del bpy.types.Scene.selected_addon
    bpy.utils.unregister_class(ReloadAddonOperator)
