# -*- coding: utf-8 -*-
"""首次运行 / 缺少运行时的安装向导：调用 setup.ps1 并实时显示日志。"""
import os
import subprocess

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout)

from pplib.ffmpeg import ROOT

CREATE_NO_WINDOW = 0x08000000


def _decode(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk", "replace")
        except Exception:
            return data.decode("latin-1", "replace")


class InstallDialog(QDialog):
    finishedOk = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("安装运行时")
        self.resize(860, 560)
        self._proc = None
        self._ok = False

        lay = QVBoxLayout(self)
        tip = QLabel(
            "将执行项目自带的 <b>setup.ps1</b>：创建/复用 .venv、安装 PyTorch 与依赖、"
            "下载权重（约 190 MB）和 Real-CUGAN（约 45 MB）。<br>"
            "首次安装视网络需要 10~20 分钟，中途可以关闭窗口稍后重试（已下载部分会跳过）。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(8000)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.status = QLabel("准备中…")
        row.addWidget(self.status, 1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self._on_close)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.setModal(True)

    # ---------------------------------------------------------- 流程
    def start(self):
        setup = os.path.join(str(ROOT), "setup.ps1")
        if not os.path.isfile(setup):
            self._append("[错误] 找不到 setup.ps1：%s" % setup)
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            return
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyRead.connect(self._on_read)
        self._proc.finished.connect(self._on_finished)
        self._proc.setWorkingDirectory(str(ROOT))
        self._append("执行：powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1")
        self._proc.start("powershell",
                         ["-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", setup])
        self.status.setText("安装中…（可以先去忙别的，完成后会提示）")

    def _on_read(self):
        if not self._proc:
            return
        data = bytes(self._proc.readAll())
        if data:
            self._append(_decode(data).rstrip())

    def _on_finished(self, code, _status):
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if code == 0 else 0)
        if code == 0:
            self._ok = True
            self.status.setText("安装完成 ✔")
            self._append("\n===== 安装完成 =====")
            self.finishedOk.emit()
        else:
            self.status.setText("安装失败（退出码 %d），日志见 setup.log" % code)
            self._append("\n===== 安装失败（退出码 %d）=====" % code)

    def _append(self, text):
        if not text:
            return
        for line in text.splitlines():
            self.log.appendPlainText(line)

    def _on_close(self):
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            self.status.setText("仍在安装：可以关闭窗口，后台会继续；下次打开会自动跳过已完成步骤")
        self.accept()

    def is_ok(self):
        return self._ok
