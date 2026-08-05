bl_info = {
    "name": "USE全局翻译",
    "author": "布的[微信bude6688],Shuimeng,666",
    "version": (2, 0, 7),
    "blender": (3, 0, 0),
    "location": "偏好设置 > Add-ons",
    "description": "一键式全局翻译,心无旁骛,你只管专心的创作!",
}

import bpy, os, shutil, blf, re, ftplib, lzma, importlib, sys, threading, subprocess, struct, gettext, configparser
from bpy.types import Operator, AddonPreferences
from bpy_extras.io_utils import ImportHelper
from functools import lru_cache
from collections import defaultdict
from datetime import datetime
from bpy.app.handlers import persistent

up_ok = False; z_file = ""; z_time = None; who_mo = None; mo_date = None; down_jd = 0; down_msg = ""; down_ac = False; down_err = False
zh = 'zh_CN' if bpy.app.version < (4, 0, 0) else 'zh_HANS'
mo_path = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', zh, 'LC_MESSAGES', 'blender.mo')
lo9 = os.path.join(os.path.dirname(__file__), "update.ini")

def re_bl():
    subprocess.Popen(bpy.app.binary_path)
    bpy.ops.wm.quit_blender()

def connect_ftp():
    a, b, c = bytes.fromhex("3137352e3137382e34322e3231387c3137355f3137385f34325f3231387c64733761355033385777417733506b73").decode().split('|')
    ftp = ftplib.FTP()
    ftp.connect(a, 21, timeout=15); ftp.login(user=b, passwd=c)
    return ftp

def get_xz_info(ftp):
    try:
        xz8 = su8 = xz7 = su7 = None
        for f in [f for f in ftp.nlst() if f.endswith(".xz")]:
            name_ext = f[:-3]
            if name_ext.isdigit() and len(name_ext) in [7,8]:
                if len(name_ext)==8 and not xz8: xz8, su8 = f, int(name_ext)
                elif len(name_ext)==7 and not xz7: xz7, su7 = f, int(name_ext)
        return xz8, su8, xz7, su7
    except Exception: return None, None, None, None

def read_log(lo9):
    config = configparser.ConfigParser()
    config['Ver'] = {'main_8': '0', 'pack_7': '0'}
    if os.path.exists(lo9):
        try: config.read(lo9, encoding='utf-8')
        except: pass
    return config.getint('Ver', 'main_8', fallback=0), config.getint('Ver', 'pack_7', fallback=0)

def write_log(value, lo9):
    config = configparser.ConfigParser()
    if os.path.exists(lo9):
        try: config.read(lo9, encoding='utf-8')
        except: pass
    config['Ver'] = {'main_8': str(value) if len(str(value)) == 8 else config.get('Ver', 'main_8', fallback='0'),
                    'pack_7': str(value) if len(str(value)) != 8 else config.get('Ver', 'pack_7', fallback='0')}
    try:
        with open(lo9, 'w', encoding='utf-8') as f:
            config.write(f)
        return True
    except:
        return False

def d_file_with_progress(ftp, filename, target_path, operator_instance):
    global down_jd, down_msg
    total_size = ftp.size(filename)
    downloaded = 0
    chunk_size = 1024 * 16
    def callback(data):
        nonlocal downloaded
        downloaded += len(data)
        f.write(data)
        if total_size > 0:
            progress = min(99, int((downloaded / total_size) * 100))
            operator_instance.progress = progress
            operator_instance.message = f"下载中... {progress}%"
    with open(target_path, "wb") as f:
        ftp.retrbinary(f"RETR {filename}", callback, blocksize=chunk_size)
    return target_path

