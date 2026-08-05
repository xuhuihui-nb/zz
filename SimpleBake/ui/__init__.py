from . import panel
from . import panel_operators
from . import objects_list
from . import channel_packing_list
from . import preferences
from . import presets_list
from . import presets_list_local
from . import object_uvs_list
from . import panel_helpers

def register():
    objects_list.register()
    panel.register()
    panel_operators.register()
    channel_packing_list.register()
    preferences.register()
    presets_list.register()
    presets_list_local.register()
    object_uvs_list.register()
    panel_helpers.register()

def unregister():
    objects_list.unregister()
    panel.unregister()
    panel_operators.unregister()
    channel_packing_list.unregister()
    preferences.unregister()
    presets_list.unregister()
    presets_list_local.unregister()
    object_uvs_list.unregister()
    panel_helpers.unregister()
