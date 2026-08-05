import bpy
from ..utils.registration import register_cls
from ..utils import state, get_selected_fixed_pins, get_pin_prop, set_pin_props, get_all_fixed_pins


def update_use_smooth_brush(self, context):
    op = state.running_op
    if op:
        op.is_smoothing_brush_stroke = False
        if hasattr(op, 'draw_pins') and context:
            try:
                op.draw_pins(context, None)
            except Exception:
                pass
        if context and getattr(context, 'area', None):
            context.area.tag_redraw()


def update_fixed_pin_influence(self, context):
    op = state.running_op
    if op and hasattr(op, 'pin_cache_update'):
        try:
            op.pin_cache_update(context, None)
        except Exception:
            pass
    if context and getattr(context, 'area', None):
        context.area.tag_redraw()


def update_fixed_pin_expansion(self, context):
    op = state.running_op
    if op:
        if hasattr(op, 'fixed_anchor_world_pos'):
            raw_pins = self.source_ob.get('sw_pins', ()) if self.source_ob else ()
            raw_fixed_set = {p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)}
            for idx in list(op.fixed_anchor_world_pos.keys()):
                if idx not in raw_fixed_set:
                    op.fixed_anchor_world_pos.pop(idx, None)
        if hasattr(op, 'pin_cache_update'):
            try:
                op.pin_cache_update(context, None)
            except Exception:
                pass
    if context and getattr(context, 'area', None):
        context.area.tag_redraw()


