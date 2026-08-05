import sys
import os
import bpy
import bmesh
from mathutils import Vector

# Add current addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.dirname(addon_dir))

from softwrap2.core.gpu_engine import GPUSpringEngine, read_texture_flat

class PythonSpringEngine:
    def __init__(self, verts_coords, triangles, target_bvh):
        self.n_verts = len(verts_coords) // 3
        self.verts = [Vector(verts_coords[i*3 : i*3+3]) for i in range(self.n_verts)]
        self.prev_verts = [Vector(verts_coords[i*3 : i*3+3]) for i in range(self.n_verts)]
        self.vert_normals = [Vector((0.0, 0.0, 0.0)) for _ in range(self.n_verts)]
        self.triangles = triangles
        self.n_triangles = len(triangles)
        self.face_normals = [Vector((0.0, 0.0, 0.0)) for _ in range(self.n_triangles)]
        self.target_bvh = target_bvh
        self.update_mesh_normals()

    def update_mesh_normals(self):
        # 1. Compute face normals
        for i, (v0, v1, v2) in enumerate(self.triangles):
            a = self.verts[v0]
            b = self.verts[v1]
            c = self.verts[v2]
            cr = (b - a).cross(c - a)
            self.face_normals[i] = cr.normalized() if cr.length > 1e-6 else Vector((0,0,0))
            
        # 2. Compute vertex normals
        self.vert_normals = [Vector((0.0, 0.0, 0.0)) for _ in range(self.n_verts)]
        for i, (v0, v1, v2) in enumerate(self.triangles):
            self.vert_normals[v0] += self.face_normals[i]
            self.vert_normals[v1] += self.face_normals[i]
            self.vert_normals[v2] += self.face_normals[i]
            
        for i in range(self.n_verts):
            if self.vert_normals[i].length > 1e-6:
                self.vert_normals[i].normalize()

    def kinetic_step(self, damping):
        new_verts = [v.copy() for v in self.verts]
        for i in range(self.n_verts):
            new_verts[i] = self.verts[i] + (self.verts[i] - self.prev_verts[i]) * damping
            
        self.prev_verts = [v.copy() for v in self.verts]
        self.verts = new_verts

    def snap_to_bvh(self, snapping_force, cycle_quality, snapping_mode):
        new_verts = [v.copy() for v in self.verts]
        for i in range(self.n_verts):
            nearest = self.target_bvh.find_nearest(self.verts[i])
            if nearest:
                loc, norm, tri_idx, dist = nearest
                snap_vec = loc - self.verts[i]
                pn = norm
                
                if snapping_mode == 'SURFACE':
                    if snap_vec.dot(pn) > 0.0:
                        if snap_vec.dot(self.vert_normals[i]) < 0.0:
                            snap_vec = self.vert_normals[i] * snap_vec.length + snap_vec * 0.5
                            
                    dot_norm = self.vert_normals[i].dot(pn)
                    snapping_weight = dot_norm * dot_norm
                    new_verts[i] += snap_vec * snapping_force * snapping_weight
                    
        self.verts = new_verts

