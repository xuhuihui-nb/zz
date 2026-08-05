import bpy

all_classes = []


def register_cls(cls):
    if cls not in all_classes:
        all_classes.append(cls)
    return cls


def register_panel_draw(label=None, parent_cls=None, poll=lambda s, c: True):
    def decorator(draw_fnc):
        nonlocal label, parent_cls, poll
        if not label or callable(label):
            label = ' '.join(x.capitalize() for x in draw_fnc.__name__.split('_'))

        panel_name = f'VIEW3D_PT_softwrap2_{draw_fnc.__name__}'

        cls_dict = {
            'bl_label': label,
            'bl_space_type': 'VIEW_3D',
            'bl_region_type': 'UI',
            'bl_category': '动态拓扑',
            'poll': classmethod(poll),
            'draw': lambda self, context: draw_fnc(self.layout, context)
        }
        if parent_cls:
            cls_dict['bl_parent_id'] = parent_cls.__name__

        panel_cls = type(panel_name, (bpy.types.Panel,), cls_dict)
        return register_cls(panel_cls)

    if callable(label):
        return decorator(label)
    return decorator
