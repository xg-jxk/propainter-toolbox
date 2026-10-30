# -*- coding: utf-8 -*-
"""Real-CUGAN 超分流程：抽帧 → 放大 → 编码。"""
import os
import re
import shutil
import sys
import tempfile
import time

import cv2

from .events import Cancelled, JobError
from .ffmpeg import (CUGAN_DIR, CUGAN_EXE, dir_size, encode_frames,
                     ensure_out_writable, extract_frames, human_size, probe,
                     run_stream)

PCT_EXTRACT = (2.0, 15.0)
PCT_UPSCALE = (15.0, 88.0)
PCT_ENCODE = (88.0, 100.0)

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def check_cugan():
    if not os.path.isfile(str(CUGAN_EXE)):
        raise JobError("找不到 Real-CUGAN：%s" % CUGAN_EXE,
                       "先运行 setup.cmd，或在桌面应用里点「安装运行时」")


def run_sr(video, opts, emit, out=None, final=True):
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        raise JobError("找不到视频：%s" % video)
    opts.validate()
    check_cugan()

    model_dir = os.path.join(str(CUGAN_DIR), opts.model)
    if not os.path.isdir(model_dir):
        raise JobError("Real-CUGAN 模型目录不存在：%s" % model_dir,
                       "重新运行 setup.cmd 下载 Real-CUGAN")

    from .options import default_out
    out = out or default_out(video, "sr", opts.scale)
    ensure_out_writable(out)

    t0 = time.time()
    job = tempfile.mkdtemp(prefix="ppsr_")
    fdir, udir = os.path.join(job, "in"), os.path.join(job, "up")
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(udir, exist_ok=True)
    wdir = os.path.join(job, "work")
    try:
        emit.stage("探测视频", 1)
        fps, has_audio, src_dur = probe(video)
        emit.log("%s · %g fps · 音轨%s" % (os.path.basename(video), fps,
                                          "有" if has_audio else "无"))

        emit.stage("抽帧", PCT_EXTRACT[0])
        extract_frames(video, fdir, fps, src_dur, emit=emit,
                       pct_from=PCT_EXTRACT[0], pct_to=PCT_EXTRACT[1])
        n = len(os.listdir(fdir))
        first = cv2.imread(os.path.join(fdir, "00000.png"), cv2.IMREAD_GRAYSCALE)
        if first is None:
            raise JobError("读不到抽出的第一帧")
        h = first.shape[0]
        denoise = opts.denoise
        if denoise is None:
            denoise = 3 if h < 720 else 0
        emit.log("%d 帧 · 高 %d · denoise=%d · 模型 %s" % (n, h, denoise, opts.model))

        emit.stage("超分 %dx" % opts.scale, PCT_UPSCALE[0])
        cmd = [str(CUGAN_EXE), "-i", fdir, "-o", udir, "-f", "png",
               "-s", str(opts.scale), "-n", str(denoise), "-m", opts.model]

        def on_line(line):
            m = _PCT_RE.search(line)
            if m:
                frac = max(0.0, min(1.0, float(m.group(1)) / 100.0))
                pct = PCT_UPSCALE[0] + (PCT_UPSCALE[1] - PCT_UPSCALE[0]) * frac
                emit.total_pct(pct, "超分 %dx" % opts.scale)
                emit.progress(int(frac * n), n, "超分")
            elif line.strip() and len(line.strip()) < 200:
                emit.log("    " + line.strip())

        t_up = time.time()
        try:
            run_stream(cmd, on_line, cwd=str(CUGAN_DIR), emit=emit, label="Real-CUGAN 放大")
        except JobError as e:
            raise JobError(str(e), "显存不足时把 scale 从 3/4 降到 2；"
                                   "或确认显卡驱动支持 Vulkan")
        dt = time.time() - t_up
        emit.log("放大完成 %.0fs（%.2fs/帧）" % (dt, dt / max(1, n)))

        ups = sorted(os.listdir(udir))
        if len(ups) < n:
            raise JobError("放大结果缺失：%d/%d 张" % (len(ups), n),
                           "可能是磁盘满或 Real-CUGAN 中途退出")

        emit.stage("编码", PCT_ENCODE[0])
        encode_frames(udir, video, out, fps, n, has_audio,
                      encoder=opts.encoder, crf=opts.crf, preset=opts.preset, emit=emit)
        emit.total_pct(PCT_ENCODE[1])

        dur_out = probe(out)[2]
        if dur_out and abs(dur_out - n / fps) > 0.3:
            emit.log("[警告] 输出时长 %.2fs != 预期 %.2fs" % (dur_out, n / fps))

        size = os.path.getsize(out) if os.path.isfile(out) else None
        result = {"out": out, "size": size, "elapsed": time.time() - t0, "frames": n}
        if final:
            emit.done(out=out, size=size, elapsed=result["elapsed"],
                      extra={"frames": n, "scale": opts.scale})
        return result
    except Cancelled:
        raise
    except JobError:
        raise
    except Exception as e:
        raise JobError("%s: %s" % (type(e).__name__, e))
    finally:
        if opts.keep:
            emit.log("中间文件：%s（%s）" % (job, human_size(dir_size(job))))
        else:
            shutil.rmtree(job, ignore_errors=True)
