__all__ = (
    "display_errors",
    "register",
    "unregister",

    "ExtensionUI_Visibility",
)

import bpy

from bpy.types import (
    Menu,
    Panel,
)

from bl_ui.space_userpref import (
    USERPREF_PT_addons,
    USERPREF_PT_extensions,
    USERPREF_MT_extensions_active_repo,
)

USE_SHOW_ADDON_TYPE_AS_TEXT = True
USE_SHOW_ADDON_TYPE_AS_ICON = True

SECRET_ADDONS = {__package__}

USE_ADDON_IGNORE_EXTENSION_MANIFEST_HACK = True

def size_as_fmt_string(num: float, *, precision: int = 1) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"):
        if abs(num) < 1024.0:
            return "{:3.{:d}f}{:s}".format(num, precision, unit)
        num /= 1024.0
    unit = "YB"
    return "{:.{:d}f}{:s}".format(num, precision, unit)

def sizes_as_percentage_string(size_partial: int, size_final: int) -> str:
    if size_final == 0:
        percent = 0.0
    else:
        size_partial = min(size_partial, size_final)
        percent = size_partial / size_final

    return "{:-6.2f}%".format(percent * 100)

def pkg_repo_and_id_from_theme_path(repos_all, filepath):
    import os
    if not filepath:
        return None

    dirpath = os.path.dirname(filepath)
    repo_directory, pkg_id = os.path.split(dirpath)
    for repo_index, repo in enumerate(repos_all):
        if repo_directory != repo.directory:
            continue
        return repo_index, pkg_id
    return None

def pkg_repo_module_prefix(repo):
    return "bl_ext.{:s}.".format(repo.module)

def module_parent_dirname(module_filepath):
    import os
    parts = module_filepath.rsplit(os.sep, 3)
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        if len(parts) >= 3:
            return parts[-3]
    else:
        if len(parts) >= 2:
            return parts[-2]
    return ""

def domain_extract_from_url(url):
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    return domain

def pkg_manifest_zip_all_items(pkg_manifest_local, pkg_manifest_remote):
    if pkg_manifest_remote is None:
        if pkg_manifest_local is not None:
            for pkg_id, item_local in pkg_manifest_local.items():
                yield pkg_id, (item_local, None)
        return
    elif pkg_manifest_local is None:
        for pkg_id, item_remote in pkg_manifest_remote.items():
            yield pkg_id, (None, item_remote)
        return

    assert (pkg_manifest_remote is not None) and (pkg_manifest_local is not None)
    pkg_manifest_local_copy = pkg_manifest_local.copy()
    for pkg_id, item_remote in pkg_manifest_remote.items():
        yield pkg_id, (pkg_manifest_local_copy.pop(pkg_id, None), item_remote)
    for pkg_id, item_local in pkg_manifest_local_copy.items():
        yield pkg_id, (item_local, None)

ADDON_TYPE_EXTENSION = 0
ADDON_TYPE_LEGACY_CORE = 1
ADDON_TYPE_LEGACY_USER = 2
ADDON_TYPE_LEGACY_OTHER = 3

addon_type_name = (
    "Extension",
    "Core",
    "Legacy (User)",
    "Legacy (Other)",
)

addon_type_icon = (
    'COMMUNITY',
    'BLENDER',
    'FILE_FOLDER',
    'PACKAGE',
)

if USE_ADDON_IGNORE_EXTENSION_MANIFEST_HACK:
    def addon_ignore_manifest_website_hack_remote_or_default(module_name, item_doc_url):
        from . import repo_cache_store_ensure
        from .bl_extension_ops import (
            extension_repos_read,
        )

        repos_all = extension_repos_read()
        repo_module, pkg_id = module_name.split(".")[1:]
        item_remote = None

        repo_cache_store = repo_cache_store_ensure()

        for repo_index, pkg_manifest_remote in enumerate(
                repo_cache_store.pkg_manifest_from_remote_ensure(
                    error_fn=print,
                    ignore_missing=True,
                )
        ):
            if repos_all[repo_index].module == repo_module:
                if pkg_manifest_remote is not None:
                    item_remote = pkg_manifest_remote.get(pkg_id)
                break
        if item_remote is None:
            return item_doc_url
        return item_remote.website or item_doc_url

def addon_draw_item_expanded(
        *,
        layout,
        mod,
        addon_type,
        is_enabled,
        item_description,
        item_maintainer,
        item_version,
        item_warnings,
        item_doc_url,
        item_tracker_url,
        show_developer_ui,
):
    from bpy.app.translations import (
        contexts as i18n_contexts,
    )

    split = layout.split(factor=0.8)
    col_a = split.column()
    col_b = split.column()

    if item_description:
        col_a.label(
            text="{:s}".format(item_description),
        )

    rowsub = col_b.row()
    rowsub.alignment = 'RIGHT'
    if addon_type == ADDON_TYPE_LEGACY_CORE:
        rowsub.active = False
        rowsub.label(text="Built-in")
        rowsub.separator()
    elif addon_type == ADDON_TYPE_LEGACY_USER:
        rowsub.operator("preferences.addon_remove", text="Uninstall").module = mod.__name__
    del rowsub

    layout.separator(type='LINE')

    sub = layout.column()
    sub.active = is_enabled
    split = sub.split(factor=0.15)
    col_a = split.column()
    col_b = split.column()

    col_a.alignment = 'RIGHT'

    if item_doc_url:
        col_a.label(text="Website")
        col_b.split(factor=0.5).operator(
            "wm.url_open",
            text=domain_extract_from_url(item_doc_url),
            icon='HELP' if addon_type in {ADDON_TYPE_LEGACY_CORE, ADDON_TYPE_LEGACY_USER} else 'URL',
        ).url = item_doc_url
    if item_tracker_url:
        col_a.label(text="Feedback", text_ctxt=i18n_contexts.editor_preferences)
        col_b.split(factor=0.5).operator(
            "wm.url_open", text="Report a Bug", icon='URL',
        ).url = item_tracker_url

    if USE_SHOW_ADDON_TYPE_AS_TEXT:
        col_a.label(text="Type")
        col_b.label(text=addon_type_name[addon_type])
    if item_maintainer:
        col_a.label(text="Maintainer")
        col_b.label(text=item_maintainer)
    if item_version:
        col_a.label(text="Version")
        col_b.label(text=item_version, translate=False)
    if item_warnings:
        col_a.label(text="Warning")
        col_b.label(text=item_warnings[0], icon='ERROR')
        if len(item_warnings) > 1:
            for value in item_warnings[1:]:
                col_a.label(text="")
                col_b.label(text=value, icon='BLANK1')
            del value

    if addon_type != ADDON_TYPE_LEGACY_CORE:
        col_a.label(text="File")
        row = col_b.row()
        row.label(text=mod.__file__, translate=False)
        import os
        row.operator("wm.path_open", text="", icon='FILE_FOLDER').filepath = os.path.dirname(mod.__file__)

