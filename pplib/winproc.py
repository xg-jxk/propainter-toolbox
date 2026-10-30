# -*- coding: utf-8 -*-
"""统一的子进程启动参数：Windows 上不弹控制台窗口。

GUI 是窗口子系统（console=False），从它启动任何控制台程序（python.exe / ffmpeg /
powershell / nvidia-smi）时，系统都会新建一个控制台窗口。CREATE_NO_WINDOW 在
CreateProcess 阶段就告诉系统"别分配控制台"，比启动后再隐藏更彻底。
"""
import os
import subprocess

#: Windows: CREATE_NO_WINDOW；其它平台为 0
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def extra_kwargs():
    """返回需要附加给 subprocess 的参数。"""
    return {"creationflags": NO_WINDOW} if NO_WINDOW else {}


def run(cmd, **kwargs):
    merged = extra_kwargs()
    merged.update(kwargs)
    return subprocess.run(cmd, **merged)


def popen(cmd, **kwargs):
    merged = extra_kwargs()
    merged.update(kwargs)
    return subprocess.Popen(cmd, **merged)