def check_mo(mo_path):
    global who_mo, mo_date
    try:
        with open(mo_path, 'rb') as f:
            magic_bytes = f.read(4)
            if len(magic_bytes) < 4 or struct.unpack('<I', magic_bytes)[0] != 0x950412de:
                return
            f.seek(4)
            version, nstrings, orig_tab_off, trans_tab_off = struct.unpack('<IIII', f.read(16))
            f.seek(trans_tab_off)
            msg_len, msg_off = struct.unpack('<II', f.read(8))
            f.seek(msg_off)
            data = f.read(msg_len)
            msgstr = data.decode('utf-8')
            date_str = None
            for line in msgstr.splitlines():
                if ':' in line and not line.startswith('"'):
                    if 'last-translator' in line.lower():
                        who_mo = line.split(':', 1)[1].strip()
                    elif 'po-revision-date' in line.lower():
                        date_str = line.split(':', 1)[1].strip()
            if date_str:
                mo_date = int(date_str[:10].replace('-', ''))
    except Exception:
        pass

def c_updates():
    global up_ok, z_file, z_time
    view = bpy.context.preferences.view
    try:
        if bpy.app.translations.locale != zh:
            view.language = zh
            [bpy.ops.ui.toggle_cn() for _ in range(2)]
    except: pass
    if not view.use_translate_interface:
        view.use_translate_interface = True
    if any("Layout" in ws.name for ws in bpy.data.workspaces):
        [bpy.ops.ui.toggle_cn() for _ in range(2)]
    try:
        ftp = connect_ftp()
        xz8, su8, xz7, su7 = get_xz_info(ftp)
        ftp.quit()
        if not xz8 and not xz7:
            return
        main_8, pack_7 = read_log(lo9)
        if main_8 == 0 and pack_7 == 0 and who_mo == 'bude':
            write_log(mo_date, lo9)
            if xz8 and su8 > mo_date:
                if su8 > mo_date:
                    up_ok, z_file, z_time = True, xz8, su8
        else:
            if xz8 and su8 and (main_8 == 0 or su8 > main_8):
                up_ok, z_file, z_time = True, xz8, su8
            elif not up_ok and xz7 and su7 and (pack_7 == 0 or su7 > pack_7):
                up_ok, z_file, z_time = True, xz7, su7
    except Exception:
        pass

workspace_name_map = {
    "Animation": "动画",
    "Compositing": "合成",
    "Geometry Nodes": "几何节点",
    "Layout": "布局",
    "Modeling": "建模",
    "Rendering": "渲染",
    "Scripting": "脚本",
    "Sculpting": "雕刻",
    "Shading": "着色",
    "Texture Paint": "纹理绘制",
    "UV Editing": "UV编辑"
}
reverse_workspace_map = {v: k for k, v in workspace_name_map.items()}

class OT_toggle_cn(Operator):
    bl_idname = "ui.toggle_cn"
    bl_label = "中英切换"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "点击切换中英文，按住ALT点击可进行更新,但建议在首选项更新,因为可以看更新进度!"

    def invoke(self, context, event):
        global up_ok
        if event.alt:
            msg, op = ("开始更新语言包...", 'INVOKE_DEFAULT') if up_ok else ("当前没有可用更新", None)
            if op: bpy.ops.ftp.u_a(op)
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        return self.execute(context)
    def execute(self, context):
        prefs = context.preferences
        current = prefs.view.use_translate_interface
        prefs.view.use_translate_interface = not current
        name_map = reverse_workspace_map if current else workspace_name_map
        for workspace in bpy.data.workspaces:
            for old_name, new_name in name_map.items():
                if old_name in workspace.name:
                    workspace.name = workspace.name.replace(old_name, new_name)
                    break
        [area.tag_redraw() for window in context.window_manager.windows for area in window.screen.areas]
        return {'FINISHED'}

def draw_language_menu(self, context):
    layout = self.layout
    prefs = context.preferences
    c_e = prefs.view.use_translate_interface
    z_str = str(z_time)
    xi = up_ok and len(z_str) == 7
    big = up_ok and len(z_str) == 8
    split = layout.split(factor=0.0001)
    split.column()
    col = split.column(align=True)
    col.scale_x, col.scale_y = 0.82, 0.85
    col.separator(factor=0.5)
    col.alert = big
    if c_e:
        col.operator("ui.toggle_cn", text="F5切英文", depress=xi)
    else:
        col.operator("ui.toggle_cn", text="F5切中文", depress=xi)

def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return []
    km = kc.keymaps.new(name="Window", space_type='EMPTY')
    kmi = km.keymap_items.new("ui.toggle_cn", type='F5', value='PRESS')
    return [(km, kmi)]
