import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.props import StringProperty, BoolProperty, IntProperty

from pathlib import Path
import os
import sys
import re

from .utils import SBConstants, get_base_folder_patho, select_only_this, select_only_these, get_texture_channels, blender_default_colorspace
from .messages import print_message
from .background_and_progress import BakeInProgress as Bip

FILE_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "TIFF": "tiff", "TARGA": "tga","TARGA_RAW": "tga", "OPEN_EXR": "exr"}

def apply_scene_col_settings(context, scene):
    scene.display_settings.display_device = context.scene.display_settings.display_device
    scene.view_settings.view_transform = context.scene.view_settings.view_transform
    scene.view_settings.look = context.scene.view_settings.look
    scene.view_settings.exposure = context.scene.view_settings.exposure
    scene.view_settings.gamma = context.scene.view_settings.gamma
    scene.sequencer_colorspace_settings.name = context.scene.sequencer_colorspace_settings.name
    return True


class SimpleBake_OT_Save_Images_Externally(Operator):
    """Saved baked images externally"""
    bl_idname = "simplebake.save_images_externally"
    bl_description = "Save baked images externally"
    bl_label = "Save"

    bake_operation_id: StringProperty()
    bake_mode: StringProperty()
    lightmap_apply_colman: BoolProperty(default=False)
    
    def execute(self, context):
        
        sbp = context.scene.SimpleBake_Props

        #Set what we need from the panel
        self.file_format = sbp.export_file_format
        self.folder_per_object = sbp.export_folder_per_object
        self.apply_col_man_to_col = sbp.apply_col_man_to_col
        self.merged_bake = sbp.merged_bake
        self.merged_bake_name = sbp.merged_bake_name
        self.export_cycles_col_space = sbp.export_cycles_col_space
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False
        
        
        #Get all the images we want to save externally
        imgs = ([img for img in bpy.data.images 
                 if "SB_bake_operation_id" in img and
                 img["SB_bake_operation_id"] == self.bake_operation_id and
                 "SB_this_bake" in img and img["SB_this_bake"] == self.bake_mode
                 ])
        

        #Remove any already exported
        for img in list(imgs):
            exported_list = list(img["SB_exported_list"])
            if self.bake_operation_id in exported_list:
                print_message(context, f"{img.name} has already been exported")
                imgs.remove(img)

        #Exit here if there aren't any
        if len(imgs) == 0:
            print_message(context, f"No images to export, exiting")
            return {'FINISHED'}


         
        #Find the save location for each image
        save_locations = {}
        
        if self.in_background:
            p = sbp.export_path.replace("//", "")
            base_save_folder = Path(sbp.base_folder_override) / p
        else:
            base_save_folder = Path(bpy.path.abspath(sbp.export_path))
        
        print_message(context, f"Saving baked images to {str(base_save_folder)}")
        
        if not self.folder_per_object:#Not folder per object
            for img in imgs:
                save_locations[img.name] = base_save_folder #All the same
        else: #Folder per object
            if self.merged_bake:
                for img in imgs:
                    save_locations[img.name] = base_save_folder / self.merged_bake_name #All the same
            else:
                for img in imgs:
                    obj_name = img["SB_bake_object"]
                    if img.get("SB_bake_material"):
                        save_locations[img.name] = base_save_folder / obj_name / img["SB_bake_material"]
                    else:
                        save_locations[img.name] = base_save_folder / obj_name
            
        #Create the base save folder if it doesn't already exist
        if not os.path.isdir(str(base_save_folder)):
            os.makedirs(str(base_save_folder))
        
        #We want a scene so we can control bit depth etc.
        s = bpy.data.scenes.new("SB_Export_Temp")
        s.render.image_settings.file_format = self.file_format
        
        #Do we want to apply colour management from current scene?
        #CyclesBake
        s.view_settings.view_transform = "Standard" #default

        if sbp.global_mode == "CyclesBake":
            if self.export_cycles_col_space and self.bake_mode != "NORMAL":
                print_message(context, "Applying scene col management settings CyclesBake")
                apply_scene_col_settings(context, s)
            else:
                print_message(context, f"No col management settings for {self.bake_mode}")

        #PBR
        else:
            if self.apply_col_man_to_col and self.bake_mode == SBConstants.PBR_DIFFUSE:
                print_message(context, "Applying scene col management settings to PBR Diffuse")
                apply_scene_col_settings(context, s)
            else:
                print_message(context, f"No col management settings for {self.bake_mode}")

        #Either
        if self.lightmap_apply_colman and self.bake_mode == SBConstants.LIGHTMAP:
            print_message(context, "Applying scene col management settings lightmap")
            apply_scene_col_settings(context, s)



        #Bit depth
        if self.file_format in ["JPEG", "TARGA", "TARGA_RAW"]:
            pass # Skip this entirely
        elif (sbp.everything_16bit or
            self.bake_mode == SBConstants.PBR_NORMAL and not sbp.no_force_32bit_normals or
            self.bake_mode == "NORMAL" and not sbp.no_force_32bit_normals):
                s.render.image_settings.color_depth = "16"
        elif self.file_format == "OPEN_EXR":
            s.render.image_settings.color_depth = "32"
        else:
            s.render.image_settings.color_depth = "8"
        
        #Channels
        if self.file_format == "JPEG":
            s.render.image_settings.color_mode = get_texture_channels(context, self.bake_mode)
        else:
            ua = sbp.texture_bg_col[3] < 1.0
            if ua: s.render.image_settings.color_mode = "RGBA"
            else: s.render.image_settings.color_mode = get_texture_channels(context, self.bake_mode)

        print_message(context, f"Chosen {s.render.image_settings.color_mode} for {self.bake_mode}")

        #Extras
        if self.file_format == "JPEG":
            s.render.image_settings.quality =  sbp.jpeg_quality
        if self.file_format == "OPEN_EXR":
            s.render.image_settings.exr_codec = sbp.exr_codec_export

        #Save to disk
        for img in imgs:
            save_folder = save_locations[img.name]
            #Create the folder in the file system if it's not there already
            if not os.path.isdir(str(save_folder)):
                os.mkdir(str(save_folder))

            ext = FILE_EXTENSIONS[self.file_format]

            #Some housekeeping to do if we are going to save a UDIM image
            udim_marker = "<UDIM>." if len(img.tiles)>1 else ""
            if len(img.tiles)>1:
                pattern = re.compile(rf"^{re.escape(img.name)}\.(\d{{4,}})\.{re.escape(ext)}$")
                for file in save_folder.iterdir():
                    if file.is_file() and pattern.match(file.name):
                        print(f"Deleting: {file}")  # optional
                        file.unlink()


            save_path = save_folder / (img.name + "." + udim_marker + ext)
            print_message(context, f"Save path: {str(save_path)}")
            
            #Save image
            #Let's try this
            img.save_render(str(save_path).encode('utf-8').decode('utf-8'), scene=s)
            
            #Store full path. We may need it later on. About to update to relative path
            full_save_path = str(save_path)
            img["SB_full_save_path"] = full_save_path

            #Store the bit depth and channels too as this is oddly hard to get back later
            img["SB_bit_depth"] = s.render.image_settings.color_depth
            img["SB_channels"] = s.render.image_settings.color_mode
            img["SB_view_transform"] = s.view_settings.view_transform
            img["SB_exr_codec"] = s.render.image_settings.exr_codec
            
            #Some changes needed for UDIM images
            img.source = "TILED" if len(img.tiles)>1 else "FILE"

            #TRY TO covnert to relative path. Even if in the background, as the append op will fix this
            try:
                img.filepath = bpy.path.relpath(full_save_path)
            except ValueError:
                print_message(context, "Converting to relative path failed - probably different drive on Windows")
                img.filepath = full_save_path

            
            try:
                img.unpack(method="REMOVE")
            except:
                pass
            
            #Colour space settings for (what is now) external image
            if self.file_format == "OPEN_EXR":
                #Get default for non-col (for OpenEXR)
                img.colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=False)[1]

            elif "SB_denoised" in img and img["SB_denoised"] and(
            sbp.global_mode in [SBConstants.CYCLESBAKE, SBConstants.CYCLESBAKE_S2A]):
                img.colorspace_settings.name = sbp.cyclesbake_cs
            else:
                pass # Keep the defaults from when image was created
           
                
            #Record that we exported this image for this bake job
            exported_list = list(img["SB_exported_list"])
            exported_list.append(self.bake_operation_id)
            img["SB_exported_list"] = exported_list
            
            print_message(context, f"{img.name} saved externally")
            
        #When all done, remove the temp scene
        bpy.data.scenes.remove(s)
        
        return {'FINISHED'}

