import bpy
import random

## TODO:
## Apply Reprojection should create a new history entry, not remove the whole thing
## move history stuff to new file

def clear_history(context):
    qremesher = context.scene.qremesher
    
    # clears the list
    # but mesh data will still be there until restart, like with all data-blocks
    qremesher.history.clear()

    # match mesh data name to object name, before it stops being the history_object
    ## this rename function is a new feature for Blender 4.3
    ## https://developer.blender.org/docs/release_notes/4.3/python_api/#data-blocks
    if qremesher.history_object != None:
        qremesher.history_object.data.rename(qremesher.history_object.name , mode='ALWAYS')
    # the old one doesn't handle name collisions
    #obj.data.name = obj.name
    
    # clear the history object, don't keep it around even with empty history
    qremesher.history_object = None
    
def relative_mode_count(object, mode):
        polycount = len(object.data.polygons)
        result = 1000 # fallback amount

        match mode:
            case 'HALF':
                result = polycount/2
            case 'SAME':
                result = polycount
            case 'DOUBLE':
                result = polycount*2

        # return the result, but cap it at 50k
        return int(min(result, 50000))

# taken from:
# https://stackoverflow.com/questions/579310/formatting-long-numbers-as-strings
def format_num(num):
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])

def overwrite_density_paint(density_color):
    
    # make sure that the density attribute exists before painting
    if "qremesher_density" not in bpy.context.object.data.color_attributes:
        bpy.ops.geometry.color_attribute_add(
            name="qremesher_density",
            data_type='BYTE_COLOR',
            color=(1, 1, 1, 1)
        ) 
        
    # activate Paint Soft brush from Essentials
    bpy.ops.brush.asset_activate(
        asset_library_type='ESSENTIALS',
        asset_library_identifier="",
        relative_asset_identifier="brushes\\essentials_brushes-mesh_sculpt.blend\\Brush\\Paint Soft",
    )

    brush = bpy.data.brushes["Paint Soft"]
    
    brush.color = density_color
    # set the secondary color to white, so it's easy to "erase" density by inverting brush
    brush.secondary_color = (1, 1, 1)


def copy_attribute(mesh, source_name="material_index", new_name=".qremesher_mats"):
    
    # if there is no source, just create blank attributes and finish the function
    if source_name not in mesh.attributes:
        mesh.attributes.new(name=source_name, type='INT', domain='FACE')
        mesh.attributes.new(name=new_name, type='INT', domain='FACE')
        return
    
    attr_copy = mesh.attributes.new(name=new_name, type='INT', domain='FACE')

    # for i, face in enumerate(mesh.attributes['material_index'].data):
       # mesh.attributes['.qremesher_mats'].data[i].value = face.value
 
    mat_indexes = [face.value for face in mesh.attributes[source_name].data]

    attr_copy.data.foreach_set("value", mat_indexes)


