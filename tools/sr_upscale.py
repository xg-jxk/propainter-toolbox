# -*- coding: utf-8 -*-
"""Real-CUGAN 视频超分（一键）

  python sr_upscale.py --video "D:\\v\\a.mp4"                 # 2x，保守降噪
  python sr_upscale.py --video "D:\\v\\a.mp4" --scale 3 --denoise 3
可选: --out --crf 17 --encoder auto|nvenc|x264 --model models-pro|models-se
      --workdir --log-file --keep
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

import cv2

from common import (ROOT as _ROOT, CUGAN_DIR as _CUGAN_DIR, ensure_out_writable,
                    encode_frames, find_ffmpeg, human_size, log, probe, run,
                    set_log_file)

REPO = str(_ROOT)
CUGAN_DIR = str(_CUGAN_DIR)
CUGAN = os.path.join(CUGAN_DIR, "realcugan-ncnn-vulkan.exe")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3],
                    help="不给就自动：高度<720 用 3（强降噪），否则用 0（保守）")
    ap.add_argument("--model", default="models-pro")
    ap.add_argument("--out")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--preset", default=None, help="x264 预设，默认 medium")
    ap.add_argument("--workdir", help="临时目录位置（默认系统临时目录；建议指到大盘）")
    ap.add_argument("--log-file", dest="log_file")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    if a.log_file:
        set_log_file(a.log_file)

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit("找不到视频: %s" % video)
    for p in (CUGAN, find_ffmpeg()):
        if not os.path.isfile(p):
            raise SystemExit("缺少: %s（先跑 setup.cmd）" % p)
    model_dir = os.path.join(CUGAN_DIR, a.model)
    if not os.path.isdir(model_dir):
        raise SystemExit("Real-CUGAN 模型目录不存在: %s（可先跑 setup.cmd 重新下载）" % model_dir)

    name = os.path.splitext(os.path.basename(video))[0]
    out = a.out or os.path.join(os.path.dirname(video), "%s_%dx.mp4" % (name, a.scale))
    ensure_out_writable(out)
    t0 = time.time()

    if a.workdir:
        os.makedirs(a.workdir, exist_ok=True)
    job = tempfile.mkdtemp(prefix="ppsr_", dir=a.workdir or None)
    fdir, udir = os.path.join(job, "in"), os.path.join(job, "up")
    os.makedirs(fdir)
    os.makedirs(udir)

    try:
        log("1/3 抽帧 ...")
        fps, has_audio, src_dur = probe(video)
        if not (5.0 <= fps <= 240.0):
            raise SystemExit("读不到合理的帧率（%s），请确认源文件是否完整" % fps)
        # fps 滤镜归一化：VFR 源不会变速
        run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", video,
             "-vf", "fps=%g" % fps, "-start_number", "0",
             os.path.join(fdir, "%05d.png")])
        n = len(os.listdir(fdir))
        if n == 0:
            raise SystemExit("抽帧结果为空：磁盘满或 ffmpeg 解码失败")
        first = cv2.imread(os.path.join(fdir, "00000.png"), cv2.IMREAD_GRAYSCALE)
        if first is None:
            raise SystemExit("读不到抽出的第一帧")
        h = first.shape[0]
        if a.denoise is None:
            a.denoise = 3 if h < 720 else 0
        log("    %d 帧, 高 %d, %g fps, 音轨 %s, denoise=%d"
            % (n, h, fps, "有" if has_audio else "无", a.denoise))
        if src_dur and abs(n / fps - src_dur) > max(0.5, 0.05 * src_dur):
            log("    [警告] 抽帧 %d 张 ≈ %.2fs，与源时长 %.2fs 不一致" % (n, n / fps, src_dur))

        log("2/3 Real-CUGAN 放大 %dx（denoise=%d, %s）..." % (a.scale, a.denoise, a.model))
        t = time.time()
        run([CUGAN, "-i", fdir, "-o", udir, "-f", "png", "-s", str(a.scale),
             "-n", str(a.denoise), "-m", a.model], cwd=CUGAN_DIR)
        dt = time.time() - t
        log("    完成 %.0fs（%.2fs/帧）" % (dt, dt / max(1, n)))
        ups = sorted(os.listdir(udir))
        if len(ups) < n:
            raise SystemExit("放大结果缺失：%d/%d 张（%s）。可能是磁盘满、Real-CUGAN 中途退出，"
                             "或该临时目录被清理工具删除" % (len(ups), n, udir))

        log("3/3 编码 ...")
        encode_frames(udir, video, out, fps, n, has_audio,
                      encoder=a.encoder, crf=a.crf, preset=a.preset)
    finally:
        if a.keep:
            log("中间文件: %s" % job)
        else:
            shutil.rmtree(job, ignore_errors=True)

    dur_out = probe(out)[2]
    if dur_out and abs(dur_out - n / fps) > 0.3:
        log("    [警告] 输出时长 %.2fs != 预期 %.2fs，请检查源视频是否为可变帧率"
            % (dur_out, n / fps))
    log("完成: %s (%s, 总用时 %.0fs)" % (out, human_size(os.path.getsize(out)), time.time() - t0))


if __name__ == "__main__":
    main()
