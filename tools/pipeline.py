# -*- coding: utf-8 -*-
"""去水印 + 超分 一条龙

  python pipeline.py --video "D:\\v\\a.mp4"                 # 去水印 -> 2x
  python pipeline.py --video "D:\\v\\a.mp4" --scale 3
  python pipeline.py --video "D:\\v\\a.mp4" --rect 1314,918,320,120
可选: --denoise -1|0|1|2|3  --out  --keep  --workdir  --log-file
      --encoder auto|nvenc|x264  --intermediate-crf 12
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

from common import (ROOT as _ROOT, ensure_out_writable, log, set_log_file)

REPO = str(_ROOT)
PY = sys.executable
_THIS = os.path.dirname(os.path.abspath(__file__))
WM = os.path.join(_THIS, "wm_remove.py")
SR = os.path.join(_THIS, "sr_upscale.py")


def call(cmd):
    """直接继承 stdout/stderr，能看到两个脚本的实时进度。"""
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit("步骤失败（退出码 %d）: %s"
                         % (rc, os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--rect", help="不给就自动检测水印")
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3])
    ap.add_argument("--out")
    ap.add_argument("--padding", type=float, default=None, help="透传给 wm_remove 的 --padding")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--intermediate-crf", type=int, default=12, dest="intermediate_crf",
                    help="去水印中间文件码率（默认 12，肉眼无损；0 是无损但文件巨大）")
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--workdir")
    ap.add_argument("--log-file", dest="log_file")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    if a.log_file:
        set_log_file(a.log_file)

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit("找不到视频: %s" % video)
    for p in (PY, WM, SR):
        if not os.path.isfile(p):
            raise SystemExit("缺少: %s" % p)

    name = os.path.splitext(os.path.basename(video))[0]
    out_dir = os.path.dirname(video)
    final = a.out or os.path.join(out_dir, "%s_无水印_%dx.mp4" % (name, a.scale))
    ensure_out_writable(final)

    if a.workdir:
        os.makedirs(a.workdir, exist_ok=True)
    job = tempfile.mkdtemp(prefix="ppline_", dir=a.workdir or None)
    clean = os.path.join(job, "clean.mp4")
    t0 = time.time()

    try:
        log("步骤 1/2  去水印 ...")
        cmd = [PY, WM, "--video", video, "--out", clean, "--crf", str(a.intermediate_crf)]
        cmd += (["--rect", a.rect] if a.rect else ["--auto"])
        if a.padding is not None:
            cmd += ["--padding", str(a.padding)]
        if a.encoder != "auto":
            cmd += ["--encoder", a.encoder]
        if a.log_file:
            cmd += ["--log-file", a.log_file]
        call(cmd)

        log("步骤 2/2  超分 ...")
        cmd = [PY, SR, "--video", clean, "--scale", str(a.scale), "--out", final,
               "--crf", str(a.crf)]
        if a.denoise is not None:
            cmd += ["--denoise", str(a.denoise)]
        if a.encoder != "auto":
            cmd += ["--encoder", a.encoder]
        if a.log_file:
            cmd += ["--log-file", a.log_file]
        call(cmd)
    finally:
        if a.keep:
            log("中间文件: %s" % job)
        else:
            shutil.rmtree(job, ignore_errors=True)

    log("完成: %s  (总用时 %.0fs)" % (final, time.time() - t0))


if __name__ == "__main__":
    main()
