import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty
from bpy.utils import register_class, unregister_class

from .utils import SBConstants
from .messages import print_message
from .background_and_progress import BakeInProgress as Bip

class SimpleBake_OT_Material_Backup(Operator):
    """Backup object materials"""
    bl_idname = "simplebake.material_backup"
    bl_description = "Backup and restore materials on an object"
    bl_label = "Backup/Restore" 

    mode: EnumProperty(items=[
        ("initialise", "initialise", ""),
        ("master_backup", "master_backup", ""),
        ("master_restore", "master_restore", ""),
        ("working_backup", "working_backup", ""),
        ("working_restore", "working_restore", "")
        ])
    target_object_name: StringProperty()
    
    MODE_MASTER_BACKUP = "master_backup"
    MODE_MASTER_RESTORE = "master_restore"
    MODE_WORKING_BACKUP = "working_backup"
    MODE_WORKING_RESTORE = "working_restore"
    MODE_INITIALISE = "initialise"
    
    def initialise(self, context):
        
        print_message(context, "Initialising material tags")
        for mat in bpy.data.materials:
            if "SB_working_dup" in mat: del mat["SB_working_dup"]
            if "SB_master_dup" in mat: del mat["SB_master_dup"]
            
    
    def backup(self, context):
        print_message(context, f"Backup materials mode {self.tag}")
        obj = context.scene.objects[self.target_object_name]
        slots = [slot for slot in obj.material_slots if slot.material != None]
        
        for slot in slots:

            mat = slot.material

            #Does a dup already exist for this mat. If so, use it and skip this slot
            possible_dups = [m for m in bpy.data.materials if self.tag in m and m[self.tag]==mat.name]
            if len(possible_dups)>0:
                print_message(context, f"Backup of material {mat.name} already exists. Using {possible_dups[0].name}")
                slot.material = possible_dups[0]
                continue

            dup = mat.copy()
            dup[self.tag] = mat.name

            prefix = self.tag[:4].upper().replace("_","")

            dup.name = prefix + "_" + mat.name
            slot.material = dup
            
            #In case of crash
            mat["SB_orig_fake_user"] = mat.use_fake_user
            mat.use_fake_user = True
            
    def restore(self, context):


        #Do this scene wide
        print_message(context, f"Restoring materials mode {self.tag}")
        
        objs = context.scene.objects
        del_list_mat_names = []
        
        for obj in objs:
            slots = [slot for slot in obj.material_slots if slot.material != None]
            
            for slot in slots:
                mat = slot.material
                
                if self.tag in mat:
                    del_list_mat_names.append(mat.name)
                    orig_mat_name = mat[self.tag]
                    #Don't want to try and restore the placeholder material. Doesn't exist.
                    #if "SimpleBake_Placeholder" not in orig_mat_name:
                    if (m:=bpy.data.materials.get(orig_mat_name)):
                        slot.material = bpy.data.materials[orig_mat_name]
                    
                    if "SB_orig_fake_user" in slot.material and not slot.material["SB_orig_fake_user"]:
                        slot.material.use_fake_user = False

                    
        for mat_name in del_list_mat_names:
            if mat_name in bpy.data.materials:
                mat = bpy.data.materials[mat_name]
                bpy.data.materials.remove(mat, do_unlink=True)
    
    def execute(self, context):
        #Master backup and initialise are one-shot setup — only run on the
        #first frame of a sequence (or on every bake when not in a sequence).
        if not Bip.Sequence.should_run_setup():
            if self.mode == self.__class__.MODE_MASTER_BACKUP:
                print_message(context, "No master backup - sequence and not first run")
                return{'FINISHED'}
            if self.mode == self.__class__.MODE_INITIALISE:
                print_message(context, "No materials initialise - sequence and not first run")
                return{'FINISHED'}

        #Master restore is one-shot teardown — only run on the last frame of
        #a sequence (or on every bake when not in a sequence).
        if not Bip.Sequence.should_run_teardown():
            if self.mode == self.__class__.MODE_MASTER_RESTORE:
                print_message(context, "No master restore - sequence and not last run")
                return{'FINISHED'}

        if self.mode == self.__class__.MODE_WORKING_BACKUP:
            self.tag = "SB_working_dup"
            self.backup(context)
        elif self.mode == self.__class__.MODE_WORKING_RESTORE:
            self.tag = "SB_working_dup"
            self.restore(context)
        elif self.mode == self.__class__.MODE_MASTER_BACKUP:
            self.tag = "SB_master_dup"
            self.backup(context)
        elif self.mode == self.__class__.MODE_MASTER_RESTORE:
            self.tag = "SB_master_dup"
            self.restore(context)
        elif self.mode == self.__class__.MODE_INITIALISE:
            self.initialise(context)
            
        return{'FINISHED'}
        
        

classes = ([
        SimpleBake_OT_Material_Backup
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