def pre_remesh(context):
    scene = context.scene
    qremesher = scene.qremesher
    original_object = context.object
    mesh = original_object.data
    color_attributes = original_object.data.color_attributes

    # check object for valid mesh data, just in case
    if original_object == None or original_object.type != 'MESH' or mesh == None:
        return
    
    # if this is a new object, clear the history and set it as new history_object
    if original_object != qremesher.history_object:
        clear_history(context)
        qremesher.history_object = original_object

    # # make a single user copy of mesh data if there's multiple users and no remesh history
    # if mesh.users > 1 and len(qremesher.history) < 1:
        # original_object.data = original_object.data.copy()

    # calculate the quad count for relative modes (same/half/double)
    if qremesher.quad_count_mode != 'CUSTOM':
        # hacky way to temp save the original mode string for later
        original_object['qr_count_mode'] = qremesher.quad_count_mode
        qremesher.target_count = relative_mode_count(original_object, qremesher.quad_count_mode)
    
    # there is no Face Set attribute, so don't use them
    if ".sculpt_face_set" not in original_object.data.attributes:
        qremesher.use_face_sets = False
    
    # backup original materials and slots
    if qremesher.use_face_sets:
        copy_attribute(original_object.data, "material_index", ".qremesher_mats")
        original_object['backup_slots'] = [slot.name for slot in original_object.material_slots]
    
    # convert Face Sets to Mats, and enable use_materials
    if qremesher.use_face_sets:
        facesets_to_materials(original_object)
        qremesher.use_materials = True
        # these two can't be used at once, so just disable it
        qremesher.use_material_index = False 
    # dummy 'use_material' prop to avoid UI stuff
    # will only trigger if 'use_face_sets' is off
    elif qremesher.use_material_index:
        qremesher.use_materials = True

    # match symmetry options
    qremesher.symmetry_x = original_object.use_mesh_mirror_x
    qremesher.symmetry_y = original_object.use_mesh_mirror_y
    qremesher.symmetry_z = original_object.use_mesh_mirror_z
    
    # make sure the density paint is the active attribute (that's what qremesher uses)
    if "qremesher_density" in color_attributes:
        color_attributes.active_color = color_attributes["qremesher_density"]
        
        

def post_remesh(context, original_object):

    qremesher = context.scene.qremesher
    new_object = context.active_object

    # Original should not be hidden
    original_object.hide_set(state=False)

    # Original object should be re-selected and made active
    original_object.select_set(True)
    context.view_layer.objects.active = original_object

    # New object should be de-selected, and hidden from view and render
    new_object.select_set(False)
    new_object.hide_set(state=True)
    new_object.hide_viewport = True
    new_object.hide_render = True
    
    #restore materials and slots, before mesh data gets swapped
    if qremesher.use_face_sets:
        original_object.data.materials.clear()
        copy_attribute(original_object.data, ".qremesher_mats", "material_index")
        for name in original_object['backup_slots']:
            bpy.ops.object.material_slot_add()
            active = original_object.active_material_index
            if name != '': # special cond for empty mat slots
                original_object.material_slots[active].material = bpy.data.materials[name]
        # delete temp
        del original_object['backup_slots']

    # extra steps if the object doesn't have remesh history
    if len(qremesher.history) < 1:
        # match the mesh data name to the object name, because "Cube.004" looks bad
        original_object.data.name = original_object.name
        #add objects mesh data as the first entry, making it the "original" mesh
        history_item = qremesher.history.add()
        history_item.mesh = original_object.data

    # match name again to maintain naming (???)
    new_object.data.name = original_object.data.name

    # store New Object mesh in history of Original Object
    history_item = qremesher.history.add()
    history_item.mesh = new_object.data
    # hacky way to get the original mode string, delete the temp prop immediately
    if 'qr_count_mode' in original_object:
        history_item.mode = original_object['qr_count_mode']
        del original_object['qr_count_mode']
    else:
        history_item.mode = qremesher.quad_count_mode
    # set the intended quad count, not the actual one of the finished mesh
    history_item.quads = qremesher.target_count
    
    # set the last added item as the active one
    qremesher.history_active = len(qremesher.history)-1

    #swap the mesh data
    original_object.data = new_object.data

    # clean nasty topology flag, since mesh is now clean
    if hasattr(original_object, "csm"):
        original_object.csm.nasty_topology = False
        original_object.csm.remesh_prep = False

    #delete the New Object that was created by qremesher
    bpy.data.objects.remove(new_object, do_unlink=True)
    
    # remove density paint from remeshed object, no need for it
    color_attributes = original_object.data.color_attributes
    if 'qremesher_density' in color_attributes:
        color_attributes.remove(color_attributes['qremesher_density'])

    # if the count mode is a relative mode (same/half/double)
    # then reset it to SAME
    # so the user has to pick a relative mode again manually
    if qremesher.quad_count_mode != 'CUSTOM':
        qremesher.quad_count_mode = 'SAME'
        # set the target count to the current polycount
        qremesher.target_count = len(original_object.data.polygons)
    #else
    # otherwise the mode and count will be left alone
    
    


