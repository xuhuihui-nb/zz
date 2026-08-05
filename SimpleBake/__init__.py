bl_info = {
    "name": "SimpleBake",
    "author": "Lewis <www.toohey.co.uk/SimpleBake/support/>",
    "version": (2, 7, 1),
    "blender": (5, 0, 0),
    "location": "Properties Panel -> Render Settings Tab",
    "description": "Simple baking of PBR and other textures",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Object",
}


import bpy
from bpy.utils import register_class, unregister_class

from . import object_preperation
from . import image_management
from . import material_management
from . import external_save
from . import property_group
from . import uv_management
from . import copy_and_apply
from . import starting_checks
from . import utils
from . import background_and_progress
from . import channel_packing
from . import cleanup
try:
    from . import auto_update
except:
    auto_update = None
from . import presets
from . import presets_local
from . import sketchfab_upload
from . import messages
from . import auto_cage
from . import aov
from . import preview_operators

from . import ui
from . import bake_operators

import platform
import sys

if auto_update != None:
    from .auto_update import VersionControl
else:
    VersionControl = None




classes = ([
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

    object_preperation.register()
    image_management.register()
    material_management.register()
    external_save.register()
    property_group.register()
    ui.register()
    uv_management.register()
    copy_and_apply.register()
    bake_operators.register()
    starting_checks.register()
    utils.register()
    background_and_progress.register()
    channel_packing.register()
    if auto_update!=None:
        auto_update.register()
    presets.register()
    presets_local.register()
    sketchfab_upload.register()
    messages.register()
    auto_cage.register()
    cleanup.register()
    aov.register()
    preview_operators.register()

    bpy.types.Scene.simplebake_active_subtab = bpy.props.EnumProperty(
        name="SimpleBake 分页",
        description="选择简单烘焙子页面",
        items=[
            ('PANEL', "烘焙面板", "切换至烘焙主控制面板"),
            ('SETTINGS', "设置", "切换至简单烘焙插件设置页面"),
        ],
        default='PANEL'
    )

    prefs = ui.preferences.get_sb_prefs()

    version = bl_info["version"]
    if VersionControl != None:
        VersionControl.installed_version = version
        VersionControl.check_at_current_version(True)


def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)
        
    object_preperation.unregister()
    image_management.unregister()
    material_management.unregister()
    external_save.unregister()
    property_group.unregister()
    ui.unregister()
    uv_management.unregister()
    copy_and_apply.unregister()
    bake_operators.unregister()
    starting_checks.unregister()
    utils.unregister()
    background_and_progress.unregister()
    channel_packing.unregister()
    if auto_update != None:
        auto_update.unregister()
    presets.unregister()
    presets_local.unregister()
    sketchfab_upload.unregister()
    messages.unregister()
    auto_cage.unregister()
    cleanup.unregister()
    aov.unregister()
    preview_operators.unregister()

    if hasattr(bpy.types.Scene, "simplebake_active_subtab"):
        del bpy.types.Scene.simplebake_active_subtab

