import os

import bpy
from bpy.types import Context, Panel, UILayout

from .preferences import GRABDOC_PT_presets
from .utils.baker import get_baker_by_index
from .utils.generic import get_version, get_user_preferences
from .utils.scene import camera_in_3d_view, is_scene_valid


class GDPanel:
    bl_category    = '纹理场景'
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label       = ""


class GRABDOC_PT_grabdoc(GDPanel):
    bl_label      = "纹理场景 " + (get_version() or "")
    documentation = "https://github.com/oRazeD/GrabDoc/wiki"

    def draw_header_preset(self, _context: Context):
        row = self.layout.row()
        row.operator(
            "wm.url_open", text="", icon='HELP'
        ).url = self.documentation
        row.separator(factor=.2)

    def draw(self, _context: Context):
        if is_scene_valid():
            return
        row = self.layout.row(align=True)
        row.scale_y = 1.5
        row.operator("grabdoc.scene_setup",
                     text="Setup Scene", icon='TOOL_SETTINGS')


class GRABDOC_PT_scene(GDPanel):
    bl_label     = 'Scene'
    bl_parent_id = "GRABDOC_PT_grabdoc"

    @classmethod
    def poll(cls, _context: Context) -> bool:
        return is_scene_valid()

    def draw_header(self, _context: Context):
        self.layout.label(icon='SCENE_DATA')

    def draw_header_preset(self, _context: Context):
        GRABDOC_PT_presets.draw_menu(self.layout, text="Presets")

    def draw(self, context: Context):
        gd = context.scene.gd
        layout = self.layout

        col = layout.column(align=True)
        row = col.row(align=True)
        row.scale_x = row.scale_y = 1.25
        row.operator("grabdoc.scene_setup",
                     text="Rebuild Scene", icon='FILE_REFRESH')
        row.operator("grabdoc.scene_cleanup", text="", icon="CANCEL")

        box = col.box()
        row = box.row(align=True)
        row.scale_y = .9
        row.label(text="Camera")
        row.prop(gd, "coll_selectable", text="", emboss=False,
icon='RESTRICT_SELECT_OFF' if gd.coll_selectable else 'RESTRICT_SELECT_ON')
        row.prop(gd, "coll_visible", text="", emboss=False,
icon='RESTRICT_VIEW_OFF' if gd.coll_visible else 'RESTRICT_VIEW_ON')
        row.prop(gd, "coll_rendered", text="", emboss=False,
icon='RESTRICT_RENDER_OFF' if gd.coll_rendered else 'RESTRICT_RENDER_ON')
        camera_in_view = camera_in_3d_view()
        row.operator("grabdoc.toggle_camera_view",
                     text="Exit" if camera_in_view else "View",
icon="OUTLINER_OB_CAMERA" if camera_in_view else "OUTLINER_DATA_CAMERA")

        col = layout.column(align=True)
        col.use_property_split = False
        col.use_property_decorate = False
        col.prop(gd, 'scale', text="缩放", expand=True)

        row_grid = col.row(align=True)
        row_grid.prop(gd, 'grid_subdivs', text="网格细分")
        row_grid.prop(gd, 'use_grid', text="")

        row_ref = col.row(align=True)
        row_ref.enabled = not gd.preview_state
        row_ref.prop(gd, 'reference', text="参考图")
        row_ref.operator("grabdoc.load_reference", text="", icon='FILE_FOLDER')


