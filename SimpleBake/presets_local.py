import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.props import StringProperty

from .presets import basic_props, scene_props
from .messages import print_message
from . import utils
from .ui.objects_list import refresh_mat_bake_list

import json

#TODO - Loading order problem

def deep_setattr(obj, attr, value):
    """Recursively set attributes on an object, including sub-objects."""
    pre, _, post = attr.rpartition('.')
    return setattr(deep_getattr(obj, pre) if pre else obj, post, value)

def deep_getattr(obj, attr):
    """Recursively get attributes from an object, including sub-objects."""
    for part in attr.split('.'):
        obj = getattr(obj, part)
    return obj

def sb_prop_group_to_dict(context):
    """
    Puts all SimpleBake current settings into a dict
    """
    sbp = context.scene.SimpleBake_Props

    d = {}

    for p in basic_props:
        try:
            val = getattr(sbp, p)
        except UnicodeDecodeError as e:
            print(f"[SimpleBake] UnicodeDecodeError on prop '{p}': {e}")

        if isinstance(val, bpy.types.bpy_prop_array):
            d[p] = list(val)
        else:
            d[p] = val

    #Now for the objects
    d["objects_list"] = [o.name for o in sbp.objects_list]
    d["mat_bake_list"] = [(e.obj_name, e.mat_name, e.enabled) for e in sbp.mat_bake_list]
    d["pbr_target_obj"] =  sbp.targetobj.name if sbp.targetobj != None else None
    d["cycles_target_obj"] =  sbp.targetobj_cycles.name if sbp.targetobj_cycles != None else None

    #Cage object if there is one
    if context.scene.render.bake.cage_object != None:
        d["cage_object"] = context.scene.render.bake.cage_object.name
    else:
        d["cage_object"] = None

    #Now the channel pack images
    cp_images_dict = {}
    for cpt in sbp.cp_list:
        thiscpt_dict = {}
        thiscpt_dict["R"] = cpt.R
        thiscpt_dict["G"] = cpt.G
        thiscpt_dict["B"] = cpt.B
        thiscpt_dict["A"] = cpt.A

        thiscpt_dict["file_format"] = cpt.file_format
        thiscpt_dict["exr_codec"] = cpt.exr_codec
        thiscpt_dict["png_compression"] = cpt.png_compression

        cp_images_dict[cpt.name] = thiscpt_dict
    if len(cp_images_dict)>0:
            d["channel_packed_images"] = cp_images_dict

    #UV map list
    d["uvs"] = [(i.name, i.uv_name) for i in sbp.uv_items]

    return d


def existing_preset_to_dict(context, friendly_name):
    """
    Pulls out an existing saved local preset into a dict
    """
    sbp = context.scene.SimpleBake_Props

    name =  f"SB_local_preset_{friendly_name}"
    s = sbp[name]
    d = json.loads(s)
    return d

def save_preset(context, friendly_name):
    """
    Saves the current SimpleBake settings to a local preset of name friendly_name
    """
    sbp = context.scene.SimpleBake_Props

    sb = sb_prop_group_to_dict(context)
    cs = {}
    for p in scene_props:
        cs[p] = deep_getattr(context.scene, p)



    sbp[f"SB_local_preset_{friendly_name}"] = json.dumps(sb | cs)

