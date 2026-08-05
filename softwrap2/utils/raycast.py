import bpy
import bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d, location_3d_to_region_2d
from .timer import intersect_point_2d_rectangle
from .state import S, SW_SHAPE_KEY_NAME, running_op


def areas_under_mouse(context, event):
    mx, my = event.mouse_x, event.mouse_y
    areas = []
    for area in context.screen.areas:
        regions = []

        if intersect_point_2d_rectangle(mx, my, area.x, area.y, area.width, area.height):
            for region in area.regions:
                if intersect_point_2d_rectangle(mx, my, region.x, region.y, region.width, region.height):
                    regions.append(region)

        areas.append((area, regions))

    return areas


def is_mouse_over_ui(context, event):
    if not hasattr(event, 'mouse_x') or not hasattr(event, 'mouse_y'):
        return False
    mx, my = event.mouse_x, event.mouse_y
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            if intersect_point_2d_rectangle(mx, my, area.x, area.y, area.width, area.height):
                for region in area.regions:
                    if region.type in {'UI', 'HEADER', 'TOOLS', 'TOOL_HEADER', 'HUD'}:
                        if intersect_point_2d_rectangle(mx, my, region.x, region.y, region.width, region.height):
                            return True
    return False


def get_mouse_ray(context, event, mat=Matrix.Identity(4)):
    region = context.region
    r3d = context.space_data.region_3d
    co = event.mouse_region_x, event.mouse_region_y
    origin = mat @ region_2d_to_origin_3d(region, r3d, co)
    vec = region_2d_to_vector_3d(region, r3d, co)
    vec.rotate(mat)
    return origin, vec


def apply_topology_face_material(ob):
    if not ob or ob.type != 'MESH':
        return
    mat_name = "SW_Topology_Material"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

    mat.diffuse_color = (0.0, 1.0, 0.5, 1.0)
    if hasattr(mat, 'blend_method'):
        mat.blend_method = 'OPAQUE'
    if hasattr(mat, 'shadow_method'):
        mat.shadow_method = 'NONE'

    if mat.node_tree:
        nodes = mat.node_tree.nodes
        principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if principled:
            if 'Base Color' in principled.inputs:
                principled.inputs['Base Color'].default_value = (0.0, 1.0, 0.5, 1.0)
            if 'Alpha' in principled.inputs:
                principled.inputs['Alpha'].default_value = 1.0
            if 'Emission' in principled.inputs:
                principled.inputs['Emission'].default_value = (0.0, 1.0, 0.5, 1.0)
            if 'Emission Strength' in principled.inputs:
                principled.inputs['Emission Strength'].default_value = 0.3

    if mat not in ob.data.materials[:]:
        ob.data.materials.append(mat)

    mat_idx = list(ob.data.materials).index(mat)
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(ob.data)
        for face in bm.faces:
            face.material_index = mat_idx
        bmesh.update_edit_mesh(ob.data)
    else:
        for poly in ob.data.polygons:
            poly.material_index = mat_idx

    ob.show_wire = S.wire
    ob.show_in_front = S.show_in_front


def mouse_raycast(obj, context, event):
    if not obj or not obj.data:
        return False, None, None, None

    mat = obj.matrix_world.inverted()
    origin, vec = get_mouse_ray(context, event, mat)

    try:
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bvh = BVHTree.FromBMesh(bm)
            location, normal, index, dist = bvh.ray_cast(origin, vec)
        else:
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            if running_op and hasattr(running_op, 'get_vert_co') and obj == getattr(S, 'source_ob', None):
                for v in bm.verts:
                    v.co = running_op.get_vert_co(context, v.index)
            else:
                sk = getattr(obj.data, 'shape_keys', None)
                if sk and SW_SHAPE_KEY_NAME in sk.key_blocks:
                    shape = sk.key_blocks[SW_SHAPE_KEY_NAME]
                    shape_cos = [0.0] * (len(bm.verts) * 3)
                    shape.data.foreach_get('co', shape_cos)
                    for v in bm.verts:
                        idx3 = v.index * 3
                        v.co = Vector((shape_cos[idx3], shape_cos[idx3+1], shape_cos[idx3+2]))
            bm.faces.ensure_lookup_table()
            bvh = BVHTree.FromBMesh(bm)
            location, normal, index, dist = bvh.ray_cast(origin, vec)
            bm.free()

        if location is not None:
            return True, location, normal, index
        return False, None, None, None
    except Exception:
        pass

    try:
        res = obj.ray_cast(origin, vec)
        if isinstance(res, tuple):
            if len(res) == 4:
                return res[0], res[1], res[2], res[3]
            elif len(res) == 5:
                return res[0], res[1], res[2], res[3]
    except Exception:
        pass

    return False, None, None, None


def global_to_screen(co, context):
    region = context.region
    r3d = context.space_data.region_3d
    return location_3d_to_region_2d(region, r3d, co)


def offset_towards_camera(co, context, factor=1.0):
    try:
        space = getattr(context, 'space_data', None)
        if not space or not hasattr(space, 'region_3d'):
            return co
        rv3d = space.region_3d
        cam_matrix = rv3d.view_matrix.inverted()
        if rv3d.view_perspective == 'PERSP':
            cam_pos = cam_matrix.to_translation()
            direction = cam_pos - co
            dist = direction.length
            if dist > 1e-4:
                shift_dist = min(0.08, max(0.001, dist * 0.0018 * factor))
                return co + direction.normalized() * shift_dist
        else:
            view_dir = cam_matrix.to_3x3() @ Vector((0, 0, 1))
            return co + view_dir.normalized() * (0.0025 * factor)
    except Exception:
        pass
    return co


def vertex_group_to_list(obj, vg_name):
    vg = obj.vertex_groups.get(vg_name, None)
    if not vg:
        return None
    data = []
    for i in range(len(obj.data.vertices)):
        try:
            data.append(vg.weight(i))
        except RuntimeError:
            data.append(0)
    return data
