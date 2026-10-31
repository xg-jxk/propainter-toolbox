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
    "sr_enabled": True,          # 修复+超分是主用法，默认两个都开
    "detect": "auto",            # auto | rect | mask
    "rect": "",
    "mask": "",
    "padding": 0.45,
    "sr_target": "1080p",        # 1080p | 2K | 4K | 8K | max（够不着时自动就近取档）
    "denoise": "auto",           # auto | -1 | 1 | 2 | 3
    "model": "models-pro",
    "out_dir": "",               # 空 = 与源视频同目录
    "crf": 17,                   # 只有三档：17 高 / 20 中 / 23 低
    "test_mode": False,
    "test_seconds": 3,
    "test_start": 0.0,
    "open_when_done": True,
    "preset": "balanced",        # fast | balanced | detail（"" = 自定义）
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


def migrate(cfg):
    """把旧版配置一次性迁到参数精简后的语义（只做一次，靠 ui_version 标记）。

    旧版默认目标 "4K" 在低分辨率源上会自动滑到 8K/最高，所以这次统一回到 1080p。
    """
    if int(cfg.get("ui_version", 0) or 0) >= 2:
        return cfg
    cfg["sr_target"] = "1080p"
    if str(cfg.get("preset", "")) == "quality":
        cfg["preset"] = "detail"          # 旧预设改名，且不再绑定画质
    try:
        crf = int(cfg.get("crf", 17))
    except (TypeError, ValueError):
        crf = 17
    cfg["crf"] = 17 if crf <= 17 else (20 if crf <= 20 else 23)
    if str(cfg.get("denoise", "auto")) == "0":   # 旧「0 保守」并到「弱」
        cfg["denoise"] = "1"
    cfg["ui_version"] = 2
    for key in ("subvideo", "mask_dilation", "detect_thr", "ref_stride",
                "sr_max_output", "encoder", "keep"):
        cfg.pop(key, None)
    return cfg


def load(path=None):
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, migrate(dict(data)))


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