def addons_panel_draw_missing_with_extension_impl(
        *,
        context,
        layout,
        missing_modules
):
    layout_header, layout_panel = layout.panel("builtin_addons", default_closed=True)
    layout_header.label(text="Missing Built-in Add-ons", icon='ERROR')

    if layout_panel is None:
        return

    prefs = context.preferences
    extensions_map_from_legacy_addons_ensure()

    repo_index = -1
    repo = None
    for repo_test_index, repo_test in enumerate(prefs.extensions.repos):
        if (
                repo_test.use_remote_url and
                (repo_test.remote_url.rstrip("/") == extensions_map_from_legacy_addons_url)
        ):
            repo_index = repo_test_index
            repo = repo_test
            break

    box = layout_panel.box()
    box.label(text="Add-ons previously shipped with Blender are now available from extensions.blender.org.")

    pkg_manifest_remote = {}

    if repo is None:
        box.label(text="Blender's extension repository not found!", icon='ERROR')
    elif not repo.enabled:
        box.label(text="Blender's extension repository must be enabled to install extensions!", icon='ERROR')
        repo_index = -1
    else:
        from . import repo_cache_store_ensure
        repo_cache_store = repo_cache_store_ensure()
        pkg_manifest_remote = repo_cache_store.refresh_remote_from_directory(directory=repo.directory, error_fn=print)
        if pkg_manifest_remote is None:
            row = box.row()
            row.label(text="Blender's extension repository must be refreshed!", icon='ERROR')
            rowsub = row.row()
            rowsub.alignment = 'RIGHT'
            rowsub.operator("extensions.repo_sync_all", text="Refresh Remote", icon='FILE_REFRESH')
            rowsub.label(text="", icon='BLANK1')
            pkg_manifest_remote = {}
            del row, rowsub
        del repo_cache_store
    del repo

    for addon_module_name in sorted(missing_modules):
        addon_pkg_id, addon_name = extensions_map_from_legacy_addons[addon_module_name]

        boxsub = box.column().box()
        colsub = boxsub.column()
        row = colsub.row()

        row_left = row.row()
        row_left.alignment = 'LEFT'

        row_left.label(text=addon_name, translate=False)

        row_right = row.row()
        row_right.alignment = 'RIGHT'

        if repo_index != -1 and addon_pkg_id:
            rowsub = row_right.row()
            rowsub.alignment = 'RIGHT'
            props = rowsub.operator("extensions.package_install", text="Install")
            props.repo_index = repo_index
            props.pkg_id = addon_pkg_id
            props.do_legacy_replace = True
            del props

            if addon_pkg_id not in pkg_manifest_remote:
                rowsub.enabled = False
            del rowsub

        row_right.operator("preferences.addon_disable", text="", icon="X", emboss=False).module = addon_module_name


def addons_panel_draw_missing_impl(
        *,
        layout,
        missing_modules,
):
    layout_header, layout_panel = layout.panel("missing_script_files", default_closed=True)
    layout_header.label(text="Missing Add-ons", icon='ERROR')

    if layout_panel is None:
        return

    box = layout_panel.box()
    for addon_module_name in sorted(missing_modules):

        boxsub = box.column().box()
        colsub = boxsub.column()
        row = colsub.row(align=True)

        row_left = row.row()
        row_left.alignment = 'LEFT'
        row_left.label(text=addon_module_name, translate=False)

        row_right = row.row()
        row_right.alignment = 'RIGHT'
        row_right.operator("preferences.addon_disable", text="", icon="X", emboss=False).module = addon_module_name


def addons_panel_draw_items(
        layout,
        context,
        *,
        addon_modules,
        used_addon_module_name_map,
        search_casefold,
        addon_tags_exclude,
        enabled_only,
        addon_extension_manifest_map,
        addon_extension_block_map,

        show_development,
        show_developer_ui,
):

    import addon_utils
    from .bl_extension_ops import (
        pkg_info_check_exclude_filter_ex,
    )

    module_names = set()

    user_addon_paths = []

    extensions_warnings = addon_utils._extensions_warnings_get()

    for mod in addon_modules:
        module_names.add(module_name := mod.__name__)

        is_enabled = module_name in used_addon_module_name_map
        if enabled_only and (not is_enabled):
            continue

        is_extension = addon_utils.check_extension(module_name)
        bl_info = addon_utils.module_bl_info(mod)
        show_expanded = bl_info["show_expanded"]

        if is_extension:
            item_warnings = []

            if pkg_block := addon_extension_block_map.get(module_name):
                item_warnings.append("Blocked: {:s}".format(pkg_block.reason))

            if value := extensions_warnings.get(module_name):
                item_warnings.extend(value)
            del value

            if (item_local := addon_extension_manifest_map.get(module_name)) is not None:
                del bl_info

                item_name = item_local.name
                item_description = item_local.tagline
                item_tags = item_local.tags
                if show_expanded:
                    item_maintainer = item_local.maintainer
                    item_version = item_local.version
                    item_doc_url = item_local.website
                    item_tracker_url = ""

                    if USE_ADDON_IGNORE_EXTENSION_MANIFEST_HACK:
                        item_doc_url = addon_ignore_manifest_website_hack_remote_or_default(module_name, item_doc_url)
            else:
                item_name = bl_info.get("name") or module_name
                del bl_info

                item_description = ""
                item_tags = ()
                item_warnings.append("Unable to parse the manifest")
                item_maintainer = ""
                item_version = "0.0.0"
                item_doc_url = ""
                item_tracker_url = ""

            del item_local
        else:
            if (module_name in SECRET_ADDONS) and is_enabled and (show_development is False):
                continue

            item_warnings = []

            item_name = bl_info["name"]
            item_description = bl_info["description"].rstrip(".")
            item_tags = (bl_info["category"],)

            if value := bl_info["warning"]:
                item_warnings.append(value)
            del value

            if show_expanded:
                item_maintainer = value if (value := bl_info["author"]) else ""
                item_version = ".".join(str(x) for x in value) if (value := bl_info["version"]) else ""
                item_doc_url = bl_info["doc_url"]
                item_tracker_url = bl_info.get("tracker_url")
            del bl_info

        if search_casefold and (
                not pkg_info_check_exclude_filter_ex(
                    item_name,
                    item_description,
                    search_casefold,
                )
        ):
            continue

        if addon_tags_exclude:
            if tags_exclude_match(item_tags, addon_tags_exclude):
                continue

        if is_extension:
            addon_type = ADDON_TYPE_EXTENSION
        elif module_parent_dirname(mod.__file__) == "addons_core":
            addon_type = ADDON_TYPE_LEGACY_CORE
        elif USERPREF_PT_addons.is_user_addon(mod, user_addon_paths):
            addon_type = ADDON_TYPE_LEGACY_USER
        else:
            addon_type = ADDON_TYPE_LEGACY_OTHER

        col_box = layout.column()
        box = col_box.box()
        colsub = box.column()
        row = colsub.row(align=True)

        row.operator(
            "preferences.addon_expand",
            icon='DOWNARROW_HLT' if show_expanded else 'RIGHTARROW',
            emboss=False,
        ).module = module_name

        row.operator(
            "preferences.addon_disable" if is_enabled else "preferences.addon_enable",
            icon='CHECKBOX_HLT' if is_enabled else 'CHECKBOX_DEHLT', text="",
            emboss=False,
        ).module = module_name

        sub = row.row()
        sub.active = is_enabled

        sub.label(text="" + item_name)

        if item_warnings:
            sub.label(icon='ERROR')
        elif USE_SHOW_ADDON_TYPE_AS_ICON:
            sub.label(icon=addon_type_icon[addon_type])

        if show_expanded:
            addon_draw_item_expanded(
                layout=box,
                mod=mod,
                addon_type=addon_type,
                is_enabled=is_enabled,
                item_description=item_description,
                item_maintainer=item_maintainer,
                item_version=item_version,
                item_warnings=item_warnings,
                item_doc_url=item_doc_url,
                item_tracker_url=item_tracker_url,
                show_developer_ui=show_developer_ui,
            )

            if is_enabled:
                if (addon_preferences := used_addon_module_name_map[module_name].preferences) is not None:
                    box.separator(type='LINE')
                    USERPREF_PT_addons.draw_addon_preferences(box, context, addon_preferences)
    return module_names


