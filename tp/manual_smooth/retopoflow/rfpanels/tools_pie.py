import bpy, os
from bpy.types import Menu, Operator
from bpy.utils import previews


class RFMenu_MT_ToolPie(Menu):
    bl_idname = 'RF_MT_Tools'
    bl_label = 'RetopoFlow Tools'

    @classmethod
    def poll(self, context):
        from ..preferences import RF_Prefs
        tools = context.workspace.tools
        return (
            RF_Prefs.get_prefs(context).enable_pie_hotkey and
            context.mode == 'EDIT_MESH'
            # and tools.from_space_view3d_mode('EDIT_MESH', create=False).idname.split('.')[0] == 'retopoflow'
        )

    def draw_bottom_menu(self, pie):
        tool = bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        pie_emboss = 'PIE_MENU' if bpy.app.version >= (5,0,0) else 'RADIAL_MENU'

        back = pie.box().column(align=True)

        row = back.row()
        row.emboss = pie_emboss
        row.label(text='Clean Up')
        section = back.box().column()
        row = section.row(align=True)
        row.operator('retopoflow.meshcleanup', text='Selected').affect_all=False
        row.operator('retopoflow.meshcleanup', text='All').affect_all=True

        if tool.idname == 'retopoflow.tweak' or tool.idname == 'retopoflow.relax':
            tool_name = 'Tweak' if tool.idname == 'retopoflow.tweak' else 'Relax'
            props = tool.operator_properties(tool.idname)
            row = back.row()
            row.emboss = pie_emboss
            row.label(text=tool_name)
            section = back.box().column()
            section.ui_units_x = 9
            grid = section.grid_flow(even_columns=True, even_rows=True)
            row = grid.row(align=True)
            col = row.column(align=False)
            col.prop(props, 'brush_radius')
            col.prop(props, 'brush_strength', slider=True)
            col.prop(props, 'brush_falloff', slider=True)
            col.row(align=True, heading='Selected').prop(props, 'mask_selected', expand=True, icon_only=True)
            col.row(align=True, heading='Boundary').prop(props, 'mask_boundary', expand=True, icon_only=True)
            row = col.row(align=True)
            row.prop(props, 'include_corners')
            row.prop(props, 'include_occluded')

    def draw(self, context):
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        layout = self.layout
        pie = layout.menu_pie()

        # West
        pie.operator(
            'retopoflow.switch_to_tweak',
            text='Tweak',
            icon_value=RF_icons['TWEAK'].icon_id,
            depress=tool.idname=='retopoflow.tweak'
        )

        # East
        pie.operator(
            'retopoflow.switch_to_relax',
            text='Relax',
            icon_value=RF_icons['RELAX'].icon_id,
            depress=tool.idname=='retopoflow.relax'
        )

        # South
        self.draw_bottom_menu(pie)


keymaps = []
RF_icons = None


def register():
    bpy.utils.register_class(RFMenu_MT_ToolPie)

    wm = bpy.context.window_manager
    keyconfigs = wm.keyconfigs.addon
    if keyconfigs:
        keymap = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        keymap_item = keymap.keymap_items.new('wm.call_menu_pie', 'W', 'PRESS', ctrl=False, shift=False, alt=False)
        keymap_item.properties.name =  RFMenu_MT_ToolPie.bl_idname
        keymaps.append((keymap, keymap_item))

    global RF_icons
    RF_icons = previews.new()
    icons_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'icons'))
    RF_icons.load('TWEAK', os.path.join(icons_dir, 'tweak-icon.png'), 'IMAGE')
    RF_icons.load('RELAX', os.path.join(icons_dir, 'relax-icon.png'), 'IMAGE')

def unregister():
    bpy.utils.unregister_class(RFMenu_MT_ToolPie)

    for keymap, keymap_item in keymaps:
        keymap.keymap_items.remove(keymap_item)
    keymaps.clear()

    global RF_icons
    previews.remove(RF_icons)

