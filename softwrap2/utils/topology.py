import bmesh
from math import atan2
from collections import defaultdict


def core_mesh_from_bm(bm):
    bm.verts.ensure_lookup_table()
    verts = [tuple(v.co) for v in bm.verts]

    def triangles(face):
        for i in range(len(face.verts) - 2):
            yield face.verts[0].index, face.verts[i + 1].index, face.verts[i + 2].index

    faces = [tri for f in bm.faces for tri in triangles(f)]
    # Assuming core.Mesh imported if core engine available
    try:
        from ..core.gpu_engine import Mesh
        return Mesh(verts, faces)
    except Exception:
        return (verts, faces)


def deduplicate_links(items):
    if not items:
        return items
    return list(tuple(x) for x in set(frozenset(a) for a in items) if len(x) == 2)


def loop_pairs(elems):
    n = len(elems)
    half_n = n // 2

    for i in range(half_n + n % 2):
        yield (elems[i], elems[(i + half_n) % n])


def sort_vert_link_edges(vert):
    u = vert.normal.orthogonal().normalized()
    v = vert.normal.cross(u)
    o = vert.co

    def angle(edge):
        vec = vert.co - edge.other_vert(vert).co
        return atan2(vec.dot(u), vec.dot(v))

    return sorted(vert.link_edges, key=angle)


def sort_vert_link_loops(vert):
    u = vert.normal.orthogonal().normalized()
    v = vert.normal.cross(u)
    o = vert.co

    loops = vert.link_loops

    def angle(loop):
        vec = loop.vert.co - loop.link_loop_next.vert.co
        return atan2(vec.dot(u), vec.dot(v))

    return sorted(loops, key=angle)


def structural_springs_indexes(bm):
    springs = list(tuple(v.index for v in edge.verts) for edge in bm.edges)
    return springs


def somoothing_springs_indexes(bm):
    return [tuple(v.index for v in edge.verts) for edge in bm.edges if edge.verts[0].is_boundary == edge.verts[1].is_boundary]


def get_fixed_pin_rings(arranged_links, fixed_set, start_pins, max_steps=2):
    """
    通过 BFS 广度优先搜索计算 fixed_set 中从 start_pins 出发在 max_steps (默认 2 步) 以内的所有固定/牵引点及其拓扑步数距离 (dist)。
    """
    if not arranged_links or not fixed_set or not start_pins:
        return {}

    dist_map = {}
    queue = []
    for pin in start_pins:
        if pin in fixed_set:
            dist_map[pin] = 0
            queue.append(pin)

    while queue:
        curr = queue.pop(0)
        d = dist_map[curr]
        if d >= max_steps:
            continue

        if curr < len(arranged_links):
            for nbr in arranged_links[curr]:
                if nbr in fixed_set and nbr not in dist_map:
                    dist_map[nbr] = d + 1
                    queue.append(nbr)

    return dist_map


def get_step_weight(step):
    """
    牵引点的移动衰减权重计算:
    Step 0 (目标选中点): 100% 移动幅度 (1.0)
    Step 1 (第 1 阶邻接点): 50% 移动幅度 (0.5)
    Step 2 (第 2 阶邻接点): 25% 移动幅度 (0.25)
    """
    if step == 0:
        return 1.0
    elif step == 1:
        return 0.5
    elif step == 2:
        return 0.25
    return 0.0


