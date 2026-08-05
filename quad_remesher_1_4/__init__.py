# "Quad-Remesher Bridge for Blender"
# Author : Maxime Rouca
#
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

__QR_plugin_version__ = "1.41"

bl_info = {
    "name": "四边面重构器",
    "author": "Maximee",
    "version": (1, 4, 0),
    "blender": (4, 2, 0),
    "description": "四边面重构器 1.40 桥接",
	"location": "N-Panel",
    "warning": "",
	"doc_url": "",
	"tracker_url": "",
    "category": "Mesh"
}

import bpy
import bpy.props
# from rna_keymap_ui import draw_kmi
# from bl_operators.presets import AddPresetBase

from .qr_operators import (QREMESHER_OT_remesh, QREMESHER_OT_reset_settings, QREMESHER_OT_license_manager, QREMESHER_OT_facemap_to_materials, QREMESHER_OT_faceset_to_materials, QREMESHER_OT_online_help, QREMESHER_OT_News_LatestVer)

#MODIFICATION: import the function that will overwrite the UI
from .modded_ui import (
    overwrite_draw_method,
)
#MODIFICATION: import the operators module
from . import modded_operators

addon_name = __name__.split(".")[0]

#def addon_prefs():
#    return bpy.context.preferences.addons[addon_name].preferences

def paintDensityPropertyCB(self, context):
    #try:
    props = bpy.context.scene.qremesher
    vertexColorSliderValue = getattr(props, 'painted_quad_density')
    
    #print("vertexColorSliderValue = " + str(vertexColorSliderValue) + "\n")

    #Mapping: Slider in [0.25, 4]
    maxSliderValue = 4
    minSliderValue = 0.25
    normalizedValue = 0.0
    if vertexColorSliderValue > 1.0:
        normalizedValue = (vertexColorSliderValue - 1.0) / (maxSliderValue - 1.0)
    elif vertexColorSliderValue < 1.0:
        normalizedValue =  - ((1.0/vertexColorSliderValue) - 1.0) / ((1.0/minSliderValue) - 1.0)

    if (normalizedValue > 1):
        normalizedValue = 1
    if (normalizedValue < -1):
        normalizedValue = -1

    # -- normalizedValue to color
    r = 1.0
    g = 1.0
    b = 1.0
    if normalizedValue > 0.0:
        r = 1
        g = 1-normalizedValue
        b = 1-normalizedValue
    elif normalizedValue < 0.0:
        r = 1+normalizedValue
        g = 1
        b = 1
        
    # set the color
    mycolor=(r, g, b)
    #MODIFICATION: use a different brush for density paint
    #bpy.data.brushes["Draw"].color = mycolor
    modded_operators.overwrite_density_paint(mycolor)

    #except Exception:
    #    print("Exception: in paintDensityPropertyCB..\n")
    return


   
#MODIFICATION: functions to react to properties being changed
        
def QuadCountChanged(self, context):
    qremesher = context.scene.qremesher
    if qremesher.quad_count_mode != 'CUSTOM':
        qremesher.quad_count_mode ='CUSTOM'

def InitializeDensityPaint(self, context):
    # safety check for no object selected
    if context.object == None:
        return
    if not context.scene.qremesher.use_vertex_color:
        return
        
    if "qremesher_density" not in context.object.data.attributes:
        bpy.ops.geometry.color_attribute_add(
            name="qremesher_density",
            data_type='BYTE_COLOR',
            color=(1, 1, 1, 1)
        )

    # activate Paint Soft brush from Essentials
    bpy.ops.brush.asset_activate(
        asset_library_type='ESSENTIALS',
        asset_library_identifier="",
        relative_asset_identifier="brushes\\essentials_brushes-mesh_sculpt.blend\\Brush\\Paint Soft",
    )

# switch mesh data immediately when an entry in remesh history is clicked on
# (no need for an extra "apply" button this way)
def HistoryActiveChange(self, context):
    qremesher = context.scene.qremesher
    if qremesher.history_object != None:
        qremesher.history_object.data = qremesher.history[qremesher.history_active].mesh
    
