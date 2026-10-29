# -*- coding: utf-8 -*-
"""ProPainter 去水印：自动检测 / 手动矩形 / 掩码 三种模式

  python wm_remove.py --video "D:\\v\\a.mp4"                      # 自动找水印
  python wm_remove.py --video "D:\\v\\a.mp4" --dry-run            # 只检测 + 出预览图（秒级）
  python wm_remove.py --video "D:\\v\\a.mp4" --rect 1314,918,320,120
  python wm_remove.py --video "D:\\v\\a.mp4" --mask "D:\\v\\masks"
可选: --out --padding 0.45 --subvideo 40 --neighbor 10 --ref-stride 12
      --mask-dilation 2 --crf 17 --encoder auto|nvenc|x264
      --workdir --log-file --detect-thr 0.62 --keep
"""
import argparse
import atexit
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np

from common import (ROOT as _ROOT, ensure_out_writable, encode_frames,
                    dir_size, find_ffmpeg, human_size, log, probe, run,
                    set_log_file)

REPO = str(_ROOT)
PY = sys.executable

# 自动检测的默认参数。换平台（半透明 logo / 彩色角标）时优先调这里或命令行，
# 不要把魔法数字再写回函数体。
DETECT = {
    "white": 185,        # 灰度阈值：大于它算"浅色"
    "sat": 60,           # HSV 饱和度上限：小于它算"白/灰"
    "min_w": 0.10,       # 候选宽（相对画面宽）
    "max_w": 0.55,
    "min_h": 0.025,
    "max_h": 0.22,
    "aspect": (2.0, 10.0),   # 文字类水印（"WATERMARK"、@昵称）天然是长条，6.0 太严
    "corner": 0.25,      # 中心必须落在最外 25% 的四角
    "fill": (0.03, 0.60),
    "edge": 0.01,
    "close": 13,         # 形态学闭运算核：把同一行文字里分开的字符合成一个候选
    "thr": 0.62,         # 逐帧模板匹配置信度阈值
    "samples": 40,       # 自动检测最多采样多少帧
}

_STATE = {"job": None, "keep": False, "ok": False}


def _on_exit():
    """成功就删临时目录；失败则保留并打印路径与体积，方便排查。"""
    job = _STATE["job"]
    if not job:
        return
    if _STATE["ok"] and not _STATE["keep"]:
        shutil.rmtree(job, ignore_errors=True)
    elif not _STATE["ok"] and os.path.isdir(job):
        try:
            size = human_size(dir_size(job))
        except Exception:
            size = "未知大小"
        print("[提示] 任务中断，中间文件保留在 %s（%s，确认后可整体删除）" % (job, size),
              file=sys.stderr)


atexit.register(_on_exit)


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

def _candidates(gray, bgr, W, H, cfg=None):
    cfg = cfg or DETECT
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = ((gray > cfg["white"]) & (hsv[..., 1] < cfg["sat"])).astype(np.uint8) * 255
    raw = white.copy()
    k = int(cfg.get("close", 13))
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    edges = cv2.Canny(gray, 80, 160)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (cfg["min_w"] * W <= w <= cfg["max_w"] * W and cfg["min_h"] * H <= h <= cfg["max_h"] * H):
            continue
        if not (cfg["aspect"][0] <= w / max(h, 1) <= cfg["aspect"][1]):
            continue
        # 角标一般贴在四角：要求中心落在最外 25% 的区域
        cx, cy = x + w / 2.0, y + h / 2.0
        if not ((cx < cfg["corner"] * W or cx > (1 - cfg["corner"]) * W) and
                (cy < cfg["corner"] * H or cy > (1 - cfg["corner"]) * H)):
            continue
        # 填充率必须基于"闭运算之前"的掩码来算：闭运算会把字间空隙填上，
        # 用闭运算后的掩码算，粗体文字会被误判成"实心大块"
        fill = (raw[y:y + h, x:x + w] > 0).mean()
        if not (cfg["fill"][0] <= fill <= cfg["fill"][1]):   # 实心大块 = 画面内容
            continue
        # 文字/描边角标内部有明显的边缘；平滑的高光/皮肤没有
        if (edges[y:y + h, x:x + w] > 0).mean() < cfg["edge"]:
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


