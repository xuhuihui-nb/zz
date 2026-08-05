"""Image sequence bake operator.

Drives a frame-by-frame repeat of the main PBR / Cycles bake operator.

Architecture:
    - This is a modal operator that owns Blender's event loop for the
      duration of the sequence. A 1-second timer polls ``Bip.is_baking``
      between frames — this is coarse but reliable across very different
      bake durations.
    - Because a modal operator needs the event loop, sequence bakes cannot
      run under background mode (which fires off a headless subprocess
      and exits). The UI disables background mode whenever the image
      sequence toggle is on.
    - This operator is the single writer of ``Bip.Sequence`` state. All
      other modules must consume that state via
      ``Bip.Sequence.should_run_setup`` / ``should_run_teardown`` rather
      than poking the raw flags.
"""


import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import StringProperty
from ..background_and_progress import BakeInProgress as Bip
from ..messages import print_message


def _resolve_bpy_op(cmd):
    """Resolve ``"simplebake.foo"`` → ``bpy.ops.simplebake.foo``.

    Replaces an older ``eval()``-based call. Raises ValueError if the
    operator can't be found or isn't callable.
    """
    parts = cmd.split(".")
    op = bpy.ops
    for part in parts:
        op = getattr(op, part, None)
        if op is None:
            raise ValueError(f"Unknown bpy operator: {cmd}")
    if not callable(op):
        raise ValueError(f"Resolved object is not callable: {cmd}")
    return op


class SimpleBake_OT_Image_Sequence(Operator):
    """SimpleBake Image Sequence Operator"""
    bl_idname = "simplebake.image_sequence"
    bl_label = "SimpleBake Image Squence Bake Operator"

    _timer = []
    start_frame = 0
    end_frame = 0

    cmd: StringProperty()

    def modal(self, context, event):
        if event.type == 'TIMER':

            if Bip.was_error:
                print_message(context, "Cancelling Image Sequence timer after error")
                self.cancel(context)
                return {'CANCELLED'}

            cur_frame = context.scene.frame_current
            if cur_frame < self.end_frame:
                if not Bip.is_baking:

                    #Must be after the first run
                    Bip.Sequence.is_first_frame = False

                    #Check if this will be the last run
                    if cur_frame + 1 == self.end_frame:
                        #From here on the per-frame teardown operators will
                        #run (master restore, copy-and-apply, completion
                        #message). common_bake_support calls
                        #Bip.Sequence.reset() once the last frame finishes.
                        Bip.Sequence.is_last_frame = True

                    #Advance frame and run the bake again
                    context.scene.frame_current += 1
                    print_message(context, f"Image sequence calling main operator for frame {context.scene.frame_current}")
                    _resolve_bpy_op(self.cmd)()
            else:
                self.cancel(context)
                return {'CANCELLED'}

        return {'PASS_THROUGH'}


    def execute(self, context):

        sbp = context.scene.SimpleBake_Props
        print_message(context, f"Image sequence calling main operator: {self.cmd}")

        self.start_frame = sbp.image_sequence_start_frame
        self.end_frame = sbp.image_sequence_end_frame

        # Inclusive range: we bake at frames start, start+1, ..., end.
        Bip.Sequence.active = True
        Bip.Sequence.is_first_frame = True
        Bip.Sequence.is_last_frame = (self.start_frame == self.end_frame)
        Bip.Sequence.total_frames = (self.end_frame - self.start_frame) + 1

        context.scene.frame_set(self.start_frame)

        wm = context.window_manager
        self._timer.append(wm.event_timer_add(1.0, window=context.window))
        wm.modal_handler_add(self)

        #First run of the chosen command
        _resolve_bpy_op(self.cmd)()

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        for t in self._timer:
            wm.event_timer_remove(t)


classes = ([
    SimpleBake_OT_Image_Sequence
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
