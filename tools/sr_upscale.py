# -*- coding: utf-8 -*-
"""Real-CUGAN 视频超分（一键）

  python sr_upscale.py --video "D:\\v\\a.mp4"                 # 2x，保守降噪
  python sr_upscale.py --video "D:\\v\\a.mp4" --scale 3 --denoise 3
可选: --out --crf 17 --model models-pro|models-se --keep
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from common import ROOT as _ROOT, find_ffmpeg

REPO = str(_ROOT)
CUGAN_DIR = os.path.join(REPO, "tools", "realcugan")
CUGAN = os.path.join(CUGAN_DIR, "realcugan-ncnn-vulkan.exe")
FFMPEG = find_ffmpeg()


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors="ignore")
    if p.returncode != 0:
        sys.stderr.write((p.stdout or "")[-2000:] + "\n" + (p.stderr or "")[-2000:])
        raise SystemExit(f"命令失败: {os.path.basename(cmd[0])}")
    return p


def probe(v):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", v], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, errors="ignore")
    info = p.stderr
    m = re.search(r"(\d+(?:\.\d+)?) fps", info)
    fps = float(m.group(1)) if m else 30.0
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else None
    return fps, ("Audio:" in info), dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--scale", type=int, default=2, choices=[2, 3, 4])
    ap.add_argument("--denoise", type=int, default=None, choices=[-1, 0, 1, 2, 3],
                    help="不给就自动：高度<720 用 3（强降噪），否则用 0（保守）")
    ap.add_argument("--model", default="models-pro")
    ap.add_argument("--out")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit(f"找不到视频: {video}")
    for p in (CUGAN, FFMPEG):
        if not os.path.isfile(p):
            raise SystemExit(f"缺少: {p}")

    name = os.path.splitext(os.path.basename(video))[0]
    out = a.out or os.path.join(os.path.dirname(video), f"{name}_{a.scale}x.mp4")
    t0 = time.time()
    job = tempfile.mkdtemp(prefix="ppsr_")
    fdir, udir = os.path.join(job, "in"), os.path.join(job, "up")
    os.makedirs(fdir)
    os.makedirs(udir)

    log("1/3 抽帧 ...")
    fps, has_audio, src_dur = probe(video)
    # fps 滤镜归一化：VFR 源不会变速
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video,
         "-vf", f"fps={fps:g}", "-start_number", "0", os.path.join(fdir, "%05d.png")])
    n = len(os.listdir(fdir))
    import cv2
    h = cv2.imread(os.path.join(fdir, "00000.png"), cv2.IMREAD_GRAYSCALE).shape[0]
    if a.denoise is None:
        a.denoise = 3 if h < 720 else 0
    log(f"    {n} 帧, 高 {h}, {fps:g} fps, 音轨 {'有' if has_audio else '无'}, denoise={a.denoise}")
    if src_dur and abs(n / fps - src_dur) > max(0.5, 0.05 * src_dur):
        log(f"    [警告] 抽帧 {n} 张 ≈ {n / fps:.2f}s，与源时长 {src_dur:.2f}s 不一致")

    log(f"2/3 Real-CUGAN 放大 {a.scale}x（denoise={a.denoise}, {a.model}）...")
    t = time.time()
    run([CUGAN, "-i", fdir, "-o", udir, "-f", "png", "-s", str(a.scale),
         "-n", str(a.denoise), "-m", a.model], cwd=CUGAN_DIR)
    dt = time.time() - t
    log(f"    完成 {dt:.0f}s（{dt / max(1, n):.2f}s/帧）")
    ups = sorted(os.listdir(udir))
    if len(ups) < n:
        raise SystemExit(f"放大结果缺失：{len(ups)}/{n} 张（{udir}）。"
                         f"可能是磁盘满、Real-CUGAN 中途退出，或该临时目录被清理工具删除。")

    log("3/3 编码 ...")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{fps:g}",
           "-i", os.path.join(udir, "%05d.png"), "-i", video, "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "1:a:0"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if has_audio:
        cmd += ["-c:a", "copy", "-t", f"{n / fps:.3f}"]
    cmd += [out]
    run(cmd)
    dur_out = probe(out)[2]
    if dur_out and abs(dur_out - n / fps) > 0.3:
        log(f"    [警告] 输出时长 {dur_out:.2f}s != 预期 {n / fps:.2f}s，"
            f"请检查源视频是否为可变帧率")

    if a.keep:
        log(f"    中间文件: {job}")
    else:
        shutil.rmtree(job, ignore_errors=True)
    log(f"完成: {out} ({os.path.getsize(out) / 1048576:.1f} MB, 总用时 {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
