# -*- coding: utf-8 -*-
"""配置持久化：%LOCALAPPDATA%\\ProPainterToolbox\\config.json"""
import copy
import json
import os

APP_DIR_NAME = "ProPainterToolbox"

#: 条款版本：升级条款时 +1，用户下次启动会重新确认
TERMS_VERSION = 1

DEFAULTS = {
    "mode": "repair",        # repair | sr | pipeline
    "detect": "auto",        # auto | rect | mask
    "rect": "",
    "mask": "",
    "padding": 0.45,
    "subvideo": 40,
    "neighbor": 10,
    "crf": 17,
    "encoder": "auto",
    "scale": 2,
    "denoise": "auto",       # auto | -1 | 0 | 1 | 2 | 3
    "out_dir": "",           # 空 = 与源视频同目录
    "workdir": "",           # 留空用系统临时目录
    "keep": False,
    "open_when_done": True,
    "last_dir": "",
    "terms_version": 0,
    "window": {"w": 1000, "h": 760},
}


def app_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def config_path():
    return os.path.join(app_dir(), "config.json")


def _merge(base, extra):
    out = copy.deepcopy(base)
    if isinstance(extra, dict):
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
    return out


def load(path=None):
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return _merge(DEFAULTS, data)
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg, path=None):
    path = path or config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def logs_dir():
    d = os.path.join(app_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d
