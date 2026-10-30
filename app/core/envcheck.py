# -*- coding: utf-8 -*-
"""运行环境自检：.venv / 权重 / Real-CUGAN / ffmpeg / 显卡。"""
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from pplib.const import WEIGHT_FILES
from pplib.ffmpeg import CUGAN_DIR, CUGAN_EXE, ROOT, WEIGHTS, find_ffmpeg

VENV_PYTHON = os.path.join(str(ROOT), ".venv", "Scripts", "python.exe")
VENV_PYTHONW = os.path.join(str(ROOT), ".venv", "Scripts", "pythonw.exe")


@dataclass
class RuntimeStatus:
    venv_python: str = VENV_PYTHON
    venv_ok: bool = False
    ffmpeg_ok: bool = False
    cugan_ok: bool = False
    weights_missing: List[str] = field(default_factory=list)
    gpu_name: str = ""
    driver: str = ""
    nvenc: bool = False
    setup_log: Optional[str] = None

    @property
    def weights_ok(self):
        return not self.weights_missing

    @property
    def ready(self):
        return self.venv_ok and self.ffmpeg_ok and self.cugan_ok and self.weights_ok

    def missing_text(self):
        miss = []
        if not self.venv_ok:
            miss.append("Python 虚拟环境")
        if not self.weights_ok:
            miss.append("ProPainter 权重")
        if not self.cugan_ok:
            miss.append("Real-CUGAN")
        if not self.ffmpeg_ok:
            miss.append("ffmpeg")
        return "、".join(miss)

    def gpu_text(self):
        if self.gpu_name:
            return "%s（驱动 %s）" % (self.gpu_name, self.driver or "?")
        return "未检测到 NVIDIA 显卡，将使用 CPU（去水印会非常慢）"


def _nvidia():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        if out.returncode == 0 and out.stdout.strip():
            first = out.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")
    except Exception:
        pass
    return "", ""


def _has_nvenc():
    try:
        ff = find_ffmpeg()
        p = subprocess.run([ff, "-hide_banner", "-encoders"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, errors="ignore", timeout=10)
        return "h264_nvenc" in (p.stdout or "")
    except Exception:
        return False


def check():
    st = RuntimeStatus()
    st.venv_ok = os.path.isfile(VENV_PYTHON)
    try:
        find_ffmpeg()
        st.ffmpeg_ok = True
    except Exception:
        st.ffmpeg_ok = False
    st.cugan_ok = os.path.isfile(str(CUGAN_EXE)) and os.path.isdir(os.path.join(str(CUGAN_DIR), "models-pro"))
    st.weights_missing = [n for n in WEIGHT_FILES
                          if not os.path.isfile(os.path.join(str(WEIGHTS), n))
                          or os.path.getsize(os.path.join(str(WEIGHTS), n)) < 1024 * 1024]
    st.gpu_name, st.driver = _nvidia()
    st.nvenc = _has_nvenc() if st.gpu_name else False
    log = os.path.join(str(ROOT), "setup.log")
    st.setup_log = log if os.path.isfile(log) else None
    return st


def torch_info(python_exe=None):
    """慢查询：torch 版本与 CUDA 是否可用（在后台线程里调）。"""
    exe = python_exe or VENV_PYTHON
    if not os.path.isfile(exe):
        return "未安装"
    code = ("import torch;print('%s cuda=%s' % (torch.__version__, torch.cuda.is_available()))")
    try:
        p = subprocess.run([exe, "-c", code], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, timeout=90,
                           encoding="utf-8", errors="replace")
        if p.returncode == 0:
            return p.stdout.strip()
        return (p.stderr or "").strip().splitlines()[-1] if p.stderr else "未知错误"
    except Exception as e:
        return "检测失败：%s" % e
