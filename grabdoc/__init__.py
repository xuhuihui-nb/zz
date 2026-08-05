import importlib

import bpy
from bpy.app.handlers import persistent

bl_info = {
    "name": "纹理烘焙场景",
    "author": "Ethan Simon-Law",
    "version": (2, 0, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 纹理烘焙场景",
    "description": "A trim & tileable baker for Blender",
    "category": "Render",
}



#########################
# BOOTSTRAPPER
#########################


def init_baker_dependencies():
    """Refresh all dynamic GrabDoc classes or
    properties dependent on the `UIList` structure."""
    from .preferences import generate_pack_enums
    register_bakers()
    generate_pack_enums()


def register_bakers():
    """Unregister and re-register all bakers and their respective panels."""
    from .ui import GRABDOC_PT_Baker
    for cls in GRABDOC_PT_Baker.__subclasses__():
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            continue
    for cls in subclass_baker_panels():
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass


def subclass_baker_panels():
    """Creates panels for every item in the baker
    `CollectionProperty`s via dynamic subclassing."""
    from .ui import GRABDOC_PT_Baker
    from .utils.baker import get_baker_collections
    baker_classes = []
    for baker_prop in get_baker_collections():
        for baker in baker_prop:
            baker.initialize()
            class_name = f"GRABDOC_PT_{baker.ID}_{baker.index}"
            panel_cls = type(class_name, (GRABDOC_PT_Baker,), {})
            panel_cls.baker = baker
            baker_classes.append(panel_cls)
    return baker_classes


#########################
# HANDLERS
#########################


@persistent
def load_post_handler(_dummy) -> None:
    if not bpy.data.filepath:
        return
    init_baker_dependencies()


@persistent
def save_pre_handler(_dummy) -> None:
    if not bpy.context.scene.gd.preview_state:
        return
    bpy.ops.grabdoc.baker_preview_exit()


#########################
# REGISTRATION
#########################


module_names = (
    "operators.core",
    "operators.material",
    "operators.marmoset",
    "preferences",
    "ui"
)

_modules = []

def _load_modules():
    global _modules
    _modules = []
    for module_name in module_names:
        mod = importlib.import_module(f".{module_name}", __package__)
        _modules.append(mod)

from .ui import draw_grabdoc_ui

def register():
    _load_modules()
    for mod in _modules:
        mod.register()

    bpy.app.handlers.load_post.append(load_post_handler)
    bpy.app.handlers.save_pre.append(save_pre_handler)

def unregister():
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    if save_pre_handler in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_pre_handler)
    for mod in reversed(_modules):
        try:
            mod.unregister()
        except Exception:
            pass