def addons_panel_draw_error_duplicates(layout):
    import addon_utils
    import os

    box = layout.box()
    row = box.row()
    row.label(text="Multiple add-ons with the same name found!")
    row.label(icon='ERROR')
    box.label(text="Delete one of each pair to resolve:")
    for (addon_name, addon_file, addon_path) in addon_utils.error_duplicates:
        box.separator()
        sub_col = box.column(align=True)
        sub_col.label(text=addon_name + ":")

        sub_row = sub_col.row()
        sub_row.label(text="    " + addon_file)
        sub_row.operator("wm.path_open", text="", icon='FILE_FOLDER').filepath = os.path.dirname(addon_file)

        sub_row = sub_col.row()
        sub_row.label(text="    " + addon_path)
        sub_row.operator("wm.path_open", text="", icon='FILE_FOLDER').filepath = os.path.dirname(addon_path)


def addons_panel_draw_error_generic(layout, lines):
    box = layout.box()
    sub = box.row()
    sub.label(text=lines[0])
    sub.label(icon='ERROR')
    for l in lines[1:]:
        box.label(text=l)


def addons_panel_draw_impl(
        panel,
        context,
        search_casefold,
        addon_tags_exclude,
        enabled_only,
        *,
        show_development,
        show_developer_ui,
):
    import addon_utils
    from .bl_extension_ops import (
        extension_repos_read,
        repo_cache_store_refresh_from_prefs,
    )

    from . import repo_cache_store_ensure

    layout = panel.layout

    if addon_utils.error_duplicates:
        addons_panel_draw_error_duplicates(layout)
    if addon_utils.error_encoding:
        addons_panel_draw_error_generic(
            layout, (
                "One or more add-ons do not have UTF-8 encoding",
                "(see console for details)",
            ),
        )

    repo_cache_store = repo_cache_store_ensure()

    if not repo_cache_store.is_init():
        repo_cache_store_refresh_from_prefs(repo_cache_store)

    prefs = context.preferences

    layout_topmost = layout.column()

    repos_all = extension_repos_read()

    errors_on_draw = []

    local_ex = None

    def error_fn_local(ex):
        nonlocal local_ex
        local_ex = ex

    addon_extension_manifest_map = {}
    addon_extension_block_map = {}

    for repo_index, (
            pkg_manifest_local,
            pkg_manifest_remote,
    ) in enumerate(zip(
        repo_cache_store.pkg_manifest_from_local_ensure(error_fn=error_fn_local),
        repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=error_fn_local),
        strict=True,
    )):
        if pkg_manifest_local is None:
            continue

        repo_module_prefix = pkg_repo_module_prefix(repos_all[repo_index])
        for pkg_id, item_local in pkg_manifest_local.items():
            if item_local.type != "add-on":
                continue
            module_name = repo_module_prefix + pkg_id
            addon_extension_manifest_map[module_name] = item_local

            if pkg_manifest_remote is not None:
                if (item_remote := pkg_manifest_remote.get(pkg_id)) is not None:
                    if (pkg_block := item_remote.block) is not None:
                        addon_extension_block_map[module_name] = pkg_block

    used_addon_module_name_map = {addon.module: addon for addon in prefs.addons}

    module_names = addons_panel_draw_items(
        layout,
        context,
        addon_modules=addon_utils.modules(refresh=False),
        used_addon_module_name_map=used_addon_module_name_map,
        search_casefold=search_casefold,
        addon_tags_exclude=addon_tags_exclude,
        enabled_only=enabled_only,
        addon_extension_manifest_map=addon_extension_manifest_map,
        addon_extension_block_map=addon_extension_block_map,
        show_development=show_development,
        show_developer_ui=show_developer_ui,
    )

    missing_modules = {
        addon_module_name for addon_module_name in used_addon_module_name_map
        if addon_module_name not in module_names
    }

    if missing_modules:
        extensions_map_from_legacy_addons_ensure()

        missing_modules_with_extension = set()
        missing_modules_without_extension = set()

        for addon_module_name in missing_modules:
            if addon_module_name in extensions_map_from_legacy_addons:
                missing_modules_with_extension.add(addon_module_name)
            else:
                missing_modules_without_extension.add(addon_module_name)
        if missing_modules_with_extension:
            addons_panel_draw_missing_with_extension_impl(
                context=context,
                layout=layout_topmost,
                missing_modules=missing_modules_with_extension,
            )

        missing_modules = missing_modules_without_extension

    if missing_modules:
        addons_panel_draw_missing_impl(
            layout=layout_topmost,
            missing_modules=missing_modules,
        )

    display_errors.errors_curr = errors_on_draw
    if errors_on_draw:
        display_errors.draw(layout_topmost)


def addons_panel_draw(panel, context):
    prefs = context.preferences
    view = prefs.view

    wm = context.window_manager
    layout = panel.layout

    split = layout.split(factor=0.5)
    row_a = split.row()
    row_b = split.row()
    row_a.prop(wm, "addon_search", text="", icon='VIEWZOOM', placeholder="Search Add-ons")
    row_b.prop(view, "show_addons_enabled_only", text="Enabled Only")
    row_b.operator("extensions.package_install_files", text="Install Add-on")
    rowsub = row_b.row(align=True)

    rowsub.popover("USERPREF_PT_addons_tags", text="", icon='TAG')

    rowsub.separator()

    rowsub.menu("USERPREF_MT_addons_settings", text="", icon='DOWNARROW_HLT')
    del split, row_a, row_b, rowsub

    if bpy.app.version < (5, 0, 0):
        addon_tags_exclude = {k for (k, v) in wm.get("addon_tags", {}).items() if v is False}
    else:
        addon_tags_exclude = tags_exclude_get(wm, "addon_tags")

    addons_panel_draw_impl(
        panel,
        context,
        wm.addon_search.casefold(),
        addon_tags_exclude,
        view.show_addons_enabled_only,
        show_development=prefs.experimental.use_extensions_debug,
        show_developer_ui=prefs.view.show_developer_ui,
    )

from collections import namedtuple

ExtensionUI = namedtuple(
    "ExtensionUI",
    (
        "repo_index",
        "pkg_id",
        "item_local",
        "item_remote",
        "is_enabled",
        "is_outdated",
    ),
)
del namedtuple


