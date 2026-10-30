# -*- coding: utf-8 -*-
"""事件模型单测：取消、进度映射、JSONL 输出格式。"""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import (Cancelled, Emitter, JobError, ScaledEmitter,  # noqa: E402
                          jsonl_sink)


class EmitterTest(unittest.TestCase):
    def setUp(self):
        self.buf = io.StringIO()
        self.events = []
        self.emit = Emitter(sink=lambda obj: (self.events.append(obj),
                                              self.buf.write(json.dumps(obj, ensure_ascii=False) + "\n")))

    def test_cancel(self):
        self.emit.stage("x", 10)
        self.emit.cancel()
        with self.assertRaises(Cancelled):
            self.emit.check_cancel()

    def test_progress_monotonic_pct(self):
        self.emit.stage("抽帧", 5)
        self.emit.total_pct(10)
        self.emit.total_pct(5)          # 不允许回退
        self.emit.progress(5, 10, "抽帧")
        pcts = [e.get("pct") for e in self.events if e.get("t") == "stage"]
        self.assertEqual(pcts, [5.0, 10.0, 10.0])

    def test_error_event(self):
        self.emit.error("boom", "try this")
        last = self.events[-1]
        self.assertEqual(last["t"], "error")
        self.assertEqual(last["hint"], "try this")


class ScaledEmitterTest(unittest.TestCase):
    def test_mapping(self):
        events = []
        base = Emitter(sink=events.append)
        sub = ScaledEmitter(base, 50, 100)
        sub.stage("超分", 0)
        sub.total_pct(50)
        pcts = [e.get("pct") for e in events if e.get("t") == "stage"]
        self.assertEqual(pcts, [50.0, 75.0])

    def test_cancel_passthrough(self):
        base = Emitter(sink=lambda obj: None)
        sub = ScaledEmitter(base, 0, 50)
        sub.cancel()
        self.assertTrue(base.cancelled)
        with self.assertRaises(Cancelled):
            sub.check_cancel()


class JsonlSinkTest(unittest.TestCase):
    def test_format(self):
        buf = io.StringIO()
        emit = Emitter(jsonl_sink(buf))
        emit.log("中文日志")
        emit.total_pct(42.5)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        obj = json.loads(lines[0])
        self.assertEqual(obj["t"], "log")
        self.assertIn("中文日志", obj["msg"])
        self.assertEqual(json.loads(lines[1])["pct"], 42.5)


class JobErrorTest(unittest.TestCase):
    def test_hint(self):
        e = JobError("msg", "hint")
        self.assertEqual(str(e), "msg")
        self.assertEqual(e.hint, "hint")


if __name__ == "__main__":
    unittest.main()