class GRABDOC_PT_output(GDPanel):
    bl_label     = 'Output'
    bl_parent_id = "GRABDOC_PT_grabdoc"

    @classmethod
    def poll(cls, _context: Context) -> bool:
        return is_scene_valid()

    def draw_header(self, _context: Context):
        self.layout.label(icon='OUTPUT')

    def draw_header_preset(self, context: Context):
        mt_executable = get_user_preferences().mt_executable
        if context.scene.gd.engine == 'marmoset' \
        and not os.path.exists(mt_executable):
            self.layout.enabled = False
        self.layout.scale_x = 1
        self.layout.operator("grabdoc.baker_export",
                             text="Export", icon="EXPORT")

    def mt_header_layout(self, layout: UILayout):
        col = layout.column(align=True)
        row = col.row()
        preferences = get_user_preferences()
        if not os.path.exists(preferences.mt_executable):
            row.alignment = 'CENTER'
            row.label(text="Marmoset Toolbag Executable Required", icon='INFO')
            row = col.row()
            row.prop(preferences, 'mt_executable', text="Executable Path")
            return
        row.prop(preferences, 'mt_executable', text="Executable Path")
        row = col.row(align=True)
        row.scale_y = 1.25
        row.operator("grabdoc.bake_marmoset", text="Bake in Marmoset",
                     icon="EXPORT").send_type = 'open'
        row.operator("grabdoc.bake_marmoset",
                     text="", icon='FILE_REFRESH').send_type = 'refresh'

    def draw(self, context: Context):
        layout = self.layout
        layout.activate_init         = True
        layout.use_property_split    = False
        layout.use_property_decorate = False

        gd = context.scene.gd
        engine_is_marmoset = gd.engine == "marmoset"
        if engine_is_marmoset:
            self.mt_header_layout(layout)

        col2 = layout.column(align=True)
        col2.use_property_split = False
        col2.use_property_decorate = False

        # 引擎选择
        col2.prop(gd, 'engine', text="引擎")

        # 路径选择
        row_path = col2.row(align=True)
        row_path.prop(gd, 'filepath', text="")
        row_path.operator("grabdoc.open_folder", text="", icon="FOLDER_REDIRECT")

        # 文件名称
        col2.prop(gd, 'filename', text="名称")

        # 分辨率
        row_res = col2.row(align=True)
        row_res.prop(gd, 'resolution_x', text="X")
        row_res.prop(gd, 'resolution_y', text="Y")
        row_res.prop(gd, 'resolution_lock', icon_only=True, text=" ",
                 icon="LOCKED" if gd.resolution_lock else "UNLOCKED")
        row_res.operator("grabdoc.increase_resolution", text="", icon="ADD")
        row_res.operator("grabdoc.decrease_resolution", text="", icon="REMOVE")

        # 输出格式
        col2.prop(gd, 'mt_format' if engine_is_marmoset else 'format', text="")

        # 色深
        row_depth = col2.row(align=True)
        if gd.format == "OPEN_EXR":
            row_depth.prop(gd, 'exr_depth', expand=True)
        elif gd.format != "TARGA" or engine_is_marmoset:
            row_depth.prop(gd, 'depth', expand=True)
        else:
            row_depth.enabled = False
            row_depth.prop(gd, 'tga_depth', expand=True)

        # 压缩率 / 编解码
        if gd.format != "TARGA":
            image_settings = context.scene.render.image_settings
            row_codec = col2.row(align=True)
            if gd.format == "PNG":
                row_codec.prop(gd, 'png_compression', text="压缩")
            elif gd.format == "OPEN_EXR":
                row_codec.prop(image_settings, 'exr_codec', text="Codec")
            else:
                row_codec.prop(image_settings, 'tiff_codec', text="Codec")

        # 滤镜宽度与开关
        row_filter = col2.row(align=True)
        row_filter.prop(gd, 'filter_width', text="滤镜宽度")
        row_filter.prop(gd, 'use_filtering', text="")

        if engine_is_marmoset:
            row_samples = col2.row(align=True)
            row_samples.prop(gd, 'mt_samples', text="Samples", expand=True)

        # 选项复选框
        col_props = col2.column(align=True)
        col_props.prop(gd, 'use_bake_collection', text="烘焙群组")
        col_props.prop(gd, 'use_pack_maps', text="烘焙时打包")
        if gd.use_pack_maps:
            col_props.prop(gd, 'remove_original_maps', text="移除原始贴图")
        col_props.prop(gd, 'use_transparent', text="透明背景")
        if engine_is_marmoset:
            col_props.prop(gd, 'mt_auto_bake', text='Bake on Import')
            row_auto = col_props.row(align=True)
            row_auto.enabled = gd.mt_auto_bake
            row_auto.prop(gd, 'mt_auto_close', text='Close after Baking')


class GRABDOC_PT_bake_maps(GDPanel):
    bl_label     = 'Maps'
    bl_parent_id = "GRABDOC_PT_grabdoc"

    @classmethod
    def poll(cls, _context: Context) -> bool:
        return is_scene_valid()

    def draw_header(self, _context: Context):
        self.layout.label(icon='SHADING_RENDERED')

    def draw_header_preset(self, _context: Context):
        self.layout.operator("grabdoc.baker_visibility",
                             emboss=False, text="", icon="HIDE_OFF")

    def draw(self, context: Context):
        gd = context.scene.gd
        if not gd.preview_state:
            return

        layout = self.layout
        col = layout.column(align=True)

        row = col.row(align=True)
        row.alert = True
        row.scale_y = 1.5
        row.operator("grabdoc.baker_preview_exit", icon="CANCEL")

        row = col.row(align=True)
        row.scale_y = 1.1
        baker_prop = getattr(gd, gd.preview_map_type)
        baker = get_baker_by_index(baker_prop, gd.preview_index)
        row.operator(
            "grabdoc.baker_export_preview",
            text=f"Export {baker.NAME}", icon="EXPORT"
        ).baker_index = baker.index
        baker.draw(context, layout)