def post_post_remesh(context, original_object):
    qremesher = context.scene.qremesher
    # purge the temporary materials and recreate face sets
    if original_object.mode == 'SCULPT' and qremesher.use_face_sets:
        bpy.ops.sculpt.face_sets_init(mode='MATERIALS')
        original_object.data.materials.clear()
    # disable just for safety, if it's needed, it will be re-enabled elsewehere
    qremesher.use_materials = False


def facesets_to_materials(obj):
    # import random

    if obj == None or obj.type != 'MESH' or obj.data == None:
        return

    mesh = obj.data
    # purge all materials and slots from the mesh, need a clean slate!
    mesh.materials.clear()
    # create new material_index, it always gets removed by the purge
    material_index = mesh.attributes.new(name='material_index', type='INT', domain='FACE')
    face_sets = mesh.attributes['.sculpt_face_set']

    #set(data.value for data in fsets.data)

    # assign material slots based on face set index
    known_face_sets = dict()
    for face_index, face_set_id in enumerate(face_sets.data):

        known_face_sets[face_set_id.value] = True

        material_index.data[face_index].value = list(known_face_sets.keys()).index(face_set_id.value)


    for i, face_set in enumerate(known_face_sets):
        bpy.ops.object.material_slot_add()
        slot = obj.material_slots[i]

        # slot.material = bpy.data.materials.new(f"FaceSet.{face_set:03d}")
        slot.material = bpy.data.materials.new("FromFaceSet")
        slot.material.diffuse_color[0] = random.random()
        slot.material.diffuse_color[1] = random.random()
        slot.material.diffuse_color[2] = random.random()


class QREMESHER_OT_SetQuadCount(bpy.types.Operator):
    bl_idname = "qremesher.set_quad_count"
    bl_label = "设置四边形数量"
    bl_description = "设置目标四边形数量"

    amount: bpy.props.IntProperty(default=1000)

    @classmethod
    def poll(cls, context):
        # check if object mesh data is valid?
        return True

    def execute(self, context):
        qremesher = context.scene.qremesher

        # set the mode to CUSTOM, to update the UI
        qremesher.quad_count_mode = 'CUSTOM'

        # set the result, but cap it at 50k
        qremesher.target_count = int(min(self.amount, 50000))

        return {'FINISHED'}



class QREMESHER_OT_SwitchMeshData(bpy.types.Operator):
    bl_idname = "qremesher.switch_mesh"
    bl_label = "切换网格数据"
    bl_description = "将对象的网格数据替换为指定的数据"
    #bl_options = {'REGISTER', 'UNDO'}

    object: bpy.props.StringProperty(name="Object")
    mesh: bpy.props.StringProperty(name="Mesh")

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        data = bpy.data

        # check if object and mesh exist
        if (self.object not in data.objects) or (self.mesh not in data.meshes):
            return {'CANCELLED'}

        obj = data.objects[self.object]
        mesh = data.meshes[self.mesh]

        # protect previous object mesh data
        obj.data.use_fake_user = True

        # switch to new mesh data
        obj.data = mesh

        return {'FINISHED'}


class QREMESHER_OT_PurgeMeshHistory(bpy.types.Operator):
    bl_idname = "qremesher.purge_mesh_history"
    bl_label = "清除历史记录"
    bl_description = "删除所有网格数据，只保留选中的那个"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        qremesher = context.scene.qremesher
        obj = qremesher.history_object
        

        # there's nothing to purge
        if len(qremesher.history) < 1:
            return {'CANCELLED'}
            
        clear_history(context)

        return {'FINISHED'}


