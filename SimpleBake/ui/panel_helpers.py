import bpy
from ..bake_operators.pbr_bake_support_operators import has_convertible_shaders

is_dirty1 = True
is_dirty2 = True
is_dirty3 = True
is_dirty4 = True

@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    global is_dirty1, is_dirty2, is_dirty3, is_dirty4
    is_dirty1 = True
    is_dirty2 = True
    is_dirty3 = True
    is_dirty4 = True

check_for_render_inactive_modifiers_cached = False
def check_for_render_inactive_modifiers(context):
    def update_cache(result):
        global is_dirty1, check_for_render_inactive_modifiers_cached
        check_for_render_inactive_modifiers_cached = result
        is_dirty1 = False

    if not is_dirty1:
        return check_for_render_inactive_modifiers_cached

    sbp = context.scene.SimpleBake_Props
    objects = [i.obj_point for i in sbp.objects_list if i.obj_point is not None]
    for obj in objects:
        for mod in obj.modifiers:
            if mod.show_render and not mod.show_viewport:
                update_cache(True)
                return True
    if sbp.selected_s2a and sbp.targetobj is not None:
        for mod in sbp.targetobj.modifiers:
            if mod.show_render and not mod.show_viewport:
                update_cache(True)
                return True
    if sbp.cycles_s2a and sbp.targetobj_cycles is not None:
        for mod in sbp.targetobj_cycles.modifiers:
            if mod.show_render and not mod.show_viewport:
                update_cache(True)
                return True
    update_cache(False)
    return False

check_for_convertible_shaders_cached = False
def check_for_convertible_shaders(context):
    def update_cache(result):
        global is_dirty2, check_for_convertible_shaders_cached
        check_for_convertible_shaders_cached = result
        is_dirty2 = False

    if not is_dirty2:
        return check_for_convertible_shaders_cached

    sbp = context.scene.SimpleBake_Props
    bake_objects = [i.obj_point.name for i in sbp.objects_list]
    if sbp.selected_s2a and sbp.s2a_opmode == "decals" and sbp.targetobj is not None:
        bake_objects.append(sbp.targetobj.name)
    mats = set()
    for obj_name in bake_objects:
        if not (o := context.scene.objects.get(obj_name)):
            continue
        for slot in o.material_slots:
            if slot.material is not None:
                mats.add(slot.material.name)
    result = any(has_convertible_shaders(m) for m in mats)
    update_cache(result)
    return result

check_for_auto_cage_cached = False
def check_for_auto_cage(context):

    def update_cache(result):
        global is_dirty3, check_for_auto_cage_cached
        check_for_auto_cage_cached = result
        is_dirty3 = False

    if not is_dirty3:
        return check_for_auto_cage_cached

    sbp = context.scene.SimpleBake_Props

    if sbp.global_mode == 'PBR':
        if sbp.targetobj == None:
            update_cache(False)
            return False
        else:
            tobj_name = sbp.targetobj.name
    else: #CyclesBake
        if sbp.targetobj_cycles == None:
            update_cache(False)
            return False
        else:
            tobj_name = sbp.targetobj_cycles.name

    t = [o.name for o in context.scene.objects
         if "SB_auto_cage" in o and o["SB_auto_cage"] == tobj_name]

    if len(t) > 0:
        update_cache(True)
        return True
    else:
        update_cache(False)
        return False

check_for_viewport_inactive_modifiers_cached = False
def check_for_viewport_inactive_modifiers(context):
    def update_cache(result):
        global is_dirty4, check_for_viewport_inactive_modifiers_cached
        check_for_viewport_inactive_modifiers_cached = result
        is_dirty4 = False

    if not is_dirty4:
        return check_for_viewport_inactive_modifiers_cached
    sbp = context.scene.SimpleBake_Props
    objects = [i.obj_point for i in sbp.objects_list if i.obj_point is not None]
    for obj in objects:
        for mod in obj.modifiers:
            if mod.show_viewport and not mod.show_render:
                update_cache(True)
                return True
    update_cache(False)
    return False


def _dirty_timer():
    global is_dirty1, is_dirty2, is_dirty3, is_dirty4
    is_dirty1 = True
    is_dirty2 = True
    is_dirty3 = True
    is_dirty4 = True
    return 3.0

def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    bpy.app.timers.register(_dirty_timer, first_interval=3.0, persistent=True)

def unregister():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if bpy.app.timers.is_registered(_dirty_timer):
        bpy.app.timers.unregister(_dirty_timer)
