import bpy
import uuid
import json
import os
import ctypes
from bpy.app.handlers import persistent

def get_areas(screen):
    if not screen:
        return []
    return [a for a in screen.areas if a.type not in {'STATUSBAR', 'TOPBAR'}]


bl_info = {
    "name": "窗口切换",
    "author": "Trae",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > N Panel > 窗口切换",
    "description": "在N面板显示当前Blender窗口布局",
    "category": "Window",
}


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "presets.json")
CACHED_PRESETS = {}

# --- Window Persistence Helpers ---

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]

def setup_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def get_blender_window_rects():
    """Get geometry of all current Blender windows using Windows API"""
    rects = []
    
    # DPI Awareness is now handled globally in register
            
    # 2. Find all windows belonging to current process
    pid = os.getpid()
    
    def enum_windows_callback(hwnd, lParam):
        # Check if window belongs to this process
        window_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        
        if window_pid.value == pid:
            # Check if visible
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                # Filter out tooltips/popups by checking class name if needed
                # For now, just rely on visibility and maybe window title length?
                # Actually, Blender's main windows usually have a title.
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                     return True
                     
                rect = RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                
                # Calculate width/height from rect
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                
                # Filter out tiny windows (tooltips, invisible helper windows)
                if width < 100 or height < 100:
                    return True

                rects.append({
                    'x': rect.left,
                    'y': rect.top,
                    'width': width,
                    'height': height,
                    'hwnd': hwnd
                })
        return True
        
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    ctypes.windll.user32.EnumWindows(CMPFUNC(enum_windows_callback), 0)
    
    # Sort: Main window is usually at (0,0) or has specific properties, but here we rely on creation order?
    # Actually, we just need to ensure consistent order.
    # Let's sort by X then Y to have a deterministic order from left to right, top to bottom.
    # This matches how users typically arrange screens.
    rects.sort(key=lambda r: (r['x'], r['y']))
    
    return rects

def prevent_white_flash(hwnd):
    """
    Sets the window class background brush to a dark gray brush to reduce flash intensity.
    """
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        
        # GCLP_HBRBACKGROUND = -10
        
        # Check if 64-bit
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            # Try SetClassLongPtrW first
            if hasattr(user32, "SetClassLongPtrW"):
                SetClassLongPtr = user32.SetClassLongPtrW
            else:
                # Fallback, though uncommon on 64-bit python
                SetClassLongPtr = user32.SetClassLongW
        else:
            SetClassLongPtr = user32.SetClassLongW
            
        SetClassLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        SetClassLongPtr.restype = ctypes.c_void_p
        
        # Use Stock Object to avoid GDI leaks
        # DKGRAY_BRUSH = 3
        # BLACK_BRUSH = 4
        # NULL_BRUSH = 5
        
        # We use BLACK_BRUSH (4) for maximum darkness
        hBrush = gdi32.GetStockObject(4) 
        
        # Set Class Background Brush
        SetClassLongPtr(hwnd, -10, hBrush)
        
        # Force a repaint to apply the new background immediately if needed?
        # Actually, we want the *next* repaint (resize) to use this.
        
    except Exception as e:
        # print(f"MBQH: Failed to prevent white flash: {e}")
        pass

def set_window_geometry(x, y, width, height):
    """
    Sets the position and size of the currently active Blender window (Windows only).
    """
    try:
        # Get active window handle
        hwnd = ctypes.windll.user32.GetActiveWindow()
        if not hwnd:
            return

        # Try to prevent white flash by setting class background
        # prevent_white_flash(hwnd) # Already handled in register()

        # SWP_NOZORDER (0x0004) ignores the Z-order
        # SWP_NOACTIVATE (0x0010)
        # SWP_NOCOPYBITS (0x0100) Discards the entire contents of the client area.
        flags = 0x0004 | 0x0100
        
        ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, width, height, flags)
    except Exception as e:
        print(f"Failed to set window geometry: {e}")

def save_window_layout():
    """Save current window configuration to presets"""
    global CACHED_PRESETS
    CACHED_PRESETS['window_layout'] = get_blender_window_rects()
    save_config()

@persistent
def restore_window_layout(dummy):
    """Restore window layout on startup"""
    global CACHED_PRESETS
    load_config() # Ensure fresh config
    
    saved_layout = CACHED_PRESETS.get('window_layout', [])
    if not saved_layout:
        return
        
    current_windows = bpy.context.window_manager.windows
    
    # 1. Create missing windows
    needed = len(saved_layout) - len(current_windows)
    start_index = len(current_windows)
    
    if needed > 0:
        # We need to execute operators, but load_post might run before context is fully ready for ops?
        # Usually fine.
        for i in range(needed):
            target_idx = start_index + i
            if target_idx < len(saved_layout):
                rect = saved_layout[target_idx]
                try:
                    # Create new window
                    bpy.ops.wm.window_new()
                    # Set geometry immediately (it's active)
                    set_window_geometry(rect['x'], rect['y'], rect['width'], rect['height'])
                except Exception as e:
                    print(f"MBQH: Failed to restore window: {e}")


class MBQH_OT_SaveWindowLayout(bpy.types.Operator):
    """Save current window layout positions"""
    bl_idname = "mbqh.save_window_layout"
    bl_label = "Save Window Layout"
    
    def execute(self, context):
        save_window_layout()
        self.report({'INFO'}, "Window layout saved")
        return {'FINISHED'}

class MBQH_OT_RestoreWindowLayout(bpy.types.Operator):
    """Restore saved window layout"""
    bl_idname = "mbqh.restore_window_layout"
    bl_label = "Restore Window Layout"
    
    def execute(self, context):
        saved_layout = CACHED_PRESETS.get('window_layout', [])
        if not saved_layout:
            self.report({'WARNING'}, "No saved layout found")
            return {'CANCELLED'}
            
        current_windows = context.window_manager.windows
        
        # Create missing windows
        needed = len(saved_layout) - len(current_windows)
        
        # Strategy:
        # 1. Main window (index 0) - Try to set if possible? 
        #    Actually, we can't easily set non-active window geometry without HWND mapping.
        #    We will focus on creating NEW windows with correct geometry.
        
        # 2. For new windows, we create them one by one.
        #    Each creation makes it active -> Set geometry immediately.
        
        start_index = len(current_windows)
        
        for i in range(needed):
            # Target geometry
            target_idx = start_index + i
            if target_idx < len(saved_layout):
                rect = saved_layout[target_idx]
                
                bpy.ops.wm.window_new()
                # New window is now active
                set_window_geometry(rect['x'], rect['y'], rect['width'], rect['height'])
                
        return {'FINISHED'}

def load_config():
    global CACHED_PRESETS
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                CACHED_PRESETS = json.load(f)
        except:
            CACHED_PRESETS = {}

def save_config():
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(CACHED_PRESETS, f, indent=4)
    except:
        pass

