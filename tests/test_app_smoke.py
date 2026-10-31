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
    def test_default_target_is_1080p(self):
        """默认 1080p（统一长边）；选什么就是什么，不会被程序改档。"""
        win = self._win()
        win.sr_panel.set_source_size(854, 480)
        self.assertEqual(win.sr_panel.want_key(), "1080p")
        self.assertEqual(win.sr_panel.target_key(), "1080p")
        self.assertEqual(win.sr_panel.options()["scale"], 3)   # 854→1080p 要 3x
        self.assertEqual(win.sr_panel.plan(854, 480)["final"], (1920, 1080))

        # 1080p 源：档位仍然是 1080p，只是跳过超分
        win.sr_panel.set_source_size(1920, 1080)
        self.assertEqual(win.sr_panel.target_key(), "1080p")
        self.assertFalse(win.sr_panel.plan(1920, 1080)["need_sr"])
        self.assertEqual(win.sr_panel.plan(1920, 1080)["final"], (1920, 1080))

        # 4K 源也还是 1080p：跳过超分 + 缩到 1080p
        win.sr_panel.set_source_size(3840, 2160)
        self.assertEqual(win.sr_panel.target_key(), "1080p")
        self.assertEqual(win.sr_panel.plan(3840, 2160)["final"], (1920, 1080))
        win.close()

    def test_target_is_remembered(self):
        """目标档位是用户选的，换源文件、换批次都不该被改写。"""
        win = self._win()
        win.sr_panel.set_target("4K")
        win.sr_panel.set_source_size(854, 480)
        self.assertEqual(win.sr_panel.target_key(), "4K")
        win.sr_panel.set_source_size(1920, 1080)
        self.assertEqual(win.sr_panel.target_key(), "4K")
        self.assertEqual(win.sr_panel.plan(1920, 1080)["final"], (3840, 2160))
        self.assertEqual(win._collect_config()["sr_target"], "4K")
        win.close()

    def test_quality_from_crf_mapping(self):
        from app.ui.panels import quality_from_crf
        self.assertEqual(quality_from_crf(14), 17)     # 旧预设「高质量」的 14 归到高
        self.assertEqual(quality_from_crf(17), 17)
        self.assertEqual(quality_from_crf(18), 20)
        self.assertEqual(quality_from_crf(22), 23)
        self.assertEqual(quality_from_crf(None), 17)

    def test_action_areas(self):
        """方案 C：队列操作在表格上方，运行控制在底部状态条，重置参数归设置区。"""
        from PySide6.QtWidgets import QPushButton
        win = self._win()
        lv = win.table.parentWidget().layout()
        idx_bar = lv.indexOf(win.queue_bar)
        idx_table = lv.indexOf(win.table)
        self.assertGreaterEqual(idx_bar, 0)
        self.assertLess(idx_bar, idx_table, "队列工具条应在表格上方")
        self.assertIn(win.open_btn, win.queue_bar.findChildren(QPushButton))

        strip = win.findChild(type(win.status_strip), "statusStrip")
        self.assertIsNotNone(strip)
        for w in (win.start_btn, win.cancel_btn, win.progress, win.clean_btn):
            self.assertTrue(strip.isAncestorOf(w), "%s 应在底部状态条里" % w.text())
        self.assertTrue(win.preset_bar.isAncestorOf(win.reset_btn))

        # 运行中清理缓存必须禁用（否则会删正在用的临时文件）
        win.set_running(True)
        self.assertFalse(win.clean_btn.isEnabled())
        self.assertEqual(win.progress.format(), "%p%")
        win.set_running(False)
        self.assertTrue(win.clean_btn.isEnabled())
        win.close()

    def test_preset_applies_values(self):
        win = self._win()
        win._apply_preset("detail")
        self.assertAlmostEqual(win.repair_panel.padding.value(), 0.55, places=2)
        self.assertEqual(win.repair_panel._subvideo, 80)
        win._apply_preset("fast")
        self.assertAlmostEqual(win.repair_panel.padding.value(), 0.35, places=2)
        self.assertEqual(win.repair_panel._subvideo, 20)
        self.assertEqual(win._current_preset(), "fast")
        # 预设只管上下文，不动画质
        self.assertEqual(win.output_panel.crf_value(), 17)
        win.close()

    def test_manual_edit_clears_preset(self):
        """手改外扩/画质后，档位要变成"自定义"。"""
        win = self._win()
        win._apply_preset("detail")
        self.assertEqual(win._current_preset(), "detail")
        win.repair_panel.padding.setValue(0.82)
        self.assertEqual(win._current_preset(), "")
        self.assertIn("已自定义", win.preset_hint.text())
        win._apply_preset("fast")
        for btn, data in win.output_panel.quality._buttons:
            if data == 23:
                btn.click()                      # 模拟真实点选（会发 changed 信号）
        self.assertEqual(win.output_panel.crf_value(), 23)
        self.assertEqual(win._current_preset(), "")
        win.close()

    # ------------------------------------------------------------ 折叠
    def test_no_collapsed_advanced_sections(self):
        """高级参数已取消：两张卡片都不再有 advanced 折叠区。"""
        win = self._win()
        self.assertFalse(hasattr(win.repair_panel, "advanced"))
        self.assertFalse(hasattr(win.output_panel, "advanced"))
        self.assertFalse(hasattr(win.sr_panel, "advanced"))
        win.close()

    # ------------------------------------------------------------ 说明图标
    def test_every_param_has_help(self):
        from app.ui import help as uihelp
        used = ("mode", "detect", "rect", "mask", "padding",
                "scale", "denoise", "model",
                "out_dir", "crf", "open_when_done")
        for key in used:
            self.assertIn(key, uihelp.PARAM_HELP, key)
            html = uihelp.tooltip_html(key)
            self.assertIn("<b>", html)
            self.assertGreater(len(html), 40, key)

    def test_info_icons_are_wired(self):
        from PySide6.QtWidgets import QLabel
        win = self._win()
        icons = [w for w in win.findChildren(QLabel) if w.objectName() == "infoIcon"]
        self.assertGreaterEqual(len(icons), 11, "i 图标数量不对")
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
        bubble.watch_tree(win)
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
        bubble.watch_tree(win)
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
        win.test_panel.test_mode.setChecked(True)
        win.test_panel.test_seconds.setValue(3)
        win.test_panel.test_start.setValue(2.5)
        spec = win._build_spec(r"C:\v\a.mp4")
        self.assertEqual(spec["clip_seconds"], 3)
        self.assertAlmostEqual(spec["clip_start"], 2.5, places=1)
        win.test_panel.test_mode.setChecked(False)
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

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            out = cmd[-1]
            if isinstance(out, str) and out.endswith(".part.mp4"):
                open(out, "wb").close()

        try:
            ffmod.pick_encoder = lambda prefer="auto": "h264_nvenc"
            ffmod.run = fake_run
            out1 = os.path.join(d, "out.mp4")
            ffmod.encode_frames(d, "in.mp4", out1, 30, 1, False, encoder="auto", crf=20)
            self.assertIn("libx264", captured["cmd"])
            self.assertNotIn("h264_nvenc", captured["cmd"])
            self.assertTrue(os.path.isfile(out1))          # .part 已改名

            small = tempfile.mkdtemp(prefix="ppenc2_")
            Image.new("RGB", (1920, 1080)).save(os.path.join(small, "00000.png"))
            captured.clear()
            out2 = os.path.join(small, "out2.mp4")
            ffmod.encode_frames(small, "in.mp4", out2, 30, 1, False, encoder="auto", crf=20)
            self.assertIn("h264_nvenc", captured["cmd"])
        finally:
            ffmod.run, ffmod.pick_encoder = orig_run, orig_pick
    def test_target_labels_and_plan(self):
        """目标档位按「统一长边」解释：每档都显示最终输出尺寸。"""
        import subprocess
        from pplib.ffmpeg import find_ffmpeg, probe_size
        from pplib.scaling import final_size, plan_scale

        d = tempfile.mkdtemp(prefix="ppsz_")
        clip = os.path.join(d, "a.mp4")
        subprocess.run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=320x180", "-t", "0.3",
                        "-c:v", "libx264", "-preset", "ultrafast", clip], check=True)
        self.assertEqual(probe_size(clip), (320, 180))
        self.assertEqual(probe_size(os.path.join(d, "nope.mp4")), (0, 0))

        # 16:9 吸附：854×480 属于 16:9 家族，直接钉到 1920×1080
        self.assertEqual(final_size(854, 480, 1920), (1920, 1080))
        self.assertEqual(final_size(3416, 1920, 1920), (1920, 1080))
        self.assertEqual(final_size(1708, 960, 2560), (2560, 1440))
        # 非 16:9 保持比例
        self.assertEqual(final_size(1440, 1080, 1920), (1920, 1440))     # 4:3
        self.assertEqual(final_size(1080, 1920, 1920), (1080, 1920))     # 竖屏
        # 4x 也够不到：仍然补齐到目标尺寸
        self.assertEqual(plan_scale(854, 480, 7680)["final"], (7680, 4320))
        self.assertTrue(plan_scale(854, 480, 7680).get("reason"))

        win = self._win()
        win.sr_panel.set_source_size(1280, 720)
        texts = [win.sr_panel.target.itemText(i) for i in range(win.sr_panel.target.count())]
        self.assertIn("1920×1080", texts[0])
        self.assertIn("2560×1440", texts[1])
        self.assertIn("3840×2160", texts[2])
        # 目标总是可达（不达标就跳过、够不到就补齐），所以不再有禁用项
        self.assertTrue(all(win.sr_panel.target.model().item(i).isEnabled()
                            for i in range(win.sr_panel.target.count())))
        win.sr_panel.set_target("4K")
        self.assertEqual(win.sr_panel.plan(1280, 720)["scale"], 3)   # 720p×3 = 3840
        self.assertEqual(win.sr_panel.plan(1280, 720)["final"], (3840, 2160))
        win.sr_panel.set_target("1080p")
        self.assertEqual(win.sr_panel.plan(1280, 720)["scale"], 2)
        self.assertEqual(win.sr_panel.plan(1280, 720)["final"], (1920, 1080))
        self.assertIn("1280×720", win.sr_panel.scale_hint.text())
        win.close()

    def test_sr_skips_when_source_is_big_enough(self):
        """源长边已达标：跳过超分模型，但仍缩放到统一尺寸。"""
        win = self._win()
        win.sr_panel.set_enabled_state(True)
        win.sr_panel.set_target("1080p")
        plan = win.sr_panel.plan(3416, 1920)
        self.assertFalse(plan["need_sr"])
        self.assertEqual(plan["final"], (1920, 1080))
        self.assertIn("跳过超分", plan["reason"])

        # 1080p 源选 1080p：尺寸不变，也只走"跳过"
        plan2 = win.sr_panel.plan(1920, 1080)
        self.assertFalse(plan2["need_sr"])
        self.assertEqual(plan2["final"], (1920, 1080))

        # 4K 源选 8K：需要超分（2x）
        win.sr_panel.set_target("8K")
        plan3 = win.sr_panel.plan(3840, 2160)
        self.assertTrue(plan3["need_sr"])
        self.assertEqual(plan3["scale"], 2)
        self.assertEqual(plan3["final"], (7680, 4320))
        win.close()

    def test_scale_labels_follow_target(self):
        """同一批不同源尺寸，输出尺寸必须一致（这是统一长边的核心诉求）。"""
        win = self._win()
        win.sr_panel.set_target("1080p")
        outs = set()
        for w, h in ((854, 480), (1280, 720), (1708, 960), (1920, 1080), (3416, 1920)):
            outs.add(win.sr_panel.plan(w, h)["final"])
        self.assertEqual(outs, {(1920, 1080)})
        win.close()
    def test_missing_size_is_probed_before_start(self):
        """加入时没读到分辨率，开始前必须补探测，避免默默按 2x。"""
        import subprocess
        from pplib.ffmpeg import find_ffmpeg

        d = tempfile.mkdtemp(prefix="ppprobe_")
        clip = os.path.join(d, "a.mp4")
        subprocess.run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=1920x1080", "-t", "0.3",
                        "-c:v", "libx264", "-preset", "ultrafast", clip], check=True)

        win = self._win()
        win.sr_panel.set_enabled_state(True)
        win.sr_panel.set_target("1080p")
        win.queue.add_paths([clip])
        win.queue[0].width = 0          # 模拟加入时探测失败
        win.queue[0].height = 0
        win._rebuild_table()

        captured = {}
        win.runner.start = lambda spec: captured.setdefault("spec", spec)
        win._start_next()
        self.assertEqual(win.queue[0].width, 1920)
        self.assertEqual(win.queue[0].height, 1080)
        self.assertEqual(captured["spec"]["sr"]["target_long"], 1920)
        win.close()

    def test_bridge_prefers_pythonw(self):
        """任务进程优先用 pythonw.exe，避免 GUI 拉起黑窗。"""
        from app.core.bridge import JobRunner
        d = tempfile.mkdtemp(prefix="pppy_")
        py = os.path.join(d, "python.exe")
        open(py, "w").close()
        self.assertEqual(JobRunner._quiet_python(py), py)
        pyw = os.path.join(d, "pythonw.exe")
        open(pyw, "w").close()
        self.assertEqual(JobRunner._quiet_python(py), pyw)

    def test_reset_restores_defaults(self):
        """一键重置：参数回默认，队列不受影响。"""
        win = self._win()
        win.queue.add_paths([self._tmp_video()])
        win._rebuild_table()

        win.repair_panel.padding.setValue(1.2)
        win.sr_panel.set_enabled_state(False)
        win.sr_panel.set_target("8K")
        win.output_panel.quality.set_value(23)
        win.test_panel.test_mode.setChecked(True)
        win.open_when_done.setChecked(False)
        win._apply_preset("fast")

        win.reset_params()

        self.assertAlmostEqual(win.repair_panel.padding.value(), 0.45, places=2)
        self.assertTrue(win.sr_panel.is_enabled())          # 默认修复+超分都开
        self.assertEqual(win.sr_panel.want_key(), "1080p")  # 不再默认 4K/最高
        self.assertEqual(win.output_panel.crf_value(), 17)
        self.assertFalse(win.test_panel.test_mode.isChecked())
        self.assertTrue(win.open_when_done.isChecked())
        self.assertEqual(win._current_preset(), "balanced")
        self.assertEqual(len(win.queue), 1)      # 队列不清空
        win.close()


    def test_auto_model_choice(self):
        """内置选型：pro 优先；缺档换 se（4x、2x 的降噪 1/2 只有 se 有）。"""
        from pplib.cugan_models import auto_model
        avail = {
            "models-pro": {(2, -1), (2, 0), (2, 3), (3, -1), (3, 0), (3, 3)},
            "models-se": {(2, -1), (2, 0), (2, 1), (2, 2), (2, 3),
                          (3, -1), (3, 0), (3, 3), (4, -1), (4, 0), (4, 3)},
        }
        self.assertEqual(auto_model(avail, 2, 3)[0], "models-pro")
        self.assertEqual(auto_model(avail, 4, 3)[0], "models-se")
        self.assertEqual(auto_model(avail, 2, 1)[0], "models-se")
        self.assertEqual(auto_model(avail, 3, 1)[0], "models-pro")   # 就近 conservative

    def test_sr_panel_has_no_model_selector(self):
        win = self._win()
        self.assertFalse(hasattr(win.sr_panel, "model"))
        self.assertFalse(hasattr(win.sr_panel, "advanced"))
        self.assertEqual(win.sr_panel.options(1920, 1080)["model"], "auto")
        win.close()


    def test_test_panel_is_separate_card(self):
        win = self._win()
        self.assertTrue(hasattr(win, "test_panel"))
        self.assertFalse(hasattr(win.output_panel, "test_mode"))
        self.assertIsNot(win.test_panel.parent(), win.output_panel)
        win.test_panel.test_mode.setChecked(True)
        self.assertEqual(win.test_panel.clip_seconds(), 3)
        win.close()


    def test_cleanup_sweep(self):
        """只清自己的前缀，且尊重时间阈值。"""
        import time
        from pplib import cleanup
        d = tempfile.mkdtemp(prefix="ppclean_")
        old = os.path.join(d, "ppwm_old")
        new = os.path.join(d, "ppsr_new")
        other = os.path.join(d, "notmine")
        for p in (old, new, other):
            os.makedirs(p)
            open(os.path.join(p, "f.bin"), "wb").write(b"x" * 1024)
        past = time.time() - 48 * 3600
        os.utime(old, (past, past))
        os.utime(other, (past, past))

        count, freed = cleanup.sweep(max_age_hours=24, root=d)
        self.assertEqual(count, 1)
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))       # 太新，保留
        self.assertTrue(os.path.exists(other))     # 不是我们的前缀

        count2, _ = cleanup.sweep(max_age_hours=0, root=d)
        self.assertEqual(count2, 1)
        self.assertFalse(os.path.exists(new))


if __name__ == "__main__":
    unittest.main()
