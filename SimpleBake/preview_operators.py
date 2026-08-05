import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy.utils import register_class, unregister_class

from .messages import print_message
from .utils import SBConstants


class SimpleBake_OT_PreviewBakeType(Operator):
    """Preview what will be baked for this bake type by configuring materials"""
    bl_idname = "simplebake.preview_bake_type"
    bl_label = "Preview"
    bl_description = "Preview this bake type in the viewport by configuring object materials"

    bake_type: StringProperty()

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        bake_type = self.bake_type

        # Start by removing any existing preview
        bpy.ops.simplebake.restore_preview()

        bake_objects = [item.obj_point for item in sbp.objects_list if item.obj_point is not None]

        if bake_type in SBConstants.ALL_SPECIALS:
            if bake_type == SBConstants.COLOURID:
                from .bake_operators.specials_bake_operators import SimpleBake_OT_Setup_Col_ID
                SimpleBake_OT_Setup_Col_ID.clear()

            for obj in bake_objects:
                bpy.ops.simplebake.specials_mats_swapping(mode="record", obj_name=obj.name)

                if bake_type == SBConstants.COLOURID:
                    bpy.ops.simplebake.setup_col_id(obj_name=obj.name)
                elif bake_type == SBConstants.VERTEXCOL:
                    if not obj.data.color_attributes:
                        continue
                    bpy.ops.simplebake.import_and_assign_specials(bake_mode=bake_type, obj_name=obj.name)
                    bpy.ops.simplebake.setup_vertex_col(obj_name=obj.name)
                else:  # AO, Thickness, Curvature, Lightmap
                    bpy.ops.simplebake.import_and_assign_specials(bake_mode=bake_type, obj_name=obj.name)

        else:
            # Initialise / clear any stale material tags from a previous preview or bake
            bpy.ops.simplebake.material_backup(mode="initialise")

            # Remove node groups (also performs master backup of all object materials).
            # Only available on Blender 4.1+, which is the minimum for this addon.
            bpy.ops.simplebake.pbr_pre_bake()

            # Remove reroute nodes from all object materials
            bpy.ops.simplebake.remove_reroutes()

            # Per-object: working backup then configure materials for the target bake type
            for obj in bake_objects:
                bpy.ops.simplebake.material_backup(
                    target_object_name=obj.name,
                    mode="working_backup"
                )
                bpy.ops.simplebake.prepare_object_mats_pbr(
                    target_name=obj.name,
                    this_bake=bake_type,
                    bake_operation_id="",
                    no_bake_image_node=True
                )

        # Switch Solid viewports to Material Preview so the preview is visible
        sbp.preview_changed_shading = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        if space.shading.type == 'SOLID':
                            space.shading.type = 'MATERIAL'
                            sbp.preview_changed_shading = True

        print_message(context, f"Preview active: {bake_type}")
        sbp.preview_active = True
        sbp.preview_bake_type = bake_type
        return {'FINISHED'}


class SimpleBake_OT_RestorePreview(Operator):
    """Restore materials after a bake type preview"""
    bl_idname = "simplebake.restore_preview"
    bl_label = "Restore Materials"
    bl_description = "Restore object materials to their original state after previewing"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        if sbp.preview_bake_type in SBConstants.ALL_SPECIALS:
            bake_objects = [item.obj_point for item in sbp.objects_list if item.obj_point is not None]
            for obj in bake_objects:
                bpy.ops.simplebake.specials_mats_swapping(mode="restore", obj_name=obj.name)
        else:
            # Restore working-mode duplicates first (scene-wide, no object name needed)
            bpy.ops.simplebake.material_backup(mode="working_restore")
            # Then restore master duplicates (scene-wide)
            bpy.ops.simplebake.material_backup(mode="master_restore")

        if sbp.preview_changed_shading:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            if space.shading.type == 'MATERIAL':
                                space.shading.type = 'SOLID'
            sbp.preview_changed_shading = False

        print_message(context, "Preview materials restored")
        sbp.preview_active = False
        sbp.preview_bake_type = ""
        return {'FINISHED'}


classes = [
    SimpleBake_OT_PreviewBakeType,
    SimpleBake_OT_RestorePreview,
]


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
