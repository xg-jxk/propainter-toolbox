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


class SpawnError(RuntimeError):
    """启动子进程失败时的可读错误。"""

    def __init__(self, cmd, exc, hint=""):
        self.cmd = cmd
        self.orig = exc
        self.hint = hint
        super().__init__("无法启动 %s：%s%s" % (
            _name(cmd), exc, ("（%s）" % hint) if hint else ""))

    def __str__(self):
        return super().__str__()


def _name(cmd):
    try:
        return str(cmd[0]) if isinstance(cmd, (list, tuple)) else str(cmd)
    except Exception:
        return "子进程"


_WIN_HINTS = {
    2: "找不到可执行文件，可能需要先安装运行时",
    3: "路径不存在",
    5: "权限不足，可能被杀毒软件或安全策略拦截",
    32: "文件被占用",
    740: "需要管理员权限",
    193: "不是有效的可执行文件",
}


def _hint(exc):
    winerror = getattr(exc, "winerror", None)
    if winerror in _WIN_HINTS:
        return _WIN_HINTS[winerror]
    return _WIN_HINTS.get(getattr(exc, "errno", None), "")


def extra_kwargs():
    """返回需要附加给 subprocess 的参数。"""
    return {"creationflags": NO_WINDOW} if NO_WINDOW else {}


def run(cmd, **kwargs):
    merged = extra_kwargs()
    merged.update(kwargs)
    try:
        return subprocess.run(cmd, **merged)
    except OSError as e:
        raise SpawnError(cmd, e, _hint(e)) from e


def popen(cmd, **kwargs):
    merged = extra_kwargs()
    merged.update(kwargs)
    try:
        return subprocess.Popen(cmd, **merged)
    except OSError as e:
        raise SpawnError(cmd, e, _hint(e)) from e