def find_area_and_screen(context, area_pointer=None, x=None, y=None, settings_id=None):
    """Helper to find area and its screen across all windows"""
    for window in context.window_manager.windows:
        screen = window.screen
        
        # 1. Try by ID in settings
        if settings_id:
            for item in screen.mbqh_area_cache:
                if item.id == settings_id:
                    # Found the settings object, now find the area in this screen
                    for area in get_areas(screen):
                        if str(area.as_pointer()) == item.area_pointer:
                            return area, screen, item
                    # Fallback by coords
                    for area in get_areas(screen):
                        if area.x == item.x and area.y == item.y:
                            return area, screen, item
                            
        # 2. Try by pointer
        if area_pointer:
            for area in get_areas(screen):
                if str(area.as_pointer()) == area_pointer:
                    # Found area, get settings
                    settings = get_area_settings(screen, area)
                    return area, screen, settings
                    
        # 3. Try by coords (only if screen matches context or we are desperate? 
        # Coords are global screen coords? No, window relative usually. 
        # But x/y in Blender areas are usually relative to window. 
        # So x/y matching is risky across windows without knowing the window.
        # We'll skip x/y global search unless we are sure.)
        
    return None, None, None

def update_preset(self, context):
    """Deprecated: No longer used for auto-save"""
    pass

def get_area_node(areas, bounds):
    """
    Recursively build a tree of areas based on their coordinates.
    bounds: (min_x, min_y, max_x, max_y)
    """
    if not areas:
        return None
        
    # Base case: single area
    if len(areas) == 1:
        return {'type': 'LEAF', 'area': areas[0]}
        
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    
    # Sort unique coordinates
    xs = sorted(list(set([a.x for a in areas] + [a.x + a.width for a in areas])))
    ys = sorted(list(set([a.y for a in areas] + [a.y + a.height for a in areas])))
    
    # Filter coordinates strictly within bounds
    valid_xs = [x for x in xs if min_x < x < max_x]
    valid_ys = [y for y in ys if min_y < y < max_y]
    
    # Try vertical split (Left/Right) - corresponds to layout.split()
    for x in valid_xs:
        left = [a for a in areas if a.x + a.width <= x]
        right = [a for a in areas if a.x >= x]
        if len(left) + len(right) == len(areas) and left and right:
            return {
                'type': 'H_SPLIT', 
                'split_x': x,
                'factor': (x - min_x) / width,
                'left': get_area_node(left, (min_x, min_y, x, max_y)),
                'right': get_area_node(right, (x, min_y, max_x, max_y))
            }
            
    # Try horizontal split (Top/Bottom) - corresponds to layout.column()
    for y in valid_ys:
        bottom = [a for a in areas if a.y + a.height <= y]
        top = [a for a in areas if a.y >= y]
        if len(bottom) + len(top) == len(areas) and bottom and top:
            return {
                'type': 'V_SPLIT',
                'split_y': y,
                'top': get_area_node(top, (min_x, y, max_x, max_y)),
                'bottom': get_area_node(bottom, (min_x, min_y, max_x, y))
            }
            
    # Fallback if no clean split found (should not happen in standard tiling)
    return {'type': 'LEAF_LIST', 'areas': areas}

# --- Data ---
AREA_TYPE_ITEMS = [
    ('NONE', "无", "", 'X', -1),
    ('VIEW_3D', "3D 视图", "", 'VIEW3D', 0),
    ('IMAGE_EDITOR', "图像编辑器", "", 'IMAGE_DATA', 1),
    ('UV', "UV编辑器", "", 'UV', 22),
    ('GeometryNodeTree', "几何节点编辑器", "", 'NODETREE', 2),
    ('SEQUENCE_EDITOR', "视频序列编辑器", "", 'SEQUENCE', 3),
    ('CLIP_EDITOR', "影片剪辑编辑器", "", 'TRACKER', 4),
    ('DOPESHEET', "动画摄影表", "", 'ACTION', 5),
    ('FCURVES', "曲线编辑器", "", 'GRAPH', 6),
    ('NLA_EDITOR', "非线性动画", "", 'NLA', 7),
    ('TEXT_EDITOR', "文本编辑器", "", 'TEXT', 8),
    ('CONSOLE', "Python控制台", "", 'CONSOLE', 9),
    ('INFO', "信息", "", 'INFO', 10),
    ('OUTLINER', "大纲视图", "", 'OUTLINER', 11),
    ('PROPERTIES', "属性", "", 'PROPERTIES', 12),
    ('FILES', "文件浏览器", "", 'FILEBROWSER', 13),
    ('PREFERENCES', "偏好设置", "", 'PREFERENCES', 14),
    ('ASSETS', "资产浏览器", "", 'ASSET_MANAGER', 16),
    ('SPREADSHEET', "电子表格", "", 'SPREADSHEET', 17),
    ('ShaderNodeTree', "着色器编辑器", "", 'NODE_MATERIAL', 18),
    ('CompositorNodeTree', "合成器", "", 'NODE_COMPOSITING', 19),
    ('TextureNodeTree', "纹理节点编辑器", "", 'NODE_TEXTURE', 20),
    ('TIMELINE', "时间线", "", 'TIME', 21),
    ('DRIVERS', "驱动器", "", 'DRIVER', 23),
]

def get_type_icon(type_name):
    """Helper to get icon for a specific area type"""
    for item in AREA_TYPE_ITEMS:
        if item[0] == type_name:
            return item[3]
    return 'WINDOW'

class MBQH_AreaSettings(bpy.types.PropertyGroup):
    """Store custom properties and unique ID for each area"""
    id: bpy.props.StringProperty(name="Area ID", default="")
    
    # Tracking properties to link back to the transient Area object
    # Pointers can be large (64-bit), so use StringProperty to store as hex/string
    area_pointer: bpy.props.StringProperty()
    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()
    
    # Store the original type of the window
    original_type: bpy.props.StringProperty(name="Original Type", default="")
    
    preset_1: bpy.props.EnumProperty(
        name="Preset 1",
        description="First preset area type",
        items=AREA_TYPE_ITEMS,
        default='VIEW_3D'
    )
    preset_2: bpy.props.EnumProperty(
        name="Preset 2",
        description="Second preset area type",
        items=AREA_TYPE_ITEMS,
        default='PROPERTIES'
    )
    preset_3: bpy.props.EnumProperty(
        name="Preset 3",
        description="Third preset area type",
        items=AREA_TYPE_ITEMS,
        default='OUTLINER'
    )
    
    # Shortcut properties - now just for internal storage/loading
    shortcut_key: bpy.props.StringProperty(name="Shortcut Key", default="")
    shortcut_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False)
    shortcut_shift: bpy.props.BoolProperty(name="Shift", default=False)
    shortcut_alt: bpy.props.BoolProperty(name="Alt", default=False)
    
    # State tracking
    is_initialized: bpy.props.BoolProperty(default=False)

