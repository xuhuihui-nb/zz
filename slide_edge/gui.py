# -*- coding: utf-8 -*-

import bpy
import blf

from mathutils import Matrix, Vector, Quaternion
from mathutils import bvhtree
from bpy_extras import view3d_utils
import gpu
from gpu_extras.batch import batch_for_shader
import math

if bpy.app.version < (3, 5, 0):
    import bgl

import pprint

if bpy.app.version < (3, 5, 0):
    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
else:
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

handle3d = None
handle3dtext = None

lines = []
lines2 = []
txtall = []
rects = []
textpos = []
data = []


def addline(p1, p2):
    global lines
    lines.append(p1)
    lines.append(p2)


def addline2(p1, p2):
    global lines2
    lines2.append(p1)
    lines2.append(p2)    


def get_screen_pos(loc):
    region = bpy.context.region
    region3D = bpy.context.space_data.region_3d
    pos = view3d_utils.location_3d_to_region_2d(region, region3D, loc)
    return pos    


def addtext(loc, txt):
    global textpos
    pos = get_screen_pos(loc)
    if pos:
        textpos.append((str(txt), pos.x, pos.y, 20))


def ShowMessageBox(messages="", title="", icon='BLENDER'):
    def draw(self, context):
        for s in messages:
            self.layout.label(text=s)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def draw_3d(self, context):
    global lines
    global lines2
    draw_line(lines, (1, 1, 0, 1), True, True, 1)
    draw_line(lines2, (1, 1, 1, 1), True, True, 4)


def draw_text_callback(self, context):
    global txtall
    global textpos
    left = 600
    sp = 30 * 1.7
    top = len(txtall) * sp + 90
    off = 0
    for p in txtall:
        off += sp
        draw_text([left, top - off], p)    

    for p in textpos:        
        draw_text_adv(p)    


def draw_text_adv(pam):
    sc = bpy.context.preferences.system.ui_scale 
    text, x, y, size = pam
    font_id = 0
    blf.color(font_id, 1, 1, 1, 1)
    blf.position(font_id, x, y, 0)
    if bpy.app.version < (3, 5, 0):
        blf.size(font_id, math.floor(size * sc), 72)
    else:
        blf.size(font_id, math.floor(size * sc))
    blf.draw(font_id, text)


def draw_text(pos, text):
    sc = bpy.context.preferences.system.ui_scale 
    if pos is None:
        return
    font_id = 0
    blf.color(font_id, 1, 1, 1, 1)
    blf.position(font_id, pos[0], pos[1], 0)
    if bpy.app.version < (3, 5, 0):
        blf.size(font_id, math.floor(16 * sc), 72)
    else:
        blf.size(font_id, math.floor(16 * sc))    
    blf.draw(font_id, text)


def draw_line(points, color, blend=False, smooth=False, width=1):
    if not points:
        return
    if bpy.app.version < (3, 5, 0):
        draw_line_gl(points, color, blend=blend, smooth=smooth, width=width)
        return

    global shader
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("color", color)
    shader.uniform_float("lineWidth", width)
    batch = batch_for_shader(shader, 'LINES', {"pos": points})
    batch.draw(shader)
    gpu.state.blend_set("NONE")


def draw_line_gl(points, color, blend=False, smooth=False, width=1):
    global shader

    if len(points) == 0:
        return

    if blend:
        bgl.glEnable(bgl.GL_BLEND)
    else:
        bgl.glDisable(bgl.GL_BLEND)

    if smooth:
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
    else:
        bgl.glDisable(bgl.GL_LINE_SMOOTH)
    
    bgl.glLineWidth(width)

    shader.bind()
    shader.uniform_float("color", color)
    batch = batch_for_shader(shader, 'LINES', {"pos": points})
    batch.draw(shader)

    bgl.glDisable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_LINE_SMOOTH)
    bgl.glLineWidth(1)    


def draw_handle_add(arg):
    global handle3d
    handle3d = bpy.types.SpaceView3D.draw_handler_add(
        draw_3d, arg, 'WINDOW', 'POST_VIEW')

def text_handle_add(arg):
    global handle3dtext
    handle3dtext = bpy.types.SpaceView3D.draw_handler_add(
        draw_text_callback, arg, 'WINDOW', 'POST_PIXEL')


def draw_handle_remove():    
    global handle3d
    if handle3d is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle3d, 'WINDOW')
        except Exception:
            pass
        handle3d = None

    global handle3dtext
    if handle3dtext is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle3dtext, 'WINDOW')
        except Exception:
            pass
        handle3dtext = None
