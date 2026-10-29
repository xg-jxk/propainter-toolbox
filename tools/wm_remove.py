# -*- coding: utf-8 -*-
"""ProPainter 去水印：自动检测 / 手动矩形 / 掩码 三种模式

  python wm_remove.py --video "D:\\v\\a.mp4" --auto              # 自动找水印
  python wm_remove.py --video "D:\\v\\a.mp4" --auto --dry-run    # 只检测 + 出预览图
  python wm_remove.py --video "D:\\v\\a.mp4" --rect 1314,918,320,120
  python wm_remove.py --video "D:\\v\\a.mp4" --mask "D:\\v\\masks"
可选: --out --padding 0.45 --subvideo 40 --neighbor 10 --crf 17 --keep
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np

from common import ROOT as _ROOT, find_ffmpeg

REPO = str(_ROOT)
PY = sys.executable
FFMPEG = find_ffmpeg()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd, cwd=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, errors="ignore")
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-3000:] + "\n" + p.stderr[-3000:])
        raise SystemExit(f"命令失败: {cmd[0]}")
    return p


def probe(video):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", video],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors="ignore")
    m = re.search(r"(\d+(?:\.\d+)?) fps", p.stderr)
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else None
    return (float(m.group(1)) if m else 30.0), ("Audio:" in p.stderr), dur


# --------------------------------------------------------------- 几何工具

def crop_geom(box, W, H, padding):
    x, y, w, h = box
    pad = int(max(w, h) * padding)
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    cw, ch = x1 - x0, y1 - y0
    if cw < 128:
        x0 = max(0, x0 - (128 - cw) // 2)
        cw = min(W, 128)
    if ch < 128:
        y0 = max(0, y0 - (128 - ch) // 2)
        ch = min(H, 128)
    cw = min(W, int(np.ceil(cw / 8.0) * 8))
    ch = min(H, int(np.ceil(ch / 8.0) * 8))
    return min(x0, W - cw), min(y0, H - ch), cw, ch


def union_box(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return x0, y0, x1 - x0, y1 - y0


# --------------------------------------------------------------- 自动检测

def _candidates(gray, bgr, W, H):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = ((gray > 185) & (hsv[..., 1] < 60)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    edges = cv2.Canny(gray, 80, 160)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (0.10 * W <= w <= 0.55 * W and 0.025 * H <= h <= 0.22 * H):
            continue
        if not (2.0 <= w / max(h, 1) <= 6.0):
            continue
        # 角标一般贴在四角：要求中心落在最外 25% 的区域
        cx, cy = x + w / 2.0, y + h / 2.0
        if not ((cx < 0.25 * W or cx > 0.75 * W) and (cy < 0.25 * H or cy > 0.75 * H)):
            continue
        fill = (white[y:y + h, x:x + w] > 0).mean()
        if not (0.03 <= fill <= 0.60):      # 实心大块 = 画面内容，不是文字角标
            continue
        # 文字/描边角标内部有明显的边缘；平滑的高光/皮肤没有
        if (edges[y:y + h, x:x + w] > 0).mean() < 0.01:
            continue
        out.append((x, y, w, h))
    return out


def _cluster(cands, tol):
    groups = []
    for (i, box) in cands:
        for g in groups:
            bx, by, bw, bh = g["box"]
            if abs(box[0] - bx) <= tol and abs(box[1] - by) <= tol \
                    and abs(box[2] - bw) <= tol and abs(box[3] - bh) <= tol:
                g["items"].append((i, box))
                g["box"] = tuple(int(np.median([b[k] for _, b in g["items"]])) for k in range(4))
                break
        else:
            groups.append({"box": box, "items": [(i, box)]})
    return groups


def _match_all(frames, tpl, W, H, rx0, ry0, log_):
    scales = [0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12]
    res, prev = [], None
    for i, f in enumerate(frames):
        g = cv2.imread(f, cv2.IMREAD_GRAYSCALE)

        def search(x0, y0, x1, y1):
            roi = g[y0:y1, x0:x1]
            best = (-1.0, x0, y0, tpl.shape[1], tpl.shape[0])
            for s in scales:
                tw, th = int(round(tpl.shape[1] * s)), int(round(tpl.shape[0] * s))
                if tw >= roi.shape[1] or th >= roi.shape[0]:
                    continue
                r = cv2.matchTemplate(roi, cv2.resize(tpl, (tw, th)), cv2.TM_CCOEFF_NORMED)
                _, mx, _, ml = cv2.minMaxLoc(r)
                if mx > best[0]:
                    best = (mx, x0 + ml[0], y0 + ml[1], tw, th)
            return best

        if prev is not None:
            px, py, pw, ph = prev
            m = int(max(pw, ph) * 0.7)
            b = search(max(rx0, px - m), max(ry0, py - m),
                       min(W, px + pw + m), min(H, py + ph + m))
            if b[0] < 0.45:
                b = search(rx0, ry0, W, H)
        else:
            b = search(rx0, ry0, W, H)
        res.append(b)
        prev = b[1:]
        if i and i % 120 == 0:
            log_(f"    匹配 {i}/{len(frames)}  score={b[0]:.2f}")
    return res


def auto_detect(frames, W, H, out_dir, thr=0.62, log_=log):
    step = max(1, len(frames) // 40)
    samples = list(range(0, len(frames), step))

    cands = []
    for i in samples:
        bgr = cv2.imread(frames[i])
        for b in _candidates(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), bgr, W, H):
            cands.append((i, b))
    if not cands:
        log_("    没找到白色角标候选，请改用 --rect 指定位置")
        return []

    groups = _cluster(cands, tol=int(0.02 * W))
    groups.sort(key=lambda g: len(g["items"]), reverse=True)
    main = groups[0]
    if len(main["items"]) < max(3, int(0.15 * len(samples))):
        log_(f"    候选不稳定（{len(main['items'])}/{len(samples)} 帧），请改用 --rect")
        return []
    bx, by, bw, bh = main["box"]
    log_(f"    初定位 ({bx},{by}) {bw}x{bh}，命中 {len(main['items'])}/{len(samples)} 帧")

    best_i, best_sharp = main["items"][0][0], -1.0
    for i, _ in main["items"]:
        v = cv2.Laplacian(cv2.imread(frames[i], 0)[by:by + bh, bx:bx + bw], cv2.CV_64F).var()
        if v > best_sharp:
            best_sharp, best_i = v, i
    tpl = cv2.imread(frames[best_i], 0)[by:by + bh, bx:bx + bw]
    log_(f"    模板取第 {best_i} 帧（清晰度 {best_sharp:.0f}），开始逐帧跟踪")

    rx0, ry0 = max(0, bx - int(1.2 * bw)), max(0, by - int(1.2 * bh))
    raw = _match_all(frames, tpl, W, H, rx0, ry0, log_)

    boxes = {i: (x, y, w, h) for i, (sc, x, y, w, h) in enumerate(raw) if sc >= thr}
    for i in list(boxes):
        if sum(1 for k in range(i - 3, i + 4) if k in boxes and k != i) < 2:
            boxes.pop(i)
    if not boxes:
        log_("    跟踪没有稳定命中，请改用 --rect")
        return []

    segs, cur, prevx = [], [], None
    for i in sorted(boxes):
        x = boxes[i][0]
        if prevx is not None and abs(x - prevx) > int(0.04 * W):
            segs.append(cur)
            cur = []
        cur.append(i)
        prevx = x
    if cur:
        segs.append(cur)

    out = []
    for s in segs:
        if len(s) < 5:
            continue
        out.append({"f0": s[0], "f1": s[-1], "frames": s,
                    "boxes": {i: boxes[i] for i in s}})

    if out_dir:
        for k, seg in enumerate(out):
            i = seg["frames"][len(seg["frames"]) // 2]
            img = cv2.imread(frames[i])
            x, y, w, h = seg["boxes"][i]
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 3)
            cv2.putText(img, f"seg{k} f{i}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 0), 3)
            cv2.imwrite(os.path.join(out_dir, f"detect_seg{k}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out


# --------------------------------------------------------------- 单段处理

def process_segment(seg, idx, frames_dir, W, H, job, args):
    x0, y0, cw, ch = crop_geom(union_box(seg["boxes"].values()), W, H, args.padding)
    seg_dir = os.path.join(job, f"seg{idx}")
    crops, masks = os.path.join(seg_dir, "crops"), os.path.join(seg_dir, "masks")
    os.makedirs(crops, exist_ok=True)
    os.makedirs(masks, exist_ok=True)
    log(f"    seg{idx}: 帧 {seg['f0']}-{seg['f1']}，裁剪 ({x0},{y0}) {cw}x{ch}")

    for k, i in enumerate(seg["frames"]):
        img = cv2.imread(os.path.join(frames_dir, f"{i:05d}.png"))
        cv2.imwrite(os.path.join(crops, f"{k:05d}.png"), img[y0:y0 + ch, x0:x0 + cw])
        m = np.zeros((ch, cw), np.uint8)
        if seg.get("mask_dir"):
            src = cv2.imread(os.path.join(seg["mask_dir"], f"{i:05d}.png"), 0)
            if src.shape[:2] == (H, W):
                m = src[y0:y0 + ch, x0:x0 + cw]
        else:
            bx, by, bw, bh = seg["boxes"][i]
            g = 4
            mx0, my0 = max(0, bx - x0 - g), max(0, by - y0 - g)
            mx1 = min(cw, bx - x0 + bw + g)
            my1 = min(ch, by - y0 + bh + g)
            m[my0:my1, mx0:mx1] = 255
        cv2.imwrite(os.path.join(masks, f"{k:05d}.png"), m)

    env = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    t = time.time()
    run([PY, "inference_propainter.py", "--video", crops, "--mask", masks,
         "--output", os.path.join(seg_dir, "out"), "--save_frames", "--fp16",
         "--subvideo_length", str(args.subvideo), "--neighbor_length", str(args.neighbor),
         "--ref_stride", "12", "--mask_dilation", "2"], cwd=REPO, env=env)
    log(f"    seg{idx} 推理完成 {time.time() - t:.0f}s "
        f"({(time.time() - t) / max(1, len(seg['frames'])):.2f}s/帧)")

    res_dir = os.path.join(seg_dir, "out", "crops", "frames")
    return {"x0": x0, "y0": y0, "cw": cw, "ch": ch, "masks": masks, "res": res_dir}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--rect")
    ap.add_argument("--mask")
    ap.add_argument("--out")
    ap.add_argument("--padding", type=float, default=0.45)
    ap.add_argument("--subvideo", type=int, default=40)
    ap.add_argument("--neighbor", type=int, default=10)
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit(f"找不到视频: {video}")
    if not (a.auto or a.rect or a.mask):
        raise SystemExit("请指定 --auto 或 --rect x,y,w,h 或 --mask")
    for p in (PY, FFMPEG, os.path.join(REPO, "inference_propainter.py")):
        if not os.path.isfile(p):
            raise SystemExit(f"缺少依赖: {p}")

    name = os.path.splitext(os.path.basename(video))[0]
    out = a.out or os.path.join(os.path.dirname(video), name + "_无水印.mp4")
    t0 = time.time()

    job = tempfile.mkdtemp(prefix="ppwm_")
    frames_dir = os.path.join(job, "frames")
    final_dir = os.path.join(job, "final")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    log("1/5 抽帧 ...")
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video, "-vsync", "0",
         "-start_number", "0", "-y", os.path.join(frames_dir, "%05d.png")])
    files = sorted(os.listdir(frames_dir))
    n = len(files)
    frames = [os.path.join(frames_dir, f) for f in files]
    first = cv2.imread(frames[0])
    H, W = first.shape[:2]
    fps, has_audio, src_dur = probe(video)
    log(f"    {n} 帧, {W}x{H}, {fps:g} fps, 音轨: {'有' if has_audio else '无'}")

    # ---- 确定要处理的片段 ----
    if a.auto:
        log("2/5 自动检测水印 ...")
        segs = auto_detect(frames, W, H, job)
        if not segs:
            shutil.rmtree(job, ignore_errors=True)
            raise SystemExit("自动检测失败，请用 --rect x,y,w,h 手动指定")
        for k, s in enumerate(segs):
            bx, by, bw, bh = union_box(s["boxes"].values())
            log(f"    片段{k}: 帧 {s['f0']}-{s['f1']}（{len(s['frames'])} 帧），水印框约 ({bx},{by}) {bw}x{bh}")
    elif a.rect:
        box = tuple(int(v) for v in a.rect.replace("，", ",").split(","))
        if len(box) != 4:
            raise SystemExit("--rect 格式应为 x,y,w,h")
        segs = [{"f0": 0, "f1": n - 1, "frames": list(range(n)),
                 "boxes": {i: box for i in range(n)}}]
        log(f"2/5 手动矩形 ({box[0]},{box[1]}) {box[2]}x{box[3]}")
    else:
        seg = {"f0": 0, "f1": n - 1, "frames": list(range(n)), "boxes": {}}
        if os.path.isdir(a.mask):
            names = sorted(os.listdir(a.mask))
            if len(names) != n:
                raise SystemExit(f"掩码数量({len(names)}) != 帧数({n})")
            seg["mask_dir"] = a.mask
            ux = uy = ux1 = uy1 = None
            for i, nm in enumerate(sorted(names)):
                m = cv2.imread(os.path.join(a.mask, nm), 0)
                if m.shape[:2] != (H, W):
                    m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
                    cv2.imwrite(os.path.join(a.mask, nm), m)
                ys, xs = np.nonzero(m > 10)
                if len(xs) == 0:
                    continue
                x0_, y0_ = int(xs.min()), int(ys.min())
                x1_, y1_ = int(xs.max()), int(ys.max())
                ux = x0_ if ux is None else min(ux, x0_)
                uy = y0_ if uy is None else min(uy, y0_)
                ux1 = x1_ if ux1 is None else max(ux1, x1_)
                uy1 = y1_ if uy1 is None else max(uy1, y1_)
            box = (ux, uy, ux1 - ux + 1, uy1 - uy + 1)
        else:
            m = cv2.imread(a.mask, cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise SystemExit(f"读不到掩码: {a.mask}")
            if m.shape[:2] != (H, W):
                m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
            ys, xs = np.nonzero(m > 10)
            if len(xs) == 0:
                raise SystemExit("掩码是空的")
            box = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
            seg["mask_dir"] = os.path.join(job, "masks_single")
            os.makedirs(seg["mask_dir"], exist_ok=True)
            for i in range(n):
                cv2.imwrite(os.path.join(seg["mask_dir"], f"{i:05d}.png"), m)
        seg["boxes"] = {i: box for i in range(n)}
        segs = [seg]
        log(f"2/5 掩码范围 ({box[0]},{box[1]}) {box[2]}x{box[3]}")

    if a.dry_run:
        log("dry-run：检测预览已写入临时目录")
        keep_dir = os.path.join(os.path.dirname(video), name + "_detect")
        shutil.rmtree(keep_dir, ignore_errors=True)
        os.makedirs(keep_dir, exist_ok=True)
        for f in os.listdir(job):
            if f.startswith("detect_"):
                shutil.copy2(os.path.join(job, f), keep_dir)
        log(f"预览图: {keep_dir}")
        if a.keep:
            log(f"中间文件: {job}")
        else:
            shutil.rmtree(job, ignore_errors=True)
        return

    log("3/5 ProPainter 推理 ...")
    metas = [process_segment(s, k, frames_dir, W, H, job, a) for k, s in enumerate(segs)]

    log("4/5 贴回原帧 ...")
    frame_to_seg = {}
    for k, s in enumerate(segs):
        for j, i in enumerate(s["frames"]):
            frame_to_seg[i] = (k, j)
    for i in range(n):
        img = cv2.imread(frames[i])
        if i in frame_to_seg:
            k, j = frame_to_seg[i]
            m = metas[k]
            res = cv2.imread(os.path.join(m["res"], f"{j:04d}.png"))
            if res is not None:
                mm = cv2.imread(os.path.join(m["masks"], f"{j:05d}.png"), 0)
                alpha = cv2.GaussianBlur(mm.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
                x0, y0, cw, ch = m["x0"], m["y0"], m["cw"], m["ch"]
                src = img[y0:y0 + ch, x0:x0 + cw]
                blend = (res.astype(np.float32) * alpha + src.astype(np.float32) * (1 - alpha)).astype(np.uint8)
                img[y0:y0 + ch, x0:x0 + cw] = blend
        cv2.imwrite(os.path.join(final_dir, f"{i:05d}.png"), img)

    log("5/5 编码 ...")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-framerate", f"{fps:g}", "-i", os.path.join(final_dir, "%05d.png"), "-i", video,
           "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "1:a:0"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if has_audio:
        # 用 -t 精确截到视频时长；-shortest 在音轨时间戳异常的片源上会截掉视频帧
        cmd += ["-c:a", "copy", "-t", f"{n / fps:.3f}"]
    cmd += [out]
    run(cmd)
    dur_out = probe(out)[2]
    if dur_out and abs(dur_out - n / fps) > 0.3:
        log(f"    [警告] 输出时长 {dur_out:.2f}s != 预期 {n / fps:.2f}s")

    if a.keep:
        log(f"    中间文件: {job}")
    else:
        shutil.rmtree(job, ignore_errors=True)
    log(f"完成: {out}  ({os.path.getsize(out) / 1048576:.1f} MB, 总用时 {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