def get_area_settings(screen, area):
    """Retrieve or create settings for a specific area using fuzzy matching"""
    ptr = str(area.as_pointer())
    found_item = None
    
    # 1. Try exact pointer match (fastest and most reliable for current session)
    for item in screen.mbqh_area_cache:
        if item.area_pointer == ptr:
            item.x = area.x
            item.y = area.y
            found_item = item
            break
            
    # 2. Try coordinate match (fallback for session restore/reload)
    if not found_item:
        for item in screen.mbqh_area_cache:
            if item.x == area.x and item.y == area.y:
                item.area_pointer = ptr
                found_item = item
                break
            
    # 3. Create new settings if not found
    if not found_item:
        found_item = screen.mbqh_area_cache.add()
        found_item.id = str(uuid.uuid4())
        found_item.area_pointer = ptr
        found_item.x = area.x
        found_item.y = area.y
    
    # --- Load Defaults from Cache ---
    # Only load if not initialized to prevent overwriting during runtime type changes
    if found_item.is_initialized:
        return found_item
        
    target_type = getattr(area, "ui_type", area.type)
    siblings = []
    for a in get_areas(screen):
        t = getattr(a, "ui_type", a.type)
        if t == target_type:
            siblings.append(a)
    
    # Sort by -Y, X (Top-Left priority)
    siblings.sort(key=lambda a: (-a.y, a.x))
    
    try:
        index = siblings.index(area)
    except ValueError:
        index = 0
    
    if target_type in CACHED_PRESETS:
        idx_str = str(index)
        if idx_str in CACHED_PRESETS[target_type]:
            data = CACHED_PRESETS[target_type][idx_str]
            
            # Helper to validate and sanitize preset value
            def validate_preset(val, default):
                # Check if val is a valid item in AREA_TYPE_ITEMS
                valid_keys = [item[0] for item in AREA_TYPE_ITEMS]
                if val in valid_keys:
                    return val
                
                # Handle legacy/incorrect mapping
                if val == 'DOPESHEET_EDITOR':
                    return 'DOPESHEET'
                
                # Handle GRAPH_EDITOR mismatch
                if val == 'GRAPH_EDITOR':
                    return 'FCURVES'
                
                # Handle FILE_BROWSER mismatch
                if val == 'FILE_BROWSER':
                    return 'FILES'
                
                # Try to fuzzy match if suffix missing
                if val and val + '_EDITOR' in valid_keys:
                    return val + '_EDITOR'
                    
                return default

            # Update only if different to avoid redundant updates/callbacks
            p1 = validate_preset(data.get('preset_1', 'VIEW_3D'), 'VIEW_3D')
            if found_item.preset_1 != p1:
                found_item.preset_1 = p1
            
            p2 = validate_preset(data.get('preset_2', 'PROPERTIES'), 'PROPERTIES')
            if found_item.preset_2 != p2:
                found_item.preset_2 = p2
                
            p3 = validate_preset(data.get('preset_3', 'OUTLINER'), 'OUTLINER')
            if found_item.preset_3 != p3:
                found_item.preset_3 = p3

            # Load Shortcut
            found_item.shortcut_key = data.get('shortcut_key', '')
            found_item.shortcut_ctrl = data.get('shortcut_ctrl', False)
            found_item.shortcut_shift = data.get('shortcut_shift', False)
            found_item.shortcut_alt = data.get('shortcut_alt', False)
    
    # Mark as initialized
    found_item.is_initialized = True
            
    return found_item

def get_effective_type(screen, area):
    settings = get_area_settings(screen, area)
    current_type = getattr(area, "ui_type", area.type)
    
    if settings.original_type:
            # Helper to validate and sanitize original_type value
            # Same logic as validate_preset but we might need to handle cases where original_type is not in our list
            # but is still valid for Blender. 
            # However, known_types set below expects valid Enum keys or exact matches.
            
            # The issue might be that original_type itself is stored as 'DOPESHEET' 
            # while the actual area type in Blender is 'DOPESHEET_EDITOR'.
            # Or vice versa.
            
            # Let's ensure we use the same validation for checking known types.
            
            known_types = {
                settings.original_type, 
                settings.preset_1, 
                settings.preset_2, 
                settings.preset_3
            }
            
            # Handle legacy DOPESHEET mapping for comparison
            if 'DOPESHEET' in known_types:
                known_types.add('DOPESHEET_EDITOR')
            if 'DOPESHEET_EDITOR' in known_types:
                known_types.add('DOPESHEET')
            
            # Handle GRAPH_EDITOR mapping
            if 'GRAPH_EDITOR' in known_types:
                known_types.add('FCURVES')
            if 'FCURVES' in known_types:
                known_types.add('GRAPH_EDITOR')
            
            # Handle FILE_BROWSER / FILES mapping
            if 'FILE_BROWSER' in known_types:
                known_types.add('FILES')
            if 'FILES' in known_types:
                known_types.add('FILE_BROWSER')
                
            if current_type in known_types:
                return settings.original_type
    
    return current_type

def get_grouped_areas(screen):
    """Helper to get grouped and sorted areas to ensure consistent naming"""
    area_groups = {}
    for area in get_areas(screen):
        type_key = get_effective_type(screen, area)
        if type_key not in area_groups:
            area_groups[type_key] = []
        area_groups[type_key].append(area)
    
    for key in area_groups:
        area_groups[key].sort(key=lambda a: (-a.y, a.x))
        
    return area_groups

def get_keymap_item(target_type, target_index, area_id=None):
    """Find existing keymap item for this target"""
    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        return None
    
    km = wm.keyconfigs.addon.keymaps.get("Window")
    if not km:
        return None
        
    for kmi in km.keymap_items:
        if kmi.idname == "mbqh.select_area":
            # Check ID match first (Strongest)
            if area_id and getattr(kmi.properties, "area_id", "") == area_id:
                 return kmi
                 
            # Check Type/Index match (Legacy/Fallback)
            if kmi.properties.target_ui_type == target_type and kmi.properties.target_index == target_index:
                return kmi
    return None

def ensure_keymap_item(target_type, target_index, area_id=None):
    """Get or create keymap item"""
    kmi = get_keymap_item(target_type, target_index, area_id)
    if kmi:
        return kmi
        
    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        return None
        
    km = wm.keyconfigs.addon.keymaps.get("Window")
    if not km:
        km = wm.keyconfigs.addon.keymaps.new(name="Window", space_type='EMPTY', region_type='WINDOW')
        
    kmi = km.keymap_items.new("mbqh.select_area", type='NONE', value='PRESS')
    kmi.properties.target_ui_type = target_type
    kmi.properties.target_index = target_index
    if area_id:
        kmi.properties.area_id = area_id
        kmi.properties.from_keymap = True
    return kmi

