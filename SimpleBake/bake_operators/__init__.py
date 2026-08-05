from . import pbr_bake_operators
from . import common_bake_support
from . import specials_bake_operators
from . import pbr_bake_support_operators
from . import cycles_bake_operators
from . import cyclesbake_support_operators
from . import auto_match_operators
from . import decal_operators
from . import image_sequence

def register():
    pbr_bake_operators.register()
    pbr_bake_support_operators.register()
    common_bake_support.register()
    specials_bake_operators.register()
    cycles_bake_operators.register()
    cyclesbake_support_operators.register()
    auto_match_operators.register()
    decal_operators.register()
    image_sequence.register()
    
def unregister():
    pbr_bake_operators.unregister()
    pbr_bake_support_operators.unregister()
    common_bake_support.unregister()
    specials_bake_operators.unregister()
    cycles_bake_operators.unregister()
    cyclesbake_support_operators.unregister()
    auto_match_operators.unregister()
    decal_operators.unregister()
    image_sequence.unregister()
 
