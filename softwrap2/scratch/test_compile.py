import sys
import os
import traceback
import bpy
import gpu

# Add the addon directory to path
addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(addon_dir)

log_path = os.path.join(os.path.dirname(__file__), "compile_log.txt")

try:
    print("Beginning validation of all GLSL compute shaders with 2D packing...")
    
    from softwrap2.core.gpu_engine import compile_compute_shader
    
    # 1. integrate.glsl
    print("Compiling integrate.glsl...")
    compile_compute_shader("integrate.glsl", [
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
    
    # 2. spring_force.glsl
    print("Compiling spring_force.glsl...")
    compile_compute_shader("spring_force.glsl", [
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
    
    # 3. smooth.glsl
    print("Compiling smooth.glsl...")
    compile_compute_shader("smooth.glsl", [
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
    
    # 4. quad_smooth.glsl
    print("Compiling quad_smooth.glsl...")
    compile_compute_shader("quad_smooth.glsl", [
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
    
    # 5. snap_solver.glsl
    print("Compiling snap_solver.glsl...")
    compile_compute_shader("snap_solver.glsl", [
        ('INT', 'n_verts'),
        ('FLOAT', 'snapping_force'),
        ('INT', 'use_mask'),
        ('INT', 'invert_mask'),
        ('INT', 'snapping_mode'),
    ], [
        (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
        (1, 'RGBA32F', 'FLOAT_2D', 'img_vert_normals', {'READ'}),
        (2, 'RGBA32F', 'FLOAT_2D', 'img_snap_points', {'READ'}),
        (3, 'RGBA32F', 'FLOAT_2D', 'img_snap_normals', {'READ'}),
        (4, 'RGBA32F', 'FLOAT_2D', 'img_snapping_mask', {'READ'}),
    ])
    
    # 6. update_normals.glsl
    print("Compiling update_normals.glsl...")
    compile_compute_shader("update_normals.glsl", [
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
    
    # 7. mirror.glsl
    print("Compiling mirror.glsl...")
    compile_compute_shader("mirror.glsl", [
        ('INT', 'n_verts'),
        ('INT', 'mirror_x'),
        ('INT', 'mirror_y'),
        ('INT', 'mirror_z'),
    ], [
        (0, 'RGBA32F', 'FLOAT_2D', 'img_pos', {'READ', 'WRITE'}),
        (1, 'RGBA32F', 'FLOAT_2D', 'img_symm_map', {'READ'}),
    ])
    
    print("All 7 shaders compiled and validated successfully with 2D packing!")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("SUCCESS")

except Exception as e:
    err_msg = traceback.format_exc()
    print("Validation failed:")
    print(err_msg)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(err_msg)

finally:
    # Exit Blender
    bpy.ops.wm.quit_blender()