def ReprojectSubdivsChange(self, context):
    obj = context.object
    qremesher = context.scene.qremesher
    mod = obj.modifiers["QRemesher_SubSurf"]
    mod.levels = qremesher.reproject_subdivisions
    
    # store polycount after subdivision change, so the UI doesn't check it too often
    # (this one needs the value after modifiers are done)
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    qremesher.reproject_polycount = len(obj_eval.data.polygons)

 
#MODIFICATION: define the remesh history item (has to be registered before history prop)
class QREMESHER_HistoryItem(bpy.types.PropertyGroup):
    # ? make a separate name prop instead of using mesh name?
    #name: bpy.props.StringProperty(name="Name", default="Mesh")
    mesh: bpy.props.PointerProperty(type=bpy.types.Mesh)
    mode: bpy.props.StringProperty(default='CUSTOM') 
    quads: bpy.props.IntProperty(default=-1)  
    reprojected: bpy.props.BoolProperty(default=False)  

# ----- Properties container ------
class QRSettingsPropertyGroup(bpy.types.PropertyGroup):
    # Target Quad Count
    target_count: bpy.props.IntProperty(
        name="四边形数量",
        description="设置所需四边形数量",
        default=5000, soft_min=100, soft_max=10000, step=20, min = 1,
        #MODIFICATION: add a function to react to quad count change
        update=QuadCountChanged,
    )

    curvatureAdaptivness_Tooltip = "控制四边形大小如何局部适应曲率。\n值越高，高曲率区域四边形越小。\n设置为0可获得均匀四边形大小"
    adaptQuadCount_Tooltip = "自适应四边形数量：\n开启：创建比要求更多的多边形以适应高曲率区域。\n关闭（默认）：更精确地遵循目标四边形数量。\n建议让其保持'关闭'以更好地遵循目标四边形数量。"
    useVertexColors_Tooltip = "使用'顶点颜色'控制四边形大小密度。"
    vertexColorWidget_Tooltip = "定义用于控制所需四边形密度变化的颜色（使用'绘制'工具，在'顶点绘制'模式下）\n . 从0.25 => '密度除以4' = 大四边形 = 青色\n . 到4 => '密度乘以4' = 小四边形 = 红色。"
    useMaterials_Tooltip="如果开启，四边形重构器将使用现有的'材质'来引导四边形重构。\n材质索引将在重构后保持。"
    useNormals_Tooltip="注意：此选项在特定情况下有用，但默认应保持'关闭'（多面体网格）。阅读文档获取更多信息..."
    useNormals_Tooltip+="\n如果开启，四边形重构器将使用现有的'法线'来引导重构，在法线分割/折痕边缘处形成边环。\n默认情况下，Blender在所有边缘创建分割法线。\n仅当启用SmoothShade + AutoSmooth时启用此选项是有用的...\n在平滑有机形状上，建议禁用它。"
    detectHardEdges_Tooltip="如果开启，四边形重构器将基于几何体自动检测/计算硬边（使用边缘角度和其他几何考虑因素的混合）。\n如果'使用法线分割'被勾选，通常最好取消勾选'按角度检测硬边'。\n在平滑有机形状上，建议禁用它。"
    symToolTip = "这些选项允许执行对称的四边形重构。可以组合所有3个对称轴。"
    #symToolTip += "\n注意：轴是局部坐标轴！建议将Gizmo设置为'对象'模式以更好地查看局部坐标轴。"
    hideInputTip = "如果开启（默认），输入对象将在重构后隐藏。"
    
    # Quads size settings
    adaptive_size: bpy.props.FloatProperty(name="自适应大小", 
                                         description=curvatureAdaptivness_Tooltip,
                                         default=50, min=0, max=100, step=0.5, precision=0, subtype = 'PERCENTAGE')

    adapt_quad_count: bpy.props.BoolProperty(name="自适应四边形数量", default=True, 
                                            description=adaptQuadCount_Tooltip)
    
    use_vertex_color: bpy.props.BoolProperty(name="使用顶点颜色", 
                                            description=useVertexColors_Tooltip,
                                            default=False,
                                            #MODIFICATION:
                                            # make sure density attribute exists before painting
                                            update=InitializeDensityPaint,
                                            )

    painted_quad_density: bpy.props.FloatProperty(name="四边形密度（绘制）", 
                                            description=vertexColorWidget_Tooltip,
                                           default=1.0, min=0.25, max=4.0, step=0.4,
                                           #MODIFICATION: make the density slider look nicer
                                           subtype='FACTOR',
                                           update=paintDensityPropertyCB)

    # Edge loops control
    use_materials: bpy.props.BoolProperty(name="使用材质", default=False, 
                                            description = useMaterials_Tooltip)
    use_normals: bpy.props.BoolProperty(name="使用法线分割", 
                                        default=False,                    #because when I create a sphere, all edges are 'creased', not a good idea to enable this by default...
                                        description=useNormals_Tooltip)
    autodetect_hard_edges: bpy.props.BoolProperty(name="按角度检测硬边", 
                                                    #MODIFICATION: yeah, I prefer it off by default :P
                                                    default=False, 
                                                    description=detectHardEdges_Tooltip)

    # Misc category
    symmetry_x: bpy.props.BoolProperty(name="X", default=False, description=symToolTip)
    symmetry_y: bpy.props.BoolProperty(name="Y", default=False, description=symToolTip)
    symmetry_z: bpy.props.BoolProperty(name="Z", default=False, description=symToolTip)
    
    hide_input: bpy.props.BoolProperty(name="隐藏输入对象", default=True, description=hideInputTip)
    
    # progress bar value
    progress_value: bpy.props.FloatProperty(default=0, subtype='PERCENTAGE', precision=1, min=0, soft_min=0, soft_max=100, max=100)
    
    #MODIFICATION: add more config properties
    quad_count_mode: bpy.props.EnumProperty(
        items=(
                ('CUSTOM', "自定义", "设置自定义面数", 0),
                ('HALF', "减半", "对象面数的一半", 1),
                ('SAME', "相同", "与对象面数相同", 2),
                ('DOUBLE', "翻倍", "对象面数的两倍", 3),
        ),
        default='CUSTOM',
    )
    use_face_sets: bpy.props.BoolProperty(
        name="使用面集",
        default=False, 
        description = "面集将用于引导重构。\n\n材质不会被保留",
    )
    # dummy prop for 'use_materials' to avoid weird UI stuff
    use_material_index: bpy.props.BoolProperty(
        name="使用材质",
        default=False, 
        description = "材质将用于引导重构。\n\n注意：不能与'使用面集'选项一起使用",
    )
    history_object: bpy.props.PointerProperty(type=bpy.types.Object)
    history_active: bpy.props.IntProperty(
        name="切换到此网格数据",
        default=0,
        update=HistoryActiveChange,
    )
    history: bpy.props.CollectionProperty(type=QREMESHER_HistoryItem)
    in_reproject_mode: bpy.props.BoolProperty(default=False)
    reproject_polycount: bpy.props.IntProperty(default=0)
    reproject_target: bpy.props.PointerProperty(type=bpy.types.Object)
    reproject_subdivisions: bpy.props.IntProperty(
        name = "细分级别",
        description = "在重新投影之前应用的细分级别",
        default=0, min=0, max=6, soft_max=4,
        update=ReprojectSubdivsChange,
    )


