import bpy

from .modded_operators import format_num

def has_active_modifier(obj, name):
    if name in obj.modifiers:
        return obj.modifiers[name].show_viewport
    else:
        return False

def box_layout(text, icon, layout, height=0.8):

    box = layout.box()
    col = box.column()
    
    title = col.box()
    title.scale_y = height
    row = title.row(align=False)
    row.label(text=text, icon=icon)
    col.separator(factor=0.5)
    
    return row, col
    
def title_box(layout, text="Title", icon='NONE', height=0.8, align=False):
    box = layout.box()
    row = box.row(align=align)
    row.label(text=text, icon=icon)
    
    return row
    
def category_box(layout, spacing=0.5):
    cat = layout.box().column(align=False)
    return cat
 
def sub_box(layout):
    sub = layout.box().column()
    return sub



def draw_quad_remesher_ui(layout, context):
    qremesher = context.scene.qremesher
    obj = context.object
    count_mode = qremesher.quad_count_mode
    
    # ---- TITLE ---- #
    cat = category_box(layout)
    # title = title_box(cat, text="四边面重构器 1.40", icon='MOD_REMESH')
    # title.menu("QREMESHER_MT_InfoMenu", text="", icon='HELP')
    
    # 重构按钮
    row = cat.row()
    row.scale_y = 1.5
    row.operator("qremesher.remesh", depress=False)
   
    # 子列用于对齐按钮
    sub = cat.column(align=True)
    
    # 四边形数量自定义输入
    row = sub.row(align=True)
    row.scale_y = 1.2
    row.active = (count_mode == 'CUSTOM')
    row.prop(qremesher, 'target_count')
    
    # 四边形数量自定义值
    presets = (500, 1000, 2000, 5000, 10000)
    
    row = sub.row(align=True)
    for amount in presets:
        active = (count_mode == 'CUSTOM' and qremesher.target_count == amount)
        op = row.operator("qremesher.set_quad_count", text=format_num(amount), depress=active)
        op.amount = amount
    
    # 四边形数量相对值
    row = sub.row(align=True)
    # 分离为 prop_enum 以在 UI 中跳过 'CUSTOM' 模式
    row.prop_enum(qremesher, "quad_count_mode", 'HALF')
    row.prop_enum(qremesher, "quad_count_mode", 'SAME')
    row.prop_enum(qremesher, "quad_count_mode", 'DOUBLE')
    
    
    # ---- 设置 ---- #
    cat = category_box(layout)
    title = title_box(cat, text="设置", icon='PREFERENCES')
    title.operator("qremesher.reset_settings", text="", icon='FILE_REFRESH')
    
    
    # -- 四边形大小设置 -- 
    cat.prop(qremesher, 'adaptive_size')
    sub = sub_box(cat)
    sub.prop(qremesher, 'adapt_quad_count')
    sub.prop(qremesher, 'use_vertex_color')
    if qremesher.use_vertex_color:
        
        row = sub.row(align=True)
        try:
            active = (context.tool_settings.sculpt.brush.name == "Paint Soft")
        except Exception as e:
            active = False
            
        op = row.operator("brush.asset_activate", text="", icon="BRUSH_DATA", depress=active)
        op.asset_library_type='ESSENTIALS'
        op.asset_library_identifier=""
        op.relative_asset_identifier="brushes\\essentials_brushes-mesh_sculpt.blend\\Brush\\Paint Soft"
        
        row.prop(qremesher, 'painted_quad_density')


    # -- 边环控制 -- 
    sub = sub_box(cat)
    sub.prop(qremesher, 'use_face_sets')
    sub.prop(qremesher, 'use_material_index')
    sub.prop(qremesher, 'use_normals')
    sub.prop(qremesher, 'autodetect_hard_edges', text="检测硬边")
    
    if obj != None:
        row = cat.row(align=True)
        row.prop(obj, 'use_mesh_mirror_x', text="X", toggle=True)
        row.prop(obj, 'use_mesh_mirror_y', text="Y", toggle=True)
        row.prop(obj, 'use_mesh_mirror_z', text="Z", toggle=True)


    # ---- HISTORY ---- #
    if (
        obj == qremesher.history_object and
        len(qremesher.history) > 0 and
        not qremesher.in_reproject_mode
        ):
        cat = category_box(layout)
        title = title_box(cat, text="历史记录", icon='PRESET')
        title.operator("qremesher.reproject_mode_start", text="", icon='CON_SHRINKWRAP')
        #title.operator("qremesher.purge_mesh_history", text="", icon='TRASH')
        
        sub = sub_box(cat)
        sub.template_list(
            "QREMESHER_UL_History",
            "",
            qremesher,
            "history",
            qremesher,
            "history_active",
            rows=3,
        )
        
    # sub.label(text="History disabled while Re-projection is active", icon="ERROR")
    
    ## Reprojection 
    if qremesher.in_reproject_mode:
        cat = category_box(layout)
        title = title_box(cat, text="重投影", icon='CON_SHRINKWRAP', align=True)
        title.operator("qremesher.reproject_mode_finish", text="", icon='CHECKMARK')
        title.operator("qremesher.reproject_mode_cancel", text="", icon='X')

        sub = sub_box(cat)
        row = sub.row(align=True)
        row.scale_x = 1.5
        shape = has_active_modifier(obj, "QRemesher_Shrinkwrap")
        color = has_active_modifier(obj, "QRemesher_DataTransfer")
        polycount = qremesher.reproject_polycount
        
        row.prop(qremesher, "reproject_subdivisions", text="Subdivisions")
        
        row = sub.row(align=True)
        row.operator("qremesher.reproject_shape", text="形状", icon='MOD_SHRINKWRAP', depress=shape)
        row.operator("qremesher.reproject_color", text="颜色", icon='MOD_DATA_TRANSFER', depress=color)
        
        sub.label(text="最终多边形数："+str(polycount))


def overwrite_draw_method(self, context):
    draw_quad_remesher_ui(self.layout, context)


class QREMESHER_UL_History(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ): 
        row = layout.row(align=True)
        row.prop(item.mesh, "name", text="", icon_value=icon, emboss=False)
        sub = row.row(align=False)
        sub.alignment = 'RIGHT'
        sub.active = False
        if index == 0:
            sub.label(text="原始")
        elif item.reprojected:
            sub.label(text="重投影")
        else:
            if item.mode != 'CUSTOM':
                name = context.scene.qremesher.bl_rna.properties['quad_count_mode'].enum_items[item.mode].name
                sub.label(text=name)  
            else:
                sub.label(text=format_num(item.quads))
    def draw_filter(self, context, layout):
        layout.label(text="这里没有过滤选项！")
        layout.label(text="我就是不能移除这个箭头 >:[")


class QREMESHER_MT_InfoMenu(bpy.types.Menu):
    bl_label = "Info"

    def draw(self, context):
        layout = self.layout
        
        # layout.operator("qremesher.license_manager")
        layout.operator("qremesher.online_help")
        # layout.operator("qremesher.latestver", text="Latest Version")
        

classes = [
    
    QREMESHER_UL_History,
    QREMESHER_MT_InfoMenu,

]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
