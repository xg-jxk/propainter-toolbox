# -*- coding: utf-8 -*-
"""用 QProcess 执行 pplib.runner，把 JSONL 事件翻译成 Qt 信号。

单独起进程的好处：取消可以杀进程树立即生效，torch/CUDA 崩了也不会带走界面。
"""
import json
import os
import subprocess
import tempfile

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from pplib.ffmpeg import ROOT

CREATE_NO_WINDOW = 0x08000000


class JobRunner(QObject):
    started = Signal()
    logLine = Signal(str)
    stageChanged = Signal(str, float)
    progressChanged = Signal(int, int, float, int, str)
    finished = Signal(str, dict)      # state: done / failed / cancelled

    def __init__(self, python_exe, parent=None):
        super().__init__(parent)
        self.python_exe = python_exe
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._buf = ""
        self._spec_path = None
        self._cancelled = False
        self._result = {}
        self._error = None

    # ---------------------------------------------------------- 控制
    def is_running(self):
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def start(self, spec):
        fd, path = tempfile.mkstemp(prefix="ppjob_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False)
        self._spec_path = path
        self._buf = ""
        self._cancelled = False
        self._result = {}
        self._error = None

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        env.insert("PP_ROOT", str(ROOT))
        self._proc.setProcessEnvironment(env)
        self._proc.setWorkingDirectory(str(ROOT))
        self._proc.start(self.python_exe, ["-m", "pplib.runner", "--spec", path, "--jsonl"])
        self.started.emit()

    def cancel(self):
        self._cancelled = True
        if not self.is_running():
            return
        pid = int(self._proc.processId() or 0)
        if pid:
            try:  # Windows 上 QProcess.kill 只杀父进程，torch 的子进程会变孤儿
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW)
                return
            except Exception:
                pass
        self._proc.kill()

    # ---------------------------------------------------------- 事件
    @staticmethod
    def _decode(data, encoding="utf-8"):
        """QByteArray → str。原来误把 QByteArray 当文件对象调 .readAll()，
        每次读都抛 AttributeError，导致 runner 的日志/错误根本进不了界面。"""
        try:
            raw = bytes(data)
        except Exception:
            try:
                raw = bytes(data.data())
            except Exception:
                return ""
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            return raw.decode("gbk", "replace")

    def _on_stdout(self):
        self._buf += self._decode(self._proc.readAllStandardOutput())
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._dispatch(line)

    def _on_stderr(self):
        text = self._decode(self._proc.readAllStandardError()).strip()
        if text:
            self.logLine.emit(text)

    def _dispatch(self, line):
        try:
            obj = json.loads(line)
        except ValueError:
            self.logLine.emit(line)
            return
        if not isinstance(obj, dict):
            return
        kind = obj.get("t")
        if kind == "log":
            self.logLine.emit(obj.get("msg", ""))
        elif kind == "stage":
            self.stageChanged.emit(obj.get("name", ""), float(obj.get("pct") or 0.0))
        elif kind == "progress":
            self.progressChanged.emit(int(obj.get("cur") or 0), int(obj.get("total") or 0),
                                      float(obj.get("pct") or 0.0),
                                      int(obj.get("eta") or 0), obj.get("note") or "")
        elif kind == "done":
            self._result = obj
        elif kind == "error":
            self._error = obj
            msg = obj.get("msg", "")
            hint = obj.get("hint")
            self.logLine.emit("[错误] %s" % msg)
            if hint:
                self.logLine.emit("       %s" % hint)
        elif kind == "cancelled":
            self._cancelled = True

    def _on_finished(self, code, _status):
        # Windows 上 finished 可能早于最后一次 readyReadStandardOutput，
        # 不先把残留读干净，最后那条 error 事件就会丢（界面只剩「失败」）
        try:
            self._on_stdout()
            self._on_stderr()
        except Exception:
            pass
        self._cleanup()
        payload = dict(self._result or {})
        if self._error:
            payload.setdefault("msg", self._error.get("msg"))
            payload.setdefault("hint", self._error.get("hint"))
        payload["code"] = code
        if code not in (0, 3) and not payload.get("msg"):
            payload["msg"] = "任务进程异常退出（退出码 %d），详见日志" % code
        if self._cancelled or code == 3:
            state = "cancelled"
        elif code == 0:
            state = "done"
        else:
            state = "failed"
        self.finished.emit(state, payload)

    def _on_error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            self.logLine.emit("[错误] 无法启动任务进程：%s" % self.python_exe)
            self._cleanup()
            self.finished.emit("failed", {"msg": "任务进程启动失败", "code": -1})

    def _cleanup(self):
        if self._spec_path:
            try:
                os.remove(self._spec_path)
            except OSError:
                pass
            self._spec_path = None