class ExtensionUI_FilterParams:
    __slots__ = (
        "search_casefold",
        "tags_exclude",
        "filter_by_type",
        "addons_enabled",
        "active_theme_info",
        "repos_all",

        "show_installed_enabled",
        "show_installed_disabled",
        "show_available",

        "has_installed_enabled",
        "has_installed_disabled",
        "has_available",
    )

    def __init__(
            self,
            *,
            search_casefold,
            tags_exclude,
            filter_by_type,
            addons_enabled,
            active_theme_info,
            repos_all,
            show_installed_enabled,
            show_installed_disabled,
            show_available,
    ):
        self.search_casefold = search_casefold
        self.tags_exclude = tags_exclude
        self.filter_by_type = filter_by_type
        self.addons_enabled = addons_enabled
        self.active_theme_info = active_theme_info
        self.repos_all = repos_all
        self.show_installed_enabled = show_installed_enabled
        self.show_installed_disabled = show_installed_disabled
        self.show_available = show_available

        self.has_installed_enabled = False
        self.has_installed_disabled = False
        self.has_available = False

    @staticmethod
    def default_from_context(context):
        from .bl_extension_ops import (
            blender_filter_by_type_map,
            extension_repos_read,
        )

        wm = context.window_manager
        prefs = context.preferences

        repos_all = extension_repos_read()

        filter_by_type = blender_filter_by_type_map[wm.extension_type]
        show_addons = filter_by_type in {"", "add-on"}
        show_themes = filter_by_type in {"", "theme"}

        if show_addons:
            addons_enabled = {addon.module for addon in prefs.addons} if show_addons else None
        else:
            addons_enabled = None

        if show_themes:
            active_theme_info = pkg_repo_and_id_from_theme_path(repos_all, prefs.themes[0].filepath)
        else:
            active_theme_info = None

        if bpy.app.version < (5, 0, 0):
            extension_tags_exclude = {k for (k, v) in wm.get("extension_tags", {}).items() if v is False}
        else:
            extension_tags_exclude = tags_exclude_get(wm, "extension_tags")

        return ExtensionUI_FilterParams(
            search_casefold=wm.extension_search.casefold(),
            tags_exclude=extension_tags_exclude,
            filter_by_type=filter_by_type,
            addons_enabled=addons_enabled,
            active_theme_info=active_theme_info,
            repos_all=repos_all,

            show_installed_enabled=wm.extension_show_panel_installed,
            show_installed_disabled=wm.extension_show_panel_installed,
            show_available=wm.extension_show_panel_available,
        )

    def extension_ui_visible(
            self,
            repo_index,
            pkg_manifest_local,
            pkg_manifest_remote,
    ):
        from .bl_extension_ops import (
            pkg_info_check_exclude_filter,
        )

        show_addons = self.filter_by_type in {"", "add-on"}

        if show_addons:
            repo_module_prefix = pkg_repo_module_prefix(self.repos_all[repo_index])

        for pkg_id, (item_local, item_remote) in pkg_manifest_zip_all_items(pkg_manifest_local, pkg_manifest_remote):

            is_installed = item_local is not None

            item = item_local or item_remote
            if self.filter_by_type and (self.filter_by_type != item.type):
                continue
            if self.search_casefold and (not pkg_info_check_exclude_filter(item, self.search_casefold)):
                continue

            if self.tags_exclude:
                if tags_exclude_match(item.tags, self.tags_exclude):
                    continue

            is_addon = False
            is_theme = False
            match item.type:
                case "add-on":
                    is_addon = True
                case "theme":
                    is_theme = True

            if is_addon:
                if is_installed:
                    addon_module_name = repo_module_prefix + pkg_id
                    is_enabled = addon_module_name in self.addons_enabled

                else:
                    is_enabled = False
                    addon_module_name = None
            elif is_theme:
                is_enabled = (repo_index, pkg_id) == self.active_theme_info
                addon_module_name = None
            else:
                is_enabled = is_installed
                addon_module_name = None

            item_version = item.version
            if item_local is None or item_remote is None:
                item_remote_version = None
                is_outdated = False
            else:
                item_remote_version = item_remote.version
                is_outdated = item_remote_version != item_version

            if is_installed:
                if is_enabled:
                    self.has_installed_enabled = True
                    if not self.show_installed_enabled:
                        continue
                else:
                    self.has_installed_disabled = True
                    if not self.show_installed_disabled:
                        continue
            else:
                self.has_available = True
                if not self.show_available:
                    continue

            yield ExtensionUI(repo_index, pkg_id, item_local, item_remote, is_enabled, is_outdated)

class ExtensionUI_Visibility:
    __slots__ = (
        "_visible",
    )

    def __init__(self, context, repo_cache_store):
        visible = set()

        params = ExtensionUI_FilterParams.default_from_context(context)

        for repo_index, (
                pkg_manifest_local,
                pkg_manifest_remote,
        ) in enumerate(zip(
            repo_cache_store.pkg_manifest_from_local_ensure(error_fn=print),
            repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=print),
            strict=True,
        )):
            for ext_ui in params.extension_ui_visible(
                    repo_index,
                    pkg_manifest_local,
                    pkg_manifest_remote,
            ):
                visible.add((ext_ui.pkg_id, repo_index))

        self._visible = visible

    def test(self, key):
        return key in self._visible

class display_errors:
    errors_prev = []
    errors_curr = []

    @staticmethod
    def clear():
        display_errors.errors_prev = display_errors.errors_curr

    @staticmethod
    def draw(layout):
        if display_errors.errors_curr == display_errors.errors_prev:
            return
        box_header = layout.box()
        row = box_header.split(factor=0.9)
        row.label(text="Repository Alert:", icon='ERROR')
        rowsub = row.row(align=True)
        rowsub.alignment = 'RIGHT'
        rowsub.operator("extensions.status_clear_errors", text="", icon='X', emboss=False)

        box_contents = box_header.box()
        for err in display_errors.errors_curr:
            if "\n" in err:
                box_contents_align = box_contents.column(align=True)
                for err in err.split("\n"):
                    box_contents_align.label(text=err)
            else:
                box_contents.label(text=err)


class notify_info:
    _update_state = None

    @staticmethod
    def update_ensure(repos):
        in_progress = False
        match notify_info._update_state:
            case True:
                pass
            case None:
                from .bl_extension_notify import update_non_blocking
                notify_info._update_state = True
                if repos_notify := [(repo, True) for repo in repos if repo.remote_url]:
                    if update_non_blocking(repos_fn=lambda: repos_notify):
                        notify_info._update_state = False
                        in_progress = True
            case False:
                from .bl_extension_notify import update_in_progress
                if update_in_progress():
                    in_progress = True
                else:
                    notify_info._update_state = True
        return in_progress

    @staticmethod
    def update_show_in_preferences():
        if notify_info._update_state is not True:
            return

        notify_info._update_state = False

class ExtensionUI_Section:
    __slots__ = (
        "panel_header",
        "ui_ext_sort_fn",
        "panel_header_action",

        "enabled",
        "extension_ui_list",
    )

    def __init__(self, *, panel_header, ui_ext_sort_fn, panel_header_action=None):
        self.panel_header = panel_header
        self.ui_ext_sort_fn = ui_ext_sort_fn
        self.panel_header_action = panel_header_action

        self.enabled = True
        self.extension_ui_list = []

    @staticmethod
    def sort_by_blocked_and_name_fn(ext_ui):
        item_local = ext_ui.item_local
        item_remote = ext_ui.item_remote
        return (
            not (item_remote is not None and item_remote.block is not None),
            (item_local or item_remote).name.casefold(),
        )

    @staticmethod
    def sort_by_name_fn(ext_ui):
        return (ext_ui.item_local or ext_ui.item_remote).name.casefold()


def extensions_panel_draw_online_extensions_request_impl(
        self,
        _context,
):
    from bpy.app.translations import pgettext_rpt as rpt_

    layout = self.layout
    layout_header, layout_panel = layout.panel("advanced", default_closed=False)
    layout_header.label(text="Online Extensions")

    if layout_panel is None:
        return

    box = layout_panel.box()

    for line in (
            rpt_("Internet access is required to install and update online extensions. "),
            rpt_("You can adjust this later from \"System\" preferences."),
    ):
        box.label(text=line, translate=False)

    row = box.row(align=True)
    row.alignment = 'LEFT'
    row.label(text="While offline, use \"Install from Disk\" instead.")
    row.operator(
        "wm.url_open",
        text="",
        icon='URL',
        emboss=False,
    ).url = (
        "https://docs.blender.org/manual/"
        "{:s}/{:d}.{:d}/editors/preferences/extensions.html#installing-extensions"
    ).format(
        bpy.utils.manual_language_code(),
        *bpy.app.version[:2],
    )

    row = box.row()
    props = row.operator("wm.context_set_boolean", text="Continue Offline", icon='X')
    props.data_path = "preferences.extensions.use_online_access_handled"
    props.value = True

    row.operator("extensions.userpref_allow_online", text="Allow Online Access", icon='CHECKMARK')