language_keymap_items = []

def draw_use_ui(layout, context):
    if down_ac:
        box = layout.box()
        row = box.row()
        row.alert = down_err
        row.label(text=down_msg, icon='ERROR' if down_err else 'INFO')
        if not down_err:
            row = box.row()
            if bpy.app.version >= (4, 0, 0):
                row.progress(
                    factor=down_jd / 100.0,
                    type='BAR',
                    text=f"{down_jd}%"
                )
            else:
                progress_bar = "█" * int(down_jd / 2) + "░" * (50 - int(down_jd / 2))
                row.label(text=f"[{progress_bar}] {down_jd}%")
    box = layout.box()
    box.label(text="联网更新翻译")
    main_8, pack_7 = read_log(lo9)
    ale = False
    z_str = str(z_time)
    if len(z_str) == 8:
        vers = f"发现语言包更新:{z_str[0:4]}年{z_str[4:6]}月{z_str[6:8]}日"
    else:
        vers = f"发现补丁包更新:{z_str}"
    msg_1 = f" {vers} 版,快更新到最新版吧,如有错漏记得反馈哦!"
    m_str = str(main_8)
    if pack_7 == 0:
        p_str = "无补丁包!"
    else:
        p_str = str(pack_7)
    msg_0 = ""
    if main_8 != 0:
        if who_mo == 'bude':
            msg_0 = f"当前语言包版为: {m_str[0:4]}年{m_str[4:6]}月{m_str[6:8]}日版,翻译补丁包版本为: {p_str}"
        else:
            msg_0 = "当前语言包损坏,或使用的非(布的)翻译包,可能使用了其它插件的翻译包!"
            ale = True
    else:
        if who_mo != 'bude':
            msg_0 = "当前语言包未下载,翻译未生效,需更新语言包后生效!"
    admin_text = '管理员' if ((os.getuid() == 0) if sys.platform != "win32" else bool(__import__('ctypes').windll.shell32.IsUserAnAdmin())) else '普通用户'
    system = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, sys.platform)
    def get_install_info():
        path = bpy.app.binary_path
        path_lower = path.lower()
        if "windowsapps" in path_lower:
            return "微软商店特殊权限"
        elif "steam" in path_lower:
            if "program files" in path_lower:
                return "Steam需要权限"
            return "Steam无需权限"
        elif "program files" in path_lower:
            return "受限目录需要权限"
        else:
            return "普通安装无需权限"
    install_info = get_install_info()
    mo_dir = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', zh, 'LC_MESSAGES')
    tip_row = box.row()
    tip_row.label(text=f"诊断信息: {system}{admin_text},{bpy.app.version_string}{install_info}, {'有' if os.path.isdir(mo_dir) else '无'}目录, {'有' if os.path.exists(mo_path) else '无'}文件", icon='BLENDER')
    alert_row = box.row()
    alert_row.alert = ale
    alert_row.label(text=msg_0, icon='ERROR')
    if up_ok and not down_ac:
        alert_row = box.row()
        alert_row.alert = True
        alert_row.label(text=msg_1, icon='ERROR')
        main_row = box.row()
        if len(z_str) == 8:
            main_row.alert = True
        split = main_row.split(factor=0.2)
        left_col = split.column()
        if len(z_str) == 8:
            left_col.operator("ftp.u_a", text="立即更新语言包")
        if len(z_str) == 7:
            left_col.operator("ftp.u_a", text="立即更新补丁包", depress=True)
        right_col = split.column()
        right_col.label(text="更新受网络因素影响,如多次更新失败请使用手动导入方式!")
    elif not down_ac:
        main_row = box.row()
        split = main_row.split(factor=0.2)
        left_col = split.column()
        left_col.operator("ftp.f_c", text="检查语言包更新", depress=False)
        right_col = split.column()
        right_col.label(text="点击变红再点一次进行更新,没变化说明没有更新,不需要猛点!!")
    main_row = box.row()
    split = main_row.split(factor=0.2)
    left_col = split.column()
    left_col.operator("mo.in_m", text="手动导入字典")
    right_col = split.column()
    right_col.label(text="手动导入自行下载的语言包进行更新")
    main_row = box.row()
    split = main_row.split(factor=0.2)
    left_col = split.column()
    left_col.operator("wm.re_translation", text="恢复官方翻译")
    right_col = split.column()
    right_col.label(text="删除全局翻译语言包,恢复官方翻译")
    if bpy.app.version >= (4, 2, 3):
        box = layout.box()
        box.label(text="插件列表翻译")
        row = box.row()
        main_row = box.row()
        split = main_row.split(factor=0.2)
        left_col = split.column()
        left_col.operator("wm.t_all", text="完整翻译列表")
        right_col = split.column()
        right_col.label(text="翻译在插件和扩展列表里的名称的描述")
        main_row = box.row()
        split = main_row.split(factor=0.2)
        left_col = split.column()
        left_col.operator("wm.r_all", text="恢复官方列表")
        right_col = split.column()
        right_col.label(text="恢复插件和扩展列表的翻译,使用官方原版")
    if bpy.app.version >= (4, 4):
        box = layout.box()
        box.label(text="雕刻笔刷翻译")
        row = box.row()
        main_row = box.row()
        split = main_row.split(factor=0.2)
        left_col = split.column()
        left_col.operator("wm.t_bis", text="翻译雕刻笔刷")
        right_col = split.column()
        right_col.label(text="翻译雕刻笔刷,会立即重启,注意如有文件请保存")
        main_row = box.row()
        split = main_row.split(factor=0.2)
        left_col = split.column()
        left_col.operator("wm.r_bis", text="恢复雕刻笔刷")
        right_col = split.column()
        right_col.label(text="恢复雕刻笔刷,会立即重启,注意如有文件请保存")
    box = layout.box()
    row = box.row()
    main_row = box.row()
    split = main_row.split(factor=0.2)
    left_col = split.column()
    left_col.operator("wm.url_open", text="问题与技巧", depress=True).url = "https://www.bilibili.com/video/BV1JaaZzbEpc"
    right_col = split.column()
    right_col.label(text="QQ群: 386107819")