class QREMESHER_OT_ReprojectModeStart(bpy.types.Operator):
    bl_idname = "qremesher.reproject_mode_start"
    bl_label = "重投影模式"
    bl_description = "将数据从原始对象传输到选中的网格"

    @classmethod
    def poll(cls, context):
        if context.object == None:
            cls.poll_message_set("对象无效！")
            return False
        elif len(context.scene.qremesher.history) < 1:
            cls.poll_message_set("对象尚未重构！")
            return False
        elif context.scene.qremesher.history_active == 0:
            cls.poll_message_set("已选择原始对象，无法向自身重投影！")
            return False
        else:
            return True

    def execute(self, context):
        qremesher = context.scene.qremesher
        obj = qremesher.history_object
        

        # mark that the object is using reproject mode
        qremesher.in_reproject_mode = True

        # create a new object that will be used for the reprojection
        # set the mesh data to the "Original" from history ()
        reproject_target = bpy.data.objects.new("reproject_target", qremesher.history[0].mesh)
        # copy the original's transform matrix
        reproject_target.matrix_world = obj.matrix_world

        # add a Subdivision modifier to for the two other modifers below
        mod_name = "QRemesher_SubSurf"
        mod = obj.modifiers.new(name=mod_name, type='SUBSURF')
        # mod.levels = 0 # set it to zero, in case mesh is already big!
        mod.levels = qremesher.reproject_subdivisions
        mod.show_render = False # never show it in render
        mod.show_only_control_edges = False # so the full wireframe shows
        
        # store polycount for subdivisions, so the UI doesn't check it too often
        qremesher.reproject_polycount = len(obj.data.polygons)

        # add a Shrinkwrap modifier to re-project the details
        mod_name = "QRemesher_Shrinkwrap"
        mod = obj.modifiers.new(name=mod_name, type='SHRINKWRAP')
        # hide it immediately, so it doesn't lag when the object is added
        mod.show_viewport = False
        mod.show_render = False # never show it in render
        # set the proper options
        mod.wrap_method = 'PROJECT'
        mod.use_negative_direction = True
        mod.target = reproject_target

        # add a Data Transfer modifier to transfer the vertex color
        mod_name = "QRemesher_DataTransfer"
        mod = obj.modifiers.new(name=mod_name, type='DATA_TRANSFER')
        # hide it immediately, so it doesn't lag when the object is added
        mod.show_viewport = False
        mod.show_render = False # never show it in render
        # set the proper options
        mod.use_vert_data = True
        mod.data_types_verts = {'COLOR_VERTEX'}
        mod.object = reproject_target
        bpy.ops.object.datalayout_transfer(modifier=mod_name)
        
        # remember object for later deletion
        qremesher.reproject_target = reproject_target
        
        return {'FINISHED'}


class QREMESHER_OT_ReprojectModeFinish(bpy.types.Operator):
    bl_idname = "qremesher.reproject_mode_finish"
    bl_label = "完成重投影"
    bl_description = "应用所有细分和重投影。\n"
    bl_description += "注意：这也会清除重构历史记录！"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        qremesher = context.scene.qremesher
        obj = qremesher.history_object
        
        
        # add the, soon to be, reprojected mesh to history
        history_item = qremesher.history.add()
        history_item.mesh = obj.data.copy()
        history_item.reprojected = True
        qremesher.history_active = len(qremesher.history)-1
        
        # reproject by applying all modifiers
        bpy.ops.object.convert(target='MESH')
        
        # delete the temp reproject object
        bpy.data.objects.remove(qremesher.reproject_target, do_unlink=True)
        
        # reset these so they don't show up in a new reprojection
        qremesher.property_unset("reproject_subdivisions")
        qremesher.property_unset("reproject_polycount")
        qremesher.property_unset("reproject_target")

        qremesher.in_reproject_mode = False
        
        return {'FINISHED'}


