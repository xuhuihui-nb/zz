import bpy
from ..utils import find_closest_obj, show_message_box, find_3d_viewport
from bpy.utils import register_class, unregister_class
from bpy.types import Operator, PropertyGroup, UIList
from bpy.props import EnumProperty, StringProperty
from ..utils import invalidate_udim_cache



def refresh_bake_objects_list(context):
    
    sbp = context.scene.SimpleBake_Props

    if sbp.global_mode == "PBR" and sbp.selected_s2a:
        if sbp.s2a_opmode != "automatch":
            if sbp.targetobj != None:
                if sbp.targetobj.name not in bpy.context.scene.objects:
                    sbp.targetobj = None

    if sbp.global_mode == "CyclesBake" and sbp.cycles_s2a:
        if sbp.s2a_opmode != "automatch":
            if sbp.targetobj_cycles != None:
                if sbp.targetobj_cycles.name not in bpy.context.scene.objects:
                    sbp.targetobj_cycles = None


    objects_list = sbp.objects_list

    gone = []
    for li in objects_list:
        #Is it empty?
        if li.obj_point == None:
            gone.append(li.name)

        #Is it no longer in the scene?
        elif li.obj_point.name not in context.scene.objects:
            gone.append(li.name)

        #Is it not in use anywhere else?
        elif len(li.obj_point.users_scene) < 1:
            gone.append(li.name)

        elif sbp.selected_s2a or sbp.cycles_s2a:
            if sbp.s2a_opmode=="automatch" and sbp.auto_match_mode == "name":
                for o in sbp.objects_list:
                    if o.obj_point != None and not o.obj_point.name.lower().endswith("_high"):
                        gone.append(o.name)
    for g in gone:
        objects_list.remove(objects_list.find(g))

    for i in objects_list:
        i.name = i.obj_point.name

    #Throw in a refresh of the UV list. WHy not?
    bpy.ops.simplebake.sync_uv_list()


def _strip_sb_prefixes(name):
    """Strip SimpleBake backup prefixes (SBW_, SBM_) to recover the original material name."""
    if name.startswith("SBW_"):
        name = name[4:]
    if name.startswith("SBM_"):
        name = name[4:]
    return name

def refresh_mat_bake_list(context):
    """Keep mat_bake_list in sync with objects_list and their materials."""
    sbp = context.scene.SimpleBake_Props

    # Build the set of (obj_name, mat_name) pairs that should exist.
    # Strip SimpleBake backup prefixes so the list always stores original names.
    wanted = set()
    for item in sbp.objects_list:
        if item.obj_point is None:
            continue
        obj = item.obj_point
        for slot in obj.material_slots:
            if slot.material is not None:
                wanted.add((obj.name, _strip_sb_prefixes(slot.material.name)))

    # Remove stale entries
    to_remove = []
    for i, entry in enumerate(sbp.mat_bake_list):
        if (entry.obj_name, entry.mat_name) not in wanted:
            to_remove.append(i)
    for i in reversed(to_remove):
        sbp.mat_bake_list.remove(i)

    # Add missing entries (default enabled=True)
    existing = {(e.obj_name, e.mat_name) for e in sbp.mat_bake_list}
    for obj_name, mat_name in sorted(wanted):
        if (obj_name, mat_name) not in existing:
            entry = sbp.mat_bake_list.add()
            entry.obj_name = obj_name
            entry.mat_name = mat_name
            entry.enabled = True