class Mo_m_in(Operator, ImportHelper):
    """选择你下载回来的XZ文件进行导入"""
    bl_idname = "mo.in_m"
    bl_label = "导入xz语言包"
    bl_options = {'INTERNAL'}
    filename_ext = ".xz"

    filter_glob: bpy.props.StringProperty(default="*.xz", options={'HIDDEN'})
    def execute(self, context):
        try:
            xz_path = self.filepath
            if not xz_path.endswith('.xz'):
                self.report({'ERROR'}, "请选择有效的.xz文件")
                return {'CANCELLED'}
            filename = os.path.basename(xz_path)
            name_ext = filename[:-3]
            if not name_ext.isdigit() or len(name_ext) != 8:
                self.report({'ERROR'}, "文件名格式\n不正确\n，必须为\n8位数字")
                return {'CANCELLED'}
            ver_num = int(name_ext)
            mo_dir = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', zh, 'LC_MESSAGES')
            os.makedirs(mo_dir, exist_ok=True)
            mo_p = os.path.join(mo_dir, 'blender.mo')
            try:
                with lzma.open(xz_path, 'rb') as f:
                    with open(mo_p, 'wb') as target:
                        shutil.copyfileobj(f, target)
            except Exception as e:
                self.report({'ERROR'}, f"解压失败: {str(e)}")
                return {'CANCELLED'}
            write_log(ver_num, lo9)
            mulu = os.path.dirname(__file__)
            tang = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', 'languages')
            lang = os.path.join(mulu, 'data', zh, 'languages')
            if not os.path.exists(tang):
                shutil.copy2(lang, tang)
            self.report({'INFO'}, f"本地语言包导入成功! 版本: {ver_num}")
            bpy.app.timers.register(re_bl, first_interval=0.5)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"导入失败: {str(e)}")
            return {'CANCELLED'}

