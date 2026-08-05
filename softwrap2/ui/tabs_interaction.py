from ..utils import state
from ..utils.state import S


def interaction(self, context, layout=None):
    if layout is None:
        layout = self.layout
    op = state.running_op
    if op:
        if S.interact_mouse:
            mouse_side = S.mouse_button.replace('_', ' ').lower()
            layout.label(text=f'[shift + {mouse_side}] to add a pin')
        else:
            layout.label(text='Mouse interaction disabled')

    col = layout.column(align=True)
    col.prop(S(), 'interact_mouse', toggle=True)
    col.prop(S(), 'pause', toggle=True)
    row = col.row(align=True)
    row.prop(S(), 'mouse_button', expand=True)
    col.separator()
