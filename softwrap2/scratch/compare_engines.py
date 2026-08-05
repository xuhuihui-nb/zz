import sys
import os
import bpy
import bmesh
from mathutils import Vector
from collections import defaultdict

# Add current and backup directories to sys.path
addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.dirname(addon_dir))
sys.path.append(r"D:\桌面\暂存\softwrap2")

import softwrap_core2 as core
from softwrap2.core.gpu_engine import GPUSpringEngine

def loop_pairs(lst):
    n = len(lst)
    for i in range(n):
        yield lst[i], lst[(i + 1) % n]
        yield lst[i], lst[(i + 2) % n]

def structural_springs_indexes(bm):
    return [tuple(v.index for v in edge.verts) for edge in bm.edges]

def shear_spring_indexes(bm):
    return [tuple(v.index for v in pair) for face in bm.faces for pair in loop_pairs(face.verts)]

def bending_spring_indexes(bm, distance=1):
    distance = max(distance, 1)
    springs = {}
    links_by_edge = defaultdict(list)
    for vert in bm.verts:
        for loop in vert.link_loops:
            edge = loop.edge
            links_by_edge[edge].append([])
            for _ in range(distance):
                loop = loop.link_loop_next
                for _ in range(len(loop.vert.link_edges) // 2 - 1):
                    loop = loop.link_loop_radial_next.link_loop_next
                other = loop.vert
                if vert.index == other.index:
                    continue
                spr = frozenset((vert.index, other.index))
                if spr not in springs:
                    springs[spr] = 1
                links_by_edge[edge][-1].append(len(springs) - 1)
    return [tuple(k) for k in springs.keys()]

def ternary_links_indexes(bm):
    links = []
    for vert in bm.verts:
        for edge in vert.link_edges:
            other = edge.other_vert(vert)
            for face in edge.link_faces:
                for loop in face.loops:
                    if loop.vert == other:
                        loop = loop.link_loop_next
                        if loop.vert != vert:
                            links.append((vert.index, other.index, loop.vert.index))
    return links

def quaternary_link_indexes(bm):
    links = []
    for face in bm.faces:
        if len(face.verts) == 4:
            a, b, c, d = (v.index for v in face.verts)
            links.append((a, c, b, d))
    return links

def run_comparison():
    print("---------------------------------------------")
    print("Starting CPU vs GPU Engine Mathematical Comparison...")
    
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
    print(f"Mesh created. Vertices: {n_verts}, Edges: {len(bm.edges)}, Faces: {len(bm.faces)}")
    
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
    struct_idx = structural_springs_indexes(bm)
    shear_idx = shear_spring_indexes(bm)
    bend_idx = bending_spring_indexes(bm, 3)
    ternary_idx = ternary_links_indexes(bm)
    quad_idx = quaternary_link_indexes(bm)
    
    print("Creating cpu_mesh...")
    cpu_mesh = core.Mesh([tuple(v.co) for v in bm.verts], triangles)
    print("Creating target_cpu_mesh...")
    target_cpu_mesh = core.Mesh([tuple(v) for v in verts_vec], triangles)
    print("Creating target_cpu_bvh...")
    target_cpu_bvh = core.BVH(target_cpu_mesh)
    
    # Store references globally to prevent GC
    global_refs = {'cpu_mesh': cpu_mesh, 'target_cpu_mesh': target_cpu_mesh, 'target_cpu_bvh': target_cpu_bvh}
    
    print("Creating cpu_engine...")
    cpu_engine = core.SpringEngine(cpu_mesh, target_cpu_bvh)
    print("Creating gpu_engine...")
    gpu_engine = GPUSpringEngine(verts_coords, triangles, target_bvh)
    
    # Print lengths of index lists
    print(f"struct_idx length: {len(struct_idx)}")
    print(f"shear_idx length: {len(shear_idx)}")
    print(f"bend_idx length: {len(bend_idx)}")
    print(f"ternary_idx length: {len(ternary_idx)}")
    print(f"quad_idx length: {len(quad_idx)}")

    print("Creating cpu_struct...")
    cpu_struct = cpu_engine.create_spring_group(struct_idx)
    print("Creating gpu_struct...")
    gpu_struct = gpu_engine.create_spring_group(bm, struct_idx)

    # Only create if not empty
    cpu_shear = cpu_engine.create_spring_group(shear_idx) if shear_idx else None
    gpu_shear = gpu_engine.create_spring_group(bm, shear_idx) if shear_idx else None

    cpu_bend = cpu_engine.create_spring_group(bend_idx) if bend_idx else None
    gpu_bend = gpu_engine.create_spring_group(bm, bend_idx) if bend_idx else None

    cpu_ternary = cpu_engine.create_ternary_links(ternary_idx) if ternary_idx else None
    gpu_ternary = gpu_engine.create_ternary_links(bm, ternary_idx) if ternary_idx else None

    cpu_quad = cpu_engine.create_quaternary_links(quad_idx) if quad_idx else None
    gpu_quad = gpu_engine.create_quaternary_links(bm, quad_idx) if quad_idx else None

    # Print initial position of first 3 vertices
    print("\n[Initial Coordinates]")
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")
    
    # Test 1: Quaternary Smooth
    factor = 0.5
    print("\n--- Test 1: Quaternary smooth ---")
    if cpu_quad:
        cpu_quad.smooth(factor)
        gpu_quad.smooth(factor)
    else:
        print("Skipping Quad smooth (empty)")
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")
    
    # Test 2: Soft Spring Force
    print("\n--- Test 2: Soft Spring Force ---")
    cpu_struct.soft_spring_force(0.5, 0.2, 0.01, 0.5, 1.5)
    gpu_struct.soft_spring_force(0.5, 0.2, 0.01, 0.5, 1.5)
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")
    
    # Test 3: Stiff Spring Force (Structural)
    print("\n--- Test 3: Stiff Spring Force (Structural) ---")
    cpu_struct.stiff_spring_force(0.7)
    gpu_struct.stiff_spring_force(0.7)
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")
    
    # Test 4: Kinetic Step
    print("\n--- Test 4: Kinetic Step ---")
    cpu_engine.kinetic_step(0.75)
    gpu_engine.kinetic_step(0.75)
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")
    
    # Test 5: Snap to BVH
    print("\n--- Test 5: Snap to BVH ---")
    cpu_engine.snap_to_bvh(0.5, 1, 'SURFACE')
    gpu_engine.snap_to_bvh(0.5, 1, 'SURFACE')
    print(f"CPU: {[cpu_engine[i] for i in range(9)]}")
    print(f"GPU: {gpu_engine.read_positions()[:9]}")

if __name__ == "__main__":
    try:
        run_comparison()
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
