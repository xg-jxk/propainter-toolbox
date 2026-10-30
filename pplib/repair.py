# -*- coding: utf-8 -*-
"""区域修复主流程：抽帧 → 检测 → 分段裁剪 → ProPainter 补全 → 羽化贴回 → 编码。

对外只有 run_repair()，CLI / GUI / JSONL 任务进程都调它。
"""
import json
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np

from . import detect as D
from .const import WEIGHT_FILES
from .events import Cancelled, JobError
from .ffmpeg import (INFERENCE, ROOT, WEIGHTS, dir_size, encode_frames,
                     ensure_out_writable, extract_frames, find_ffmpeg,
                     human_size, probe, run, run_stream)

# 整体进度分区（百分比）
PCT_EXTRACT = (2.0, 15.0)
PCT_DETECT = (15.0, 25.0)
PCT_INFER = (25.0, 80.0)
PCT_PASTE = (80.0, 92.0)
PCT_ENCODE = (92.0, 100.0)

PROGRESS_PREFIX = "@@PP@@"


def check_weights():
    missing = []
    for name in WEIGHT_FILES:
        p = os.path.join(str(WEIGHTS), name)
        if not os.path.isfile(p) or os.path.getsize(p) < 1024 * 1024:
            missing.append(name)
    if missing:
        raise JobError("缺少模型权重：%s" % ", ".join(missing),
                       "先运行 setup.cmd 下载权重，或在桌面应用里点「安装运行时」")


def _detect_cfg(opts):
    cfg = dict(D.DETECT)
    if opts.detect_fill:
        cfg["fill"] = (D.DETECT["fill"][0], float(opts.detect_fill))
    if opts.detect_aspect:
        cfg["aspect"] = (D.DETECT["aspect"][0], float(opts.detect_aspect))
    return cfg


def _parse_rect(text):
    parts = text.replace("，", ",").split(",")
    return tuple(int(v) for v in parts)


