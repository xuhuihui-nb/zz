import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy.utils import register_class, unregister_class

from .background_and_progress import BakeInProgress
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from datetime import datetime

_handle = None
past_messages = [""]
current_obj = ""
current_mode = ""


debug_only = False


def redraw_3d_viewport():
    s = bpy.context.screen
    viewport_areas = []
    for a in s.areas:
        if a.type == "VIEW_3D":
            viewport_areas.append(a)

    for a in viewport_areas:
        a.tag_redraw()


def remove_callback_px():
    global _handle
    global past_messages
    # Check if condition is met
    if BakeInProgress.is_baking:
        # Reset timer
        bpy.app.timers.unregister(remove_callback_px)
        bpy.app.timers.register(remove_callback_px, first_interval=5.0)
    else:
        bpy.app.timers.unregister(remove_callback_px)
        past_messages = [""]
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
            _handle = None
        except Exception as e:
            _handle = None

def draw_callback_px():
    global _handle
    global past_messages
    global current_mode
    global current_obj
    sbp=bpy.context.scene.SimpleBake_Props

        #
    # if past_messages[-1] != sbp.fg_status_message:
    #     past_messages.append(sbp.fg_status_message)
    #     past_messages = past_messages[-3:]

    font_id = 0
    blf.size(font_id, 20)
    blf.color(font_id, 1, 1, 1, 1)

    COUNT=10
    pms = past_messages[-1*COUNT:]

    i=0
    while i < len(pms):
        blf.position(font_id, 15, (COUNT-i)*30, 0)
        blf.draw(font_id, pms[i])
        i+=1

    if not BakeInProgress.is_baking:
        return True

    if BakeInProgress.Sequence.active:
        blf.position(font_id, 15, (COUNT+4)*30, 0)
        blf.draw(font_id, f"FRAME NUMBER - {bpy.context.scene.frame_current} (End Frame: {sbp.image_sequence_end_frame})")
    blf.position(font_id, 15, (COUNT+3)*30, 0)
    blf.draw(font_id, f"SIMPLEBAKE - BAKING IN PROGRESS - {sbp.percent_complete}% COMPLETE")
    blf.position(font_id, 15, (COUNT+2)*30, 0)
    if BakeInProgress.is_baking:
        blf.draw(font_id, f"CURRENTLY BAKING | {current_obj} | {current_mode}")
    blf.position(font_id, 15, (COUNT+1)*30, 0)
    blf.draw(font_id, f"------------------------------------------------------------------------")


def print_message(context, msg, screen=True, debug=False):

    #import time
    #time.sleep(0.1)  # Sleep for 100 milliseconds

    if (debug_only and debug) or not debug_only:
        print(f"SIMPLEBAKE: -- {msg}")



    global _handle
    if _handle == None and screen:
        args = ()
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
        bpy.app.timers.register(remove_callback_px, first_interval=5.0)

    global past_messages
    try:#Because we can be called on Blender load and get that restricted context error
        sbp=context.scene.SimpleBake_Props
        current_time = datetime.now().time()
        formatted_time = current_time.strftime('%H:%M:%S')
        sbp.fg_status_message = f"[{formatted_time}] - {msg}"
        past_messages.append(sbp.fg_status_message)

        redraw_3d_viewport()
    except:
        pass

    global current_mode
    global current_obj
    if "Starting bake mode:" in msg:
        current_mode = msg.replace("Starting bake mode: ","")
    if "Starting object:" in msg:
        current_obj = msg.replace("Starting object: ","")


class SimpleBake_OT_Print_Message(Operator):
    bl_idname = "simplebake.print_message"
    bl_label = ""

    message: StringProperty()

    def execute(self, context):
        global _handle
        if _handle == None:
            args = ()
            _handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, args, 'WINDOW', 'POST_PIXEL')

        print_message(context, self.message)

        return {'FINISHED'}

classes = ([
    SimpleBake_OT_Print_Message
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
