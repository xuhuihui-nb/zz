import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty
from bpy.utils import register_class, unregister_class
from bpy.types import Operator

import os, signal
import uuid
import tempfile
import subprocess
import sys
from pathlib import Path

from .utils import show_message_box, force_to_object_mode, SBConstants, pbr_selections_to_list, specials_selection_to_list
#from .messages import print_message

class BakeInProgress:
    is_baking = False
    was_error = False

    class Sequence:
        """State for an image-sequence bake in progress.

        The image_sequence operator is the sole writer of these flags. All
        other modules must consume them via ``should_run_setup`` /
        ``should_run_teardown`` rather than reading the booleans directly,
        so that "first-frame" / "last-frame" / "not-a-sequence" semantics
        stay in one place.
        """

        active = False           # True while a sequence bake is running
        is_first_frame = False   # True during the bake of the first frame
        is_last_frame = False    # True during the bake of the final frame
        total_frames = 0         # Number of frames covered by the sequence

        @classmethod
        def should_run_setup(cls):
            """Per-frame operators that do one-shot setup (master backup,
            material initialise) should only run on the first frame of a
            sequence — or on every bake if we're not in a sequence at all.
            """
            return (not cls.active) or cls.is_first_frame

        @classmethod
        def should_run_teardown(cls):
            """Per-frame operators that do one-shot teardown (master
            restore, copy-and-apply, S2A hide, completion report, mesh
            export) should only run on the final frame of a sequence —
            or on every bake if we're not in a sequence at all.
            """
            return (not cls.active) or cls.is_last_frame

        @classmethod
        def reset(cls):
            cls.active = False
            cls.is_first_frame = False
            cls.is_last_frame = False
            cls.total_frames = 0