def _match_all(frames, tpl, W, H, rx0, ry0, log_=log):
    scales = [0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12]
    res, prev = [], None
    for i, f in enumerate(frames):
        g = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if g is None:
            res.append((-1.0, 0, 0, 0, 0))
            continue

        def search(x0, y0, x1, y1):
            roi = g[y0:y1, x0:x1]
            best = (-1.0, x0, y0, tpl.shape[1], tpl.shape[0])
            for s in scales:
                tw, th = int(round(tpl.shape[1] * s)), int(round(tpl.shape[0] * s))
                if tw > roi.shape[1] or th > roi.shape[0]:
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
                # 跟丢时全图重找：注意从 (0,0) 开始，否则水印漂到画面另一侧会永远搜不到
                b = search(0, 0, W, H)
        else:
            b = search(rx0, ry0, W, H)
        res.append(b)
        prev = b[1:]
        if i and i % 120 == 0:
            log_("    匹配 %d/%d  score=%.2f" % (i, len(frames), b[0]))
    return res


def auto_detect(frames, W, H, out_dir, thr=None, log_=log, cfg=None):
    cfg = cfg or DETECT
    thr = cfg["thr"] if thr is None else thr
    step = max(1, len(frames) // max(1, cfg["samples"]))
    samples = list(range(0, len(frames), step))

    cands = []
    for i in samples:
        bgr = cv2.imread(frames[i])
        if bgr is None:
            continue
        for b in _candidates(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), bgr, W, H, cfg):
            cands.append((i, b))
    if not cands:
        log_("   没找到白色角标候选：可试 --detect-fill 0.85 / --detect-aspect 9，"
             "或直接用 --rect x,y,w,h")
        return []

    groups = _cluster(cands, tol=int(0.02 * W))
    groups.sort(key=lambda g: len(g["items"]), reverse=True)
    main = groups[0]
    if len(main["items"]) < max(3, int(0.15 * len(samples))):
        log_("    候选不稳定（%d/%d 帧），请改用 --rect" % (len(main["items"]), len(samples)))
        return []
    bx, by, bw, bh = main["box"]
    log_("    初定位 (%d,%d) %dx%d，命中 %d/%d 帧" % (bx, by, bw, bh, len(main["items"]), len(samples)))

    best_i, best_sharp = main["items"][0][0], -1.0
    for i, _ in main["items"]:
        img = cv2.imread(frames[i], 0)
        if img is None:
            continue
        v = cv2.Laplacian(img[by:by + bh, bx:bx + bw], cv2.CV_64F).var()
        if v > best_sharp:
            best_sharp, best_i = v, i
    tpl_img = cv2.imread(frames[best_i], 0)
    if tpl_img is None:
        log_("    模板帧读取失败，请改用 --rect")
        return []
    tpl = tpl_img[by:by + bh, bx:bx + bw]
    log_("    模板取第 %d 帧（清晰度 %.0f），开始逐帧跟踪" % (best_i, best_sharp))

    rx0, ry0 = max(0, bx - int(1.2 * bw)), max(0, by - int(1.2 * bh))
    raw = _match_all(frames, tpl, W, H, rx0, ry0, log_)

    boxes = {i: (x, y, w, h) for i, (sc, x, y, w, h) in enumerate(raw) if sc >= thr and w > 0}
    for i in list(boxes):
        if sum(1 for k in range(i - 3, i + 4) if k in boxes and k != i) < 2:
            boxes.pop(i)
    if not boxes:
        log_("    跟踪没有稳定命中，请改用 --rect")
        return []

    segs, cur, prev = [], [], None
    for i in sorted(boxes):
        x, y = boxes[i][0], boxes[i][1]
        # x、y 同时判断：水印上下移动时不切段，union 框会被拉高、裁剪区域变大
        if prev is not None and (abs(x - prev[0]) > int(0.04 * W) or abs(y - prev[1]) > int(0.04 * H)):
            segs.append(cur)
            cur = []
        cur.append(i)
        prev = (x, y)
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
            if img is None:
                continue
            x, y, w, h = seg["boxes"][i]
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 3)
            cv2.putText(img, "seg%d f%d" % (k, i), (20, 60), cv2.FONT_HERSHEY_SIMPLEX,
                        1.4, (0, 255, 0), 3)
            cv2.imwrite(os.path.join(out_dir, "detect_seg%d.jpg" % k), img,
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out


# --------------------------------------------------------------- 单段处理

def process_segment(seg, idx, frames_dir, W, H, job, args):
    x0, y0, cw, ch = crop_geom(union_box(seg["boxes"].values()), W, H, args.padding)
    seg_dir = os.path.join(job, "seg%d" % idx)
    crops, masks = os.path.join(seg_dir, "crops"), os.path.join(seg_dir, "masks")
    os.makedirs(crops, exist_ok=True)
    os.makedirs(masks, exist_ok=True)
    log("    seg%d: 帧 %d-%d，裁剪 (%d,%d) %dx%d" % (idx, seg["f0"], seg["f1"], x0, y0, cw, ch))

    for k, i in enumerate(seg["frames"]):
        src_path = os.path.join(frames_dir, "%05d.png" % i)
        img = cv2.imread(src_path)
        if img is None:
            raise SystemExit("读帧失败: %s（磁盘满或抽帧不完整）" % src_path)
        cv2.imwrite(os.path.join(crops, "%05d.png" % k), img[y0:y0 + ch, x0:x0 + cw])
        m = np.zeros((ch, cw), np.uint8)
        if seg.get("mask_dir"):
            mask_path = os.path.join(seg["mask_dir"], "%05d.png" % i)
            src = cv2.imread(mask_path, 0)
            if src is None:
                raise SystemExit("读不到掩码: %s" % mask_path)
            if src.shape[:2] != (H, W):
                raise SystemExit("掩码尺寸不对: %s 是 %dx%d，视频是 %dx%d"
                                 % (mask_path, src.shape[1], src.shape[0], W, H))
            m = src[y0:y0 + ch, x0:x0 + cw]
        else:
            bx, by, bw, bh = seg["boxes"][i]
            g = 4
            mx0, my0 = max(0, bx - x0 - g), max(0, by - y0 - g)
            mx1 = min(cw, bx - x0 + bw + g)
            my1 = min(ch, by - y0 + bh + g)
            m[my0:my1, mx0:mx1] = 255
        cv2.imwrite(os.path.join(masks, "%05d.png" % k), m)

    env = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    t = time.time()
    run([PY, "inference_propainter.py", "--video", crops, "--mask", masks,
         "--output", os.path.join(seg_dir, "out"), "--save_frames", "--fp16",
         "--subvideo_length", str(args.subvideo), "--neighbor_length", str(args.neighbor),
         "--ref_stride", str(args.ref_stride), "--mask_dilation", str(args.mask_dilation)],
        cwd=REPO, env=env)
    dt = time.time() - t
    log("    seg%d 推理完成 %.0fs（%.2fs/帧）" % (idx, dt, dt / max(1, len(seg["frames"]))))

    res_dir = os.path.join(seg_dir, "out", "crops", "frames")
    return {"x0": x0, "y0": y0, "cw": cw, "ch": ch, "masks": masks, "res": res_dir}


# --------------------------------------------------------------- dry-run

def _sample_times(dur, n):
    if not dur or dur <= 0:
        return [0.0]
    step = float(dur) / (n + 1)
    return [step * (k + 1) for k in range(n)]


def _detect_cfg(args):
    """把命令行的检测参数合进 DETECT 默认值。"""
    cfg = dict(DETECT)
    fill_max = getattr(args, "detect_fill", None)
    if fill_max:
        cfg["fill"] = (DETECT["fill"][0], float(fill_max))
    aspect_max = getattr(args, "detect_aspect", None)
    if aspect_max:
        cfg["aspect"] = (DETECT["aspect"][0], float(aspect_max))
    return cfg


def dry_run_preview(video, args, name, fps, dur):
    """只抽十几张采样帧做检测，秒级出预览；不再为看几张图抽整片。"""
    job = _STATE["job"]
    log("dry-run：只抽采样帧做检测，不处理整片 ...")
    if args.mask:
        log("  --mask 模式的 dry-run 未实现（掩码本身已指明位置），请直接跑正式流程。")
        return

    times = _sample_times(dur, 12)
    paths = []
    for k, t in enumerate(times):
        p = os.path.join(job, "s%02d.png" % k)
        run([find_ffmpeg(), "-hide_banner", "-loglevel", "error",
             "-ss", "%.3f" % t, "-i", video, "-frames:v", "1", "-y", p])
        if os.path.isfile(p):
            paths.append(p)
    if not paths:
        raise SystemExit("采样抽帧失败：可能是视频损坏或 ffmpeg 不支持该封装")

    first = cv2.imread(paths[0])
    if first is None:
        raise SystemExit("采样帧读取失败: %s" % paths[0])
    H, W = first.shape[:2]

    found = []
    if args.rect:
        box = tuple(int(v) for v in args.rect.replace("，", ",").split(","))
        if len(box) != 4:
            raise SystemExit("--rect 格式应为 x,y,w,h")
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
        segs = auto_detect(paths, W, H, job, thr=args.detect_thr, cfg=_detect_cfg(args))
        if not segs:
            log("  没检测到稳定的水印，请改用 --rect x,y,w,h（坐标可用截图工具量）")
        for s in segs:
            found.append((union_box(s["boxes"].values()), len(s["frames"])))

    keep_dir = os.path.join(os.path.dirname(video),
                            "%s_detect_%s" % (name, time.strftime("%Y%m%d_%H%M%S")))
    ensure_out_writable(os.path.join(keep_dir, "probe.tmp"))
    os.makedirs(keep_dir, exist_ok=True)
    copied = 0
    for f in sorted(os.listdir(job)):
        if f.startswith("detect_"):
            shutil.copy2(os.path.join(job, f), keep_dir)
            copied += 1
    log("  预览图 %d 张：%s" % (copied, keep_dir))
    for box, cnt in found:
        log("  检测框 (%d,%d) %dx%d（采样命中 %d 帧）" % (box[0], box[1], box[2], box[3], cnt))


# --------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--auto", action="store_true", help="自动检测水印位置")
    ap.add_argument("--rect", help="手动矩形 x,y,w,h")
    ap.add_argument("--mask", help="掩码文件或掩码目录")
    ap.add_argument("--out")
    ap.add_argument("--padding", type=float, default=0.45)
    ap.add_argument("--subvideo", type=int, default=40)
    ap.add_argument("--neighbor", type=int, default=10)
    ap.add_argument("--ref-stride", type=int, default=12, dest="ref_stride")
    ap.add_argument("--mask-dilation", type=int, default=2, dest="mask_dilation")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--encoder", default="auto", choices=["auto", "x264", "nvenc"])
    ap.add_argument("--preset", default=None, help="x264 预设，默认 slow")
    ap.add_argument("--detect-thr", type=float, default=DETECT["thr"], dest="detect_thr")
    ap.add_argument("--detect-fill", type=float, default=None, dest="detect_fill",
                    help="白色填充率上限，默认 0.60；文字水印偏密时可试 0.85")
    ap.add_argument("--detect-aspect", type=float, default=None, dest="detect_aspect",
                    help="候选宽高比上限，默认 6.0；长条文字水印可试 9")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--workdir", help="临时目录位置（默认系统临时目录；建议指到大盘）")
    ap.add_argument("--log-file", dest="log_file")
    a = ap.parse_args()

    if a.log_file:
        set_log_file(a.log_file)

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        raise SystemExit("找不到视频: %s" % video)
    if not (a.auto or a.rect or a.mask):
        raise SystemExit("请指定 --auto 或 --rect x,y,w,h 或 --mask")
    if not (0.0 <= a.padding <= 2.0):
        raise SystemExit("--padding 应在 0~2 之间")
    for p in (PY, find_ffmpeg(), os.path.join(REPO, "inference_propainter.py")):
        if not os.path.isfile(p):
            raise SystemExit("缺少依赖: %s" % p)

    name = os.path.splitext(os.path.basename(video))[0]
    out = a.out or os.path.join(os.path.dirname(video), name + "_无水印.mp4")
    # 提前验证可写，避免跑完一小时才在编码那步失败
    ensure_out_writable(out)
    t0 = time.time()

    if a.workdir:
        os.makedirs(a.workdir, exist_ok=True)
    job = tempfile.mkdtemp(prefix="ppwm_", dir=a.workdir or None)
    _STATE["job"], _STATE["keep"] = job, a.keep
    frames_dir = os.path.join(job, "frames")
    final_dir = os.path.join(job, "final")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    fps, has_audio, src_dur = probe(video)
    if not (5.0 <= fps <= 240.0):
        raise SystemExit("读不到合理的帧率（%s），请确认源文件是否完整" % fps)

    if a.dry_run:
        dry_run_preview(video, a, name, fps, src_dur)
        _STATE["ok"] = True
        log("dry-run 完成（未处理整片）")
        return

    log("1/5 抽帧 ...")
    # 用 fps 滤镜归一化成恒定帧率：VFR 源不会让输出时长跑偏
    run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", video,
         "-vf", "fps=%g" % fps, "-start_number", "0", "-y",
         os.path.join(frames_dir, "%05d.png")])
    files = sorted(os.listdir(frames_dir))
    n = len(files)
    if n == 0:
        raise SystemExit("抽帧结果为空：磁盘满或 ffmpeg 解码失败")
    frames = [os.path.join(frames_dir, f) for f in files]
    first = cv2.imread(frames[0])
    if first is None:
        raise SystemExit("读不到抽出的第一帧: %s" % frames[0])
    H, W = first.shape[:2]
    log("    %d 帧, %dx%d, %g fps, 音轨: %s" % (n, W, H, fps, "有" if has_audio else "无"))
    if src_dur and abs(n / fps - src_dur) > max(0.5, 0.05 * src_dur):
        log("    [警告] 抽帧 %d 张 ≈ %.2fs，与源时长 %.2fs 不一致，输出可能会变速"
            % (n, n / fps, src_dur))

    # ---- 确定要处理的片段（显式的 --rect / --mask 优先于 --auto）----
    if a.rect:
        box = tuple(int(v) for v in a.rect.replace("，", ",").split(","))
        if len(box) != 4:
            raise SystemExit("--rect 格式应为 x,y,w,h")
        if box[2] <= 0 or box[3] <= 0:
            raise SystemExit("--rect 的宽高必须大于 0")
        segs = [{"f0": 0, "f1": n - 1, "frames": list(range(n)),
                 "boxes": {i: box for i in range(n)}}]
        log("2/5 手动矩形 (%d,%d) %dx%d" % (box[0], box[1], box[2], box[3]))
    elif a.mask:
        seg = {"f0": 0, "f1": n - 1, "frames": list(range(n)), "boxes": {}}
        mdir = os.path.join(job, "masks_in")
        os.makedirs(mdir, exist_ok=True)
        if os.path.isdir(a.mask):
            names = sorted(os.listdir(a.mask))
            if len(names) != n:
                raise SystemExit("掩码数量(%d) != 帧数(%d)" % (len(names), n))
            ux = uy = ux1 = uy1 = None
            for i, nm in enumerate(names):
                mpath = os.path.join(a.mask, nm)
                m = cv2.imread(mpath, 0)
                if m is None:
                    raise SystemExit("读不到掩码: %s" % mpath)
                if m.shape[:2] != (H, W):
                    raise SystemExit("掩码尺寸不对: %s 是 %dx%d，视频是 %dx%d"
                                     % (mpath, m.shape[1], m.shape[0], W, H))
                # 写进临时目录，绝不改动用户的掩码文件
                cv2.imwrite(os.path.join(mdir, "%05d.png" % i), m)
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
                raise SystemExit("掩码里没有任何白色区域（全黑）")
            box = (ux, uy, ux1 - ux + 1, uy1 - uy + 1)
        else:
            m = cv2.imread(a.mask, cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise SystemExit("读不到掩码: %s" % a.mask)
            if m.shape[:2] != (H, W):
                raise SystemExit("掩码尺寸不对: %s 是 %dx%d，视频是 %dx%d"
                                 % (a.mask, m.shape[1], m.shape[0], W, H))
            ys, xs = np.nonzero(m > 10)
            if len(xs) == 0:
                raise SystemExit("掩码是空的")
            box = (int(xs.min()), int(ys.min()),
                   int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
            for i in range(n):
                cv2.imwrite(os.path.join(mdir, "%05d.png" % i), m)
        seg["mask_dir"] = mdir
        seg["boxes"] = {i: box for i in range(n)}
        segs = [seg]
        log("2/5 掩码范围 (%d,%d) %dx%d" % (box[0], box[1], box[2], box[3]))
    else:
        log("2/5 自动检测水印 ...")
        segs = auto_detect(frames, W, H, job, thr=a.detect_thr, cfg=_detect_cfg(a))
        if not segs:
            shutil.rmtree(job, ignore_errors=True)
            _STATE["job"] = None
            raise SystemExit("自动检测失败，请用 --rect x,y,w,h 手动指定（可先 --dry-run 看预览）")
        for k, s in enumerate(segs):
            bx, by, bw, bh = union_box(s["boxes"].values())
            log("    片段%d: 帧 %d-%d（%d 帧），水印框约 (%d,%d) %dx%d"
                % (k, s["f0"], s["f1"], len(s["frames"]), bx, by, bw, bh))

    log("3/5 ProPainter 推理 ...")
    metas = [process_segment(s, k, frames_dir, W, H, job, a) for k, s in enumerate(segs)]

    log("4/5 贴回原帧 ...")
    frame_to_seg = {}
    for k, s in enumerate(segs):
        for j, i in enumerate(s["frames"]):
            frame_to_seg[i] = (k, j)
    for i in range(n):
        img = cv2.imread(frames[i])
        if img is None:
            raise SystemExit("读帧失败: %s" % frames[i])
        if i in frame_to_seg:
            k, j = frame_to_seg[i]
            m = metas[k]
            res = cv2.imread(os.path.join(m["res"], "%04d.png" % j))
            if res is not None:
                mask_path = os.path.join(m["masks"], "%05d.png" % j)
                mm = cv2.imread(mask_path, 0)
                if mm is None:
                    raise SystemExit("读不到掩码: %s" % mask_path)
                alpha = cv2.GaussianBlur(mm.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
                x0, y0, cw, ch = m["x0"], m["y0"], m["cw"], m["ch"]
                src = img[y0:y0 + ch, x0:x0 + cw]
                if res.shape[:2] != src.shape[:2]:
                    res = cv2.resize(res, (src.shape[1], src.shape[0]), interpolation=cv2.INTER_CUBIC)
                blend = (res.astype(np.float32) * alpha + src.astype(np.float32) * (1 - alpha))
                img[y0:y0 + ch, x0:x0 + cw] = np.clip(blend, 0, 255).astype(np.uint8)
        cv2.imwrite(os.path.join(final_dir, "%05d.png" % i), img)

    got = len(os.listdir(final_dir))
    if got != n:
        raise SystemExit("贴回帧数不足：%d/%d，可能是磁盘满或读帧失败" % (got, n))
    log("5/5 编码 ...")
    encode_frames(final_dir, video, out, fps, n, has_audio,
                  encoder=a.encoder, crf=a.crf, preset=a.preset)

    dur_out = probe(out)[2]
    if dur_out and abs(dur_out - n / fps) > 0.3:
        log("    [警告] 输出时长 %.2fs != 预期 %.2fs" % (dur_out, n / fps))

    if a.keep:
        log("    中间文件: %s" % job)
    _STATE["ok"] = True
    log("完成: %s  (%s, 总用时 %.0fs)"
        % (out, human_size(os.path.getsize(out)), time.time() - t0))


if __name__ == "__main__":
    main()
