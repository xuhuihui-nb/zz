import os

import bpy

from ..constants import Global


def get_temp_path() -> str:
    """Gets or creates a temporary directory.

    Tries the Blender extension path API first (works when installed as an
    extension). Falls back to a ``temp`` folder next to the addon itself when
    the addon is loaded as a legacy add-on (no extension package context).
    """
    pkg = __package__.rsplit(".", maxsplit=1)[0]
    try:
        return bpy.utils.extension_path_user(pkg, path="temp", create=True)
    except (ValueError, AttributeError):
        # Legacy addon path: use a temp/ dir next to the addon package
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        temp_dir = os.path.join(addon_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir


def get_format() -> str:
    """Get the correct file extension based on `format` attribute"""
    return f".{Global.IMAGE_FORMATS[bpy.context.scene.gd.format]}"


def get_filepath() -> str:
    """Get the absolute export filepath from the user preferences"""
    gd = bpy.context.scene.gd
    if not gd.filepath:
        return "//"
    return gd.filepath
