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

#: 输出长边上限（8K 7680×4320）；超过就没必要也没法处理了
MAX_OUTPUT_LONG = 7680