class GRABDOC_PT_pack_maps(GDPanel):
    bl_label     = 'Pack'
    bl_parent_id = "GRABDOC_PT_grabdoc"
    bl_options   = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        if context.scene.gd.preview_state:
            return False
        return is_scene_valid()

    def draw_header(self, _context: Context):
        self.layout.label(icon='RENDERLAYERS')

    def draw(self, context: Context):
        gd = context.scene.gd
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        col = layout.column(align=True)

        # 第一行：R, G, B, A 四个通道，强制左对齐紧贴
        row_rgba = col.row(align=True)
        for prop_name, label_text in [('channel_r', "R:"), ('channel_g', "G:"), ('channel_b', "B:"), ('channel_a', "A:")]:
            sub = row_rgba.row(align=True)
            sub.alignment = 'LEFT'
            sub.label(text=label_text)
            sub.prop(gd, prop_name, text="")

        col.separator(factor=0.5)

        # 第二行：打包后缀名，强制左对齐紧贴
        row_suffix = col.row(align=True)
        sub_s = row_suffix.row(align=True)
        sub_s.alignment = 'LEFT'
        sub_s.label(text="后缀名:")
        sub_s.prop(gd, 'pack_name', text="")


class GRABDOC_PT_Baker(GDPanel):
    bl_parent_id = "GRABDOC_PT_bake_maps"
    bl_options   = {'DEFAULT_CLOSED', 'HEADER_LAYOUT_EXPAND'}

    baker = None

    @classmethod
    def poll(cls, context: Context) -> bool:
        if not cls.baker:
            return False
        return not context.scene.gd.preview_state and cls.baker.visibility

    def draw_header(self, context: Context):
        row = self.layout.row(align=True)
        row2 = row.row(align=True)
        gd = context.scene.gd
        if gd.engine == 'marmoset' \
        and (len(self.baker.REQUIRED_SOCKETS) > 0 or self.baker.ID == 'custom'):
            row2.active = False
        row2.separator(factor=.5)
        row2.prop(self.baker, 'enabled', text="")
        text = f"{self.baker.get_display_name()} Preview"
        preview = row2.operator("grabdoc.baker_preview", text=text)
        preview.map_type    = self.baker.ID
        preview.baker_index = self.baker.index
        row2.operator("grabdoc.baker_export_single",
                      text="", icon='RENDER_STILL').map_type = self.baker.ID

        if self.baker == getattr(gd, self.baker.ID)[0]:
            row.operator("grabdoc.baker_add",
                         text="", icon='ADD').map_type = self.baker.ID
            return
        remove = row.operator("grabdoc.baker_remove", text="", icon='TRASH')
        remove.map_type    = self.baker.ID
        remove.baker_index = self.baker.index

    def draw(self, context: Context):
        self.baker.draw(context, self.layout)


################################################
# REGISTRATION
################################################


classes = []

def register():
    pass

def unregister():
    pass


