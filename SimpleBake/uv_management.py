import bpy 
from bpy.utils import register_class, unregister_class
from bpy.types import Operator
from bpy.props import FloatProperty, EnumProperty, BoolProperty, StringProperty

from .utils import SBConstants, select_only_this
from .messages import print_message
from .bake_operators.common_bake_support import match_high_low_objects

def rearrange_uvs(obj, uv_name):
    
    uvs = obj.data.uv_layers
    orig_active_name = uvs.active.name
    orig_active_render_name = [uv.name for uv in uvs if uv.active_render][0]
    
    while uvs[0].name != uv_name:
        
        #Move to bottom
        name = uvs[0].name
        uvs.active = uvs[0]
        uvs.new()
        uvs.remove(uvs[0])
        uvs[-1].name = name
        
    uvs.active = uvs[orig_active_name]
    uvs[orig_active_render_name].active_render = True

def pack_uvs(self, context):
    sbp = context.scene.SimpleBake_Props

    bpy.ops.uv.select_all(action="SELECT")

    #Always average - still relevant for pre-Blender 3.6
    if sbp.new_uv_method == "CombineExisting" and self.average_islands:
        bpy.ops.uv.average_islands_scale()

    n = int(''.join(c for c in bpy.app.version_string if c.isdigit()))
    if n >= 360:
        bpy.ops.uv.pack_islands("EXEC_DEFAULT", udim_source=sbp.uvp_pack_to, rotate=sbp.uvp_rotate, rotate_method=sbp.uvp_rotation_method, scale=sbp.uvp_scale, merge_overlap=sbp.uvp_merge_overlapping, margin_method=sbp.uvp_margin_method, margin=sbp.uvpackmargin, pin=sbp.uvp_lock_pinned, pin_method=sbp.uvp_lock_method, shape_method=sbp.uvp_shape_method)
    else: # Pre Blender 3.6
        bpy.ops.uv.pack_islands(rotate=True, margin=sbp.uvpackmargin)

    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)