def _dry_run(video, opts, emit, job, name, fps, dur):
    """只抽十几张采样帧做检测，秒级出预览。"""
    emit.stage("检测预览", PCT_DETECT[0])
    if opts.mask:
        raise JobError("--mask 模式不支持 dry-run",
                       "掩码本身已经指明位置，直接跑正式流程即可")
    times = D.sample_times(dur, 12)
    paths = []
    ff = find_ffmpeg()
    for k, t in enumerate(times):
        p = os.path.join(job, "s%02d.png" % k)
        run([ff, "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % t,
             "-i", video, "-frames:v", "1", "-y", p], emit=emit, label="采样抽帧")
        if os.path.isfile(p):
            paths.append(p)
    if not paths:
        raise JobError("采样抽帧失败", "视频可能损坏，或 ffmpeg 不支持该封装")

    first = cv2.imread(paths[0])
    if first is None:
        raise JobError("采样帧读取失败：%s" % paths[0])
    H, W = first.shape[:2]

    found = []
    if opts.rect:
        box = _parse_rect(opts.rect)
        found.append((box, len(paths)))
        for k, p in enumerate(paths):
            im = cv2.imread(p)
            if im is None:
                continue
            x, y, w, h = box
            cv2.rectangle(im, (x, y), (x + w, y + h), (0, 0, 255), 3)
            cv2.imwrite(os.path.join(job, "detect_rect_%02d.jpg" % k), im,
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
    else:
        segs = D.auto_detect(paths, W, H, job, thr=opts.detect_thr,
                             cfg=_detect_cfg(opts), emit=emit)
        if not segs:
            emit.log("  没检测到稳定的目标区域，请改用 --rect x,y,w,h（坐标可用截图工具量）")
        for s in segs:
            found.append((D.union_box(s["boxes"].values()), len(s["frames"])))

    keep_dir = os.path.join(os.path.dirname(video),
                            "%s_detect_%s" % (name, time.strftime("%Y%m%d_%H%M%S")))
    ensure_out_writable(os.path.join(keep_dir, "probe.tmp"))
    os.makedirs(keep_dir, exist_ok=True)
    copied = 0
    for f in sorted(os.listdir(job)):
        if f.startswith("detect_"):
            shutil.copy2(os.path.join(job, f), keep_dir)
            copied += 1
    emit.log("  预览图 %d 张：%s" % (copied, keep_dir))
    for box, cnt in found:
        emit.log("  检测框 (%d,%d) %dx%d（采样命中 %d 帧）"
                 % (box[0], box[1], box[2], box[3], cnt))
    emit.total_pct(PCT_DETECT[1])
    return {"preview_dir": keep_dir, "boxes": [list(b) for b, _ in found]}


def _build_mask(path, out_dir, n, H, W):
    """把用户掩码写进临时目录并返回 (mask_dir, 并集框)。"""
    os.makedirs(out_dir, exist_ok=True)
    if os.path.isdir(path):
        names = sorted(os.listdir(path))
        if len(names) != n:
            raise JobError("掩码数量(%d) != 帧数(%d)" % (len(names), n),
                           "掩码目录里的 png 要和视频帧一一对应")
        ux = uy = ux1 = uy1 = None
        for i, nm in enumerate(names):
            mpath = os.path.join(path, nm)
            m = cv2.imread(mpath, 0)
            if m is None:
                raise JobError("读不到掩码：%s" % mpath)
            if m.shape[:2] != (H, W):
                raise JobError("掩码尺寸不对：%s 是 %dx%d，视频是 %dx%d"
                               % (mpath, m.shape[1], m.shape[0], W, H),
                               "掩码必须是原视频分辨率；不确定就用 --rect")
            cv2.imwrite(os.path.join(out_dir, "%05d.png" % i), m)
            ys, xs = np.nonzero(m > 10)
            if len(xs) == 0:
                continue
            x0_, y0_ = int(xs.min()), int(ys.min())
            x1_, y1_ = int(xs.max()), int(ys.max())
            ux = x0_ if ux is None else min(ux, x0_)
            uy = y0_ if uy is None else min(uy, y0_)
            ux1 = x1_ if ux1 is None else max(ux1, x1_)
            uy1 = y1_ if uy1 is None else max(uy1, y1_)
        if ux is None:
            raise JobError("掩码里没有任何白色区域（全黑）")
        return out_dir, (ux, uy, ux1 - ux + 1, uy1 - uy + 1)

    m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise JobError("读不到掩码：%s" % path)
    if m.shape[:2] != (H, W):
        raise JobError("掩码尺寸不对：%s 是 %dx%d，视频是 %dx%d"
                       % (path, m.shape[1], m.shape[0], W, H),
                       "掩码必须是原视频分辨率；不确定就用 --rect")
    ys, xs = np.nonzero(m > 10)
    if len(xs) == 0:
        raise JobError("掩码是空的")
    box = (int(xs.min()), int(ys.min()),
           int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    for i in range(n):
        cv2.imwrite(os.path.join(out_dir, "%05d.png" % i), m)
    return out_dir, box


def _run_inference(seg, seg_dir, opts, emit, base_frames, total_frames):
    """跑一次 inference_propainter.py，边读 stdout 边把进度翻译成整体进度。"""
    crops = os.path.join(seg_dir, "crops")
    masks = os.path.join(seg_dir, "masks")
    out_root = os.path.join(seg_dir, "out")
    seg_frames = max(1, len(seg["frames"]))

    cmd = [sys.executable, str(INFERENCE),
           "--video", crops, "--mask", masks, "--output", out_root,
           "--save_frames", "--fp16", "--progress",
           "--subvideo_length", str(opts.subvideo),
           "--neighbor_length", str(opts.neighbor),
           "--ref_stride", str(opts.ref_stride),
           "--mask_dilation", str(opts.mask_dilation)]
    env = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")

    def on_line(line):
        if line.startswith(PROGRESS_PREFIX):
            try:
                obj = json.loads(line[len(PROGRESS_PREFIX):])
            except ValueError:
                return
            if "stage" in obj:
                emit.log("    推理：%s" % obj["stage"])
                return
            cur = float(obj.get("cur", 0))
            tot = max(1.0, float(obj.get("total", seg_frames)))
            frac = max(0.0, min(1.0, cur / tot))
            done = base_frames + frac * seg_frames
            pct = PCT_INFER[0] + (PCT_INFER[1] - PCT_INFER[0]) * (done / max(1.0, total_frames))
            emit.total_pct(pct, "推理")
            emit.progress(int(done), int(total_frames), "推理")
        elif line.strip():
            emit.log("    " + line.strip())

    try:
        run_stream(cmd, on_line, cwd=str(ROOT), env=env, emit=emit, label="ProPainter 推理")
    except JobError as e:
        raise JobError(str(e), "显存不足时把 subvideo 降到 20、padding 降到 0.3；"
                               "驱动太旧请升级到 527.41+")

    res_dir = os.path.join(out_root, "crops", "frames")
    if not os.path.isdir(res_dir):
        raise JobError("推理没有产出帧：%s" % res_dir, "看日志里推理阶段的报错")
    got = len([f for f in os.listdir(res_dir) if f.endswith(".png")])
    if got < seg_frames:
        raise JobError("推理输出帧数不足：%d/%d" % (got, seg_frames),
                       "可能是磁盘满或显存不足导致中断")
    return res_dir


def run_repair(video, opts, emit, out=None, final=True):
    """执行一次区域修复，返回结果字典。"""
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        raise JobError("找不到视频：%s" % video)
    opts.validate()
    if not (opts.rect or opts.mask or opts.auto):
        raise JobError("请指定检测方式：自动检测 / 手动矩形 / 掩码")

    name = os.path.splitext(os.path.basename(video))[0]
    from .options import default_out
    out = out or default_out(video, "repair")
    ensure_out_writable(out)
    os.makedirs(str(ROOT), exist_ok=True)

    t0 = time.time()
    job = tempfile.mkdtemp(prefix="ppwm_")
    frames_dir = os.path.join(job, "frames")
    final_dir = os.path.join(job, "final")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)
    ok = False
    try:
        emit.stage("探测视频", 1)
        fps, has_audio, src_dur = probe(video)
        emit.log("%s · %g fps · 音轨%s · 时长%s"
                 % (os.path.basename(video), fps, "有" if has_audio else "无",
                    "%.1fs" % src_dur if src_dur else "未知"))

        if opts.dry_run:
            extra = _dry_run(video, opts, emit, job, name, fps, src_dur)
            ok = True
            if final:
                emit.done(out=None, elapsed=time.time() - t0, extra=extra)
            return {"dry_run": True, "extra": extra}

        emit.stage("抽帧", PCT_EXTRACT[0])
        extract_frames(video, frames_dir, fps, src_dur, emit=emit,
                       pct_from=PCT_EXTRACT[0], pct_to=PCT_EXTRACT[1])
        files = sorted(os.listdir(frames_dir))
        n = len(files)
        frames = [os.path.join(frames_dir, f) for f in files]
        first = cv2.imread(frames[0])
        if first is None:
            raise JobError("读不到抽出的第一帧：%s" % frames[0])
        H, W = first.shape[:2]
        emit.log("%d 帧 · %dx%d · %g fps" % (n, W, H, fps))
        if src_dur and abs(n / fps - src_dur) > max(0.5, 0.05 * src_dur):
            emit.log("[警告] 抽帧 %d 张 ≈ %.2fs，与源时长 %.2fs 不一致，输出可能变速"
                     % (n, n / fps, src_dur))

        # ---- 确定要处理的片段（显式 rect / mask 优先于 auto）----
        if opts.rect:
            box = _parse_rect(opts.rect)
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                raise JobError("rect 格式应为 x,y,w,h（宽高需大于 0）")
            segs = [{"f0": 0, "f1": n - 1, "frames": list(range(n)),
                     "boxes": {i: box for i in range(n)}}]
            emit.log("手动矩形 (%d,%d) %dx%d" % box)
        elif opts.mask:
            mdir = os.path.join(job, "masks_in")
            mdir, box = _build_mask(opts.mask, mdir, n, H, W)
            segs = [{"f0": 0, "f1": n - 1, "frames": list(range(n)),
                     "boxes": {i: box for i in range(n)}, "mask_dir": mdir}]
            emit.log("掩码范围 (%d,%d) %dx%d" % box)
        else:
            emit.stage("自动定位区域", PCT_DETECT[0])
            segs = D.auto_detect(frames, W, H, job, thr=opts.detect_thr,
                                 cfg=_detect_cfg(opts), emit=emit)
            if not segs:
                raise JobError("自动检测失败", "用「手动矩形」指定目标位置，"
                                              "或先用 --dry-run 看预览图")
            for k, s in enumerate(segs):
                bx, by, bw, bh = D.union_box(s["boxes"].values())
                emit.log("片段%d：帧 %d-%d（%d 帧），目标框约 (%d,%d) %dx%d"
                         % (k, s["f0"], s["f1"], len(s["frames"]), bx, by, bw, bh))
        emit.total_pct(PCT_DETECT[1])

        check_weights()

        # ---- 逐段：裁剪 → 掩码 → 推理 ----
        total_frames = float(sum(len(s["frames"]) for s in segs)) or 1.0
        done_before = 0.0
        metas = []
        for k, seg in enumerate(segs):
            x0, y0, cw, ch = D.crop_geom(D.union_box(seg["boxes"].values()), W, H, opts.padding)
            seg_dir = os.path.join(job, "seg%d" % k)
            crops = os.path.join(seg_dir, "crops")
            masks = os.path.join(seg_dir, "masks")
            os.makedirs(crops, exist_ok=True)
            os.makedirs(masks, exist_ok=True)
            emit.stage("推理 %d/%d" % (k + 1, len(segs)), PCT_INFER[0])
            emit.log("seg%d：帧 %d-%d，裁剪 (%d,%d) %dx%d"
                     % (k, seg["f0"], seg["f1"], x0, y0, cw, ch))

            for j, i in enumerate(seg["frames"]):
                src_path = os.path.join(frames_dir, "%05d.png" % i)
                img = cv2.imread(src_path)
                if img is None:
                    raise JobError("读帧失败：%s" % src_path, "磁盘是否已满？")
                cv2.imwrite(os.path.join(crops, "%05d.png" % j), img[y0:y0 + ch, x0:x0 + cw])
                m = np.zeros((ch, cw), np.uint8)
                if seg.get("mask_dir"):
                    mp = os.path.join(seg["mask_dir"], "%05d.png" % i)
                    src = cv2.imread(mp, 0)
                    if src is None:
                        raise JobError("读不到掩码：%s" % mp)
                    m = src[y0:y0 + ch, x0:x0 + cw]
                else:
                    bx, by, bw, bh = seg["boxes"][i]
                    g = 4
                    mx0, my0 = max(0, bx - x0 - g), max(0, by - y0 - g)
                    mx1 = min(cw, bx - x0 + bw + g)
                    my1 = min(ch, by - y0 + bh + g)
                    m[my0:my1, mx0:mx1] = 255
                cv2.imwrite(os.path.join(masks, "%05d.png" % j), m)

            t_start = time.time()
            res_dir = _run_inference(seg, seg_dir, opts, emit, done_before, total_frames)
            dt = time.time() - t_start
            emit.log("seg%d 推理完成 %.0fs（%.2fs/帧）"
                     % (k, dt, dt / max(1, len(seg["frames"]))))
            done_before += len(seg["frames"])
            metas.append({"x0": x0, "y0": y0, "cw": cw, "ch": ch,
                          "masks": masks, "res": res_dir})

        # ---- 贴回 ----
        emit.stage("贴回原帧", PCT_PASTE[0])
        frame_to_seg = {}
        for k, s in enumerate(segs):
            for j, i in enumerate(s["frames"]):
                frame_to_seg[i] = (k, j)
        for i in range(n):
            img = cv2.imread(frames[i])
            if img is None:
                raise JobError("读帧失败：%s" % frames[i])
            if i in frame_to_seg:
                k, j = frame_to_seg[i]
                m = metas[k]
                res = cv2.imread(os.path.join(m["res"], "%04d.png" % j))
                if res is not None:
                    mask_path = os.path.join(m["masks"], "%05d.png" % j)
                    mm = cv2.imread(mask_path, 0)
                    if mm is None:
                        raise JobError("读不到掩码：%s" % mask_path)
                    alpha = cv2.GaussianBlur(mm.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
                    x0, y0, cw, ch = m["x0"], m["y0"], m["cw"], m["ch"]
                    src = img[y0:y0 + ch, x0:x0 + cw]
                    if res.shape[:2] != src.shape[:2]:
                        res = cv2.resize(res, (src.shape[1], src.shape[0]),
                                         interpolation=cv2.INTER_CUBIC)
                    blend = res.astype(np.float32) * alpha + src.astype(np.float32) * (1 - alpha)
                    img[y0:y0 + ch, x0:x0 + cw] = np.clip(blend, 0, 255).astype(np.uint8)
            cv2.imwrite(os.path.join(final_dir, "%05d.png" % i), img)
            if (i + 1) % 5 == 0 or i + 1 == n:
                pct = PCT_PASTE[0] + (PCT_PASTE[1] - PCT_PASTE[0]) * (i + 1) / n
                emit.total_pct(pct, "贴回原帧")
                emit.progress(i + 1, n, "贴回原帧")

        got = len(os.listdir(final_dir))
        if got != n:
            raise JobError("贴回帧数不足：%d/%d" % (got, n), "磁盘是否已满？")

        # ---- 编码 ----
        emit.stage("编码", PCT_ENCODE[0])
        encode_frames(final_dir, video, out, fps, n, has_audio,
                      encoder=opts.encoder, crf=opts.crf, preset=opts.preset, emit=emit)
        emit.total_pct(PCT_ENCODE[1])

        dur_out = probe(out)[2]
        if dur_out and abs(dur_out - n / fps) > 0.3:
            emit.log("[警告] 输出时长 %.2fs != 预期 %.2fs" % (dur_out, n / fps))

        size = os.path.getsize(out) if os.path.isfile(out) else None
        ok = True
        result = {"out": out, "size": size, "elapsed": time.time() - t0, "frames": n}
        if final:
            emit.done(out=out, size=size, elapsed=result["elapsed"], extra={"frames": n})
        return result
    except Cancelled:
        raise
    except JobError:
        raise
    except Exception as e:  # 未预期异常也转成可读错误
        raise JobError("%s: %s" % (type(e).__name__, e))
    finally:
        if opts.keep:
            emit.log("中间文件：%s（%s）" % (job, human_size(dir_size(job))))
        else:
            shutil.rmtree(job, ignore_errors=True)
