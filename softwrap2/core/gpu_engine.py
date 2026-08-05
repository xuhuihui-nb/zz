import os
import gpu
import struct
import array
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

def compile_compute_shader(filename, push_constants, image_bindings):
    core_dir = os.path.dirname(__file__)
    filepath = os.path.join(core_dir, filename)
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    info = gpu.types.GPUShaderCreateInfo()
    info.local_group_size(256, 1, 1)
    for dtype, name in push_constants:
        info.push_constant(dtype, name)
    for slot, fmt, typ, name, qual in image_bindings:
        info.image(slot, fmt, typ, name, qualifiers=qual)
    info.compute_source(source)
    return gpu.shader.create_from_info(info)

def make_texture_1d(size, data=None):
    if size <= 0:
        size = 1
    width = 1024
    height = (size + width - 1) // width
    
    expected_floats = width * height * 4
    if data is None:
        data = [0.0] * expected_floats
    else:
        if len(data) < expected_floats:
            data = list(data) + [0.0] * (expected_floats - len(data))
        elif len(data) > expected_floats:
            data = data[:expected_floats]
            
    buf = gpu.types.Buffer('FLOAT', expected_floats, data)
    return gpu.types.GPUTexture((width, height), format='RGBA32F', data=buf)

def read_texture_flat(texture):
    nested = texture.read().to_list()
    flat = []
    for row in nested:
        for pixel in row:
            flat.extend(pixel)
    return flat

def pack_spring_links(n_verts, coords, spring_indices):
    arranged = [[] for _ in range(n_verts)]
    for a, b in spring_indices:
        arranged[a].append(b)
        arranged[b].append(a)
    
    headers = [0.0] * (n_verts * 4)
    links = []
    current_start = 0
    for i in range(n_verts):
        count = len(arranged[i])
        headers[i*4 : i*4+2] = [float(current_start), float(count)]
        p_i = Vector(coords[i*4 : i*4+3])
        for neighbor in arranged[i]:
            p_n = Vector(coords[neighbor*4 : neighbor*4+3])
            rest_length = (p_i - p_n).length
            links.extend([float(neighbor), rest_length, 1.0, 0.0]) # RGBA32F
        current_start += count
    return headers, links, arranged

def pack_ternary_links(n_verts, coords, vert_normals, ternary_indices):
    arranged = [[] for _ in range(n_verts)]
    for c, a, b in ternary_indices:
        arranged[c].append((a, b))
    
    headers = [0.0] * (n_verts * 4)
    links = []
    current_start = 0
    for i in range(n_verts):
        count = len(arranged[i])
        headers[i*4 : i*4+2] = [float(current_start), float(count)]
        p_i = Vector(coords[i*4 : i*4+3])
        normal = Vector(vert_normals[i*4 : i*4+3])
        for a, b in arranged[i]:
            pa = Vector(coords[a*4 : a*4+3])
            pb = Vector(coords[b*4 : b*4+3])
            avg = (pa + pb) * 0.5
            d = p_i - avg
            side = 1.0 if d.dot(normal) > 0 else 0.0
            len_ab = (pa - pb).length
            avg_dist = d.length / (len_ab + 1e-5)
            links.extend([float(a), float(b), side, avg_dist]) # RGBA32F
        current_start += count
    return headers, links

def pack_quaternary_links(n_verts, coords, quad_indices):
    links = []
    for a, b, c, d in quad_indices:
        pa = Vector(coords[a*4 : a*4+3])
        pb = Vector(coords[b*4 : b*4+3])
        pc = Vector(coords[c*4 : c*4+3])
        pd = Vector(coords[d*4 : d*4+3])
        ratio = (pa - pb).length / ((pc - pd).length + 1e-5)
        side = 1.0 if (pa - pb).dot(pc - pd) > 1.0 else 0.0
        links.append((a, b, c, d, ratio, side))
        
    arranged = [[] for _ in range(n_verts)]
    for idx, (a, b, c, d, ratio, side) in enumerate(links):
        arranged[a].append((idx, 0))
        arranged[b].append((idx, 1))
        arranged[c].append((idx, 2))
        arranged[d].append((idx, 3))
        
    headers = [0.0] * (n_verts * 4)
    vertex_links = []
    current_start = 0
    for i in range(n_verts):
        count = len(arranged[i])
        headers[i*4 : i*4+2] = [float(current_start), float(count)]
        for link_idx, role in arranged[i]:
            vertex_links.extend([float(link_idx), float(role), 0.0, 0.0]) # RGBA32F
        current_start += count
        
    flat_quad_indices = []
    flat_quad_params = []
    for a, b, c, d, ratio, side in links:
        flat_quad_indices.extend([float(a), float(b), float(c), float(d)])
        flat_quad_params.extend([ratio, side, 0.0, 0.0])
        
    return flat_quad_indices, flat_quad_params, headers, vertex_links