class PythonSpringGroup:
    def __init__(self, engine, links_idx):
        self.engine = engine
        self.links_idx = links_idx
        # Build neighbor lists
        self.neighbors = [[] for _ in range(engine.n_verts)]
        for a, b in links_idx:
            self.neighbors[a].append(b)
            self.neighbors[b].append(a)
            
        # Initialize original lengths and scales
        self.original_lengths = {}
        self.scales = {}
        for a, b in links_idx:
            dist = (engine.verts[a] - engine.verts[b]).length
            self.original_lengths[(a, b)] = dist
            self.original_lengths[(b, a)] = dist
            self.scales[(a, b)] = 1.0
            self.scales[(b, a)] = 1.0

    def soft_spring_force(self, stiffness, deform_update, deform_restore, min_deform, max_deform):
        new_verts = [v.copy() for v in self.engine.verts]
        for i in range(self.engine.n_verts):
            total_force = Vector((0.0, 0.0, 0.0))
            count = len(self.neighbors[i])
            if count == 0:
                continue
            for a in self.neighbors[i]:
                delta = self.engine.verts[i] - self.engine.verts[a]
                curr_length = max(delta.length, 1e-5)
                
                rest_len = self.original_lengths[(i, a)]
                scale = self.scales[(i, a)]
                target_length = rest_len * scale
                
                diff = (target_length - curr_length) / curr_length
                total_force += delta * diff
                
                # Update plasticity scale
                new_scale = curr_length / (rest_len + 1e-5)
                new_scale = max(min_deform, min(max_deform, new_scale))
                scale = scale + (new_scale - scale) * deform_update
                scale = scale + (1.0 - scale) * deform_restore
                self.scales[(i, a)] = scale
                
            new_verts[i] += total_force * (1.0 / count) * stiffness
        self.engine.verts = new_verts

    def stiff_spring_force(self, stiffness):
        new_verts = [v.copy() for v in self.engine.verts]
        for i in range(self.engine.n_verts):
            accum_pos = Vector((0.0, 0.0, 0.0))
            count = len(self.neighbors[i])
            if count == 0:
                continue
            for a in self.neighbors[i]:
                delta = self.engine.verts[i] - self.engine.verts[a]
                curr_length = max(delta.length, 1e-5)
                
                rest_len = self.original_lengths[(i, a)]
                scale = self.scales[(i, a)]
                
                diff = (rest_len * scale) / curr_length
                diff = 1.0 + (diff - 1.0) * stiffness
                
                accum_pos += self.engine.verts[a] + delta * diff
                
            new_verts[i] = accum_pos * (1.0 / count)
        self.engine.verts = new_verts