class Re_translation(Operator):
    bl_idname = "wm.re_translation"
    bl_label = "官方翻译"

    def execute(self, context):
        try:
            uu = bpy.utils.user_resource('DATAFILES', path='locale')
            mu2 = os.path.join(os.path.dirname(__file__), 'patch.mo')
            if os.path.exists(uu):
                shutil.rmtree(uu)
            if os.path.exists(mu2):
                os.remove(mu2)
            if os.path.exists(lo9):
                os.remove(lo9)
            self.report({'INFO'}, "官方翻译已恢复,重启blender后生效!")
            bpy.app.timers.register(re_bl, first_interval=0.5)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f" 恢复官方翻译失败,请尝试以管理员运行blender - {str(e)}")
            return {'CANCELLED'}

class Brush_Op:
    @classmethod
    def poll(cls, context):
        return sys.platform in ["win32", "darwin", "linux"]
    def clean_cache(self):
        try:
            if path := (
                (sys.platform == "win32" and os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Blender Foundation', 'Blender', 'Cache')) or
                (sys.platform == "darwin" and os.path.join(os.path.expanduser("~"), 'Library', 'Caches', 'Blender')) or
                (sys.platform.startswith("linux") and os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.join(os.path.expanduser("~"), '.cache')), 'blender'))
            ):
                os.path.exists(path) and shutil.rmtree(path)
        except:
            pass
    def check_admin(self):
        if sys.platform == "win32":
            if bpy.app.binary_path and "Program Files" in bpy.app.binary_path:
                return True
        else:
            return os.getuid() == 0
        return False
    def get_dir(self):
        return os.path.join(bpy.utils.resource_path('LOCAL'), 'datafiles', 'assets', 'brushes')

class T_all(Brush_Op, Operator):
    bl_idname = "wm.t_all"
    bl_label = "插件列表"

    def execute(self, context):
        try:
            core = os.path.join(bpy.utils.resource_path('LOCAL'), 'scripts', 'addons_core', 'bl_pkg')
            all_file = os.path.join(os.path.dirname(__file__), 'data', '1', 'bl_extension_ui.py')
            p_y = os.path.join(core, 'bl_extension_ui.py')
            shutil.copy2(all_file, p_y)
            shutil.rmtree(os.path.join(core, '__pycache__'), ignore_errors=True)
            self.report({'INFO'}, "插件列表已翻译为中文，将自动重启!")
            bpy.app.timers.register(re_bl, first_interval=0.5)
            return {'FINISHED'}
        except PermissionError:
            msg = "需要管理员/root权限" if self.check_admin() else "权限不足"
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"插件列表翻译失败: {str(e)}")
            return {'CANCELLED'}

class R_all(Brush_Op, Operator):
    bl_idname = "wm.r_all"
    bl_label = "还原官方"

    def execute(self, context):
        try:
            core = os.path.join(bpy.utils.resource_path('LOCAL'), 'scripts', 'addons_core', 'bl_pkg')
            noo = os.path.join(os.path.dirname(__file__), 'data', '2', 'bl_extension_ui.py')
            p_y = os.path.join(core, 'bl_extension_ui.py')
            shutil.copy2(noo, p_y)
            shutil.rmtree(os.path.join(core, '__pycache__'), ignore_errors=True)
            if "bl_pkg" in sys.modules:
                importlib.reload(sys.modules["bl_pkg"])
            self.report({'INFO'}, "插件列表已恢复原始状态!")
            return {'FINISHED'}
        except PermissionError:
            msg = "需要管理员/root权限" if self.check_admin() else "权限不足"
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"插件列表恢复失败: {str(e)}")
            return {'CANCELLED'}

class T_bishua(Brush_Op, Operator):
    bl_idname = "wm.t_bis"
    bl_label = "雕刻笔刷"

    def execute(self, context):
        try:
            src_dir = os.path.join(os.path.dirname(__file__), 'data', '1', 'brushes')
            dst_dir = self.get_dir()
            if os.path.exists(dst_dir):
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            self.clean_cache()
            self.report({'INFO'}, "雕刻笔刷已翻译，将重启Blender!")
            bpy.app.timers.register(re_bl, first_interval=0.5)
            return {'FINISHED'}
        except PermissionError:
            msg = "需要管理员/root权限" if self.check_admin() else "权限不足"
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"失败: {str(e)}")
            return {'CANCELLED'}