def sync_shortcuts_to_cache():
    """Sync all current keymap items back to Settings Objects"""
    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        return
        
    km = wm.keyconfigs.addon.keymaps.get("Window")
    if not km:
        return
        
    # Iterate keymap items and update settings objects
    for kmi in km.keymap_items:
        if kmi.idname == "mbqh.select_area":
            
            # Find the settings object this KMI refers to
            target_settings = None
            
            # 1. By ID
            aid = getattr(kmi.properties, "area_id", "")
            if aid:
                # Search all windows
                for win in wm.windows:
                    if not win.screen: continue
                    for item in win.screen.mbqh_area_cache:
                        if item.id == aid:
                            target_settings = item
                            break
                    if target_settings: break
            
            # 2. By Type/Index (Fallback)
            if not target_settings:
                t_type = kmi.properties.target_ui_type
                t_idx = kmi.properties.target_index
                
                if t_type and t_idx >= 0:
                    # We need to find the area matching this
                    # This is tricky because we don't know which screen.
                    # We have to search all screens?
                    # Or just assume active context? No, context not passed.
                    # We iterate all screens.
                    for win in wm.windows:
                        screen = win.screen
                        if not screen: continue
                        
                        siblings = []
                        for a in get_areas(screen):
                            t = get_effective_type(screen, a)
                            if t == t_type:
                                siblings.append(a)
                        siblings.sort(key=lambda a: (-a.y, a.x))
                        
                        if t_idx < len(siblings):
                            area = siblings[t_idx]
                            target_settings = get_area_settings(screen, area)
                            # Found one match. Is it the right one? 
                            # Type/Index is ambiguous across screens if multiple screens have same layout.
                            # But usually we only care about the one user is editing?
                            # This fallback is weak. ID is preferred.
                            break
                        if target_settings: break
            
            if target_settings:
                # Update settings from KMI
                key = kmi.type if kmi.type != 'NONE' else ""
                
                # Only update if different to avoid overhead?
                target_settings.shortcut_key = key
                target_settings.shortcut_ctrl = kmi.ctrl
                target_settings.shortcut_shift = kmi.shift
                target_settings.shortcut_alt = kmi.alt

def sync_presets_to_cache(context):
    """Sync all area presets to CACHED_PRESETS from PropertyGroups"""
    global CACHED_PRESETS
    
    # 1. Preserve Layout Data (we don't want to lose window positions)
    layout_keys = {'window_layout', 'windows', 'windows_layout', 'aux_windows'}
    preserved_data = {k: v for k, v in CACHED_PRESETS.items() if k in layout_keys}
    
    # 2. Reset Cache (to clear stale entries)
    CACHED_PRESETS.clear()
    CACHED_PRESETS.update(preserved_data)
    
    # 3. Iterate Active Windows & Areas
    for window in context.window_manager.windows:
        screen = window.screen
        if not screen: continue
        
        # Group areas by effective type to determine indices
        area_groups = {}
        for area in get_areas(screen):
            t = get_effective_type(screen, area)
            if t not in area_groups:
                area_groups[t] = []
            area_groups[t].append(area)
            
        # Sort each group (Top-Left priority) to ensure stable indexing
        for t in area_groups:
            area_groups[t].sort(key=lambda a: (-a.y, a.x))
            
        # Now iterate and save
        for t, areas in area_groups.items():
            for i, area in enumerate(areas):
                # This gets the exact settings object bound to the UI
                settings = get_area_settings(screen, area)
                
                if t not in CACHED_PRESETS:
                    CACHED_PRESETS[t] = {}
                
                idx_str = str(i)
                CACHED_PRESETS[t][idx_str] = {
                    'preset_1': settings.preset_1,
                    'preset_2': settings.preset_2,
                    'preset_3': settings.preset_3,
                    'shortcut_key': settings.shortcut_key,
                    'shortcut_ctrl': settings.shortcut_ctrl,
                    'shortcut_shift': settings.shortcut_shift,
                    'shortcut_alt': settings.shortcut_alt
                }

class MBQH_OT_save_shortcuts(bpy.types.Operator):
    """Save current shortcuts to config file"""
    bl_idname = "mbqh.save_shortcuts"
    bl_label = "Save Settings"
    bl_description = "Save current configuration (Shortcuts, Presets, Layout)"
    
    def execute(self, context):
        # 1. Sync Keymaps -> Settings (Shortcuts)
        sync_shortcuts_to_cache()
        
        # 2. Sync Settings -> Cache (Presets + Shortcuts)
        # This is crucial: we pull from the PropertyGroups that the UI is bound to
        sync_presets_to_cache(context)
        
        # 3. Save Window Layout -> Cache & Disk
        # save_window_layout() already saves config, but we'll do it again explicitly to be safe
        save_window_layout()
        
        # 4. Explicit Save to Disk
        # Ensure we actually write it!
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(CACHED_PRESETS, f, indent=4)
            self.report({'INFO'}, "Settings saved successfully")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save settings: {e}")
            
        return {'FINISHED'}

class MBQH_OT_clear_shortcut(bpy.types.Operator):
    """Clear the shortcut for this area"""
    bl_idname = "mbqh.clear_shortcut"
    bl_label = "Clear Shortcut"
    bl_description = "Clear the shortcut key for this area"
    bl_options = {'INTERNAL'}
    
    target_ui_type: bpy.props.StringProperty()
    target_index: bpy.props.IntProperty()
    area_id: bpy.props.StringProperty()
    
    def execute(self, context):
        # 1. Remove KMI
        kmi = get_keymap_item(self.target_ui_type, self.target_index, self.area_id)
        if kmi:
            wm = context.window_manager
            km = wm.keyconfigs.addon.keymaps.get("Window")
            if km:
                try:
                    km.keymap_items.remove(kmi)
                except Exception:
                    pass
        
        # 2. Clear Settings Object (CRITICAL FIX)
        settings = None
        screen = context.screen
        
        # Try finding by ID first
        if self.area_id:
            for item in screen.mbqh_area_cache:
                if item.id == self.area_id:
                    settings = item
                    break
        
        # Fallback to Type/Index
        if not settings and self.target_ui_type and self.target_index >= 0:
            siblings = []
            for a in get_areas(screen):
                t = get_effective_type(screen, a)
                if t == self.target_ui_type:
                    siblings.append(a)
            siblings.sort(key=lambda a: (-a.y, a.x))
            
            if self.target_index < len(siblings):
                area = siblings[self.target_index]
                settings = get_area_settings(screen, area)
        
        if settings:
            settings.shortcut_key = ""
            settings.shortcut_ctrl = False
            settings.shortcut_shift = False
            settings.shortcut_alt = False
            self.report({'INFO'}, "Shortcut cleared")
        else:
            self.report({'WARNING'}, "Shortcut cleared from UI, but settings object not found")
            
        # Force UI redraw
        for win in context.window_manager.windows:
            if win.screen:
                for area in get_areas(win.screen):
                    area.tag_redraw()
                        
        return {'FINISHED'}

