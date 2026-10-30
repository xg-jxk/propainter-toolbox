# -*- coding: utf-8 -*-
"""任务描述校验 / 队列规则 / 默认输出命名的单测（不需要 GPU）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.events import JobError  # noqa: E402
from pplib.job import MAX_QUEUE, normalize_inputs, parse_spec  # noqa: E402
from pplib.options import default_out  # noqa: E402


class ParseSpecTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppspec_")
        self.video = os.path.join(self.tmp, "a.mp4")
        with open(self.video, "wb") as fh:
            fh.write(b"\x00" * 16)

    def test_minimal(self):
        spec = parse_spec({"video": self.video})
        self.assertEqual(spec.mode, "repair")
        self.assertTrue(spec.repair.auto)
        self.assertEqual(spec.sr.scale, 2)

    def test_mode(self):
        self.assertEqual(parse_spec({"mode": "sr", "video": self.video}).mode, "sr")
        self.assertEqual(parse_spec({"mode": "pipeline", "video": self.video}).mode, "pipeline")
        with self.assertRaises(JobError):
            parse_spec({"mode": "nope", "video": self.video})

    def test_missing_video(self):
        with self.assertRaises(JobError):
            parse_spec({"mode": "repair"})
        with self.assertRaises(JobError):
            parse_spec({"video": os.path.join(self.tmp, "nope.mp4")})

    def test_bad_params(self):
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "repair": {"padding": 9}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "repair": {"rect": "1,2,3"}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "repair": {"rect": "1,2,0,4"}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "repair": {"encoder": "vulkan"}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "sr": {"scale": 5}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "sr": {"denoise": 9}})
        with self.assertRaises(JobError):
            parse_spec({"video": self.video, "intermediate_crf": 99})

    def test_rect_ok(self):
        spec = parse_spec({"video": self.video, "repair": {"rect": "1314，918，320，120"}})
        self.assertEqual(spec.repair.rect, "1314，918，320，120")  # 全角逗号由 validate 兼容


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppqueue_")

    def _touch(self, name):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as fh:
            fh.write(b"\x00")
        return p

    def test_cap(self):
        paths = [self._touch("v%02d.mp4" % i) for i in range(MAX_QUEUE + 3)]
        accepted, rejected = normalize_inputs(paths)
        self.assertEqual(len(accepted), MAX_QUEUE)
        self.assertEqual(len(rejected), 3)
        self.assertIn("队列上限", rejected[0][1])

    def test_dedupe_and_ext(self):
        a = self._touch("x.mp4")
        b = self._touch("y.txt")
        accepted, rejected = normalize_inputs([a, a, b, os.path.join(self.tmp, "missing.mp4")])
        self.assertEqual(accepted, [os.path.abspath(a)])
        reasons = " ".join(r[1] for r in rejected)
        self.assertIn("不支持", reasons)
        self.assertIn("不存在", reasons)


class DefaultOutTest(unittest.TestCase):
    def test_names_and_dedupe(self):
        tmp = tempfile.mkdtemp(prefix="ppout_")
        video = os.path.join(tmp, "clip.mp4")
        open(video, "wb").close()
        first = default_out(video, "repair")
        self.assertTrue(first.endswith("clip_已修复.mp4"))
        open(first, "wb").close()
        second = default_out(video, "repair")
        self.assertTrue(second.endswith("clip_已修复(2).mp4"))
        self.assertTrue(default_out(video, "sr", 3).endswith("clip_3x.mp4"))
        self.assertTrue(default_out(video, "pipeline", 2).endswith("clip_已修复_2x.mp4"))


if __name__ == "__main__":
    unittest.main()