class R_bishua(Brush_Op, Operator):
    bl_idname = "wm.r_bis"
    bl_label = "还原笔刷"
    
    def execute(self, context):
        try:
            src_dir = os.path.join(os.path.dirname(__file__), 'data', '2', 'brushes')
            dst_dir = self.get_dir()
            if os.path.exists(dst_dir):
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            self.clean_cache()
            self.report({'INFO'}, "雕刻笔刷已恢复，将重启Blender!")
            bpy.app.timers.register(re_bl, first_interval=0.5)
            return {'FINISHED'}
        except PermissionError:
            msg = "需要管理员/root权限" if self.check_admin() else "权限不足"
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"恢复失败: {str(e)}")
            return {'CANCELLED'}

class FTP_Update(Operator):
    bl_idname = "ftp.u_a"
    bl_label = "下载并应用更新"

    progress = bpy.props.IntProperty(default=0)
    message = bpy.props.StringProperty(default="")
    _timer = None
    def execute(self, context):
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        thread = threading.Thread(target=self.download_worker, daemon=True)
        thread.start()
        return {'RUNNING_MODAL'}
    def modal(self, context, event):
        if event.type == 'TIMER':
            global down_ac, down_jd, down_msg, down_err
            down_ac = True
            down_jd = self.progress
            down_msg = self.message
            down_err = False
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'PREFERENCES':
                        area.tag_redraw()
            if self.progress >= 100 or "完成" in str(self.message) or "错误" in str(self.message):
                context.window_manager.event_timer_remove(self._timer)
                down_ac = False
                if "完成" in self.message:
                    self.report({'INFO'}, "语言包更新完成,将自动重启blender!")
                    bpy.app.timers.register(re_bl, first_interval=1.0)
                return {'FINISHED'}
        return {'PASS_THROUGH'}
    def download_worker(self):
        global up_ok, z_file, z_time
        try:
            self.progress = 0
            ftp = connect_ftp()
            if not z_file:
                self.message = "错误：未找到更新文件信息,也许网络原因,请重试!"
                return
            mulu = os.path.dirname(__file__)
            temp = os.path.join(mulu, "temp")
            tang = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', 'languages')
            lang = os.path.join(mulu, 'data', zh, 'languages')
            mu2 = os.path.join(os.path.dirname(__file__), 'patch.mo')
            os.makedirs(temp, exist_ok=True)
            xz_path = os.path.join(temp, z_file)
            self.message = "开始下载..."
            d_file_with_progress(ftp, z_file, xz_path, self)
            self.message = "解压文件中..."
            z_len = len(str(z_time))
            if z_len == 8:
                mo_dir = os.path.join(bpy.utils.user_resource('DATAFILES'), 'locale', zh, 'LC_MESSAGES')
                os.makedirs(mo_dir, exist_ok=True)
                mo_p = os.path.join(mo_dir, 'blender.mo')
            else:
                mo_p = mu2
            with lzma.open(xz_path, 'rb') as f:
                with open(mo_p, 'wb') as target:
                    shutil.copyfileobj(f, target)
            write_log(z_time, lo9)
            if os.path.exists(temp):
                shutil.rmtree(temp)
            if z_len == 8:
                if not os.path.exists(tang):
                    shutil.copy2(lang, tang)
                if os.path.exists(mu2):
                    os.remove(mu2)
            self.message = "更新完成!"
            self.progress = 100
            up_ok = False
        except Exception as e:
            self.message = f"更新失败,请尝试以管理员运行blender: {str(e)}"
        finally:
            try:
                ftp.quit()
            except:
                pass

class FTP_check(Operator):
    bl_idname = "ftp.f_c"
    bl_label = "手动检查更新"
    def execute(self, context):
        c_updates()
        return {'FINISHED'}

