# -*- coding: utf-8 -*-
"""界面冒烟测试：离屏构建主窗口，确认没有导入/布局异常。

没有安装 PySide6 时自动跳过（命令行用户不需要它）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "未安装 PySide6")
class AppSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_window_builds(self):
        from app.ui.mainwindow import MainWindow
        win = MainWindow()
        self.assertIn("ProPainter", win.windowTitle())
        self.assertEqual(win.table.columnCount(), 5)
        self.assertEqual(win.queue_label.text(), "0 / 20")
        win.close()

    def test_queue_cap_in_ui(self):
        import tempfile

        from app.ui.mainwindow import MainWindow
        tmp = tempfile.mkdtemp(prefix="ppui_")
        paths = []
        for i in range(23):
            p = os.path.join(tmp, "v%02d.mp4" % i)
            with open(p, "wb") as fh:
                fh.write(b"0")
            paths.append(p)
        win = MainWindow()
        added, rejected = win.queue.add_paths(paths)
        self.assertEqual(len(added), 20)
        self.assertEqual(len(rejected), 3)
        win.close()

    def test_spec_build(self):
        from app.ui.mainwindow import MainWindow
        win = MainWindow()
        spec = win._build_spec(r"D:\v\a.mp4")
        self.assertEqual(spec["mode"], "repair")
        self.assertTrue(spec["repair"]["auto"])
        self.assertEqual(spec["sr"]["scale"], 2)
        win.close()

    def test_terms_dialog_gate(self):
        from app.ui.terms_dialog import TermsDialog
        dlg = TermsDialog(require_accept=True)
        self.assertFalse(dlg.btn_ok.isEnabled())      # 未勾选不能继续
        dlg.check.setChecked(True)
        self.assertTrue(dlg.btn_ok.isEnabled())
        dlg.close()

    def test_terms_dialog_view_mode(self):
        from app.ui.terms_dialog import TermsDialog
        dlg = TermsDialog(require_accept=False)
        self.assertTrue(dlg.btn_ok.isEnabled())
        self.assertFalse(dlg.check.isVisible())
        dlg.close()

if __name__ == "__main__":
    unittest.main()