class BackgroundBakeTasks:
    #Non-blender class. BG bake task
    
    active_tasks = []
    completed_tasks = []
    queued_tasks = []
    
    @classmethod
    def get_completed_or_active_bgt_by_pid(cls, pid):
        pid = int(pid)
        
        match = [t for t in cls.completed_tasks if t.pid == pid]
        if len(match) == 0:
            match = [t for t in cls.active_tasks if t.pid == pid]
        assert(len(match)>0)
        match = match[0]
        
        return match
    
    @classmethod
    def get_queued_bgt_by_id(cls, id):
        match = [t for t in cls.queued_tasks if t.id == id]
        assert(len(match) == 1)
        match = match[0]
        
        return match
    
    @classmethod
    def get_bgbake_status(cls, active_bgbake):
        sbp = bpy.context.scene.SimpleBake_Props
        pid = active_bgbake.pid
        path = Path(sbp.bgbake_temp_dir) / "progress" / str(pid)
                            
        try:
            with open(str(path), "r") as progfile:
                progress = int(progfile.readline())
        except:
            #No file yet, as no bake operation has completed yet. Holding message
            progress = 0
        
        active_bgbake.progress = progress
        
        if progress == 100:
            cls.completed_tasks.append(active_bgbake)
            cls.active_tasks.remove(active_bgbake)
            cls.next_please()
        
        return progress
    
    @classmethod
    def next_please(cls):
        if len(cls.active_tasks) == 0 and len(cls.queued_tasks) > 0:
            t = cls.queued_tasks[0]
            cls.active_tasks.append(t)
            cls.queued_tasks.remove(t)
            t.spawn_bg_process()
            return 2
        
        elif len(cls.active_tasks) == 0 and len(cls.queued_tasks) == 0:
            #Nothing happening, kill timer
            return None
        
        else:
            if len(cls.active_tasks)>0: # Just in case
                active_bgt = cls.active_tasks[0]
                cls.get_bgbake_status(active_bgt)
            return 2
    
    def save_file_copy(self):
        sbp = bpy.context.scene.SimpleBake_Props
        unique_id = str(uuid.uuid4())[0:7]
        tmp_dir_path = Path(sbp.bgbake_temp_dir)
        if not os.path.exists(str(tmp_dir_path)):
                os.makedirs(str(tmp_dir_path))
        
        save_path = tmp_dir_path / (unique_id + ".blend")
        
        #Pack dirty images or we lose them on save
        [i.pack() for i in bpy.data.images if i.is_dirty]
        
        bpy.ops.wm.save_as_mainfile(filepath=str(save_path), check_existing=False, copy=True)
        self.initial_save_path = save_path

        return True
    
    def spawn_bg_process(self):
        sbp = bpy.context.scene.SimpleBake_Props
        tmp_dir_path = sbp.bgbake_temp_dir #Already posix path
        base_folder_override = Path(bpy.data.filepath).parent.as_posix()

        args = [bpy.app.binary_path]
        if not sbp.fake_background:
            args.append("--background")
        #args.append("--factory-startup")
        args.append(str(self.initial_save_path))
        args.append("--python-expr")
        args.append(f"""
import bpy;
import os;
from pathlib import Path;
prefs = bpy.context.preferences;
bpy.ops.preferences.addon_enable(module='SimpleBake');
allowed_addons = ['io_anim_bvh', 'io_curve_svg', 'io_mesh_uv_layout', 'io_scene_fbx', 'io_scene_gltf2', 'cycles', 'pose_library', 'bl_pkg', 'SimpleBake'];
for addon in prefs.addons.keys():
    if addon not in allowed_addons:
        try:
            bpy.ops.preferences.addon_disable(module=addon)
            print(f"Disabled " + addon)
        except:
            print(f"Error when disabling addon " + addon)
orig_file_path = bpy.data.filepath;
savepath=str(Path('{tmp_dir_path}') / (str(os.getpid()) + '.blend'));
bpy.ops.wm.save_as_mainfile(filepath=str(savepath), check_existing=False);
os.remove(orig_file_path);
bpy.context.scene.SimpleBake_Props.bgbake_temp_dir = '{tmp_dir_path}';
bpy.context.scene.SimpleBake_Props.base_folder_override = '{base_folder_override}';
{self.start_command};
""")
        process = subprocess.Popen(args, shell=False)

        self.pid = process.pid
        self.file_path_po = Path(tmp_dir_path) / (str(process.pid) + ".blend")

        
        return True
    
    def __init__(self, name, copy_and_apply, start_command, bg_bake_id):
        sbp = bpy.context.scene.SimpleBake_Props

        #Check for queued that need promotion
        bpy.app.timers.register(BackgroundBakeTasks.next_please, first_interval=2)

        # #If this is some kind of PBR bake, run the pre-bake now
        # master_switch = "P" if sbp.global_mode == "PBR" else "C"
        # need = (True if ("pbr" in start_command) or
        #     ("automatch" in start_command and master_switch == "P") or
        #     ("decals" in start_command)
        #     else False)
        # if need:
        #     bpy.ops.simplebake.pbr_pre_bake()


        self.start_command = start_command
        self.save_file_copy()
        self.progress = 0
        if name == "": name = "Untitled"
        self.name = name
        self.copy_and_apply = copy_and_apply
        self.bg_bake_id = bg_bake_id
        self.pid = 0
        self.id = str(uuid.uuid4())

        # #Restore materials in the foreground file
        # bpy.ops.simplebake.material_backup(mode="master_restore")

        #Assume queued for now
        self.__class__.queued_tasks.append(self)

        #print_message(context, "BG bake task created")