class SIMPLEBAKE_UL_Objects_List(UIList):
    """Bake objects list"""

    viable_high_low_bakes = []

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):

        sbp = context.scene.SimpleBake_Props
        custom_icon = 'OBJECT_DATAMODE'
        name = item.obj_point.name if item.obj_point != None else "_?_"
        target_obj = "???"
        cage_obj = ""

        #Set the icon if in name mode
        if (sbp.selected_s2a or sbp.cycles_s2a) and item.obj_point != None:
            if sbp.s2a_opmode=="automatch":
                if sbp.auto_match_mode == "name":
                    custom_icon = "SEQUENCE_COLOR_01" if bpy.app.version < (4,4,0) else "STRIP_COLOR_01"
                    target_obj = "???"

                    for o in context.scene.objects:
                        if name.lower().replace("_high", "_low") == o.name.lower():
                            target_obj = o.name
                            custom_icon = "SEQUENCE_COLOR_04" if bpy.app.version < (4,4,0) else "STRIP_COLOR_04"
                            if name not in __class__.viable_high_low_bakes:
                                    __class__.viable_high_low_bakes.append(name)

                    #We didn't find a match
                    if target_obj == "???":
                        if name in __class__.viable_high_low_bakes:
                            __class__.viable_high_low_bakes.remove(name)

                    # Look up cage object by naming convention
                    cage_obj = ""
                    if target_obj != "???":
                        parts = target_obj.split("_")
                        base_name = '_'.join(parts[:-1]).lower()
                        for o in context.scene.objects:
                            if o.name.lower() == f"{base_name}_cage":
                                cage_obj = o.name
                                break

        #Set the icon if in position mode
        if (sbp.selected_s2a or sbp.cycles_s2a) and item.obj_point != None:
            if sbp.s2a_opmode=="automatch":
                if sbp.auto_match_mode == "position":
                    co = find_closest_obj(context, name)
                    if co != None:
                        custom_icon = "SEQUENCE_COLOR_04" if bpy.app.version < (4,4,0) else "STRIP_COLOR_04"
                        target_obj = co.name
                        if name not in __class__.viable_high_low_bakes:
                            __class__.viable_high_low_bakes.append(name)
                    else:
                        custom_icon = "SEQUENCE_COLOR_01" if bpy.app.version < (4,4,0) else "STRIP_COLOR_01"
                        target_obj = "???"
                        if name in __class__.viable_high_low_bakes:
                            __class__.viable_high_low_bakes.remove(name)

        # Draw
        if self.layout_type in {'DEFAULT', 'COMPACT'}:

            col = layout.column()
            col.label(text=name, icon=custom_icon)
            if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
                col = layout.column()
                col.alignment = 'CENTER'
                col.label(text=" --> ")
                col = layout.column()
                icon = "QUESTION" if target_obj == "???" else "CHECKMARK"
                col.label(text=target_obj, icon=icon)
                if sbp.auto_match_mode == "name":
                    col = layout.column()
                    if cage_obj:
                        col.label(text=cage_obj, icon="MOD_MESHDEFORM")
                    else:
                        col.label(text="No cage")

        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon = custom_icon)



class SimpleBake_OT_Add_Bake_Object(Operator):
    """Add selected object(s) to the bake list"""

    bl_idname = "simplebake.add_bake_object"
    bl_label = "Adds a bake object to the list"

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects)
    
    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        #Lets get rid of the non-mesh objects from the selections
        [obj.select_set(False) for obj in context.scene.objects if obj.type != "MESH"]

        #Do we still have an active object?
        if context.active_object == None:
            #If not, pick one
            context.view_layer.objects.active = context.selected_objects[0]

        #Add to list if not already in the list
        objs = context.selected_objects.copy()

        for obj in objs:
            #If we are in matching high to low mode, only allow adding of _high objects
            if (sbp.selected_s2a or sbp.cycles_s2a):
                if sbp.s2a_opmode=="automatch" and sbp.auto_match_mode == "name":
                    if not obj.name.lower().endswith("_high"):
                        messages = ([
                        f"ERROR: Can't add object {obj.name}",
                        "You  have auto match high and low poly selected and",
                        "you are using name mode.",
                        "Only object names ending in \"_high\" can be added"
                        ])
                        show_message_box(context, messages, "Errors occured", icon = 'ERROR')
                        continue

            #Only add if not already on the list
            r = [o.name for o in sbp.objects_list if o.name == obj.name]
            if len(r) == 0:
                n = sbp.objects_list.add()    
                n.obj_point = obj
                n.name = obj.name
        
        #Throw in a refresh
        refresh_bake_objects_list(context)
        refresh_mat_bake_list(context)

        if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            if len(SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes)<2:
                sbp.merged_bake = False

        #Invalidate UDIM cache
        invalidate_udim_cache()
        
        return{'FINISHED'}


class SimpleBake_OT_Add_Bake_Object_By_Name(Operator):
    """Add specified object(s) to the bake list"""

    bl_idname = "simplebake.add_bake_object_by_name"
    bl_label = "Adds a bake object to the list"

    override_target_obj_name: StringProperty(default="")

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        n = sbp.objects_list.add()
        obj = context.scene.objects[self.override_target_obj_name]
        n.obj_point = obj
        n.name = obj.name

        #Invalidate UDIM cache
        invalidate_udim_cache()

        return{'FINISHED'}


