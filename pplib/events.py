# -*- coding: utf-8 -*-
"""进度 / 日志 / 取消的统一事件模型。

两种消费方式：
  - 命令行：sink 为 None，事件直接人读打印（progress 事件静默，避免刷屏）
  - GUI：sink 由 jsonl_sink() 提供，把每个事件序列化成一行 JSON 写进管道
"""
import json
import sys
import threading
import time


class Cancelled(Exception):
    """用户取消了任务。"""


class JobError(Exception):
    """可预期的失败；hint 会展示给用户当建议。"""

    def __init__(self, msg, hint=None):
        Exception.__init__(self, msg)
        self.hint = hint


def _log_line(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _human_sink(obj):
    t = obj.get("t")
    if t == "log":
        print(obj.get("msg", ""), flush=True)
    elif t == "stage":
        print("[%s] == %s ==" % (time.strftime("%H:%M:%S"), obj.get("name", "")), flush=True)
    elif t == "done":
        size = obj.get("size")
        size_txt = "" if size is None else "，%s" % _fmt(size)
        print("[%s] 完成：%s%s（用时 %.0fs）"
              % (time.strftime("%H:%M:%S"), obj.get("out") or "", size_txt,
                 obj.get("elapsed") or 0), flush=True)
    elif t == "error":
        sys.stderr.write("[错误] %s\n" % obj.get("msg", ""))
        if obj.get("hint"):
            sys.stderr.write("       %s\n" % obj["hint"])
        sys.stderr.flush()
    elif t == "cancelled":
        sys.stderr.write("已取消\n")
        sys.stderr.flush()


def _fmt(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


human_sink = _human_sink


def jsonl_sink(stream=None):
    """返回一个把事件写成 JSONL 的 sink（线程安全）。"""
    stream = stream or sys.stdout
    lock = threading.Lock()

    def sink(obj):
        line = json.dumps(obj, ensure_ascii=False)
        with lock:
            stream.write(line + "\n")
            stream.flush()

    return sink


class Emitter(object):
    def __init__(self, sink=None):
        self._sink = sink or _human_sink
        self._cancel = threading.Event()
        self._stage = ""
        self._pct = 0.0
        self._stage_t0 = time.time()
        self._t0 = time.time()

    # ---------------------------------------------------------- 取消
    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def check_cancel(self):
        if self._cancel.is_set():
            raise Cancelled()

    # ---------------------------------------------------------- 事件
    def _emit(self, obj):
        try:
            self._sink(obj)
        except Exception:
            pass

    def log(self, msg):
        self._emit({"t": "log", "msg": "[%s] %s" % (time.strftime("%H:%M:%S"), msg)})

    def stage(self, name, pct=None):
        self._stage = name
        self._stage_t0 = time.time()
        if pct is not None:
            self._pct = max(self._pct, float(pct))
        self._emit({"t": "stage", "name": name, "pct": round(self._pct, 1)})
        self.check_cancel()

    def total_pct(self, pct, name=None):
        """推进整体进度（不改变当前阶段的计时基准）。"""
        self._pct = max(self._pct, float(pct))
        self._emit({"t": "stage", "name": name or self._stage, "pct": round(self._pct, 1)})
        self.check_cancel()

    def progress(self, cur, total, note=""):
        total = max(1, int(total))
        cur = max(0, min(int(cur), total))
        elapsed = max(1e-6, time.time() - self._stage_t0)
        rate = cur / elapsed
        eta = int((total - cur) / rate) if rate > 0 else None
        self._emit({"t": "progress", "cur": cur, "total": total,
                    "pct": round(self._pct, 1), "rate": round(rate, 2),
                    "eta": eta, "note": note})
        self.check_cancel()

    def done(self, out=None, size=None, elapsed=None, extra=None):
        self._emit({"t": "done", "out": out, "size": size,
                    "elapsed": round(time.time() - self._t0 if elapsed is None else elapsed, 1),
                    "extra": extra or {}})

    def error(self, msg, hint=None):
        self._emit({"t": "error", "msg": str(msg), "hint": hint})

    def cancelled_event(self):
        self._emit({"t": "cancelled"})


def tee_sink(*sinks):
    """把事件同时分发给多个 sink（例如 GUI 管道 + 日志文件）。"""
    sinks = [s for s in sinks if s]

    def sink(obj):
        for s in sinks:
            try:
                s(obj)
            except Exception:
                pass

    return sink


def file_sink(path):
    """把 log 事件追加进文件（进度事件忽略，避免文件爆炸）。"""
    handle = open(path, "a", encoding="utf-8", errors="ignore")

    def sink(obj):
        if obj.get("t") in ("log", "error", "done", "cancelled"):
            handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
            handle.flush()

    sink.handle = handle
    return sink


def cli_emitter(log_file=None):
    """命令行用的 Emitter：人读输出，可选同时写日志文件。"""
    if not log_file:
        return Emitter()
    return Emitter(tee_sink(human_sink, file_sink(log_file)))


class ScaledEmitter(object):
    """把子任务的 0-100 进度映射到整体区间（pipeline 串联两步时用）。"""

    def __init__(self, inner, lo, hi):
        self.inner = inner
        self.lo = float(lo)
        self.hi = float(hi)

    def _map(self, pct):
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return None
        return self.lo + (self.hi - self.lo) * max(0.0, min(100.0, pct)) / 100.0

    # --- 取消：直接委托
    def cancel(self):
        self.inner.cancel()

    @property
    def cancelled(self):
        return self.inner.cancelled

    def check_cancel(self):
        self.inner.check_cancel()

    # --- 事件
    def log(self, msg):
        self.inner.log(msg)

    def stage(self, name, pct=None):
        self.inner.stage(name, None if pct is None else self._map(pct))

    def total_pct(self, pct, name=None):
        self.inner.total_pct(self._map(pct), name)

    def progress(self, cur, total, note=""):
        self.inner.progress(cur, total, note)

    def done(self, out=None, size=None, elapsed=None, extra=None):
        self.inner.done(out, size, elapsed, extra)

    def error(self, msg, hint=None):
        self.inner.error(msg, hint)

    def cancelled_event(self):
        self.inner.cancelled_event()
