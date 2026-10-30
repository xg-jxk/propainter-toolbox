# -*- coding: utf-8 -*-
"""目标区域自动定位：白色角标候选 → 聚类 → 多尺度模板跟踪 → 按位置切段。

纯 cv2/numpy 逻辑，不依赖 torch，可以单独测。
"""
import os
import time

import cv2
import numpy as np

# 自动检测默认参数。换平台（半透明 logo / 彩色角标）时优先调这里或命令行，
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


def _log(emit, msg):
    if emit is not None:
        emit.log(msg)
    else:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# --------------------------------------------------------------- 几何

def crop_geom(box, W, H, padding):
    """按目标框外扩裁剪，宽高对齐 8 的倍数并保证不越界、不小于 128。"""
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


# --------------------------------------------------------------- 候选

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
        if not (cfg["min_w"] * W <= w <= cfg["max_w"] * W
                and cfg["min_h"] * H <= h <= cfg["max_h"] * H):
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
        if not (cfg["fill"][0] <= fill <= cfg["fill"][1]):
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


def _match_all(frames, tpl, W, H, rx0, ry0, emit=None):
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
                # 跟丢时全图重找：注意从 (0,0) 开始，否则目标漂到画面另一侧会永远搜不到
                b = search(0, 0, W, H)
        else:
            b = search(rx0, ry0, W, H)
        res.append(b)
        prev = b[1:]
        if i and i % 120 == 0:
            _log(emit, "    匹配 %d/%d  score=%.2f" % (i, len(frames), b[0]))
    return res


def auto_detect(frames, W, H, out_dir=None, thr=None, cfg=None, emit=None, info=None):
    """返回 [{"f0","f1","frames":[i...],"boxes":{i:(x,y,w,h)}}]。

    info: 可选的 dict，失败时回填 {"box": (x,y,w,h), "hits": n, "samples": m}
    """
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
        _log(emit, "   没找到浅色角标候选：可试 --detect-fill 0.85 / --detect-aspect 9，"
                   "或在界面里改用手动矩形 / 逐帧掩码")
        return []

    groups = _cluster(cands, tol=int(0.02 * W))
    groups.sort(key=lambda g: len(g["items"]), reverse=True)
    main = groups[0]
    if len(main["items"]) < max(3, int(0.15 * len(samples))):
        bx, by, bw, bh = main["box"]
        if info is not None:
            info.update({"box": main["box"], "hits": len(main["items"]),
                         "samples": len(samples)})
        _log(emit, "   候选不稳定（%d/%d 帧），疑似位置 (%d,%d) %dx%d"
                   % (len(main["items"]), len(samples), bx, by, bw, bh))
        return []
    bx, by, bw, bh = main["box"]
    _log(emit, "   初定位 (%d,%d) %dx%d，命中 %d/%d 帧"
         % (bx, by, bw, bh, len(main["items"]), len(samples)))

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
        _log(emit, "   模板帧读取失败，请改用 --rect")
        return []
    tpl = tpl_img[by:by + bh, bx:bx + bw]
    _log(emit, "   模板取第 %d 帧（清晰度 %.0f），开始逐帧跟踪" % (best_i, best_sharp))

    rx0, ry0 = max(0, bx - int(1.2 * bw)), max(0, by - int(1.2 * bh))
    raw = _match_all(frames, tpl, W, H, rx0, ry0, emit)

    boxes = {i: (x, y, w, h) for i, (sc, x, y, w, h) in enumerate(raw) if sc >= thr and w > 0}
    for i in list(boxes):
        if sum(1 for k in range(i - 3, i + 4) if k in boxes and k != i) < 2:
            boxes.pop(i)
    if not boxes:
        _log(emit, "   跟踪没有稳定命中，请改用 --rect")
        return []

    segs, cur, prev = [], [], None
    for i in sorted(boxes):
        x, y = boxes[i][0], boxes[i][1]
        # x、y 同时判断：目标上下移动时不切段，union 框会被拉高、裁剪区域变大
        if prev is not None and (abs(x - prev[0]) > int(0.04 * W)
                                 or abs(y - prev[1]) > int(0.04 * H)):
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


def sample_times(dur, n=12):
    if not dur or dur <= 0:
        return [0.0]
    step = float(dur) / (n + 1)
    return [step * (k + 1) for k in range(n)]