class SimpleBake_OT_Process_UVs(Operator):
    """Start the bake operation"""
    bl_idname = "simplebake.process_uvs"
    bl_description = "Prepare UV maps on the bake objects"
    bl_label = "Prepare UVs"

    def smart_project_to_atlas(self, context):
        
        sbp = context.scene.SimpleBake_Props
        
        print_message(context, "Smart projecting all objects to atlas map")
        
        #Selection
        bpy.ops.object.select_all(action="DESELECT")
        for obj in self.bake_objects:
            obj.select_set(state=True)
            
        #Make sure we have an active object
        if context.active_object == None:
            context.view_layer.objects.active = self.bake_objects[0]
        
        for obj in self.bake_objects:
            if("SimpleBake" in obj.data.uv_layers):
                obj.data.uv_layers.remove(obj.data.uv_layers["SimpleBake"])
                
            obj.data.uv_layers.new(name="SimpleBake")
            obj.data.uv_layers["SimpleBake"].active = True

        bpy.ops.object.mode_set(mode="EDIT", toggle=False) #Enter edit mode
        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action="SELECT")
            
        #Unwrap
        bpy.ops.uv.smart_project(island_margin=self.island_margin, correct_aspect=self.uvcorrectaspect)
        
        #Packing
        #pack_uvs(self)

        bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
        return
    
    def combine_existing_to_atlas(self, context):
        
        sbp = context.scene.SimpleBake_Props
        
        print_message(context, "Combining existing UVs into atlas map")
        
        #Selection
        # bpy.ops.object.select_all(action="DESELECT")

        for obj in bpy.context.selected_objects:
            obj.select_set(False)

        for obj in self.bake_objects:
            obj.select_set(state=True)

        #Make sure we have an active object
        if context.active_object == None:
            context.view_layer.objects.active = self.bake_objects[0]
        
        for obj in self.bake_objects:
            if("GENERATED_SimpleBake_Atlas" in obj.data.uv_layers):
                obj.data.uv_layers.remove(obj.data.uv_layers["GENERATED_SimpleBake_Atlas"])
                
            u = obj.data.uv_layers.new(name="GENERATED_SimpleBake_Atlas")
            u.active = True

        #With everything selected, pack into one big map
        bpy.ops.object.mode_set(mode="EDIT", toggle=False)
        bpy.ops.mesh.reveal()
        
        bpy.ops.mesh.select_all(action="SELECT")

        pack_uvs(self, context)

        bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
        return
    

    def smart_project_individual_objects(self, context):
        
        print_message(context, "Smart projecting each object individually")
        
        for obj in self.bake_objects:
            
            select_only_this(context, obj)
            
            if("SimpleBake" in obj.data.uv_layers):
                obj.data.uv_layers.remove(obj.data.uv_layers["SimpleBake"])
            obj.data.uv_layers.new(name="SimpleBake")
            obj.data.uv_layers["SimpleBake"].active = True

            bpy.ops.object.mode_set(mode="EDIT", toggle=False)
            
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action="SELECT")

            bpy.ops.uv.smart_project(island_margin=self.island_margin, correct_aspect=self.uvcorrectaspect)
            
            bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        return
    
    
    def per_mat_pack_uvs_to_bounds(self, context):

        sbp = context.scene.SimpleBake_Props
        print_message(context, "Packing UVs for each material into new UV map")

        bpy.ops.object.select_all(action="DESELECT")

        for obj in self.bake_objects:

            # Copy existing UV data into a fresh SimpleBake layer
            source_layer = obj.data.uv_layers.active
            if "SimpleBake" in obj.data.uv_layers:
                obj.data.uv_layers.remove(obj.data.uv_layers["SimpleBake"])
            new_layer = obj.data.uv_layers.new(name="SimpleBake")
            if source_layer:
                for i, item in enumerate(source_layer.data):
                    new_layer.data[i].uv = item.uv.copy()
            new_layer.active = True

            select_only_this(context, obj)
            bpy.ops.object.mode_set(mode='EDIT', toggle=False)
            bpy.ops.mesh.reveal()

            # Get enabled materials — strip SBM_/SBW_ prefix for comparison
            enabled_mat_names = {
                e.mat_name for e in sbp.mat_bake_list
                if e.obj_name == obj.name and e.enabled
            }

            i = 0
            for slot in obj.material_slots:
                if slot.material is None:
                    i += 1
                    continue
                mat_name = slot.material.name
                if mat_name.startswith("SBW_"): mat_name = mat_name[4:]
                if mat_name.startswith("SBM_"): mat_name = mat_name[4:]
                if enabled_mat_names and mat_name not in enabled_mat_names:
                    i += 1
                    continue
                obj.active_material_index = i
                bpy.ops.mesh.select_all(action="DESELECT")
                bpy.ops.object.material_slot_select()
                bpy.ops.uv.pack_islands(scale=True, margin=self.island_margin)
                i += 1

            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

        return

    def check_prefer_sb_maps(self, context):
        if self.prefer_sb_uv_maps:
            print_message(context, "Preferring existing UV maps called SimpleBake. Setting them to active")
            for obj in self.bake_objects:
                if("SimpleBake" in obj.data.uv_layers):
                    obj.data.uv_layers["SimpleBake"].active = True
        return
    
    
    def execute(self, context):

        sbp = context.scene.SimpleBake_Props

        #Pull what we need from the panel
        self.island_margin = sbp.unwrapmargin
        self.uvcorrectaspect = sbp.uvcorrectaspect
        self.average_islands = sbp.average_uv_size
        self.prefer_sb_uv_maps = sbp.prefer_existing_sbmap
        self.new_uv_option = sbp.new_uv_option
        self.new_uv_method = sbp.new_uv_method
        self.expand_mat_uvs = sbp.expand_mat_uvs
        self.uvpackmargin = sbp.uvpackmargin


        #Set the bake objects
        if (sbp.selected_s2a or sbp.cycles_s2a) and sbp.s2a_opmode=="automatch":
            from .bake_operators.auto_match_operators import SimpleBake_OT_AutoMatch_Operation as bo
            hl_matches = bo.hl_matches
            self.bake_objects = [context.scene.objects[name] for name in hl_matches.keys()]

        elif sbp.selected_s2a: #Covering decals or standard
            self.bake_objects =[sbp.targetobj]
        elif sbp.cycles_s2a:
            self.bake_objects =[sbp.targetobj_cycles]
        else:
            self.bake_objects = [i.obj_point for i in sbp.objects_list]
            
        
        #Decide what we are actually doing
        if sbp.tex_per_mat and self.expand_mat_uvs:
            self.per_mat_pack_uvs_to_bounds(context)
        elif self.new_uv_option and len(self.bake_objects)==1:
            self.smart_project_individual_objects(context)
        elif self.new_uv_option and self.new_uv_method == SBConstants.NEWUV_SMART_INDIVIDUAL:
            self.smart_project_individual_objects(context)
        elif self.new_uv_option and self.new_uv_method == SBConstants.NEWUV_SMART_ATLAS:
            self.smart_project_to_atlas(context)
        elif self.new_uv_option and self.new_uv_method == SBConstants.NEWUV_COMBINE_EXISTING:
            self.combine_existing_to_atlas(context)
        elif not self.new_uv_option:
            print_message(context, "We are working with existing UV maps")
            self.check_prefer_sb_maps(context)
        else:
            print_message(context, "Something went wrong processing UVs")
            

        for obj in self.bake_objects:
            obj["SB_uv_used_for_bake"] = obj.data.uv_layers.active.name

            if self.new_uv_option and sbp.move_new_uvs_to_top:
                rearrange_uvs(obj, obj["SB_uv_used_for_bake"])




            
        return {'FINISHED'}

classes = ([
    SimpleBake_OT_Process_UVs#,
    #SimpleBake_OT_Pack_UVs
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