class MBQH_OT_CreateIndependentWindow(bpy.types.Operator):
    """Create a new independent window"""
    bl_idname = "mbqh.create_independent_window"
    bl_label = "+ 独立窗口"
    bl_description = "Create a new independent window"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.wm.window_new()
        # Removed auto-save logic
        return {'FINISHED'}





class MBQH_OT_switch_to_preset(bpy.types.Operator):
    """Switch the target area to the stored preset type"""
    bl_idname = "mbqh.switch_to_preset"
    bl_label = "Switch Area Preset"
    bl_description = "Switch the window to this preset type"
    bl_options = {'REGISTER', 'UNDO'}

    target_area_id: bpy.props.StringProperty()
    preset_index: bpy.props.IntProperty(min=1, max=3)

    def execute(self, context):
        screen = context.screen
        target_settings = None
        
        # Find settings by ID
        for item in screen.mbqh_area_cache:
            if item.id == self.target_area_id:
                target_settings = item
                break
        
        if target_settings:
            # Find the actual area
            target_area = None
            # Try by pointer
            for area in get_areas(screen):
                if str(area.as_pointer()) == target_settings.area_pointer:
                    target_area = area
                    break
            
            # Fallback by coords
            if not target_area:
                for area in get_areas(screen):
                    if area.x == target_settings.x and area.y == target_settings.y:
                        target_area = area
                        # Update pointer
                        target_settings.area_pointer = str(area.as_pointer())
                        break
            
            if target_area:
                preset_key = f"preset_{self.preset_index}"
                new_type = getattr(target_settings, preset_key)
                if new_type != 'NONE':
                    target_area.ui_type = new_type
                    target_area.tag_redraw()
            
        return {'FINISHED'}

class MBQH_OT_select_area(bpy.types.Operator):
    bl_idname = "mbqh.select_area"
    bl_label = "Switch Area Type"
    bl_description = "Click to switch this area to the next preset type"
    
    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()
    area_id: bpy.props.StringProperty(options={'HIDDEN'})
    
    # For keymap support
    target_ui_type: bpy.props.StringProperty(options={'HIDDEN'})
    target_index: bpy.props.IntProperty(default=-1, options={'HIDDEN'})
    from_keymap: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    
    def execute(self, context):
        target_area = None
        settings = None
        
        # 1. Try finding by ID (Robust for Keymaps with from_keymap=True)
        if self.from_keymap and self.area_id:
            # We use area_id to find the intended target settings
            target_area, screen, settings = find_area_and_screen(context, settings_id=self.area_id)
            
            # Context Check for Keymap:
            # If we found an area, we must ensure it matches the area under the mouse
            if target_area and context.area:
                 if context.area != target_area:
                     # This keymap was intended for 'target_area', but we are hovering 'context.area'
                     # Mismatch -> Pass through to let other keymaps try
                     return {'PASS_THROUGH'}
                     
            # If target_area is None (e.g. window closed), we also Pass Through
            if not target_area:
                return {'PASS_THROUGH'}

        # 2. Legacy/Fallback Keymap Support (Type + Index)
        elif self.target_ui_type and self.target_index >= 0:
            screen = context.screen
            siblings = []
            for a in get_areas(screen):
                # Use effective type to find sibling
                t = get_effective_type(screen, a)
                if t == self.target_ui_type:
                    siblings.append(a)
            
            # Sort by -Y, X
            siblings.sort(key=lambda a: (-a.y, a.x))
            
            if self.target_index < len(siblings):
                candidate_area = siblings[self.target_index]
                
                # Context Check:
                if context.area:
                    if context.area != candidate_area:
                        return {'PASS_THROUGH'}
                
                target_area = candidate_area
                settings = get_area_settings(screen, target_area)
        
        # 3. UI Button Click (x/y or area_id without from_keymap)
        if not target_area:
            if self.area_id:
                target_area, screen, settings = find_area_and_screen(context, settings_id=self.area_id)
            elif self.x or self.y:
                 target_area, screen, settings = find_area_and_screen(context, x=self.x, y=self.y)
        
        if target_area and settings:
            # 2. Cycle through presets + original
            # Get current type - use ui_type for better compatibility (e.g. Geometry Nodes)
            current_type = target_area.ui_type
            
            # If original type is not set, set it now (first time switch)
            if not settings.original_type:
                settings.original_type = current_type
                
            orig = settings.original_type
            p1 = settings.preset_1
            p2 = settings.preset_2
            p3 = settings.preset_3
            
            # Determine next type: Original -> P1 -> P2 -> P3 -> Original
            
            # Filter valid presets (not NONE)
            valid_presets = []
            if p1 != 'NONE': valid_presets.append(p1)
            if p2 != 'NONE': valid_presets.append(p2)
            if p3 != 'NONE': valid_presets.append(p3)
            
            # Cycle order: [Original] + valid_presets
            cycle_list = [orig] + valid_presets
            
            # Find current index
            try:
                curr_idx = cycle_list.index(current_type)
            except ValueError:
                curr_idx = -1
            
            if curr_idx != -1:
                # Normal cycle: move to next type in the list
                next_idx = (curr_idx + 1) % len(cycle_list)
                new_type = cycle_list[next_idx]
            else:
                # current_type is NOT in cycle_list, meaning the user manually
                # changed this area to a type outside of our preset configuration.
                # We should treat the current type as the new starting point
                # rather than forcibly reverting to the old original_type.
                # Update original_type to reflect the user's manual choice.
                settings.original_type = current_type
                orig = current_type
                # Rebuild cycle list with updated origin
                cycle_list = [orig] + valid_presets
                # Start cycle from origin -> go to first valid preset (if any)
                next_idx = 1 if len(cycle_list) > 1 else 0
                new_type = cycle_list[next_idx]
            
            # Apply switch (only if there's actually something to switch to)
            # If no valid presets are set, cycle_list == [orig], so new_type == orig
            # and we avoid pointless switching.
            if new_type != current_type:
                target_area.ui_type = new_type
                target_area.tag_redraw()
            else:
                self.report({'INFO'}, f"Area is already {current_type}, no presets configured")

        return {'FINISHED'}

class MBQH_OT_set_area_type(bpy.types.Operator):
    """Switch the area to a specific type"""
    bl_idname = "mbqh.set_area_type"
    bl_label = "Set Area Type"
    bl_description = "Switch area to this type"
    
    type: bpy.props.StringProperty()
    
    def execute(self, context):
        area = context.area
        # Ensure we have settings and original type is tracked
        settings = get_area_settings(context.screen, area)
        
        # Save original type if not set
        if not settings.original_type:
            # Use current effective type
            settings.original_type = getattr(area, "ui_type", area.type)
            
        if self.type:
            if self.type == 'NONE':
                return {'CANCELLED'}
            try:
                area.ui_type = self.type
                area.tag_redraw()
            except Exception as e:
                self.report({'ERROR'}, f"Failed to switch to {self.type}: {e}")
                return {'CANCELLED'}
                
        return {'FINISHED'}