def bmesh_walk_edge_loop(start_edge):
    """
    使用 Blender BMesh 标准双向追溯算法从 start_edge 向两端延伸。
    支持开孔/边界边缘循环 (Boundary Edge Loops) 与内部四边形循环 (Interior Edge Loops)。
    """
    if not start_edge or not hasattr(start_edge, 'verts'):
        return set()

    loop_verts = {start_edge.verts[0].index, start_edge.verts[1].index}
    loop_edges = {start_edge.index}

    is_boundary_start = (len(start_edge.link_faces) == 1 or getattr(start_edge, 'is_boundary', False))

    for start_v in start_edge.verts:
        curr_edge = start_edge
        curr_vert = start_v
        while True:
            if is_boundary_start:
                boundary_edges = [
                    e for e in curr_vert.link_edges
                    if e != curr_edge and (len(e.link_faces) == 1 or getattr(e, 'is_boundary', False))
                ]
                if len(boundary_edges) != 1:
                    break
                next_edge = boundary_edges[0]
            else:
                if len(curr_vert.link_edges) != 4:
                    break
                curr_faces = set(curr_edge.link_faces)
                opp = [
                    e for e in curr_vert.link_edges
                    if e != curr_edge and not (set(e.link_faces) & curr_faces)
                ]
                if len(opp) != 1:
                    break
                next_edge = opp[0]

            if next_edge.index in loop_edges:
                break

            loop_edges.add(next_edge.index)
            next_vert = next_edge.other_vert(curr_vert)
            loop_verts.add(next_vert.index)
            curr_edge = next_edge
            curr_vert = next_vert

    return loop_verts


def find_fixed_pin_loop(arranged_links, fixed_set, start_idx, target_nbr=None, get_co_func=None):
    """
    从 start_idx 出发，沿 fixed_set 查找已生成的固定点连通链条或循环。
    若指定 target_nbr，则仅沿该方向及其反方向追踪单条循环线。
    """
    if not arranged_links or not fixed_set or start_idx not in fixed_set or start_idx >= len(arranged_links):
        return {start_idx}

    loop_pins = {start_idx}
    nbrs = [n for n in arranged_links[start_idx] if n in fixed_set]
    if not nbrs:
        return {start_idx}

    branches = []
    if target_nbr is not None and target_nbr in nbrs:
        branches.append(target_nbr)
        co_start = get_co_func(start_idx) if get_co_func else None
        co_target = get_co_func(target_nbr) if get_co_func else None
        if co_start and co_target:
            dir_target = co_target - co_start
            if dir_target.length > 1e-6:
                dir_target /= dir_target.length
                best_dot = -0.3
                opp_nbr = None
                for n in nbrs:
                    if n != target_nbr:
                        co_n = get_co_func(n)
                        d = co_n - co_start
                        if d.length > 1e-6:
                            dot = dir_target.dot(d / d.length)
                            if dot < best_dot:
                                best_dot = dot
                                opp_nbr = n
                if opp_nbr is not None:
                    branches.append(opp_nbr)
    else:
        branches = nbrs

    for nbr in branches:
        curr = nbr
        prev = start_idx
        while curr in fixed_set and curr not in loop_pins:
            loop_pins.add(curr)
            if curr >= len(arranged_links):
                break

            candidates = [n for n in arranged_links[curr] if n in fixed_set and n != prev and n not in loop_pins]
            if not candidates:
                break
            if len(candidates) == 1:
                prev = curr
                curr = candidates[0]
            else:
                best_cand = None
                if get_co_func:
                    try:
                        co_curr = get_co_func(curr)
                        co_prev = get_co_func(prev)
                        dir_in = co_curr - co_prev
                        len_in = dir_in.length
                        if len_in > 1e-6:
                            dir_in /= len_in
                            best_dot = 0.5
                            for cand in candidates:
                                dir_out = get_co_func(cand) - co_curr
                                len_out = dir_out.length
                                if len_out > 1e-6:
                                    dot = dir_in.dot(dir_out / len_out)
                                    if dot > best_dot:
                                        best_dot = dot
                                        best_cand = cand
                    except Exception:
                        best_cand = None

                if best_cand is not None:
                    prev = curr
                    curr = best_cand
                else:
                    break

    return loop_pins