class SimpleBake_OT_Remove_Bake_Object(Operator):
    """Remove the selected object from the bake list."""

    bl_idname = "simplebake.remove_bake_object"
    bl_label = "Removes a bake object from the list"

    @classmethod
    def poll(cls, context):
        #TODO-------
        return context.scene.SimpleBake_Props.objects_list

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        objects_list = sbp.objects_list
        index = sbp.objects_list_index
        #Record it's name
        name = sbp.objects_list[index].name

        objects_list.remove(index)
        sbp.objects_list_index = min(max(0, index - 1), len(objects_list) - 1)

        #Throw in a refresh
        refresh_bake_objects_list(context)
        refresh_mat_bake_list(context)

        #Also remove from high low list
        if name in SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes:
            SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes.remove(name)
        if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            if len(SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes)<2:
                sbp.merged_bake = False

        #Invalidate UDIM cache
        invalidate_udim_cache()

        return{'FINISHED'}


class SimpleBake_OT_Clear_Bake_Objects_List(Operator):
    """Clear the object list"""

    bl_idname = "simplebake.clear_bake_objects_list"
    bl_label = "Clears the bake object list"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        sbp.objects_list.clear()

        #Throw in a refresh
        refresh_bake_objects_list(context)
        refresh_mat_bake_list(context)

        #Clear the high low match list
        SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes = []
        # if len(SIMPLEBAKE_UL_Objects_List.viable_high_low_bakes)<2:
        #     sbp.merged_bake = False
        
        #Invalidate UDIM cache
        invalidate_udim_cache()

        return{'FINISHED'}

class SimpleBake_OT_Move_Bake_Object_List(Operator):
    """Move an object in the list."""

    bl_idname = "simplebake.move_bake_object_list"
    bl_label = "Moves an item in the bake objects list"

    direction: bpy.props.EnumProperty(items=(('UP', 'Up', ""),
                                              ('DOWN', 'Down', ""),))

    @classmethod
    def poll(cls, context):
        return context.scene.SimpleBake_Props.objects_list

    def move_index(self, context):
        """ Move index of an item render queue while clamping it. """
        sbp = context.scene.SimpleBake_Props
        index = sbp.objects_list_index
        list_length = len(sbp.objects_list) - 1  # (index starts at 0)
        new_index = index + (-1 if self.direction == 'UP' else 1)

        sbp.objects_list_index = max(0, min(new_index, list_length))

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        objects_list = sbp.objects_list
        index = sbp.objects_list_index

        neighbor = index + (-1 if self.direction == 'UP' else 1)
        objects_list.move(neighbor, index)
        self.move_index(context)
        
        #Throw in a refresh
        refresh_bake_objects_list(context)
        
        return{'FINISHED'}


class SimpleBake_OT_Refresh_Bake_Object_List(Operator):
    """Refresh the list to remove objects"""

    bl_idname = "simplebake.refresh_bake_object_list"
    bl_label = "Refresh the bake objects list"

    @classmethod
    def poll(cls, context):
        return True


    def execute(self, context):
        refresh_bake_objects_list(context)
        refresh_mat_bake_list(context)

        #Invalidate UDIM cache
        invalidate_udim_cache()

        return{'FINISHED'}

#highlight_on = False


class SimpleBake_OT_Set_Highlight_Cols(Operator):
    """Actually modify the object colours"""

    bl_idname = "simplebake.set_highlight_cols"
    bl_label = "Set highlight cols to objects"

    @classmethod
    def update_object_list_from_selectd(cls):
        sbp = bpy.context.scene.SimpleBake_Props
        if (o:=bpy.context.active_object):
            if (i:=sbp.objects_list.find(o.name))!=-1:
                if sbp.objects_list_index !=i:
                    sbp.objects_list_index =i

    def execute(self, context):

        sbp = bpy.context.scene.SimpleBake_Props

        #Do this anyway (EEVEE updates even if object selection changed)
        __class__.update_object_list_from_selectd()

        if not sbp.highlight_on:
            return{'CANCELLED'} #Highlight turned off - end timer

        #Do nothing more if we aren't in shading mode
        any_shading = False
        for space in find_3d_viewport():
            if space.shading.type == "SOLID":
                any_shading = True
        if not any_shading:
            return{'CANCELLED'}
            #return 0.2 #Do nothing. Check back later

        def set_col(obj_names, col):
            for o_name in obj_names:
                if (o:=bpy.data.objects.get(o_name)):
                    if o.color != col:
                        if "SB_orig_col" not in o:
                            o["SB_orig_col"] = o.color
                        o.color = col

        bake_objs = [o.name for o in sbp.objects_list]
        all_objs = ([o.name for o in bpy.context.scene.objects if
                     o.name not in bake_objs and
                     o.type == "MESH" and
                     "SB_auto_cage" not in o])

        set_col(all_objs, (1,1,1,1))
        c = sbp.highlight_col
        set_col(bake_objs, (c.r, c.g, c.b, 1.0))

        return{'FINISHED'}



