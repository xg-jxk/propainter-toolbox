# -*- coding: utf-8 -*-
"""共享路径/进程工具（供 tools 下的脚本 import）。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
CUGAN_DIR = TOOLS / "realcugan"
CUGAN_EXE = CUGAN_DIR / "realcugan-ncnn-vulkan.exe"
WEIGHTS = ROOT / "weights"

_ffmpeg = None


def find_ffmpeg():
    """依次尝试：环境变量 FFMPEG → PATH → tools/ffmpeg → imageio-ffmpeg。"""
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    env = os.environ.get("FFMPEG")
    if env and Path(env).is_file():
        _ffmpeg = env
    else:
        p = shutil.which("ffmpeg")
        if p:
            _ffmpeg = p
        else:
            cand = TOOLS / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if cand.is_file():
                _ffmpeg = str(cand)
            else:
                try:
                    import imageio_ffmpeg
                    _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    pass
    if not _ffmpeg:
        raise SystemExit("找不到 ffmpeg：请安装并加入 PATH，或把 ffmpeg.exe 放到 tools/ffmpeg/ 下")
    return _ffmpeg


def run(cmd, cwd=None, env=None, quiet=True):
    kw = dict(cwd=cwd, env=env)
    if quiet:
        kw.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
    p = subprocess.run(cmd, **kw)
    if p.returncode != 0:
        if quiet:
            sys.stderr.write((p.stdout or "")[-3000:] + "\n" + (p.stderr or "")[-3000:])
        raise SystemExit(f"命令失败: {os.path.basename(str(cmd[0]))}")
    return p


def probe(video):
    """返回 (fps, 是否有音轨, 时长秒)。"""
    ff = find_ffmpeg()
    p = subprocess.run([ff, "-hide_banner", "-i", str(video)], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, errors="ignore")
    info = p.stderr
    import re
    m = re.search(r"(\d+(?:\.\d+)?) fps", info)
    fps = float(m.group(1)) if m else 30.0
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else None
    return fps, ("Audio:" in info), dur