def find_mesh_edge_loop(arranged_links, start_idx, target_nbr=None, get_co_func=None):
    """
    从 start_idx 出发，沿网格拓扑连线查找规则四边形拓扑的循环边 (Edge Loop)。
    若指定 target_nbr，则仅沿该方向及其反方向追踪单条循环线。
    遇到极点/不规则节点或边界时自动停止，避免无序蔓延。
    """
    if not arranged_links or start_idx >= len(arranged_links):
        return {start_idx}

    loop_verts = {start_idx}
    nbrs = arranged_links[start_idx]
    if not nbrs:
        return {start_idx}

    branches = []
    if target_nbr is not None and target_nbr in nbrs:
        branches.append(target_nbr)
        co_start = get_co_func(start_idx) if get_co_func else None
        co_target = get_co_func(target_nbr) if get_co_func else None
        if co_start and co_target:
            dir_target = co_target - co_start
            if dir_target.length > 1e-6:
                dir_target /= dir_target.length
                best_dot = -0.3
                opp_nbr = None
                for n in nbrs:
                    if n != target_nbr:
                        co_n = get_co_func(n)
                        d = co_n - co_start
                        if d.length > 1e-6:
                            dot = dir_target.dot(d / d.length)
                            if dot < best_dot:
                                best_dot = dot
                                opp_nbr = n
                if opp_nbr is not None:
                    branches.append(opp_nbr)
    else:
        branches = nbrs

    for nbr in branches:
        curr = nbr
        prev = start_idx
        while curr not in loop_verts:
            loop_verts.add(curr)
            if curr >= len(arranged_links):
                break

            curr_nbrs = arranged_links[curr]
            if len(curr_nbrs) != 4:
                break

            candidates = [n for n in curr_nbrs if n != prev and n not in loop_verts]
            if not candidates:
                break

            best_cand = None
            if get_co_func:
                try:
                    co_curr = get_co_func(curr)
                    co_prev = get_co_func(prev)
                    dir_in = co_curr - co_prev
                    len_in = dir_in.length
                    if len_in > 1e-6:
                        dir_in /= len_in
                        best_dot = 0.75
                        for cand in candidates:
                            dir_out = get_co_func(cand) - co_curr
                            len_out = dir_out.length
                            if len_out > 1e-6:
                                dot = dir_in.dot(dir_out / len_out)
                                if dot > best_dot:
                                    best_dot = dot
                                    best_cand = cand
                except Exception:
                    best_cand = None

            if best_cand is not None:
                prev = curr
                curr = best_cand
            else:
                break

    return loop_verts


def find_traction_loop(arranged_links, fixed_set, start_idx, target_nbr=None, get_co_func=None):
    if fixed_set and start_idx in fixed_set:
        res = find_fixed_pin_loop(arranged_links, fixed_set, start_idx, target_nbr, get_co_func)
        if len(res) > 1:
            return res
    return find_mesh_edge_loop(arranged_links, start_idx, target_nbr, get_co_func)


def shear_spring_indexes(bm):
    return [(v.index for v in pair) for face in bm.faces for pair in loop_pairs(face.verts)]


def bending_spring_indexes(bm, distance=1):
    distance = max(distance, 1)

    springs = {}
    length_correlations = set()
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

    for edge in bm.edges:
        for spring_chain in links_by_edge[edge]:
            for i in range(len(spring_chain) - 1):
                length_correlations.add(frozenset((spring_chain[i], spring_chain[i + 1])))

    return list(springs.keys())


def ternary_links_indexes(bm):
    links = []
    for vert in bm.verts:
        for ea, eb in loop_pairs(sort_vert_link_edges(vert)):
            va = ea.other_vert(vert)
            vb = eb.other_vert(vert)
            link = vert.index, va.index, vb.index
            if not len(frozenset(link)) < 3:
                links.append(link)
    return links


def quaternary_link_indexes(bm):
    links = []
    for face in bm.faces:
        if len(face.verts) == 4:
            indexes = *(v.index for v in face.verts),
            links.append((indexes[0], indexes[1], indexes[3], indexes[2]))
            links.append((indexes[0], indexes[3], indexes[1], indexes[2]))
            links.append((indexes[0], indexes[2], indexes[1], indexes[3]))

    for vert in bm.verts:
        for e1, e2 in loop_pairs(sort_vert_link_edges(vert)):
            if e1.is_manifold and e2.is_manifold:
                links.append((vert.index, e1.other_vert(vert).index, vert.index, e2.other_vert(vert).index))

    return links
