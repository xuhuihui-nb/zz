import sys
import os
import bpy
import bmesh
import array

# Add the addon directory to path
addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(addon_dir)

from softwrap2.core.gpu_engine import GPUSpringEngine

log_path = os.path.join(os.path.dirname(__file__), "sim_progress.log")
def log(msg):
    print(msg)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def run_test():
    if os.path.exists(log_path):
        os.remove(log_path)
        
    log("Creating dummy mesh...")
    bpy.ops.mesh.primitive_cube_add(size=2, enter_editmode=False, align='WORLD', location=(0, 0, 0))
    source_ob = bpy.context.active_object
    
    # Subdivide it
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=2)
    bpy.ops.object.editmode_toggle()
    
    bm = bmesh.new()
    bm.from_mesh(source_ob.data)
    
    n_verts = len(bm.verts)
    log(f"Num vertices: {n_verts}")
    
    verts_coords = [0.0] * (n_verts * 3)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        verts_coords[v.index * 3 : v.index * 3 + 3] = v.co
        
    triangles = []
    for face in bm.faces:
        for i in range(len(face.verts) - 2):
            triangles.append((face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index))
            
    # Create target BVH (using same mesh for testing)
    from mathutils.bvhtree import BVHTree
    verts_vec = [v.co.copy() for v in bm.verts]
    dummy_tris = []
    for f in bm.faces:
        for i in range(len(f.verts) - 2):
            dummy_tris.append((f.verts[0].index, f.verts[i+1].index, f.verts[i+2].index))
    target_bvh = BVHTree.FromPolygons(verts_vec, dummy_tris)
    
    log("Initializing GPUSpringEngine...")
    engine = GPUSpringEngine(verts_coords, triangles, target_bvh)
    
    # Create spring groups (dummy indices)
    log("Creating spring groups...")
    from softwrap2.__init__ import structural_springs_indexes, shear_spring_indexes, bending_spring_indexes, ternary_links_indexes, quaternary_link_indexes
    
    struct_idx = structural_springs_indexes(bm)
    shear_idx = shear_spring_indexes(bm)
    bend_idx = bending_spring_indexes(bm, 3)
    ternary_idx = ternary_links_indexes(bm)
    quad_idx = quaternary_link_indexes(bm)
    
    log("Instantiating link objects...")
    structural_springs = engine.create_spring_group(bm, struct_idx)
    shear_springs = engine.create_spring_group(bm, shear_idx)
    bending_springs = engine.create_spring_group(bm, bend_idx)
    ternary_links = engine.create_ternary_links(bm, ternary_idx)
    quaternary_links = engine.create_quaternary_links(bm, quad_idx)
    
    log("Running quaternary_links.smooth...")
    quaternary_links.smooth(0.1)
    
    log("Running shear_springs.soft_spring_force...")
    shear_springs.soft_spring_force(0.5, 0.1, 0.05, 0.3, 3.0)
    
    log("Running bending_springs.soft_spring_force...")
    bending_springs.soft_spring_force(0.5, 0.1, 0.05, 0.3, 3.0)
    
    log("Running structural_springs.soft_spring_force...")
    structural_springs.soft_spring_force(0.5, 0.1, 0.05, 0.3, 3.0)
    
    log("Running kinetic_step...")
    engine.kinetic_step(0.75)
    
    log("Running snap_to_bvh...")
    engine.snap_to_bvh(0.5, 1, 'SURFACE')
    
    log("Running update_mesh_normals...")
    engine.update_mesh_normals(1.0)
    
    log("Running symmetry map...")
    symm = engine.create_symmetry_map(None)
    symm.mirror(True, False, False)
    
    log("Test completed successfully without crash!")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        log(f"Python exception occurred:\n{err_msg}")
    finally:
        bpy.ops.wm.quit_blender()