class MBQH_OT_assign_shortcut(bpy.types.Operator):
    """Assign a shortcut key to this area switch"""
    bl_idname = "mbqh.assign_shortcut"
    bl_label = "Assign Shortcut"
    bl_options = {'INTERNAL'}
    
    area_id: bpy.props.StringProperty()
    
    def invoke(self, context, event):
        wm = context.window_manager
        self.report({'INFO'}, "Press a key (Esc to cancel, Backspace/Delete to clear)")
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}
        
    def modal(self, context, event):
        if event.value == 'PRESS':
            if event.type == 'ESC':
                return {'CANCELLED'}
            
            settings = None
            # Find settings
            for win in context.window_manager.windows:
                screen = win.screen
                for item in screen.mbqh_area_cache:
                    if item.id == self.area_id:
                        settings = item
                        break
                if settings: break
            
            if not settings:
                return {'CANCELLED'}

            if event.type in {'BACK_SPACE', 'DEL'}:
                # Clear shortcut
                settings.shortcut_key = ""
                settings.shortcut_ctrl = False
                settings.shortcut_shift = False
                settings.shortcut_alt = False
                self.report({'INFO'}, "Shortcut cleared")
            elif event.type not in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT', 'OSKEY', 'UNKNOWN', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                # Set shortcut
                settings.shortcut_key = event.type
                settings.shortcut_ctrl = event.ctrl
                settings.shortcut_shift = event.shift
                settings.shortcut_alt = event.alt
                self.report({'INFO'}, f"Shortcut set to {event.type}")
            else:
                # Modifier only, ignore
                return {'RUNNING_MODAL'}
            
            # Trigger update (which saves config and updates keymaps)
            # We need to manually call update logic or just rely on property update?
            # Property update only fires when set via UI or python assignment?
            # Yes, assignment above triggers update_preset if properties have update=update_preset.
            # But wait, update_preset saves to JSON.
            # We also need to update keymaps. update_preset calls update_keymaps().
            # So we are good.
            
            return {'FINISHED'}
            
        return {'RUNNING_MODAL'}

def update_keymaps():
    """Rebuild keymaps based on current live area settings"""
    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        return
    
    kc = wm.keyconfigs.addon
    km_name = "Window" 
    km = kc.keymaps.get(km_name)
    if not km:
        km = kc.keymaps.new(name=km_name, space_type='EMPTY', region_type='WINDOW')
        
    # Clear existing shortcuts for our operator
    to_remove = []
    for kmi in km.keymap_items:
        if kmi.idname == "mbqh.select_area":
            to_remove.append(kmi)
            
    for kmi in to_remove:
        km.keymap_items.remove(kmi)
            
    # Add new shortcuts from LIVE areas
    # We iterate all windows/screens/areas to find active shortcuts
    
    # Track which shortcuts we've added to avoid duplicates if multiple areas share ID?
    # IDs are unique per area settings.
    
    for window in wm.windows:
        screen = window.screen
        if not screen: continue
        
        # We need to iterate areas and get their settings
        for area in get_areas(screen):
            settings = get_area_settings(screen, area)
            
            key = settings.shortcut_key
            if key:
                try:
                    kmi = km.keymap_items.new(
                        "mbqh.select_area", 
                        type=key, 
                        value='PRESS', 
                        ctrl=settings.shortcut_ctrl,
                        shift=settings.shortcut_shift,
                        alt=settings.shortcut_alt
                    )
                    # Use ID-based targeting
                    kmi.properties.area_id = settings.id
                    kmi.properties.from_keymap = True
                    
                    # Fallback properties (just in case, though ID takes precedence)
                    kmi.properties.target_ui_type = getattr(area, "ui_type", area.type)
                    kmi.properties.target_index = -1 # Index is dynamic, so we don't rely on it
                    
                except Exception as e:
                    print(f"MBQH: Failed to add keymap for {settings.id}: {e}")

class MBQH_Properties(bpy.types.PropertyGroup):
    page: bpy.props.EnumProperty(
        items=[
            ('LAYOUT', "布局", "显示窗口布局"),
            ('SETTINGS', "设置", "显示插件设置"),
        ],
        name="Page",
        default='LAYOUT'
    )

def draw_mbqh_ui(layout, context):
    scene = context.scene
    mbqh = scene.mbqh

    # Draw Tab Switcher
    row = layout.row(align=True)
    row.prop(mbqh, "page", expand=True)
    layout.separator()

    if mbqh.page == 'LAYOUT':
        draw_layout_view(layout, context)
    else:
        draw_settings_view(layout, context)

def get_area_name(screen, area, area_groups):
    """Get consistent name with numbering for an area"""
    type_key = get_effective_type(screen, area)
    
    display_name = type_key.replace('_', ' ').title()
    if type_key == 'ASSETS':
        display_name = "资产浏览器"
    elif type_key == 'FILES':
        display_name = "文件浏览器"
    elif type_key == 'GeometryNodeTree':
        display_name = "几何节点编辑器"
    elif type_key == 'ShaderNodeTree':
        display_name = "着色器编辑器"
    elif type_key == 'CompositorNodeTree':
        display_name = "合成器"
    elif type_key == 'TextureNodeTree':
        display_name = "纹理节点编辑器"
    elif type_key == 'VIEW_3D':
        display_name = "3D 视图"
    elif type_key == 'PROPERTIES':
        display_name = "属性"
    elif type_key == 'OUTLINER':
        display_name = "大纲视图"
    elif type_key == 'PREFERENCES':
        display_name = "偏好设置"
    elif type_key == 'INFO':
        display_name = "信息"
    elif type_key == 'CONSOLE':
        display_name = "Python控制台"
    elif type_key == 'TEXT_EDITOR':
        display_name = "文本编辑器"
    elif type_key == 'FCURVES':
        display_name = "曲线编辑器"
    elif type_key == 'DOPESHEET':
        display_name = "动画摄影表"
    elif type_key == 'UV':
        display_name = "UV编辑器"
    elif type_key == 'DRIVERS':
        display_name = "驱动器"
    elif type_key == 'NLA_EDITOR':
        display_name = "非线性动画"
    elif type_key == 'CLIP_EDITOR':
        display_name = "影片剪辑编辑器"
    elif type_key == 'SEQUENCE_EDITOR':
        display_name = "视频序列编辑器"
    elif type_key == 'IMAGE_EDITOR':
        display_name = "图像编辑器"
    elif type_key == 'NODE_EDITOR':
        display_name = "节点编辑器"
    elif type_key == 'SPREADSHEET':
        display_name = "电子表格"
        
    if type_key in area_groups:
        areas = area_groups[type_key]
        if len(areas) > 1:
            try:
                index = areas.index(area)
                display_name = f"{display_name} {index + 1}"
            except ValueError:
                pass
                
    return display_name