extensions_map_from_legacy_addons = None
extensions_map_from_legacy_addons_url = None


def extensions_map_from_legacy_addons_ensure():
    import os
    global extensions_map_from_legacy_addons, extensions_map_from_legacy_addons_url
    if extensions_map_from_legacy_addons is not None:
        return

    filepath = os.path.join(os.path.dirname(__file__), "extensions_map_from_legacy_addons.py")
    with open(filepath, "rb") as fh:
        data = eval(compile(fh.read(), filepath, "eval"), {})
    extensions_map_from_legacy_addons = data["extensions"]
    extensions_map_from_legacy_addons_url = data["remote_url"]


def extensions_map_from_legacy_addons_reverse_lookup(pkg_id):
    extensions_map_from_legacy_addons_ensure()
    for key_addon_module_name, (value_pkg_id, _) in extensions_map_from_legacy_addons.items():
        if pkg_id == value_pkg_id:
            return key_addon_module_name
    return ""


def extension_draw_item(
        layout,
        *,
        pkg_id,
        item_local,
        item_remote,
        is_enabled,
        is_outdated,
        show,
        mark,

        repo_index,
        repo_item,
        operation_in_progress,
        extensions_warnings,
        show_developer_ui,
):
    item = item_local or item_remote
    is_installed = item_local is not None
    has_remote = repo_item.remote_url != ""

    if item_remote is not None:
        pkg_block = item_remote.block
    else:
        pkg_block = None

    if is_enabled:
        item_warnings = extensions_warnings.get(pkg_repo_module_prefix(repo_item) + pkg_id, [])
    else:
        item_warnings = []

    colsub = layout.column()
    row = colsub.row(align=True)

    if show:
        props = row.operator("extensions.package_show_clear", text="", icon='DOWNARROW_HLT', emboss=False)
    else:
        props = row.operator("extensions.package_show_set", text="", icon='RIGHTARROW', emboss=False)
    props.pkg_id = pkg_id
    props.repo_index = repo_index
    del props

    if mark is not None:
        if mark:
            props = row.operator("extensions.package_mark_clear", text="", icon='RADIOBUT_ON', emboss=False)
        else:
            props = row.operator("extensions.package_mark_set", text="", icon='RADIOBUT_OFF', emboss=False)
        props.pkg_id = pkg_id
        props.repo_index = repo_index
        del props

    sub = row.row()
    sub.active = is_enabled
    if pkg_block or item_warnings:
        sub.label(text=item.name, icon='ERROR')
    else:
        sub.label(text=item.name)

    del sub

    row_right_toplevel = row.row(align=True)
    if operation_in_progress:
        row_right_toplevel.enabled = False
    row_right_toplevel.alignment = 'RIGHT'
    row_right = row_right_toplevel.row()
    row_right.alignment = 'RIGHT'

    if has_remote and (item_remote is not None):
        if pkg_block is not None:
            row_right.label(text="Blocked   ")
        elif is_installed:
            if is_outdated:
                row_right.label(text="{:s} → {:s}".format(item_local.version, item_remote.version))
                props = row_right.operator("extensions.package_install", text="Update")
                props.repo_index = repo_index
                props.pkg_id = pkg_id
                props.enable_on_install = is_enabled
                del props
        else:
            props = row_right.operator("extensions.package_install", text="Install")
            props.repo_index = repo_index
            props.pkg_id = pkg_id
            del props
    else:
        if has_remote and (item_remote is None):
            row_right.label(text="Orphan   ")

        row_right.active = False

    row_right = row_right_toplevel.row(align=True)
    row_right.alignment = 'RIGHT'
    row_right.separator()

    row_right.context_string_set("extension_path", "{:s}.{:s}".format(repo_item.module, pkg_id))
    row_right.menu("USERPREF_MT_extensions_item", text="", icon='DOWNARROW_HLT')
    del row_right
    del row_right_toplevel

    if show:
        import os
        from bpy.app.translations import pgettext_iface as iface_

        col = layout.column()

        row = col.row()
        row.active = is_enabled

        row.label(text="{:s}".format(item.tagline))

        col.separator(type='LINE')
        del col

        col_info = layout.column()
        col_info.active = is_enabled
        split = col_info.split(factor=0.15)
        col_a = split.column()
        col_b = split.column()
        col_a.alignment = "RIGHT"

        if pkg_block is not None:
            col_a.label(text="Blocked")
            col_b.label(text=pkg_block.reason, translate=False)

        if item_warnings:
            col_a.label(text="Warning")
            col_b.label(text=item_warnings[0])
            if len(item_warnings) > 1:
                for value in item_warnings[1:]:
                    col_a.label(text="")
                    col_b.label(text=value)
                del value

        if value := (item_remote or item_local).website:
            col_a.label(text="Website")
            col_b.split(factor=0.5).operator(
                "wm.url_open", text=domain_extract_from_url(value), icon='URL',
            ).url = value
        del value

        if item.type == "add-on":
            col_a.label(text="Permissions")

            if (value := item.permissions):
                col_b.label(text=", ".join([iface_(x).title() for x in value]), translate=False)
            else:
                col_b.label(text="No permissions specified")
            del value

        col_a.label(text="Maintainer")
        col_b.label(text=item.maintainer, translate=False)

        col_a.label(text="Version")
        if is_outdated:
            col_b.label(
                text=iface_("{:s} ({:s} available)").format(item.version, item_remote.version),
                translate=False,
            )
        else:
            col_b.label(text=item.version, translate=False)

        if has_remote and (item_remote is not None):
            col_a.label(text="Size")
            col_b.label(text=size_as_fmt_string(item_remote.archive_size), translate=False)

        col_a.label(text="License")
        col_b.label(text=item.license, translate=False)

        col_a.label(text="Repository")
        col_b.label(text=repo_item.name, translate=False)

        if is_installed:
            col_a.label(text="Path")
            row = col_b.row()
            dirpath = os.path.join(repo_item.directory, pkg_id)
            row.label(text=dirpath, translate=False)

            row.operator("wm.path_open", text="", icon='FILE_FOLDER').filepath = dirpath


