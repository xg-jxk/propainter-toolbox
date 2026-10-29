# -*- coding: utf-8 -*-
"""去水印 + 超分 一条龙

  python pipeline.py --video "D:\\v\\a.mp4"                 # 去水印 -> 2x
  python pipeline.py --video "D:\\v\\a.mp4" --scale 3
  python pipeline.py --video "D:\\v\\a.mp4" --rect 1314,918,320,120
可选: --denoise -1|0|1|2|3  --out  --keep
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

from common import ROOT as _ROOT

REPO = str(_ROOT)
PY = sys.executable
WM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wm_remove.py")
SR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sr_upscale.py")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def call(cmd):
    # 直接继承 stdout/stderr，能看到两个脚本的实时进度
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"步骤失败（退出码 {rc}）: {os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--rect", help="不给就自动检测水印")
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3])
    ap.add_argument("--out")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit(f"找不到视频: {video}")
    for p in (PY, WM, SR):
        if not os.path.isfile(p):
            raise SystemExit(f"缺少: {p}")

    name = os.path.splitext(os.path.basename(video))[0]
    out_dir = os.path.dirname(video)
    final = a.out or os.path.join(out_dir, f"{name}_无水印_{a.scale}x.mp4")
    job = tempfile.mkdtemp(prefix="ppline_")
    clean = os.path.join(job, "clean.mp4")   # 中间文件用 crf 0（无损），不吃画质
    t0 = time.time()

    log("步骤 1/2  去水印 ...")
    cmd = [PY, WM, "--video", video, "--out", clean, "--crf", "0"]
    cmd += (["--rect", a.rect] if a.rect else ["--auto"])
    call(cmd)

    log("步骤 2/2  超分 ...")
    cmd = [PY, SR, "--video", clean, "--scale", str(a.scale), "--out", final]
    if a.denoise is not None:
        cmd += ["--denoise", str(a.denoise)]
    call(cmd)

    if a.keep:
        log(f"中间文件: {job}")
    else:
        shutil.rmtree(job, ignore_errors=True)
    log(f"完成: {final}  (总用时 {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
