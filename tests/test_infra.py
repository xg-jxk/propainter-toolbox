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


class FfmpegResolveTest(unittest.TestCase):
    """打包后的 exe 里 imageio_ffmpeg 被排除了，定位 ffmpeg 不能只靠 import。"""

    def test_venv_binary_lookup(self):
        from pplib import ffmpeg as ffmod
        venv = os.path.join(ROOT, ".venv")
        if not os.path.isdir(venv):
            self.skipTest("没有 .venv")
        got = ffmod._venv_ffmpeg()
        if not got:
            self.skipTest(".venv 里没有 imageio-ffmpeg 的二进制")
        self.assertTrue(os.path.isfile(got))
        self.assertIn(".venv", got)

    def test_find_ffmpeg_without_imageio_import(self):
        """模拟冻结版：import imageio_ffmpeg 失败也要能找到 ffmpeg。"""
        import builtins
        from pplib import ffmpeg as ffmod

        real_import = builtins.__import__
        old = ffmod._ffmpeg

        def _blocked(name, *args, **kwargs):
            if name == "imageio_ffmpeg":
                raise ImportError("imageio_ffmpeg 被 PyInstaller excludes 排除")
            return real_import(name, *args, **kwargs)

        ffmod._ffmpeg = None
        builtins.__import__ = _blocked
        try:
            path = ffmod.find_ffmpeg(allow_import=False)
            self.assertTrue(os.path.isfile(path))
        finally:
            builtins.__import__ = real_import
            ffmod._ffmpeg = old

    def test_probe_size_explains_failure(self):
        """读不到分辨率时要给出原因，而不是只回 (0, 0)。"""
        from pplib.ffmpeg import probe_size, probe_size_ex
        missing = os.path.join(tempfile.mkdtemp(prefix="ppmiss_"), "nope.mp4")
        self.assertEqual(probe_size(missing), (0, 0))
        w, h, why = probe_size_ex(missing)
        self.assertEqual((w, h), (0, 0))
        self.assertTrue(why)
        self.assertIn("ffmpeg", why)


