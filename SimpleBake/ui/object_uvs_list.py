import bpy
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, PropertyGroup, UIList
from bpy.props import EnumProperty, StringProperty, BoolProperty


class SIMPLEBAKE_UL_UVItems(UIList):
    """Rows: object name + dropdown of its UV maps (edit-active selector)"""
    bl_idname = "SIMPLEBAKE_UL_UVItems"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        sbp = context.scene.SimpleBake_Props
        # data == SimpleBake_Props; item == ZZ_SimpleBakeUVItem
        #ob = bpy.data.objects.get(item.object_name)
        ob = bpy.data.objects.get(item.name)
        row = layout.row(align=True)

        sb_uvl = next((l for l in ob.data.uv_layers if l.name=="SimpleBake"), None)

        # Object name
        row.label(
            #text=item.object_name or "<missing>",
            text=item.name or "<missing>",
            icon='UV_EDGESEL' if (ob and getattr(ob, "type", "") == 'MESH') else 'OBJECT_DATA'
        )

        # UV dropdown (prop_search over ob.data.uv_layers)
        if sbp.prefer_existing_sbmap and sb_uvl:
            row.label(text="SimpleBake (Locked)")
            row.enabled = False


        elif ob and ob.type == 'MESH' and getattr(ob.data, "uv_layers", None) and len(ob.data.uv_layers) > 0:
            row.prop_search(
                item, "uv_name",
                ob.data, "uv_layers",
                text=""
            )
        else:
            row.label(text="(no UV maps)", icon='ERROR')

def sb_uvlist_sync_from_bake_list(context):
    sc = context.scene
    sbp = sc.SimpleBake_Props

    sbp.uv_items.clear()

    obj_names = [o.name for o in sbp.objects_list if bpy.data.objects.get(o.name)]
    for name in obj_names:
        ob = bpy.data.objects[name]
        it = sbp.uv_items.add()
        #it.object_name = name
        it.name = name

        me = getattr(ob, "data", None)
        if not me or not getattr(me, "uv_layers", None) or len(me.uv_layers) == 0:
            it.uv_name = ""
            continue

        # Current EDIT-active — use active_index (reliable in Blender 5.0);
        # l.active getter is not reliably updated after setting active_index.
        active_idx = getattr(me.uv_layers, "active_index", 0)
        if not (0 <= active_idx < len(me.uv_layers)):
            active_idx = 0
        it.uv_name = me.uv_layers[active_idx].name

    # keep index in range
    sbp.uv_items_index = min(max(0, sbp.uv_items_index), max(0, len(sbp.uv_items)-1))

class SIMPLEBAKE_OT_SyncUVList(Operator):
    bl_idname = "simplebake.sync_uv_list"
    bl_label = "Synchronise Bake UV List"
    bl_description = "Populate/refresh the list of bake objects and their UV maps"

    def execute(self, context):
        sb_uvlist_sync_from_bake_list(context)
        #self.report({'INFO'}, "Bake UV list synchronised")
        return {'FINISHED'}

# Helper (optional)
def _first_uv_name(ob: bpy.types.Object) -> str:
    me = getattr(ob, "data", None)
    if not me or not getattr(me, "uv_layers", None) or len(me.uv_layers) == 0:
        return ""
    return me.uv_layers[0].name



class SIMPLEBAKE_OT_UVSetAllName(Operator):
    """Attempt to set all edit active UVs of bake objects to the UV map name selected on the panel"""
    bl_idname = "simplebake.uv_set_all_name"
    bl_label = "Set all"


    @classmethod
    def poll(self, context):
        sbp = context.scene.SimpleBake_Props
        if sbp.available_uv_maps in ["","None"]:
            return False
        else:
            return True

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        if not getattr(sbp, "uv_items", None):
            return {'CANCELLED'}

        for i in sbp.uv_items:
            i.uv_name = sbp.available_uv_maps

        return {'FINISHED'}




classes = ([
    SIMPLEBAKE_UL_UVItems,
    SIMPLEBAKE_OT_SyncUVList,
    SIMPLEBAKE_OT_UVSetAllName
        ])

def register():
    global classes
    for cls in classes:
        try:
            unregister_class(cls)
        except Exception:
            pass
        try:
            register_class(cls)
        except Exception as e:
            pass

def unregister():
    global classes
    for cls in classes:
        unregister_class(cls)
