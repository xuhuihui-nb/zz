from .utils import get_sb_prefs
import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.props import BoolProperty, StringProperty, IntProperty

import uuid
import numpy as np
import os

from .utils import SBConstants, get_udim_tiles, get_cached_udim_tiles, get_bake_objects, blender_default_colorspace
from .messages import print_message
from .background_and_progress import BakeInProgress as Bip
from .aov import get_aov_colspace, get_aov_type, get_aov_name
from . import __package__ as base_package

def gen_image_name(context, name, globalmode, baketype, mat_name=""):
    sbp = context.scene.SimpleBake_Props
    prefs = get_sb_prefs(context)
    proposed_name = prefs.img_name_format

    if SBConstants.PBRAOVS in baketype:
        baketype = get_aov_name(context, baketype)

    filepath = bpy.data.filepath
    if filepath:
        filename_no_ext = os.path.splitext(os.path.basename(filepath))[0]
    else:
        filename_no_ext = ""


    if Bip.Sequence.active:
        if "%FRAME%" not in proposed_name:
            proposed_name = f"{proposed_name}.%FRAME%"
        proposed_name = proposed_name.replace("%FRAME%", f"{context.scene.frame_current:04d}")
    else:
        proposed_name = proposed_name.replace(".%FRAME%", "")
        proposed_name = proposed_name.replace("%FRAME%", "")

    proposed_name = proposed_name.replace("%OBJ%", name)
    proposed_name = proposed_name.replace("%BAKEMODE%", globalmode)
    proposed_name = proposed_name.replace("%BAKETYPE%", baketype)
    proposed_name = proposed_name.replace("%BATCH%", sbp.batch_name)
    proposed_name = proposed_name.replace("%BLEND_FILE_NAME%", filename_no_ext)
    res = f"{sbp.outputwidth}x{sbp.outputheight}"
    if prefs.abbr_res and sbp.outputwidth % 1024 == 0 and sbp.outputheight % 1024 == 0:
        res = f"{int(sbp.outputwidth / 1024)}K"
    proposed_name = proposed_name.replace("%RESOLUTION%", res)

    if mat_name:
        if "%MAT%" in proposed_name:
            proposed_name = proposed_name.replace("%MAT%", mat_name)
        else:
            proposed_name = f"{proposed_name}_{mat_name}"
    else:
        proposed_name = proposed_name.replace("%MAT%", "")

    return proposed_name


