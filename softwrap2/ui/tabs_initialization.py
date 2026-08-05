import time
from ..utils import state, get_selected_fixed_pins
from ..utils.state import S


def symmetry(layout, context):
    row = layout.row(align=True)
    row.label(text='Mirror')
    for i, axis in enumerate('XYZ'):
        row.prop(S(), 'mirror', text=axis, index=i, toggle=True)

    op = state.running_op
    if op:
        for axis, enable, error, scale, dim in zip('XYZ', S.mirror, op.symmetry_map.error, S.source_ob.scale, S.source_ob.dimensions):
            if enable and error / (dim / scale) > 0.05:
                layout.label(text=f'Warning: source mesh may not be symmetrical at axis {axis}', icon='ERROR')
                layout.label(text=f'    Error: {round(error / (dim / scale) , 6)}')


def initialization(self, context, layout=None):
    if layout is None:
        layout = self.layout
    op = state.running_op

    col = layout.column(align=True)
    row = col.row(align=True)
    row.active = S.source_ob is not None
    row.prop(S(), 'wire', toggle=True)
    row.prop(S(), 'show_in_front', toggle=True)
    row.prop(S(), 'mouse_grab_size')

    row_snap = col.row(align=True)
    row_snap.active = S.source_ob is not None
    row_snap.prop(S(), 'snapping_mode', expand=True)

    col = layout.column(align=True)
    row = col.row(align=True)
    row.scale_y = 2
    split = row.split(factor=0.5, align=True)
    if op:
        running_anim = ['*---', '-*--',
                        '--*-', '---*',
                        '--*-', '-*--'][int(time.time() * 5) % 5]
        split.operator('object.start_softwrap', text=f'Stop {running_anim}', icon='CANCEL')
    else:
        split.operator('object.start_softwrap', text='Start', icon='PLAY')

    sub_right = split.row(align=True)
    sub_right.prop(S(), 'pause', toggle=True, icon='PAUSE')
    sub_right.operator('object.apply_softwrap')
    sub_right.operator('object.reset_softwrap')

    row_mesh = layout.row(align=True)

    split_main = row_mesh.split(factor=0.5, align=True)
    row_src = split_main.split(factor=0.225, align=True)
    row_src.operator('object.set_source_softwrap', text='源')
    row_src.prop(S(), 'source_ob', text='')

    row_tgt = split_main.split(factor=0.225, align=True)
    row_tgt.operator('object.set_target_softwrap', text='目标')
    row_tgt.prop(S(), 'target_ob', text='')

    row = layout.row(align=True)
    row.scale_y = 1.5
    row.active = S.source_ob is not None
    row.prop(S(), 'snapping_force', slider=True)

    box_pin = layout.column()

    row_pin_ops = box_pin.row(align=True)
    row_pin_ops.operator('object.add_pin_softwrap', text='固定点(ctrl+shift)')
    row_pin_ops.operator('object.pins_remove_softwrap')
    sub_btn = row_pin_ops.row(align=True)
    sub_btn.enabled = bool(op and S.pause)
    sub_btn.prop(S(), 'use_smooth_brush', toggle=True, text='牵引平滑(ctrl+shift)', icon='BRUSH_DATA')

    col_exp = box_pin.column(align=True)
    col_exp.prop(S(), 'fixed_pin_expansion', slider=True)

    row_btn1 = col_exp.row(align=True)
    for i in range(11):
        op = row_btn1.operator('object.set_fixed_pin_prop', text=str(i))
        op.prop_type = 'expansion'
        op.val = i

    col_inf = box_pin.column(align=True)
    col_inf.prop(S(), 'fixed_pin_influence', slider=True)

    row_btn2 = col_inf.row(align=True)
    for i in range(11):
        op = row_btn2.operator('object.set_fixed_pin_prop', text=str(i))
        op.prop_type = 'influence'
        op.val = i

    box = layout.column()

    symmetry(box, context)

    col_smooth = box.column(align=True)

    row = col_smooth.row(align=True)
    row.prop(S(), 'smooth', slider=True)
    row.prop(S(), 'structural_stiffness', slider=True)

    row = col_smooth.row(align=True)
    row.prop(S(), 'quad_smoothing', slider=True)
    row.prop(S(), 'shear_stiffness', slider=True)

    row = col_smooth.row(align=True)
    row.prop(S(), 'topologic_smooth', slider=True)
    row.prop(S(), 'bending_stiffness', slider=True)

    row = col_smooth.row(align=True)
    row.prop(S(), 'min_scaling')
    row.prop(S(), 'max_scaling')

    col_sim = box.column(align=True)

    row = col_sim.row(align=True)
    row.prop(S(), 'damping', slider=True)
    row.prop(S(), 'scale_plasticity', slider=True)
    sub_bend = row.row(align=True)
    sub_bend.active = not op
    sub_bend.prop(S(), 'bending_distance')

    row = col_sim.row(align=True)
    row.prop(S(), 'simulation_steps')
    row.prop(S(), 'scale_restoration', slider=True)
    row.prop(S(), 'snapping_quality', slider=True)