def draw_panel_content(context, layout):
    #print("draw_panel_content called")
    # NB: this function is called very often (example, quite at each mouse move in the panel...)
    
    props = bpy.context.scene.qremesher
    #props = addon_prefs().props

    wm = context.window_manager

    # "REMESH IT" button
#    if QREMESHER_OT_remesh.IsRemeshing:
#        myrow = layout.row(align=True)
#        myrow.label(text="(ESC)")
#        myrow.prop(props, 'progress_value')
#        #layout.prop(props, 'progress_value')
    layout.operator(QREMESHER_OT_remesh.bl_idname)
    layout.separator()
        
    # Settings
    col = layout.column(align=True)
    # row = col.row(align=True)
    col.prop(props, 'target_count')

    col.separator()

    # --- Quad Size settings ---
    box = col.box()
    box.label(text="  四边形大小设置")

    box.prop(props, 'adaptive_size')
    box.prop(props, 'adapt_quad_count')
    box.prop(props, 'use_vertex_color')

    #box.separator()
    box.prop(props, 'painted_quad_density')

    col.separator()

    # --- Quad Size settings ---
    box = col.box()
    box.label(text="  边环控制")

    box.prop(props, 'use_materials')
    box.prop(props, 'use_normals')
    box.prop(props, 'autodetect_hard_edges')

    col.separator()

    # --- Misc.... ---
    box = col.box()
    box.label(text="  其他")
    box.label(text="对称性:")
    myrow = box.row(align=True)
    myrow.prop(props, 'symmetry_x')
    myrow.prop(props, 'symmetry_y')
    myrow.prop(props, 'symmetry_z')
    box.prop(props, 'hide_input')
    box.operator(QREMESHER_OT_reset_settings.bl_idname)
    # box.operator(QREMESHER_OT_license_manager.bl_idname)
    if bpy.app.version[0] >= 4:
        box.operator(QREMESHER_OT_faceset_to_materials.bl_idname)
    else:
        box.operator(QREMESHER_OT_facemap_to_materials.bl_idname)
    box.operator(QREMESHER_OT_online_help.bl_idname)
  



