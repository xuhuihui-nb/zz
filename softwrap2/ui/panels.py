import bpy
from ..utils.registration import register_cls
from ..utils.state import S
from .tabs_initialization import initialization
from .tabs_interaction import interaction


def draw_softwrap_ui(layout, context):
    layout.row(align=True).prop(S(), 'active_tab', expand=True)

    tab = S.active_tab
    if tab == 'INITIALIZATION':
        initialization(None, context, layout=layout)
    elif tab == 'INTERACTION':
        interaction(None, context, layout=layout)


# 取消注册独立 N 面板，避免在侧边栏出现重复的“动态拓扑”标签，UI 已在“我的工具”主面板中通过 draw_softwrap_ui 渲染
class VIEW3D_PT_softwrap2_main(bpy.types.Panel):
    bl_label = '动态拓扑'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '动态拓扑'

    def draw(self, context):
        draw_softwrap_ui(self.layout, context)