class SimpleBake_OT_Import_BGBake(Operator):
    """Import baked textures and objects from the background"""
    bl_idname = "simplebake.import_bgbake"
    bl_label = "Import"
    
    pid: StringProperty()
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        bgt = BackgroundBakeTasks.get_completed_or_active_bgt_by_pid(self.pid)
        
        force_to_object_mode(context)
        
        b_img_names = [i.name for i in bpy.data.images]
        b_obj_names = [o.name for o in context.scene.objects]

        bg_blend_path = str(Path(sbp.bgbake_temp_dir) / (self.pid + ".blend"))

        if bgt.copy_and_apply:
            # Import objects + images together via collection append
            savepath = bg_blend_path + "/Collection/"
            bpy.ops.wm.append(filename="SimpleBake_Bakes_Background", directory=savepath,
                              use_recursive=False, active_collection=False)

            sbc = bpy.data.collections["SimpleBake_Bakes_Background"]
            sbc.name = "SimpleBake_Bakes"

            # Relocate, as append leaves it in a funny place
            context.scene.collection.children.link(sbc)
            del_list = []
            for c in bpy.data.collections:
                if sbc.name in c.children:
                    c.children.unlink(sbc)
                    if len(c.children) == 0:
                        del_list.append(c.name)
            for name in del_list:
                c = bpy.data.collections.get(name)
                if c is not None:
                    bpy.data.collections.remove(c)
        else:
            # Import images directly — no need to append objects just to delete them
            replaced_names = set()
            with bpy.data.libraries.load(bg_blend_path, link=False) as (data_from, data_to):
                intended_names = list(data_from.images)
                data_to.images = list(data_from.images)
            # data_to.images[i] corresponds to intended_names[i].
            # If the loaded image's name differs from its intended name, Blender renamed
            # it due to a conflict with an existing foreground image. We compare by
            # intended name (not by stripping .001/.002 suffixes) so that materials whose
            # names legitimately contain ".001"/".002" are not misidentified as conflicts.
            for intended, img in zip(intended_names, data_to.images):
                if img is None:
                    continue
                if "SB_bake_operation_id" not in img:
                    bpy.data.images.remove(img)
                    continue
                if img.name != intended:
                    # Blender renamed this image — it conflicted with an existing foreground image
                    fg_img = bpy.data.images.get(intended)
                    if fg_img is not None and fg_img.get("SB_bake_operation_id") == img.get("SB_bake_operation_id"):
                        # Stale: identical image already in foreground — discard the import
                        bpy.data.images.remove(img)
                    else:
                        # New image that collided with an existing one (overwrite)
                        if fg_img is not None and "SB_bake_operation_id" in fg_img:
                            bpy.data.images.remove(fg_img)
                            replaced_names.add(intended)
                        img.name = intended
                        img.use_fake_user = True
                else:
                    # Name unchanged — no conflict, freshly baked image
                    img.use_fake_user = True
            # Exclude replaced names so count reflects actual new/updated images
            b_img_names = [n for n in b_img_names if n not in replaced_names]

        a_img_names = [i.name for i in bpy.data.images]
        a_obj_names = [o.name for o in context.scene.objects]

        message = []
        message.append(f"Imported - {len(a_img_names) - len(b_img_names)} images")
        message.append(f"Imported - {len(a_obj_names) - len(b_obj_names)} objects")

        # Set fake_user on newly arrived images
        diflist = [n for n in a_img_names if n not in b_img_names]
        for i_name in diflist:
            if i := bpy.data.images.get(i_name):
                i.use_fake_user = True

        # Duplicate handling only needed for copy_and_apply (wm.append path)
        if bgt.copy_and_apply:
            for name in b_img_names:
                if name + ".002" in a_img_names:
                    bpy.data.images.remove(bpy.data.images[name])
                    bpy.data.images[name + ".002"].name = name
                elif name + ".001" in a_img_names:
                    bpy.data.images.remove(bpy.data.images[name])
                    bpy.data.images[name + ".001"].name = name

        BackgroundBakeTasks.completed_tasks.remove(bgt)

        #Hide source and/or cage object if requested
        for obj in context.scene.objects:
            if "SB_BG_HIDE" in obj:
                l = obj["SB_BG_HIDE"]
                if bgt.bg_bake_id in l:
                    obj.hide_set(True)


        show_message_box(context, message, "Import complete", icon = 'INFO')
        return{'FINISHED'}

    
class SimpleBake_OT_Delete_Queued_BGBake(Operator):
    """Delete a queued background bake"""
    bl_idname = "simplebake.delete_queued_bgbake"
    bl_label = "Delete"
    
    id: StringProperty()
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        bgt = BackgroundBakeTasks.get_queued_bgt_by_id(self.id)
        
        BackgroundBakeTasks.queued_tasks.remove(bgt)
        
        return{'FINISHED'}
                