def extensions_panel_draw_impl(
        self,
        context,
        params,
        operation_in_progress,
        show_development,
):

    from bpy.app.translations import (
        pgettext_iface as iface_,
    )
    from .bl_extension_ops import (
        blender_extension_mark,
        blender_extension_show,
        repo_cache_store_refresh_from_prefs,
    )

    from . import repo_cache_store_ensure

    wm = context.window_manager
    prefs = context.preferences

    repo_cache_store = repo_cache_store_ensure()

    import addon_utils
    extensions_warnings = addon_utils._extensions_warnings_get()

    if not repo_cache_store.is_init():
        repo_cache_store_refresh_from_prefs(repo_cache_store)

    layout = self.layout

    layout_topmost = layout.column()

    if bpy.app.online_access:
        if notify_info.update_ensure(params.repos_all):
            from .bl_extension_notify import update_ui_text
            text, icon = update_ui_text()
            if text:
                layout_topmost.box().label(text=text, icon=icon)
            del text, icon

    errors_on_draw = []

    local_ex = None
    remote_ex = None

    def error_fn_local(ex):
        nonlocal local_ex
        local_ex = ex

    def error_fn_remote(ex):
        nonlocal remote_ex
        remote_ex = ex

    section_list = (
        ExtensionUI_Section(
            panel_header=(iface_("Installed"), "extension_show_panel_installed"),
            ui_ext_sort_fn=ExtensionUI_Section.sort_by_blocked_and_name_fn,
            panel_header_action=(
                ((iface_("Update All"), "extensions.package_upgrade_all")) if wm.extensions_updates > 0 else None
            ),
        ),
        ExtensionUI_Section(
            panel_header=None,
            ui_ext_sort_fn=ExtensionUI_Section.sort_by_name_fn,
        ),
        ExtensionUI_Section(
            panel_header=None,
            ui_ext_sort_fn=ExtensionUI_Section.sort_by_name_fn,
        ),
        ExtensionUI_Section(
            panel_header=None,
            ui_ext_sort_fn=ExtensionUI_Section.sort_by_name_fn,
        ),
        ExtensionUI_Section(
            panel_header=(iface_("Available"), "extension_show_panel_available"),
            ui_ext_sort_fn=None,
        ),
    )
    section_table = {
        (True, True): section_list[0],
        (True, False): section_list[1],
        (False, True): section_list[2],
        (False, False): section_list[3],
    }
    section_installed = section_list[0]
    section_available = section_list[4]

    repo_index = -1
    pkg_manifest_local = None
    pkg_manifest_remote = None

    for repo_index, (
            pkg_manifest_local,
            pkg_manifest_remote,
    ) in enumerate(zip(
        repo_cache_store.pkg_manifest_from_local_ensure(error_fn=error_fn_local),
        repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=error_fn_remote),
        strict=True,
    )):
        if (remote_ex is not None) or (local_ex is not None):
            repo = params.repos_all[repo_index]
            if remote_ex is not None:
                if isinstance(remote_ex, FileNotFoundError) and (remote_ex.filename == repo.directory):
                    pass
                else:
                    errors_on_draw.append("Remote of \"{:s}\": {:s}".format(repo.name, str(remote_ex)))
                remote_ex = None

            if local_ex is not None:
                if isinstance(local_ex, FileNotFoundError) and (local_ex.filename == repo.directory):
                    pass
                else:
                    errors_on_draw.append("Local of \"{:s}\": {:s}".format(repo.name, str(local_ex)))
                local_ex = None
            continue

        has_remote = params.repos_all[repo_index].remote_url != ""
        if pkg_manifest_remote is None:
            if has_remote:
                if bpy.app.online_access:
                    errors_on_draw.append(
                        (
                            "Repository: \"{:s}\" remote data unavailable, "
                            "sync with the remote repository."
                        ).format(
                            params.repos_all[repo_index].name,
                        )
                    )
                elif prefs.extensions.use_online_access_handled is False:
                    pass
                else:
                    errors_on_draw.append(
                        (
                            "Repository: \"{:s}\" remote data unavailable, "
                            "either allow \"Online Access\" or disable the repository to suppress this message"
                        ).format(
                            params.repos_all[repo_index].name,
                        )
                    )
                continue

        for ext_ui in params.extension_ui_visible(
                repo_index,
                pkg_manifest_local,
                pkg_manifest_remote,
        ):
            if ext_ui.item_local is None:
                section = section_available
            else:
                if ((item_remote := ext_ui.item_remote) is not None) and (item_remote.block is not None):
                    section = section_installed
                else:
                    section = section_table[ext_ui.is_outdated, ext_ui.is_enabled]

            section.extension_ui_list.append(ext_ui)

    if wm.extensions_blocked:
        errors_on_draw.append((
            "Found {:d} extension(s) blocked by the remote repository!\n"
            "Expand the extension to see the reason for blocking.\n"
            "Uninstall these extensions to remove the warning."
        ).format(wm.extensions_blocked))

    del repo_index, pkg_manifest_local, pkg_manifest_remote

    section_installed.enabled = (params.has_installed_enabled or params.has_installed_disabled)
    section_available.enabled = params.has_available

    layout_panel = None

    for section in section_list:
        if not section.enabled:
            continue

        if section.panel_header:
            label, prop_id = section.panel_header
            layout_header, layout_panel = layout.panel_prop(wm, prop_id)
            layout_header.label(text=label, translate=False)

            if section.panel_header_action is not None:
                operator_label, operator = section.panel_header_action
                row = layout_header.row()
                row.scale_x = 1.14
                row.active = wm.extensions_updates > 0 and not operation_in_progress
                row.alignment = 'RIGHT'
                row.operator(operator, text=operator_label)
                del operator, operator_label, row
            del label, prop_id, layout_header

        if layout_panel is None:
            continue
        if not section.extension_ui_list:
            continue

        if section.ui_ext_sort_fn is not None:
            section.extension_ui_list.sort(key=section.ui_ext_sort_fn)

        for ext_ui in section.extension_ui_list:
            extension_draw_item(
                layout_panel.box(),
                pkg_id=ext_ui.pkg_id,
                item_local=ext_ui.item_local,
                item_remote=ext_ui.item_remote,
                is_enabled=ext_ui.is_enabled,
                is_outdated=ext_ui.is_outdated,
                show=(ext_ui.pkg_id, ext_ui.repo_index) in blender_extension_show,
                mark=((ext_ui.pkg_id, ext_ui.repo_index) in blender_extension_mark) if show_development else None,

                repo_index=ext_ui.repo_index,
                repo_item=params.repos_all[ext_ui.repo_index],
                operation_in_progress=operation_in_progress,
                extensions_warnings=extensions_warnings,
                show_developer_ui=prefs.view.show_developer_ui,
            )

    display_errors.errors_curr = errors_on_draw
    if errors_on_draw:
        if not operation_in_progress:
            display_errors.draw(layout_topmost)


class USERPREF_PT_addons_tags(Panel):
    bl_label = "Add-on Tags"

    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    def draw(self, context):
        tags_panel_draw(self.layout, context, "addon_tags")


class USERPREF_PT_extensions_tags(Panel):
    bl_label = "Extensions Tags"

    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    def draw(self, context):
        tags_panel_draw(self.layout, context, "extension_tags")


class USERPREF_MT_addons_settings(Menu):
    bl_label = "Add-ons Settings"

    def draw(self, _context):
        layout = self.layout

        layout.operator("extensions.repo_refresh_all", text="Refresh Local", icon='FILE_REFRESH')

        layout.separator()

        layout.operator("extensions.package_install_files", text="Install from Disk...")


class USERPREF_MT_extensions_settings(Menu):
    bl_label = "Extension Settings"

    def draw(self, context):
        layout = self.layout

        prefs = context.preferences

        layout.operator("wm.url_open_preset", text="Visit Extensions Platform", icon='URL').type = 'EXTENSIONS'
        layout.separator()

        layout.operator("extensions.repo_sync_all", icon='FILE_REFRESH')
        layout.operator("extensions.repo_refresh_all")

        layout.separator()

        layout.operator("extensions.package_install_files", text="Install from Disk...", icon='IMPORT')

        if prefs.experimental.use_extensions_debug:

            layout.separator()

            layout.operator("extensions.package_mark_set_all", text="Mark All")
            layout.operator("extensions.package_mark_clear_all", text="Unmark All")

            layout.separator()

            layout.operator(
                "extensions.package_install_marked",
                text="Install Marked",
                icon='IMPORT',
            ).enable_on_install = False
            layout.operator(
                "extensions.package_uninstall_marked",
                text="Uninstall Marked",
                icon='X',
            )

            layout.operator("extensions.package_obsolete_marked")

            layout.separator()

            layout.operator("extensions.repo_lock_all")
            layout.operator("extensions.repo_unlock_all")