@register_cls
class SoftwrapSettings(bpy.types.PropertyGroup):
    def stop_engine(self, context):
        op = state.running_op
        if op:
            op.stop(context)

    def set_wire(self, context):
        if self.source_ob:
            self.wire = self.source_ob.show_wire
            self.show_in_front = self.source_ob.show_in_front

    def source_ob_update(self, context):
        if self.source_ob and not self.source_ob.type == 'MESH':
            self.source_ob = None
        self.stop_engine(context)
        self.set_wire(context)

    def target_ob_update(self, context):
        if self.target_ob and not self.target_ob.type == 'MESH':
            self.target_ob = None
        self.stop_engine(context)

    def wire_update(self, context):
        if self.source_ob:
            self.source_ob.show_wire = self.wire
            self.source_ob.show_all_edges = self.wire

    def show_in_front_update(self, context):
        if self.source_ob:
            self.source_ob.show_in_front = self.show_in_front

    def mesh_poll(self, ob):
        return ob.type == 'MESH' and ob.name in bpy.context.scene.objects

    source_ob: bpy.props.PointerProperty(
        name='source mesh', type=bpy.types.Object, update=source_ob_update, poll=mesh_poll,
        description='The mesh that is going to be deformed into a new shape using the target mesh as reference')

    target_ob: bpy.props.PointerProperty(
        name='target mesh', type=bpy.types.Object, update=target_ob_update, poll=mesh_poll,
        description='The mesh that is going to be used as reference, (tipcally a sculpt or a 3d scan)')

    wire: bpy.props.BoolProperty(
        name='Wire', update=wire_update,
        description='Toggle wireframe display on the source mesh')

    show_in_front: bpy.props.BoolProperty(
        name='In Front', update=show_in_front_update,
        description='Toggle in front display on the source mesh')

    mirror: bpy.props.BoolVectorProperty(
        name='Mirror', size=3, default=(False, False, False),
        description='Enforce symmetry across an axis.')

    min_scaling: bpy.props.FloatProperty(
        name='Min Scaling', default=0.8,
        description='Minimun allowed rest length for edges')

    max_scaling: bpy.props.FloatProperty(
        name='Max Scaling', default=3,
        description='Maximun allowed rest length for edges')

    scale_plasticity: bpy.props.FloatProperty(
        name='Scale Plasticity', min=0, max=1, default=1.0,
        description='Amount of semi-permanent deformation per frame')

    scale_restoration: bpy.props.FloatProperty(
        name='Scale Restoration', min=0, max=1, default=0.0,
        description='Amount of restoration to the semi-parmanent deformation per frame')

    smooth: bpy.props.FloatProperty(
        name='Smooth', min=0, soft_max=5, default=0,
        description='Amount of somothing applied to the mesh per frame (nonlinear)\n'
                    'Note: has the side effect of swrinking the mesh,')

    quad_smoothing: bpy.props.FloatProperty(
        name='Quad Smooth', min=0, soft_max=10, default=0,
        description='Amount of force applied per frame to restore the shape of quads (nonlinear)\n'
                    'Note: has the side effect of swrinking the mesh,')

    topologic_smooth: bpy.props.FloatProperty(
        name='Topologic Smooth', min=0, soft_max=5, default=2,
        description='Amount of topology-aware smoothing applied to the mesh per frame, (nonlinear)\n'
                    'Note: Less aggressive than smooth, ideal for removing kinks in edge loops caused by by pins')

    structural_stiffness: bpy.props.FloatProperty(
        name='Structural Stiffness', min=0, soft_max=10, default=2,
        description='Stiffness of the direct links between vertices')

    bending_stiffness: bpy.props.FloatProperty(
        name='Bending Stiffness', min=0, soft_max=10, default=2,
        description='Stiffness of the links across multiple edges')

    shear_stiffness: bpy.props.FloatProperty(
        name='Shear Stiffness', min=0, soft_max=10, default=2,
        description='Stiffness of the links across face diagonals')

    bending_distance: bpy.props.IntProperty(
        name='Bending Distance', min=0, default=3,
        description='Maximun distance (by edges) for bending springs to be created')

    damping: bpy.props.FloatProperty(
        name='Damping', min=0, max=1, default=0.3,
        description='Dampen the simulation to increase stability')

    simulation_steps: bpy.props.IntProperty(
        name='Simulation Steps', min=0, default=2,
        description='Number of simulation steps per frame')

    snapping_quality: bpy.props.IntProperty(
        name='Snapping Quality', min=1, max=20, default=10,
        description='How of often to update the snapping direction from the source mesh to the target mesh')

    snapping_force: bpy.props.FloatProperty(
        name='Snapping Strength', min=0, max=1, default=0,
        description='Strength of the snapping, how much it pulls the source mesh towards the target mesh')

    snapping_mode: bpy.props.EnumProperty(
        name='Snap Mode', default='SURFACE',
        items=[('SURFACE', 'Surface', 'Surface'),
               ('OUTSIDE', 'Outside', 'Outside'),
               ('INSIDE', 'Inside', 'Inside')],
        description='Controls which side of the target mesh affects the snapping.')

    mouse_grab_size: bpy.props.IntProperty(
        name='Mouse Grab Size', min=1, default=3,
        description='Size of the area grabbed by the mouse')

    def get_fixed_pin_expansion(self):
        ob = self.source_ob
        if not ob:
            return self.get('_fixed_pin_expansion_global', 0)
        selected_fixed = get_selected_fixed_pins()
        if selected_fixed:
            first_idx = next(iter(selected_fixed))
            return get_pin_prop(ob, first_idx, 'expansion', default_val=self.get('_fixed_pin_expansion_global', 0))
        else:
            return self.get('_fixed_pin_expansion_global', 0)

    def set_fixed_pin_expansion(self, val):
        self['_fixed_pin_expansion_global'] = int(val)
        ob = self.source_ob
        if ob:
            selected_fixed = get_selected_fixed_pins()
            if selected_fixed:
                set_pin_props(ob, selected_fixed, 'expansion', val)
            else:
                all_fixed = get_all_fixed_pins(ob)
                set_pin_props(ob, all_fixed, 'expansion', val)

        update_fixed_pin_expansion(self, bpy.context)

    fixed_pin_expansion: bpy.props.IntProperty(
        name='固定点扩展', min=0, max=50, soft_max=50, step=1,
        get=get_fixed_pin_expansion,
        set=set_fixed_pin_expansion,
        description='指定固定点周围扩展为固定点的圈层数：选中固定点时调节当前选中的固定点，未选中时调节全体固定点'
    )

    def get_fixed_pin_influence(self):
        ob = self.source_ob
        if not ob:
            return self.get('_fixed_pin_influence_global', 0)
        selected_fixed = get_selected_fixed_pins()
        if selected_fixed:
            first_idx = next(iter(selected_fixed))
            return get_pin_prop(ob, first_idx, 'influence', default_val=self.get('_fixed_pin_influence_global', 0))
        else:
            return self.get('_fixed_pin_influence_global', 0)

    def set_fixed_pin_influence(self, val):
        self['_fixed_pin_influence_global'] = int(val)
        ob = self.source_ob
        if ob:
            selected_fixed = get_selected_fixed_pins()
            if selected_fixed:
                set_pin_props(ob, selected_fixed, 'influence', val)
            else:
                all_fixed = get_all_fixed_pins(ob)
                set_pin_props(ob, all_fixed, 'influence', val)

        update_fixed_pin_influence(self, bpy.context)

    fixed_pin_influence: bpy.props.IntProperty(
        name='固定点影响范围', min=0, max=100, soft_max=100, step=1,
        get=get_fixed_pin_influence,
        set=set_fixed_pin_influence,
        description='指定固定点的影响范围：选中固定点时调节当前选中的固定点，未选中时调节全体固定点'
    )

    use_smooth_brush: bpy.props.BoolProperty(
        name='平滑牵引点笔刷', default=False,
        update=update_use_smooth_brush,
        description='开启平滑牵引点笔刷：在暂停模式下按住 Ctrl 键或手动开启，可对笔刷范围内的牵引点进行平滑拉直')

    pause: bpy.props.BoolProperty(
        name='Pause (Space)', default=False,
        description='Temporarily halt the simulation')

    interact_mouse: bpy.props.BoolProperty(
        name='Interaction (Shift + Space)', default=True,
        description='Enable interception of mouse events for pin creation and grabbing')

    mouse_button: bpy.props.EnumProperty(
        name='Interact With', default='LEFTMOUSE',
        items=[('LEFTMOUSE', 'Left Mouse', 'Left Mouse'), ('RIGHTMOUSE', 'Right Mouse', 'Right Mouse')],
        description='Which mouse button to use for interacting with the simulation ')

    active_tab: bpy.props.EnumProperty(
        name="Tab",
        items=[
            ('INITIALIZATION', '初始化', 'Initialization settings'),
            ('INTERACTION', '交互', 'Interaction settings'),
        ],
        default='INITIALIZATION'
    )
