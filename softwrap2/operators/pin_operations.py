import bpy
import bmesh
from mathutils import Vector, Matrix
from ..utils.registration import register_cls
from ..utils import state
from ..utils.state import S, SW_SHAPE_KEY_NAME, get_settings


@register_cls
class OBJECT_OT_apply_softwrap(bpy.types.Operator):
    bl_idname = 'object.apply_softwrap'
    bl_label = 'Apply'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = 'Apply the deformation and exit simulation if running'

    @classmethod
    def poll(self, context):
        return get_settings(context).source_ob

    def execute(self, context):
        if not S.source_ob:
            return {'CANCELLED'}

        orig_mode = S.source_ob.mode
        if orig_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        shapes = S.source_ob.data.shape_keys
        bpy.ops.object.pins_remove_softwrap()

        if shapes and SW_SHAPE_KEY_NAME in shapes.key_blocks:
            data = [0.0] * (len(S.source_ob.data.vertices) * 3)
            shapes.key_blocks[SW_SHAPE_KEY_NAME].data.foreach_get('co', data)
            S.source_ob.shape_key_remove(shapes.key_blocks[SW_SHAPE_KEY_NAME])

            if S.source_ob.data.shape_keys:
                if len(shapes.key_blocks) == 1:
                    S.source_ob.shape_key_remove(shapes.key_blocks[0])
                    S.source_ob.data.vertices.foreach_set('co', data)
                else:
                    shapes.key_blocks[0].data.foreach_set('co', data)
            else:
                S.source_ob.data.vertices.foreach_set('co', data)
        else:
            if orig_mode == 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
                context.scene.tool_settings.mesh_select_mode = (True, False, False)
            return {'CANCELLED'}

        op = state.running_op
        if op:
            op.stop(context)

        if orig_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
            context.scene.tool_settings.mesh_select_mode = (True, False, False)

        return {'FINISHED'}


@register_cls
class OBJECT_OT_reset_softwrap(bpy.types.Operator):
    bl_idname = 'object.reset_softwrap'
    bl_label = 'Reset'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = 'Reset the deformation'

    @classmethod
    def poll(self, context):
        return get_settings(context).source_ob

    def execute(self, context):
        if not S.source_ob:
            return {'CANCELLED'}

        orig_mode = S.source_ob.mode
        if orig_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        op = state.running_op
        if op:
            op.reset_simulation(context)

        shapes = S.source_ob.data.shape_keys
        if shapes and SW_SHAPE_KEY_NAME in shapes.key_blocks:
            S.source_ob.shape_key_remove(shapes.key_blocks[SW_SHAPE_KEY_NAME])
            if S.source_ob.data.shape_keys and len(shapes.key_blocks) == 1:
                S.source_ob.shape_key_remove(shapes.key_blocks[0])

        if orig_mode == 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
            context.scene.tool_settings.mesh_select_mode = (True, False, False)
            if op:
                op.reset_simulation(context)

        return {'FINISHED'}


@register_cls
class OBJECT_OT_add_pin_softwrap(bpy.types.Operator):
    bl_idname = 'object.add_pin_softwrap'
    bl_label = '固定点(ctrl+中键)'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = '将编辑模式下选中的点/线/面顶点设定为固定点'

    @classmethod
    def poll(cls, context):
        ob = get_settings(context).source_ob
        return ob and ob.type == 'MESH' and ob.mode == 'EDIT'

    def execute(self, context):
        ob = S.source_ob
        if not ob or ob.mode != 'EDIT':
            self.report({'WARNING'}, "必须在编辑模式下使用")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        selected_verts = [v for v in bm.verts if v.select]

        if not selected_verts:
            self.report({'WARNING'}, "请先在编辑模式下选择顶点/边/面")
            return {'CANCELLED'}

        raw_pins = ob.get('sw_pins', ())
        existing_indices = set()
        for p in raw_pins:
            if isinstance(p, int):
                existing_indices.add(p)
            elif hasattr(p, '__getitem__') and 'vert_idx' in p:
                existing_indices.add(p['vert_idx'])

        count = 0
        for v in selected_verts:
            if v.index not in existing_indices:
                existing_indices.add(v.index)
                count += 1

        ob['sw_pins'] = list(existing_indices)
        bpy.ops.ed.undo_push(message='Add Fixed Pins')

        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"已设定 {count} 个固定点")
        return {'FINISHED'}


