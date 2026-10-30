# -*- coding: utf-8 -*-
"""后台环境探测：避免启动时同步跑 nvidia-smi / ffmpeg 卡住首屏。"""
from PySide6.QtCore import QThread, Signal

from . import envcheck


class EnvProbe(QThread):
    done = Signal(object)      # RuntimeStatus

    def run(self):
        try:
            status = envcheck.check()
        except Exception:
            status = envcheck.RuntimeStatus()
        self.done.emit(status)