class SimpleBake_OT_Highlight_Bake_Objects(Operator):
    """Highlight selected objects in the viewport"""

    bl_idname = "simplebake.highlight_bake_objects"
    bl_label = "Highlights bake objects in the viewport on this screen"


    @classmethod
    def poll(cls, context):
        sbp = context.scene.SimpleBake_Props
        return not sbp.highlight_on

    @classmethod
    def set_timer(cls):
        bpy.app.timers.register(cls.col_bake_objects, first_interval=1.0)

    @classmethod
    def col_bake_objects(cls):
        sbp = bpy.context.scene.SimpleBake_Props

        bpy.ops.simplebake.set_highlight_cols()

        if not sbp.highlight_on:
            return None
        else:
            return 0.2

    @classmethod
    def set_display(cls, context):

        for space in find_3d_viewport():
            space.shading.color_type = "OBJECT"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props

        sbp.highlight_on = True
        __class__.set_timer()

        __class__.col_bake_objects()
        __class__.set_display(context)

        return{'FINISHED'}



class SimpleBake_OT_Remove_Highlight(Operator):
    """Remove highlight of selected objects in the viewport"""

    bl_idname = "simplebake.remove_highlight"
    bl_label = "Removes the highlights for bake objects in the viewport on this screen"

    @classmethod
    def poll(cls, context):
        sbp = context.scene.SimpleBake_Props
        return sbp.highlight_on

    def uncol_bake_objects(self, context):
        sbp = context.scene.SimpleBake_Props
        bpy.ops.simplebake.refresh_bake_object_list()
        obj_names = [o.name for o in sbp.objects_list]

        for o_name in obj_names:
            if (o:=bpy.data.objects.get(o_name)):
                if "SB_orig_col" in o:
                    o.color = o["SB_orig_col"]
                    del o["SB_orig_col"]

    def unset_display(self, context):

        #for screen in bpy.data.screens:
        screen = bpy.context.window.screen
        # Iterate through the areas in the current screen
        for area in screen.areas:
            # Check if the area is a 3D viewport
            if area.type == 'VIEW_3D':
                # Optionally, you can access the space data of the area
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.color_type = "MATERIAL"

    def execute(self, context):
        sbp = context.scene.SimpleBake_Props
        sbp.highlight_on = False

        self.uncol_bake_objects(context)
        self.unset_display(context)


        return{'FINISHED'}

    
class SimpleBake_OT_Materials_Expand_All(Operator):
    """Expand all objects in the Materials section"""
    bl_idname = "simplebake.materials_expand_all"
    bl_label = "Expand All"

    def execute(self, context):
        for item in context.scene.SimpleBake_Props.objects_list:
            item.expanded = True
        return {'FINISHED'}


class SimpleBake_OT_Materials_Collapse_All(Operator):
    """Collapse all objects in the Materials section"""
    bl_idname = "simplebake.materials_collapse_all"
    bl_label = "Collapse All"

    def execute(self, context):
        for item in context.scene.SimpleBake_Props.objects_list:
            item.expanded = False
        return {'FINISHED'}


classes = ([
        SIMPLEBAKE_UL_Objects_List,
        SimpleBake_OT_Add_Bake_Object,
        SimpleBake_OT_Add_Bake_Object_By_Name,
        SimpleBake_OT_Remove_Bake_Object,
        SimpleBake_OT_Clear_Bake_Objects_List,
        SimpleBake_OT_Move_Bake_Object_List,
        SimpleBake_OT_Refresh_Bake_Object_List,
        SimpleBake_OT_Highlight_Bake_Objects,
        SimpleBake_OT_Remove_Highlight,
        SimpleBake_OT_Set_Highlight_Cols,
        SimpleBake_OT_Materials_Expand_All,
        SimpleBake_OT_Materials_Collapse_All,
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
