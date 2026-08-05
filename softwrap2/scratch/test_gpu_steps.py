import sys
import os
import bpy
import bmesh
from mathutils import Vector

# Add current addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.dirname(addon_dir))

from softwrap2.core.gpu_engine import GPUSpringEngine

def test_gpu_steps():
    print("---------------------------------------------")
    print("Testing GPU Engine Steps...")
    
    # 1. Create a dummy mesh
    bpy.ops.mesh.primitive_cube_add(size=2, enter_editmode=False, align='WORLD', location=(0, 0, 0))
    source_ob = bpy.context.active_object
    
    # Subdivide once to get some vertices and faces
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=1)
    bpy.ops.object.editmode_toggle()
    
    bm = bmesh.new()
    bm.from_mesh(source_ob.data)
    n_verts = len(bm.verts)
    print(f"Mesh created. Vertices: {n_verts}")
    
    verts_coords = [0.0] * (n_verts * 3)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        verts_coords[v.index * 3 : v.index * 3 + 3] = v.co
        
    triangles = []
    for face in bm.faces:
        for i in range(len(face.verts) - 2):
            triangles.append((face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index))
            
    # Build target BVHTree (displace it slightly to have snapping force)
    from mathutils.bvhtree import BVHTree
    verts_vec = [v.co.copy() + Vector((0.2, 0.1, -0.1)) for v in bm.verts]
    target_bvh = BVHTree.FromPolygons(verts_vec, triangles)
    
    # Build Spring indices
    from softwrap2.__init__ import structural_springs_indexes
    struct_idx = structural_springs_indexes(bm)
    
    print("Initializing GPUSpringEngine...")
    gpu_engine = GPUSpringEngine(verts_coords, triangles, target_bvh)
    
    print("Creating structural springs...")
    gpu_struct = gpu_engine.create_spring_group(bm, struct_idx)
    
    # Read headers and links textures
    from softwrap2.core.gpu_engine import read_texture_flat
    headers_val = read_texture_flat(gpu_struct.headers_tex)
    links_val = read_texture_flat(gpu_struct.links_tex)
    print(f"struct_idx length: {len(struct_idx)}")
    print(f"headers (first 16 floats): {headers_val[:16]}")
    print(f"links (first 16 floats): {links_val[:16]}")
    
    # Print initial position
    print(f"Initial GPU coords (first 3 verts): {gpu_engine.read_positions()[:9]}")
    print(f"Initial normals (first 3 verts): {read_texture_flat(gpu_engine.normals_tex)[:12]}")
    
    # Call update_mesh_normals(1.0) to update normals
    gpu_engine.update_mesh_normals(1.0)
    print(f"Normals after update_mesh_normals: {read_texture_flat(gpu_engine.normals_tex)[:12]}")
    
    # Step 1: Snap to BVH (Deform the mesh)
    print("Running snap_to_bvh...")
    gpu_engine.snap_to_bvh(0.5, 1, 'SURFACE')
    coords_deformed = gpu_engine.read_positions()
    print(f"After snap_to_bvh: {coords_deformed[:9]}")
    
    # Step 2: Soft Spring Force (Should pull it back!)
    print("Running soft_spring_force...")
    gpu_struct.soft_spring_force(0.5, 0.2, 0.01, 0.5, 1.5)
    coords_after_soft = gpu_engine.read_positions()
    print(f"After soft_spring_force: {coords_after_soft[:9]}")
    
    # Check if they changed
    diffs = [abs(coords_deformed[j] - coords_after_soft[j]) for j in range(9)]
    print(f"Coordinate differences: {diffs}")
    
    # Step 3: Stiff Spring Force (Should pull it back even more!)
    print("Running stiff_spring_force...")
    gpu_struct.stiff_spring_force(0.5)
    coords_after_stiff = gpu_engine.read_positions()
    print(f"After stiff_spring_force: {coords_after_stiff[:9]}")
    
    # Check if they changed from soft
    diffs_stiff = [abs(coords_after_soft[j] - coords_after_stiff[j]) for j in range(9)]
    print(f"Coordinate differences (soft to stiff): {diffs_stiff}")
    print("---------------------------------------------")

if __name__ == "__main__":
    try:
        test_gpu_steps()
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