class USERPREF_MT_extensions_item(Menu):
    bl_label = "Extension Item"

    @classmethod
    def _extension_data_or_error(cls, prefs, extension_path):

        from . import repo_cache_store_ensure
        from .bl_extension_ops import extension_repos_read

        repo_module, pkg_id = extension_path.partition(".")[0::2]

        repos_all = extension_repos_read()
        repo_index, repo = next(
            (
                (repo_index, repo)
                for repo_index, repo in enumerate(repos_all)
                if repo.module == repo_module
            ),
            (-1, None),
        )
        if repo is None:
            return "Internal error accessing repository"

        repo_cache_store = repo_cache_store_ensure()

        pkg_manifest_local = repo_cache_store.refresh_local_from_directory(directory=repo.directory, error_fn=print)
        pkg_manifest_remote = repo_cache_store.refresh_remote_from_directory(directory=repo.directory, error_fn=print)

        item_local = (pkg_manifest_local or {}).get(pkg_id)
        item_remote = (pkg_manifest_remote or {}).get(pkg_id)

        if item_local is None and item_remote is None:
            return "Internal error accessing repository meta-data"

        repo_module_prefix = pkg_repo_module_prefix(repo)

        addon_module_name = repo_module_prefix + pkg_id

        is_enabled = False
        if item_local is not None:
            match item_local.type:
                case "add-on":
                    is_enabled = prefs.addons.get(addon_module_name) is not None
                case "theme":
                    active_theme_info = pkg_repo_and_id_from_theme_path(repos_all, prefs.themes[0].filepath)
                    is_enabled = (repo_index, pkg_id) == active_theme_info

        return repo, repo_index, pkg_id, item_local, item_remote, addon_module_name, is_enabled

    def draw(self, context):

        layout = self.layout

        prefs = context.preferences

        if isinstance(result := self._extension_data_or_error(prefs, getattr(context, "extension_path", "")), str):
            layout.label(text=result)
            return

        show_development = prefs.experimental.use_extensions_debug

        repo, repo_index, pkg_id, item_local, item_remote, addon_module_name, is_enabled = result
        del result

        item = item_local or item_remote

        is_installed = item_local is not None
        is_system_repo = repo.source == 'SYSTEM'

        match item.type:
            case "add-on":
                if is_installed:
                    props = layout.operator("preferences.addon_show", text="View Details")
                    props.module = addon_module_name
                    del props

                    if show_development:
                        layout.operator(
                            "preferences.addon_disable" if is_enabled else "preferences.addon_enable",
                            icon='CHECKBOX_HLT' if is_enabled else 'CHECKBOX_DEHLT',
                            text="Add-on Enabled",
                            emboss=False,
                        ).module = addon_module_name
            case "theme":
                if is_installed:
                    props = layout.operator(
                        "extensions.package_theme_disable" if is_enabled else "extensions.package_theme_enable",
                        text="Clear Theme" if is_enabled else "Set Theme",
                    )
                    props.repo_index = repo_index
                    props.pkg_id = pkg_id
                    del props

        if value := (item_remote or item_local).website:
            layout.operator("wm.url_open", text="Visit Website", icon='URL').url = value
        else:
            col = layout.column()
            col.operator("wm.url_open", text="Visit Website", icon='URL').url = ""
            col.enabled = False

        del value

        if is_installed:
            layout.separator()

            if is_system_repo:
                layout.operator("extensions.package_uninstall_system", text="Uninstall")
            else:
                props = layout.operator("extensions.package_uninstall", text="Uninstall")
                props.repo_index = repo_index
                props.pkg_id = pkg_id
                del props


def extensions_panel_draw(panel, context):
    from . import (
        repo_status_text,
    )
    from .bl_extension_notify import (
        update_in_progress,
    )

    from bpy.app.translations import pgettext_iface as iface_

    wm = context.window_manager
    prefs = context.preferences
    operation_in_progress = False
    if update_in_progress():
        operation_in_progress = True
    elif any(win.modal_operators.get("EXTENSIONS_OT_repo_sync_all") is not None for win in wm.windows):
        operation_in_progress = True

    show_development = prefs.experimental.use_extensions_debug
    show_development_reports = show_development

    layout = panel.layout

    row = layout.split(factor=0.5)
    row_a = row.row()
    row_a.prop(wm, "extension_search", text="", icon='VIEWZOOM', placeholder="Search Extensions")
    row_b = row.row(align=True)
    row_b.prop(wm, "extension_type", text="")
    row_b.popover("USERPREF_PT_extensions_tags", text="", icon='TAG')

    row_b.separator()
    row_b.popover("USERPREF_PT_extensions_repos", text="Repositories")

    row_b.separator()
    row_b.menu("USERPREF_MT_extensions_settings", text="", icon='DOWNARROW_HLT')
    del row, row_a, row_b

    if show_development_reports:
        show_status = bool(repo_status_text.log)
    else:
        show_status = bool(repo_status_text.log) and repo_status_text.running
        if show_status:
            show_status = False
            for ty, msg in repo_status_text.log:
                if ty == 'PROGRESS':
                    show_status = True

    if show_status:
        box = layout.box()
        row = box.split(factor=0.9, align=True)
        if repo_status_text.running:
            row.label(text=iface_(repo_status_text.title) + "...", icon='INFO', translate=False)
        else:
            row.label(text=repo_status_text.title, icon='INFO')
        if show_development_reports:
            rowsub = row.row(align=True)
            rowsub.alignment = 'RIGHT'
            rowsub.operator("extensions.status_clear", text="", icon='X', emboss=False)
        boxsub = box.box()
        for ty, msg in repo_status_text.log:
            if ty == 'STATUS':
                boxsub.label(text=msg)
            elif ty == 'PROGRESS':
                msg_str, progress_unit, progress, progress_range = msg
                if progress <= progress_range:
                    boxsub.progress(
                        factor=progress / progress_range,
                        text="{:s}, {:s}".format(
                            sizes_as_percentage_string(progress, progress_range),
                            iface_(msg_str),
                        ),
                        translate=False,
                    )
                elif progress_unit == 'BYTE':
                    boxsub.progress(
                        factor=0.0,
                        text="{:s}, {:s}".format(iface_(msg_str), size_as_fmt_string(progress)),
                        translate=False,
                    )
                else:
                    boxsub.progress(
                        factor=0.0,
                        text="{:s}, {:d}".format(iface_(msg_str), progress),
                        translate=False,
                    )
            else:
                boxsub.label(
                    text="{:s}: {:s}".format(iface_(ty), iface_(msg)),
                    translate=False,
                )

        if repo_status_text.running:
            return

    if (
            (not prefs.extensions.use_online_access_handled) and
            (not bpy.app.online_access) and
            any(repo for repo in prefs.extensions.repos if repo.enabled and repo.use_remote_url)
    ):
        extensions_panel_draw_online_extensions_request_impl(panel, context)

    extensions_panel_draw_impl(
        panel,
        context,
        ExtensionUI_FilterParams.default_from_context(context),
        operation_in_progress,
        show_development,
    )


def extensions_repo_active_draw(self, _context):
    from . import repo_active_or_none
    layout = self.layout

    if (repo := repo_active_or_none()) is not None:
        layout.context_pointer_set("extension_repo", repo)

    if repo is not None and repo.use_remote_url:
        layout.operator("extensions.repo_sync_all", text="", icon='FILE_REFRESH').use_active_only = True
    else:
        layout.operator("extensions.repo_refresh_all", text="", icon='FILE_REFRESH').use_active_only = True

    layout.separator()

    layout.menu("USERPREF_MT_extensions_active_repo_extra", text="", icon='DOWNARROW_HLT')


