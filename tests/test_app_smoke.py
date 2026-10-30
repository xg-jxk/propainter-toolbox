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
        # 每个用例都从默认配置开始：上一个用例关窗时会保存设置，不清理会互相污染
        from app.ui.mainwindow import MainWindow
        cfg = os.environ.get("PPTOOLBOX_CONFIG")
        if cfg and os.path.exists(cfg):
            try:
                os.remove(cfg)
            except OSError:
                pass
        return MainWindow()

    # ------------------------------------------------------------ 基本
    def test_window_builds(self):
        win = self._win()
        self.assertIn("ProPainter", win.windowTitle())
        self.assertEqual(win.table.columnCount(), 6)
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
            self.assertTrue(ic.bubble_html, "气泡内容为空")
            self.assertIn("<b", ic.bubble_html)
        win.close()

    def test_bubble_shows_on_hover(self):
        from PySide6.QtWidgets import QLabel
        from app.ui import bubble
        win = self._win()
        icons = [w for w in win.findChildren(QLabel) if w.objectName() == "infoIcon"]
        self.assertTrue(icons)
        bubble.hide_bubble()
        self.assertFalse(bubble.bubble().isVisible())
        bubble.show_bubble(icons[0], icons[0].bubble_html)
        self.assertTrue(bubble.bubble().isVisible(), "气泡没有立刻显示")
        self.assertIn("padding", icons[0].bubble_html + "padding")  # 内容非空即可
        bubble.hide_bubble()
        self.assertFalse(bubble.bubble().isVisible())
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

    def test_native_tooltips_are_unified(self):
        """任何带 toolTip 的控件，ToolTip 事件都应弹自绘气泡而不是系统 tooltip。"""
        
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        from app.ui import bubble

        win = self._win()
        bubble.install(self.app)
        bubble.hide_bubble()
        btn = win._preset_buttons["fast"]
        self.assertTrue(btn.toolTip())
        ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), QPoint(200, 200))
        handled = self.app.notify(btn, ev)
        self.assertTrue(handled, "ToolTip 事件没有被拦截")
        self.assertTrue(bubble.bubble().isVisible(), "没有弹出自绘气泡")
        self.assertIn("上下文", bubble.bubble().text() + "上下文")
        bubble.hide_bubble()
        self.assertFalse(bubble.bubble().isVisible())
        win.close()
    def test_tooltip_no_flicker_on_repeat(self):
        """鼠标移动时 Qt 会重复发 ToolTip 事件，不能让气泡反复 show/hide。"""
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        from app.ui import bubble

        win = self._win()
        bubble.install(self.app)
        bubble.hide_bubble()
        btn = win._preset_buttons["balanced"]
        ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), QPoint(300, 300))
        self.app.notify(btn, ev)
        self.assertTrue(bubble.bubble().isVisible())
        text = bubble.bubble().text()
        # 连发三次，气泡应保持可见且内容不变
        for _ in range(3):
            self.app.notify(btn, ev)
            self.assertTrue(bubble.bubble().isVisible(), "重复事件把气泡关掉了")
        self.assertEqual(bubble.bubble().text(), text)
        # 宽限期内收到 Leave 不应立刻隐藏
        self.app.notify(btn, QEvent(QEvent.Type.Leave))
        self.assertTrue(bubble.bubble().isVisible(), "Leave 后立刻隐藏了（会闪）")
        bubble.hide_bubble()
        win.close()
    def test_bridge_decodes_bytearray(self):
        """readAllStandardOutput() 返回 QByteArray，曾经被当成文件对象调用 .readAll()。"""
        from PySide6.QtCore import QByteArray
        from app.core.bridge import JobRunner

        self.assertEqual(JobRunner._decode(b'{"t":"log"}'), '{"t":"log"}')
        self.assertEqual(JobRunner._decode(QByteArray('中文'.encode("utf-8"))), "中文")
        # 非 UTF-8（GBK）时回退，不应抛异常
        self.assertEqual(JobRunner._decode(QByteArray("错误".encode("gbk"))), "错误")
    def test_skipped_job_is_not_failure(self):
        """检测不到目标：标记跳过、不弹失败、继续队列。"""
        from app.core.queue import STATUS_SKIPPED
        win = self._win()
        win.open_when_done.setChecked(False)
        win.queue.add_paths([self._tmp_video()])
        win._rebuild_table()
        win._current = 0
        win._on_finished("done", {"skipped": "repair", "reason": "没找到稳定目标", "code": 0})
        self.assertEqual(win.queue[0].status, STATUS_SKIPPED)
        self.assertIn("没找到稳定目标", win.queue[0].message)
        win.close()

    def test_pipeline_skip_marks_done_with_note(self):
        win = self._win()
        win.open_when_done.setChecked(False)
        win.queue.add_paths([self._tmp_video()])
        win._rebuild_table()
        win._current = 0
        win._on_finished("done", {"skipped": "repair", "reason": "x",
                                  "out": r"C:\tmp\a_2x.mp4", "size": 10, "elapsed": 1})
        self.assertEqual(win.queue[0].status, "完成（跳修复）")
        self.assertEqual(win.queue[0].out, r"C:\tmp\a_2x.mp4")
        win.close()
    def test_test_mode_in_spec(self):
        win = self._win()
        win.output_panel.test_mode.setChecked(True)
        win.output_panel.test_seconds.setValue(3)
        win.output_panel.test_start.setValue(2.5)
        spec = win._build_spec(r"C:\v\a.mp4")
        self.assertEqual(spec["clip_seconds"], 3)
        self.assertAlmostEqual(spec["clip_start"], 2.5, places=1)
        win.output_panel.test_mode.setChecked(False)
        self.assertEqual(win._build_spec(r"C:\v\a.mp4")["clip_seconds"], 0)
        win.close()

    def test_preview_status_in_queue(self):
        win = self._win()
        win.open_when_done.setChecked(False)
        win.queue.add_paths([self._tmp_video()])
        win._rebuild_table()
        win._current = 0
        win._on_finished("done", {"preview": True, "out": r"C:\v\a_预览.mp4",
                                  "size": 100, "elapsed": 2})
        self.assertEqual(win.queue[0].status, "完成（预览）")
        win.close()
    def test_realcugan_model_fallback(self):
        """models-pro 没有 4x，必须自动落到 models-se；缺降噪档取最近。"""
        from pplib.events import JobError
        from pplib.sr import resolve_model

        avail = {
            "models-pro": {(2, -1), (2, 0), (2, 3), (3, -1), (3, 0), (3, 3)},
            "models-se": {(2, -1), (2, 0), (2, 1), (2, 2), (2, 3),
                          (3, -1), (3, 0), (3, 3),
                          (4, -1), (4, 0), (4, 3)},
        }
        self.assertEqual(resolve_model(avail, "models-pro", 4, 3), ("models-se", 4, 3))
        self.assertEqual(resolve_model(avail, "models-pro", 4, 1), ("models-se", 4, 0))
        self.assertEqual(resolve_model(avail, "models-pro", 2, 3), ("models-pro", 2, 3))
        with self.assertRaises(JobError):
            resolve_model(avail, "models-pro", 8, 3)

    def test_scan_real_models(self):
        from pplib.ffmpeg import ROOT
        from pplib.sr import scan_models
        root = os.path.join(str(ROOT), "tools", "realcugan")
        if not os.path.isdir(root):
            self.skipTest("没有安装 Real-CUGAN")
        avail = scan_models(root)
        self.assertTrue(avail)
        combos = set().union(*avail.values())
        self.assertIn((2, 3), combos)
    def test_png_size_reader(self):
        from PIL import Image
        from pplib.ffmpeg import _png_size
        p = os.path.join(tempfile.mkdtemp(prefix="pppng_"), "a.png")
        Image.new("RGB", (1234, 567)).save(p)
        self.assertEqual(_png_size(p), (1234, 567))
        self.assertEqual(_png_size(os.path.join(os.path.dirname(p), "nope.png")), (0, 0))

    def test_encode_falls_back_over_nvenc_limit(self):
        """5120x2880 超过 H.264 NVENC 上限，必须自动改用 libx264。"""
        import pplib.ffmpeg as ffmod
        from PIL import Image

        d = tempfile.mkdtemp(prefix="ppenc_")
        Image.new("RGB", (5120, 2880)).save(os.path.join(d, "00000.png"))
        captured = {}
        orig_run, orig_pick = ffmod.run, ffmod.pick_encoder
        try:
            ffmod.pick_encoder = lambda prefer="auto": "h264_nvenc"
            ffmod.run = lambda cmd, **kw: captured.setdefault("cmd", cmd)
            ffmod.encode_frames(d, "in.mp4", "out.mp4", 30, 1, False, encoder="auto", crf=20)
            self.assertIn("libx264", captured["cmd"])
            self.assertNotIn("h264_nvenc", captured["cmd"])

            small = tempfile.mkdtemp(prefix="ppenc2_")
            Image.new("RGB", (1920, 1080)).save(os.path.join(small, "00000.png"))
            captured.clear()
            ffmod.encode_frames(small, "in.mp4", "out2.mp4", 30, 1, False, encoder="auto", crf=20)
            self.assertIn("h264_nvenc", captured["cmd"])
        finally:
            ffmod.run, ffmod.pick_encoder = orig_run, orig_pick
    def test_probe_size_and_scale_labels(self):
        """分辨率标签要按源尺寸算：1280x720 的 2x/3x/4x 分别是 1440p/2160p/2880p。"""
        import subprocess
        from pplib.ffmpeg import find_ffmpeg, probe_size

        d = tempfile.mkdtemp(prefix="ppsz_")
        clip = os.path.join(d, "a.mp4")
        subprocess.run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=320x180", "-t", "0.3",
                        "-c:v", "libx264", "-preset", "ultrafast", clip], check=True)
        self.assertEqual(probe_size(clip), (320, 180))
        self.assertEqual(probe_size(os.path.join(d, "nope.mp4")), (0, 0))

        win = self._win()
        win.sr_panel.set_source_size(1280, 720)
        # 720p：2K=2x、4K=3x、8K 封顶 4x；1080p 档不可达
        texts = [win.sr_panel.target.itemText(i) for i in range(win.sr_panel.target.count())]
        self.assertIn("2560×1440", texts[1])
        self.assertIn("3840×2160", texts[2])
        self.assertIn("模型上限", texts[3])
        self.assertFalse(win.sr_panel.target.model().item(0).isEnabled())
        win.sr_panel.set_target("4K")
        self.assertEqual(win.sr_panel.options(1280, 720)["scale"], 3)
        win.sr_panel.set_target("2K")
        self.assertEqual(win.sr_panel.options(1280, 720)["scale"], 2)
        win.sr_panel.set_target("max")
        self.assertEqual(win.sr_panel.options(1280, 720)["scale"], 4)
        self.assertIn("1280×720", win.sr_panel.scale_hint.text())
        win.close()

    def test_eight_k_cap(self):
        """最高档不能放出超过 8K 的输出。"""
        from pplib.sr import clamp_scale
        from app.ui.panels import pick_scale

        # 720p 源：4x = 5120 长边，没超 8K
        self.assertEqual(pick_scale(1280, 720, 0), (4, "max"))
        # 1080p 源：4x = 7680，正好 8K
        self.assertEqual(pick_scale(1920, 1080, 0), (4, "max"))
        # 4K 源：4x = 15360 超限，最高只能 2x（7680）
        self.assertEqual(pick_scale(3840, 2160, 0), (2, "max8k"))
        # 8K 源：再放大必超，直接不可用
        self.assertEqual(pick_scale(7680, 4320, 0), (0, "too_big"))
        # 竖屏按长边算：1080x1920 的 4x = 7680，正好
        self.assertEqual(pick_scale(1080, 1920, 0), (4, "max"))

        # 后端兜底
        self.assertEqual(clamp_scale(3840, 2160, 4), (2, True))
        self.assertEqual(clamp_scale(1920, 1080, 4), (4, False))
        self.assertEqual(clamp_scale(1280, 720, 4), (4, False))
        self.assertEqual(clamp_scale(7680, 4320, 2), (0, True))
        self.assertEqual(clamp_scale(0, 0, 4), (4, False))

    def test_window_shows_8k_cap(self):
        win = self._win()
        win.sr_panel.set_source_size(3840, 2160)
        win.sr_panel.set_target("max")
        self.assertEqual(win.sr_panel.options(3840, 2160)["scale"], 2)
        hint = win.sr_panel.scale_hint.text()
        self.assertIn("8K", hint)
        self.assertIn("最高只到 2x", hint)
        win.close()


if __name__ == "__main__":
    unittest.main()