def run_test():
    print("---------------------------------------------")
    print("Running Python vs GPU spring engines test...")
    
    # 1. Create a dummy mesh
    bpy.ops.mesh.primitive_cube_add(size=2, enter_editmode=False, align='WORLD', location=(0, 0, 0))
    source_ob = bpy.context.active_object
    
    # Subdivide once
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=1)
    bpy.ops.object.editmode_toggle()
    
    bm = bmesh.new()
    bm.from_mesh(source_ob.data)
    n_verts = len(bm.verts)
    
    verts_coords = [0.0] * (n_verts * 3)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        verts_coords[v.index * 3 : v.index * 3 + 3] = v.co
        
    triangles = []
    for face in bm.faces:
        for i in range(len(face.verts) - 2):
            triangles.append((face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index))
            
    from mathutils.bvhtree import BVHTree
    verts_vec = [v.co.copy() + Vector((5.0, 0.0, 0.0)) for v in bm.verts]
    target_bvh = BVHTree.FromPolygons(verts_vec, triangles)
    
    from softwrap2.__init__ import structural_springs_indexes
    struct_idx = structural_springs_indexes(bm)
    
    print("Initializing engines...")
    py_engine = PythonSpringEngine(verts_coords, triangles, target_bvh)
    py_struct = PythonSpringGroup(py_engine, struct_idx)
    
    gpu_engine = GPUSpringEngine(verts_coords, triangles, target_bvh)
    gpu_struct = gpu_engine.create_spring_group(bm, struct_idx)
    
    # Step 0: Normals Comparison
    py_norm = py_engine.vert_normals[0]
    gpu_norm = Vector(read_texture_flat(gpu_engine.normals_tex)[:3])
    print(f"Vertex 0 Normal - Python: {py_norm}, GPU: {gpu_norm}, Diff: {(py_norm - gpu_norm).length}")

    # Debug vertex 23 mapping
    from softwrap2.core.gpu_engine import pack_vertex_triangles
    headers, indices = pack_vertex_triangles(gpu_engine.n_verts, triangles)
    print(f"Vertex 23 Header (start, count) - Python: {headers[23*4 : 23*4+2]}")
    start = int(headers[23*4])
    count = int(headers[23*4+1])
    py_tris = [int(indices[(start+j)*4]) for j in range(count)]
    print(f"Vertex 23 connected triangles - Python: {py_tris}")
    
    # Read GPU textures
    gpu_headers = read_texture_flat(gpu_engine.v_tri_headers_tex)
    gpu_indices = read_texture_flat(gpu_engine.v_tri_indices_tex)
    print(f"Vertex 23 Header - GPU texture: {gpu_headers[23*4 : 23*4+2]}")
    gpu_start = int(gpu_headers[23*4])
    gpu_count = int(gpu_headers[23*4+1])
    gpu_tris = [int(gpu_indices[(gpu_start+j)*4]) for j in range(gpu_count)]
    print(f"Vertex 23 connected triangles - GPU texture: {gpu_tris}")
    
    # Print the coordinates of the connected triangles
    for tri_idx in py_tris:
        print(f"Triangle {tri_idx}: {triangles[tri_idx]}")

    # Step 1: Snap
    print("Step 1: snap_to_bvh")
    py_engine.snap_to_bvh(0.5, 1, 'SURFACE')
    gpu_engine.snap_to_bvh(0.5, 1, 'SURFACE')
    
    # Print closest point from target_bvh
    py_nearest = target_bvh.find_nearest(py_engine.verts[0])
    gpu_nearest = gpu_engine.target_bvh.find_nearest(Vector(gpu_engine.read_positions()[:3]))
    print(f"Target closest point for Vertex 0 - Python: {py_nearest[0] if py_nearest else None}, GPU: {gpu_nearest[0] if gpu_nearest else None}")
    
    py_pos = [c for v in py_engine.verts for c in v]
    gpu_pos = gpu_engine.read_positions()
    print(f"Vertex 0 Position after snap - Python: {py_engine.verts[0]}, GPU: {gpu_pos[:3]}")
    diffs = [abs(py_pos[j] - gpu_pos[j]) for j in range(len(py_pos))]
    max_diff = max(diffs)
    max_diff_idx = diffs.index(max_diff) // 3
    print(f"Max diff after snap: {max_diff} at vertex {max_diff_idx}")
    print(f"Vertex {max_diff_idx} Position - Python: {py_engine.verts[max_diff_idx]}, GPU: {gpu_pos[max_diff_idx*3 : max_diff_idx*3+3]}")
    print(f"Vertex {max_diff_idx} Normal - Python: {py_engine.vert_normals[max_diff_idx]}, GPU: {read_texture_flat(gpu_engine.normals_tex)[max_diff_idx*4 : max_diff_idx*4+3]}")
    py_near = target_bvh.find_nearest(py_engine.verts[max_diff_idx])
    gpu_near = gpu_engine.target_bvh.find_nearest(Vector(gpu_engine.read_positions()[max_diff_idx*3 : max_diff_idx*3+3]))
    print(f"Vertex {max_diff_idx} Target closest point - Python: {py_near[0] if py_near else None}, GPU: {gpu_near[0] if gpu_near else None}")
    
    # Step 2: soft_spring_force
    print("Step 2: soft_spring_force")
    py_struct.soft_spring_force(0.5, 0.2, 0.01, 0.5, 1.5)
    gpu_struct.soft_spring_force(0.5, 0.2, 0.01, 0.5, 1.5)
    
    py_pos = [c for v in py_engine.verts for c in v]
    gpu_pos = gpu_engine.read_positions()
    diffs = [abs(py_pos[j] - gpu_pos[j]) for j in range(len(py_pos))]
    print(f"Max diff after soft_spring: {max(diffs)}")
    
    # Step 3: stiff_spring_force
    print("Step 3: stiff_spring_force")
    py_struct.stiff_spring_force(0.7)
    gpu_struct.stiff_spring_force(0.7)
    
    py_pos = [c for v in py_engine.verts for c in v]
    gpu_pos = gpu_engine.read_positions()
    diffs = [abs(py_pos[j] - gpu_pos[j]) for j in range(len(py_pos))]
    print(f"Max diff after stiff_spring: {max(diffs)}")
    
    # Step 4: kinetic_step
    print("Step 4: kinetic_step")
    py_engine.kinetic_step(0.75)
    gpu_engine.kinetic_step(0.75)
    
    py_pos = [c for v in py_engine.verts for c in v]
    gpu_pos = gpu_engine.read_positions()
    diffs = [abs(py_pos[j] - gpu_pos[j]) for j in range(len(py_pos))]
    print(f"Max diff after kinetic: {max(diffs)}")
    print("---------------------------------------------")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