def get_area_icon(screen, area):
    type_key = get_effective_type(screen, area)
    for item in AREA_TYPE_ITEMS:
        if item[0] == type_key:
            return item[3]
    return 'WINDOW'

def draw_layout_view(layout, context):
    screen = context.screen
    
    if not get_areas(screen):
        layout.label(text="No areas found")
        return

    all_areas = list(get_areas(screen))
    min_x = min([a.x for a in all_areas])
    min_y = min([a.y for a in all_areas])
    max_x = max([a.x + a.width for a in all_areas])
    max_y = max([a.y + a.height for a in all_areas])
    
    area_groups = get_grouped_areas(screen)
    
    tree = get_area_node(all_areas, (min_x, min_y, max_x, max_y))
    
    main_col = layout.column(align=True)
    draw_node(main_col, tree, area_groups, screen)

def draw_settings_view(layout, context):
    screen = context.screen
    wm = context.window_manager
    
    # --- Helper for Row Drawing ---
    def draw_area_row(layout, screen, area):
        display_name = get_area_name(screen, area, area_groups)
        settings = get_area_settings(screen, area)
        
        row = layout.row(align=True)
        
        # 1. Area name (Left) - Display only
        row.label(text=display_name, icon=get_area_icon(screen, area))

        # 2. 3 Dropdowns (Middle)
        for i in range(1, 4):
            prop_name = f"preset_{i}"
            row.prop(settings, prop_name, text="", icon='DOWNARROW_HLT')
        
        # 3. Shortcut Button (Right) - KeyMapItem style
        target_type = get_effective_type(screen, area)
        
        siblings = []
        for a in get_areas(screen):
            t = get_effective_type(screen, a)
            if t == target_type:
                siblings.append(a)
        siblings.sort(key=lambda a: (-a.y, a.x))
        try:
            index = siblings.index(area)
        except ValueError:
            index = 0
        
        kmi = get_keymap_item(target_type, index, area_id=settings.id)
        if not kmi:
             kmi = ensure_keymap_item(target_type, index, area_id=settings.id)
        
        if kmi:
            sub = row.row(align=True)
            sub.prop(kmi, "type", text="", full_event=True)
            # Clear button (Always visible)
            op = sub.operator("mbqh.clear_shortcut", text="", icon='X')
            op.target_ui_type = target_type
            op.target_index = index
            op.area_id = settings.id
            
    AREAS_PER_WINDOW = 20
    
    current_window_index = 0
    for i, w in enumerate(wm.windows):
        if w == context.window:
            current_window_index = i
            break
            
    # 1. Main Window Areas (Current Context)
    col = layout.column(align=True)
    col.label(text=f"当前存在的窗口类型 (Current Window - Index {current_window_index}):")
    
    if not get_areas(screen):
        layout.label(text="No areas found")
    else:
        area_groups = get_grouped_areas(screen)
        sorted_types = sorted(area_groups.keys())
        
        for type_key in sorted_types:
            areas = area_groups[type_key]
            for area in areas:
                draw_area_row(col, screen, area)
                
    # 2. Independent Window Button
    layout.separator()
    row = layout.row(align=True)
    row.operator("mbqh.create_independent_window", text="独立窗口 (Independent Window)", icon='ADD')
    row.operator("mbqh.save_shortcuts", text="", icon='FILE_TICK') # Manual save shortcuts
    
    # 3. Independent Windows List
    other_windows = [w for w in wm.windows if w != context.window]
    
    if other_windows:
        layout.separator()
        layout.label(text="独立窗口 (Independent Windows):")
        
        for win in other_windows:
            win_screen = win.screen
            if not win_screen: continue
            
            win_idx = 0
            for i, w in enumerate(wm.windows):
                if w == win:
                    win_idx = i
                    break
            
            win_col = layout.column(align=True)
            win_col.label(text=f"Window {win_idx}")
            
            area_groups = get_grouped_areas(win_screen)
            sorted_types = sorted(area_groups.keys())
            
            w_all_sorted = []
            for k in sorted_types:
                w_all_sorted.extend(area_groups[k])
                
            for type_key in sorted_types:
                areas = area_groups[type_key]
                for area in areas:
                    try:
                        draw_area_row(win_col, win_screen, area)
                    except ValueError:
                        pass

def draw_node(layout, node, area_groups, screen):
    if not node:
        return

    scale_factor = 0.015 

    if node['type'] == 'LEAF':
        area = node['area']
        settings = get_area_settings(screen, area)
        
        col = layout.column(align=True)
        col.scale_y = max(0.1, area.height * scale_factor)
        
        display_name = get_area_name(screen, area, area_groups)
            
        op = col.operator("mbqh.select_area", text=display_name)
        op.x = area.x
        op.y = area.y
        op.area_id = settings.id
        
    elif node['type'] == 'LEAF_LIST':
        col = layout.column(align=True)
        for area in node['areas']:
            settings = get_area_settings(screen, area)
            sub = col.column(align=True)
            sub.scale_y = max(0.1, area.height * scale_factor)
            
            display_name = get_area_name(screen, area, area_groups)

            op = sub.operator("mbqh.select_area", text=display_name)
            op.x = area.x
            op.y = area.y
            op.area_id = settings.id

    elif node['type'] == 'H_SPLIT':
        split = layout.split(factor=node['factor'], align=True)
        draw_node(split.column(align=True), node['left'], area_groups, screen)
        draw_node(split.column(align=True), node['right'], area_groups, screen)
        
    elif node['type'] == 'V_SPLIT':
        col = layout.column(align=True)
        draw_node(col, node['top'], area_groups, screen)
        draw_node(col, node['bottom'], area_groups, screen)

def draw_header_presets(self, context):
    layout = self.layout
    area = context.area
    screen = context.screen
    
    if not screen or not area:
        return
        
    # 排除状态栏和顶部菜单栏的预设按钮绘制
    if area.type in {'STATUSBAR', 'TOPBAR'}:
        return

    settings = get_area_settings(screen, area)
    
    row = layout.row(align=True)
    
    # Current type
    current_type = getattr(area, "ui_type", area.type)
    
    # Button 1: Original
    orig_type = settings.original_type if settings.original_type else current_type
    is_orig = (current_type == orig_type)
    
    # Use standard icon if type not found
    icon_orig = get_type_icon(orig_type)
    op = row.operator("mbqh.set_area_type", text="", icon=icon_orig, depress=is_orig)
    op.type = orig_type
    
    # Button 2-4: Presets
    for i in range(1, 4):
        preset_type = getattr(settings, f"preset_{i}")
        if preset_type == 'NONE':
            continue
            
        is_active = (current_type == preset_type)
        
        # Avoid showing duplicate active state if multiple buttons point to same type?
        # It's fine.
        
        icon = get_type_icon(preset_type)
        op = row.operator("mbqh.set_area_type", text="", icon=icon, depress=is_active)
        op.type = preset_type