class QREMESHER_OT_ReprojectModeCancel(bpy.types.Operator):
    bl_idname = "qremesher.reproject_mode_cancel"
    bl_label = "取消重投影"
    bl_description = "移除所有修改器而不应用它们"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        qremesher = context.scene.qremesher
        
        # remove all modifiers, don't apply
        qremesher.history_object.modifiers.clear()
        
        # delete the temp reproject object
        bpy.data.objects.remove(qremesher.reproject_target, do_unlink=True)
        
        # reset these on cancel, so they don't show up in a new reprojection
        qremesher.property_unset("reproject_subdivisions")
        qremesher.property_unset("reproject_target")
        
        qremesher.in_reproject_mode = False
        
        return {'FINISHED'}


class QREMESHER_OT_ReprojectShape(bpy.types.Operator):
    bl_idname = "qremesher.reproject_shape"
    bl_label = "重投影形状"
    bl_description = "使用收缩包裹修改器从原始网格投射细节"

    def execute(self, context):
        mod = context.scene.qremesher.history_object.modifiers["QRemesher_Shrinkwrap"]
        mod.show_viewport = not mod.show_viewport
        
        return {'FINISHED'}


class QREMESHER_OT_ReprojectColor(bpy.types.Operator):
    bl_idname = "qremesher.reproject_color"
    bl_label = "重投影颜色"
    bl_description = "使用数据传输修改器从原始网格传输顶点颜色"


    def execute(self, context):
        shading = context.space_data.shading
        # switch to vertex color mode, so we can see the vertex paint
        if shading.type == 'SOLID':
            shading.color_type = 'VERTEX'
            
        mod = context.scene.qremesher.history_object.modifiers["QRemesher_DataTransfer"]
        mod.show_viewport = not mod.show_viewport
        bpy.ops.object.datalayout_transfer(modifier=mod.name)
        
        return {'FINISHED'}


class QREMESHER_OT_ReprojectSubdiv(bpy.types.Operator):
    bl_idname = "qremesher.reproject_subdiv"
    bl_label = "更改细分级别"
    bl_description = "更改重投影的细分级别"
    
    level: bpy.props.IntProperty(min=-1, max=1, default=0)

    def execute(self, context):
        qremesher = context.scene.qremesher
        obj = context.scene.qremesher.history_object
        mod = obj.modifiers["QRemesher_SubSurf"]
        mod.levels = mod.levels + self.level
        # store polycount after subdivisions, so the UI doesn't check it too often
        # (this one needs the value after modifiers are done)
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        qremesher.reproject_polycount = len(obj_eval.data.polygons)
         
        return {'FINISHED'}


# automated way to reset all settings
class QREMESHER_OT_ResetSettings(bpy.types.Operator):
    bl_idname = "qremesher.reset_settings"
    bl_label = "重置设置"
    bl_description = "将所有重构设置重置为默认值"

    def execute(self, context):
        data = bpy.data
        scene = context.scene
        # props that SHOULD be reset
        whitelist = {
            "target_count",
            "adaptive_size",
            "adapt_quad_count",
            "use_vertex_color",
            "painted_quad_density",
            "use_materials",
            "use_material_index",
            "use_normals",
            "autodetect_hard_edges",
            "symmetry_x",
            "symmetry_y",
            "symmetry_z",
            "quad_count_mode",
            "use_face_sets",
        }

        for prop in scene.qremesher.bl_rna.properties:
            if prop.identifier in whitelist:
                scene.qremesher.property_unset(prop.identifier)
            

        return {'FINISHED'}



classes = (
    QREMESHER_OT_SwitchMeshData,
    QREMESHER_OT_PurgeMeshHistory,
    QREMESHER_OT_SetQuadCount,
    QREMESHER_OT_ReprojectModeStart,
    QREMESHER_OT_ReprojectModeCancel,
    QREMESHER_OT_ReprojectModeFinish,
    QREMESHER_OT_ReprojectShape,
    QREMESHER_OT_ReprojectColor,
    QREMESHER_OT_ReprojectSubdiv,
    QREMESHER_OT_ResetSettings,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)