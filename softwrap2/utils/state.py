import bpy

SW_SHAPE_KEY_NAME = 'SoftWrap_Shape_key'

running_op = None


def get_settings(context=None):
    if context is None:
        context = bpy.context
    return context.scene.softwrap2


class SettingsProbe:
    def __getattr__(self, k):
        return getattr(get_settings(bpy.context), k)

    def __setattr__(self, k, v):
        setattr(get_settings(bpy.context), k, v)

    def __call__(self):
        return get_settings(bpy.context)


S = SettingsProbe()


PAUSE_PIN_PALETTE = [
    (1.0, 0.35, 0.0, 1.0),   # 鲜艳橙
    (0.0, 0.75, 1.0, 1.0),   # 青天蓝
    (0.95, 0.25, 0.75, 1.0), # 玫红紫
    (1.0, 0.85, 0.0, 1.0),   # 明黄
    (0.65, 0.3, 1.0, 1.0),   # 冰紫
    (0.0, 0.9, 0.85, 1.0),   # 湖蓝
    (1.0, 0.25, 0.35, 1.0),  # 珊瑚红
    (0.2, 0.5, 1.0, 1.0),    # 宝石蓝
    (1.0, 0.55, 0.0, 1.0),   # 金黄橙
    (0.85, 0.4, 1.0, 1.0),   # 薰衣草紫
]


def get_all_fixed_pins(ob):
    if not ob:
        return []
    raw_pins = ob.get('sw_pins', ())
    return [p if isinstance(p, int) else p.get('vert_idx') for p in raw_pins if isinstance(p, int) or (hasattr(p, '__getitem__') and 'vert_idx' in p)]


def get_selected_fixed_pins(context=None):
    if context is None:
        context = bpy.context
    ob = getattr(get_settings(context), 'source_ob', None)
    if not ob:
        return set()

    all_fixed = set(get_all_fixed_pins(ob))
    if not all_fixed:
        return set()

    op = running_op
    selected_verts = set()

    if op:
        if hasattr(op, 'selected_pause_pins') and op.selected_pause_pins:
            selected_verts.update(op.selected_pause_pins)
        if hasattr(op, 'selected_traction_pins') and op.selected_traction_pins:
            selected_verts.update(op.selected_traction_pins)

    if ob.mode == 'EDIT':
        try:
            import bmesh
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            selected_verts.update({v.index for v in bm.verts if v.select})
        except Exception:
            pass
    elif ob.data and hasattr(ob.data, 'vertices'):
        try:
            selected_verts.update({v.index for v in ob.data.vertices if v.select})
        except Exception:
            pass

    return all_fixed.intersection(selected_verts)


def get_pin_prop(ob, vert_idx, key, default_val=0):
    if not ob:
        return default_val
    props = ob.get('sw_pin_props', {})
    v_key = str(vert_idx)
    if isinstance(props, dict) or hasattr(props, 'items'):
        val = props.get(v_key, {})
        if isinstance(val, dict) or hasattr(val, 'items'):
            return val.get(key, default_val)
    return default_val


def set_pin_props(ob, vert_indices, key, val):
    if not ob or not vert_indices:
        return
    raw_props = ob.get('sw_pin_props', {})
    props = {}
    if isinstance(raw_props, dict) or hasattr(raw_props, 'items'):
        for k, v in raw_props.items():
            if isinstance(v, dict) or hasattr(v, 'items'):
                props[str(k)] = dict(v)
            else:
                props[str(k)] = {}

    for v_idx in vert_indices:
        v_key = str(v_idx)
        if v_key not in props:
            props[v_key] = {}
        props[v_key][key] = int(val)

    ob['sw_pin_props'] = props