classes = (
    MBQH_AreaSettings,
    MBQH_OT_CreateIndependentWindow,
    MBQH_OT_SaveWindowLayout,
    MBQH_OT_RestoreWindowLayout,
    MBQH_OT_switch_to_preset,
    MBQH_OT_select_area,
    MBQH_OT_set_area_type,
    MBQH_OT_save_shortcuts,
    MBQH_OT_clear_shortcut,
    MBQH_Properties,
)

def register():
    setup_dpi_awareness()
    load_config()
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Scene.mbqh = bpy.props.PointerProperty(type=MBQH_Properties)
    bpy.types.Screen.mbqh_area_cache = bpy.props.CollectionProperty(type=MBQH_AreaSettings)

    # Register keymaps
    update_keymaps()
    
    # Register header draw
    # Iterate all classes ending with _HT_header
    for cls_name in dir(bpy.types):
        if cls_name.endswith('_HT_header'):
            cls = getattr(bpy.types, cls_name)
            # Prepend to draw function to show on the left
            # We check if it's already there to avoid duplicates on reload
            # (Though unregister handles removal)
            cls.prepend(draw_header_presets)
    
    # Try to prevent white flash globally by setting class background to black on registration
    try:
        hwnd = ctypes.windll.user32.GetActiveWindow()
        if hwnd:
            prevent_white_flash(hwnd)
    except:
        pass



    # --- Load Handler ---
    # Register persistent handler to restore windows on file load
    if restore_window_layout not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(restore_window_layout)
    
    # Also need to handle it via a persistent handler because user prefs might be loaded after addon
    if disable_splash_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(disable_splash_handler)
        
    # Register handler to update keymaps after load
    if load_keymaps_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_keymaps_handler)

def validate_preset_value(val):
    """Ensure the preset value is a valid enum item"""
    # Check if val is a valid item in AREA_TYPE_ITEMS
    valid_keys = [item[0] for item in AREA_TYPE_ITEMS]
    if val in valid_keys:
        return val
    
    # Handle legacy/incorrect mapping
    if val == 'DOPESHEET_EDITOR':
        return 'DOPESHEET'
    
    # Handle GRAPH_EDITOR mismatch
    if val == 'GRAPH_EDITOR':
        return 'FCURVES'
    
    # Handle FILE_BROWSER mismatch
    if val == 'FILE_BROWSER':
        return 'FILES'
    
    # Try to fuzzy match if suffix missing
    if val and val + '_EDITOR' in valid_keys:
        return val + '_EDITOR'
        
    return 'NONE' # Fallback to NONE instead of default to avoid errors

def restore_presets_from_cache():
    """Force restore all area presets from CACHED_PRESETS"""
    # This runs on load to ensure JSON settings override .blend file settings
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen: continue
        
        for area in get_areas(screen):
            # Get settings (will create if needed)
            settings = get_area_settings(screen, area)
            
            target_type = getattr(area, "ui_type", area.type)
            
            # Find index
            siblings = []
            for a in get_areas(screen):
                t = getattr(a, "ui_type", a.type)
                if t == target_type:
                    siblings.append(a)
            siblings.sort(key=lambda a: (-a.y, a.x))
            
            try:
                index = siblings.index(area)
            except ValueError:
                index = 0
            
            # Lookup and Apply
            if target_type in CACHED_PRESETS:
                idx_str = str(index)
                if idx_str in CACHED_PRESETS[target_type]:
                    data = CACHED_PRESETS[target_type][idx_str]
                    
                    # Force Overwrite
                    # We use a try-except block to handle potential invalid enum values in cache
                    try:
                        p1 = data.get('preset_1', settings.preset_1)
                        p1 = validate_preset_value(p1)
                        if p1 != settings.preset_1: settings.preset_1 = p1
                        
                        p2 = data.get('preset_2', settings.preset_2)
                        p2 = validate_preset_value(p2)
                        if p2 != settings.preset_2: settings.preset_2 = p2
                        
                        p3 = data.get('preset_3', settings.preset_3)
                        p3 = validate_preset_value(p3)
                        if p3 != settings.preset_3: settings.preset_3 = p3
                        
                        # Restore shortcuts too?
                        key = data.get('shortcut_key')
                        if key is not None: settings.shortcut_key = key
                        
                        ctrl = data.get('shortcut_ctrl')
                        if ctrl is not None: settings.shortcut_ctrl = ctrl
                        
                        shift = data.get('shortcut_shift')
                        if shift is not None: settings.shortcut_shift = shift
                        
                        alt = data.get('shortcut_alt')
                        if alt is not None: settings.shortcut_alt = alt
                        
                    except Exception as e:
                        print(f"MBQH: Failed to restore preset for {target_type}: {e}")
                    
                    settings.is_initialized = True

@persistent
def load_keymaps_handler(dummy):
    """Ensure keymaps are loaded after Blender startup/file load"""
    # Small delay or just execute? Usually load_post is fine.
    # But sometimes user prefs overwrite addon keymaps?
    # Actually, addon keymaps should persist if registered.
    # But let's reload from config to be sure.
    load_config()
    restore_presets_from_cache() # Restore presets to UI
    update_keymaps() # Restore shortcuts to Keymap
    
    # Also disable splash here just in case
    if hasattr(bpy.context.preferences.view, "show_splash"):
         if bpy.context.preferences.view.show_splash:
            bpy.context.preferences.view.show_splash = False

@persistent
def disable_splash_handler(dummy):
    if hasattr(bpy.context.preferences.view, "show_splash"):
         if bpy.context.preferences.view.show_splash:
            bpy.context.preferences.view.show_splash = False

def unregister():
    # Remove header draw
    for cls_name in dir(bpy.types):
        if cls_name.endswith('_HT_header'):
            cls = getattr(bpy.types, cls_name)
            try:
                cls.remove(draw_header_presets)
            except ValueError:
                pass

    # Clean up keymaps
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.get("Window")
        if km:
            to_remove = []
            for kmi in km.keymap_items:
                if kmi.idname == "mbqh.select_area":
                    to_remove.append(kmi)
            for kmi in to_remove:
                km.keymap_items.remove(kmi)

    # Remove handlers
    if restore_window_layout in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(restore_window_layout)
        
    if disable_splash_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(disable_splash_handler)
        
    if load_keymaps_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_keymaps_handler)
    

        
    del bpy.types.Scene.mbqh
    del bpy.types.Screen.mbqh_area_cache
    for cls in classes:
        bpy.utils.unregister_class(cls)
        


if __name__ == "__main__":
    register()
