import bpy
import bmesh
import gc
import time
import random
import struct
import array
from collections import namedtuple, defaultdict
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_line_plane
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d, location_3d_to_region_2d

from ..utils.registration import register_cls
from ..utils import state
from ..utils.state import S, SW_SHAPE_KEY_NAME, PAUSE_PIN_PALETTE, get_settings, get_pin_prop
from ..utils.timer import PerfTimer, smoothstep, lerp, intersect_point_2d_rectangle, iter_float_factor
from ..utils.raycast import (
    areas_under_mouse, is_mouse_over_ui, get_mouse_ray, apply_topology_face_material,
    mouse_raycast, global_to_screen, offset_towards_camera, vertex_group_to_list
)
from ..utils.topology import (
    core_mesh_from_bm, deduplicate_links, loop_pairs, sort_vert_link_edges, sort_vert_link_loops,
    structural_springs_indexes, somoothing_springs_indexes, get_fixed_pin_rings, get_step_weight,
    bmesh_walk_edge_loop, find_fixed_pin_loop, find_mesh_edge_loop, find_traction_loop,
    shear_spring_indexes, bending_spring_indexes, ternary_links_indexes, quaternary_link_indexes
)
from ..core.gpu_engine import GPUSpringEngine, get_pin_rings, read_texture_flat
from ..draw_3d import DrawCallback

PinCacheData = namedtuple('PinCacheData', 'rings type scale factor world_pos', defaults=(None,) * 5)

class GPUPin:
    def __init__(self, start_index, n_rings, rings):
        self.start_index = start_index
        self.n_rings = n_rings
        self.rings = rings

