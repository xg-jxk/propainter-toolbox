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
from .const import temp_root, DEFAULT_MAX_OUTPUT_LONG
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



# Real-CUGAN 用「倍率 + 降噪档」决定模型文件名：up4x-denoise3x.param
from .cugan_models import (_DENOISE_CODE, _DENOISE_FILE, auto_model,  # noqa: F401
                           resolve_model, scan_models)


def clamp_scale(width, height, scale, limit=DEFAULT_MAX_OUTPUT_LONG):
    """按输出上限收紧倍率。返回 (实际倍率, 是否被收紧)；源本身超限返回 (0, True)。"""
    limit = DEFAULT_MAX_OUTPUT_LONG if limit is None else int(limit)
    if limit <= 0:
        return int(scale), False
    long_side = max(int(width or 0), int(height or 0))
    if long_side <= 0:
        return int(scale), False
    # 硬门槛：会超限就直接拒绝（返回 0），不再降档
    if long_side * int(scale) > limit:
        return 0, True
    return int(scale), False


def run_sr(video, opts, emit, out=None, final=True):
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        raise JobError("找不到视频：%s" % video)
    opts.validate()
    if getattr(opts, "skip_reason", None):
        reason = str(opts.skip_reason)
        emit.log("跳过超分：%s" % reason)
        result = {"skipped": True, "reason": reason, "out": None}
        if final:
            emit.done(out=None, size=None, elapsed=0.0,
                      extra={"skipped": "sr", "reason": reason})
        return result
    check_cugan()

    model_root = str(CUGAN_DIR)
    if not os.path.isdir(model_root):
        raise JobError("Real-CUGAN 模型目录不存在：%s" % model_root,
                       "重新运行 setup.cmd 下载 Real-CUGAN")
    available = scan_models(model_root)
    if not available:
        raise JobError("Real-CUGAN 一个模型都没找到：%s" % model_root,
                       "重新运行 setup.cmd 下载 Real-CUGAN")

    from .options import default_out
    out = out or default_out(video, "sr", opts.scale)
    ensure_out_writable(out)

    t0 = time.time()
    job = tempfile.mkdtemp(prefix="ppsr_", dir=temp_root())
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
        h, w = first.shape[0], first.shape[1]
        # 8K 上限：即使 CLI 传了过大的倍率，也不能放出超 8K 的输出
        long_side = max(w, h)
        cap = int(getattr(opts, "max_output_long", DEFAULT_MAX_OUTPUT_LONG) or 0)
        scale_use, blocked = clamp_scale(w, h, opts.scale, cap)
        if scale_use <= 0:
            reason = ("按 %dx 放大后长边会到 %d，超过输出上限 %d"
                      % (opts.scale, long_side * int(opts.scale), cap)
                      if cap else "无法按 %dx 放大" % opts.scale)
            emit.log("跳过超分：%s" % reason)
            result = {"skipped": True, "reason": reason, "out": None}
            if final:
                emit.done(out=None, size=None, elapsed=0.0,
                          extra={"skipped": "sr", "reason": reason})
            return result

        denoise = opts.denoise
        if denoise is None:
            denoise = 3 if h < 720 else 0
        # 按真实存在的文件挑组合，避免 ncnn 因 _wfopen 失败直接崩（0xC0000409）
        wanted = str(getattr(opts, "model", "auto") or "auto")
        if wanted == "auto" or wanted not in available:
            model_name, scale_used, denoise_used = auto_model(
                available, int(scale_use), int(denoise), emit)
        else:
            model_name, scale_used, denoise_used = resolve_model(
                available, wanted, int(scale_use), int(denoise), emit)
        denoise = denoise_used
        emit.log("%d 帧 · 高 %d · 模型 %s · %dx · 降噪 %d（%s）"
                 % (n, h, model_name, scale_used, denoise,
                    _DENOISE_FILE.get(denoise, str(denoise))))

        emit.stage("超分 %dx" % scale_used, PCT_UPSCALE[0])
        cmd = [str(CUGAN_EXE), "-i", fdir, "-o", udir, "-f", "png",
               "-s", str(scale_used), "-n", str(denoise), "-m", model_name]

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
            raise JobError(str(e), "若日志里有 _wfopen … failed，是模型文件缺失："
                                   "换个倍率/降噪，或重新运行 setup.cmd；"
                                   "否则多半是显存不足（把倍率降到 2）或驱动不支持 Vulkan")
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
