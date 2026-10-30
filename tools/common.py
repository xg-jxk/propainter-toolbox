# -*- coding: utf-8 -*-
"""兼容层：老的 tools/common.py 现在转发到 pplib.ffmpeg。

保留它是为了不破坏已有 import；新代码请直接用 pplib.*。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import JobError  # noqa: F401,E402
from pplib.ffmpeg import (CUGAN_DIR, CUGAN_EXE, ROOT, TOOLS, WEIGHTS,  # noqa: F401,E402
                          dir_size, encode_frames, ensure_out_writable, find_ffmpeg,
                          human_size, pick_encoder, probe, run, run_stream,
                          video_encode_args)


def log(msg):
    import time
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def set_log_file(path):  # 兼容旧签名；实际日志由 Emitter / runner 负责
    return None
