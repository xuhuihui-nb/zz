# -*- coding: utf-8 -*-

DBG = False
DBG_INIT = False
DBG_PM = False
DBG_PANEL = False
DBG_TREE = False
DBG_PROP_PATH = False
DBG_CMD_EDITOR = False
DBG_LAYOUT = False
DBG_PROP = False
DBG_STACK = False
DBG_MACRO = False
DBG_STICKY = False


def logi(*args, **kwargs):
    print("[PME INFO]", *args, **kwargs)


def logw(*args, **kwargs):
    print("[PME WARN]", *args, **kwargs)


def loge(*args, **kwargs):
    print("[PME ERROR]", *args, **kwargs)


def logh(title=""):
    print(f"=== PME: {title} ===")


def logd(*args, **kwargs):
    print("[PME DEBUG]", *args, **kwargs)


def __getattr__(name):
    if name.startswith("DBG"):
        return False
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
