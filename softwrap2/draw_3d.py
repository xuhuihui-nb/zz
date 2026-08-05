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

'''
This is a utility module for drawing lines in the 3D viewport on Blender 2.8
using the GPU Api


The idea is to get rid of messy draw functions and data that is hard to keep track.
This class works directly like a callable draw handler and keeps track of all the geometry data.
'''

__all__ = ["DrawCallback"]

import bpy
try:
    import bgl
except ImportError:
    bgl = None
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
VERSION = bpy.app.version

vertex_shader = '''

uniform mat4 ModelViewProjectionMatrix;

#ifdef USE_WORLD_CLIP_PLANES
uniform mat4 ModelMatrix;
#endif

in vec3 pos;
in vec4 color;

out vec4 finalColor;

void main()
{
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
    gl_Position.z -= 0.002;
    finalColor = color;

    #ifdef USE_WORLD_CLIP_PLANES
      world_clip_planes_calc_clip_distance((ModelMatrix * vec4(pos, 1.0)).xyz);
    #endif
}

'''


fragment_shader = """
in vec4 finalColor;
out vec4 fragColor;

void main()
{
  fragColor = finalColor;
  fragColor = blender_srgb_to_framebuffer_space(fragColor);
}
"""

point_fragment_shader = """
in vec4 finalColor;
in vec4 fragCoord;

out vec4 fragColor;

void main()
{
    vec2 coord = (gl_PointCoord - vec2(0.5, 0.5)) * 2.0;
    float fac = dot(coord, coord);
    if (fac > 0.5){
        discard;
    }
    fragColor = finalColor;
    fragColor = blender_srgb_to_framebuffer_space(fragColor);
}

"""


