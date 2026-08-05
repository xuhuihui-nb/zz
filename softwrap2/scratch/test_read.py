import sys
import os
import bpy

addon_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(addon_dir, "core"))

import gpu
from gpu_engine import make_texture_1d, read_texture_flat

def test():
    print("---------------------------------------------")
    print("Testing make_texture_1d and read_texture_flat...")
    data = [1.0, 2.0, 3.0, 4.0] * 5
    tex = make_texture_1d(5, data)
    readback = read_texture_flat(tex)
    print(f"Original length: {len(data)}, Readback length: {len(readback)}")
    print(f"Original: {data[:12]}")
    print(f"Readback: {readback[:12]}")
    print("---------------------------------------------")

if __name__ == "__main__":
    try:
        test()
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