class smart_blf:
    nd_r1 = re.compile(r"^([^:]+?)(\s*\[[A-Za-z0-9]+\])?:\s*(.+)$")
    ops_r2 = re.compile(r"^(\W*)(.+?)(\W*)$")
    fh_r3 = re.compile(r"^(.+?)\s+(\(.+?\))$")
    lw_r4 = re.compile(r"^([a-zA-Z][a-zA-Z\s]*)\s+([^a-zA-Z\s].*|.*\d.*)$")

    def __init__(self):
        self._original_blf_draw = None
        self._active = False
        self._processors = (self._p_s_t, self._p_l_v, self._p_d_w, self._p_s_w, self._p_l_w, self._p_f_f)
    def _p_s_t(self, text): return self._pgettext(text)
    def _p_l_v(self, text):
        match = self.nd_r1.match(text)
        return f"{self._pgettext(match.group(1).strip())}{match.group(2) or ''}: {self._pgettext(match.group(3).strip())}" if match else text
    def _p_d_w(self, text):
        match = self.fh_r3.match(text)
        return f"{self._pgettext(match.group(1))} {self._pgettext(match.group(2))}" if match else text
    def _p_l_w(self, text):
        match = self.lw_r4.match(text)
        return f"{self._pgettext(match.group(1).strip())} {match.group(2)}" if match else text
    def _p_s_w(self, text):
        match = self.ops_r2.match(text)
        return f"{match.group(1)}{self._pgettext(match.group(2))}{match.group(3)}" if match else text
    def _p_f_f(self, text): return self._pgettext(text)
    def _pgettext(self, text): return bpy.app.translations.pgettext(text)
    @lru_cache(maxsize=2048)
    def _pipeline_translate(self, text):
        if not text or not text.strip(): return text
        current_text = text
        for processor in self._processors:
            processed_text = processor(current_text)
            if processed_text != current_text: current_text = processed_text
        return current_text
    def _translated_draw(self, font_id, text, *args, **kwargs):
        prefs = bpy.context.preferences
        c_e = prefs.view.use_translate_interface
        return self._original_blf_draw(font_id, text if not c_e else (self._pipeline_translate(text) if text else text), *args, **kwargs)
    def register(self):
        if not self._active:
            self._original_blf_draw = blf.draw
            blf.draw = self._translated_draw
            self._active = True
    def unregister(self):
        if self._active and self._original_blf_draw:
            blf.draw = self._original_blf_draw
        self._active = False
        self._pipeline_translate.cache_clear()
smart_hud = smart_blf()

def load_patch():
    pmo = os.path.join(os.path.dirname(__file__), 'patch.mo')
    if os.path.exists(pmo):
        try:
            with open(pmo, 'rb') as mo_file:
                lang = gettext.GNUTranslations(mo_file)
            catalog = lang._catalog
            if "" in catalog:
                del catalog[""]
            d_dict = {}
            for msgid, msgstr in catalog.items():
                if not msgstr or isinstance(msgid, tuple):
                    continue
                d_dict.setdefault(zh, {})[('*', msgid)] = msgstr
                if len(msgid) < 64:
                    d_dict.setdefault(zh, {})[('Operator', msgid)] = msgstr
            return d_dict
        except Exception:
            return None
    else:
        return None
@persistent
def load_handler(dummy):
    bpy.app.timers.register(c_updates, first_interval=0.01, persistent=False)
classes = (Re_translation, T_all, R_all, T_bishua, R_bishua, FTP_Update, FTP_check, OT_toggle_cn, Mo_m_in)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    check_mo(mo_path)
    patch_dict = load_patch()
    if patch_dict:
        try:
            bpy.app.translations.register(__name__, patch_dict)
        except ValueError:
            pass
    smart_hud.register()
    bpy.types.TOPBAR_MT_editor_menus.append(draw_language_menu)
    global language_keymap_items
    language_keymap_items = register_keymap()
    bpy.app.handlers.load_post.append(load_handler)
    bpy.app.timers.register(c_updates, first_interval=0.01, persistent=False)

def unregister():
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
    global language_keymap_items
    for km, kmi in language_keymap_items:
        km.keymap_items.remove(kmi)
    language_keymap_items = []
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_language_menu)
    smart_hud.unregister()
    bpy.app.translations.unregister(__name__)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()