# -*- coding: utf-8 -*-
"""配置持久化：%LOCALAPPDATA%\\ProPainterToolbox\\config.json"""
import copy
import json
import os

APP_DIR_NAME = "ProPainterToolbox"

#: 条款版本：升级条款时 +1，用户下次启动会重新确认
TERMS_VERSION = 1

DEFAULTS = {
    "repair_enabled": True,
    "sr_enabled": False,
    "detect": "auto",            # auto | rect | mask
    "rect": "",
    "mask": "",
    "padding": 0.45,
    "subvideo": 40,
    "mask_dilation": 2,
    "detect_thr": 0.62,
    "ref_stride": 12,
    "sr_target": "4K",           # 1080p | 2K | 4K | 8K | max
    "sr_max_output": 7680,       # 0 = 不限制
    "denoise": "auto",           # auto | -1 | 0 | 1 | 2 | 3
    "model": "models-pro",
    "out_dir": "",               # 空 = 与源视频同目录
    "crf": 17,
    "encoder": "auto",
    "test_mode": False,
    "test_seconds": 3,
    "test_start": 0.0,
    "keep": False,
    "open_when_done": True,
    "preset": "balanced",
    "log_open": False,
    "mode": "repair",            # 旧版字段，仅用于迁移
    "workdir": "",
    "last_dir": "",
    "terms_version": 0,
    "window": {"w": 1440, "h": 900},
}


def app_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def config_path():
    # 测试/多实例可用环境变量覆盖，避免污染用户真实配置
    override = os.environ.get("PPTOOLBOX_CONFIG")
    if override:
        return override
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