def create_dir_if_needed(path):
    path = str(path)
    if not os.path.isdir(path):
        os.makedirs(path)

class SimpleBake_OT_Save_Objects_Externally(Operator):
    """Saved baked objects externally"""
    bl_idname = "simplebake.save_objects_externally"
    bl_description = "Save baked objects externally"
    bl_label = "Save"

    bake_operation_id: StringProperty()
    
    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        if not Bip.Sequence.should_run_teardown():
            print_message(context, "No external mesh save - sequence and not last run")
            return {'FINISHED'} #Nope out if this is part of a sequence

        #Set what we need from the panel
        self.apply_mods_on_mesh_export = sbp.apply_mods_on_mesh_export
        self.apply_transformation = sbp.apply_transformation
        self.copy_and_apply = sbp.copy_and_apply
        self.export_folder_per_object = sbp.export_folder_per_object
        self.merged_bake = sbp.merged_bake
        self.merged_bake_name = sbp.merged_bake_name
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False
        self.mesh_mode = sbp.export_mesh_individual_or_combined

        blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        mesh_export_name = sbp.mesh_export_name if sbp.mesh_export_name != "%blend_file_name%" else blend_name

        #Find objects we want to export. Depends what we are actually doing:
        if sbp.apply_bakes_to_original and (sbp.cycles_s2a or sbp.selected_s2a):
            if sbp.cycles_s2a:
                objs = [sbp.targetobj_cycles]
            if sbp.selected_s2a:
                objs = [sbp.targetobj]
        elif sbp.apply_bakes_to_original:
            objs = [i.obj_point for i in sbp.objects_list]
        else:
            objs = ([o for o in context.scene.objects if "SB_copy_and_apply_from" in o and
                    "SB_bake_operation_id" in o and o["SB_bake_operation_id"] == self.bake_operation_id])

        #Maybe merge the objects
        if sbp.merge_export_obj and sbp.export_mesh_individual_or_combined == "combined" and sbp.merged_bake:
            print_message(context, "Merging baked objects within the output mesh file")

            dup_objects_names = []

            for o in objs:
                select_only_this(context, o)
                bpy.ops.object.duplicate_move()
                new_obj = bpy.context.active_object
                dup_objects_names.append(new_obj.name)

            #Join them together
            select_only_these(context, [o:=bpy.data.objects.get(o_name) for o_name in dup_objects_names if o!=None])
            bpy.ops.object.join()

            #Just the one object now
            objs = [context.active_object]

            #Clear all materials except the first one
            o = context.active_object
            i=0
            for slot in o.material_slots:
                if i != 0:
                    slot.material = None
            i+=1


            #Name the mesh
            context.active_object.name = f"{mesh_export_name}_Baked"

            #Keep track of this for later deletion
            merged_mesh_obj_name = context.active_object.name



        #Export
        if self.in_background:
            p = sbp.export_path.replace("//", "")
            base_save_folder = Path(sbp.base_folder_override) / p
        else:
            base_save_folder = Path(bpy.path.abspath(sbp.export_path))
            
        print_message(context, f"Saving exported mesh to {str(base_save_folder)}")
        
        #Create the base save folder if it doesn't already exist
        create_dir_if_needed(base_save_folder)

        if sbp.export_format == "fbx":
            operator = getattr(bpy.ops.export_scene, "fbx")
            extension = ".fbx"
            #preset_path = bpy.utils.preset_paths('operator/export_scene.fbx/')
            use_selection_name = "use_selection"

            myargs = {
            'check_existing': False,
            'use_selection': True,
            'use_mesh_modifiers': self.apply_mods_on_mesh_export,
            'bake_space_transform': self.apply_transformation,
            'path_mode': "STRIP"
            }

        elif sbp.export_format == "obj":
            operator = getattr(bpy.ops.wm, "obj_export")
            extension = ".obj"
            #preset_path = bpy.utils.preset_paths('operator/wm.obj_export/')
            use_selection_name = "export_selected_objects"

            myargs = {
            'check_existing': False,
            'export_selected_objects': True,
            'apply_modifiers': self.apply_mods_on_mesh_export,
            'path_mode': "STRIP"
            }

        elif sbp.export_format == "dae":
            operator = getattr(bpy.ops.wm, "collada_export")
            extension = ".dae"
            #preset_path = bpy.utils.preset_paths('operator/wm.obj_export/')
            use_selection_name = "selected"

            myargs = {
            'check_existing': False,
            'selected': True,
            'apply_modifiers': self.apply_mods_on_mesh_export,
            'use_texture_copies': False
            }

        else:
            operator = getattr(bpy.ops.export_scene, "gltf")
            extension = ".glb"
            preset_path = bpy.utils.preset_paths('operator/export_scene.gltf/')
            use_selection_name = "use_selection"

            myargs = {
            'check_existing': False,
            'use_selection': True,
            'export_apply': self.apply_mods_on_mesh_export
            }
     
        kwargs = None
        #If we are using a preset, gather those settings
        if (preset_name:=sbp.export_mesh_preset_name) not in ["None",""]:
            filepath = sbp.export_mesh_preset_name #Internal name is the path to the preset file

            class Container(object):
                __slots__ = ('__dict__',)

            op = Container()
            file = open(filepath, 'r')

            # storing the values from the preset on the class
            for line in file.readlines()[3::]:
                exec(line, globals(), locals())
            kwargs = op.__dict__


        def do_export(filepath):

            if kwargs:
                print_message(context,f"Using mesh export preset {preset_name}")
                print_message(context, f"Using {sbp.export_format} preset values - {preset_name}")
                kwargs["filepath"] = str(filepath).encode('utf-8').decode('utf-8')
                kwargs[use_selection_name] = True
                operator(**kwargs)
            else:
                print_message(context,f"No mesh export preset. Using default export settings")
                myargs["filepath"] = str(filepath).encode('utf-8').decode('utf-8')
                operator(**myargs)

        #Not merged bake, sub-folder, combined mesh
        if not self.merged_bake and self.export_folder_per_object and self.mesh_mode != 'individual':
            filepath = base_save_folder / (mesh_export_name + extension)
            #Make sure folder definitely exists
            create_dir_if_needed(base_save_folder)
            select_only_these(context, objs)
            do_export(filepath)

        #Folder per object, but not merged bake OR folder per object and merged bake but want individual meshes
        elif self.export_folder_per_object and ((not self.merged_bake) or (self.merged_bake and self.mesh_mode=="individual")):
            for obj in objs:
                if "SB_copy_and_apply_from" in obj:
                    original_name = obj["SB_copy_and_apply_from"]
                else:
                    original_name = obj.name
                filepath = base_save_folder / original_name / (original_name + extension)
                #Make sure folder definitely exists
                create_dir_if_needed(base_save_folder / original_name)
                select_only_this(context, obj)
                do_export(filepath)

        #Folder per object and merged bake. Combined mesh
        elif self.export_folder_per_object and self.merged_bake:
            filepath = base_save_folder / self.merged_bake_name / (mesh_export_name + extension)
            create_dir_if_needed(base_save_folder / self.merged_bake_name)
            select_only_these(context, objs)
            do_export(filepath)


        #Not folder per object, but we still want individual mesh files
        elif self.mesh_mode=="individual":
            for obj in objs:
                if "SB_copy_and_apply_from" in obj:
                    original_name = obj["SB_copy_and_apply_from"]
                else:
                    original_name = obj.name
                filepath = base_save_folder / (original_name + extension)
                #Make sure folder definitely exists
                create_dir_if_needed(base_save_folder)
                select_only_this(context, obj)
                do_export(filepath)

        #Not folder per object (either merged bake or not), but not apply to original objects
        else:
            filepath = base_save_folder / (mesh_export_name + extension)
            create_dir_if_needed(base_save_folder)
            select_only_these(context, objs)
            do_export(filepath)


        #If we didn't actually want copy and apply, remove the objects (unless in background
        #AND UNLESS we are applying bakes to original objects
        if not self.copy_and_apply and not self.in_background and not sbp.apply_bakes_to_original:
            [bpy.data.objects.remove(o) for o in objs]

        #If we merged the objects for export, remove the duplicate file
        if sbp.merge_export_obj and sbp.export_mesh_individual_or_combined == "combined" and sbp.merged_bake:
            if o:=bpy.data.objects.get(merged_mesh_obj_name):
                bpy.data.objects.remove(o)


        
        return {'FINISHED'}


classes = ([
        SimpleBake_OT_Save_Images_Externally,
        SimpleBake_OT_Save_Objects_Externally
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