class SimpleBake_OT_Bake_Image(Operator):
    """Generate image to be baked to if needed"""
    bl_idname = "simplebake.bake_image"
    bl_description = "Generates image to be baked to if needed"
    bl_label = "GenImage"
    
    need_first_time_settings = []


    bake_operation_id: StringProperty()
    this_bake: StringProperty()
    target_object_name: StringProperty()
    global_mode: StringProperty()
    bake_mode: StringProperty()


    
    def create_individual_bake_image(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "Getting individual baked image")
        
        prefs = get_sb_prefs(context)

        alias_dict = prefs.get_alias_dict()
        if self.this_bake in alias_dict: this_bake = alias_dict[self.this_bake]
        else: this_bake = self.this_bake

        proposed_name = gen_image_name(context, self.target_object_name, self.global_mode, this_bake)

        need_new = False
        if proposed_name in bpy.data.images and not self.clear_image:
            #It's there, and we aren't going to clear it

            #No action for now
            i = bpy.data.images[proposed_name]
            self.created_images.append(i)
            self.set_image_tags(i)
            need_new = False

        elif proposed_name in bpy.data.images:
            #It's there, but we want to clear it
            bpy.data.images.remove(bpy.data.images[proposed_name])
            need_new = True

        else:
            #It's not there
            need_new = True
        
        if need_new:
            #Actually Create the image
            tiled = True if (self.total_tiles > 1 and sbp.auto_detect_udims) else False
            ua = sbp.texture_bg_col[3] < 1.0
            i = bpy.data.images.new(proposed_name, self.img_width, self.img_height, alpha=ua, float_buffer=self.float_buffer, tiled=tiled)


            self.created_images.append(i)
            self.set_image_tags(i)
            self.need_first_time_settings.append(i)
        else:
            #self.need_first_time_settings = False
            pass
        
    
    def create_merged_bake_image(self, context):
        sbp = context.scene.SimpleBake_Props
        print_message(context, "Getting merged bake image")
        
        prefs = get_sb_prefs(context)

        alias_dict = prefs.get_alias_dict()
        if self.this_bake in alias_dict: this_bake = alias_dict[self.this_bake]
        else: this_bake = self.this_bake

        proposed_name = gen_image_name(context, self.merged_bake_name, self.global_mode, this_bake)

        need_new = False
        
        if proposed_name not in bpy.data.images:
            need_new = True
        else:
            i = bpy.data.images[proposed_name]
            if "SB_bake_operation_id" in i and i["SB_bake_operation_id"] != self.bake_operation_id:
                #It's there, but different bake ID
                if self.clear_image:
                    bpy.data.images.remove(i)
                    need_new = True
                else:
                    #Essentially do nothing
                    pass

            elif "SB_bake_operation_id" not in i:
                 #It's there, but it doesn't even have an ID. This will be a weird coincidence
                if self.clear_image:
                    bpy.data.images.remove(i)
                    need_new = True
                else:
                    #Essentially do nothing
                    pass

            elif "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id:
                #It's there, and it's our bake
                need_new = False
                
        if need_new:
            tiled = True if (self.total_tiles > 1 and sbp.auto_detect_udims) else False
            ua = sbp.texture_bg_col[3] < 1.0
            i = bpy.data.images.new(proposed_name, self.img_width, self.img_height, alpha=ua, float_buffer=self.float_buffer, tiled=tiled)

            #Create all the tiles
            # if tiled:
            #     for t in self.active_tiles:
            #         i.tiles.new(t)

            self.created_images.append(i)
            self.set_image_tags(i)
            self.need_first_time_settings.append(i)

        else:
            #Just using existing image, pretend we created it
            #i is created up on line 113
            self.created_images.append(i)
            self.set_image_tags(i)


    
    def create_per_mat_bake_image(self, context):
        """Create one bake image per enabled material for tex_per_mat mode."""
        sbp = context.scene.SimpleBake_Props
        prefs = get_sb_prefs(context)

        alias_dict = prefs.get_alias_dict()
        this_bake = alias_dict.get(self.this_bake, self.this_bake)

        # Get enabled materials for this object from mat_bake_list
        all_entries = [e for e in sbp.mat_bake_list if e.obj_name == self.target_object_name]
        enabled_mats = [e.mat_name for e in all_entries if e.enabled]

        # If the object has no mat_bake_list entries at all (e.g. it's an S2A target object),
        # fall back to standard single-image creation.
        # If it has entries but all are disabled, skip image creation entirely.
        if not all_entries:
            self.create_individual_bake_image(context)
            return
        if not enabled_mats:
            return

        for mat_name in enabled_mats:
            proposed_name = gen_image_name(
                context, self.target_object_name, self.global_mode, this_bake,
                mat_name=mat_name
            )

            need_new = False
            if proposed_name in bpy.data.images and not self.clear_image:
                i = bpy.data.images[proposed_name]
                self.created_images.append(i)
                self.set_image_tags(i, mat_name=mat_name)
                need_new = False
            elif proposed_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[proposed_name])
                need_new = True
            else:
                need_new = True

            if need_new:
                tiled = True if (self.total_tiles > 1 and sbp.auto_detect_udims) else False
                ua = sbp.texture_bg_col[3] < 1.0
                i = bpy.data.images.new(
                    proposed_name, self.img_width, self.img_height,
                    alpha=ua, float_buffer=self.float_buffer, tiled=tiled
                )
                self.created_images.append(i)
                self.set_image_tags(i, mat_name=mat_name)
                self.need_first_time_settings.append(i)

    def set_image_tags(self, i, mat_name=""):
        i["SB_bake_object"] = self.target_object_name
        i["SB_global_mode"] = self.global_mode
        i["SB_this_bake"] = self.this_bake
        i["SB_merged_bake"] = self.merged_bake
        i["SB_merged_bake_name"] = self.merged_bake_name
        i["SB_bake_operation_id"] = self.bake_operation_id
        i["SB_float_buffer"] = self.float_buffer
        i["SB_scaled"] = False
        i["SB_exported_list"] = []
        i["SB_denoised"] = False
        i["SB_aa"] = False
        if mat_name:
            i["SB_bake_material"] = mat_name
    

    def set_image_settings(self, context, imgs):

        sbp = context.scene.SimpleBake_Props

        for i in imgs:
            print_message(context, f"Adjusting settings on new image {i.name}")

            if self.this_bake == SBConstants.PBR_NORMAL:
                gc = (0.5,0.5,1.0,1.0) #Normal ignores the use alpha option
            elif self.this_bake == "NORMAL": #CyclesBake normal
                gc = (0.5,0.5,1.0,1.0) #Normal ignores the use alpha option
            #elif self.use_alpha:
                #gc = (0.0,0.0,0.0,0.0)
            else:
                gc = sbp.texture_bg_col

            i.generated_color = gc
            #If this is a tiled image, let's go for all the tiles too
            #if len(i.tiles) > 1: #Even an untiled image has tile length of 1

            if i.source == 'TILED':
                area = context.screen.areas[0]

                old_type = area.type
                area.type = "IMAGE_EDITOR"
                area.spaces[0].image = i
                with context.temp_override(area=area):

                    for t in self.active_tiles:
                        if t==1001:
                            continue
                        print(f"Going to add tile {t}")
                        ua = sbp.texture_bg_col[3] < 1.0
                        bpy.ops.image.tile_add(number=t, count=1, label="", fill=True, color=gc, generated_type='BLANK', width=self.img_width, height=self.img_height, float=self.float_buffer, alpha=ua)


                area.type = old_type

                print(f"Len tiles now {len(i.tiles)}")


            prefs = get_sb_prefs(context)
            cs_dict = prefs.get_cs_dict()
            

            if self.this_bake in cs_dict:
                cs = cs_dict[self.this_bake]
            elif self.global_mode in [SBConstants.CYCLESBAKE,SBConstants.CYCLESBAKE_S2A] and context.scene.cycles.bake_type != "NORMAL":
                cs = sbp.cyclesbake_cs
            elif SBConstants.PBRAOVS in self.this_bake:
                print(f"AOV DETECTED BASED ON {self.this_bake}")
                cs = get_aov_colspace(context, self.this_bake)
            else:
                cs = blender_default_colorspace(float_buffer=False, col=True)[1]

            i.colorspace_settings.name = cs
            print_message(context, f"Image colour space set to {cs}")

            i.use_fake_user = True


    
    def execute(self, context):


        sbp = context.scene.SimpleBake_Props
        self.merged_bake = sbp.merged_bake
        self.total_tiles = 0
        self.active_tiles = []

        if sbp.auto_detect_udims:
            if not self.merged_bake:
                #Nice and simple
                r = get_cached_udim_tiles(context, self.target_object_name)
                self.total_tiles = r["total_tiles"]
                self.active_tiles = r["active_tiles"]
                print_message(context, f"Object {self.target_object_name} has maximum UDIM tile {self.total_tiles}")
                print_message(context, f"Object {self.target_object_name} has active UDIM tiles {self.active_tiles}")
            else:
                #Way more complicated
                self.active_tiles = set()
                self.total_tiles = 0
                objects = get_bake_objects(context)
                for o_name in objects:
                    if not (o:=context.scene.objects.get(o_name)):
                        continue
                    r = get_cached_udim_tiles(context, o.name)
                    these_active_tiles = r["active_tiles"]
                    self.active_tiles.update(these_active_tiles)

                    this_total_tiles = r["total_tiles"]
                    self.total_tiles = this_total_tiles if this_total_tiles > self.total_tiles else self.total_tiles
                self.active_tiles = list(self.active_tiles)

                print_message(context, f"Merged bake with maximum UDIM tile {self.total_tiles}")
                print_message(context, f"Merged bake with active UDIM tiles {self.active_tiles}")



        #Grab what we need from the panel
        self.merged_bake_name = sbp.merged_bake_name
        #self.use_alpha = sbp.use_alpha
        self.img_height = sbp.imgheight
        self.img_width = sbp.imgwidth
        self.clear_image = sbp.clear_image
        self.float_buffer = True if (self.bake_mode == SBConstants.PBR_NORMAL and not sbp.no_force_32bit_normals) or sbp.everything32bitfloat else False

        self.need_first_time_settings = []
        self.created_images = []


        if self.merged_bake:
            self.create_merged_bake_image(context)
        elif sbp.tex_per_mat:
            self.create_per_mat_bake_image(context)
        else:
            self.create_individual_bake_image(context)
            
            
        #We had to create a new image
        if self.created_images != []:
            #Set image settings for images that are freshly created
            self.set_image_settings(context, self.need_first_time_settings)
        
        else:
            print_message(context, "Using existing image")
        
        return {'FINISHED'}
    


classes = ([
        SimpleBake_OT_Bake_Image
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
