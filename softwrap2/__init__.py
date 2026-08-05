# Copyright (C) 2021 Jean Da Costa machado.
# Jean3dimensional@gmail.com
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bpy
import bpy.app.handlers as handlers

bl_info = {
    'name': '动态拓扑',
    'description': 'Transfer topology from one model to another using a softbody simulation',
    'author': 'Jean Da Costa Machado',
    'version': (2, 1, 4),
    'blender': (4, 5, 0),
    'warning': 'local build for Blender 4.5',
    'doc_url': 'https://jeacom25b.github.io/Softwrap-Manual/',
    'tracker_url': 'https://jeacom25b.github.io/Softwrap-Manual/',
    'category': 'Mesh',
    'location': '3D view > properties (N-panel) > 动态拓扑'
}

from .utils import all_classes, register_cls, register_panel_draw, state, S, SW_SHAPE_KEY_NAME, PAUSE_PIN_PALETTE, get_settings
from .draw_3d import DrawCallback
from .properties import SoftwrapSettings
from .ui import draw_softwrap_ui, initialization, symmetry, interaction, VIEW3D_PT_softwrap2_main
from .operators import (
    OBJECT_OT_set_source_softwrap,
    OBJECT_OT_set_target_softwrap,
    OBJECT_OT_apply_softwrap,
    OBJECT_OT_reset_softwrap,
    OBJECT_OT_add_pin_softwrap,
    OBJECT_OT_smooth_traction_pins_softwrap,
    OBJECT_OT_remove_pins_softwrap,
    OBJECT_OT_start_softwrap,
    GPUPin,
    PinCacheData
)


def load_pre_handler(scene):
    try:
        S().stop_engine(bpy.context)
    except Exception:
        pass
    DrawCallback.remove_all_handlers()


@handlers.persistent
def save_pre_handler(scene):
    op = state.running_op
    if op and hasattr(op, 'save_traction_pins_to_ob'):
        op.save_traction_pins_to_ob()


def register():
    if load_pre_handler not in handlers.load_pre:
        handlers.load_pre.append(load_pre_handler)
    if save_pre_handler not in handlers.save_pre:
        handlers.save_pre.append(save_pre_handler)

    for cls in all_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[Softwrap2 Error] Failed to register class {cls}: {e}")

    bpy.types.Scene.softwrap2 = bpy.props.PointerProperty(type=SoftwrapSettings)


def unregister():
    if load_pre_handler in handlers.load_pre:
        handlers.load_pre.remove(load_pre_handler)
    if save_pre_handler in handlers.save_pre:
        handlers.save_pre.remove(save_pre_handler)

    for cls in reversed(all_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    if hasattr(bpy.types.Scene, "softwrap2"):
        del bpy.types.Scene.softwrap2
