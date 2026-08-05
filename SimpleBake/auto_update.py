import bpy
from urllib.request import urlopen
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
import base64
from pathlib import Path
import os
import urllib.request
import shutil

from .utils import show_message_box
from .messages import print_message

def ignore_delete_errors(func, path, exc_info):
    # This function is called when shutil.rmtree hits an error.
    # Just ignore the error and move on.
    print(f"Could not delete {path}. Ignoring. Reason: {exc_info[1]}")


class VersionControl:
    #Non-Blender class
    was_error = False
    at_current = True
    installed_version = False #Will be set by init - Tuple
    installed_version_str = ""
    current_version_str = ""
    just_updated = False
    
    @classmethod
    def check_at_current_version(cls, no_online_check):
        iv = cls.installed_version
        iv = str(iv[0]) + str(iv[1]) + str(iv[2])
        iv = int(iv)
        
        #For use in the panel
        cls.installed_version_str = str(cls.installed_version).replace(",",".").replace(")","").replace("(","")
    
        #If we aren't checking online, wrap it up here
        if no_online_check:
            return True
        
        
        #Grab the most recent version from my website
        link = "http://www.toohey.co.uk/SimpleBake/currentversion4"
    
        cver = 0
        try:
            f = urlopen(link, timeout=5)
            cver = f.read()
            cver = cver.decode("utf-8")
            cls.current_version_str = cver
            cver = cver.replace(".","")
            cver = int(cver)
    
        except Exception as e:
            cls.was_error = True
            print_message(bpy.context, "Unable to check for latest version of SimpleBake - are you online?", screen=False)
            cver = iv
            print_message(bpy.context, str(e), screen=False)
        
        if cver > iv:
            cls.at_current = False
            print_message(bpy.context, "There is a newer version of SimpleBake available", screen=False)
        else:
            cls.at_current = True
            print_message(bpy.context, "Your copy of SimpleBake is up to date", screen=False)
    
class SimpleBake_OT_Auto_Update(Operator):
    """Download and install updated version of SimpleBake"""
    bl_idname = "simplebake.auto_update"
    bl_label = "Update"        
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
    
        try:
            #Current ver URL
            current_ver_url = base64.b64decode("aHR0cDovL3d3dy50b29oZXkuY28udWsvU2ltcGxlQmFrZS9TaW1wbGVCYWtlX0N1cnJlbnQ0LnppcA==").decode("utf-8")
            current_ver_zip_name = "SimpleBake_Curent4.zip"
            addon_dir_name =  "SimpleBake"
    
            import zipfile #only needed here
    
            #Get the path where the addons are kept
            #if bpy.utils.script_path_pref() != None:
                #addons_path = Path(bpy.utils.script_path_pref())
            #else:
                #addons_path = Path(bpy.utils.script_path_user())
            #addons_path = addons_path / "addons"
    
            #Get the addons folder (alternative method)
            addons_path = Path(os.path.dirname(__file__)).parents[0]
            print_message(context, f"Addons folder: {addons_path}")
            
            #Make our current directory the addons directory
            os.chdir(str(addons_path))
    
            #Download new SimbleBake_Current.zip to addons folder
            print_message(context, "Starting download")
            urllib.request.urlretrieve(current_ver_url, current_ver_zip_name)
            current_ver_zip_name = "SimpleBake_Curent4.zip"
            print_message(context, "Download complete")
        
            #Delete current SimpleBake folder
            addon_dir = addons_path / addon_dir_name
            shutil.rmtree(str(addon_dir), onerror=ignore_delete_errors)
    
            #Unzip
            current_ver_zip = zipfile.ZipFile(current_ver_zip_name, "r")
            current_ver_zip.extractall()
            current_ver_zip.close()
        
            #Delete the zip file we downlaoded
            downloaded_zip = addons_path / current_ver_zip_name
            downloaded_zip.unlink()
        
            #Report
            message_lines = ["SimpleBake update complete", "Please restart Blender"]
            show_message_box(context, message_lines, "Update complete", icon = 'INFO')
            print_message(context, "Update complete. Please restart Blender")
            
            VersionControl.just_updated = True
            
            return {'FINISHED'}
        
        except Exception as e:
            print_message(context, str(e))
            return {'CANCELLED'}

class SimpleBake_OT_Rollback_Update(Operator):
    """Download and install previous version of SimpleBake"""
    bl_idname = "simplebake.rollback_update"
    bl_label = "Rollback"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        try:
            #Current ver URL
            current_ver_url = base64.b64decode("aHR0cDovL3d3dy50b29oZXkuY28udWsvU2ltcGxlQmFrZS9TaW1wbGVCYWtlX1ByZXZpb3VzNC56aXA=").decode("utf-8")
            current_ver_zip_name = "SimpleBake_Previous4.zip"
            addon_dir_name =  "SimpleBake"

            import zipfile #only needed here

            #Get the addons folder (alternative method)
            addons_path = Path(os.path.dirname(__file__)).parents[0]
            print_message(context, f"Addons folder: {addons_path}")

            #Make our current directory the addons directory
            os.chdir(str(addons_path))

            #Download new SimbleBake_Current.zip to addons folder
            print_message(context, "Starting download")
            urllib.request.urlretrieve(current_ver_url, current_ver_zip_name)
            print_message(context, "Download complete")

            #Delete current SimpleBake folder
            addon_dir = addons_path / addon_dir_name
            shutil.rmtree(str(addon_dir), onerror=ignore_delete_errors)

            #Unzip
            current_ver_zip = zipfile.ZipFile(current_ver_zip_name, "r")
            current_ver_zip.extractall()
            current_ver_zip.close()

            #Delete the zip file we downlaoded
            downloaded_zip = addons_path / current_ver_zip_name
            downloaded_zip.unlink()

            #Report
            message_lines = ["SimpleBake rollback complete", "Please restart Blender"]
            show_message_box(context, message_lines, "Rollback complete", icon = 'INFO')
            print_message(context, "Rollback complete. Please restart Blender")

            VersionControl.just_updated = True

            return {'FINISHED'}

        except Exception as e:
            print_message(context, str(e))
            return {'CANCELLED'}



classes = ([
    SimpleBake_OT_Auto_Update,
    SimpleBake_OT_Rollback_Update
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
                
