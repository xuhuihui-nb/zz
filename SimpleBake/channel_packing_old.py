from .utils import get_sb_prefs
import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

from pathlib import Path
import tempfile
import shutil
import os
import numpy as np
import sys

from .utils import SBConstants, get_base_folder_patho, blender_default_colorspace
from .messages import print_message
from . import __package__ as base_package


def create_img(context, internal_img_name, path_dir="", path_filename="",
               file_format="OPEN_EXR", exr_codec="ZIP", save=False, mode="3to1", 
               remove_internal=False, **args):
    
    sbp = context.scene.SimpleBake_Props
    
    #Import the compositing scene that we need
    path = os.path.dirname(__file__) + "/resources/channel_packing.blend/Scene/"
    
    if mode == "1to1":
        if "SBCompositing_1to1" in bpy.data.scenes:
            bpy.data.scenes.remove(bpy.data.scenes["SBCompositing_1to1"])
        bpy.ops.wm.append(filename="SBCompositing_1to1", directory=path)
        
        scene = bpy.data.scenes["SBCompositing_1to1"]

        if bpy.app.version >= (5, 0, 0):
            node_tree = scene.compositing_node_group
            nodes = scene.compositing_node_group.nodes
        else:
            node_tree = scene.node_tree
            nodes = node_tree.nodes

        
        #Set the input
        nodes["input_img"].image = args["input_img"]
        
        #The inverts all start muted
        if "invert_r_input" in args and args["invert_r_input"]: nodes["invert_r_input"].mute = False
        if "invert_g_input" in args and args["invert_g_input"]: nodes["invert_g_input"].mute = False
        if "invert_b_input" in args and args["invert_b_input"]: nodes["invert_b_input"].mute = False
        if "invert_a_input" in args and args["invert_a_input"]: nodes["invert_a_input"].mute = False
        
        if "invert_combined" in args and args["invert_combined"]: nodes["invert_combined"].mute=False
        
    
    if mode == "3to1":
        if "SBCompositing_3to1" in bpy.data.scenes:
            bpy.data.scenes.remove(bpy.data.scenes["SBCompositing_3to1"])
        bpy.ops.wm.append(filename="SBCompositing_3to1", directory=path)
        
        scene = bpy.data.scenes["SBCompositing_3to1"]

        if bpy.app.version >= (5, 0, 0):
            node_tree = scene.compositing_node_group
            nodes = scene.compositing_node_group.nodes
        else:
            node_tree = scene.node_tree
            nodes = node_tree.nodes
        
        #Set the inputs
        if ("input_r" in args) and args["input_r"]!=None:
            nodes["input_r"].image = args["input_r"]
            input_r_orig_colspace = args["input_r"].colorspace_settings.name
            if file_format == "PNG":
                args["input_r"].colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=True)[1]

        if ("input_g" in args) and args["input_g"]!=None:
            nodes["input_g"].image = args["input_g"]
            input_g_orig_colspace = args["input_g"].colorspace_settings.name
            if file_format == "PNG":
                args["input_g"].colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=True)[1]
            
        if ("input_b" in args) and args["input_b"]!=None:
            nodes["input_b"].image = args["input_b"]
            input_b_orig_colspace = args["input_b"].colorspace_settings.name
            if file_format == "PNG":
                args["input_b"].colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=True)[1]
        
        if ("input_a" in args) and args["input_a"]!=None:
            nodes["input_a"].image = args["input_a"]
            input_a_orig_colspace = args["input_a"].colorspace_settings.name
            if file_format == "PNG":
                args["input_a"].colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=True)[1]
        
        #Clear the alpha connection unless we have an alpha texture
        if (not "input_a" in args) or args["input_a"]==None: node_tree.links.remove(nodes["Combine RGBA"].inputs[3].links[0])
        
        #Alpha Premul
        if "alpha_convert" in args and args["alpha_convert"] == "straight":
            nodes["alpha_convert"].mute = False
            if bpy.app.version >= (5, 0, 0):
                nodes["alpha_convert"].inputs[1].default_value = "To Straight"
            else:
                nodes["alpha_convert"].mapping = "PREMUL_TO_STRAIGHT"

        elif "alpha_convert" in args and args["alpha_convert"] == "premul":
            nodes["alpha_convert"].mute = False
            if bpy.app.version >= (5, 0, 0):
                nodes["alpha_convert"].inputs[1].default_value = "To Premultiplied"
            else:
                nodes["alpha_convert"].mapping = "STRAIGHT_TO_PREMUL"
        else:
            #Leave it muted
            pass
            
        
        #The inverts all start muted
        if "invert_r_input_r" in args and args["invert_r_input_r"]: nodes["invert_r_input_r"].mute = False
        if "invert_r_input_g" in args and args["invert_r_input_g"]: nodes["invert_r_input_g"].mute = False
        if "invert_r_input_b" in args and args["invert_r_input_b"]: nodes["invert_r_input_b"].mute = False
        if "invert_r_input_a" in args and args["invert_r_input_a"]: nodes["invert_r_input_a"].mute = False
        
        if "invert_g_input_r" in args and args["invert_g_input_r"]: nodes["invert_g_input_r"].mute = False
        if "invert_g_input_g" in args and args["invert_g_input_g"]: nodes["invert_g_input_g"].mute = False
        if "invert_g_input_b" in args and args["invert_g_input_b"]: nodes["invert_g_input_b"].mute = False
        if "invert_g_input_a" in args and args["invert_g_input_a"]: nodes["invert_g_input_a"].mute = False
        
        if "invert_b_input_r" in args and args["invert_b_input_r"]: nodes["invert_b_input_r"].mute = False
        if "invert_b_input_g" in args and args["invert_b_input_g"]: nodes["invert_b_input_g"].mute = False
        if "invert_b_input_b" in args and args["invert_b_input_b"]: nodes["invert_b_input_b"].mute = False
        if "invert_b_input_a" in args and args["invert_b_input_a"]: nodes["invert_b_input_a"].mute = False
        
        if "invert_a_input_r" in args and args["invert_a_input_r"]: nodes["invert_a_input_r"].mute = False
        if "invert_a_input_g" in args and args["invert_a_input_g"]: nodes["invert_a_input_g"].mute = False
        if "invert_a_input_b" in args and args["invert_a_input_b"]: nodes["invert_a_input_b"].mute = False
        if "invert_a_input_a" in args and args["invert_a_input_a"]: nodes["invert_a_input_a"].mute = False
        
        #Isolate the input channels
        if "isolate_input_r" in args and args["isolate_input_r"]:
            node_tree.links.remove(nodes["Combine RGBA.002"].inputs[1].links[0])
            node_tree.links.remove(nodes["Combine RGBA.002"].inputs[2].links[0])
            node_tree.links.remove(nodes["Combine RGBA.002"].inputs[3].links[0])
            nodes["Combine RGBA.002"].mute=True
        if "isolate_input_g" in args and args["isolate_input_g"]:
            node_tree.links.remove(nodes["Combine RGBA.003"].inputs[0].links[0])
            node_tree.links.remove(nodes["Combine RGBA.003"].inputs[2].links[0])
            node_tree.links.remove(nodes["Combine RGBA.003"].inputs[3].links[0])
            nodes["Combine RGBA.003"].mute=True
        if "isolate_input_b" in args and args["isolate_input_b"]:
            node_tree.links.remove(nodes["Combine RGBA.004"].inputs[0].links[0])
            node_tree.links.remove(nodes["Combine RGBA.004"].inputs[1].links[0])
            node_tree.links.remove(nodes["Combine RGBA.004"].inputs[3].links[0])
            nodes["Combine RGBA.004"].mute=True
    
    
    #-----------------------------------------------------------------------------
    
    #Disable the BW nodes
    if "mute_bws" in args and args["mute_bws"]:
        bw_nodes = [node for node in nodes if node.bl_idname == "CompositorNodeRGBToBW"]
        for node in bw_nodes:
            node.mute=True
        
    #Set the output resolution of the scene to the texture size we are using
    scene.render.resolution_y = sbp.outputheight
    scene.render.resolution_x = sbp.outputwidth
    
    #Render to temp file for the internal image
    tmpdir = Path(tempfile.mkdtemp())
    scene.render.filepath = str(tmpdir / path_filename)
    #Let's always do this an EXR (lossless compression)
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.exr_codec = "ZIP"
    bpy.ops.render.render(animation=False, write_still=True, use_viewport=False, scene=scene.name)

    #Reload the temp file into an internal image again
    img = bpy.data.images.load(str(tmpdir / path_filename)+"."+"exr")

    #Make sure that image is non-color (or equiv) for now
    #ACES
    try:
        img.colorspace_settings.name = blender_default_colorspace(float_buffer=False, col=True)[1]
    except:
        img.colorspace_settings.name = "role_data"


    #Pack image, so we don't lose it when we delete the temp file
    img.pack()

    #Rename internal image
    img.name = internal_img_name

    #Delete the external tmp file
    shutil.rmtree(str(tmpdir))    

    if save:
        #Render to output file, if we are saving extnerally
        scene.render.filepath = str(path_dir / path_filename)
        
        #Set file format to requested
        scene.render.image_settings.file_format = file_format
        
        #Compression and adjust other settings
        scene.render.image_settings.color_mode = "RGBA"
        
        #Always use the max bit depth that we can
        if file_format == "OPEN_EXR":
            scene.render.image_settings.color_depth = "32"
            scene.render.image_settings.exr_codec = exr_codec
            
        elif file_format != "TARGA": #Tga cannot be 16bit. But PNG can.
            scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.compression = 0
        
        #Save
        bpy.ops.render.render(animation=False, write_still=True, use_viewport=False, scene=scene.name)


    if mode == "3to1":
        #Restore original image colour spaces
        if "input_r" in args and args["input_r"] != None: args["input_r"].colorspace_settings.name = input_r_orig_colspace
        if "input_g" in args and args["input_g"] != None: args["input_g"].colorspace_settings.name = input_g_orig_colspace
        if "input_b" in args and args["input_b"] != None: args["input_b"].colorspace_settings.name = input_b_orig_colspace
        if "input_a" in args and args["input_a"] != None: args["input_a"].colorspace_settings.name = input_a_orig_colspace
        
    #Delete the new scene
    bpy.data.scenes.remove(scene)
    
    if remove_internal:
    #Remove the internal image
        bpy.data.images.remove(img)
    
    
    return True
    