# Side panel ui
class QREMESHER_PT_qremesher(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '四边面重构'        # name of the VerticalTab
    bl_label = "四边面重构器 "+__QR_plugin_version__

    bl_idname = "QREMESHER_PT_qremesher"

    # bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True
    
    def draw_header_preset(self, context): 
        layout = self.layout
        row= layout.row()
        row.operator(QREMESHER_OT_online_help.bl_idname, text="", icon='HELP')

    def draw(self, context):
        draw_panel_content(context, self.layout)


# Scene settings subpanel
'''
class QREMESHER_PT_qremesher_setting_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'QRemesher'
    bl_label = "Settings"

    bl_idname = "QREMESHER_PT_qremesher_setting_panel"
    bl_parent_id = "QREMESHER_PT_qremesher"   # NB: ca suffit a ajouter ce sub panel dans le panel QREMESHER_PT_qremesher

    # bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):

        self.layout.operator(QREMESHER_OT_reset_settings.bl_idname)

        self.layout.separator()

        #draw_panel_content(context, self.layout)
'''


classes = [
            #MODIFICATION: register object stack item, needs to be registered before group
            QREMESHER_HistoryItem,
            
            QRSettingsPropertyGroup,
        
           #QREMESHER_PT_qremesher,
           #QREMESHER_PT_qremesher_setting_panel,

           QREMESHER_OT_remesh,
           QREMESHER_OT_reset_settings,
        #    QREMESHER_OT_license_manager,
           QREMESHER_OT_facemap_to_materials, # Blender 3.x
           QREMESHER_OT_faceset_to_materials, # Blender 4.x
           QREMESHER_OT_online_help,
           # QREMESHER_OT_News_LatestVer,
           
           ]
addon_keymaps = []


def hotkeys():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc:
        if '3D View' not in kc.keymaps:
            km_view3d = kc.keymaps.new('3D View', space_type='VIEW_3D', region_type='WINDOW')
        else:
            km_view3d = kc.keymaps['3D View']

        kmi = km_view3d.keymap_items.new(QREMESHER_OT_remesh.bl_idname, head=True, type='R', value='PRESS',
                                         ctrl=True, alt=True)

        addon_keymaps.append((km_view3d, kmi))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.qremesher = bpy.props.PointerProperty(type=QRSettingsPropertyGroup)
    # QREMESHER_OT_News_LatestVer.readNews()
    
    #MODIFICATION: register the added modules
    modded_ui.register()
    modded_operators.register()
    
    hotkeys()
    
    #MODIFICATION: overwrite the draw method of the main panel if registered
    if hasattr(bpy.types, "QREMESHER_PT_qremesher"):
        bpy.types.QREMESHER_PT_qremesher.draw = overwrite_draw_method


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    
    #MODIFICATION: unregister the added modules
    modded_operators.unregister()
    modded_ui.unregister()
    
    del bpy.types.Scene.qremesher

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc:
        for km, kmi in addon_keymaps:
            km.keymap_items.remove(kmi)
    addon_keymaps.clear()