def _apply_preset_dict(context, d):
    """Apply a settings dict to the current scene. d is modified in-place."""
    sbp = context.scene.SimpleBake_Props
    utils.suppress_for_preset_load = True

    sbp.objects_list.clear()

    #First the object list
    for obj_name in d["objects_list"]:
        if obj_name in context.scene.objects:
            #Find where name attribute of each object in the advanced selection list matches the name
                l = [o.name for o in sbp.objects_list if o.name == obj_name]
                if len(l) == 0:
                    #Not already in the list
                    i = sbp.objects_list.add()
                    i.name = obj_name #Advanced object list has a name and pointers arritbute
                    i.obj_point = context.scene.objects[obj_name]

    if d["pbr_target_obj"] != None and d["pbr_target_obj"] in context.scene.objects:
        sbp.targetobj = context.scene.objects[d["pbr_target_obj"]]
    if d["cycles_target_obj"] != None and d["cycles_target_obj"] in context.scene.objects:
        sbp.targetobj_cycles = context.scene.objects[d["cycles_target_obj"]]
    if d["cage_object"] != None and d["cage_object"] in context.scene.objects:
        context.scene.render.bake.cage_object = context.scene.objects[d["cage_object"]]

    #Mat bake list — refresh first to populate all materials, then apply saved enabled states
    refresh_mat_bake_list(context)
    if "mat_bake_list" in d:
        saved_states = {(obj_name, mat_name): enabled for obj_name, mat_name, enabled in d["mat_bake_list"]}
        for entry in sbp.mat_bake_list:
            key = (entry.obj_name, entry.mat_name)
            if key in saved_states:
                entry.enabled = saved_states[key]

    del d["objects_list"]
    d.pop("mat_bake_list", None)

    #Now channel pack
    if "channel_packed_images" in d:
        channel_packed_images = d["channel_packed_images"]

        if len(channel_packed_images) > 0:
            sbp.cp_list.clear()

        for imgname in channel_packed_images:
            thiscpt_dict = channel_packed_images[imgname]

            #Create the list item
            li = sbp.cp_list.add()
            li.name = imgname

            #Set the list item properies
            li.R = thiscpt_dict["R"]
            li.G = thiscpt_dict["G"]
            li.B = thiscpt_dict["B"]
            li.A = thiscpt_dict["A"]

            li.file_format = thiscpt_dict["file_format"]
            li.exr_codec = thiscpt_dict["exr_codec"]
            if "png_compression" in thiscpt_dict:
                li.png_compression = thiscpt_dict["png_compression"]
            else:
                li.png_compression = 15

    #UV maps list
    bpy.ops.simplebake.sync_uv_list()
    if "uvs" in d:
        for n, uvn in d["uvs"]:
            if (i:=sbp.uv_items.find(n)) != -1:
                sbp.uv_items[i].uv_name = uvn

    try:
        for k in d:
            if k not in scene_props:
                try:
                    setattr(sbp, k, d[k])
                except:
                    pass
            else:
                try:
                    deep_setattr(context.scene, k, d[k])
                except:
                    pass
    finally:
        utils.suppress_for_preset_load = False


def load_preset(context, friendly_name):
    _apply_preset_dict(context, existing_preset_to_dict(context, friendly_name))



class SimpleBake_OT_local_preset_save(Operator):
    """Save current SimpleBake settings to local preset"""
    bl_idname = "simplebake.local_preset_save"
    bl_label = "Save local preset"

    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        return sbp.local_preset_name != ""

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        save_preset(context, sbp.local_preset_name)
        bpy.ops.simplebake.local_preset_refresh()

        self.report({"INFO"}, f"Local Preset {sbp.local_preset_name} saved")
        return {'FINISHED'}

class SimpleBake_OT_local_preset_save_override(Operator):
    """Save current SimpleBake settings to local preset overriding the UI for the name"""
    bl_idname = "simplebake.local_preset_save_override"
    bl_label = "Save local preset"

    name_override: StringProperty()

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        save_preset(context, self.name_override)
        return {'FINISHED'}

class SimpleBake_OT_local_preset_load(Operator):
    """Load selected SimpleBake preset"""
    bl_idname = "simplebake.local_preset_load"
    bl_label = "Load local preset"

    @classmethod
    def poll(cls,context):
        sbp = context.scene.SimpleBake_Props
        try:
            sbp.local_presets_list[sbp.local_presets_list_index].name
            return True
        except:
            return False


    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        load_preset(context, friendly_name=sbp.local_preset_name)
        self.report({"INFO"}, f"Local Preset {sbp.local_preset_name} loaded")
        return {'FINISHED'}

class SimpleBake_OT_local_preset_load_override(Operator):
    """Load selected SimpleBake preset overriding the UI for the name"""
    bl_idname = "simplebake.local_preset_load_override"
    bl_label = "Load local preset"

    name_override: StringProperty()

    def execute(self, context):
        load_preset(context, friendly_name=self.name_override)
        return {'FINISHED'}

class SimpleBake_OT_Paste_Settings_Clipboard(Operator):
    """Paste SimpleBake settings from clipboard JSON (copied via Copy Settings to Clipboard)"""
    bl_idname = "simplebake.paste_settings_clipboard"
    bl_label = "Paste Settings from Clipboard"

    def execute(self, context):
        raw = context.window_manager.clipboard
        if not raw or not raw.strip():
            self.report({"ERROR"}, "Clipboard is empty")
            return {'CANCELLED'}

        try:
            d = json.loads(raw)
        except json.JSONDecodeError as e:
            self.report({"ERROR"}, f"Clipboard does not contain valid JSON: {e}")
            return {'CANCELLED'}

        required = {"objects_list", "pbr_target_obj", "cycles_target_obj", "cage_object"}
        if not required.issubset(d.keys()):
            self.report({"ERROR"}, "Clipboard JSON does not look like SimpleBake settings")
            return {'CANCELLED'}

        _apply_preset_dict(context, d)
        self.report({"INFO"}, "SimpleBake settings pasted from clipboard")
        return {'FINISHED'}


classes = ([
    SimpleBake_OT_local_preset_load,
    SimpleBake_OT_local_preset_save,
    SimpleBake_OT_local_preset_save_override,
    SimpleBake_OT_local_preset_load_override,
    SimpleBake_OT_Paste_Settings_Clipboard,
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