@register_cls
class OBJECT_OT_start_softwrap(bpy.types.Operator):
    bl_idname = 'object.start_softwrap'
    bl_label = 'Test springs'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = 'Run the softwrap softbody engine'

    _timer = None

    n_verts = 0
    bvh = None
    engine = None
    structural_springs = None
    shear_springs = None
    bending_springs = None
    arranged_links = None

    symmetry_map = None

    mouse_pin_pos = None
    mouse_pin_delta = None
    mouse_pin = None

    pin_cache = None

    simulation_mask = None
    snapping_mask = None

    draw3d = None

    last_mode = None

    perf_timer = None

    @classmethod
    def poll(self, context):
        if S.target_ob and not S.target_ob.type == 'MESH':
            return False
        return S.source_ob and S.source_ob.type == 'MESH'

    def invoke(self, context, event):
        pass
        if state.running_op:
            state.running_op.stop(context)
            return {'CANCELLED'}

        # 当点击开始按钮时，先把“吸附强度”恢复为0，并将“平滑牵引点”状态调整为取消 (False)
        S.snapping_force = 0.0
        S.use_smooth_brush = False
        self.selected_pause_pins = set()

        if S.target_ob:
            self.target_ob_ref = S.target_ob
            try:
                S.target_ob.select_set(False)
                S.target_ob.hide_select = True
            except Exception:
                pass

        # 1. 转换为“拓扑面” (应用拓扑半透明绿色材质)
        apply_topology_face_material(S.source_ob)

        # 2. 激活源网格并直接进入编辑模式中的“点”模式
        for o in context.selected_objects:
            o.select_set(False)
        S.source_ob.select_set(True)
        context.view_layer.objects.active = S.source_ob

        if S.source_ob.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        context.scene.tool_settings.mesh_select_mode = (True, False, False)

        # 确保激活 Shape Key
        self.get_shape(context)

        # 3. 提取拓扑与几何坐标
        bm = bmesh.from_edit_mesh(S.source_ob.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm_copy = bm.copy()

        self.n_verts = len(bm_copy.verts)
        
        # 提取初始位置和拓扑面片
        verts_coords = [0.0] * (self.n_verts * 3)
        for v in bm_copy.verts:
            verts_coords[v.index * 3 : v.index * 3 + 3] = v.co
            
        triangles = []
        for face in bm_copy.faces:
            for i in range(len(face.verts) - 2):
                triangles.append((face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index))

        # 构建 BVHTree
        if S.target_ob:
            tbm = bmesh.new()
            tbm.from_mesh(S.target_ob.data)
            bmesh.ops.transform(tbm, matrix=S.target_ob.matrix_world, space=Matrix.Identity(4), verts=tbm.verts)
            bmesh.ops.transform(tbm, matrix=S.source_ob.matrix_world.inverted(), space=Matrix.Identity(4), verts=tbm.verts)
            tbm.normal_update()
            self.bvh = BVHTree.FromBMesh(tbm)
            tbm.free()

        # 初始化 GPU 物理求解引擎
        self.engine = GPUSpringEngine(verts_coords, triangles, self.bvh)

        self.structural_springs = self.engine.create_spring_group(bm_copy, structural_springs_indexes(bm_copy))
        self.shear_springs = self.engine.create_spring_group(bm_copy, shear_spring_indexes(bm_copy))
        self.bending_springs = self.engine.create_spring_group(bm_copy, bending_spring_indexes(bm_copy, S.bending_distance))
        self.arranged_links = self.structural_springs.arranged_links

        self.symmetry_map = self.engine.create_symmetry_map(S)

        self.ternary_links = self.engine.create_ternary_links(bm_copy, ternary_links_indexes(bm_copy))
        self.quaternary_links = self.engine.create_quaternary_links(bm_copy, quaternary_link_indexes(bm_copy))
        bm_copy.free()

        state.running_op = self

        self.snapping_mask_update(context)
        self.simulation_mask_update(context)

        self.pin_cache = {}
        self.pause_fixed_orig_pos = {}
        self.traction_pins = {}
        self.is_g_grab_traction = False
        self.g_grab_pins = []
        self.g_grab_fixed_pins = []
        self.g_grab_traction_pins = []
        self.g_grab_backup = {}
        self.prev_pause = False
        self.draw3d = DrawCallback()
        self.draw3d.line_width = 3.5
        self.draw3d.setup_handler()

        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1 / 60, window=context.window)
        self.perf_timer = PerfTimer()
        return {'RUNNING_MODAL'}

    def mouse_pin_set(self, context, event):
        result, location, normal, index = mouse_raycast(S.source_ob, context, event)

        if not result and hasattr(self, 'bvh') and self.bvh:
            # 当源网格射线没击中时，重试碰撞目标网格 (Target Mesh) 对应的 BVH
            mat = S.source_ob.matrix_world.inverted()
            origin, vec = get_mouse_ray(context, event, mat)
            tgt_loc, tgt_norm, tgt_idx, tgt_dist = self.bvh.ray_cast(origin, vec)
            if tgt_loc is not None:
                result = True
                location = tgt_loc
                normal = tgt_norm
                index_v = min(range(len(S.source_ob.data.vertices)), key=lambda i: (S.source_ob.data.vertices[i].co - tgt_loc).length)
                self.mouse_pin_pos = S.source_ob.matrix_world @ location
                self.mouse_pin_delta = self.mouse_pin_pos - S.source_ob.matrix_world @ self.get_vert_co(context, index_v)
                n_rings = S.mouse_grab_size
                rings = get_pin_rings(self.arranged_links, index_v, n_rings)
                self.mouse_pin = GPUPin(index_v, n_rings, rings)
                return True

        if not result:
            return False

        # 从相交面对应的顶点中选取距离交点最近的一个
        face_vertices = S.source_ob.data.polygons[index].vertices
        index = min(face_vertices, key=lambda i: (self.get_vert_co(context, i) - location).length)

        self.mouse_pin_pos = S.source_ob.matrix_world @ location
        self.mouse_pin_delta = self.mouse_pin_pos - S.source_ob.matrix_world @ self.get_vert_co(context, index)

        # 创建 MOUSE_PIN 逻辑
        n_rings = S.mouse_grab_size
        rings = get_pin_rings(self.arranged_links, index, n_rings)
        self.mouse_pin = GPUPin(index, n_rings, rings)

        return True

    def mouse_pin_update(self, context, event):
        o, dir = get_mouse_ray(context, event)
        plane = context.space_data.region_3d.view_rotation @ Vector((0, 0, 1))
        self.mouse_pin_pos = intersect_line_plane(o, o + dir, self.mouse_pin_pos, plane)

    def mouse_pin_clear(self, context, event):
        self.mouse_pin_pos = None
        self.mouse_pin = None
        self.mouse_pin_delta = None

    def empty_pin_scale(self, empty):
        return max((sum(empty.scale) / 3) * 4, 1.000001)

    def pin_cache_update(self, context, event):
        mat = S.source_ob.matrix_world
        mat_inv = S.source_ob.matrix_world.inverted()

        raw_pins = S.source_ob.get('sw_pins', ())
        raw_fixed_indices = []
        for p in raw_pins:
            if isinstance(p, int):
                raw_fixed_indices.append(p)
            elif hasattr(p, '__getitem__') and 'vert_idx' in p:
                raw_fixed_indices.append(p['vert_idx'])

        S.source_ob['sw_pins'] = raw_fixed_indices

        # 处理固定点扩展 (fixed_pin_expansion)
        fixed_indices = list(raw_fixed_indices)
        expanded_target_positions = {}

        if raw_fixed_indices and hasattr(self, 'arranged_links') and self.arranged_links:
            expanded_set = set(raw_fixed_indices)
            raw_fixed_set = set(raw_fixed_indices)

            # 清理非原始固定点的旧锚定记录，确保扩展点能在启动和运行时动态重新计算
            if hasattr(self, 'fixed_anchor_world_pos'):
                for idx in list(self.fixed_anchor_world_pos.keys()):
                    if idx not in raw_fixed_set:
                        self.fixed_anchor_world_pos.pop(idx, None)

            for root_idx in raw_fixed_indices:
                if root_idx < self.n_verts:
                    expansion_rings = max(get_pin_prop(S.source_ob, root_idx, 'expansion', default_val=getattr(S, '_fixed_pin_expansion_global', 0)), 0)
                    if expansion_rings <= 0:
                        continue

                    if hasattr(self, 'traction_pins') and root_idx in self.traction_pins:
                        P_root_world = self.traction_pins[root_idx]
                    elif root_idx in self.fixed_anchor_world_pos:
                        P_root_world = self.fixed_anchor_world_pos[root_idx]
                    else:
                        P_root_world = mat @ self.get_vert_co(context, root_idx)
                        if S.target_ob:
                            P_root_world = self.snap_point_to_bvh(context, P_root_world)

                    N_tgt_w = Vector((0.0, 0.0, 1.0))
                    if hasattr(self, 'bvh') and self.bvh and S.source_ob:
                        local_p = mat_inv @ P_root_world
                        nearest = self.bvh.find_nearest(local_p)
                        if nearest and nearest[1] is not None and nearest[1].length_squared > 1e-6:
                            N_tgt_w = (mat.to_3x3() @ nearest[1]).normalized()
                        else:
                            N_tgt_w = (mat.to_3x3() @ self.get_rest_vert_norm(context, root_idx)).normalized()
                    else:
                        N_tgt_w = (mat.to_3x3() @ self.get_rest_vert_norm(context, root_idx)).normalized()

                    if N_tgt_w.length_squared < 1e-6:
                        N_tgt_w = Vector((0.0, 0.0, 1.0))

                    helper_tgt = Vector((1.0, 0.0, 0.0)) if abs(N_tgt_w.x) < 0.8 else Vector((0.0, 1.0, 0.0))
                    T_tgt = (helper_tgt.cross(N_tgt_w)).normalized()
                    B_tgt = N_tgt_w.cross(T_tgt).normalized()

                    N_src_w = (mat.to_3x3() @ self.get_rest_vert_norm(context, root_idx)).normalized()
                    if N_src_w.length_squared < 1e-6:
                        N_src_w = Vector((0.0, 0.0, 1.0))
                    helper_src = Vector((1.0, 0.0, 0.0)) if abs(N_src_w.x) < 0.8 else Vector((0.0, 1.0, 0.0))
                    T_src = (helper_src.cross(N_src_w)).normalized()
                    B_src = N_src_w.cross(T_src).normalized()

                    ring_layers = get_pin_rings(self.arranged_links, root_idx, expansion_rings + 1)
                    p_src_root = self.get_rest_vert_co(context, root_idx)

                    for ring in ring_layers[1:]:
                        for nbr_idx in ring:
                            if nbr_idx < self.n_verts and nbr_idx not in raw_fixed_set:
                                expanded_set.add(nbr_idx)
                                if nbr_idx not in expanded_target_positions:
                                    v_diff = mat.to_3x3() @ (self.get_rest_vert_co(context, nbr_idx) - p_src_root)
                                    u = v_diff.dot(T_src)
                                    v = v_diff.dot(B_src)
                                    w = v_diff.dot(N_src_w)

                                    P_cand = P_root_world + u * T_tgt + v * B_tgt + w * N_tgt_w
                                    P_snapped = self.snap_point_to_bvh(context, P_cand)
                                    expanded_target_positions[nbr_idx] = P_snapped

            fixed_indices = sorted(expanded_set)

        fixed_set = set(fixed_indices)

        if not hasattr(self, 'fixed_anchor_world_pos'):
            self.fixed_anchor_world_pos = {}

        # 清理已被删除的固定点的锚定记录
        for idx in list(self.fixed_anchor_world_pos.keys()):
            if idx not in fixed_set:
                self.fixed_anchor_world_pos.pop(idx, None)

        if hasattr(self, 'traction_pins') and self.traction_pins:
            for idx in list(self.traction_pins.keys()):
                if idx not in fixed_set:
                    self.traction_pins.pop(idx, None)

        new_cache = {}

        def get_or_create_pin_rings(index, scale):
            n_rings = int(scale)
            return get_pin_rings(self.arranged_links, index, n_rings)

        is_editing = (S.source_ob and S.source_ob.mode == 'EDIT')

        for index in fixed_indices:
            if index < self.n_verts:
                if index in expanded_target_positions:
                    world_pos = expanded_target_positions[index]
                    self.fixed_anchor_world_pos[index] = world_pos
                elif hasattr(self, 'traction_pins') and index in self.traction_pins:
                    world_pos = self.traction_pins[index]
                    self.fixed_anchor_world_pos[index] = world_pos
                elif S.pause or index not in self.fixed_anchor_world_pos:
                    raw_co = mat @ self.get_vert_co(context, index)
                    if S.target_ob:
                        world_pos = self.snap_point_to_bvh(context, raw_co)
                    else:
                        world_pos = raw_co
                    self.fixed_anchor_world_pos[index] = world_pos
                elif is_editing:
                    current_co = mat @ self.get_vert_co(context, index)
                    anchor_co = self.fixed_anchor_world_pos[index]
                    if (current_co - anchor_co).length > 1e-4:
                        world_pos = current_co
                        if S.target_ob:
                            world_pos = self.snap_point_to_bvh(context, world_pos)
                        self.fixed_anchor_world_pos[index] = world_pos
                    else:
                        world_pos = anchor_co
                else:
                    world_pos = self.fixed_anchor_world_pos[index]

                pin_inf = get_pin_prop(S.source_ob, index, 'influence', default_val=getattr(S, '_fixed_pin_influence_global', 0))
                scale = float(max(pin_inf, 0) + 1)
                rings = get_or_create_pin_rings(index, scale)
                new_cache[index] = PinCacheData(rings=rings, type='FIXED_PIN', scale=scale, factor=1.0, world_pos=world_pos)

        if self.mouse_pin_pos:
            self.mouse_pin_update(context, event)
            pin_type = 'MOUSE_PIN'
            index = self.mouse_pin.start_index
            new_cache[index] = PinCacheData(rings=self.mouse_pin.rings,
                                            type=pin_type,
                                            scale=self.mouse_pin.n_rings + 1,
                                            factor=1.0,
                                            world_pos=self.mouse_pin_pos - self.mouse_pin_delta)

        for axis in range(3):
            if S.mirror[axis]:
                for idx, pin_data in list(new_cache.items()):
                    mirr_idx = self.symmetry_map[idx][axis]
                    if mirr_idx == idx:
                        continue
                    location = mat_inv @ pin_data.world_pos
                    location[axis] *= -1
                    location = mat @ location
                    pin_type = 'MIRROR_' + pin_data.type
                    rings = get_or_create_pin_rings(mirr_idx, pin_data.scale)

                    new_cache[mirr_idx] = PinCacheData(rings=rings,
                                                        type=pin_type,
                                                        scale=pin_data.scale,
                                                        factor=pin_data.factor,
                                                        world_pos=location)

        self.pin_cache = new_cache

    def pin_cache_apply(self, context, event, factor=1.0, mouse_factor=1.0):
        mat_inv = S.source_ob.matrix_world.inverted()
        coords = read_texture_flat(self.engine.pos_tex)

        disp_x = [0.0] * self.n_verts
        disp_y = [0.0] * self.n_verts
        disp_z = [0.0] * self.n_verts
        weights = [0.0] * self.n_verts
        fixed_center_mask = [False] * self.n_verts

        # 遍历所有控制钉计算并在 CPU 端累加位移，之后上传 GPU 叠加至解算位置
        for index, pin_data in self.pin_cache.items():
            vert_loc = Vector((coords[index*4], coords[index*4+1], coords[index*4+2]))
            local_pos = mat_inv @ pin_data.world_pos

            vec = local_pos - vert_loc
            if pin_data.type == 'FIXED_PIN' or 'FIXED' in pin_data.type:
                f = 1.0
            else:
                f = mouse_factor if pin_data.type == 'MOUSE_PIN' else factor
            scale = pin_data.scale

            # 应用拓扑环受力权重衰减
            for i, ring in enumerate(pin_data.rings):
                if pin_data.type == 'FIXED_PIN' or 'FIXED' in pin_data.type:
                    weight = max((scale - i) / scale, 0.0)
                else:
                    denom = scale - 1.0
                    if abs(denom) > 1e-5:
                        weight = max(min((scale - i - 1.0) / denom, 1.0), 0.0)
                    else:
                        weight = 1.0
                ring_vec = vec * pin_data.factor * f * weight

                for v_idx in ring:
                    if v_idx < self.n_verts:
                        if i == 0 and (pin_data.type == 'FIXED_PIN' or 'FIXED' in pin_data.type):
                            disp_x[v_idx] = ring_vec.x
                            disp_y[v_idx] = ring_vec.y
                            disp_z[v_idx] = ring_vec.z
                            weights[v_idx] = 1.0
                            fixed_center_mask[v_idx] = True
                        elif not fixed_center_mask[v_idx]:
                            disp_x[v_idx] += ring_vec.x
                            disp_y[v_idx] += ring_vec.y
                            disp_z[v_idx] += ring_vec.z
                            weights[v_idx] += weight

        for v_idx in range(self.n_verts):
            w = weights[v_idx]
            if w > 0.0:
                w_norm = max(w, 1.0)
                self.engine.pin_displacements_data[v_idx*4] = disp_x[v_idx] / w_norm
                self.engine.pin_displacements_data[v_idx*4+1] = disp_y[v_idx] / w_norm
                self.engine.pin_displacements_data[v_idx*4+2] = disp_z[v_idx] / w_norm

    def get_pause_pin_color_map(self, fixed_set):
        if not fixed_set:
            return {}

        visited = set()
        components = []

        for idx in sorted(fixed_set):
            if idx not in visited:
                comp = []
                queue = [idx]
                visited.add(idx)
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    if hasattr(self, 'arranged_links') and self.arranged_links and curr < len(self.arranged_links):
                        for nbr in self.arranged_links[curr]:
                            if nbr in fixed_set and nbr not in visited:
                                visited.add(nbr)
                                queue.append(nbr)
                components.append(comp)

        color_map = {}
        for comp_idx, comp in enumerate(components):
            color = PAUSE_PIN_PALETTE[comp_idx % len(PAUSE_PIN_PALETTE)]
            for idx in comp:
                color_map[idx] = color

        return color_map

    def draw_pins(self, context, event):
        white_line = Vector((1.0, 1.0, 1.0, 1.0))
        yellow_line = Vector((1.0, 0.85, 0.0, 0.95))
        orange_dot = Vector((1.0, 0.6, 0.0, 1.0))
        red = Vector((1.0, 0.2, 0.2, 0.9))
        green = Vector((0.0, 0.9, 0.4, 0.9))

        self.draw3d.clear_data()
        self.draw3d.draw_on_top = S.show_in_front
        self.draw3d.line_width = 3.5

        if S.pause and (getattr(S, 'use_smooth_brush', False) or (event and getattr(event, 'ctrl', False) and getattr(event, 'shift', False))):
            m_pos = getattr(self, 'mouse_pos', None)
            if not m_pos and event and hasattr(event, 'mouse_region_x'):
                m_pos = (event.mouse_region_x, event.mouse_region_y)
            if m_pos:
                brush_r = max(int(S.mouse_grab_size), 1) * 20.0
                self.draw3d.add_brush_circle_2d(m_pos, brush_r)

        if S.pause and getattr(self, 'is_box_selecting', False):
            start_pt = getattr(self, 'box_start', None)
            curr_pt = getattr(self, 'box_current', None)
            if start_pt is not None and curr_pt is not None:
                self.draw3d.add_box_2d(start_pt, curr_pt)

        coords = read_texture_flat(self.engine.pos_tex)
        mat = S.source_ob.matrix_world

        bm_edit = None
        if S.source_ob and S.source_ob.mode == 'EDIT':
            try:
                bm_edit = bmesh.from_edit_mesh(S.source_ob.data)
                bm_edit.verts.ensure_lookup_table()
            except Exception:
                bm_edit = None

        def get_vert_world_pos(v_idx):
            if bm_edit and v_idx < len(bm_edit.verts):
                return mat @ bm_edit.verts[v_idx].co
            return mat @ Vector((coords[v_idx*4], coords[v_idx*4+1], coords[v_idx*4+2]))

        fixed_set = set()
        for index, pin_data in self.pin_cache.items():
            if pin_data.type == 'FIXED_PIN':
                fixed_set.add(index)

        # 判断当前网格选择模式 (点/线/面) 及选中的顶点
        is_vert_mode = False
        is_edge_mode = False
        is_face_mode = False
        selected_edge_pairs = set()
        selected_verts = set()
        if S.source_ob:
            if S.source_ob.mode == 'EDIT' and bm_edit:
                try:
                    select_mode = context.scene.tool_settings.mesh_select_mode
                    is_vert_mode = select_mode[0] and not select_mode[1] and not select_mode[2]
                    is_edge_mode = select_mode[1] and not select_mode[2]
                    is_face_mode = select_mode[2]
                    bm_edit.verts.ensure_lookup_table()
                    for v in bm_edit.verts:
                        if v.select:
                            selected_verts.add(v.index)
                    if not is_vert_mode:
                        bm_edit.edges.ensure_lookup_table()
                        for e in bm_edit.edges:
                            if e.select:
                                selected_edge_pairs.add((e.verts[0].index, e.verts[1].index))
                                selected_edge_pairs.add((e.verts[1].index, e.verts[0].index))
                except Exception:
                    pass
            elif S.source_ob.data and hasattr(S.source_ob.data, 'vertices'):
                try:
                    select_mode = (True, False, False)
                    if context.scene and hasattr(context.scene, 'tool_settings'):
                        select_mode = context.scene.tool_settings.mesh_select_mode
                    is_vert_mode = select_mode[0] and not select_mode[1] and not select_mode[2]
                    is_edge_mode = select_mode[1] and not select_mode[2]
                    is_face_mode = select_mode[2]
                    for v in S.source_ob.data.vertices:
                        if v.select:
                            selected_verts.add(v.index)
                    if hasattr(S.source_ob.data, 'edges'):
                        for e in S.source_ob.data.edges:
                            if e.select:
                                selected_edge_pairs.add((e.vertices[0], e.vertices[1]))
                                selected_edge_pairs.add((e.vertices[1], e.vertices[0]))
                except Exception:
                    pass

        # 获取网格顶点法线用于背面剔除
        normals = None
        if bm_edit:
            try:
                bm_edit.normal_update()
                normals = [v.normal.copy() for v in bm_edit.verts]
            except Exception:
                pass
        elif S.source_ob and S.source_ob.data and hasattr(S.source_ob.data, 'vertices'):
            try:
                normals = [v.normal.copy() for v in S.source_ob.data.vertices]
            except Exception:
                pass

        pause_colors = self.get_pause_pin_color_map(fixed_set) if S.pause else {}
        green_col = (0.0, 0.95, 0.4, 1.0)
        g_grab_fixed_set = set(getattr(self, 'g_grab_fixed_pins', []))
        g_grab_traction_set = set(getattr(self, 'g_grab_traction_pins', []))
        g_grab_pins_set = g_grab_fixed_set | g_grab_traction_set
        
        pause_pins_set = set(getattr(self, 'selected_pause_pins', set()))
        traction_pins_set = set(getattr(self, 'selected_traction_pins', set()))
        if S.pause:
            if hasattr(self, 'selected_pause_pins') or hasattr(self, 'selected_traction_pins'):
                active_selected_pins = pause_pins_set.union(traction_pins_set).intersection(fixed_set).union(g_grab_pins_set)
            else:
                active_selected_pins = selected_verts.intersection(fixed_set).union(g_grab_pins_set)
        else:
            active_selected_pins = selected_verts.union(g_grab_pins_set)

        # 只要有选中的固定点/牵引点或正在移动牵引点，计算 2 步以内影响的邻接边 map
        active_affected_map = {}
        if active_selected_pins and fixed_set and hasattr(self, 'arranged_links') and self.arranged_links:
            active_affected_map = get_fixed_pin_rings(self.arranged_links, fixed_set, list(active_selected_pins), max_steps=2)

        def get_pin_effective_pos(v_idx):
            if S.pause and hasattr(self, 'traction_pins') and self.traction_pins and v_idx in self.traction_pins:
                return self.traction_pins[v_idx]
            return get_vert_world_pos(v_idx)

        for index, pin_data in self.pin_cache.items():
            vert_loc = get_vert_world_pos(index)
            vert_norm = normals[index] if (normals and index < len(normals)) else Vector((0, 0, 1))

            if pin_data.type == 'MOUSE_PIN':
                self.draw3d.add_line(vert_loc, pin_data.world_pos, red, green)
                self.draw3d.add_point(vert_loc, red)
            elif pin_data.type == 'FIXED_PIN':
                is_pin_selected = index in pause_pins_set or index in g_grab_fixed_set
                inner_col = green_col if is_pin_selected else pause_colors.get(index, (0.0, 0.75, 1.0, 1.0))
                if is_vert_mode:
                    # 点模式：仅渲染固定点圆环
                    self.draw3d.add_isolated_pin(vert_loc, vert_norm, scale=0.5, color=inner_col)
                elif is_edge_mode or is_face_mode:
                    # 边/面模式：仅对“孤立固定点”（没有邻接固定边/面的点）渲染固定点，避免点与边/面重叠
                    is_isolated = True
                    if hasattr(self, 'arranged_links') and self.arranged_links and index < len(self.arranged_links):
                        for neighbor in self.arranged_links[index]:
                            if neighbor in fixed_set:
                                is_isolated = False
                                break
                    if is_isolated:
                        self.draw3d.add_isolated_pin(vert_loc, vert_norm, scale=1.0, color=inner_col)
                else:
                    # 物体模式等默认渲染
                    is_isolated = True
                    if hasattr(self, 'arranged_links') and self.arranged_links and index < len(self.arranged_links):
                        for neighbor in self.arranged_links[index]:
                            if neighbor in fixed_set:
                                is_isolated = False
                                break
                    if is_isolated:
                        self.draw3d.add_isolated_pin(vert_loc, vert_norm, scale=1.0, color=inner_col)
                    else:
                        self.draw3d.add_point(vert_loc, inner_col if is_pin_selected else orange_dot)

        # 1. 识别全固定面，并在面模式或物体模式下绘制黄色填充面
        edge_fixed_face_count = defaultdict(int)
        yellow_face = (1.0, 0.85, 0.0, 0.35)

        should_draw_faces = is_face_mode or (not is_vert_mode and not is_edge_mode)

        if fixed_set and S.source_ob:
            if bm_edit:
                try:
                    bm_edit.faces.ensure_lookup_table()
                    for f in bm_edit.faces:
                        if all(v.index in fixed_set for v in f.verts):
                            for e in f.edges:
                                pair = (min(e.verts[0].index, e.verts[1].index), max(e.verts[0].index, e.verts[1].index))
                                edge_fixed_face_count[pair] += 1
                            if should_draw_faces:
                                f_coords = [offset_towards_camera(get_vert_world_pos(v.index), context, factor=0.6) for v in f.verts]
                                for i in range(len(f_coords) - 2):
                                    self.draw3d.add_triangle(f_coords[0], f_coords[i+1], f_coords[i+2], yellow_face)
                except Exception:
                    pass
            elif S.source_ob.data and hasattr(S.source_ob.data, 'polygons'):
                try:
                    for poly in S.source_ob.data.polygons:
                        if all(v in fixed_set for v in poly.vertices):
                            n_v = len(poly.vertices)
                            for i in range(n_v):
                                v1 = poly.vertices[i]
                                v2 = poly.vertices[(i + 1) % n_v]
                                pair = (min(v1, v2), max(v1, v2))
                                edge_fixed_face_count[pair] += 1
                            if should_draw_faces:
                                f_coords = [offset_towards_camera(get_vert_world_pos(v), context, factor=0.6) for v in poly.vertices]
                                for i in range(len(f_coords) - 2):
                                    self.draw3d.add_triangle(f_coords[0], f_coords[i+1], f_coords[i+2], yellow_face)
                except Exception:
                    pass

        # 2. 绘制模型表面原始固定边（仅在边模式/面模式/物体模式下绘制，点模式下不与顶点重叠）
        should_draw_edges = is_edge_mode or is_face_mode or (not is_vert_mode)

        if should_draw_edges and fixed_set and hasattr(self, 'arranged_links') and self.arranged_links:
            for idx in fixed_set:
                if idx < len(self.arranged_links):
                    p1_raw = get_vert_world_pos(idx)
                    for neighbor in self.arranged_links[idx]:
                        if neighbor in fixed_set and neighbor > idx:
                            pair = (idx, neighbor)
                            # 如果该边被 2 个或以上固定面共享，则属于栅格内部共享边，隐藏不绘制黄边
                            if edge_fixed_face_count.get(pair, 0) >= 2 and should_draw_faces:
                                continue

                            p2_raw = get_vert_world_pos(neighbor)
                            p1 = offset_towards_camera(p1_raw, context, factor=1.5)
                            p2 = offset_towards_camera(p2_raw, context, factor=1.5)
                            is_selected = (idx, neighbor) in selected_edge_pairs or (neighbor, idx) in selected_edge_pairs
                            if is_selected:
                                continue
                            
                            # 背景连线颜色 (当前的连线颜色)
                            if S.pause and idx in pause_colors:
                                bg_line_color = pause_colors[idx]
                            else:
                                bg_line_color = yellow_line

                            self.draw3d.add_line(p1, p2, bg_line_color, bg_line_color)

                            # 选中固定点或移动牵引点时，模型表面连线叠加绿色，并逐级变淡
                            if active_affected_map and (idx in active_affected_map or neighbor in active_affected_map):
                                s1 = active_affected_map.get(idx, 999)
                                s2 = active_affected_map.get(neighbor, 999)
                                if s1 <= 2 or s2 <= 2:
                                    a1 = get_step_weight(s1) * 0.95
                                    a2 = get_step_weight(s2) * 0.95
                                    green1 = Vector((0.0, 0.95, 0.4, a1))
                                    green2 = Vector((0.0, 0.95, 0.4, a2))
                                    self.draw3d.add_line(p1, p2, green1, green2)

        # 3. 仅在暂停模式下绘制牵引点 (同心圆)、牵引连线及与源固定点之间的虚线
        if S.pause and hasattr(self, 'traction_pins') and self.traction_pins:
            # 绘制牵引点之间的 3D 连线边 (点模式、边模式、面模式下均绘制牵引边)
            if fixed_set and hasattr(self, 'arranged_links') and self.arranged_links:
                for idx in fixed_set:
                    if idx in self.traction_pins and idx < len(self.arranged_links):
                        p1_trac = self.traction_pins[idx]
                        for neighbor in self.arranged_links[idx]:
                            if neighbor in fixed_set and neighbor > idx:
                                pair = (idx, neighbor)
                                if edge_fixed_face_count.get(pair, 0) >= 2 and should_draw_faces:
                                    continue
                                p2_trac = get_pin_effective_pos(neighbor)
                                p1_t = offset_towards_camera(p1_trac, context, factor=1.5)
                                p2_t = offset_towards_camera(p2_trac, context, factor=1.5)
                                # 基础 3D 牵引连线颜色
                                if S.pause and idx in pause_colors:
                                    bg_line_color = pause_colors[idx]
                                else:
                                    bg_line_color = yellow_line

                                self.draw3d.add_line(p1_t, p2_t, bg_line_color, bg_line_color)

                                # 选中或调整牵引点时，3D 牵引连线叠加绿色步数边，按拓扑步数 (0->1->2) 逐步透明化
                                if active_affected_map and (idx in active_affected_map or neighbor in active_affected_map):
                                    s1 = active_affected_map.get(idx, 999)
                                    s2 = active_affected_map.get(neighbor, 999)
                                    if s1 <= 2 or s2 <= 2:
                                        a1 = get_step_weight(s1) * 0.95
                                        a2 = get_step_weight(s2) * 0.95
                                        green1 = Vector((0.0, 0.95, 0.4, a1))
                                        green2 = Vector((0.0, 0.95, 0.4, a2))
                                        self.draw3d.add_line(p1_t, p2_t, green1, green2)

            for idx, traction_loc in list(self.traction_pins.items()):
                if idx in fixed_set:
                    orig_loc = get_vert_world_pos(idx)
                    vert_norm = normals[idx] if (normals and idx < len(normals)) else Vector((0, 0, 1))

                    is_pin_selected = (idx in traction_pins_set) or (idx in pause_pins_set) or (idx in g_grab_traction_set) or (idx in g_grab_fixed_set)
                    pin_color = green_col if is_pin_selected else pause_colors.get(idx, (0.0, 0.75, 1.0, 1.0))
                    dashed_alpha = 1.0 if is_pin_selected else 0.3
                    dashed_color = Vector((pin_color[0], pin_color[1], pin_color[2], dashed_alpha))

                    # 绘制连接虚线 (未选中时 30% 透明度，选中时 100% 不透明高亮显示)
                    self.draw3d.add_dashed_line(orig_loc, traction_loc, dashed_color, dash_length=0.0025, gap_ratio=3.0)

                    # 牵引点渲染与固定点在边/面模式下保持一致：
                    # - 点模式：所有牵引点均渲染圆环点（scale=0.5），配合上面的 3D 连线实现“同时渲染点和边”
                    # - 边/面模式：仅对“孤立牵引点”（没有邻接固定/牵引边的点）渲染圆环点（scale=1.0），与固定点渲染逻辑一致
                    should_draw_trac_pin = True
                    if is_edge_mode or is_face_mode:
                        is_trac_isolated = True
                        if hasattr(self, 'arranged_links') and self.arranged_links and idx < len(self.arranged_links):
                            for neighbor in self.arranged_links[idx]:
                                if neighbor in fixed_set:
                                    is_trac_isolated = False
                                    break
                        should_draw_trac_pin = is_trac_isolated

                    if should_draw_trac_pin:
                        pin_scale = 0.5 if is_vert_mode else 1.0
                        self.draw3d.add_isolated_pin(traction_loc, vert_norm, scale=pin_scale, color=pin_color)

        self.draw3d.update_batch()

    def snapping_mask_update(self, context):
        vg_data = []
        self.snapping_mask = self.engine.create_mask(vg_data)

    def simulation_mask_update(self, context):
        vg_data = []
        self.simulation_mask = self.engine.create_mask(vg_data)

    def reset_simulation(self, context):
        vdata = [0.0] * (self.n_verts * 3)
        S.source_ob.data.vertices.foreach_get('co', vdata)
        self.engine.from_list(vdata)

        if S.source_ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(S.source_ob.data)
            bm.verts.ensure_lookup_table()
            if len(bm.verts) * 3 == len(vdata):
                for i, v in enumerate(bm.verts):
                    v.co.x = vdata[i*3]
                    v.co.y = vdata[i*3+1]
                    v.co.z = vdata[i*3+2]
                bmesh.update_edit_mesh(S.source_ob.data)

    def load_shape_to_engine(self, context):
        vdata = [0.0] * (self.n_verts * 3)
        self.get_shape(context).data.foreach_get('co', vdata)
        self.engine.from_list(vdata)

    def get_vert_co(self, context, index):
        if S.source_ob and S.source_ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(S.source_ob.data)
            bm.verts.ensure_lookup_table()
            if index < len(bm.verts):
                return bm.verts[index].co
        return self.get_shape(context).data[index].co

    def get_rest_vert_co(self, context, index):
        if S.source_ob and S.source_ob.data:
            shapes = getattr(S.source_ob.data, 'shape_keys', None)
            if shapes and hasattr(shapes, 'key_blocks') and len(shapes.key_blocks) > 0:
                key = shapes.key_blocks.get('Basis', shapes.key_blocks[0])
                if index < len(key.data):
                    return key.data[index].co.copy()
            elif hasattr(S.source_ob.data, 'vertices') and index < len(S.source_ob.data.vertices):
                return S.source_ob.data.vertices[index].co.copy()
        return self.get_vert_co(context, index)

    def get_vert_norm(self, context, index):
        if S.source_ob and S.source_ob.mode == 'EDIT':
            try:
                bm = bmesh.from_edit_mesh(S.source_ob.data)
                bm.verts.ensure_lookup_table()
                if index < len(bm.verts):
                    return bm.verts[index].normal.copy()
            except Exception:
                pass
        if S.source_ob and S.source_ob.data and hasattr(S.source_ob.data, 'vertices'):
            try:
                if index < len(S.source_ob.data.vertices):
                    return S.source_ob.data.vertices[index].normal.copy()
            except Exception:
                pass
        return Vector((0.0, 0.0, 1.0))

    def get_rest_vert_norm(self, context, index):
        if S.source_ob and S.source_ob.data and hasattr(S.source_ob.data, 'vertices'):
            try:
                if index < len(S.source_ob.data.vertices):
                    return S.source_ob.data.vertices[index].normal.copy()
            except Exception:
                pass
        return self.get_vert_norm(context, index)

    def reinit_engine(self, context):
        if S.source_ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(S.source_ob.data)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm_copy = bm.copy()
        else:
            S.source_ob.data.update()
            bm_copy = bmesh.new()
            bm_copy.from_mesh(S.source_ob.data)

        self.n_verts = len(bm_copy.verts)
        verts_coords = [0.0] * (self.n_verts * 3)
        for v in bm_copy.verts:
            verts_coords[v.index * 3 : v.index * 3 + 3] = v.co

        triangles = []
        for face in bm_copy.faces:
            for i in range(len(face.verts) - 2):
                triangles.append((face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index))

        self.engine = GPUSpringEngine(verts_coords, triangles, self.bvh)
        self.structural_springs = self.engine.create_spring_group(bm_copy, structural_springs_indexes(bm_copy))
        self.shear_springs = self.engine.create_spring_group(bm_copy, shear_spring_indexes(bm_copy))
        self.bending_springs = self.engine.create_spring_group(bm_copy, bending_spring_indexes(bm_copy, S.bending_distance))
        self.arranged_links = self.structural_springs.arranged_links
        self.symmetry_map = self.engine.create_symmetry_map(S)
        self.ternary_links = self.engine.create_ternary_links(bm_copy, ternary_links_indexes(bm_copy))
        self.quaternary_links = self.engine.create_quaternary_links(bm_copy, quaternary_link_indexes(bm_copy))
        bm_copy.free()

        self.snapping_mask_update(context)
        self.simulation_mask_update(context)

    def get_shape(self, context):
        sk = S.source_ob.data.shape_keys
        if sk and SW_SHAPE_KEY_NAME in sk.key_blocks:
            shape = sk.key_blocks[SW_SHAPE_KEY_NAME]
        else:
            if not sk or len(sk.key_blocks) == 0:
                S.source_ob.shape_key_add(name='Basis')
            shape = S.source_ob.shape_key_add(name=SW_SHAPE_KEY_NAME)
            shape.value = 1.0

        if sk and shape.name in sk.key_blocks:
            idx = sk.key_blocks.keys().index(shape.name)
            S.source_ob.active_shape_key_index = idx
        return shape

    error = None

    def modal(self, context, event):
        pass
        if self.error:
            print('operator runned twice')
            return {'FINISHED'}

        try:
            return self.modal_impl(context, event)
        except Exception as e:
            self.error = e
            self.stop(context)
            import traceback
            import os
            log_path = os.path.join(os.path.dirname(__file__), "operator_error.log")
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            except:
                pass
            raise e

    def raycast_traction_target(self, context, event, ref_pos=None):
        if hasattr(self, 'bvh') and self.bvh and S.source_ob:
            mat_inv = S.source_ob.matrix_world.inverted()
            origin, vec = get_mouse_ray(context, event, mat_inv)
            tgt_loc, tgt_norm, tgt_idx, tgt_dist = self.bvh.ray_cast(origin, vec)
            if tgt_loc is not None:
                return S.source_ob.matrix_world @ tgt_loc

        if S.source_ob:
            result, location, normal, index = mouse_raycast(S.source_ob, context, event)
            if result and location is not None:
                return S.source_ob.matrix_world @ location

        o, dir_vec = get_mouse_ray(context, event)
        plane_normal = context.space_data.region_3d.view_rotation @ Vector((0, 0, 1))
        target_ref = ref_pos if ref_pos else (S.source_ob.matrix_world.to_translation() if S.source_ob else Vector((0, 0, 0)))
        intersect_pt = intersect_line_plane(o, o + dir_vec, target_ref, plane_normal)
        return intersect_pt if intersect_pt else o + dir_vec * 2.0

    def pick_pause_pin(self, context, event, fixed_indices):
        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        rv3d = getattr(space, 'region_3d', None) if space else None
        if not region or not rv3d or not fixed_indices:
            return None

        from bpy_extras.view3d_utils import location_3d_to_region_2d
        m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        best_target = None
        min_d = 18.0
        mat = S.source_ob.matrix_world

        for idx in fixed_indices:
            orig_pos = mat @ self.get_vert_co(context, idx)
            p2d_orig = location_3d_to_region_2d(region, rv3d, orig_pos)
            d_orig = (p2d_orig - m_pos).length if p2d_orig else 1e9

            d_t = 1e9
            if hasattr(self, 'traction_pins') and idx in self.traction_pins:
                t_pos = self.traction_pins[idx]
                p2d_t = location_3d_to_region_2d(region, rv3d, t_pos)
                if p2d_t:
                    d_t = (p2d_t - m_pos).length

            if d_orig <= d_t:
                if d_orig < min_d:
                    min_d = d_orig
                    best_target = ('FIXED', idx)
            else:
                if d_t < min_d:
                    min_d = d_t
                    best_target = ('TRACTION', idx)

        return best_target

    def pick_mesh_vert(self, context, event):
        if not S.source_ob or not S.source_ob.data:
            return None

        result, location, normal, index = mouse_raycast(S.source_ob, context, event)
        if not result or location is None:
            if hasattr(self, 'bvh') and self.bvh:
                mat = S.source_ob.matrix_world.inverted()
                origin, vec = get_mouse_ray(context, event, mat)
                tgt_loc, tgt_norm, tgt_idx, tgt_dist = self.bvh.ray_cast(origin, vec)
                if tgt_loc is not None and tgt_idx is not None:
                    result = True
                    location = tgt_loc
                    index = tgt_idx

        if not result or location is None or index is None:
            return None

        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        rv3d = getattr(space, 'region_3d', None) if space else None
        m_pos = Vector((event.mouse_region_x, event.mouse_region_y)) if (region and rv3d) else None

        from bpy_extras.view3d_utils import location_3d_to_region_2d

        select_mode = (True, False, False)
        if context.scene and hasattr(context.scene, 'tool_settings'):
            select_mode = context.scene.tool_settings.mesh_select_mode

        is_edge_mode = select_mode[1]
        is_face_mode = select_mode[2]
        mat = S.source_ob.matrix_world

        def dist_to_segment_2d(p, a, b):
            ab = b - a
            ab_len_sq = ab.length_squared
            if ab_len_sq < 1e-6:
                return (p - a).length
            t = max(0.0, min(1.0, (p - a).dot(ab) / ab_len_sq))
            proj = a + ab * t
            return (p - proj).length

        if S.source_ob.mode == 'EDIT':
            try:
                bm = bmesh.from_edit_mesh(S.source_ob.data)
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                if index is not None and 0 <= index < len(bm.faces):
                    face = bm.faces[index]
                    if is_face_mode:
                        return [v.index for v in face.verts]
                    elif is_edge_mode:
                        best_edge = None
                        min_d = 1e9
                        for e in face.edges:
                            if m_pos and region and rv3d:
                                p1_2d = location_3d_to_region_2d(region, rv3d, mat @ e.verts[0].co)
                                p2_2d = location_3d_to_region_2d(region, rv3d, mat @ e.verts[1].co)
                                if p1_2d and p2_2d:
                                    d = dist_to_segment_2d(m_pos, p1_2d, p2_2d)
                                elif p1_2d:
                                    d = (m_pos - p1_2d).length
                                elif p2_2d:
                                    d = (m_pos - p2_2d).length
                                else:
                                    d = 1e9
                            else:
                                p1_3d = e.verts[0].co
                                p2_3d = e.verts[1].co
                                loc_local = location if isinstance(location, Vector) else Vector(location)
                                seg = p2_3d - p1_3d
                                l2 = seg.length_squared
                                t = max(0.0, min(1.0, (loc_local - p1_3d).dot(seg) / l2)) if l2 > 1e-6 else 0.0
                                d = (loc_local - (p1_3d + seg * t)).length

                            if d < min_d:
                                min_d = d
                                best_edge = e

                        if best_edge:
                            return [best_edge.verts[0].index, best_edge.verts[1].index]
                        return [v.index for v in face.verts[:2]]
                    else:
                        best_v = None
                        min_d = 1e9
                        for v in face.verts:
                            if m_pos and region and rv3d:
                                p2d = location_3d_to_region_2d(region, rv3d, mat @ v.co)
                                d = (p2d - m_pos).length if p2d else 1e9
                            else:
                                loc_local = location if isinstance(location, Vector) else Vector(location)
                                d = (v.co - loc_local).length
                            if d < min_d:
                                min_d = d
                                best_v = v

                        if best_v:
                            return [best_v.index]
                        return [face.verts[0].index]
            except Exception:
                pass
        else:
            try:
                mesh = S.source_ob.data
                if index is not None and 0 <= index < len(mesh.polygons):
                    poly = mesh.polygons[index]
                    if is_face_mode:
                        return list(poly.vertices)
                    elif is_edge_mode:
                        best_edge_pair = None
                        min_d = 1e9
                        n_v = len(poly.vertices)
                        for i in range(n_v):
                            v1_idx = poly.vertices[i]
                            v2_idx = poly.vertices[(i + 1) % n_v]
                            if m_pos and region and rv3d:
                                c1 = mat @ self.get_vert_co(context, v1_idx)
                                c2 = mat @ self.get_vert_co(context, v2_idx)
                                p1_2d = location_3d_to_region_2d(region, rv3d, c1)
                                p2_2d = location_3d_to_region_2d(region, rv3d, c2)
                                if p1_2d and p2_2d:
                                    d = dist_to_segment_2d(m_pos, p1_2d, p2_2d)
                                elif p1_2d:
                                    d = (m_pos - p1_2d).length
                                elif p2_2d:
                                    d = (m_pos - p2_2d).length
                                else:
                                    d = 1e9
                            else:
                                c1_3d = self.get_vert_co(context, v1_idx)
                                c2_3d = self.get_vert_co(context, v2_idx)
                                loc_local = location if isinstance(location, Vector) else Vector(location)
                                seg = c2_3d - c1_3d
                                l2 = seg.length_squared
                                t = max(0.0, min(1.0, (loc_local - c1_3d).dot(seg) / l2)) if l2 > 1e-6 else 0.0
                                d = (loc_local - (c1_3d + seg * t)).length

                            if d < min_d:
                                min_d = d
                                best_edge_pair = [v1_idx, v2_idx]

                        if best_edge_pair:
                            return best_edge_pair
                        return list(poly.vertices[:2])
                    else:
                        best_v_idx = None
                        min_d = 1e9
                        for v_idx in poly.vertices:
                            if m_pos and region and rv3d:
                                c = mat @ self.get_vert_co(context, v_idx)
                                p2d = location_3d_to_region_2d(region, rv3d, c)
                                d = (p2d - m_pos).length if p2d else 1e9
                            else:
                                loc_local = location if isinstance(location, Vector) else Vector(location)
                                c3d = self.get_vert_co(context, v_idx)
                                d = (c3d - loc_local).length

                            if d < min_d:
                                min_d = d
                                best_v_idx = v_idx

                        if best_v_idx is not None:
                            return [best_v_idx]
                        return [poly.vertices[0]]
            except Exception:
                pass

        return None

    def pick_target_neighbor(self, context, event, start_idx):
        if not hasattr(self, 'arranged_links') or start_idx >= len(self.arranged_links):
            return None

        nbrs = self.arranged_links[start_idx]
        if not nbrs:
            return None

        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        rv3d = getattr(space, 'region_3d', None) if space else None
        if not region or not rv3d or not S.source_ob:
            return nbrs[0]

        from bpy_extras.view3d_utils import location_3d_to_region_2d
        m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        mat = S.source_ob.matrix_world

        co_start_3d = mat @ self.get_vert_co(context, start_idx)
        p2d_start = location_3d_to_region_2d(region, rv3d, co_start_3d)
        if not p2d_start:
            return nbrs[0]

        best_nbr = None
        min_dist = 1e9

        for nbr in nbrs:
            co_nbr_3d = mat @ self.get_vert_co(context, nbr)
            p2d_nbr = location_3d_to_region_2d(region, rv3d, co_nbr_3d)
            if p2d_nbr:
                seg_vec = p2d_nbr - p2d_start
                seg_len_sq = seg_vec.length_squared
                if seg_len_sq > 1e-4:
                    t = max(0.0, min(1.0, (m_pos - p2d_start).dot(seg_vec) / seg_len_sq))
                    proj_pt = p2d_start + seg_vec * t
                    dist = (m_pos - proj_pt).length
                else:
                    dist = (m_pos - p2d_nbr).length

                if dist < min_dist:
                    min_dist = dist
                    best_nbr = nbr

        return best_nbr if best_nbr is not None else nbrs[0]

    def pick_closest_edge(self, context, event):
        if not S.source_ob or S.source_ob.mode != 'EDIT':
            return None

        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        rv3d = getattr(space, 'region_3d', None) if space else None
        if not region or not rv3d:
            return None

        from bpy_extras.view3d_utils import location_3d_to_region_2d
        m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        mat = S.source_ob.matrix_world

        try:
            bm = bmesh.from_edit_mesh(S.source_ob.data)
            bm.edges.ensure_lookup_table()
            best_edge_idx = None
            min_dist = 40.0

            for e in bm.edges:
                p1_3d = mat @ e.verts[0].co
                p2_3d = mat @ e.verts[1].co
                p1_2d = location_3d_to_region_2d(region, rv3d, p1_3d)
                p2_2d = location_3d_to_region_2d(region, rv3d, p2_2d)
                if p1_2d and p2_2d:
                    seg_vec = p2_2d - p1_2d
                    seg_len_sq = seg_vec.length_squared
                    if seg_len_sq > 1e-4:
                        t = max(0.0, min(1.0, (m_pos - p1_2d).dot(seg_vec) / seg_len_sq))
                        proj_pt = p1_2d + seg_vec * t
                        dist = (m_pos - proj_pt).length
                    else:
                        dist = (m_pos - p1_2d).length

                    if dist < min_dist:
                        min_dist = dist
                        best_edge_idx = e.index

            return best_edge_idx
        except Exception:
            return None

    def sync_bmesh_selection(self, context):
        if S.source_ob and S.source_ob.mode == 'EDIT':
            try:
                bm = bmesh.from_edit_mesh(S.source_ob.data)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

                pins = getattr(self, 'selected_pause_pins', set())

                for e in bm.edges:
                    e.select_set(False)
                for f in bm.faces:
                    f.select_set(False)
                for v in bm.verts:
                    v.select_set(v.index in pins)
                for e in bm.edges:
                    if e.verts[0].index in pins and e.verts[1].index in pins:
                        e.select_set(True)
                for f in bm.faces:
                    if all(v.index in pins for v in f.verts):
                        f.select_set(True)

                bmesh.update_edit_mesh(S.source_ob.data)
            except Exception:
                pass

    def load_traction_pins_from_ob(self):
        if not S.source_ob:
            return
        if not hasattr(self, 'traction_pins') or self.traction_pins is None:
            self.traction_pins = {}
        raw_trac = S.source_ob.get('sw_traction_pins', [])
        if raw_trac:
            for item in raw_trac:
                try:
                    if hasattr(item, '__getitem__') and 'vert_idx' in item and 'pos' in item:
                        v_idx = int(item['vert_idx'])
                        p = item['pos']
                        self.traction_pins[v_idx] = Vector((float(p[0]), float(p[1]), float(p[2])))
                except Exception:
                    pass

        if not hasattr(self, 'fixed_anchor_world_pos') or self.fixed_anchor_world_pos is None:
            self.fixed_anchor_world_pos = {}
        raw_anchors = S.source_ob.get('sw_fixed_anchors', [])
        if raw_anchors:
            for item in raw_anchors:
                try:
                    if hasattr(item, '__getitem__') and 'vert_idx' in item and 'pos' in item:
                        v_idx = int(item['vert_idx'])
                        p = item['pos']
                        self.fixed_anchor_world_pos[v_idx] = Vector((float(p[0]), float(p[1]), float(p[2])))
                except Exception:
                    pass

    def save_traction_pins_to_ob(self):
        if not S.source_ob:
            return
        trac_data = []
        if hasattr(self, 'traction_pins') and self.traction_pins:
            for idx, pos in self.traction_pins.items():
                trac_data.append({'vert_idx': int(idx), 'pos': [float(pos.x), float(pos.y), float(pos.z)]})
        S.source_ob['sw_traction_pins'] = trac_data

        anchor_data = []
        if hasattr(self, 'fixed_anchor_world_pos') and self.fixed_anchor_world_pos:
            for idx, pos in self.fixed_anchor_world_pos.items():
                anchor_data.append({'vert_idx': int(idx), 'pos': [float(pos.x), float(pos.y), float(pos.z)]})
        S.source_ob['sw_fixed_anchors'] = anchor_data

    def get_pin_state_snapshot(self):
        snapshot = {
            'traction_pins': {k: v.copy() for k, v in getattr(self, 'traction_pins', {}).items()} if hasattr(self, 'traction_pins') else {},
            'sw_pins': list(S.source_ob.get('sw_pins', [])) if (S.source_ob and 'sw_pins' in S.source_ob) else [],
            'fixed_anchor_world_pos': {k: v.copy() for k, v in getattr(self, 'fixed_anchor_world_pos', {}).items()} if hasattr(self, 'fixed_anchor_world_pos') else {},
            'selected_pause_pins': set(getattr(self, 'selected_pause_pins', set())),
            'selected_traction_pins': set(getattr(self, 'selected_traction_pins', set())),
        }
        return snapshot

    def push_pin_undo_snapshot(self, before_snapshot):
        if not hasattr(self, 'traction_undo_stack'):
            self.traction_undo_stack = []
        self.traction_undo_stack.append(before_snapshot)
        self.traction_redo_stack = []
        self.save_traction_pins_to_ob()

    def restore_pin_state_snapshot(self, snapshot, context=None):
        if not snapshot or not isinstance(snapshot, dict):
            return
        if 'traction_pins' in snapshot:
            self.traction_pins = {k: v.copy() for k, v in snapshot['traction_pins'].items()}
        else:
            self.traction_pins = {k: v.copy() for k, v in snapshot.items() if isinstance(v, Vector)}

        if 'sw_pins' in snapshot and S.source_ob:
            S.source_ob['sw_pins'] = list(snapshot['sw_pins'])
        if 'fixed_anchor_world_pos' in snapshot:
            self.fixed_anchor_world_pos = {k: v.copy() for k, v in snapshot['fixed_anchor_world_pos'].items()}
        if 'selected_pause_pins' in snapshot:
            self.selected_pause_pins = set(snapshot['selected_pause_pins'])
        if 'selected_traction_pins' in snapshot:
            self.selected_traction_pins = set(snapshot['selected_traction_pins'])
        self.sync_bmesh_selection(context)
        self.pin_cache_update(context, None)
        self.save_traction_pins_to_ob()

    def snap_point_to_bvh(self, context, world_pos):
        if (not hasattr(self, 'bvh') or not self.bvh) and S.target_ob and S.source_ob:
            try:
                tbm = bmesh.new()
                tbm.from_mesh(S.target_ob.data)
                bmesh.ops.transform(tbm, matrix=S.target_ob.matrix_world, space=Matrix.Identity(4), verts=tbm.verts)
                bmesh.ops.transform(tbm, matrix=S.source_ob.matrix_world.inverted(), space=Matrix.Identity(4), verts=tbm.verts)
                tbm.normal_update()
                self.bvh = BVHTree.FromBMesh(tbm)
                tbm.free()
            except Exception:
                pass

        if hasattr(self, 'bvh') and self.bvh and S.source_ob:
            mat_inv = S.source_ob.matrix_world.inverted()
            local_p = mat_inv @ world_pos
            nearest = self.bvh.find_nearest(local_p)
            if nearest and nearest[0] is not None:
                return S.source_ob.matrix_world @ nearest[0]
        return world_pos

    def apply_smooth_brush(self, context, mouse_x, mouse_y):
        if not S.source_ob or not hasattr(self, 'arranged_links'):
            return

        region = getattr(context, 'region', None)
        space = getattr(context, 'space_data', None)
        rv3d = getattr(space, 'region_3d', None) if space else None
        if not region or not rv3d:
            return

        from bpy_extras.view3d_utils import location_3d_to_region_2d
        m_pos = Vector((mouse_x, mouse_y))

        raw_pins = S.source_ob.get('sw_pins', ())
        fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]
        if not fixed_indices:
            return
        fixed_set = set(fixed_indices)

        if not hasattr(self, 'traction_pins'):
            self.traction_pins = {}

        mat = S.source_ob.matrix_world
        brush_ring_count = max(int(S.mouse_grab_size), 1)

        center_pin_res = self.pick_pause_pin(context, type('DummyEvent', (), {'mouse_region_x': mouse_x, 'mouse_region_y': mouse_y})(), fixed_indices)
        center_pin = center_pin_res[1] if isinstance(center_pin_res, (list, tuple)) and len(center_pin_res) >= 2 else center_pin_res

        pins_to_smooth = {}
        if center_pin is not None and isinstance(center_pin, int):
            affected_rings = get_fixed_pin_rings(self.arranged_links, fixed_set, [center_pin], max_steps=brush_ring_count)
            r_screen = brush_ring_count * 25.0

            def get_pos(v_idx):
                if v_idx in self.traction_pins:
                    return self.traction_pins[v_idx].copy()
                return (mat @ self.get_vert_co(context, v_idx)).copy()

            for v_idx, step in affected_rings.items():
                v_pos = get_pos(v_idx)
                p2d = location_3d_to_region_2d(region, rv3d, v_pos)
                if p2d:
                    dist_2d = (p2d - m_pos).length
                    if dist_2d <= r_screen * 1.5:
                        weight_top = max(1.0 - (step / (brush_ring_count + 1)), 0.1)
                        weight_dist = max(1.0 - (dist_2d / (r_screen * 1.5)), 0.1)
                        pins_to_smooth[v_idx] = weight_top * weight_dist
        else:
            r_screen = brush_ring_count * 20.0
            for idx in fixed_indices:
                v_pos = self.traction_pins[idx] if idx in self.traction_pins else (mat @ self.get_vert_co(context, idx))
                p2d = location_3d_to_region_2d(region, rv3d, v_pos)
                if p2d:
                    dist_2d = (p2d - m_pos).length
                    if dist_2d <= r_screen:
                        weight_dist = max(1.0 - (dist_2d / r_screen), 0.1)
                        pins_to_smooth[idx] = weight_dist

        # 在暂停模式下，被显式选中的固定点/牵引点 (locked_pins) 处于锁定状态，不受平滑笔刷的影响 (作为固定锚点)
        sel_pause = set(getattr(self, 'selected_pause_pins', set()))
        sel_trac = set(getattr(self, 'selected_traction_pins', set()))
        g_grab_fixed = set(getattr(self, 'g_grab_fixed_pins', []))
        g_grab_trac = set(getattr(self, 'g_grab_traction_pins', []))
        locked_pins = sel_pause | sel_trac | g_grab_fixed | g_grab_trac

        alpha = 0.4
        new_positions = {}

        def get_current_pos(v_idx):
            if v_idx in self.traction_pins:
                return self.traction_pins[v_idx].copy()
            return (mat @ self.get_vert_co(context, v_idx)).copy()

        def compute_straightened_position(v_idx):
            curr_p = get_current_pos(v_idx)
            if not hasattr(self, 'arranged_links') or not self.arranged_links or v_idx >= len(self.arranged_links):
                return curr_p

            nbrs_1 = [n for n in self.arranged_links[v_idx] if n in fixed_set]
            if nbrs_1:
                fixed_nbrs = nbrs_1
            else:
                nbrs_2 = []
                for n in self.arranged_links[v_idx]:
                    if n < len(self.arranged_links):
                        for nn in self.arranged_links[n]:
                            if nn != v_idx and nn in fixed_set and nn not in nbrs_2:
                                nbrs_2.append(nn)
                fixed_nbrs = nbrs_2

            if not fixed_nbrs:
                return curr_p

            if len(fixed_nbrs) == 2:
                n1, n2 = fixed_nbrs[0], fixed_nbrs[1]
                p1, p2 = get_current_pos(n1), get_current_pos(n2)
                M = (p1 + p2) * 0.5
                H = curr_p - M
                target = M + H * 0.75

                # 间距与切线平滑：防止与锁定点 (locked_pins) 远离或产生尖角折断
                d1 = (curr_p - p1).length
                d2 = (curr_p - p2).length
                d_avg = (d1 + d2) * 0.5

                if n1 in locked_pins and d1 > 1e-6:
                    dir1 = (target - p1)
                    if dir1.length > 1e-6:
                        target = p1 + dir1.normalized() * (d1 * 0.3 + d_avg * 0.7)
                elif n2 in locked_pins and d2 > 1e-6:
                    dir2 = (target - p2)
                    if dir2.length > 1e-6:
                        target = p2 + dir2.normalized() * (d2 * 0.3 + d_avg * 0.7)

                return target

            elif len(fixed_nbrs) == 1:
                n1 = fixed_nbrs[0]
                p1 = get_current_pos(n1)
                n1_nbrs = [n for n in self.arranged_links[n1] if n in fixed_set and n != v_idx] if n1 < len(self.arranged_links) else []
                if n1_nbrs:
                    p2 = get_current_pos(n1_nbrs[0])
                    target_dir = (p1 - p2)
                    if target_dir.length > 1e-6:
                        d0 = (curr_p - p1).length
                        return p1 + target_dir.normalized() * d0
                    return p1 * 2.0 - p2
                else:
                    return p1
            else:
                best_pair = None
                best_dot = 1.0
                for i in range(len(fixed_nbrs)):
                    for j in range(i + 1, len(fixed_nbrs)):
                        n_i, n_j = fixed_nbrs[i], fixed_nbrs[j]
                        v_i = get_current_pos(n_i) - curr_p
                        v_j = get_current_pos(n_j) - curr_p
                        len_i, len_j = v_i.length, v_j.length
                        if len_i > 1e-6 and len_j > 1e-6:
                            dot = (v_i / len_i).dot(v_j / len_j)
                            if dot < best_dot:
                                best_dot = dot
                                best_pair = (n_i, n_j)
                if best_pair and best_dot < 0.0:
                    n1, n2 = best_pair[0], best_pair[1]
                    p1, p2 = get_current_pos(n1), get_current_pos(n2)
                    M = (p1 + p2) * 0.5
                    H = curr_p - M
                    target = M + H * 0.75
                    d1 = (curr_p - p1).length
                    d2 = (curr_p - p2).length
                    d_avg = (d1 + d2) * 0.5
                    if n1 in locked_pins and d1 > 1e-6:
                        dir1 = (target - p1)
                        if dir1.length > 1e-6:
                            target = p1 + dir1.normalized() * (d1 * 0.3 + d_avg * 0.7)
                    elif n2 in locked_pins and d2 > 1e-6:
                        dir2 = (target - p2)
                        if dir2.length > 1e-6:
                            target = p2 + dir2.normalized() * (d2 * 0.3 + d_avg * 0.7)
                    return target
                else:
                    avg_p = Vector((0.0, 0.0, 0.0))
                    for n in fixed_nbrs:
                        avg_p += get_current_pos(n)
                    return avg_p / len(fixed_nbrs)

        for idx, w in pins_to_smooth.items():
            if idx in locked_pins:
                continue  # 选中点处于锁定状态，不受平滑笔刷的影响

            curr_p = get_current_pos(idx)
            target_straight_p = compute_straightened_position(idx)

            eff_alpha = min(alpha * w, 0.8)
            smoothed_p = curr_p * (1.0 - eff_alpha) + target_straight_p * eff_alpha
            snapped_p = self.snap_point_to_bvh(context, smoothed_p)
            new_positions[idx] = snapped_p

        for idx, p_new in new_positions.items():
            self.traction_pins[idx] = p_new

        if context.area:
            context.area.tag_redraw()

    def on_enter_pause(self, context):
        self.load_traction_pins_from_ob()

    def on_exit_pause(self, context):
        # 退出暂停模式时保持源网格当前原始状态，不强制将网格顶点拉伸变形至牵引点位置
        self.save_traction_pins_to_ob()

    def handle_pause_pin_movement(self, context, event):
        pass

    def stop(self, context):
        if hasattr(self, 'on_exit_pause'):
            try:
                self.on_exit_pause(context)
            except Exception:
                pass

        if hasattr(self, 'target_ob_ref') and self.target_ob_ref:
            try:
                if self.target_ob_ref.name in bpy.data.objects:
                    self.target_ob_ref.hide_select = False
            except Exception:
                pass
            self.target_ob_ref = None

        if hasattr(self, 'draw3d_outer') and self.draw3d_outer:
            try:
                self.draw3d_outer.remove_handler()
            except Exception:
                pass
            self.draw3d_outer = None

        if hasattr(self, 'draw3d') and self.draw3d:
            try:
                self.draw3d.remove_handler()
            except Exception:
                pass
            self.draw3d = None
        try:
            bpy.context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        pass
        if state.running_op and hasattr(state.running_op, 'save_traction_pins_to_ob'):
            state.running_op.save_traction_pins_to_ob()
        state.running_op = None

    def modal_impl(self, context, event):
        pass

        if not state.running_op or not S.source_ob:
            self.stop(context)
            return {'FINISHED'}

        if not getattr(self, '_initialized_trac_pins', False):
            self._initialized_trac_pins = True
            self.load_traction_pins_from_ob()

        # 检测 暂停 (Pause) 状态切换
        current_pause = S.pause
        prev_pause = getattr(self, 'prev_pause', False)
        if current_pause and not prev_pause:
            self.on_enter_pause(context)
        elif not current_pause and prev_pause:
            self.on_exit_pause(context)
        self.prev_pause = current_pause

        if event.type == 'ESC' and not getattr(self, 'is_transforming', False):
            self.stop(context)
            return {'FINISHED'}

        # 暂停模式下通过 G 键移动牵引点
        if S.pause and getattr(self, 'is_g_grab_traction', False):
            if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                before_snap = getattr(self, 'g_grab_before_snapshot', None)
                if before_snap:
                    self.push_pin_undo_snapshot(before_snap)

                self.is_g_grab_traction = False
                self.g_grab_pins = []
                self.g_grab_fixed_pins = []
                self.g_grab_traction_pins = []
                self.g_grab_backup = {}
                self.g_grab_before_snapshot = None
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
                if hasattr(self, 'g_grab_backup'):
                    for idx, prev_pos in self.g_grab_backup.items():
                        if prev_pos is None:
                            self.traction_pins.pop(idx, None)
                        else:
                            self.traction_pins[idx] = prev_pos
                self.is_g_grab_traction = False
                self.g_grab_pins = []
                self.g_grab_fixed_pins = []
                self.g_grab_traction_pins = []
                self.g_grab_backup = {}
                self.g_grab_before_snapshot = {}
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            elif event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER'}:
                c0 = getattr(self, 'g_grab_initial_centroid', Vector((0.0, 0.0, 0.0)))
                mode = getattr(self, 'g_transform_mode', 'TRANSLATE')
                initial_positions = getattr(self, 'g_grab_initial_positions', {})
                affected_map = getattr(self, 'g_grab_affected_map', {})

                if mode == 'SCALE':
                    start_2d = getattr(self, 'g_transform_mouse_start', Vector((event.mouse_region_x, event.mouse_region_y)))
                    center_2d = getattr(self, 'g_transform_screen_centroid', start_2d)
                    curr_2d = Vector((event.mouse_region_x, event.mouse_region_y))

                    d_start = (start_2d - center_2d).length
                    d_curr = (curr_2d - center_2d).length

                    if d_start > 15.0:
                        scale_fac = max(d_curr / d_start, 0.05)
                    else:
                        scale_fac = max(1.0 + (d_curr - d_start) / 100.0, 0.05)

                    grab_pins = getattr(self, 'g_grab_pins', [])
                    is_group = len(grab_pins) > 1

                    for idx, step in affected_map.items():
                        if idx in initial_positions:
                            weight = get_step_weight(step)
                            eff_scale = 1.0 + (scale_fac - 1.0) * weight
                            raw_pos = c0 + (initial_positions[idx] - c0) * eff_scale
                            if is_group:
                                self.traction_pins[idx] = raw_pos
                            else:
                                self.traction_pins[idx] = self.snap_point_to_bvh(context, raw_pos)

                elif mode == 'ROTATE':
                    start_2d = getattr(self, 'g_transform_mouse_start', Vector((event.mouse_region_x, event.mouse_region_y)))
                    center_2d = getattr(self, 'g_transform_screen_centroid', start_2d)
                    curr_2d = Vector((event.mouse_region_x, event.mouse_region_y))

                    v0 = start_2d - center_2d
                    v1 = curr_2d - center_2d

                    if v0.length_squared < 1e-4 or v1.length_squared < 1e-4:
                        angle_diff = 0.0
                    else:
                        angle_diff = atan2(v1.y, v1.x) - atan2(v0.y, v0.x)

                    rv3d = context.space_data.region_3d if (context.space_data and hasattr(context.space_data, 'region_3d')) else None
                    if rv3d and hasattr(rv3d, 'view_matrix'):
                        rot_axis = (rv3d.view_matrix.to_3x3().inverted() @ Vector((0, 0, 1))).normalized()
                    else:
                        rot_axis = Vector((0, 0, 1))

                    grab_pins = getattr(self, 'g_grab_pins', [])
                    is_group = len(grab_pins) > 1

                    for idx, step in affected_map.items():
                        if idx in initial_positions:
                            weight = get_step_weight(step)
                            eff_angle = angle_diff * weight
                            rot_mat = Matrix.Rotation(eff_angle, 3, rot_axis)
                            raw_pos = c0 + rot_mat @ (initial_positions[idx] - c0)
                            if is_group:
                                self.traction_pins[idx] = raw_pos
                            else:
                                self.traction_pins[idx] = self.snap_point_to_bvh(context, raw_pos)

                else: # TRANSLATE
                    new_target = self.raycast_traction_target(context, event, ref_pos=c0)
                    grab_pins = getattr(self, 'g_grab_pins', [])
                    if len(grab_pins) > 1:
                        # 整体移动多个牵引点：采用群组刚体贴合，保持原本形成的形状与点间距不变
                        snapped_centroid = self.snap_point_to_bvh(context, new_target)
                        delta_group = snapped_centroid - c0
                        for idx, step in affected_map.items():
                            if idx in initial_positions:
                                weight = get_step_weight(step)
                                self.traction_pins[idx] = initial_positions[idx] + (delta_group * weight)
                    else:
                        # 单点移动：独立表面吸附
                        delta = new_target - c0
                        for idx, step in affected_map.items():
                            if idx in initial_positions:
                                weight = get_step_weight(step)
                                raw_pos = initial_positions[idx] + (delta * weight)
                                snapped_pos = self.snap_point_to_bvh(context, raw_pos)
                                self.traction_pins[idx] = snapped_pos

                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下对控制点 (Pins) 的 撤销 (Undo: Ctrl+Z) 与 重做 (Redo: Ctrl+Y / Ctrl+Shift+Z) 处理
        is_undo = (event.type == 'Z' and event.value == 'PRESS' and (event.ctrl or event.oskey) and not event.shift)
        is_redo = ((event.type == 'Z' and event.value == 'PRESS' and (event.ctrl or event.oskey) and event.shift) or (event.type == 'Y' and event.value == 'PRESS' and (event.ctrl or event.oskey)))

        if S.pause and is_undo:
            if getattr(self, 'is_g_grab_traction', False):
                if hasattr(self, 'g_grab_backup'):
                    for idx, prev_pos in self.g_grab_backup.items():
                        if prev_pos is None:
                            self.traction_pins.pop(idx, None)
                        else:
                            self.traction_pins[idx] = prev_pos
                self.is_g_grab_traction = False
                self.g_grab_pins = []
                self.g_grab_fixed_pins = []
                self.g_grab_traction_pins = []
                self.g_grab_backup = {}
                self.g_grab_before_snapshot = {}
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            elif hasattr(self, 'traction_undo_stack') and self.traction_undo_stack:
                current_state = self.get_pin_state_snapshot()
                if not hasattr(self, 'traction_redo_stack'):
                    self.traction_redo_stack = []
                self.traction_redo_stack.append(current_state)

                prev_state = self.traction_undo_stack.pop()
                self.restore_pin_state_snapshot(prev_state, context)
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        if S.pause and is_redo:
            if hasattr(self, 'traction_redo_stack') and self.traction_redo_stack:
                current_state = self.get_pin_state_snapshot()
                if not hasattr(self, 'traction_undo_stack'):
                    self.traction_undo_stack = []
                self.traction_undo_stack.append(current_state)

                next_state = self.traction_redo_stack.pop()
                self.restore_pin_state_snapshot(next_state, context)
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下的 2D 框选 (Box Select / Border Select) 实时交互处理
        if S.pause and getattr(self, 'is_box_selecting', False):
            m_pos = Vector((event.mouse_region_x, event.mouse_region_y))

            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    self.box_start = m_pos
                    self.box_current = m_pos
                    self.box_dragged = False
                    self.draw_pins(context, event)
                    if context.area:
                        context.area.tag_redraw()
                    return {'RUNNING_MODAL'}

                elif event.value == 'RELEASE':
                    if getattr(self, 'box_start', None) is not None and getattr(self, 'box_current', None) is not None:
                        b_min_x = min(self.box_start.x, self.box_current.x)
                        b_max_x = max(self.box_start.x, self.box_current.x)
                        b_min_y = min(self.box_start.y, self.box_current.y)
                        b_max_y = max(self.box_start.y, self.box_current.y)

                        if getattr(self, 'box_dragged', False) and ((b_max_x - b_min_x > 8) or (b_max_y - b_min_y > 8)):
                            raw_pins = S.source_ob.get('sw_pins', ()) if S.source_ob else ()
                            fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

                            region = getattr(context, 'region', None)
                            space = getattr(context, 'space_data', None)
                            rv3d = getattr(space, 'region_3d', None) if space else None
                            if region and rv3d:
                                from bpy_extras.view3d_utils import location_3d_to_region_2d
                                mat = S.source_ob.matrix_world
                                mat_rot = mat.to_3x3()
                                boxed_fixed = set()
                                boxed_traction = set()

                                shading = getattr(space, 'shading', None)
                                is_xray = bool(shading and (getattr(shading, 'show_xray', False) or getattr(shading, 'type', '') == 'WIREFRAME'))

                                is_perspective = rv3d.is_perspective
                                cam_pos = rv3d.view_matrix.inverted().translation
                                view_dir_ortho = -(rv3d.view_rotation @ Vector((0, 0, 1))).normalized()

                                bvh = None
                                created_bm_bvh = None
                                if not is_xray and S.source_ob:
                                    if S.source_ob.mode == 'EDIT':
                                        try:
                                            bm_bvh = bmesh.from_edit_mesh(S.source_ob.data)
                                            bm_bvh.faces.ensure_lookup_table()
                                            bvh = BVHTree.FromBMesh(bm_bvh)
                                        except Exception:
                                            pass
                                    elif S.source_ob.data:
                                        try:
                                            created_bm_bvh = bmesh.new()
                                            created_bm_bvh.from_mesh(S.source_ob.data)
                                            created_bm_bvh.verts.ensure_lookup_table()
                                            for v in created_bm_bvh.verts:
                                                v.co = self.get_vert_co(context, v.index)
                                            created_bm_bvh.faces.ensure_lookup_table()
                                            bvh = BVHTree.FromBMesh(created_bm_bvh)
                                        except Exception:
                                            pass

                                def is_v_visible(pos_3d, v_norm_world):
                                    if is_perspective:
                                        to_cam = cam_pos - pos_3d
                                        dist_to_cam = to_cam.length
                                        if dist_to_cam < 1e-6:
                                            return True
                                        v_dir = -to_cam / dist_to_cam
                                    else:
                                        v_dir = view_dir_ortho
                                        dist_to_cam = 1000.0

                                    if v_norm_world.length_squared > 1e-8:
                                        if v_norm_world.dot(-v_dir) <= 0.0:
                                            return False

                                    if bvh:
                                        if is_perspective:
                                            r_orig = cam_pos + v_dir * 1e-3
                                            r_dir = v_dir
                                            t_dist = dist_to_cam - 2e-3
                                        else:
                                            r_orig = pos_3d - v_dir * 1000.0
                                            r_dir = v_dir
                                            t_dist = 1000.0 - 2e-3

                                        if t_dist > 1e-4:
                                            hit_loc, hit_n, hit_i, hit_d = bvh.ray_cast(r_orig, r_dir)
                                            if hit_loc is not None and hit_d < t_dist:
                                                return False

                                    return True

                                if S.source_ob and S.source_ob.mode == 'EDIT':
                                    try:
                                        bm = bmesh.from_edit_mesh(S.source_ob.data)
                                        bm.verts.ensure_lookup_table()
                                        for v in bm.verts:
                                            idx = v.index
                                            orig_pos = mat @ v.co
                                            p2d_orig = location_3d_to_region_2d(region, rv3d, orig_pos)
                                            if p2d_orig and (b_min_x <= p2d_orig.x <= b_max_x and b_min_y <= p2d_orig.y <= b_max_y):
                                                if is_xray or is_v_visible(orig_pos, (mat_rot @ v.normal).normalized()):
                                                    boxed_fixed.add(idx)

                                            if hasattr(self, 'traction_pins') and idx in self.traction_pins:
                                                t_pos = self.traction_pins[idx]
                                                p2d_t = location_3d_to_region_2d(region, rv3d, t_pos)
                                                if p2d_t and (b_min_x <= p2d_t.x <= b_max_x and b_min_y <= p2d_t.y <= b_max_y):
                                                    if is_xray or is_v_visible(t_pos, (mat_rot @ v.normal).normalized()):
                                                        boxed_traction.add(idx)
                                    except Exception:
                                        pass
                                elif S.source_ob and hasattr(S.source_ob.data, 'vertices'):
                                    for idx, v in enumerate(S.source_ob.data.vertices):
                                        orig_pos = mat @ self.get_vert_co(context, idx)
                                        p2d_orig = location_3d_to_region_2d(region, rv3d, orig_pos)
                                        if p2d_orig and (b_min_x <= p2d_orig.x <= b_max_x and b_min_y <= p2d_orig.y <= b_max_y):
                                            if is_xray or is_v_visible(orig_pos, (mat_rot @ v.normal).normalized()):
                                                boxed_fixed.add(idx)

                                        if hasattr(self, 'traction_pins') and idx in self.traction_pins:
                                            t_pos = self.traction_pins[idx]
                                            p2d_t = location_3d_to_region_2d(region, rv3d, t_pos)
                                            if p2d_t and (b_min_x <= p2d_t.x <= b_max_x and b_min_y <= p2d_t.y <= b_max_y):
                                                if is_xray or is_v_visible(t_pos, (mat_rot @ v.normal).normalized()):
                                                    boxed_traction.add(idx)

                                if created_bm_bvh:
                                    created_bm_bvh.free()

                                if not hasattr(self, 'selected_pause_pins'):
                                    self.selected_pause_pins = set()
                                if not hasattr(self, 'selected_traction_pins'):
                                    self.selected_traction_pins = set()

                                before_snap = self.get_pin_state_snapshot()
                                prev_sel_pause = set(self.selected_pause_pins)
                                prev_sel_trac = set(self.selected_traction_pins)

                                if event.shift:
                                    self.selected_pause_pins |= boxed_fixed
                                    self.selected_traction_pins |= boxed_traction
                                else:
                                    self.selected_pause_pins = boxed_fixed
                                    self.selected_traction_pins = boxed_traction

                                if prev_sel_pause != self.selected_pause_pins or prev_sel_trac != self.selected_traction_pins:
                                    self.push_pin_undo_snapshot(before_snap)

                                self.sync_bmesh_selection(context)
                        else:
                            # 单击未产生拖拽 (Click without Drag): 执行标准的点选/Shift加选/空白取消
                            picked_target = getattr(self, 'pending_click_pick', None)
                            is_shift = getattr(self, 'pending_click_shift', False)
                            if not hasattr(self, 'selected_pause_pins'):
                                self.selected_pause_pins = set()
                            if not hasattr(self, 'selected_traction_pins'):
                                self.selected_traction_pins = set()

                            before_snap = self.get_pin_state_snapshot()
                            prev_sel_pause = set(self.selected_pause_pins)
                            prev_sel_trac = set(self.selected_traction_pins)

                            if picked_target is not None:
                                if isinstance(picked_target, tuple):
                                    p_type, picked_val = picked_target
                                else:
                                    p_type, picked_val = 'FIXED', picked_target

                                if isinstance(picked_val, (set, list, tuple)):
                                    picked_set = set(picked_val)
                                else:
                                    picked_set = {picked_val}

                                if is_shift:
                                    if p_type == 'TRACTION':
                                        if picked_set.issubset(self.selected_traction_pins):
                                            self.selected_traction_pins -= picked_set
                                        else:
                                            self.selected_traction_pins |= picked_set
                                    else:
                                        if picked_set.issubset(self.selected_pause_pins):
                                            self.selected_pause_pins -= picked_set
                                        else:
                                            self.selected_pause_pins |= picked_set
                                else:
                                    if p_type == 'TRACTION':
                                        self.selected_traction_pins = set(picked_set)
                                        self.selected_pause_pins = set()
                                    else:
                                        self.selected_pause_pins = set(picked_set)
                                        self.selected_traction_pins = set()
                            else:
                                if not is_shift:
                                    self.selected_pause_pins = set()
                                    self.selected_traction_pins = set()
                                    self.g_grab_pins = []
                                    self.g_grab_fixed_pins = []
                                    self.g_grab_traction_pins = []

                            if prev_sel_pause != self.selected_pause_pins or prev_sel_trac != self.selected_traction_pins:
                                self.push_pin_undo_snapshot(before_snap)

                            self.sync_bmesh_selection(context)

                    self.is_box_selecting = False
                    self.box_dragged = False
                    self.box_start = None
                    self.box_current = None
                    self.pending_click_pick = None
                    self.draw_pins(context, event)
                    if context.area:
                        context.area.tag_redraw()
                    return {'RUNNING_MODAL'}

            elif event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                if getattr(self, 'box_start', None) is not None:
                    dist = (m_pos - self.box_start).length
                    if dist > 8.0:
                        self.box_dragged = True
                    self.box_current = m_pos
                    self.draw_pins(context, event)
                    if context.area:
                        context.area.tag_redraw()
                    return {'RUNNING_MODAL'}

            elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
                self.is_box_selecting = False
                self.box_dragged = False
                self.box_start = None
                self.box_current = None
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下的 Shift + 鼠标滚轮 及 [ / ] 方括号快捷键动态调整笔刷尺寸 (Shift + Wheel / Bracket keys resize brush)
        if S.pause:
            is_bracket_press = event.type in {'LEFT_BRACKET', 'RIGHT_BRACKET'} and event.value == 'PRESS'
            is_wheel_shift = event.shift and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
            if is_bracket_press or is_wheel_shift:
                if event.type in {'WHEELUPMOUSE', 'RIGHT_BRACKET'}:
                    S.mouse_grab_size = min(50, S.mouse_grab_size + 1)
                elif event.type in {'WHEELDOWNMOUSE', 'LEFT_BRACKET'}:
                    S.mouse_grab_size = max(1, S.mouse_grab_size - 1)

                self.report({'INFO'}, f"笔刷抓取尺寸: {S.mouse_grab_size}")
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下 Ctrl + 单击鼠标滚轮键/中键 (Ctrl + MIDDLEMOUSE PRESS) 切换固定/取消固定所选点 (Toggle Pin)
        if S.pause and event.type == 'MIDDLEMOUSE' and event.value == 'PRESS' and event.ctrl:
            raw_pins = S.source_ob.get('sw_pins', ()) if S.source_ob else ()
            fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

            sel_pause = set(getattr(self, 'selected_pause_pins', set()))
            sel_trac = set(getattr(self, 'selected_traction_pins', set()))
            selected_verts = sel_pause | sel_trac

            target_verts = set()
            if selected_verts:
                target_verts = selected_verts
            else:
                picked_target = self.pick_pause_pin(context, event, fixed_indices) if fixed_indices else None
                if picked_target is not None:
                    p_type, picked_val = picked_target if isinstance(picked_target, tuple) else ('FIXED', picked_target)
                    if isinstance(picked_val, (set, list, tuple)):
                        target_verts = set(picked_val)
                    elif isinstance(picked_val, int):
                        target_verts = {picked_val}
                else:
                    mesh_verts = self.pick_mesh_vert(context, event)
                    if mesh_verts:
                        target_verts = set(mesh_verts)

            if target_verts:
                pins_set = set(fixed_indices)
                mat = S.source_ob.matrix_world if S.source_ob else Matrix.Identity(4)
                before_snap = self.get_pin_state_snapshot()

                # 若目标控制点都已经固定，则全部取消固定；否则全部设为固定点
                if target_verts.issubset(pins_set):
                    pins_set -= target_verts
                    for v_idx in target_verts:
                        if hasattr(self, 'traction_pins'):
                            self.traction_pins.pop(v_idx, None)
                        if hasattr(self, 'fixed_anchor_world_pos'):
                            self.fixed_anchor_world_pos.pop(v_idx, None)
                        if hasattr(self, 'selected_pause_pins'):
                            self.selected_pause_pins.discard(v_idx)
                        if hasattr(self, 'selected_traction_pins'):
                            self.selected_traction_pins.discard(v_idx)
                    self.report({'INFO'}, f"已取消固定 {len(target_verts)} 个控制点")
                else:
                    pins_set |= target_verts
                    for v_idx in target_verts:
                        if hasattr(self, 'traction_pins') and v_idx in self.traction_pins:
                            wpos = self.traction_pins[v_idx].copy()
                        else:
                            wpos = mat @ self.get_vert_co(context, v_idx)
                        if not hasattr(self, 'fixed_anchor_world_pos'):
                            self.fixed_anchor_world_pos = {}
                        self.fixed_anchor_world_pos[v_idx] = wpos
                        if hasattr(self, 'selected_pause_pins'):
                            self.selected_pause_pins.add(v_idx)
                    self.report({'INFO'}, f"已固定 {len(target_verts)} 个控制点")

                S.source_ob['sw_pins'] = list(pins_set)
                self.pin_cache_update(context, event)
                self.push_pin_undo_snapshot(before_snap)
                bpy.ops.ed.undo_push(message='Toggle Pin (Ctrl+Middle Click)')
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下的 B 键框选快捷键 (B Key Box Select)
        if S.pause and event.type == 'B' and event.value == 'PRESS' and not getattr(self, 'is_g_grab_traction', False):
            self.is_box_selecting = True
            self.box_start = None
            self.box_current = None
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # 暂停模式下同时按住 Ctrl + Shift 键自动激活“平滑牵引点”UI高亮变蓝
        if S.pause:
            is_ctrl_shift_down = bool((getattr(event, 'ctrl', False) or (event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value != 'RELEASE')) and (getattr(event, 'shift', False) or (event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value != 'RELEASE')))
            if is_ctrl_shift_down:
                if not S.use_smooth_brush:
                    S.use_smooth_brush = True
                    self.ctrl_shift_activated_smooth = True
                    if context.area:
                        context.area.tag_redraw()
            else:
                if getattr(self, 'ctrl_shift_activated_smooth', False):
                    S.use_smooth_brush = False
                    self.ctrl_shift_activated_smooth = False
                    if context.area:
                        context.area.tag_redraw()

        is_over_ui = is_mouse_over_ui(context, event)

        if is_over_ui and event.type != 'TIMER':
            self.mouse_pos = None
            if not getattr(self, 'is_smoothing_brush_stroke', False) and not getattr(self, 'is_g_grab_traction', False) and not getattr(self, 'is_mouse_dragging_pin', False):
                return {'PASS_THROUGH'}

        if not is_over_ui and hasattr(event, 'mouse_region_x') and hasattr(event, 'mouse_region_y'):
            self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)

        # 暂停模式下的平滑笔刷移动与长按响应（支持 Ctrl + Shift 快捷按键及 TIMER 触发长按平滑）
        if S.pause and (getattr(S, 'use_smooth_brush', False) or getattr(self, 'is_smoothing_brush_stroke', False) or (event and getattr(event, 'ctrl', False) and getattr(event, 'shift', False))):
            if getattr(self, 'is_smooth_brush_pending', False):
                press_t = getattr(self, 'smooth_brush_press_time', 0.0)
                dt = time.time() - press_t
                start_pos = getattr(self, 'smooth_brush_start_pos', None)
                curr_pos = getattr(self, 'mouse_pos', start_pos)
                dist = (Vector(curr_pos) - start_pos).length if (curr_pos and start_pos) else 0.0

                if dist > 4.0 or dt > 0.12:
                    self.is_smooth_brush_pending = False
                    self.is_smoothing_brush_stroke = True
                    if start_pos and not is_over_ui:
                        self.apply_smooth_brush(context, start_pos.x, start_pos.y)

            if getattr(self, 'is_smoothing_brush_stroke', False) and not is_over_ui:
                m_pos = getattr(self, 'mouse_pos', None)
                if m_pos:
                    self.apply_smooth_brush(context, m_pos[0], m_pos[1])

            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER'}:
                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                if getattr(self, 'is_smoothing_brush_stroke', False) or getattr(self, 'is_smooth_brush_pending', False):
                    return {'RUNNING_MODAL'}

        # 暂停模式下的鼠标释放与直接拖拽/笔刷状态结束处理
        if S.pause and event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.is_mouse_drag_pending = False
            if getattr(self, 'is_smooth_brush_pending', False):
                self.is_smooth_brush_pending = False
                self.is_smoothing_brush_stroke = False
                self.smooth_brush_before_snapshot = {}
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if getattr(self, 'is_smoothing_brush_stroke', False):
                self.is_smoothing_brush_stroke = False
                before_snap = getattr(self, 'smooth_brush_before_snapshot', None)
                if before_snap:
                    self.push_pin_undo_snapshot(before_snap)
                self.smooth_brush_before_snapshot = None
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            if getattr(self, 'is_mouse_dragging_pin', False):
                before_snap = getattr(self, 'g_grab_before_snapshot', None)
                if before_snap:
                    self.push_pin_undo_snapshot(before_snap)

                self.is_mouse_dragging_pin = False
                self.is_g_grab_traction = False
                self.g_grab_pins = []
                self.g_grab_fixed_pins = []
                self.g_grab_traction_pins = []
                self.g_grab_backup = {}
                self.g_grab_before_snapshot = None
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # 暂停模式下鼠标按住并拖拽牵引点 (Mouse Direct Dragging Traction Pins)
        if S.pause and getattr(self, 'is_mouse_drag_pending', False) and not getattr(self, 'is_g_grab_traction', False):
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                start_m = getattr(self, 'drag_mouse_start', m_pos)
                if (m_pos - start_m).length > 4.0:
                    raw_pins = S.source_ob.get('sw_pins', ()) if S.source_ob else ()
                    fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

                    drag_target = getattr(self, 'drag_picked_pin', None)
                    if drag_target is not None and fixed_indices:
                        if isinstance(drag_target, tuple):
                            p_type, drag_pin = drag_target
                        else:
                            p_type, drag_pin = 'FIXED', drag_target

                        sel_pause = set(getattr(self, 'selected_pause_pins', set()))
                        sel_traction = set(getattr(self, 'selected_traction_pins', set()))
                        active_sel = sel_pause | sel_traction

                        # 若当前鼠标拖拽的点已在选中集合中，联动拖拽全组点；否则单点选择并拖拽
                        if drag_pin in active_sel:
                            self.g_grab_fixed_pins = [p for p in sel_pause if p in fixed_indices]
                            self.g_grab_traction_pins = [p for p in sel_traction if p in fixed_indices]
                            picked_pins = list(set(self.g_grab_fixed_pins) | set(self.g_grab_traction_pins))
                        else:
                            if p_type == 'TRACTION':
                                self.selected_traction_pins = {drag_pin}
                                self.selected_pause_pins = set()
                                self.g_grab_traction_pins = [drag_pin]
                                self.g_grab_fixed_pins = []
                            else:
                                self.selected_pause_pins = {drag_pin}
                                self.selected_traction_pins = set()
                                self.g_grab_fixed_pins = [drag_pin]
                                self.g_grab_traction_pins = []
                            picked_pins = [drag_pin]

                        if picked_pins:
                            self.is_box_selecting = False
                            self.is_mouse_drag_pending = False
                            self.is_mouse_dragging_pin = True
                            self.is_g_grab_traction = True
                            self.g_transform_mode = 'TRANSLATE'
                            self.g_grab_pins = picked_pins
                            if not hasattr(self, 'traction_pins'):
                                self.traction_pins = {}

                            fixed_set_all = set(fixed_indices)
                            affected_map = get_fixed_pin_rings(self.arranged_links, fixed_set_all, picked_pins, max_steps=2)
                            self.g_grab_affected_map = affected_map

                            self.g_grab_backup = {idx: self.traction_pins.get(idx) for idx in affected_map}
                            self.g_grab_before_snapshot = self.get_pin_state_snapshot()

                            mat = S.source_ob.matrix_world
                            self.g_grab_initial_positions = {}
                            c0 = Vector((0.0, 0.0, 0.0))
                            for idx in picked_pins:
                                if idx in self.traction_pins:
                                    p_curr = self.traction_pins[idx].copy()
                                else:
                                    p_curr = (mat @ self.get_vert_co(context, idx)).copy()
                                c0 += p_curr

                            for idx in affected_map:
                                if idx in self.traction_pins:
                                    p_curr = self.traction_pins[idx].copy()
                                else:
                                    p_curr = (mat @ self.get_vert_co(context, idx)).copy()
                                self.g_grab_initial_positions[idx] = p_curr

                            c0 /= max(len(picked_pins), 1)
                            self.g_grab_initial_centroid = c0
                            self.g_transform_mouse_start = start_m

                            region = getattr(context, 'region', None)
                            space = getattr(context, 'space_data', None)
                            rv3d = getattr(space, 'region_3d', None) if space else None
                            if region and rv3d:
                                from bpy_extras.view3d_utils import location_3d_to_region_2d
                                c2d = location_3d_to_region_2d(region, rv3d, c0)
                                self.g_transform_screen_centroid = c2d if c2d else start_m
                            else:
                                self.g_transform_screen_centroid = start_m

                            if self.g_transform_mode == 'TRANSLATE':
                                init_target = self.raycast_traction_target(context, event, ref_pos=c0)
                                if len(picked_pins) > 1:
                                    snapped_centroid = self.snap_point_to_bvh(context, init_target)
                                    delta_group = snapped_centroid - c0
                                    for idx, step in affected_map.items():
                                        if idx in self.g_grab_initial_positions:
                                            weight = get_step_weight(step)
                                            self.traction_pins[idx] = self.g_grab_initial_positions[idx] + (delta_group * weight)
                                else:
                                    delta = init_target - c0
                                    for idx, step in affected_map.items():
                                        if idx in self.g_grab_initial_positions:
                                            weight = get_step_weight(step)
                                            raw_pos = self.g_grab_initial_positions[idx] + (delta * weight)
                                            snapped_pos = self.snap_point_to_bvh(context, raw_pos)
                                            self.traction_pins[idx] = snapped_pos

        # 8. 双击 (DOUBLE_CLICK) 切换固定点状态（点/边/面，暂停模式与正常模式通用）
        now_time = time.time()
        is_double_click = False
        if event.type == S.mouse_button:
            if event.value == 'DOUBLE_CLICK':
                is_double_click = True
            elif event.value == 'PRESS':
                last_t = getattr(self, '_last_click_time', 0.0)
                last_pos = getattr(self, '_last_click_pos', (0, 0))
                dist = (Vector((event.mouse_region_x, event.mouse_region_y)) - Vector(last_pos)).length
                if (now_time - last_t) < 0.28 and dist < 8.0:
                    is_double_click = True
                    self._last_click_time = 0.0
                else:
                    self._last_click_time = now_time
                    self._last_click_pos = (event.mouse_region_x, event.mouse_region_y)

        if is_double_click and S.interact_mouse:
            mesh_verts = self.pick_mesh_vert(context, event)
            if mesh_verts:
                self.is_box_selecting = False
                self.is_mouse_drag_pending = False
                self.is_mouse_dragging_pin = False

                raw_pins = list(S.source_ob.get('sw_pins', []))
                pins_set = set()
                for p in raw_pins:
                    if isinstance(p, int):
                        pins_set.add(p)
                    elif hasattr(p, '__getitem__') and 'vert_idx' in p:
                        pins_set.add(p['vert_idx'])

                target_set = set(mesh_verts)
                before_snap = self.get_pin_state_snapshot()

                # 若选中的元素（点/边/面）对应的所有顶点都已经固定，则全部取消固定；否则全部设为固定点
                if target_set.issubset(pins_set):
                    pins_set -= target_set
                    for v_idx in mesh_verts:
                        if hasattr(self, 'traction_pins'):
                            self.traction_pins.pop(v_idx, None)
                        if hasattr(self, 'fixed_anchor_world_pos'):
                            self.fixed_anchor_world_pos.pop(v_idx, None)
                        if hasattr(self, 'selected_pause_pins'):
                            self.selected_pause_pins.discard(v_idx)
                else:
                    pins_set |= target_set

                S.source_ob['sw_pins'] = list(pins_set)
                self.pin_cache_update(context, event)
                self.push_pin_undo_snapshot(before_snap)
                bpy.ops.ed.undo_push(message='Toggle Pin')

                if context.area:
                    context.area.tag_redraw()

                return {'RUNNING_MODAL'}

        # 暂停模式下的鼠标左键点选/Alt 循环选/拖拽准备/平滑笔刷按下 (LEFTMOUSE Selection & Drag & Smooth Brush Start)
        if S.pause and event.type == 'LEFTMOUSE' and event.value == 'PRESS' and not getattr(self, 'is_g_grab_traction', False):
            if not is_over_ui and (getattr(S, 'use_smooth_brush', False) or (event.ctrl and event.shift)):
                self.is_smooth_brush_pending = True
                self.is_smoothing_brush_stroke = False
                self.smooth_brush_press_time = time.time()
                self.smooth_brush_start_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                self.smooth_brush_before_snapshot = self.get_pin_state_snapshot()
                self.apply_smooth_brush(context, event.mouse_region_x, event.mouse_region_y)
                return {'RUNNING_MODAL'}
            raw_pins = S.source_ob.get('sw_pins', ()) if S.source_ob else ()
            fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

            if not hasattr(self, 'selected_pause_pins'):
                self.selected_pause_pins = set()
            if not hasattr(self, 'selected_traction_pins'):
                self.selected_traction_pins = set()

            if event.alt:
                # Alt + 点击：对连续的牵引点 (Traction Pins) / 固定点进行拓扑循环边式选择 (Loop Selection)
                picked_target = self.pick_pause_pin(context, event, fixed_indices) if fixed_indices else None
                if picked_target is not None:
                    p_type, picked_val = picked_target if isinstance(picked_target, tuple) else ('FIXED', picked_target)
                    picked_idx = picked_val if isinstance(picked_val, int) else (list(picked_val)[0] if (picked_val and isinstance(picked_val, set)) else None)

                    if picked_idx is not None:
                        mat = S.source_ob.matrix_world if S.source_ob else Matrix.Identity(4)
                        def get_co_func(v):
                            if S.pause and hasattr(self, 'traction_pins') and self.traction_pins and v in self.traction_pins:
                                return self.traction_pins[v].copy()
                            return (mat @ self.get_vert_co(context, v)).copy()

                        # 判断点击方向最接近的邻居节点 (target_nbr)
                        target_nbr = None
                        if hasattr(self, 'arranged_links') and self.arranged_links and picked_idx < len(self.arranged_links):
                            nbrs = self.arranged_links[picked_idx]
                            region = getattr(context, 'region', None)
                            space = getattr(context, 'space_data', None)
                            rv3d = getattr(space, 'region_3d', None) if space else None
                            if nbrs and region and rv3d:
                                from bpy_extras.view3d_utils import location_3d_to_region_2d
                                m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                                p_v_2d = location_3d_to_region_2d(region, rv3d, get_co_func(picked_idx))
                                min_d = 1e9
                                for n in nbrs:
                                    p_n_2d = location_3d_to_region_2d(region, rv3d, get_co_func(n))
                                    if p_v_2d and p_n_2d:
                                        seg_vec = p_n_2d - p_v_2d
                                        seg_len_sq = seg_vec.length_squared
                                        if seg_len_sq > 1e-4:
                                            t = max(0.0, min(1.0, (m_pos - p_v_2d).dot(seg_vec) / seg_len_sq))
                                            proj_pt = p_v_2d + seg_vec * t
                                            d = (m_pos - proj_pt).length
                                        else:
                                            d = (m_pos - p_n_2d).length
                                        if d < min_d:
                                            min_d = d
                                            target_nbr = n

                        trac_set = set(self.traction_pins.keys()) if (S.pause and hasattr(self, 'traction_pins') and self.traction_pins) else set()
                        fixed_set_all = set(fixed_indices)

                        before_snap = self.get_pin_state_snapshot()
                        prev_sel_pause = set(self.selected_pause_pins)
                        prev_sel_trac = set(self.selected_traction_pins)

                        if p_type == 'TRACTION' or picked_idx in trac_set:
                            # 连续牵引点循环边选择
                            target_set = trac_set if trac_set else fixed_set_all
                            loop_verts = find_fixed_pin_loop(self.arranged_links, target_set, picked_idx, target_nbr, get_co_func)
                            if event.shift:
                                if loop_verts.issubset(self.selected_traction_pins):
                                    self.selected_traction_pins -= loop_verts
                                else:
                                    self.selected_traction_pins |= loop_verts
                            else:
                                self.selected_traction_pins = set(loop_verts)
                                self.selected_pause_pins = set()
                        else:
                            # 固定点循环边选择
                            loop_verts = find_fixed_pin_loop(self.arranged_links, fixed_set_all, picked_idx, target_nbr, get_co_func)
                            if event.shift:
                                if loop_verts.issubset(self.selected_pause_pins):
                                    self.selected_pause_pins -= loop_verts
                                else:
                                    self.selected_pause_pins |= loop_verts
                            else:
                                self.selected_pause_pins = set(loop_verts)
                                self.selected_traction_pins = set()

                        if prev_sel_pause != self.selected_pause_pins or prev_sel_trac != self.selected_traction_pins:
                            self.push_pin_undo_snapshot(before_snap)

                        self.sync_bmesh_selection(context)
                        self.draw_pins(context, event)
                        if context.area:
                            context.area.tag_redraw()
                        return {'RUNNING_MODAL'}

                # 若未点中现有牵引点/固定点，则退回到 BMesh 循环边追踪算法
                closest_edge_idx = self.pick_closest_edge(context, event)
                if closest_edge_idx is None:
                    mesh_verts = self.pick_mesh_vert(context, event)
                    mesh_vert = mesh_verts[0] if (mesh_verts and isinstance(mesh_verts, (list, tuple))) else mesh_verts
                    if mesh_vert is not None and S.source_ob and S.source_ob.mode == 'EDIT':
                        try:
                            bm = bmesh.from_edit_mesh(S.source_ob.data)
                            bm.verts.ensure_lookup_table()
                            if 0 <= mesh_vert < len(bm.verts):
                                v_obj = bm.verts[mesh_vert]
                                if v_obj.link_edges:
                                    region = getattr(context, 'region', None)
                                    space = getattr(context, 'space_data', None)
                                    rv3d = getattr(space, 'region_3d', None) if space else None
                                    if region and rv3d:
                                        from bpy_extras.view3d_utils import location_3d_to_region_2d
                                        m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                                        mat = S.source_ob.matrix_world
                                        p_v_2d = location_3d_to_region_2d(region, rv3d, mat @ v_obj.co)
                                        best_edge_obj = None
                                        min_dist = 1e9
                                        for e in v_obj.link_edges:
                                            other_v = e.other_vert(v_obj)
                                            p_other_2d = location_3d_to_region_2d(region, rv3d, mat @ other_v.co)
                                            if p_v_2d and p_other_2d:
                                                seg_vec = p_other_2d - p_v_2d
                                                seg_len_sq = seg_vec.length_squared
                                                if seg_len_sq > 1e-4:
                                                    t = max(0.0, min(1.0, (m_pos - p_v_2d).dot(seg_vec) / seg_len_sq))
                                                    proj_pt = p_v_2d + seg_vec * t
                                                    dist = (m_pos - proj_pt).length
                                                else:
                                                    dist = (m_pos - p_other_2d).length
                                                if dist < min_dist:
                                                    min_dist = dist
                                                    best_edge_obj = e
                                        if best_edge_obj:
                                            closest_edge_idx = best_edge_obj.index
                        except Exception:
                            pass

                if closest_edge_idx is not None and S.source_ob and S.source_ob.mode == 'EDIT':
                    try:
                        bm = bmesh.from_edit_mesh(S.source_ob.data)
                        bm.edges.ensure_lookup_table()
                        bm.verts.ensure_lookup_table()
                        bm.faces.ensure_lookup_table()
                        if 0 <= closest_edge_idx < len(bm.edges):
                            closest_edge = bm.edges[closest_edge_idx]
                            loop_verts = bmesh_walk_edge_loop(closest_edge)
                            before_snap = self.get_pin_state_snapshot()
                            prev_sel_pause = set(self.selected_pause_pins)

                            if event.shift:
                                if loop_verts.issubset(self.selected_pause_pins):
                                    self.selected_pause_pins -= loop_verts
                                else:
                                    self.selected_pause_pins |= loop_verts
                            else:
                                self.selected_pause_pins = set(loop_verts)

                            if prev_sel_pause != self.selected_pause_pins:
                                self.push_pin_undo_snapshot(before_snap)

                            self.sync_bmesh_selection(context)
                    except Exception as err:
                        print("Edge loop selection error:", err)

                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            # 检索点击位置（优先比对现有固定点/牵引点，若未中则射线拾取模型表面顶点）
            picked_target = self.pick_pause_pin(context, event, fixed_indices) if fixed_indices else None
            if picked_target is None:
                mesh_verts = self.pick_mesh_vert(context, event)
                if mesh_verts:
                    picked_target = ('FIXED', set(mesh_verts))

            self.pending_click_pick = picked_target
            self.pending_click_shift = event.shift

            if picked_target is not None:
                p_type, picked_idx = picked_target
                if p_type == 'TRACTION' and hasattr(self, 'traction_pins') and picked_idx in self.traction_pins:
                    self.drag_mouse_start = Vector((event.mouse_region_x, event.mouse_region_y))
                    self.drag_picked_pin = picked_target
                    # 若按下了 Shift 键，则属于 Shift 加选/减选手势，不启动鼠标拖拽监听，确保 Shift 加选成功
                    if not event.shift:
                        self.is_mouse_drag_pending = True
                    else:
                        self.is_mouse_drag_pending = False
                    self.is_mouse_dragging_pin = False
                else:
                    self.is_mouse_drag_pending = False
                    self.is_mouse_dragging_pin = False
            else:
                self.is_mouse_drag_pending = False
                self.is_mouse_dragging_pin = False

            # 无论点击位置在网格内部还是空白处，均启动 2D 框选监听
            self.is_box_selecting = True
            m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
            self.box_start = m_pos
            self.box_current = m_pos
            self.box_dragged = False
            self.draw_pins(context, event)
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        # 暂停模式下的 G 移动 / S 缩放 / R 旋转 键盘快捷键响应 (Transform Hotkeys)
        if S.pause and event.type in {'G', 'S', 'R'} and event.value == 'PRESS' and not event.ctrl and not event.alt:
            mat = S.source_ob.matrix_world
            raw_pins = S.source_ob.get('sw_pins', ()) if S.source_ob else ()
            fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

            picked_pins = []
            sel_pause = set(getattr(self, 'selected_pause_pins', set()))
            sel_traction = set(getattr(self, 'selected_traction_pins', set()))
            sel_set = sel_pause | sel_traction

            if sel_set:
                unpinned_selected = [p for p in sel_set if p not in fixed_indices]
                if unpinned_selected:
                    fixed_indices.extend(unpinned_selected)
                    S.source_ob['sw_pins'] = list(set(fixed_indices))
                self.g_grab_fixed_pins = [p for p in sel_pause if p in fixed_indices]
                self.g_grab_traction_pins = [p for p in sel_traction if p in fixed_indices]
                picked_pins = list(set(self.g_grab_fixed_pins) | set(self.g_grab_traction_pins))

            if not picked_pins and S.source_ob.mode == 'EDIT':
                try:
                    bm = bmesh.from_edit_mesh(S.source_ob.data)
                    bm.verts.ensure_lookup_table()
                    selected_verts = [v.index for v in bm.verts if v.select]
                    if selected_verts:
                        unpinned_selected = [p for p in selected_verts if p not in fixed_indices]
                        if unpinned_selected:
                            fixed_indices.extend(unpinned_selected)
                            S.source_ob['sw_pins'] = list(set(fixed_indices))
                        picked_pins = selected_verts
                        self.g_grab_fixed_pins = selected_verts
                        self.g_grab_traction_pins = []
                except Exception:
                    pass

            if not picked_pins:
                picked_target = self.pick_pause_pin(context, event, fixed_indices) if fixed_indices else None
                if picked_target is None:
                    mesh_vert = self.pick_mesh_vert(context, event)
                    if mesh_vert is not None:
                        picked_target = ('FIXED', mesh_vert)
                if picked_target is not None:
                    p_type, picked_val = picked_target
                    target_indices = list(picked_val) if isinstance(picked_val, (list, tuple, set)) else [picked_val]
                    for idx in target_indices:
                        if isinstance(idx, int) and idx not in fixed_indices:
                            fixed_indices.append(idx)
                    S.source_ob['sw_pins'] = list(set(fixed_indices))
                    picked_pins = target_indices
                    if not hasattr(self, 'selected_pause_pins'):
                        self.selected_pause_pins = set()
                    if not hasattr(self, 'selected_traction_pins'):
                        self.selected_traction_pins = set()
                    if p_type == 'TRACTION':
                        self.selected_traction_pins = set(target_indices)
                        self.selected_pause_pins = set()
                        self.g_grab_traction_pins = list(target_indices)
                        self.g_grab_fixed_pins = []
                    else:
                        self.selected_pause_pins = set(target_indices)
                        self.selected_traction_pins = set()
                        self.g_grab_fixed_pins = list(target_indices)
                        self.g_grab_traction_pins = []

            if picked_pins:
                self.is_g_grab_traction = True
                if event.type == 'S':
                    self.g_transform_mode = 'SCALE'
                elif event.type == 'R':
                    self.g_transform_mode = 'ROTATE'
                else:
                    self.g_transform_mode = 'TRANSLATE'

                self.g_grab_pins = picked_pins
                if not hasattr(self, 'traction_pins'):
                    self.traction_pins = {}

                fixed_set_all = set(fixed_indices)
                affected_map = get_fixed_pin_rings(self.arranged_links, fixed_set_all, picked_pins, max_steps=2)
                self.g_grab_affected_map = affected_map

                self.g_grab_backup = {idx: self.traction_pins.get(idx) for idx in affected_map}
                self.g_grab_before_snapshot = self.get_pin_state_snapshot()

                self.g_grab_initial_positions = {}
                c0 = Vector((0.0, 0.0, 0.0))
                for idx in picked_pins:
                    if idx in self.traction_pins:
                        p_curr = self.traction_pins[idx].copy()
                    else:
                        p_curr = (mat @ self.get_vert_co(context, idx)).copy()
                    c0 += p_curr

                for idx in affected_map:
                    if idx in self.traction_pins:
                        p_curr = self.traction_pins[idx].copy()
                    else:
                        p_curr = (mat @ self.get_vert_co(context, idx)).copy()
                    self.g_grab_initial_positions[idx] = p_curr

                c0 /= max(len(picked_pins), 1)
                self.g_grab_initial_centroid = c0

                # 记录 2D 初始鼠标位置与屏幕 2D Centroid
                m_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                self.g_transform_mouse_start = m_pos

                region = getattr(context, 'region', None)
                space = getattr(context, 'space_data', None)
                rv3d = getattr(space, 'region_3d', None) if space else None
                if region and rv3d:
                    from bpy_extras.view3d_utils import location_3d_to_region_2d
                    c2d = location_3d_to_region_2d(region, rv3d, c0)
                    self.g_transform_screen_centroid = c2d if c2d else m_pos
                else:
                    self.g_transform_screen_centroid = m_pos

                if self.g_transform_mode == 'TRANSLATE':
                    init_target = self.raycast_traction_target(context, event, ref_pos=c0)
                    if len(picked_pins) > 1:
                        snapped_centroid = self.snap_point_to_bvh(context, init_target)
                        delta_group = snapped_centroid - c0
                        for idx, step in affected_map.items():
                            if idx in self.g_grab_initial_positions:
                                weight = get_step_weight(step)
                                self.traction_pins[idx] = self.g_grab_initial_positions[idx] + (delta_group * weight)
                    else:
                        delta = init_target - c0
                        for idx, step in affected_map.items():
                            if idx in self.g_grab_initial_positions:
                                weight = get_step_weight(step)
                                raw_pos = self.g_grab_initial_positions[idx] + (delta * weight)
                                snapped_pos = self.snap_point_to_bvh(context, raw_pos)
                                self.traction_pins[idx] = snapped_pos

                if context.area:
                    context.area.tag_redraw()

            return {'RUNNING_MODAL'}

        # 检测键盘快捷键 (R, S, E 等) 触发的 Blender 原生变换
        if not S.pause and event.type in {'G', 'R', 'S', 'E'} and event.value == 'PRESS' and not event.ctrl and not event.alt:
            self.is_transforming = True

        # 当处于键盘快捷键 G/R/S/E 变换操作中时：
        if getattr(self, 'is_transforming', False):
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER', 'ESC'} and event.value == 'PRESS':
                self.is_transforming = False
                # 变换完成后，重新抓取编辑模式下更新后的顶点位置并同步给 GPU 解算引擎
                if S.source_ob and S.source_ob.mode == 'EDIT':
                    try:
                        bm = bmesh.from_edit_mesh(S.source_ob.data)
                        bm.verts.ensure_lookup_table()
                        if len(bm.verts) == self.n_verts:
                            vdata = [0.0] * (self.n_verts * 3)
                            for i, v in enumerate(bm.verts):
                                vdata[i*3 : i*3+3] = v.co
                            self.engine.from_list(vdata)
                    except Exception:
                        pass
            if S.pause:
                self.handle_pause_pin_movement(context, event)
            self.draw_pins(context, event)
            if context.area:
                context.area.tag_redraw()
            return {'PASS_THROUGH'}

        shape = self.get_shape(context)
        shape.mute = False

        if S.source_ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(S.source_ob.data)
            current_n_verts = len(bm.verts)
        else:
            current_n_verts = len(S.source_ob.data.vertices)

        if current_n_verts != self.n_verts:
            self.reinit_engine(context)

        self.last_mode = S.source_ob.mode

        if event.type == 'SPACE' and event.value == 'PRESS' and not event.ctrl:
            if event.shift:
                S.interact_mouse = not S.interact_mouse
            else:
                S.pause = not S.pause
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER':
            if not S.pause:
                # 同步 Mask 属性
                self.engine.simulation_mask_tex = self.simulation_mask.tex
                self.engine.simulation_mask_invert = False
                self.engine.simulation_mask_empty = self.simulation_mask.is_empty
                self.engine.snapping_mask_tex = self.snapping_mask.tex
                self.engine.snapping_mask_invert = False
                self.engine.snapping_mask_empty = self.snapping_mask.is_empty

                # 保存起始坐标以供 simulation mask 混合
                self.engine.save_pos_for_mask()

                # 1. 物理迭代模拟
                for _ in range(S.simulation_steps):
                    for i, f in iter_float_factor(S.quad_smoothing, 1, 3, 10):
                        self.quaternary_links.smooth(f)

                    for i, f in iter_float_factor(S.shear_stiffness, 1, 3, 10):
                        if i > 0:
                            self.shear_springs.stiff_spring_force(f)
                        else:
                            self.shear_springs.soft_spring_force(f, deform_update=S.scale_plasticity,
                                                                 deform_restore=S.scale_restoration,
                                                                 min_deform=S.min_scaling,
                                                                 max_deform=S.max_scaling)

                    for i, f in iter_float_factor(S.bending_stiffness, 1, 3, 10):
                        if i > 0:
                            self.bending_springs.stiff_spring_force(f)
                        else:
                            self.bending_springs.soft_spring_force(f, deform_update=S.scale_plasticity,
                                                                   deform_restore=S.scale_restoration,
                                                                   min_deform=S.min_scaling,
                                                                   max_deform=S.max_scaling)

                    for i, f in iter_float_factor(S.structural_stiffness, 1, 3, 10):
                        if i > 0:
                            self.structural_springs.stiff_spring_force(f)
                        else:
                            self.structural_springs.soft_spring_force(f, deform_update=S.scale_plasticity,
                                                                      deform_restore=S.scale_restoration,
                                                                      min_deform=S.min_scaling,
                                                                      max_deform=S.max_scaling)

                    self.engine.kinetic_step(1.0 - S.damping)

                for i, f in iter_float_factor(S.smooth, 0.5, 3, 5):
                    self.structural_springs.smooth(f)

                for i, f in iter_float_factor(S.topologic_smooth, 0.5, 3, 5):
                    self.ternary_links.displacement_force(f)

                # 应用 simulation mask 混合
                self.engine.apply_simulation_mask_mix(1.0, False)

                self.engine.update_mesh_normals(1.0)

                f = 1.0
                for i in range(3):
                    self.pin_cache_update(context, event)
                    self.pin_cache_apply(context, event, factor=((i + 1) / 3) * f, mouse_factor=1)
                    self.engine.apply_pin_displacements()

                if self.bvh and S.snapping_force > 0:
                    self.engine.save_pos_for_mask()
                    self.engine.snap_to_bvh(S.snapping_force ** 3, 20 - S.snapping_quality + 1, S.snapping_mode)
                    self.engine.apply_snapping_mask_mix(1.0, False)

                self.symmetry_map.mirror(*S.mirror)

                # 7. 一次性回传坐标并渲染至 Blender 视图
                final_coords = self.engine.read_positions()
                if S.source_ob.mode == 'EDIT':
                    bm = bmesh.from_edit_mesh(S.source_ob.data)
                    bm.verts.ensure_lookup_table()
                    if len(bm.verts) * 3 == len(final_coords):
                        for i, v in enumerate(bm.verts):
                            v.co.x = final_coords[i*3]
                            v.co.y = final_coords[i*3+1]
                            v.co.z = final_coords[i*3+2]
                        bmesh.update_edit_mesh(S.source_ob.data)
                else:
                    self.get_shape(context).data.foreach_set('co', final_coords)
                    S.source_ob.data.update()

                self.draw_pins(context, event)
                if context.area:
                    context.area.tag_redraw()

            else:
                self.handle_pause_pin_movement(context, event)

                # 暂停/编辑/物体模式下：实时同步 Blender 视图中手动修改后的顶点坐标至 GPU 解算引擎与锚定记录
                vdata = [0.0] * (self.n_verts * 3)
                if S.source_ob and S.source_ob.mode == 'EDIT':
                    try:
                        bm = bmesh.from_edit_mesh(S.source_ob.data)
                        bm.verts.ensure_lookup_table()
                        if len(bm.verts) == self.n_verts:
                            for i, v in enumerate(bm.verts):
                                vdata[i*3 : i*3+3] = v.co
                    except Exception:
                        pass
                elif S.source_ob:
                    shape = self.get_shape(context)
                    if shape and hasattr(shape, 'data') and len(shape.data) == self.n_verts:
                        shape.data.foreach_get('co', vdata)

                if self.engine and any(vdata):
                    self.engine.from_list(vdata)

                self.pin_cache_update(context, event)
                self.draw_pins(context, event)
                if (self.mouse_pin_pos or getattr(self, 'pause_fixed_orig_pos', None)) and context.area:
                    context.area.tag_redraw()

            return {'PASS_THROUGH'} if not self.mouse_pin_pos else {'RUNNING_MODAL'}



        if event.type == S.mouse_button and event.value == 'PRESS' and S.interact_mouse:
            if S.source_ob.mode == 'EDIT':
                return {'PASS_THROUGH'}

            areas = areas_under_mouse(context, event)
            bad_region = False
            for area, regions in areas:
                if area.type == 'VIEW_3D':
                    r_types = set(r.type for r in regions)
                    if {'UI', 'HEADER', 'TOOLS'} & r_types:
                        bad_region = True

            if not bad_region and self.mouse_pin_set(context, event):
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        elif event.type == S.mouse_button and event.value == 'RELEASE':
            self.mouse_pin_clear(context, event)
            if context.area:
                context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'}