def draw_grabdoc_ui(layout, context: Context):
    """纹理场景 (GrabDoc) 专属 UI 界面"""
    layout.use_property_split = False
    layout.use_property_decorate = False

    from .utils.baker import get_baker_collections
    from .utils.scene import is_scene_valid

    if not is_scene_valid():
        box = layout.box()
        row_title = box.row()
        row_title.label(text="纹理场景 (GrabDoc)", icon='TEXTURE')
        row_title.operator("wm.url_open", text="", icon='HELP').url = "https://github.com/oRazeD/GrabDoc/wiki"

        row = box.row(align=True)
        row.scale_y = 1.5
        row.operator("grabdoc.scene_setup", text="创建纹理烘焙场景", icon='TOOL_SETTINGS')
        return

    # 1. 顶部 2 列并排区域 (50% / 50%)
    split_top = layout.split(factor=0.5)

    # 左侧列：场景管理 (Scene) + 贴图通道打包 (Pack)
    col_left = split_top.column()

    box_scene = col_left.box()
    header_scene = box_scene.row(align=True)
    header_scene.label(text="场景管理 (Scene)", icon='SCENE_DATA')
    GRABDOC_PT_presets.draw_menu(header_scene, text="预设")

    p_scene = GRABDOC_PT_scene()
    p_scene.layout = box_scene
    p_scene.draw(context)

    col_left.separator()

    gd = context.scene.gd
    box_pack = col_left.box()
    box_pack.use_property_split = False
    box_pack.use_property_decorate = False
    box_pack.label(text="贴图通道打包 (Pack)", icon='RENDERLAYERS')
    if not gd.preview_state:
        p_pack = GRABDOC_PT_pack_maps()
        p_pack.layout = box_pack
        p_pack.draw(context)

    # 右侧列：输出设置 (Output)
    col_right = split_top.column()

    box_output = col_right.box()
    header_output = box_output.row(align=True)
    header_output.label(text="输出设置 (Output)", icon='OUTPUT')
    p_output = GRABDOC_PT_output()
    p_output.layout = header_output
    p_output.draw_header_preset(context)

    p_output.layout = box_output
    p_output.draw(context)

    layout.separator()

    # 2. 底部独占整行的 贴图烘焙 (Maps)
    box_maps = layout.box()
    header_maps = box_maps.row(align=True)
    header_maps.label(text="贴图烘焙 (Maps)", icon='SHADING_RENDERED')
    p_maps = GRABDOC_PT_bake_maps()
    p_maps.layout = header_maps
    p_maps.draw_header_preset(context)

    if gd.preview_state:
        p_maps.layout = box_maps
        p_maps.draw(context)
    else:
        # 左侧：贴图项列表 (勾选只控制导出，点击选择活跃项)
        # 右侧：详情面板 (显示当前选中贴图的 预览按钮 + 专属设置菜单)
        split_maps = box_maps.split(factor=0.42)

        col_list = split_maps.column(align=True)
        col_detail = split_maps.column()

        active_type = getattr(gd, "active_baker_type", "normals") or "normals"
        active_index = getattr(gd, "active_baker_index", 0)
        active_baker_obj = None

        for baker_prop in get_baker_collections():
            for baker in baker_prop:
                if not baker.visibility:
                    continue

                if baker.ID == active_type and baker.index == active_index:
                    active_baker_obj = baker

                row = col_list.row(align=True)
                if gd.engine == 'marmoset' and (len(baker.REQUIRED_SOCKETS) > 0 or baker.ID == 'custom'):
                    row.active = False

                # 1. 勾选框：仅开启/关闭导出功能，绝对不在此处下压展开菜单
                row.prop(baker, 'enabled', text="")

                # 2. 点击项名称：选择活跃贴图项
                is_selected = (baker.ID == active_type and baker.index == active_index)
                op_select = row.operator(
                    "grabdoc.select_active_baker",
                    text=baker.get_display_name(),
                    depress=is_selected
                )
                op_select.map_type = baker.ID
                op_select.baker_index = baker.index

                # 3. 单个导出按钮
                row.operator("grabdoc.baker_export_single", text="", icon='RENDER_STILL').map_type = baker.ID

                # 4. 添加/删除同类 Baker 按钮
                if baker == getattr(gd, baker.ID)[0]:
                    row.operator("grabdoc.baker_add", text="", icon='ADD').map_type = baker.ID
                else:
                    remove = row.operator("grabdoc.baker_remove", text="", icon='TRASH')
                    remove.map_type = baker.ID
                    remove.baker_index = baker.index

        # 如果没有找到匹配的 selected baker，默认选中第一个可视项
        if not active_baker_obj:
            for baker_prop in get_baker_collections():
                for baker in baker_prop:
                    if baker.visibility:
                        active_baker_obj = baker
                        gd.active_baker_type = baker.ID
                        gd.active_baker_index = baker.index
                        break
                if active_baker_obj:
                    break

        # 右侧列：绘制当前选中贴图的 预览按钮 与 专属设置菜单
        if active_baker_obj:
            box_detail = col_detail.box()
            header_det = box_detail.row(align=True)
            header_det.label(text=f"{active_baker_obj.get_display_name()} 详情与设置", icon='PROPERTIES')

            # 预览按钮
            row_p = box_detail.row(align=True)
            row_p.scale_y = 1.2
            preview = row_p.operator("grabdoc.baker_preview", text=f"预览 {active_baker_obj.get_display_name()}")
            preview.map_type = active_baker_obj.ID
            preview.baker_index = active_baker_obj.index

            box_detail.separator()

            # 设置菜单
            active_baker_obj.draw(context, box_detail)

