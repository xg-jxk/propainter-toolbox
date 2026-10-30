# -*- coding: utf-8 -*-
"""首次运行 / 缺少运行时的安装向导：调用 setup.ps1 并实时显示日志。

用 subprocess + 线程读输出，而不是 QProcess：PySide6 没有暴露
setCreateProcessArgumentsModifier，无法给 QProcess 加 CREATE_NO_WINDOW，
拉起 powershell 时必然闪一个控制台窗口。
"""
import os
import re
import subprocess

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout)

from pplib import winproc
from pplib.ffmpeg import ROOT


def _decode(data):
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk", "replace")
        except Exception:
            return data.decode("latin-1", "replace")


_STEP_RE = re.compile(r"\[(\d+)\s*/\s*(\d+)\]")


class _SetupRunner(QThread):
    """后台跑 setup.ps1，逐行把输出发回界面。"""

    line = Signal(str)
    done = Signal(int)
    step = Signal(int, int)

    def __init__(self, cmd, cwd, parent=None):
        super().__init__(parent)
        self._cmd = cmd
        self._cwd = cwd
        self._proc = None

    def run(self):
        try:
            self._proc = winproc.popen(
                self._cmd, cwd=self._cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, bufsize=0)
        except Exception as e:
            self.line.emit("[错误] 无法启动安装进程：%s" % e)
            self.done.emit(-1)
            return
        try:
            for raw in iter(self._proc.stdout.readline, b""):
                text = _decode(raw).rstrip()
                if not text:
                    continue
                self.line.emit(text)
                m = _STEP_RE.search(text)
                if m:
                    self.step.emit(int(m.group(1)), int(m.group(2)))
        except Exception as e:
            self.line.emit("[错误] 读取安装输出失败：%s" % e)
        try:
            code = self._proc.wait(timeout=10)
        except Exception:
            code = -1
        self.done.emit(code)


class InstallDialog(QDialog):
    finishedOk = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("安装运行时")
        self.resize(860, 560)
        self._runner = None
        self._ok = False
        self._cancelled = False

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
        self.btn_cancel = QPushButton("取消安装")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row.addWidget(self.btn_cancel)
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
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-WindowStyle", "Hidden", "-File", setup]
        self._append("执行：powershell -NoProfile -ExecutionPolicy Bypass "
                     "-WindowStyle Hidden -File setup.ps1")
        self._runner = _SetupRunner(cmd, str(ROOT), self)
        self._runner.line.connect(self._append)
        self._runner.step.connect(self._on_step)
        self._runner.done.connect(self._on_done)
        self._runner.start()
        self.btn_cancel.setEnabled(True)
        self.status.setText("安装中…（可以先去忙别的，完成后会提示）")

    def cancel(self):
        """杀掉安装进程树（setup.ps1 会再拉起 python/curl）。"""
        proc = getattr(self._runner, "_proc", None)
        if proc is None or proc.poll() is not None:
            return False
        try:
            winproc.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            try:
                proc.kill()
                return True
            except Exception:
                return False

    def _on_step(self, cur, total):
        if total <= 0:
            return
        self.bar.setRange(0, total)
        self.bar.setValue(min(cur, total))

    def _on_done(self, code):
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if code == 0 else 0)
        self.btn_cancel.setEnabled(False)
        if self._cancelled and code != 0:
            self.status.setText("已取消安装（已下载的部分会保留）")
            self._append("\n===== 已取消 =====")
            return
        if code == 0:
            self._ok = True
            self.status.setText("安装完成 ✔")
            self._append("\n===== 安装完成 =====")
            self.finishedOk.emit()
        else:
            self.status.setText("安装失败（退出码 %d），日志见 setup.log" % code)
            self._append("\n===== 安装失败（退出码 %d）=====" % code)

    def _on_cancel(self):
        if self.cancel():
            self._cancelled = True
            self.status.setText("正在取消安装…（已下载的部分会保留）")
            self._append("[用户] 取消安装")
            self.btn_cancel.setEnabled(False)

    def _append(self, text):
        if not text:
            return
        for line in str(text).splitlines():
            self.log.appendPlainText(line)

    def _on_close(self):
        if self._runner is not None and self._runner.isRunning():
            self.status.setText("仍在安装：可以关闭窗口，后台会继续；下次打开会自动跳过已完成步骤")
        self.accept()

    def is_ok(self):
        return self._ok
