# -*- coding: utf-8 -*-
"""日志分隔行（pplib.logfmt）的单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib import logfmt  # noqa: E402


class StartLineTest(unittest.TestCase):
    def test_contains_index_and_name(self):
        line = logfmt.start_line(2, 5, "17c5da9c.mp4")
        self.assertIn("【2/5】", line)
        self.assertIn("17c5da9c.mp4", line)
        self.assertTrue(line.startswith(logfmt.SEP * 2))
        self.assertTrue(line.endswith(logfmt.SEP))

    def test_long_name_is_shortened(self):
        name = "a" * 60 + ".mp4"
        line = logfmt.start_line(1, 1, name)
        self.assertIn("…", line)
        self.assertLess(len(line), 120)

    def test_bar_without_text(self):
        self.assertEqual(logfmt.bar(), logfmt.SEP * logfmt.SEP_WIDTH)


class MetaLineTest(unittest.TestCase):
    def test_source_and_target(self):
        line = logfmt.meta_line(854, 480, 1920, 1080, preset="平衡", preview=True)
        self.assertIn("854×480 → 1920×1080", line)
        self.assertIn("平衡", line)
        self.assertIn("测试模式", line)

    def test_source_only(self):
        self.assertIn("854×480", logfmt.meta_line(854, 480))
        self.assertNotIn("→", logfmt.meta_line(854, 480))

    def test_empty(self):
        self.assertEqual(logfmt.meta_line(), "")


class EndLineTest(unittest.TestCase):
    def test_state_symbols(self):
        self.assertTrue(logfmt.end_line("done", "a.mp4").startswith("✔ 完成"))
        self.assertTrue(logfmt.end_line("skip", "a.mp4").startswith("⏭ 跳过"))
        self.assertTrue(logfmt.end_line("fail", "a.mp4").startswith("✘ 失败"))
        self.assertTrue(logfmt.end_line("cancel").startswith("⛔ 已取消"))

    def test_has_closing_bar(self):
        self.assertIn(logfmt.SEP * 8, logfmt.end_line("done"))

    def test_colors_differ(self):
        colors = {logfmt.state_style(s)[2] for s in ("done", "skip", "fail", "cancel")}
        self.assertEqual(len(colors), 4)


class QueueLineTest(unittest.TestCase):
    def test_uses_double_bar(self):
        line = logfmt.queue_line("开始处理 2 个文件（pipeline）")
        self.assertIn("开始处理 2 个文件", line)
        self.assertTrue(line.startswith("══"))
        self.assertTrue(line.endswith("═"))


if __name__ == "__main__":
    unittest.main()
