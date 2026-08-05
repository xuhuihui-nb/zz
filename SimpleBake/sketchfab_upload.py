from .utils import get_sb_prefs
import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

import os
from pathlib import Path
from zipfile import ZipFile
import webbrowser

from . import sketchfabapi
from .utils import get_base_folder_patho, clean_file_name, is_blend_saved
from .messages import print_message

def get_file_name():
    fullpath = bpy.data.filepath
    pathelements = os.path.split(fullpath)
    return pathelements[1]

class SimpleBake_OT_Sketchfab_Upload(Operator):
    """Upload selected SimpleBake generated objects to Sketchfab"""
    bl_idname = "simplebake.sketchfab_upload"
    bl_description = "Upload selected SimpleBake generated objects to Sketchfab. Your blend file must be saved. You can only upload objects created with SimpleBake's 'Copy objects and apply bakes' option. Select those object(s) in the viewport and click upload."
    bl_label = "Upload"
    
    @classmethod
    def poll(cls,context):

        if not is_blend_saved():
            return False
        
        if context.mode != "OBJECT":
            return False
        
        sbp = context.scene.SimpleBake_Props
        
        objs_list = context.selected_objects
        r =[o for o in objs_list if "SB_bake_operation_id" in o]
        
        if len(objs_list) == 0: return False
        elif len(r) == len(objs_list): return True
        else: return False
    
    def execute(self, context):
    
        print_message(context, "Sketchfab Upload Beginning")

        #Get the currently selected objects
        objs_list = context.selected_objects

        #Get all the textures being used by our objects. Should only have one material each
        images_imgs = []
        for obj in objs_list:
            nodes = obj.material_slots[0].material.node_tree.nodes
            for node in nodes:
                if node.bl_idname == "ShaderNodeTexImage":
                    images_imgs.append(node.image)

        #Create a temp folder for SFUpload in the folder where blend saved
        f = get_base_folder_patho(context) / "SFUpload"

        if not os.path.isdir(str(f)):
            os.mkdir(str(f))
            
        #Save each image into that folder

        writtenfilenames_strlist = []
        for img in images_imgs:
            
            #If it is internal only
            if img.filepath == "":
                #Just set it's file path and save. This one is easy
                img.file_format = "PNG"
                img.filepath = str(f / clean_file_name(img.name)) + ".png"
                img.save()
                writtenfilenames_strlist.append(Path(img.filepath).parts[-1])
                img.filepath = ""

            #If it's already been saved externally, copy it
            else:
                op = img.filepath
                off = img.file_format

                img.pack() #Or else changing its filepath will screw it up
                img.file_format = "PNG"
                img.filepath = str(f / clean_file_name(img.name)) + ".png"
                
                img.save()
                writtenfilenames_strlist.append(Path(img.filepath).parts[-1])
                
                img.unpack(method="REMOVE")
                img.filepath = op
                img.file_format = off
            
            #In either case, add the image name to our list
            


        #Export the fbx (we might have multiple objects)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objs_list:
            obj.select_set(state=True)

        filename = get_file_name().replace(".blend", "")
        bpy.ops.export_scene.fbx(filepath=str(f / f"{filename}.fbx"), check_existing=False, use_selection=True, use_mesh_modifiers=True, use_mesh_modifiers_render=True, path_mode="STRIP")

        #Zip it up
        zip_path = str(f / f"{filename}.zip")
        zip = ZipFile(str(zip_path), mode="w")
        
        #First the images
        for fn in writtenfilenames_strlist:
            zip.write(str(f / fn), arcname=fn)

        #And now the fbx
        zip.write(str(f / f"{filename}.fbx"), arcname=f"{filename}.fbx")
        zip.close()

        #Get Sketchfab API key
        preferences = context.preferences
        addon_prefs = get_sb_prefs(context)
        apikey = addon_prefs.apikey
        
        #Call Sketchfab Upload
        upload_url = sketchfabapi.upload(zip_path, get_file_name(), apikey)

        if not upload_url:
            print_message(context, "Upload to Sketchfab failed. See console messages for details")
            return False
        else:
            #Open URL that is returned
            webbrowser.open(upload_url, new=0, autoraise=True)
            print_message(context, "Upload complete. Your web broswer should have opened.")

        #Delete Zip file
        #os.remove(zip_path)

        return {'FINISHED'}

classes = ([
    SimpleBake_OT_Sketchfab_Upload
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