@register_cls
class OBJECT_OT_smooth_traction_pins_softwrap(bpy.types.Operator):
    bl_idname = 'object.smooth_traction_pins_softwrap'
    bl_label = '牵引平滑(ctrl+shift)'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = '平滑当前在暂停模式下选择的牵引点形体'

    @classmethod
    def poll(cls, context):
        return state.running_op is not None and S.pause

    def execute(self, context):
        op = state.running_op
        if not op or not S.pause:
            return {'CANCELLED'}

        fixed_indices = []
        if S.source_ob:
            raw_pins = S.source_ob.get('sw_pins', ())
            fixed_indices = [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]

        fixed_set = set(fixed_indices)

        selected_pins = set()
        if hasattr(op, 'selected_pause_pins') and op.selected_pause_pins:
            selected_pins = {p for p in op.selected_pause_pins if p in fixed_set}

        if not selected_pins and S.source_ob and S.source_ob.mode == 'EDIT':
            try:
                bm = bmesh.from_edit_mesh(S.source_ob.data)
                bm.verts.ensure_lookup_table()
                selected_pins = {v.index for v in bm.verts if v.select and v.index in fixed_set}
            except Exception:
                pass

        if not selected_pins:
            self.report({'INFO'}, "未选中任何牵引点")
            return {'CANCELLED'}

        if not hasattr(op, 'traction_pins'):
            op.traction_pins = {}

        before_snapshot = op.get_pin_state_snapshot()
        mat = S.source_ob.matrix_world if S.source_ob else Matrix.Identity(4)
        arranged_links = getattr(op, 'arranged_links', [])

        def get_pos(v_idx):
            if v_idx in op.traction_pins:
                return op.traction_pins[v_idx].copy()
            if hasattr(op, 'fixed_anchor_world_pos') and v_idx in op.fixed_anchor_world_pos:
                return op.fixed_anchor_world_pos[v_idx].copy()
            co_local = op.get_vert_co(context, v_idx)
            return mat @ co_local

        def compute_straightened_position_op(v_idx):
            curr_p = get_pos(v_idx)
            fixed_nbrs = [n for n in arranged_links[v_idx] if n in fixed_set] if v_idx < len(arranged_links) else []

            if len(fixed_nbrs) == 2:
                n1, n2 = fixed_nbrs[0], fixed_nbrs[1]
                p1, p2 = get_pos(n1), get_pos(n2)
                M = (p1 + p2) * 0.5
                H = curr_p - M
                target = M + H * 0.75
                d1 = (curr_p - p1).length
                d2 = (curr_p - p2).length
                d_avg = (d1 + d2) * 0.5

                if n1 not in selected_pins and d1 > 1e-6:
                    dir1 = (target - p1)
                    if dir1.length > 1e-6:
                        target = p1 + dir1.normalized() * (d1 * 0.3 + d_avg * 0.7)
                elif n2 not in selected_pins and d2 > 1e-6:
                    dir2 = (target - p2)
                    if dir2.length > 1e-6:
                        target = p2 + dir2.normalized() * (d2 * 0.3 + d_avg * 0.7)

                return target

            elif len(fixed_nbrs) == 1:
                n1 = fixed_nbrs[0]
                p1 = get_pos(n1)
                n1_nbrs = [n for n in arranged_links[n1] if n in fixed_set and n != v_idx] if n1 < len(arranged_links) else []
                if n1_nbrs:
                    p2 = get_pos(n1_nbrs[0])
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
                        v_i = get_pos(n_i) - curr_p
                        v_j = get_pos(n_j) - curr_p
                        len_i, len_j = v_i.length, v_j.length
                        if len_i > 1e-6 and len_j > 1e-6:
                            dot = (v_i / len_i).dot(v_j / len_j)
                            if dot < best_dot:
                                best_dot = dot
                                best_pair = (n_i, n_j)
                if best_pair and best_dot < 0.0:
                    n1, n2 = best_pair[0], best_pair[1]
                    p1, p2 = get_pos(n1), get_pos(n2)
                    M = (p1 + p2) * 0.5
                    H = curr_p - M
                    target = M + H * 0.75
                    d1 = (curr_p - p1).length
                    d2 = (curr_p - p2).length
                    d_avg = (d1 + d2) * 0.5
                    if n1 not in selected_pins and d1 > 1e-6:
                        dir1 = (target - p1)
                        if dir1.length > 1e-6:
                            target = p1 + dir1.normalized() * (d1 * 0.3 + d_avg * 0.7)
                    elif n2 not in selected_pins and d2 > 1e-6:
                        dir2 = (target - p2)
                        if dir2.length > 1e-6:
                            target = p2 + dir2.normalized() * (d2 * 0.3 + d_avg * 0.7)
                    return target
                else:
                    avg_p = Vector((0.0, 0.0, 0.0))
                    for n in fixed_nbrs:
                        avg_p += get_pos(n)
                    return avg_p / len(fixed_nbrs)

        alpha = 0.5
        for _ in range(3):
            new_positions = {}
            for idx in selected_pins:
                curr_p = get_pos(idx)
                target_straight_p = compute_straightened_position_op(idx)
                smoothed_p = curr_p * (1.0 - alpha) + target_straight_p * alpha
                snapped_p = op.snap_point_to_bvh(context, smoothed_p)
                new_positions[idx] = snapped_p

            for idx, p_new in new_positions.items():
                op.traction_pins[idx] = p_new

        op.push_pin_undo_snapshot(before_snapshot)

        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"已平滑 {len(selected_pins)} 个牵引点")
        return {'FINISHED'}


