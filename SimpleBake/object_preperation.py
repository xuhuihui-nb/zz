import bpy
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty
from bpy.utils import register_class, unregister_class

from .utils import SBConstants
from .messages import print_message
from .aov import get_aov_name

class SimpleBake_OT_PrepareObjectMatsPbr(Operator):
    """Prepare an object for PBR baking"""
    bl_idname = "simplebake.prepare_object_mats_pbr"
    bl_description = "Prepare object for PBR bake"
    bl_label = "Prepare"
    
    target_name: StringProperty()
    this_bake: StringProperty()
    bake_operation_id: StringProperty()
    no_bake_image_node: BoolProperty(default=False)
    only_bake_image_node: BoolProperty(default=False)
    
    def create_dummy_nodes(self, context, mat):
        print_message(context, f"Creating dummy nodes for {self.target_name}")
        
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        p_nodes = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
        
        #Special case for bump
        if self.this_bake == SBConstants.PBR_BUMP:
            for p_node in p_nodes:
                #Nothing connected
                if len(p_node.inputs["Normal"].links) == 0:
                    p_node["SB_Ignore_Normal"]= True
                    continue
                #Connected but not a bump node
                bump_node = p_node.inputs["Normal"].links[0].from_node
                if bump_node.bl_idname != "ShaderNodeBump":
                    p_node["SB_Ignore_Normal"]= True
                    continue
                #Nothing connected to bump node height input
                if len(bump_node.inputs['Height'].links) == 0:
                    p_node["SB_Ignore_Normal"]= True
                    continue
                #Must be OK to be treated normally
                
                
                #p_node.inputs["Normal"]["SB_Ignore"] = False
                #if len(bump_node.inputs[2].links) == 0:
                    #val = bump_node.inputs[2].default_value
                    #vnode = nodes.new("ShaderNodeValue")
                    #vnode.outputs[0].default_value = val
                    #vnode.label = "SimpleBake"
                    #node_tree.links.new(vnode.outputs[0], bump_node.inputs[2])
        
        #Normal case, not bump
        else:
            socket_name = SBConstants.get_socket_names()[self.this_bake]
            
            for p_node in p_nodes:
                #Get the sockets we care about (correct name + empty)
                sockets = [s for s in p_node.inputs if s.name == socket_name and len(s.links)==0]
                
                for socket in sockets:
                    #If not, get value of the unconnected socket
                    val = socket.default_value
                
                    socket_type = socket.bl_idname
                
                    #if socket_type == "NodeSocketColor":
                    #Not needed, but future proofing
                    if socket_type.startswith("NodeSocketColor"):
                        rgb = nodes.new("ShaderNodeRGB")
                        rgb.outputs[0].default_value = val
                        rgb.label = "SimpleBake" #????????????????????????????
                        node_tree.links.new(rgb.outputs[0], socket)
                    
                    #if socket_type in ["NodeSocketFloat", "NodeSocketFloatFactor", "NodeSocketFloatDistance"]:
                    if socket_type.startswith("NodeSocketFloat"):
                        vnode = nodes.new("ShaderNodeValue")
                        vnode.outputs[0].default_value = val
                        vnode.label = "SimpleBake" #?????????????????????????????????????????
                        node_tree.links.new(vnode.outputs[0], socket)
        
    def bypass_muted_mix_shaders(self, mat):
        #Let's bypass all the muted mix shader nodes
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        for n in nodes:
            if n.bl_idname == "ShaderNodeMixShader" and n.mute:

                if len(n.inputs[1].links) > 0:
                    fs = n.inputs[1].links[0].from_socket
                else: fs = False
    
                if len(n.outputs[0].links) > 0:
                    ts = n.outputs[0].links[0].to_socket
                else: ts = False
    
                if fs and ts:
                    node_tree.links.new(fs, ts)
                    nodes.remove(n)
        
    def swap_e_for_p(self,mat):
    
        node_tree = mat.node_tree
        nodes = node_tree.nodes

        enodes = [n for n in nodes if n.bl_idname == "ShaderNodeEmission"]

        for e in enodes:
            cval = e.inputs[0].default_value
            sval = e.inputs[1].default_value
            pos = e.location
    
            if len(e.inputs[0].links) > 0:
                cfs = e.inputs[0].links[0].from_socket
            else:
                cfs = False
    
            if len(e.inputs[1].links) > 0:
                sfs = e.inputs[1].links[0].from_socket
            else:
                sfs = False
    
            os = e.outputs[0].links[0].to_socket
    
            #Create principled BSDF
            p = nodes.new("ShaderNodeBsdfPrincipled")
    
            if cfs:
                node_tree.links.new(cfs, p.inputs["Emission Color"])
            else:
                p.inputs["Emission Color"].default_value = cval
            
            if sfs:
                node_tree.links.new(sfs, p.inputs["Emission Strength"])
            else:
                p.inputs["Emission Strength"].default_value = sval

            p.inputs["Base Color"].default_value = (0.0,0.0,0.0,1.0)
    
            node_tree.links.new(p.outputs[0], os)
    
            p.location = pos
    
        #Last action, remove all the e nodes
        [nodes.remove(n) for n in enodes]
    
    
    def remove_disconnected(self, context, mat):
        print_message(context, f"Removing disconnected nodes from {mat.name}")
        nodes = mat.node_tree.nodes
    
        #Start with the material output node
        #Remove any not in use. So not to confuse matters.
        [nodes.remove(n) for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and len(n.inputs[0].links)==0]
        
        #Find the active material output
        mos = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output == True]
        assert(len(mos) == 1)
        active_mo = mos[0]
        
        #Is it Cycles?
        if active_mo.target in ["CYCLES", "ALL"]:
            #Yes. So we are good. Just remove the others
            mos = [nodes.remove(n) for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output == False]
        else:
            #Active not Cycles. Can we find a pre-existing Cycles one somewhere?
            mos = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.target in ["CYCLES","ALL"]]
            if len(mos)>0:
                #Found existing Cycles one, make it active and remove the others
                mos[0].is_active_output = True
                #Set to All, just for the viewport candy
                mos[0].target = "ALL"
                [nodes.remove(n) for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output == False]
            else:
                #Active isn't Cycles, and no Cycles in the material. Pick one at random. Force to Cycles
                mos = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
                mos[0].is_active_output = True
                mos[0].target = "ALL"
                [nodes.remove(n) for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output == False]
    
        #Loop through nodes to remove disconnected nodes that we care about
        repeat = False
        r = [nodes.remove(n) for n in nodes if n.type == "BSDF_PRINCIPLED" and len(n.outputs[0].links) == 0 ]
        if len(r) >0: repeat = True #We removed something
        r = [nodes.remove(n) for n in nodes if n.type == "EMISSION" and len(n.outputs[0].links) == 0 ]
        if len(r) >0: repeat = True #We removed something
        r = [nodes.remove(n) for n in nodes if n.type == "MIX_SHADER" and len(n.outputs[0].links) == 0 ]
        if len(r) >0: repeat = True #We removed something

        #Special case for Shader to RGB node
        r = [nodes.remove(n) for n in nodes if n.bl_idname == "ShaderNodeShaderToRGB" and len(n.outputs[0].links) == 0 ]
        if len(r) >0: repeat = True #We removed something
        
        #If we removed any nodes, we need to do this again
        if repeat: self.remove_disconnected(context, mat)
        
    def setup_pure_p_mat(self, context, mat):
        print_message(context, f"Setup for pure P material for {self.target_name}")
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        output_node = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
        assert(len(output_node)==1)
        output_node = output_node[0]
        
        p_node = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
        assert(len(p_node)==1)
        p_node = p_node[0]
        
        #Create an emission shader and connect to output
        emissnode = nodes.new("ShaderNodeEmission")
        emissnode.label = "SimpleBake" #??????????????????????????????????
        emissnode.location = (output_node.location.x, output_node.location.y+200)
        node_tree.links.new(emissnode.outputs[0], output_node.inputs[0])
        
        #Connect whatever is in Principled Shader for this bakemode to the emission
        if self.this_bake == SBConstants.PBR_BUMP:
            normal_socket = p_node.inputs["Normal"]
            if "SB_Ignore_Normal" in p_node:
                emissnode.inputs[0].default_value = (0.5,0.5,0.5,1)
            else:
                bump_node = p_node.inputs["Normal"].links[0].from_node
                bump_input = bump_node.inputs['Height'].links[0].from_socket
                node_tree.links.new(bump_input, emissnode.inputs[0])
        else:
            socket_name = SBConstants.get_socket_names()[self.this_bake]
            socket = p_node.inputs[socket_name]
            node_tree.links.new(socket.links[0].from_socket, emissnode.inputs[0])
            
    
    def setup_mix_mat(self, context, mat):
        print_message(context, f"Setup for mix material for {self.target_name}")
        node_tree = mat.node_tree
        nodes = node_tree.nodes
        
        output_node = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
        assert(len(output_node)==1)
        output_node = output_node[0]
        
        #For every mix shader, create a mixrgb above it
        mix_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeMixShader"]
        for mix_node in mix_nodes:
            #Create RGB mix for every mix shader node
            rgbmix = nodes.new("ShaderNodeMixRGB")
            rgbmix.location = (mix_node.location.x, mix_node.location.y+200)
            rgbmix.label="SimpleBake" #????????????????????????????????????????
            rgbmix["SB_rgb_proxy_for"] = mix_node.name
            
            #If there is one, plug the factor from the original mix node into our new mix node
            if len(mix_node.inputs[0].links) > 0:
                node_tree.links.new(mix_node.inputs[0].links[0].from_socket, rgbmix.inputs[0])
            #Else, copy the default value
            else:
                rgbmix.inputs[0].default_value = mix_node.inputs[0].default_value
            
        #Loop over the new RGBmix nodes
        rgbmix_nodes = [n for n in nodes if "SB_rgb_proxy_for" in n]
        assert(len(rgbmix_nodes)>0)
        
        for rgbmix_node in rgbmix_nodes:
            #Get the original mix node
            mix_node = nodes[rgbmix_node["SB_rgb_proxy_for"]]
            
            #Socket 1 (back to p_node)
            if len(mix_node.inputs[1].links)>0 and mix_node.inputs[1].links[0].from_node.bl_idname == "ShaderNodeBsdfPrincipled":
                origin_p_node = mix_node.inputs[1].links[0].from_node
                if self.this_bake == SBConstants.PBR_BUMP:
                    normal_socket = origin_p_node.inputs["Normal"]
                    if "SB_Ignore_Normal" in origin_p_node:
                        rgbmix_node.inputs[1].default_value = (0.5,0.5,0.5,1)
                    else:
                        bump_node = origin_p_node.inputs["Normal"].links[0].from_node
                        bump_input = bump_node.inputs['Height'].links[0].from_socket
                        node_tree.links.new(bump_input, rgbmix_node.inputs[1])
                else:
                    socket_name = SBConstants.get_socket_names()[self.this_bake]
                    origin_socket = origin_p_node.inputs[socket_name].links[0].from_socket
                    node_tree.links.new(origin_socket, rgbmix_node.inputs[1])
            
            #Socket 2 (back to p_node)
            if len(mix_node.inputs[2].links)>0 and mix_node.inputs[2].links[0].from_node.bl_idname == "ShaderNodeBsdfPrincipled":
                origin_p_node = mix_node.inputs[2].links[0].from_node
                if self.this_bake == SBConstants.PBR_BUMP:
                    normal_socket = origin_p_node.inputs["Normal"]
                    if "SB_Ignore_Normal" in origin_p_node:
                        rgbmix_node.inputs[2].default_value = (0.5,0.5,0.5,1)
                    else:
                        bump_node = origin_p_node.inputs["Normal"].links[0].from_node
                        bump_input = bump_node.inputs['Height'].links[0].from_socket
                        node_tree.links.new(bump_input, rgbmix_node.inputs[2])
                else:
                    socket_name = SBConstants.get_socket_names()[self.this_bake]
                    origin_socket = origin_p_node.inputs[socket_name].links[0].from_socket
                    node_tree.links.new(origin_socket, rgbmix_node.inputs[2])
                
            #Socket 1 (back to mix node)
            if len(mix_node.inputs[1].links)>0 and mix_node.inputs[1].links[0].from_node.bl_idname == "ShaderNodeMixShader":
                origin_mix_node = mix_node.inputs[1].links[0].from_node
                #Get the RGB mix for that origin mix node
                origin_rgbmix = [n for n in nodes if "SB_rgb_proxy_for" in n and n["SB_rgb_proxy_for"] == origin_mix_node.name]
                assert(len(origin_rgbmix) == 1)
                origin_rgbmix = origin_rgbmix[0]
                
                node_tree.links.new(origin_rgbmix.outputs[0], rgbmix_node.inputs[1])

            #Socket 2 (back to mix node)
            if len(mix_node.inputs[2].links)>0 and mix_node.inputs[2].links[0].from_node.bl_idname == "ShaderNodeMixShader":
                origin_mix_node = mix_node.inputs[2].links[0].from_node
                #Get the RGB mix for that origin mix node
                origin_rgbmix = [n for n in nodes if "SB_rgb_proxy_for" in n and n["SB_rgb_proxy_for"] == origin_mix_node.name]
                assert(len(origin_rgbmix) == 1)
                origin_rgbmix = origin_rgbmix[0]
                
                node_tree.links.new(origin_rgbmix.outputs[0], rgbmix_node.inputs[2])
                
            #Back to nowhere
            if len(mix_node.inputs[1].links) == 0:
                rgbmix_node.inputs[1].default_value = (0,0,0,1)
            if len(mix_node.inputs[2].links) == 0:
                rgbmix_node.inputs[2].default_value = (0,0,0,1)
        
        #Finally connect to the output
        final_mix = output_node.inputs[0].links[0].from_node
        final_rgbmix = [n for n in nodes if "SB_rgb_proxy_for" in n and n["SB_rgb_proxy_for"] == final_mix.name]
        assert(len(final_rgbmix)>0)
        final_rgbmix = final_rgbmix[0]
        
        node_tree.links.new(final_rgbmix.outputs[0], output_node.inputs[0])
        
    def setup_displacement(self, context, mat):
        print_message(context, f"Setup for displacement bake on {self.target_name}")
        node_tree = mat.node_tree
        nodes = node_tree.nodes

        #Find the active MO node
        mo_node = None

        for n in nodes:
            if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output:
                mo_node = n

        if mo_node == None:
            print(f"Error - no active Material Output in material {mat.name}")
            return False

        #See if anything is plugged into the Displacement Socket
        mo_disp_socket = mo_node.inputs["Displacement"]
        if len(mo_disp_socket.links) <1:
            print_message(context, f"Skipping. Nothing plugged into displacement socket for material {mat.name}")
            return True

        #Find the from node. Check it's either Displacement or Displacement Vector
        disp_node = mo_disp_socket.links[0].from_node
        if disp_node.bl_idname not in ["ShaderNodeDisplacement", "ShaderNodeVectorDisplacement"]:
            return False

        #Found disp node

        source_socket = None
        socket_name = "Height" if disp_node.bl_idname == "ShaderNodeDisplacement" else "Vector"

        #Is something plugged into Height/Vector??
        if len(disp_node.inputs[socket_name].links)>0:
            source_socket =  disp_node.inputs[socket_name].links[0].from_socket
        else:
            #NOTHING PLUGGED IN
            if disp_node.inputs[socket_name].bl_idname == "NodeSocketColor":
                #No dummy node possible
                return False
            else:
                value_node = nodes.new(type='ShaderNodeValue')
                value_node.outputs[0].default_value = disp_node.inputs[socket_name].default_value
                source_socket = value_node.outputs[0]

        if source_socket == None:
            return False

        #Create emission node and hook it up
        emission_node = nodes.new(type='ShaderNodeEmission')
        emission_node.location = (mo_node.location.x, mo_node.location.y+150)
        node_tree.links.new(source_socket, emission_node.inputs["Color"])
        node_tree.links.new(emission_node.outputs[0], mo_node.inputs["Surface"])


    def setup_aov(self, context, mat, aovname):
        print_message(context, f"Setup for AOV bake for {aovname}")
        node_tree = mat.node_tree
        nodes = node_tree.nodes

        aov_node = None
        #Find the AOV node that we want
        for n in nodes:
            if n.bl_idname == "ShaderNodeOutputAOV":
                if n.aov_name == aovname:
                    #Found it
                    aov_node = n

        #Give up if we can't find the AOV node we want (for whatver reason)
        if aov_node == None:
            return False


        #Find the active MO node
        mo_node = None
        for n in nodes:
            if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output:
                mo_node = n
        assert(mo_node!=None)

        #Col is prioritised to fit with how vanilla Blender does it
        if len(aov_node.inputs['Color'].links)>0:
            source_socket = aov_node.inputs['Color'].links[0].from_socket
        elif len(aov_node.inputs['Value'].links)>0:
            source_socket = aov_node.inputs['Value'].links[0].from_socket
        else:
            print_message(context, "ERROR - Couldn't find source of AOV node")
            return False

        #Create emission node and hook it up
        emission_node = nodes.new(type='ShaderNodeEmission')
        emission_node.location = (mo_node.location.x, mo_node.location.y+150)
        node_tree.links.new(source_socket, emission_node.inputs["Color"])
        node_tree.links.new(emission_node.outputs[0], mo_node.inputs["Surface"])


    def create_bake_image_node(self, mat, mat_name=""):

        node_tree = mat.node_tree
        nodes = node_tree.nodes

        existing_bake_nodes = [n for n in nodes if "SB_bake_image_node" in n]

        if len(existing_bake_nodes) !=0:
            #Just quit if there is already a node in this material
            #e.g. Specials are used more than once. Also object may have same PBR material multiple times
            return True

        image_node = nodes.new("ShaderNodeTexImage")
        #Where is the image we want? This is different for a merged bake or per-mat bake
        if not self.merged_bake:
            if mat_name:
                # tex_per_mat: find the image specific to this material
                image_name = ([i.name for i in bpy.data.images if
                    i.get("SB_bake_object") == self.target_name and
                    i.get("SB_bake_operation_id") == self.bake_operation_id and
                    i.get("SB_this_bake") == self.this_bake and
                    i.get("SB_bake_material") == mat_name
                    ])
            else:
                image_name = ([i.name for i in bpy.data.images if
                    "SB_bake_object" in i and i["SB_bake_object"] == self.target_name and
                    "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id and
                    "SB_this_bake" in i and i["SB_this_bake"] == self.this_bake
                    ])
        else:
            image_name = ([i.name for i in bpy.data.images if
                "SB_bake_operation_id" in i and i["SB_bake_operation_id"] == self.bake_operation_id and
                "SB_this_bake" in i and i["SB_this_bake"] == self.this_bake
                ])
        assert len(image_name)==1, f"Found {len(image_name)} images looking for {self.this_bake}"
        image_name = image_name[0]

        image_node.image = bpy.data.images[image_name]
        #Leave it the only node selected
        for n in nodes:
            n.select = False
        image_node.select = True
        nodes.active = image_node

        image_node["SB_bake_image_node"] = True

        return True

    def create_dummy_bake_image_node(self, mat):
        """Create a throwaway 1x1 image node for excluded materials so Blender has
        somewhere to write their pixels (output is discarded)."""
        node_tree = mat.node_tree
        nodes = node_tree.nodes

        existing_bake_nodes = [n for n in nodes if "SB_bake_image_node" in n]
        if existing_bake_nodes:
            return

        dummy_name = "SB_excluded_mat_dummy"
        if dummy_name not in bpy.data.images:
            dummy = bpy.data.images.new(dummy_name, 1, 1, alpha=False)
            dummy["SB_dummy"] = True
        else:
            dummy = bpy.data.images[dummy_name]

        image_node = nodes.new("ShaderNodeTexImage")
        image_node.image = dummy
        for n in nodes:
            n.select = False
        image_node.select = True
        nodes.active = image_node
        image_node["SB_bake_image_node"] = True
        
    def execute(self, context):

        sbp = context.scene.SimpleBake_Props
        self.merged_bake = sbp.merged_bake
        mats=[]

        if not (o:= context.scene.objects.get(self.target_name)):
            print_message(context, f"ERROR: Preparing object. Couldn't find {self.target_name}!")
            return {'CANCELLED'}
        else:
            #Get list of materials for target object
            mats = [slot.material for slot in o.material_slots if slot.material!=None]

        # Build per-material enabled/disabled sets from mat_bake_list (empty = no restrictions)
        # Working backup materials have an SBW_ prefix — strip it to get the original name
        mat_entries = [e for e in sbp.mat_bake_list if e.obj_name == self.target_name]
        enabled_mat_names = {e.mat_name for e in mat_entries if e.enabled}
        disabled_mat_names = {e.mat_name for e in mat_entries if not e.enabled}
        has_restrictions = bool(mat_entries)  # any mat_bake_list entries for this object

        def orig_name(mat):
            """Return the original material name, stripping SBW_ (working) and SBM_ (master) backup prefixes."""
            name = mat.name
            if name.startswith("SBW_"):
                name = name[4:]
            if name.startswith("SBM_"):
                name = name[4:]
            return name

        #No prep needed for normal or any specials. Just create bake image node (if that)
        if (self.this_bake == SBConstants.PBR_NORMAL) or (self.this_bake in SBConstants.ALL_SPECIALS):
            print_message(context, "No object prep needed - specials or normal map")
            if not self.no_bake_image_node:
                for mat in mats:
                    oname = orig_name(mat)
                    if self.this_bake in SBConstants.ALL_SPECIALS and "SB_original_mat_name" in mat:
                        oname = mat["SB_original_mat_name"]
                    if has_restrictions and oname in disabled_mat_names:
                        self.create_dummy_bake_image_node(mat)
                    else:
                        use_per_mat = sbp.tex_per_mat and not self.merged_bake and has_restrictions
                        bake_mat_name = oname if use_per_mat else ""
                        self.create_bake_image_node(mat, mat_name=bake_mat_name)
                    mat["SB_bake_config"] = self.this_bake
            return {'FINISHED'}

        #Otherwise, prepare each material for this bake type
        for mat in mats:

            oname = orig_name(mat)

            # Handle excluded materials
            if has_restrictions and oname in disabled_mat_names:
                print_message(context, f"Material {mat.name} is excluded - creating dummy node")
                self.create_dummy_bake_image_node(mat)
                continue

            if "SB_bake_config" in mat and mat["SB_bake_config"] == self.this_bake:
                print_message(context, f"Material {mat.name} is already in correct config for {self.this_bake}")
                continue

            # mat_name to use when looking up per-material image (use original name, not working backup name)
            # Only use per-mat lookup if this object has mat_bake_list entries (i.e. it's a source object,
            # not an S2A target object which won't have any entries)
            bake_mat_name = oname if (sbp.tex_per_mat and not self.merged_bake and has_restrictions) else ""

            if self.only_bake_image_node:
                print_message(context, f"Just creating bake image node in mat {mat}")
                self.create_bake_image_node(mat, mat_name=bake_mat_name)
                continue

            #Special case for displacement. Don't need to mess with outher nodes
            if self.this_bake == SBConstants.PBR_DISPLACEMENT:
                self.setup_displacement(context, mat)
                if not self.no_bake_image_node:
                    self.create_bake_image_node(mat, mat_name=bake_mat_name)
                mat["SB_bake_config"] = self.this_bake #TODO-----------------CHECK FOR ISSUES
                continue

            #Special case for AOVs. Don't need to mess with outher nodes
            print(f"--------------- {self.this_bake}")
            if SBConstants.PBRAOVS in self.this_bake:
                aovname = get_aov_name(context, self.this_bake)

                self.setup_aov(context, mat, aovname)
                if not self.no_bake_image_node:
                    self.create_bake_image_node(mat, mat_name=bake_mat_name)
                mat["SB_bake_config"] = self.this_bake
                continue

            #Bypass muted mix shaders
            self.bypass_muted_mix_shaders(mat)

            #Remove disconnected nodes
            self.remove_disconnected(context, mat)

            #Swap all e for p
            self.swap_e_for_p(mat)

            #What kind of material is this?
            node_tree = mat.node_tree
            nodes = node_tree.nodes
            pnodes=True if len([n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"])>0 else False
            mixnodes=True if len([n for n in nodes if n.bl_idname == "ShaderNodeMixShader"])>0 else False

            if (pnodes and mixnodes) or (pnodes and mixnodes and enodes):
                print_message(context, "This is a Mix Material")
                self.create_dummy_nodes(context, mat)
                self.setup_mix_mat(context, mat)
                mat["SB_bake_config"] = self.this_bake #TODO-----------------CHECK FOR ISSUES
            elif(pnodes and not mixnodes):
                #print_message(context, "This is a Pure P material")
                self.create_dummy_nodes(context, mat)
                self.setup_pure_p_mat(context, mat)
                mat["SB_bake_config"] = self.this_bake #TODO-----------------CHECK FOR ISSUES
            else:
                print_message(context, "Non-PBR material type - will still create bake image node")

            if not self.no_bake_image_node:
                self.create_bake_image_node(mat, mat_name=bake_mat_name)


        return {'FINISHED'}


classes = ([
        SimpleBake_OT_PrepareObjectMatsPbr
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
