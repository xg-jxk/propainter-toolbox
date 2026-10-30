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
    def test_ffmpeg_detection_without_imageio_import(self):
        # 打包后的 exe 里 import 不到 imageio_ffmpeg，只能靠路径定位
        from app.core import envcheck
        path = envcheck.find_ffmpeg_path(allow_import=False)
        if path is None:
            self.skipTest("本机 PATH/.venv 里都没有 ffmpeg 二进制")
        self.assertTrue(os.path.isfile(path), path)

    def test_runtime_check_shape(self):
        from app.core import envcheck
        st = envcheck.check()
        self.assertIsInstance(st.ready, bool)
        self.assertIsInstance(st.ffmpeg_ok, bool)
    def test_every_param_has_help(self):
        from app.ui import help as uihelp
        used = ("mode", "detect", "rect", "mask", "padding", "subvideo",
                "crf", "encoder", "scale", "denoise", "out_dir", "keep", "open_when_done")
        for key in used:
            self.assertIn(key, uihelp.PARAM_HELP, key)
            html = uihelp.tooltip_html(key)
            self.assertIn("<b>", html)
            self.assertGreater(len(html), 40, key)

    def test_info_icons_are_wired(self):
        from PySide6.QtWidgets import QLabel
        from app.ui.mainwindow import MainWindow
        win = MainWindow()
        icons = [w for w in win.findChildren(QLabel) if w.objectName() == "infoIcon"]
        self.assertEqual(len(icons), 13)
        for ic in icons:
            self.assertTrue(ic.toolTip(), "有 i 图标没挂 tooltip")
            self.assertEqual(ic.toolTipDuration(), 15000)
        win.close()

    def test_github_button(self):
        from app.ui import links
        from app.ui.mainwindow import MainWindow
        win = MainWindow()
        self.assertFalse(win.btn_github.icon().isNull())
        self.assertTrue(win.btn_github.toolTip())
        self.assertTrue(links.PROJECT_URL.startswith("https://github.com/xg-jxk/"))
        win.close()

    def test_subvideo_widget_in_layout(self):
        from app.ui.mainwindow import MainWindow
        win = MainWindow()
        self.assertIsNotNone(win.subvideo.parent())
        self.assertEqual(win.subvideo.minimum(), 10)
        win.close()

if __name__ == "__main__":
    unittest.main()