@register_cls
class OBJECT_OT_remove_pins_softwrap(bpy.types.Operator):
    bl_idname = 'object.pins_remove_softwrap'
    bl_label = 'Delete Pins'
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = '删除固定点：选中包含固定点时仅取消所选固定点；未选中固定点时取消全部固定点'

    @classmethod
    def poll(self, context):
        return get_settings(context).source_ob

    def execute(self, context):
        ob = S.source_ob
        if not ob:
            return {'CANCELLED'}

        raw_pins = list(ob.get('sw_pins', []))
        existing_indices = set()
        for p in raw_pins:
            if isinstance(p, int):
                existing_indices.add(p)
            elif hasattr(p, '__getitem__') and 'vert_idx' in p:
                existing_indices.add(p['vert_idx'])
            elif isinstance(p, bpy.types.Object) and p.name in bpy.data.objects:
                bpy.data.objects.remove(p)

        if not existing_indices:
            ob['sw_pins'] = []
            if context.area:
                context.area.tag_redraw()
            self.report({'INFO'}, "当前没有固定点")
            return {'FINISHED'}

        selected_vert_indices = set()
        op = state.running_op

        if op and S.pause:
            if hasattr(op, 'selected_pause_pins') and op.selected_pause_pins:
                selected_vert_indices.update(op.selected_pause_pins)
            if hasattr(op, 'selected_traction_pins') and op.selected_traction_pins:
                selected_vert_indices.update(op.selected_traction_pins)

        if ob.mode == 'EDIT':
            try:
                bm = bmesh.from_edit_mesh(ob.data)
                bm.verts.ensure_lookup_table()
                selected_vert_indices.update({v.index for v in bm.verts if v.select})
            except Exception:
                pass

        pinned_selected = existing_indices.intersection(selected_vert_indices)
        before_snap = op.get_pin_state_snapshot() if (op and S.pause) else None

        if pinned_selected:
            remaining_pins = existing_indices - pinned_selected
            ob['sw_pins'] = list(remaining_pins)
            if op and S.pause:
                for v_idx in pinned_selected:
                    if hasattr(op, 'traction_pins'):
                        op.traction_pins.pop(v_idx, None)
                    if hasattr(op, 'fixed_anchor_world_pos'):
                        op.fixed_anchor_world_pos.pop(v_idx, None)
                    if hasattr(op, 'selected_pause_pins'):
                        op.selected_pause_pins.discard(v_idx)
                    if hasattr(op, 'selected_traction_pins'):
                        op.selected_traction_pins.discard(v_idx)
                op.pin_cache_update(context, None)
                if before_snap:
                    op.push_pin_undo_snapshot(before_snap)

            bpy.ops.ed.undo_push(message='Remove Selected Pins')
            self.report({'INFO'}, f"已取消所选的 {len(pinned_selected)} 个固定点")
        else:
            ob['sw_pins'] = []
            if op and S.pause:
                if hasattr(op, 'traction_pins'):
                    op.traction_pins.clear()
                if hasattr(op, 'fixed_anchor_world_pos'):
                    op.fixed_anchor_world_pos.clear()
                if hasattr(op, 'selected_pause_pins'):
                    op.selected_pause_pins.clear()
                if hasattr(op, 'selected_traction_pins'):
                    op.selected_traction_pins.clear()
                op.pin_cache_update(context, None)
                if before_snap:
                    op.push_pin_undo_snapshot(before_snap)

            bpy.ops.ed.undo_push(message='Remove All Pins')
            self.report({'INFO'}, f"已取消全部 {len(existing_indices)} 个固定点")

        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


@register_cls
class OBJECT_OT_set_fixed_pin_prop(bpy.types.Operator):
    bl_idname = 'object.set_fixed_pin_prop'
    bl_label = 'Set Fixed Pin Property'
    bl_options = {'REGISTER', 'UNDO'}

    prop_type: bpy.props.StringProperty()
    val: bpy.props.IntProperty()

    def execute(self, context):
        s = context.scene.softwrap2
        if self.prop_type == 'expansion':
            s.fixed_pin_expansion = self.val
        elif self.prop_type == 'influence':
            s.fixed_pin_influence = self.val
        return {'FINISHED'}

