import bpy
from bpy.types import Operator, UIList
from bpy.utils import register_class, unregister_class

from ..utils import SBConstants, clean_file_name

class SIMPLEBAKE_UL_CPTexList(UIList):
    """UIList."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):

        # We could write some code to decide which icon to use here...
        custom_icon = 'NODE_COMPOSITING'

        # Make sure your code supports all 3 layout types
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name, icon = custom_icon)

        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon = custom_icon)
            

class SimpleBake_OT_cptex_add(Operator):
    """Add a SimpleBake CP Texture item"""
    bl_idname = "simplebake.cptex_add"
    bl_label = "Add"
    
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        return sbp.cp_name != ""
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        cp_list = sbp.cp_list
        name = clean_file_name(sbp.cp_name)
        
        if name in cp_list:
            #Delete it
            index = sbp.cp_list.find(name)
            sbp.cp_list.remove(index)
            
        li = cp_list.add()
        li.name = name
        
        li.R = sbp.cptex_R
        li.G = sbp.cptex_G
        li.B = sbp.cptex_B
        li.A = sbp.cptex_A
        li.file_format = sbp.channelpackfileformat
        li.exr_codec = sbp.exr_codec_cpts
        li.png_compression = sbp.png_compression
        
        sbp.cp_list_index = sbp.cp_list.find(name)
        
        self.report({"INFO"}, "CP texture saved")
        return {'FINISHED'} 

class SimpleBake_OT_cptex_delete(Operator):
    """Delete the selected channel pack texture"""
    bl_idname = "simplebake.cptex_delete"
    bl_label = "Delete"
    
    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        try:
            sbp.cp_list[sbp.cp_list_index].name
            return True
        except:
            return False
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        sbp.cp_list.remove(sbp.cp_list_index)
        
        self.report({"INFO"}, "CP texture deleted")
        return {'FINISHED'} 

class SimpleBake_OT_cptex_set_defaults(Operator):
    """Add some example channel pack textures"""
    bl_idname = "simplebake.cptex_set_defaults"
    bl_label = "Add examples"
    
    @classmethod
    def poll(cls,context):
        return True
        
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        
        cp_list = sbp.cp_list
        
        #Unity Lit shader. R=metalness, G=AO, B=N/A, A=Glossy.
        li = cp_list.add()
        li.name = "Unity Lit Shader"
        li.file_format = "OPEN_EXR"
        li.R = "Metalness"
        li.G = SBConstants.AO
        li.B = "none"
        li.A = "Glossiness"
        
        #Unity Legacy Standard Diffuse. RGB=diffuse, A=alpha.
        li = cp_list.add()
        li.name = "Unity Legacy Shader"
        li.file_format = "OPEN_EXR"
        li.R = "Diffuse"
        li.G = "Diffuse"
        li.B = "Diffuse"
        li.A = "Alpha"
        
        #ORM format. R=AO, G=Roughness, B=Metalness, A=N/A.
        li = cp_list.add()
        li.name = "ORM"
        li.file_format = "OPEN_EXR"
        li.R = SBConstants.AO
        li.G = "Roughness"
        li.B = "Metalness"
        li.A = "none"
        
        #diffuse plus specular in the alpha channel.
        li = cp_list.add()
        li.name = "Diffuse and Spec in alpha"
        li.file_format = "OPEN_EXR"
        li.R = "Diffuse"
        li.G = "Diffuse"
        li.B = "Diffuse"
        li.A = "Specular"
        
        
        self.report({"INFO"}, "Default textures added")
        return {'FINISHED'} 



classes = ([
        SIMPLEBAKE_UL_CPTexList,
        SimpleBake_OT_cptex_add,
        SimpleBake_OT_cptex_delete,
        SimpleBake_OT_cptex_set_defaults
        ])

def register():
    global classes
    for cls in classes:
        try:
            unregister_class(cls)
        except Exception:
            pass
        try:
            register_class(cls)
        except Exception as e:
            pass

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)