class SimpleBake_OT_Discard_BGBake(Operator):
    """Discard a completed background bake"""
    bl_idname = "simplebake.discard_bgbake"
    bl_label = "Discard"
    
    pid: StringProperty()
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        bgt = BackgroundBakeTasks.get_completed_or_active_bgt_by_pid(self.pid)
        pid = bgt.pid
        
        BackgroundBakeTasks.completed_tasks.remove(bgt)
        path = str(bgt.file_path_po)
        try:
            os.remove(path)
            os.remove(path.replace(".blend", ".blend1"))
        except:
            pass
        
        return{'FINISHED'}


class SimpleBake_OT_Kill_Active_BGBake(Operator):
    """Kill an active background bake"""
    bl_idname = "simplebake.kill_active_bgbake"
    bl_label = "Kill"
    
    pid: StringProperty()
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        bgt = BackgroundBakeTasks.get_completed_or_active_bgt_by_pid(self.pid)
        pid = bgt.pid
        
        BackgroundBakeTasks.active_tasks.remove(bgt)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            print(f"Unable to kill process {pid}")
        
        return{'FINISHED'}
 
class SimpleBake_OT_Update_Progress(Operator):
    bl_idname = "simplebake.update_progress"
    bl_label = "Update"
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        print(f"Progress update - {sbp.current_bake_image_number}")

        self.background = True if "--background" in sys.argv or sbp.fake_background else False

        sbp.current_bake_image_number+=1
        
        percent_complete = (sbp.current_bake_image_number/sbp.total_bake_images_number) *100
        percent_complete = round(percent_complete)
        sbp.percent_complete = percent_complete
        
        if self.background:
            path = Path(sbp.bgbake_temp_dir) / "progress"
            
            if not os.path.exists(str(path)):
                os.makedirs(str(path))
            
            pid = os.getpid()
            path = path / str(pid)
            
            with open(str(path), "w") as progfile:
                progfile.write(str(percent_complete))
        
        return{'FINISHED'}


#Non-Blender class
class BakeProgress:

    def __init__(self, mode, objnum, hl_matches=None):

        sbp = bpy.context.scene.SimpleBake_Props

        t=0

        if mode == SBConstants.PBRS2A_DECALS:
            ps = len(pbr_selections_to_list(bpy.context))
            ss = len(specials_selection_to_list(bpy.context))

            #The S2A element
            t = (ps+ss) * 1
            #The non-S2A element
            t+= ps * 1

            sbp.total_bake_images_number = t


        if mode == SBConstants.PBR:
            ps = len(pbr_selections_to_list(bpy.context))
            print(f"Got {ps} pbr bakes")
            ss = len(specials_selection_to_list(bpy.context))
            print(f"Got {ss} pbr bakes")
            t = (ps + ss) * objnum
            print(f"Total of {t} based on {ps+ss} x {objnum}")

            sbp.total_bake_images_number = t


        if mode == SBConstants.PBRS2A:
            ps = len(pbr_selections_to_list(bpy.context))
            ss = len(specials_selection_to_list(bpy.context))
            o = 1 #S2A bake

            t = (ps + ss) * o

            sbp.total_bake_images_number = t

        if mode == SBConstants.CYCLESBAKE:
            cb = 1
            ss = len(specials_selection_to_list(bpy.context))
            t = (cb + ss) * objnum
            sbp.total_bake_images_number = t

        if mode == SBConstants.CYCLESBAKE_S2A:
            cb = 1 #CyclesBake
            ss = len(specials_selection_to_list(bpy.context))
            objnum = 1 #S2A bake

            t = (cb + ss) * objnum
            sbp.total_bake_images_number = t

        if mode in [SBConstants.PBRS2A_AUTOMATCH, SBConstants.CYCLESBAKES2A_AUTOMATCH]:

            #Cycles bake always has only one bake mode
            ps = len(pbr_selections_to_list(bpy.context)) if mode == SBConstants.PBRS2A_AUTOMATCH else 1

            ss = len(specials_selection_to_list(bpy.context))
            t = len(hl_matches) * (ps + ss)

            sbp.total_bake_images_number = t


classes = ([
    SimpleBake_OT_Update_Progress,
    SimpleBake_OT_Import_BGBake,
    SimpleBake_OT_Delete_Queued_BGBake,
    SimpleBake_OT_Kill_Active_BGBake,
    SimpleBake_OT_Discard_BGBake
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

