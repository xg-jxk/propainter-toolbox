# -*- coding: utf-8 -*-
"""日志、子进程错误映射、安装进度解析的单元测试。"""
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class AppLogTest(unittest.TestCase):
    def test_writes_rotating_file(self):
        import logging
        from app.core import applog
        d = tempfile.mkdtemp(prefix="pplog_")
        path = applog.setup(d)
        self.assertTrue(path and os.path.isfile(path))
        applog.write("hello log\n第二行")
        logger = logging.getLogger("protoolbox")
        for h in logger.handlers:
            h.flush()
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("hello log", text)
        self.assertIn("第二行", text)

    def test_write_without_setup_is_noop(self):
        from app.core import applog
        applog.write("no crash")      # 不应抛异常


class SpawnErrorTest(unittest.TestCase):
    def test_missing_executable_is_readable(self):
        from pplib import winproc
        with self.assertRaises(winproc.SpawnError) as ctx:
            winproc.run(["definitely-not-a-real-binary-xyz.exe"])
        msg = str(ctx.exception)
        self.assertIn("definitely-not-a-real-binary-xyz.exe", msg)
        if os.name == "nt":
            self.assertIn("找不到可执行文件", msg)


class InstallProgressTest(unittest.TestCase):
    def test_step_regex(self):
        from app.ui.install_dialog import _STEP_RE
        m = _STEP_RE.search("[3/7] 下载 PyTorch ...")
        self.assertIsNotNone(m)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (3, 7))
        self.assertIsNone(_STEP_RE.search("普通日志，没有进度"))


if __name__ == "__main__":
    unittest.main()