class SimpleBake_OT_Channel_Packing_Old(Operator):
    """Perform channel packing"""
    bl_idname = "simplebake.channel_packing_old"
    bl_label = "Pack (Old Method)"
    
    bake_operation_id: StringProperty()
    pbrtarget_only: BoolProperty(default=False)
    in_background: BoolProperty(default=False)
    global_mode: StringProperty()
    target_obj_name_override: StringProperty(default="")
    
    def find_images(self, context, selection, objname):

        if selection == "none":
            return None
        else:
            img = ([i for i in bpy.data.images if 
                        "SB_this_bake" in i and i["SB_this_bake"] == selection and
                        "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id and
                        "SB_bake_object" in i and i["SB_bake_object"] == objname])
            assert(len(img)==1), f"Found {len(img)} images, should have been 1"
            img = img[0]
            return img
    
    def find_images_merged(self, context, selection):
        if selection == "none":
            return None
        else:
            img = ([i for i in bpy.data.images if 
                        "SB_this_bake" in i and i["SB_this_bake"] == selection and
                        "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id])
            assert(len(img)==1), f"Found {len(img)} images, should have been 1"
            img = img[0]
            return img
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        #Grab what we need from panel
        self.merged_bake = sbp.merged_bake
        self.merged_bake_name = sbp.merged_bake_name
        self.export_folder_per_object = sbp.export_folder_per_object
        self.batch_name = sbp.batch_name
        self.in_background = True if "--background" in sys.argv or sbp.fake_background else False

        
        #Just in case
        if len(sbp.cp_list) == 0:
            print_message(context, "No channel packing")
            return {'FINISHED'}
        
        #print_message(context, "Creating channel packed images")
        
        #Objects
        #if self.target_obj_name_override != "":
            #objects = [context.scene.objects[self.target_obj_name_override]]
        if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            from .bake_operators.auto_match_operators import SimpleBake_OT_AutoMatch_Operation as amo
            objects = [context.scene.objects[i] for i in list(amo.hl_matches.keys())]
        elif (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="decals":
            objects = [sbp.targetobj]
        elif self.pbrtarget_only: objects =[sbp.targetobj]
        else: objects = [i.obj_point for i in sbp.objects_list]
        
        #Figure out the save folder for each object
        efpo = self.export_folder_per_object
        mb = self.merged_bake
        mbn = self.merged_bake_name
        obj_savefolders = {}
        
        if self.in_background:
            p = sbp.export_path.replace("//", "")
            base_save_folder = Path(sbp.base_folder_override) / p
        else:
            base_save_folder = Path(bpy.path.abspath(sbp.export_path))
        
        
        for obj in objects:
            if efpo and mb:
                savefolder = base_save_folder / mbn
                obj_savefolders[obj.name] = savefolder #Every object gets the same based on merged bake name
            elif efpo:
                savefolder = base_save_folder / obj.name
                obj_savefolders[obj.name] = savefolder
            else:
                savefolder = base_save_folder
                obj_savefolders[obj.name] = savefolder
        
        #Create each of the CPTs
        cp_list = sbp.cp_list
        for obj in objects:
            
            #Hacky
            if not mb: t_name = obj.name
            else: t_name = mbn 
            
            
            for cpt in cp_list:
                file_format = cpt.file_format
                cpt_name = cpt.name
                
                print_message(context, f"Creating packed texture \"{cpt_name}\" for object \"{t_name}\" with format {file_format}")
                
                r_selection = cpt.R
                g_selection = cpt.G
                b_selection = cpt.B
                a_selection = cpt.A
                
                if not self.merged_bake:
                    r_img = self.find_images(context, r_selection, obj.name)
                    g_img = self.find_images(context, g_selection, obj.name)
                    b_img = self.find_images(context, b_selection, obj.name)
                    a_img = self.find_images(context, a_selection, obj.name)
                else:
                    r_img = self.find_images_merged(context, r_selection)
                    g_img = self.find_images_merged(context, g_selection)
                    b_img = self.find_images_merged(context, b_selection)
                    a_img = self.find_images_merged(context, a_selection)
                
                #--Create the texture--
                prefs = get_sb_prefs(context)

                #Determine the name
                proposed_name = prefs.img_name_format
                proposed_name = proposed_name.replace("%OBJ%", t_name)
                proposed_name = proposed_name.replace("%BAKEMODE%", self.global_mode)
                proposed_name = proposed_name.replace("%BAKETYPE%", cpt.name)
                proposed_name = proposed_name.replace("%BATCH%", self.batch_name)
                imgname = proposed_name


                #Determine transparency mode
                if file_format == "PNG" or file_format == "TARGA":
                    alpha_convert = "premul"

                else:
                    alpha_convert = False


                # #Isolate
                # if r_selection == SBConstants.PBR_DIFFUSE and g_selection == SBConstants.PBR_DIFFUSE and b_selection == SBConstants.PBR_DIFFUSE:
                #     isolate_input_r=True
                #     isolate_input_g=True
                #     isolate_input_b=True
                # elif r_selection == SBConstants.PBR_SSSCOL and g_selection == SBConstants.PBR_SSSCOL and b_selection == SBConstants.PBR_SSSCOL:
                #     isolate_input_r=True
                #     isolate_input_g=True
                #     isolate_input_b=True
                # elif r_selection == SBConstants.PBR_EMISSION and g_selection == SBConstants.PBR_EMISSION and b_selection == SBConstants.PBR_EMISSION:
                #     isolate_input_r=True
                #     isolate_input_g=True
                #     isolate_input_b=True

                if r_selection == g_selection == b_selection:
                    isolate_input_r=True
                    isolate_input_g=True
                    isolate_input_b=True
                else:
                    isolate_input_r=False
                    isolate_input_g=False
                    isolate_input_b=False

                create_img(context, imgname, input_r=r_img, input_g=g_img, input_b=b_img,
                    input_a=a_img, save=True, mode="3to1", path_dir=obj_savefolders[obj.name],
                    path_filename=Path(imgname), file_format=file_format, exr_codec=cpt.exr_codec, alpha_convert=alpha_convert,
                    isolate_input_r=isolate_input_r, isolate_input_g=isolate_input_g, isolate_input_b=isolate_input_b,
                    remove_internal=True)


                #END OLD CODE

                if sbp.del_cptex_components:

                    del_list = []

                    if r_img != None:
                        if r_img.name in bpy.data.images:
                            print_message(context, f"Deleting {r_img.name} from local file system")
                            filepath = bpy.path.abspath(r_img.filepath)
                            del_list.append(r_img.name)
                            if os.path.isfile(filepath):
                                os.remove(filepath)

                    if g_img != None:
                        if g_img.name in bpy.data.images:
                            print_message(context, f"Deleting {g_img.name} from local file system")
                            filepath = bpy.path.abspath(g_img.filepath)
                            del_list.append(g_img.name)
                            if os.path.isfile(filepath):
                                os.remove(filepath)

                    if b_img != None:
                        if b_img.name in bpy.data.images:
                            print_message(context, f"Deleting {b_img.name} from local file system")
                            filepath = bpy.path.abspath(b_img.filepath)
                            del_list.append(b_img.name)
                            if os.path.isfile(filepath):
                                os.remove(filepath)

                    if a_img != None:
                        if a_img.name in bpy.data.images:
                            print_message(context, f"Deleting {a_img.name} from local file system")
                            filepath = bpy.path.abspath(a_img.filepath)
                            del_list.append(a_img.name)
                            if os.path.isfile(filepath):
                                os.remove(filepath)

                    for iname in del_list:
                        if iname in bpy.data.images:
                            bpy.data.images.remove(bpy.data.images[iname])


                
            #Hacky - If this is a mergedbake, break out of the object loop
            if sbp.merged_bake:
                break
            
        
        return {'FINISHED'}

    

classes = ([
    SimpleBake_OT_Channel_Packing_Old
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