class DrawCallback:
    running_draws = set()

    def __init__(self):

        # Useful for rendering in the same space of an object
        self.matrix = Matrix().Identity(4)
        # X-ray mode, draw through solid objects
        self.draw_on_top = False
        # Blend mode to choose, set it to one of the blend constants.
        self.blend_mode = 'MULTIPLY'

        self.line_width = 1
        self.point_size = 3

        # Handler Placeholder
        self.draw_handler = None

        self.line_coords = []
        self.line_colors = []
        self.dashed_line_coords = []
        self.dashed_line_colors = []
        self.point_coords = []
        self.point_colors = []
        self.tri_coords = []
        self.tri_colors = []
        self.isolated_pin_coords = []
        self.box_2d_rect = None
        self.draw_handler_2d = None

        self._polyline_shader = None
        try:
            self._polyline_shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        except (ValueError, AttributeError, TypeError):
            pass

        try:
            self._line_shader = gpu.types.GPUShader(vertex_shader, fragment_shader)
            self._point_shader = gpu.types.GPUShader(vertex_shader, point_fragment_shader)
            self._tri_shader = gpu.types.GPUShader(vertex_shader, fragment_shader)
        except TypeError:
            try:
                self._line_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
                self._point_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
                self._tri_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            except (ValueError, AttributeError):
                self._line_shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')
                self._point_shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')
                self._tri_shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')

        line_sh = self._polyline_shader if self._polyline_shader else self._line_shader
        self._line_batch = batch_for_shader(line_sh, 'LINES',
                                            {"pos": self.line_coords, "color": self.line_colors})
        self._dashed_line_batch = batch_for_shader(line_sh, 'LINES',
                                                   {"pos": self.dashed_line_coords, "color": self.dashed_line_colors})
        self._point_batch = batch_for_shader(self._point_shader, 'POINTS',
                                             {"pos": self.point_coords, "color": self.point_colors})
        self._tri_batch = batch_for_shader(self._tri_shader, 'TRIS',
                                           {"pos": self.tri_coords, "color": self.tri_colors})

    def __call__(self, *args, **kwargs):
        # __call__ Makes this object behave like a function.
        # So you can add it like a draw handler.
        self._draw()

    def setup_handler(self):
        # Utility function to easily add it as a draw handler
        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(self, (), "WINDOW", "POST_VIEW")
        self.draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(self._draw_2d, (), "WINDOW", "POST_PIXEL")
        self.__class__.running_draws.add(self)

    def remove_handler(self):
        # Utility function to remove the handler
        if self.draw_handler:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, "WINDOW")
            self.draw_handler = None
        if self.draw_handler_2d:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler_2d, "WINDOW")
            self.draw_handler_2d = None
        self.__class__.running_draws.discard(self)

    @classmethod
    def remove_all_handlers(cls):
        for draw in list(cls.running_draws):
            draw.remove_handler()

    def update_batch(self):
        # This takes the data rebuilds the shader batch.
        # Call it every time you clear the data or add new lines, otherwize,
        # You wont see changes in the viewport
        line_sh = self._polyline_shader if self._polyline_shader else self._line_shader
        coords = [self.matrix @ Vector(coord) for coord in self.line_coords]
        self._line_batch = batch_for_shader(line_sh, 'LINES', {"pos": coords, "color": self.line_colors})
        dashed_coords = [self.matrix @ Vector(coord) for coord in self.dashed_line_coords]
        self._dashed_line_batch = batch_for_shader(line_sh, 'LINES', {"pos": dashed_coords, "color": self.dashed_line_colors})
        coords = [self.matrix @ Vector(coord) for coord in self.point_coords]
        self._point_batch = batch_for_shader(self._point_shader, 'POINTS', {"pos": coords, "color": self.point_colors})
        coords = [self.matrix @ Vector(coord) for coord in self.tri_coords]
        self._tri_batch = batch_for_shader(self._tri_shader, 'TRIS', {"pos": coords, "color": self.tri_colors})

    def add_line(self, start, end, color1=(1, 0, 0, 1), color2=None):
        self.line_coords.append(Vector(start))
        self.line_coords.append(Vector(end))
        self.line_colors.append(color1)
        if color2 is None:
            self.line_colors.append(color1)
        else:
            self.line_colors.append(color2)

    def add_dashed_line(self, start, end, color1=(1, 1, 1, 1), color2=None, dash_length=0.0025, gap_ratio=3.0):
        p1 = Vector(start)
        p2 = Vector(end)
        vec = p2 - p1
        dist = vec.length
        if dist < 1e-6:
            return
        c1 = color1
        c2 = color1 if color2 is None else color2
        dir_vec = vec / dist
        period = dash_length * (1.0 + gap_ratio)
        num_dashes = max(int(dist / period), 1)
        step_len = dist / num_dashes
        solid_len = step_len * (1.0 / (1.0 + gap_ratio))
        for i in range(num_dashes):
            seg_start = p1 + dir_vec * (i * step_len)
            seg_end = seg_start + dir_vec * solid_len
            self.dashed_line_coords.append(seg_start)
            self.dashed_line_coords.append(seg_end)
            self.dashed_line_colors.append(c1)
            self.dashed_line_colors.append(c2)

    def add_point(self, location, color=(1, 0, 0, 1)):
        self.point_coords.append(location)
        self.point_colors.append(color)

    def add_triangle(self, p1, p2, p3, color=(1.0, 0.85, 0.0, 0.35)):
        self.tri_coords.extend([Vector(p1), Vector(p2), Vector(p3)])
        self.tri_colors.extend([color, color, color])

    def add_isolated_pin(self, location, normal=None, scale=1.0, color=None):
        self.isolated_pin_coords.append((Vector(location), Vector(normal) if normal else None, float(scale), color))

    def add_box_2d(self, start_2d, end_2d):
        self.box_2d_rect = (start_2d, end_2d)

    def add_brush_circle_2d(self, center_2d, radius):
        self.brush_circle_2d = (center_2d, radius)

    def clear_data(self):
        # just clear all the data
        self.line_coords = []
        self.line_colors = []
        self.dashed_line_coords = []
        self.dashed_line_colors = []
        self.point_coords = []
        self.point_colors = []
        self.tri_coords = []
        self.tri_colors = []
        self.isolated_pin_coords = []
        self.box_2d_rect = None
        self.brush_circle_2d = None

    def _draw_2d(self):
        if not self.isolated_pin_coords and not getattr(self, 'box_2d_rect', None) and not getattr(self, 'brush_circle_2d', None):
            return

        context = bpy.context
        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        if not region or not space or not hasattr(space, 'region_3d'):
            return
        rv3d = space.region_3d

        # 1. 绘制 2D 半透明框选区域及 Blender 经典虚线边框
        if getattr(self, 'box_2d_rect', None):
            p1, p2 = self.box_2d_rect
            if p1 and p2:
                x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
                x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
                if abs(x2 - x1) > 2 and abs(y2 - y1) > 2:
                    box_tris = [(x1, y1), (x2, y1), (x2, y2), (x1, y1), (x2, y2), (x1, y2)]

                    # 生成 Blender 风格经典虚线段 (Dashed Border)
                    dash_len = 5
                    gap_len = 4
                    box_lines = []

                    # 水平两边 (下&上)
                    for y in (y1, y2):
                        curr_x = x1
                        while curr_x < x2:
                            next_x = min(curr_x + dash_len, x2)
                            box_lines.extend([(curr_x, y), (next_x, y)])
                            curr_x += dash_len + gap_len

                    # 垂直两边 (左&右)
                    for x in (x1, x2):
                        curr_y = y1
                        while curr_y < y2:
                            next_y = min(curr_y + dash_len, y2)
                            box_lines.extend([(x, curr_y), (x, next_y)])
                            curr_y += dash_len + gap_len

                    try:
                        shader2d = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
                    except Exception:
                        shader2d = gpu.shader.from_builtin('UNIFORM_COLOR')

                    gpu.state.blend_set('ALPHA')
                    # 填充框选区域半透明背景
                    shader2d.bind()
                    shader2d.uniform_float("color", (1.0, 1.0, 1.0, 0.08))
                    batch_bg = batch_for_shader(shader2d, 'TRIS', {"pos": box_tris})
                    batch_bg.draw(shader2d)

                    # 绘制 Blender 经典白色虚线边框
                    if box_lines:
                        shader2d.uniform_float("color", (1.0, 1.0, 1.0, 0.95))
                        batch_b = batch_for_shader(shader2d, 'LINES', {"pos": box_lines})
                        batch_b.draw(shader2d)

        # 2. 绘制 2D 平滑笔刷圆形光标 (Smooth Brush Circle)
        if getattr(self, 'brush_circle_2d', None):
            center, radius = self.brush_circle_2d
            if center and radius > 0:
                cx, cy = center[0], center[1]
                import math
                num_seg = 40
                circle_tris = []
                circle_lines = []
                for i in range(num_seg):
                    t1 = 2.0 * math.pi * i / num_seg
                    t2 = 2.0 * math.pi * (i + 1) / num_seg
                    x1, y1 = cx + radius * math.cos(t1), cy + radius * math.sin(t1)
                    x2, y2 = cx + radius * math.cos(t2), cy + radius * math.sin(t2)

                    circle_tris.extend([(cx, cy), (x1, y1), (x2, y2)])
                    circle_lines.extend([(x1, y1), (x2, y2)])

                try:
                    shader2d = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
                except Exception:
                    shader2d = gpu.shader.from_builtin('UNIFORM_COLOR')

                gpu.state.blend_set('ALPHA')
                # 填充浅半透明底色
                shader2d.bind()
                shader2d.uniform_float("color", (0.0, 0.85, 1.0, 0.08))
                batch_fill = batch_for_shader(shader2d, 'TRIS', {"pos": circle_tris})
                batch_fill.draw(shader2d)

                # 绘制圆形光标青色边框
                shader2d.uniform_float("color", (0.0, 0.95, 1.0, 0.85))
                batch_ring = batch_for_shader(shader2d, 'LINES', {"pos": circle_lines})
                batch_ring.draw(shader2d)

        if not self.isolated_pin_coords:
            return

        from bpy_extras.view3d_utils import location_3d_to_region_2d
        import math
        from collections import defaultdict

        num_segments = 24
        white_tri_coords = []
        inner_tri_coords_by_color = defaultdict(list)

        cam_pos = None
        view_dir_to_eye = None
        mat_rot = None
        is_persp = True
        if not self.draw_on_top:
            try:
                cam_matrix = rv3d.view_matrix.inverted()
                is_persp = (rv3d.view_perspective == 'PERSP')
                if is_persp:
                    cam_pos = cam_matrix.to_translation()
                else:
                    view_dir_to_eye = (cam_matrix.to_3x3() @ Vector((0, 0, 1))).normalized()
                mat_rot = self.matrix.to_3x3()
            except Exception:
                pass

        for item in self.isolated_pin_coords:
            inner_color = (1.0, 0.55, 0.0, 1.0)
            if isinstance(item, tuple):
                if len(item) == 4:
                    world_co, vert_norm, scale, col = item
                    if col is not None:
                        inner_color = tuple(col) if hasattr(col, '__len__') else col
                elif len(item) == 3:
                    world_co, vert_norm, scale = item
                elif len(item) == 2:
                    world_co, scale = item[0], item[1]
                    vert_norm = None
                else:
                    world_co, vert_norm, scale = item[0], None, 1.0
            else:
                world_co, vert_norm, scale = item, None, 1.0

            w_co = self.matrix @ world_co

            # 背面剔除 (Backface culling)：当未勾选“在前面”时，背向摄像机的顶点隐藏不绘制
            if not self.draw_on_top and vert_norm is not None and mat_rot is not None:
                if vert_norm.length_squared > 1e-6:
                    w_norm = (mat_rot @ vert_norm).normalized()
                    if is_persp and cam_pos is not None:
                        cam_dir = (cam_pos - w_co).normalized()
                    elif view_dir_to_eye is not None:
                        cam_dir = view_dir_to_eye
                    else:
                        cam_dir = None

                    if cam_dir is not None and w_norm.dot(cam_dir) < -0.1:
                        continue  # 背面顶点，不绘制

            screen_pos = location_3d_to_region_2d(region, rv3d, w_co)
            if not screen_pos:
                continue
            cx, cy = screen_pos[0], screen_pos[1]

            # 1. 外层白色底圈 (基础半径 10 像素 * scale)
            r_outer = 10.0 * scale
            for i in range(num_segments):
                t1 = 2.0 * math.pi * i / num_segments
                t2 = 2.0 * math.pi * (i + 1) / num_segments
                white_tri_coords.append((cx, cy))
                white_tri_coords.append((cx + r_outer * math.cos(t1), cy + r_outer * math.sin(t1)))
                white_tri_coords.append((cx + r_outer * math.cos(t2), cy + r_outer * math.sin(t2)))

            # 2. 内层彩色中心点 (基础半径 5 像素 * scale)
            r_inner = 5.0 * scale
            for i in range(num_segments):
                t1 = 2.0 * math.pi * i / num_segments
                t2 = 2.0 * math.pi * (i + 1) / num_segments
                inner_tri_coords_by_color[inner_color].append((cx, cy))
                inner_tri_coords_by_color[inner_color].append((cx + r_inner * math.cos(t1), cy + r_inner * math.sin(t1)))
                inner_tri_coords_by_color[inner_color].append((cx + r_inner * math.cos(t2), cy + r_inner * math.sin(t2)))

        if not white_tri_coords:
            return

        try:
            shader2d = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        except Exception:
            shader2d = gpu.shader.from_builtin('UNIFORM_COLOR')

        gpu.state.blend_set('ALPHA')

        # 绘制外层白色圆圈
        shader2d.bind()
        shader2d.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        batch_w = batch_for_shader(shader2d, 'TRIS', {"pos": white_tri_coords})
        batch_w.draw(shader2d)

        # 绘制内层核心点 (依据不同配色分别绘制)
        for col, coords in inner_tri_coords_by_color.items():
            if coords:
                shader2d.bind()
                shader2d.uniform_float("color", col)
                batch_in = batch_for_shader(shader2d, 'TRIS', {"pos": coords})
                batch_in.draw(shader2d)

    def _start_drawing(self):
        # This handles all the settings of the renderer before starting the draw stuff
        if VERSION >= (2, 93):
            gpu.state.blend_set('ALPHA')

            if self.draw_on_top:
                gpu.state.depth_test_set('NONE')
            else:
                gpu.state.depth_test_set('LESS_EQUAL')

            if not self._polyline_shader:
                gpu.state.line_width_set(self.line_width)
            gpu.state.point_size_set(self.point_size)

        else:
            bgl.glEnable(bgl.GL_BLEND)

            if self.draw_on_top:
                bgl.glDisable(bgl.GL_DEPTH_TEST)
            else:
                bgl.glEnable(bgl.GL_DEPTH_TEST)

            if bgl:
                try:
                    bgl.glEnable(bgl.GL_LINE_SMOOTH)
                    bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
                except Exception:
                    pass

            bgl.glLineWidth(self.line_width)
            bgl.glPointSize(self.point_size)

    def _stop_drawing(self):

        # just reset some OpenGL stuff to not interfere with other drawings in the viewport
        # its not absolutely necessary but makes it safer.
        if VERSION >= (2, 93):
            pass

        else:
            if bgl:
                try:
                    bgl.glDisable(bgl.GL_LINE_SMOOTH)
                except Exception:
                    pass
            bgl.glDisable(bgl.GL_BLEND)
            bgl.glLineWidth(1)
            bgl.glPointSize(1)
            if self.draw_on_top:
                bgl.glEnable(bgl.GL_DEPTH_TEST)

    def _draw(self):
        # This should be called by __call__,
        # just regular routines for rendering in the viewport as a draw_handler
        self._start_drawing()
        self._tri_shader.bind()
        self._tri_batch.draw(self._tri_shader)

        # 1. 绘制普通线段 (使用 POLYLINE_SMOOTH_COLOR 平滑抗锯齿 Shader)
        if self._polyline_shader and self.line_coords:
            self._polyline_shader.bind()
            vp = gpu.state.viewport_get()
            self._polyline_shader.uniform_float("viewportSize", (float(vp[2]), float(vp[3])))
            self._polyline_shader.uniform_float("lineWidth", float(self.line_width))
            if hasattr(gpu.matrix, 'get_model_view_matrix'):
                mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
            else:
                mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_modelview_matrix()
            self._polyline_shader.uniform_float("ModelViewProjectionMatrix", mvp)
            self._line_batch.draw(self._polyline_shader)
        else:
            self._line_shader.bind()
            self._line_batch.draw(self._line_shader)

        # 2. 绘制牵引虚线 (线宽为现有的 30%, 即约 1.05 像素)
        if self.dashed_line_coords:
            dashed_width = float(max(self.line_width * 0.3, 1.0))
            if self._polyline_shader:
                self._polyline_shader.bind()
                vp = gpu.state.viewport_get()
                self._polyline_shader.uniform_float("viewportSize", (float(vp[2]), float(vp[3])))
                self._polyline_shader.uniform_float("lineWidth", dashed_width)
                if hasattr(gpu.matrix, 'get_model_view_matrix'):
                    mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
                else:
                    mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_modelview_matrix()
                self._polyline_shader.uniform_float("ModelViewProjectionMatrix", mvp)
                self._dashed_line_batch.draw(self._polyline_shader)
            else:
                if VERSION >= (2, 93):
                    gpu.state.line_width_set(dashed_width)
                elif bgl:
                    bgl.glLineWidth(dashed_width)

                self._dashed_line_batch.draw(self._line_shader)

                if VERSION >= (2, 93):
                    gpu.state.line_width_set(self.line_width)
                elif bgl:
                    bgl.glLineWidth(self.line_width)

        self._point_shader.bind()
        self._point_batch.draw(self._point_shader)
        self._stop_drawing()


if __name__ == "__main__":
    # Simple example, run it on blender's text editor.

    # create a new instance of the class
    draw = DrawCallback()
    # add lines to ir
    draw.add_line((10, 0, 0), (-10, 0, 0), color1=(1, 0, 0, 1), color2=(0, 0, 1, 1))
    draw.add_line((0, 0, 0), (0, 0, 5), color1=(0, 1, 0, 1), color2=(0, 1, 1, 1))
    # enable X ray mode/see through objects and set Blend mode to Additive
    draw.draw_on_top = True
    draw.blend_mode = ADDITIVE_BLEND
    # set line width to 5
    draw.line_width = 5
    # Important, update batch always when adding
    # new lines, otherwize they wont render.
    draw.update_batch()
    # setup draw handler, optionally, you can call bpy.SpaceView3D.draw_handler_add()
    draw.setup_handler()
