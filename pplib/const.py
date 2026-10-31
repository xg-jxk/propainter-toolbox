# -*- coding: utf-8 -*-
"""轻量常量与输入归一化（不 import cv2/torch，GUI 打包时体积小很多）。"""
import os

#: 界面一次最多接受的文件数（GPU 串行跑，超过只会排队更久）
MAX_QUEUE = 20

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".ts", ".flv", ".wmv", ".mpg")

#: setup.ps1 会下载的三个权重
WEIGHT_FILES = ("raft-things.pth", "recurrent_flow_completion.pth", "ProPainter.pth")


def normalize_inputs(paths, limit=MAX_QUEUE):
    """去重、校验扩展名、限制数量。返回 (accepted, rejected[(path, reason)])。"""
    accepted, rejected, seen = [], [], set()
    for raw in paths:
        p = os.path.abspath(str(raw))
        key = os.path.normcase(p)
        if key in seen:
            continue
        if not os.path.isfile(p):
            rejected.append((p, "文件不存在"))
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext not in VIDEO_EXTS:
            rejected.append((p, "不支持的格式（%s）" % (ext or "无扩展名")))
            continue
        if len(accepted) >= limit:
            rejected.append((p, "队列上限 %d 个" % limit))
            continue
        seen.add(key)
        accepted.append(p)
    return accepted, rejected

#: 输出长边上限的默认值（8K 7680×4320）；用户可在界面里改，0 表示不限制
MAX_OUTPUT_LONG = 7680
DEFAULT_MAX_OUTPUT_LONG = MAX_OUTPUT_LONG
#: 可选的上限档位（长边）：4K / 8K / 16K / 不限制
OUTPUT_LIMITS = [("4K", 3840), ("8K", 7680), ("16K", 15360), ("不限制", 0)]


def app_data_dir():
    """配置/日志/临时文件的统一根目录。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ProPainterToolbox")


def temp_root():
    """所有处理中间文件都放这里，只这一个目录需要加杀软排除。

    可用 PPTOOLBOX_TEMP 覆盖（安装版不想写用户目录时用）。
    """
    path = os.environ.get("PPTOOLBOX_TEMP") or os.path.join(app_data_dir(), "temp")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        import tempfile as _tf
        path = _tf.gettempdir()
    return path