def pack_vertex_triangles(n_verts, triangles):
    arranged = [[] for _ in range(n_verts)]
    for idx, (v0, v1, v2) in enumerate(triangles):
        arranged[v0].append(idx)
        arranged[v1].append(idx)
        arranged[v2].append(idx)
        
    headers = [0.0] * (n_verts * 4)
    indices = []
    current_start = 0
    for i in range(n_verts):
        count = len(arranged[i])
        headers[i*4 : i*4+2] = [float(current_start), float(count)]
        for tri_idx in arranged[i]:
            indices.extend([float(tri_idx), 0.0, 0.0, 0.0]) # RGBA32F
        current_start += count
    return headers, indices


def get_pin_rings(arranged_links, start_index, n_rings):
    n_rings = max(n_rings, 1)
    rings = [[start_index]]
    seen = {start_index}
    for i in range(n_rings - 1):
        next_front = []
        for v in rings[-1]:
            for neighbor in arranged_links[v]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    next_front.append(neighbor)
        rings.append(next_front)
    return rings


class GPUSpringEngine:
    def __init__(self, verts_coords, triangles, target_bvh=None):
        self.n_verts = len(verts_coords) // 3
        self.n_tris = len(triangles)
        self.triangles = triangles
        
        # 1. 基础物理缓冲区
        pos_data = []
        for i in range(self.n_verts):
            pos_data.extend([verts_coords[i*3], verts_coords[i*3+1], verts_coords[i*3+2], 1.0])
        self.pos_tex = make_texture_1d(self.n_verts, pos_data)
        self.prev_pos_tex = make_texture_1d(self.n_verts, pos_data)
        self.temp_pos_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4))
        self.pin_displacements_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4))
        self.pin_displacements_data = [0.0] * (self.n_verts * 4)

        # 2. 法线缓冲区
        self.normals_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4))
        self.face_normals_tex = make_texture_1d(self.n_tris, [0.0] * (self.n_tris * 4))
        
        flat_triangles = []
        for v0, v1, v2 in triangles:
            flat_triangles.extend([float(v0), float(v1), float(v2), 0.0])
        self.triangles_tex = make_texture_1d(self.n_tris, flat_triangles)
        
        v_tri_headers, v_tri_indices = pack_vertex_triangles(self.n_verts, triangles)
        self.v_tri_headers_tex = make_texture_1d(self.n_verts, v_tri_headers)
        self.v_tri_indices_tex = make_texture_1d(len(v_tri_indices) // 4, v_tri_indices)

        # 3. 编译计算着色器
        self.shader_integrate = compile_compute_shader("integrate.glsl", [
            ('INT', 'n_verts'),
            ('FLOAT', 'damping'),
            ('INT', 'use_mask'),
            ('INT', 'invert_mask'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_prev_pos', {'READ', 'WRITE'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_temp_pos', {'READ', 'WRITE'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_pin_displacements', {'READ'}),
            (4, 'RGBA32F', 'FLOAT_2D', 'img_simulation_mask', {'READ'}),
        ])
        
        self.shader_spring_force = compile_compute_shader("spring_force.glsl", [
            ('INT', 'n_verts'),
            ('FLOAT', 'stiffness'),
            ('INT', 'use_plasticity'),
            ('FLOAT', 'deform_update'),
            ('FLOAT', 'deform_restore'),
            ('FLOAT', 'min_deform'),
            ('FLOAT', 'max_deform'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_temp_pos', {'WRITE'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_headers', {'READ'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_links', {'READ', 'WRITE'}),
        ])
        
        self.shader_smooth = compile_compute_shader("smooth.glsl", [
            ('INT', 'n_verts'),
            ('FLOAT', 'factor'),
            ('INT', 'mode'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_temp_pos', {'WRITE'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_headers', {'READ'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_links', {'READ'}),
            (4, 'RGBA32F', 'FLOAT_2D', 'img_normals', {'READ'}),
            (5, 'RGBA32F', 'FLOAT_2D', 'img_ternary_headers', {'READ'}),
            (6, 'RGBA32F', 'FLOAT_2D', 'img_ternary_links', {'READ'}),
        ])
        
        self.shader_quad_smooth = compile_compute_shader("quad_smooth.glsl", [
            ('INT', 'n_verts'),
            ('FLOAT', 'factor'),
            ('FLOAT', 'max_ratio'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_temp_pos', {'WRITE'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_quad_indices', {'READ'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_quad_params', {'READ'}),
            (4, 'RGBA32F', 'FLOAT_2D', 'img_vertex_quad_headers', {'READ'}),
            (5, 'RGBA32F', 'FLOAT_2D', 'img_vertex_quad_links', {'READ'}),
        ])

        self.shader_snap_solver = compile_compute_shader("snap_solver.glsl", [
            ('INT', 'n_verts'),
            ('FLOAT', 'snapping_force'),
            ('INT', 'use_mask'),
            ('INT', 'invert_mask'),
            ('INT', 'snapping_mode'),
            ('INT', 'snap_count'),
            ('INT', 'cycle_quality'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_vert_normals', {'READ'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_snap_points', {'READ'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_snap_normals', {'READ'}),
            (4, 'RGBA32F', 'FLOAT_2D', 'img_snapping_mask', {'READ'}),
        ])

        self.shader_update_normals = compile_compute_shader("update_normals.glsl", [
            ('INT', 'n_items'),
            ('INT', 'mode'),
            ('FLOAT', 'lerp_factor'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_face_normals', {'READ', 'WRITE'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_vert_normals', {'READ', 'WRITE'}),
            (3, 'RGBA32F', 'FLOAT_2D', 'img_triangles', {'READ'}),
            (4, 'RGBA32F', 'FLOAT_2D', 'img_vert_tri_headers', {'READ'}),
            (5, 'RGBA32F', 'FLOAT_2D', 'img_vert_tri_indices', {'READ'}),
        ])
        
        self.shader_mirror = compile_compute_shader("mirror.glsl", [
            ('INT', 'n_verts'),
            ('INT', 'mirror_x'),
            ('INT', 'mirror_y'),
            ('INT', 'mirror_z'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_symm_map', {'READ'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_temp_pos', {'READ', 'WRITE'}),
        ])
        
        self.shader_copy_pos = compile_compute_shader("copy_pos.glsl", [
            ('INT', 'n_verts'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_src', {'READ'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_dst', {'WRITE'}),
        ])
        
        self.shader_masked_mix = compile_compute_shader("masked_mix.glsl", [
            ('INT', 'n_verts'),
            ('INT', 'invert_mask'),
            ('FLOAT', 'factor'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_old_pos', {'READ'}),
            (2, 'RGBA32F', 'FLOAT_2D', 'img_mask', {'READ'}),
        ])
        
        self.shader_apply_displacements = compile_compute_shader("apply_displacements.glsl", [
            ('INT', 'n_verts'),
        ], [
            (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
            (1, 'RGBA32F', 'FLOAT_2D', 'img_displacements', {'READ'}),
        ])
        
        # 4. 初始化吸附模块
        self.target_bvh = target_bvh
        self.bvh_closest_indexes = [-1] * self.n_verts
        self.snap_points_data = [0.0] * (self.n_verts * 4)
        self.snap_normals_data = [0.0] * (self.n_verts * 4)
        
        # 预先计算初始坐标的最近吸附点以预热缓存，防止在未重叠时初始帧向原点(0,0,0)塌陷
        if self.target_bvh:
            coords = read_texture_flat(self.pos_tex)
            for i in range(self.n_verts):
                pos_i = Vector((coords[i*4], coords[i*4+1], coords[i*4+2]))
                nearest = self.target_bvh.find_nearest(pos_i)
                if nearest:
                    loc, norm, tri_idx, dist = nearest
                    self.bvh_closest_indexes[i] = tri_idx
                    self.snap_points_data[i*4] = loc[0]
                    self.snap_points_data[i*4+1] = loc[1]
                    self.snap_points_data[i*4+2] = loc[2]
                    self.snap_normals_data[i*4] = norm[0]
                    self.snap_normals_data[i*4+1] = norm[1]
                    self.snap_normals_data[i*4+2] = norm[2]

        self.snap_points_tex = make_texture_1d(self.n_verts, self.snap_points_data)
        self.snap_normals_tex = make_texture_1d(self.n_verts, self.snap_normals_data)
        self.snap_count = 0
        
        # 5. 初始化 Mask
        self.simulation_mask_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4)) # Default to 0.0, will be bypassed when empty anyway
        self.snapping_mask_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4))
        self.simulation_mask_invert = False
        self.snapping_mask_invert = False
        self.simulation_mask_empty = True
        self.snapping_mask_empty = True
        self.old_pos_tex = make_texture_1d(self.n_verts, [0.0] * (self.n_verts * 4))
        
        # 默认初始化法线
        self.update_mesh_normals(1.0)

    def __len__(self):
        return self.n_verts * 3

    def from_list(self, vdata):
        pos_data = []
        for i in range(self.n_verts):
            pos_data.extend([vdata[i*3], vdata[i*3+1], vdata[i*3+2], 1.0])
        self.pos_tex = make_texture_1d(self.n_verts, pos_data)
        self.prev_pos_tex = make_texture_1d(self.n_verts, pos_data)
        self.bvh_closest_indexes = [-1] * self.n_verts
        
        # 重新预热吸附缓存以确保重置模拟时有正确的最近点
        if self.target_bvh:
            for i in range(self.n_verts):
                pos_i = Vector((pos_data[i*4], pos_data[i*4+1], pos_data[i*4+2]))
                nearest = self.target_bvh.find_nearest(pos_i)
                if nearest:
                    loc, norm, tri_idx, dist = nearest
                    self.bvh_closest_indexes[i] = tri_idx
                    self.snap_points_data[i*4] = loc[0]
                    self.snap_points_data[i*4+1] = loc[1]
                    self.snap_points_data[i*4+2] = loc[2]
                    self.snap_normals_data[i*4] = norm[0]
                    self.snap_normals_data[i*4+1] = norm[1]
                    self.snap_normals_data[i*4+2] = norm[2]
            self.snap_points_tex = make_texture_1d(self.n_verts, self.snap_points_data)
            self.snap_normals_tex = make_texture_1d(self.n_verts, self.snap_normals_data)
            
        self.update_mesh_normals(1.0)

    def get_verts(self, indexes):
        coords = read_texture_flat(self.pos_tex)
        ret = []
        for idx in indexes:
            ret.append((coords[idx*4], coords[idx*4+1], coords[idx*4+2]))
        return ret

    def read_positions(self):
        coords = read_texture_flat(self.pos_tex)
        out = [0.0] * (self.n_verts * 3)
        for i in range(self.n_verts):
            out[i*3] = coords[i*4]
            out[i*3+1] = coords[i*4+1]
            out[i*3+2] = coords[i*4+2]
        return out

    def kinetic_step(self, damping):
        # 写入控制钉位移
        self.pin_displacements_tex = make_texture_1d(self.n_verts, self.pin_displacements_data)
        
        self.shader_integrate.bind()
        self.shader_integrate.image('img_pos', self.pos_tex)
        self.shader_integrate.image('img_prev_pos', self.prev_pos_tex)
        self.shader_integrate.image('img_temp_pos', self.temp_pos_tex)
        self.shader_integrate.image('img_pin_displacements', self.pin_displacements_tex)
        self.shader_integrate.image('img_simulation_mask', self.simulation_mask_tex)
        
        self.shader_integrate.uniform_int("n_verts", self.n_verts)
        self.shader_integrate.uniform_float("damping", damping)
        self.shader_integrate.uniform_int("use_mask", 0)
        self.shader_integrate.uniform_int("invert_mask", 1 if self.simulation_mask_invert else 0)
        
        gpu.compute.dispatch(self.shader_integrate, (self.n_verts + 255) // 256, 1, 1)
        
        # 重置控制钉位移
        self.pin_displacements_data = [0.0] * (self.n_verts * 4)

    def save_pos_for_mask(self):
        self.shader_copy_pos.bind()
        self.shader_copy_pos.image('img_src', self.pos_tex)
        self.shader_copy_pos.image('img_dst', self.old_pos_tex)
        self.shader_copy_pos.uniform_int("n_verts", self.n_verts)
        gpu.compute.dispatch(self.shader_copy_pos, (self.n_verts + 255) // 256, 1, 1)

    def apply_simulation_mask_mix(self, factor, invert):
        if getattr(self, 'simulation_mask_empty', True):
            return
        self.shader_masked_mix.bind()
        self.shader_masked_mix.image('img_pos', self.pos_tex)
        self.shader_masked_mix.image('img_old_pos', self.old_pos_tex)
        self.shader_masked_mix.image('img_mask', self.simulation_mask_tex)
        self.shader_masked_mix.uniform_int("n_verts", self.n_verts)
        self.shader_masked_mix.uniform_int("invert_mask", 1 if invert else 0)
        self.shader_masked_mix.uniform_float("factor", factor)
        gpu.compute.dispatch(self.shader_masked_mix, (self.n_verts + 255) // 256, 1, 1)

    def apply_snapping_mask_mix(self, factor, invert):
        if getattr(self, 'snapping_mask_empty', True):
            return
        self.shader_masked_mix.bind()
        self.shader_masked_mix.image('img_pos', self.pos_tex)
        self.shader_masked_mix.image('img_old_pos', self.old_pos_tex)
        self.shader_masked_mix.image('img_mask', self.snapping_mask_tex)
        self.shader_masked_mix.uniform_int("n_verts", self.n_verts)
        self.shader_masked_mix.uniform_int("invert_mask", 1 if invert else 0)
        self.shader_masked_mix.uniform_float("factor", factor)
        gpu.compute.dispatch(self.shader_masked_mix, (self.n_verts + 255) // 256, 1, 1)
    def apply_pin_displacements(self):
        self.pin_displacements_tex = make_texture_1d(self.n_verts, self.pin_displacements_data)
        self.shader_apply_displacements.bind()
        self.shader_apply_displacements.image('img_pos', self.pos_tex)
        self.shader_apply_displacements.image('img_displacements', self.pin_displacements_tex)
        self.shader_apply_displacements.uniform_int("n_verts", self.n_verts)
        gpu.compute.dispatch(self.shader_apply_displacements, (self.n_verts + 255) // 256, 1, 1)
        self.pin_displacements_data = [0.0] * (self.n_verts * 4)

    def update_mesh_normals(self, factor):
        # Pass 1: 计算 Face Normals
        n_tris = self.n_tris
        self.shader_update_normals.bind()
        self.shader_update_normals.image('img_pos', self.pos_tex)
        self.shader_update_normals.image('img_face_normals', self.face_normals_tex)
        self.shader_update_normals.image('img_triangles', self.triangles_tex)
        # Bind remaining unused declared images to valid textures to avoid Vulkan unbound descriptor crash
        self.shader_update_normals.image('img_vert_normals', self.normals_tex)
        self.shader_update_normals.image('img_vert_tri_headers', self.v_tri_headers_tex)
        self.shader_update_normals.image('img_vert_tri_indices', self.v_tri_indices_tex)
        
        self.shader_update_normals.uniform_int("n_items", n_tris)
        self.shader_update_normals.uniform_int("mode", 0)
        gpu.compute.dispatch(self.shader_update_normals, (n_tris + 255) // 256, 1, 1)

        # Pass 2: 计算 Vertex Normals
        self.shader_update_normals.bind()
        self.shader_update_normals.image('img_face_normals', self.face_normals_tex)
        self.shader_update_normals.image('img_vert_normals', self.normals_tex)
        self.shader_update_normals.image('img_vert_tri_headers', self.v_tri_headers_tex)
        self.shader_update_normals.image('img_vert_tri_indices', self.v_tri_indices_tex)
        # Bind remaining unused declared images to valid textures to avoid Vulkan unbound descriptor crash
        self.shader_update_normals.image('img_pos', self.pos_tex)
        self.shader_update_normals.image('img_triangles', self.triangles_tex)
        
        self.shader_update_normals.uniform_int("n_items", self.n_verts)
        self.shader_update_normals.uniform_int("mode", 1)
        self.shader_update_normals.uniform_float("lerp_factor", factor)
        gpu.compute.dispatch(self.shader_update_normals, (self.n_verts + 255) // 256, 1, 1)

    def snap_to_bvh(self, snapping_force, cycle_quality, snapping_mode='SURFACE'):
        if not self.target_bvh:
            return
            
        self.snap_count += 1
        cycle_quality = max(cycle_quality, 1)
        
        # 分时更新，使用 32 位无符号整数模拟以对齐 GLSL 着色器中的哈希运算
        indices_to_update = []
        for i in range(self.n_verts):
            cycle = ((i ^ 0x243F6A88) * 0x243F6A88) & 0xffffffff
            cycle = (cycle ^ (cycle >> 5)) & 0xffffffff
            cycle = (cycle + self.snap_count) & 0xffffffff
            if cycle % cycle_quality == 0 or self.bvh_closest_indexes[i] < 0:
                indices_to_update.append(i)
        
        if indices_to_update:
            coords = read_texture_flat(self.pos_tex)
            
            for i in indices_to_update:
                pos_i = Vector((coords[i*4], coords[i*4+1], coords[i*4+2]))
                nearest = self.target_bvh.find_nearest(pos_i)
                if nearest:
                    loc, norm, tri_idx, dist = nearest
                    self.bvh_closest_indexes[i] = tri_idx
                    self.snap_points_data[i*4] = loc[0]
                    self.snap_points_data[i*4+1] = loc[1]
                    self.snap_points_data[i*4+2] = loc[2]
                    self.snap_normals_data[i*4] = norm[0]
                    self.snap_normals_data[i*4+1] = norm[1]
                    self.snap_normals_data[i*4+2] = norm[2]
                    
            self.snap_points_tex = make_texture_1d(self.n_verts, self.snap_points_data)
            self.snap_normals_tex = make_texture_1d(self.n_verts, self.snap_normals_data)

        # 调度 GPU Snapping Compute Shader
        self.shader_snap_solver.bind()
        self.shader_snap_solver.image('img_pos', self.pos_tex)
        self.shader_snap_solver.image('img_vert_normals', self.normals_tex)
        self.shader_snap_solver.image('img_snap_points', self.snap_points_tex)
        self.shader_snap_solver.image('img_snap_normals', self.snap_normals_tex)
        self.shader_snap_solver.image('img_snapping_mask', self.snapping_mask_tex)
        
        self.shader_snap_solver.uniform_int("n_verts", self.n_verts)
        self.shader_snap_solver.uniform_float("snapping_force", snapping_force)
        self.shader_snap_solver.uniform_int("use_mask", 0)
        self.shader_snap_solver.uniform_int("invert_mask", 1 if self.snapping_mask_invert else 0)
        
        mode_val = 1
        if snapping_mode == 'OUTSIDE':
            mode_val = 2
        elif snapping_mode == 'INSIDE':
            mode_val = 4
        self.shader_snap_solver.uniform_int("snapping_mode", mode_val)
        self.shader_snap_solver.uniform_int("snap_count", self.snap_count)
        self.shader_snap_solver.uniform_int("cycle_quality", cycle_quality)
        
        gpu.compute.dispatch(self.shader_snap_solver, (self.n_verts + 255) // 256, 1, 1)

    def create_spring_group(self, bm, spring_indices):
        coords = read_texture_flat(self.pos_tex)
        headers, links, arranged_links = pack_spring_links(self.n_verts, coords, spring_indices)
        return GPUSpringLinks(self, headers, links, arranged_links)

    def create_ternary_links(self, bm, ternary_indices):
        coords = read_texture_flat(self.pos_tex)
        normals = read_texture_flat(self.normals_tex)
        headers, links = pack_ternary_links(self.n_verts, coords, normals, ternary_indices)
        return GPUTernaryLinks(self, headers, links, ternary_indices)

    def create_quaternary_links(self, bm, quad_indices):
        coords = read_texture_flat(self.pos_tex)
        flat_indices, flat_params, headers, v_links = pack_quaternary_links(self.n_verts, coords, quad_indices)
        return GPUQuaternaryLinks(self, flat_indices, flat_params, headers, v_links, quad_indices)

    def create_symmetry_map(self, S):
        return GPUSymmetryMap(self, S)

    def create_mask(self, mask_list):
        return GPUMask(self, mask_list)


class GPUSpringLinks:
    def __init__(self, engine, headers, links, arranged_links):
        self.engine = engine
        self.headers_tex = make_texture_1d(len(headers) // 4, headers)
        self.links_tex = make_texture_1d(len(links) // 4, links)
        self.arranged_links = arranged_links

    def lengths_update(self):
        coords = read_texture_flat(self.engine.pos_tex)
        links = []
        for i in range(self.engine.n_verts):
            p_i = Vector(coords[i*4 : i*4+3])
            for neighbor in self.arranged_links[i]:
                p_n = Vector(coords[neighbor*4 : neighbor*4+3])
                rest_length = (p_i - p_n).length
                links.extend([float(neighbor), rest_length, 1.0, 0.0])
        self.links_tex = make_texture_1d(len(links) // 4, links)

    def soft_spring_force(self, factor, deform_update, deform_restore, min_deform, max_deform):
        self.engine.shader_spring_force.bind()
        self.engine.shader_spring_force.image('img_pos', self.engine.pos_tex)
        self.engine.shader_spring_force.image('img_temp_pos', self.engine.temp_pos_tex)
        self.engine.shader_spring_force.image('img_headers', self.headers_tex)
        self.engine.shader_spring_force.image('img_links', self.links_tex)
        
        self.engine.shader_spring_force.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_spring_force.uniform_float("stiffness", factor)
        self.engine.shader_spring_force.uniform_int("use_plasticity", 1)
        self.engine.shader_spring_force.uniform_float("deform_update", deform_update)
        self.engine.shader_spring_force.uniform_float("deform_restore", deform_restore)
        self.engine.shader_spring_force.uniform_float("min_deform", min_deform)
        self.engine.shader_spring_force.uniform_float("max_deform", max_deform)
        
        gpu.compute.dispatch(self.engine.shader_spring_force, (self.engine.n_verts + 255) // 256, 1, 1)
        
        # 零拷贝交换缓冲区
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex

    def stiff_spring_force(self, factor):
        self.engine.shader_spring_force.bind()
        self.engine.shader_spring_force.image('img_pos', self.engine.pos_tex)
        self.engine.shader_spring_force.image('img_temp_pos', self.engine.temp_pos_tex)
        self.engine.shader_spring_force.image('img_headers', self.headers_tex)
        self.engine.shader_spring_force.image('img_links', self.links_tex)
        
        self.engine.shader_spring_force.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_spring_force.uniform_float("stiffness", factor)
        self.engine.shader_spring_force.uniform_int("use_plasticity", 0)
        
        gpu.compute.dispatch(self.engine.shader_spring_force, (self.engine.n_verts + 255) // 256, 1, 1)
        
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex

    def smooth(self, factor):
        self.engine.shader_smooth.bind()
        self.engine.shader_smooth.image('img_pos', self.engine.pos_tex)
        self.engine.shader_smooth.image('img_temp_pos', self.engine.temp_pos_tex)
        self.engine.shader_smooth.image('img_headers', self.headers_tex)
        self.engine.shader_smooth.image('img_links', self.links_tex)
        # Bind remaining unused declared images to valid textures to avoid Vulkan unbound descriptor crash
        self.engine.shader_smooth.image('img_normals', self.engine.normals_tex)
        self.engine.shader_smooth.image('img_ternary_headers', self.headers_tex)
        self.engine.shader_smooth.image('img_ternary_links', self.links_tex)
        
        self.engine.shader_smooth.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_smooth.uniform_float("factor", factor)
        self.engine.shader_smooth.uniform_int("mode", 0)
        
        gpu.compute.dispatch(self.engine.shader_smooth, (self.engine.n_verts + 255) // 256, 1, 1)
        
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex

    def __getitem__(self, index):
        class CPUProbe:
            def __init__(self, links, idx):
                self.links = links
                self.idx = idx
            @property
            def avg_radius(self):
                # 快速在 CPU 计算邻近弹簧的平均长度
                headers = read_texture_flat(self.links.headers_tex)
                start = int(headers[self.idx*4])
                count = int(headers[self.idx*4+1])
                if count == 0:
                    return 0.1
                flat_links = read_texture_flat(self.links.links_tex)
                tot = 0.0
                for j in range(count):
                    tot += flat_links[(start+j)*4 + 1]
                return tot / count
        return CPUProbe(self, index)


class GPUTernaryLinks:
    def __init__(self, engine, headers, links, ternary_indices):
        self.engine = engine
        self.headers_tex = make_texture_1d(len(headers) // 4, headers)
        self.links_tex = make_texture_1d(len(links) // 4, links)
        self.ternary_indices = ternary_indices

    def displacements_update(self):
        coords = read_texture_flat(self.engine.pos_tex)
        normals = read_texture_flat(self.engine.normals_tex)
        headers, links = pack_ternary_links(self.engine.n_verts, coords, normals, self.ternary_indices)
        self.headers_tex = make_texture_1d(len(headers) // 4, headers)
        self.links_tex = make_texture_1d(len(links) // 4, links)

    def displacement_force(self, factor):
        self.engine.shader_smooth.bind()
        self.engine.shader_smooth.image('img_pos', self.engine.pos_tex)
        self.engine.shader_smooth.image('img_temp_pos', self.engine.temp_pos_tex)
        self.engine.shader_smooth.image('img_normals', self.engine.normals_tex)
        self.engine.shader_smooth.image('img_ternary_headers', self.headers_tex)
        self.engine.shader_smooth.image('img_ternary_links', self.links_tex)
        # Bind remaining unused declared images to valid textures to avoid Vulkan unbound descriptor crash
        self.engine.shader_smooth.image('img_headers', self.headers_tex)
        self.engine.shader_smooth.image('img_links', self.links_tex)
        
        self.engine.shader_smooth.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_smooth.uniform_float("factor", factor)
        self.engine.shader_smooth.uniform_int("mode", 1)
        
        gpu.compute.dispatch(self.engine.shader_smooth, (self.engine.n_verts + 255) // 256, 1, 1)
        
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex


class GPUQuaternaryLinks:
    def __init__(self, engine, flat_indices, flat_params, headers, v_links, quad_indices):
        self.engine = engine
        self.quad_indices_tex = make_texture_1d(len(flat_indices) // 4, flat_indices)
        self.quad_params_tex = make_texture_1d(len(flat_params) // 4, flat_params)
        self.vertex_headers_tex = make_texture_1d(len(headers) // 4, headers)
        self.vertex_links_tex = make_texture_1d(len(v_links) // 4, v_links)
        self.quad_indices = quad_indices

    def lengths_update(self):
        coords = read_texture_flat(self.engine.pos_tex)
        flat_indices, flat_params, headers, v_links = pack_quaternary_links(self.engine.n_verts, coords, self.quad_indices)
        self.quad_params_tex = make_texture_1d(len(flat_params) // 4, flat_params)

    def smooth(self, factor):
        self.engine.shader_quad_smooth.bind()
        self.engine.shader_quad_smooth.image('img_pos', self.engine.pos_tex)
        self.engine.shader_quad_smooth.image('img_temp_pos', self.engine.temp_pos_tex)
        self.engine.shader_quad_smooth.image('img_quad_indices', self.quad_indices_tex)
        self.engine.shader_quad_smooth.image('img_quad_params', self.quad_params_tex)
        self.engine.shader_quad_smooth.image('img_vertex_quad_headers', self.vertex_headers_tex)
        self.engine.shader_quad_smooth.image('img_vertex_quad_links', self.vertex_links_tex)
        
        self.engine.shader_quad_smooth.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_quad_smooth.uniform_float("factor", factor)
        self.engine.shader_quad_smooth.uniform_float("max_ratio", 3.0)
        
        gpu.compute.dispatch(self.engine.shader_quad_smooth, (self.engine.n_verts + 255) // 256, 1, 1)
        
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex


class GPUSymmetryMap:
    def __init__(self, engine, S):
        self.engine = engine
        # 计算双侧对称映射（在 CPU 侧用 BVHTree 初始化一次）
        self.symm_map_data = [0.0] * (self.engine.n_verts * 4)
        self.error = [0.0, 0.0, 0.0]
        
        # 构建源网格真实的 BVHTree 以对齐 CPU 对称映射逻辑
        coords = engine.read_positions()
        verts_vec = [Vector(coords[i*3:i*3+3]) for i in range(self.engine.n_verts)]
        bvh = BVHTree.FromPolygons(verts_vec, self.engine.triangles)
        
        for i in range(self.engine.n_verts):
            mapped_indices = [i, i, i]
            for axis in range(3):
                v = Vector(coords[i*3:i*3+3])
                v[axis] = -v[axis]
                nearest = bvh.find_nearest(v)
                if nearest:
                    tri_idx = nearest[2]
                    # 获取该最近三角形的三个顶点索引
                    tri_verts = self.engine.triangles[tri_idx]
                    best_v_idx = tri_verts[0]
                    best_dist = (verts_vec[best_v_idx] - v).length
                    for vert_idx in tri_verts[1:]:
                        d_val = (verts_vec[vert_idx] - v).length
                        if d_val < best_dist:
                            best_dist = d_val
                            best_v_idx = vert_idx
                    mapped_indices[axis] = best_v_idx
                    self.error[axis] = max(self.error[axis], best_dist)
            self.symm_map_data[i*4 : i*4+3] = [float(mapped_indices[0]), float(mapped_indices[1]), float(mapped_indices[2])]
            
        self.symm_map_tex = make_texture_1d(self.engine.n_verts, self.symm_map_data)

    def mirror(self, x, y, z):
        if not (x or y or z):
            return
        self.engine.shader_mirror.bind()
        self.engine.shader_mirror.image('img_pos', self.engine.pos_tex)
        self.engine.shader_mirror.image('img_symm_map', self.symm_map_tex)
        self.engine.shader_mirror.image('img_temp_pos', self.engine.temp_pos_tex)
        
        self.engine.shader_mirror.uniform_int("n_verts", self.engine.n_verts)
        self.engine.shader_mirror.uniform_int("mirror_x", 1 if x else 0)
        self.engine.shader_mirror.uniform_int("mirror_y", 1 if y else 0)
        self.engine.shader_mirror.uniform_int("mirror_z", 1 if z else 0)
        
        gpu.compute.dispatch(self.engine.shader_mirror, (self.engine.n_verts + 255) // 256, 1, 1)
        self.engine.pos_tex, self.engine.temp_pos_tex = self.engine.temp_pos_tex, self.engine.pos_tex

    def __getitem__(self, idx):
        # 用于警告检测对称偏差
        return [int(self.symm_map_data[idx*4]), int(self.symm_map_data[idx*4+1]), int(self.symm_map_data[idx*4+2])]


class GPUMask:
    def __init__(self, engine, mask_list):
        self.engine = engine
        self.mask_list = mask_list
        self.is_empty = (mask_list is None)
        flat_data = []
        if mask_list:
            for v in mask_list:
                flat_data.extend([v, 0.0, 0.0, 0.0])
        else:
            flat_data = [0.0] * (self.engine.n_verts * 4)
        self.tex = make_texture_1d(self.engine.n_verts, flat_data)

    def masked_context(self, invert=False):
        # 保存遮罩上下文配置（给引擎运算用）
        class MaskContext:
            def __init__(self, parent, invert):
                self.parent = parent
                self.invert = invert
            def __enter__(self):
                # 记录配置
                pass
            def __exit__(self, type, value, traceback):
                pass
        return MaskContext(self, invert)

    def __getitem__(self, index):
        if not self.mask_list:
            return 0.0
        return self.mask_list[index]
