# -*- coding: utf-8 -*-
"""界面冒烟测试：离屏构建主窗口，确认布局、开关、预设、说明图标都正常。

没有安装 PySide6 时自动跳过（纯命令行用户不需要它）。
"""
import os
import sys
import tempfile
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
        # 隔离配置：测试不要动用户真实的 %LOCALAPPDATA% 配置
        cls._old_cfg = os.environ.get("PPTOOLBOX_CONFIG")
        cls._tmp_cfg = os.path.join(tempfile.mkdtemp(prefix="ppcfg_"), "config.json")
        os.environ["PPTOOLBOX_CONFIG"] = cls._tmp_cfg

    @classmethod
    def tearDownClass(cls):
        if cls._old_cfg is None:
            os.environ.pop("PPTOOLBOX_CONFIG", None)
        else:
            os.environ["PPTOOLBOX_CONFIG"] = cls._old_cfg

    def _win(self):
        from app.ui.mainwindow import MainWindow
        return MainWindow()

    # ------------------------------------------------------------ 基本
    def test_window_builds(self):
        win = self._win()
        self.assertIn("ProPainter", win.windowTitle())
        self.assertEqual(win.table.columnCount(), 5)
        self.assertEqual(win.queue_label.text(), "0 / 20")
        self.assertIsNotNone(win.repair_panel)
        self.assertIsNotNone(win.sr_panel)
        self.assertIsNotNone(win.output_panel)
        win.close()

    def test_queue_cap_in_ui(self):
        tmp = tempfile.mkdtemp(prefix="ppui_")
        paths = []
        for i in range(23):
            p = os.path.join(tmp, "v%02d.mp4" % i)
            with open(p, "wb") as fh:
                fh.write(b"0")
            paths.append(p)
        win = self._win()
        added, rejected = win.queue.add_paths(paths)
        self.assertEqual(len(added), 20)
        self.assertEqual(len(rejected), 3)
        win.close()

    # ------------------------------------------------------------ 两个开关
    def test_module_switches_decide_mode(self):
        win = self._win()
        win.repair_panel.set_enabled_state(True)
        win.sr_panel.set_enabled_state(False)
        self.assertEqual(win._mode(), "repair")
        win.sr_panel.set_enabled_state(True)
        self.assertEqual(win._mode(), "pipeline")
        win.repair_panel.set_enabled_state(False)
        self.assertEqual(win._mode(), "sr")
        win.sr_panel.set_enabled_state(False)
        self.assertIsNone(win._mode())
        win.close()

    def test_no_module_disables_start(self):
        win = self._win()
        win.queue.add_paths([self._tmp_video()])
        win._refresh_queue_label()
        win.repair_panel.set_enabled_state(False)
        win.sr_panel.set_enabled_state(False)
        win._on_modules_changed()
        self.assertFalse(win.start_btn.isEnabled())
        self.assertIn("至少启用", win.status_label.text())
        win.repair_panel.set_enabled_state(True)
        win._on_modules_changed()
        self.assertTrue(win.start_btn.isEnabled())
        win.close()

    def test_spec_reflects_switches(self):
        win = self._win()
        win.repair_panel.set_enabled_state(True)
        win.sr_panel.set_enabled_state(True)
        spec = win._build_spec(r"D:\v\a.mp4")
        self.assertEqual(spec["mode"], "pipeline")
        self.assertTrue(spec["repair"]["auto"])
        self.assertEqual(spec["sr"]["scale"], 2)
        win.sr_panel.set_enabled_state(False)
        spec2 = win._build_spec(r"D:\v\a.mp4")
        self.assertEqual(spec2["mode"], "repair")
        win.close()

    # ------------------------------------------------------------ 预设
    def test_preset_applies_values(self):
        win = self._win()
        win._apply_preset("quality")
        self.assertAlmostEqual(win.repair_panel.padding.value(), 0.55, places=2)
        self.assertEqual(win.repair_panel.subvideo.value(), 80)
        self.assertEqual(win.output_panel.crf_value(), 14)
        win._apply_preset("fast")
        self.assertAlmostEqual(win.repair_panel.padding.value(), 0.35, places=2)
        self.assertEqual(win.output_panel.crf_value(), 22)
        self.assertEqual(win._current_preset(), "fast")
        win.close()

    # ------------------------------------------------------------ 折叠
    def test_advanced_collapsed_by_default(self):
        win = self._win()
        self.assertFalse(win.repair_panel.advanced.is_expanded())
        self.assertFalse(win.sr_panel.advanced.is_expanded())
        self.assertFalse(win.advanced_visible() if hasattr(win, "advanced_visible") else False)
        win.close()

    # ------------------------------------------------------------ 说明图标
    def test_every_param_has_help(self):
        from app.ui import help as uihelp
        used = ("mode", "detect", "rect", "mask", "padding", "subvideo",
                "mask_dilation", "detect_thr", "ref_stride",
                "scale", "denoise", "model",
                "out_dir", "crf", "encoder", "keep", "open_when_done")
        for key in used:
            self.assertIn(key, uihelp.PARAM_HELP, key)
            html = uihelp.tooltip_html(key)
            self.assertIn("<b>", html)
            self.assertGreater(len(html), 40, key)

    def test_info_icons_are_wired(self):
        from PySide6.QtWidgets import QLabel
        win = self._win()
        icons = [w for w in win.findChildren(QLabel) if w.objectName() == "infoIcon"]
        self.assertGreaterEqual(len(icons), 15, "i 图标数量不对")
        for ic in icons:
            self.assertTrue(ic.toolTip(), "有 i 图标没挂 tooltip")
            self.assertEqual(ic.toolTipDuration(), 15000)
        win.close()

    # ------------------------------------------------------------ GitHub
    def test_github_button(self):
        from app.ui import links
        win = self._win()
        self.assertFalse(win.btn_github.icon().isNull())
        self.assertTrue(win.btn_github.toolTip())
        self.assertTrue(links.PROJECT_URL.startswith("https://github.com/xg-jxk/"))
        win.close()

    # ------------------------------------------------------------ 条款
    def test_terms_dialog_gate(self):
        from app.ui.terms_dialog import TermsDialog
        dlg = TermsDialog(require_accept=True)
        self.assertFalse(dlg.btn_ok.isEnabled())
        dlg.check.setChecked(True)
        self.assertTrue(dlg.btn_ok.isEnabled())
        dlg.close()

    def test_terms_dialog_view_mode(self):
        from app.ui.terms_dialog import TermsDialog
        dlg = TermsDialog(require_accept=False)
        self.assertTrue(dlg.btn_ok.isEnabled())
        self.assertFalse(dlg.check.isVisible())
        dlg.close()

    # ------------------------------------------------------------ 工具
    def _tmp_video(self):
        tmp = tempfile.mkdtemp(prefix="ppui_vid_")
        p = os.path.join(tmp, "a.mp4")
        with open(p, "wb") as fh:
            fh.write(b"0")
        return p


if __name__ == "__main__":
    unittest.main()