class USERPREF_MT_extensions_active_repo_extra(Menu):
    bl_label = "Active Extension Repository"

    def draw(self, _context):
        layout = self.layout

        layout.operator(
            "extensions.package_upgrade_all",
            text="Install Available Updates",
            icon='IMPORT',
        ).use_active_only = True

        layout.operator(
            "extensions.repo_unlock",
            text="Force Unlock Repository...",
            icon='UNLOCKED',
        )

def tags_exclude_match(
        item_tags,
        exclude_tags,
):
    if not item_tags:
        return True

    for tag in item_tags:
        if tag not in exclude_tags:
            return False
    return True


def tags_current(wm, tags_attr):
    from .bl_extension_ops import (
        blender_filter_by_type_map,
        extension_repos_read,
        repo_cache_store_refresh_from_prefs,
    )

    from . import repo_cache_store_ensure

    prefs = bpy.context.preferences

    repo_cache_store = repo_cache_store_ensure()

    if not repo_cache_store.is_init():
        repo_cache_store_refresh_from_prefs(repo_cache_store)

    if tags_attr == "addon_tags":
        filter_by_type = "add-on"
        search_casefold = wm.addon_search.casefold()
        show_installed_enabled = True
        show_installed_disabled = not prefs.view.show_addons_enabled_only
        show_available = False
    else:
        filter_by_type = blender_filter_by_type_map[wm.extension_type]
        search_casefold = wm.extension_search.casefold()
        show_installed_enabled = show_installed_disabled = wm.extension_show_panel_installed
        show_available = wm.extension_show_panel_available

    repos_all = extension_repos_read()

    addons_enabled = None
    active_theme_info = None

    if filter_by_type in {"", "add-on"}:
        addons_enabled = {addon.module for addon in prefs.addons}
    if filter_by_type in {"", "theme"}:
        active_theme_info = pkg_repo_and_id_from_theme_path(repos_all, prefs.themes[0].filepath)

    params = ExtensionUI_FilterParams(
        search_casefold=search_casefold,
        tags_exclude=set(),
        filter_by_type=filter_by_type,
        addons_enabled=addons_enabled,
        active_theme_info=active_theme_info,
        repos_all=repos_all,

        show_installed_enabled=show_installed_enabled,
        show_installed_disabled=show_installed_disabled,
        show_available=show_available,
    )

    tags = set()

    for repo_index, (
            pkg_manifest_local,
            pkg_manifest_remote,
    ) in enumerate(zip(
        repo_cache_store.pkg_manifest_from_local_ensure(error_fn=print),
        repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=print) if (tags_attr != "addon_tags") else
        ((None,) * len(repos_all)),
        strict=True,
    )):
        for ext_ui in params.extension_ui_visible(
                repo_index,
                pkg_manifest_local,
                pkg_manifest_remote,
        ):
            if pkg_tags := (ext_ui.item_local or ext_ui.item_remote).tags:
                tags.update(pkg_tags)

    if tags_attr == "addon_tags":
        import addon_utils
        for mod in addon_utils.modules(refresh=False):
            module_name = mod.__name__
            is_extension = addon_utils.check_extension(module_name)
            if is_extension:
                continue
            if not show_installed_disabled:
                if module_name not in addons_enabled:
                    continue
            bl_info = addon_utils.module_bl_info(mod)
            if t := bl_info.get("category"):
                tags.add(t)

    return tags


def tags_clear(wm, tags_attr):
    if bpy.app.version < (5, 0, 0):
        import idprop
        tags_idprop = wm.get(tags_attr)
        if tags_idprop is None:
            pass
        elif isinstance(tags_idprop, idprop.types.IDPropertyGroup):
            tags_idprop.clear()
        else:
            wm[tags_attr] = {}
    else:
        tags_collection = getattr(wm, tags_attr)
        tags_collection.clear()

def tags_refresh(wm, tags_attr, *, default_value):
    if bpy.app.version < (5, 0, 0):
        import idprop
        tags_idprop = wm.get(tags_attr)
        if isinstance(tags_idprop, idprop.types.IDPropertyGroup):
            pass
        else:
            wm[tags_attr] = {}
            tags_idprop = wm[tags_attr]
        tags_curr = set(tags_idprop.keys())
        tags_next = tags_current(wm, tags_attr)
        tags_to_add = tags_next - tags_curr
        tags_to_rem = tags_curr - tags_next
        for tag in tags_to_rem:
            del tags_idprop[tag]
        for tag in tags_to_add:
            tags_idprop[tag] = default_value
        return list(sorted(tags_next))
    else:
        tags_collection = getattr(wm, tags_attr)
        tags_curr = set(tags_collection.keys())
        tags_next = tags_current(wm, tags_attr)
        tags_to_add = tags_next - tags_curr
        tags_to_rem = tags_curr - tags_next
        if tags_to_rem:
            for i in reversed([i for i, item in enumerate(tags_collection) if item.name in tags_to_rem]):
                tags_collection.remove(i)
        for tag in tags_to_add:
            item = tags_collection.add()
            item.name = tag
            item.show_tag = default_value
        return list(sorted(tags_next))

def tags_exclude_get(wm, tags_attr):
    tags_collection = getattr(wm, tags_attr)
    return {item.name for item in tags_collection if item.show_tag is False}


def tags_panel_draw(layout, context, tags_attr):
    from bpy.utils import escape_identifier
    from bpy.app.translations import contexts as i18n_contexts
    wm = context.window_manager

    split = layout.split(factor=0.5)
    row = split.row()
    row.label(text="Show Tags")
    subrow = row.row()
    subrow.alignment = 'RIGHT'
    subrow.label(text="Select")

    row = split.row()
    props = row.operator("extensions.userpref_tags_set", text="All")
    props.value = True
    props.data_path = tags_attr
    props = row.operator("extensions.userpref_tags_set", text="None")
    props.value = False
    props.data_path = tags_attr
    del split, row

    layout.separator(type='LINE')

    if tags_sorted := tags_refresh(wm, tags_attr, default_value=True):
        tags_len_half = (len(tags_sorted) + 1) // 2
        split = layout.split(factor=0.5)
        col = split.column()
        if bpy.app.version >= (5, 0, 0):
            tags_collection_map = dict(getattr(wm, tags_attr).items())
            for i, t in enumerate(sorted(tags_sorted)):
                if i == tags_len_half:
                    col = split.column()
                col.prop(
                    tags_collection_map[t],
                    "show_tag",
                    text=t,
                    text_ctxt=i18n_contexts.editor_preferences,
                )
        else:
            tags_prop = getattr(wm, tags_attr)
            for i, t in enumerate(sorted(tags_sorted)):
                if i == tags_len_half:
                    col = split.column()
                col.prop(
                    tags_prop,
                    "[\"{:s}\"]".format(escape_identifier(t)),
                    text=t,
                    text_ctxt=i18n_contexts.editor_preferences,
                )
    else:
        col = layout.column()
        col.label(text="No visible tags.")
        col.active = False

classes = (
    USERPREF_PT_addons_tags,
    USERPREF_MT_addons_settings,

    USERPREF_PT_extensions_tags,
    USERPREF_MT_extensions_settings,
    USERPREF_MT_extensions_item,
    USERPREF_MT_extensions_active_repo_extra,
)


def register():
    USERPREF_PT_addons.append(addons_panel_draw)
    USERPREF_PT_extensions.append(extensions_panel_draw)
    USERPREF_MT_extensions_active_repo.append(extensions_repo_active_draw)

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    USERPREF_PT_addons.remove(addons_panel_draw)
    USERPREF_PT_extensions.remove(extensions_panel_draw)
    USERPREF_MT_extensions_active_repo.remove(extensions_repo_active_draw)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