class BitrateCapTest(unittest.TestCase):
    """体积上限：crf 越小给得越松，按分辨率线性放大，并有上下夹紧。"""

    def test_bpp_monotonic(self):
        from pplib import ffmpeg as ffmod
        values = [ffmod.cap_bpp(c) for c in (10, 14, 17, 20, 23, 28, 40)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertAlmostEqual(ffmod.cap_bpp(14), 0.12)
        self.assertGreaterEqual(min(values), 0.008)
        self.assertLessEqual(max(values), 0.18)

    def test_maxrate_scales_with_pixels(self):
        from pplib.ffmpeg import target_maxrate
        self.assertEqual(target_maxrate(0, 0, 30, 17), 0)          # 未知分辨率 = 不限制
        small = target_maxrate(854, 480, 30, 17)
        big = target_maxrate(3416, 1920, 30, 17)
        self.assertGreater(big, small * 10)                        # 像素 16 倍
        self.assertGreaterEqual(small, 1.5e6)                      # 下限夹紧
        self.assertLessEqual(target_maxrate(7680, 4320, 60, 14), 60e6)   # 上限夹紧
        # 实测：4x(crf14) 不限码率是 58 Mbps；封顶后应落在 20~30 Mbps
        self.assertTrue(20e6 <= target_maxrate(3416, 1920, 30, 14) <= 30e6)

    def test_encode_args_carry_maxrate(self):
        from pplib.ffmpeg import video_encode_args
        nv = video_encode_args("h264_nvenc", 17, None, 5000000)
        self.assertIn("-maxrate", nv)
        self.assertEqual(nv[nv.index("-maxrate") + 1], "5000000")
        self.assertEqual(nv[nv.index("-bufsize") + 1], "10000000")
        self.assertIn("-cq", nv)
        x264 = video_encode_args("libx264", 20, "veryfast", 4000000)
        self.assertIn("-crf", x264)
        self.assertIn("-maxrate", x264)
        self.assertNotIn("-maxrate", video_encode_args("libx264", 20, None, 0))

    def test_options_parse_cap_size(self):
        from pplib.options import RepairOptions, SROptions
        self.assertTrue(RepairOptions.from_dict({}).cap_size)
        self.assertFalse(RepairOptions.from_dict({"cap_size": False}).cap_size)
        self.assertTrue(SROptions.from_dict({}).cap_size)
        self.assertFalse(SROptions.from_dict({"cap_size": 0}).cap_size)


class ConfigMigrateTest(unittest.TestCase):
    """旧配置一次性迁移：目标回 1080p、预设改名、crf 归三档、删掉不再暴露的键。"""

    def test_old_config_migrates(self):
        from app.core.config import migrate
        old = {"sr_target": "max", "preset": "quality", "crf": 14,
               "denoise": "3", "subvideo": 80, "mask_dilation": 2,
               "detect_thr": 0.62, "ref_stride": 12, "sr_max_output": 0,
               "encoder": "nvenc", "keep": True}
        new = migrate(dict(old))
        self.assertEqual(new["sr_target"], "1080p")
        self.assertEqual(new["preset"], "detail")
        self.assertEqual(new["crf"], 17)
        self.assertEqual(new["denoise"], "3")
        for key in ("subvideo", "mask_dilation", "detect_thr", "ref_stride",
                    "sr_max_output", "encoder", "keep"):
            self.assertNotIn(key, new)

    def test_migrate_is_idempotent(self):
        from app.core.config import migrate
        once = migrate({"crf": 22, "sr_target": "8K", "ui_version": 2})
        self.assertEqual(once["crf"], 22)      # 已经迁过的不再动
        self.assertEqual(once["sr_target"], "8K")

    def test_denoise_zero_folds_into_weak(self):
        from app.core.config import migrate
        self.assertEqual(migrate({"denoise": "0"})["denoise"], "1")


class OomRetryTest(unittest.TestCase):
    """显存不足：分段减半重试，清理本段残留，最多重试 2 次。"""

    class _Emit(object):
        def __init__(self):
            self.lines = []

        def log(self, text):
            self.lines.append(str(text))

    def test_retry_halves_subvideo(self):
        from pplib import repair
        from pplib.events import JobError
        from pplib.options import RepairOptions

        calls = {"n": 0, "subs": []}
        real = repair._run_inference

        def fake(seg, seg_dir, opts, emit, base, total):
            calls["n"] += 1
            calls["subs"].append(opts.subvideo)
            if calls["n"] <= 2:
                raise JobError("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB")
            return "res_dir"

        repair._run_inference = fake
        try:
            d = tempfile.mkdtemp(prefix="ppoom_")
            emit = self._Emit()
            res, used = repair._infer_with_retry(
                {"frames": [0, 1]}, d, RepairOptions(subvideo=40), emit, 0, 2)
            self.assertEqual(res, "res_dir")
            self.assertEqual(used.subvideo, 10)          # 40 → 20 → 10
            self.assertEqual(calls["subs"], [40, 20, 10])
            self.assertEqual(sum(1 for x in emit.lines if "显存不足" in x), 2)
        finally:
            repair._run_inference = real

    def test_non_oom_error_is_raised(self):
        from pplib import repair
        from pplib.events import JobError
        from pplib.options import RepairOptions

        real = repair._run_inference

        def fake(*args, **kwargs):
            raise JobError("文件损坏")

        repair._run_inference = fake
        try:
            with self.assertRaises(JobError):
                repair._infer_with_retry({"frames": [0]},
                                         tempfile.mkdtemp(prefix="ppn_"),
                                         RepairOptions(), self._Emit(), 0, 1)
        finally:
            repair._run_inference = real


class CleanupTest(unittest.TestCase):
    """清理缓存：scan 找到的东西，sweep 必须删得掉（曾经只扫系统 temp）。"""

    def _fake_residue(self, root):
        d = os.path.join(root, "ppwm_testdir")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "a.bin"), "wb") as fh:
            fh.write(b"x" * 4096)
        stray = os.path.join(root, "ppcmd_test.log")
        with open(stray, "wb") as fh:
            fh.write(b"y" * 128)
        keep = os.path.join(root, "user_file.txt")
        with open(keep, "wb") as fh:
            fh.write(b"z")
        return d, stray, keep

    def test_scan_and_sweep_agree(self):
        from pplib import cleanup
        root = tempfile.mkdtemp(prefix="ppcl_")
        d, stray, keep = self._fake_residue(root)
        found = cleanup.scan(root)
        names = {os.path.basename(p) for p, _s, _m in found}
        self.assertIn("ppwm_testdir", names)
        self.assertIn("ppcmd_test.log", names)
        self.assertNotIn("user_file.txt", names)

        n, freed = cleanup.sweep(max_age_hours=0, root=root)
        self.assertEqual(n, 2)
        self.assertGreaterEqual(freed, 4096)
        self.assertFalse(os.path.exists(d))
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(os.path.exists(keep), "非本程序的临时文件不能删")

    def test_default_root_matches_scan(self):
        """root=None 时 sweep 必须和 scan 扫同一组目录（应用 temp + 系统 temp）。"""
        from pplib import cleanup
        root = tempfile.mkdtemp(prefix="ppcl2_")
        d, _stray, _keep = self._fake_residue(root)
        real = cleanup._roots
        cleanup._roots = lambda r=None: [r] if r else [root, tempfile.gettempdir()]
        try:
            n, _freed = cleanup.sweep(max_age_hours=0)      # 不传 root
        finally:
            cleanup._roots = real
        self.assertGreaterEqual(n, 2, "默认 root 必须覆盖应用 temp 目录")
        self.assertFalse(os.path.exists(d))

    def test_recent_files_survive_24h_sweep(self):
        from pplib import cleanup
        root = tempfile.mkdtemp(prefix="ppcl3_")
        d, _stray, _keep = self._fake_residue(root)
        n, _freed = cleanup.sweep(max_age_hours=24, root=root)
        self.assertEqual(n, 0, "刚写的残留不该被 24h 规则删掉")
        self.assertTrue(os.path.isdir(d))


if __name__ == "__main__":
    unittest.main()
