# -*- coding: utf-8 -*-
"""Real-CUGAN 模型目录扫描与自动选型（不依赖 cv2，GUI 也能用）。"""
import os

#: 降噪档 → 文件名片段
_DENOISE_FILE = {-1: "no-denoise", 0: "conservative",
                 1: "denoise1x", 2: "denoise2x", 3: "denoise3x"}
_DENOISE_CODE = {v: k for k, v in _DENOISE_FILE.items()}

#: 自动选型优先级：先 pro，再 se
PREFERRED = ("models-pro", "models-se")


def scan_models(root):
    """扫描模型目录，返回 {模型名: {(倍率, 降噪档), ...}}。"""
    found = {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        combos = set()
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in files:
            if not f.endswith(".param"):
                continue
            stem = f[:-len(".param")]
            if not stem.startswith("up") or "x-" not in stem:
                continue
            try:
                scale = int(stem[2:stem.index("x-")])
            except ValueError:
                continue
            code = stem[stem.index("x-") + 2:]
            if code in _DENOISE_CODE:
                combos.add((scale, _DENOISE_CODE[code]))
        if combos:
            found[name] = combos
    return found


def resolve_model(available, wanted, scale, denoise, emit=None):
    """挑一个真实存在的 (模型, 倍率, 降噪) 组合。

    优先级：指定模型精确 → 指定模型同倍率最近降噪 → 其它模型精确 → 其它模型最近降噪。
    """
    from .events import JobError

    wanted_combos = available.get(wanted, set())
    scale_list = sorted({sc for combos in available.values() for (sc, _) in combos})

    if (scale, denoise) in wanted_combos:
        return wanted, scale, denoise

    same_scale = sorted(dn for (sc, dn) in wanted_combos if sc == scale)
    if same_scale:
        nearest = min(same_scale, key=lambda dn: (abs(dn - denoise), dn))
        if emit:
            emit.log("模型 %s 的 %dx 没有降噪=%d，自动改用降噪=%d（%s）"
                     % (wanted, scale, denoise, nearest, _DENOISE_FILE[nearest]))
        return wanted, scale, nearest

    for name, combos in available.items():
        if name == wanted:
            continue
        if (scale, denoise) in combos:
            if emit:
                emit.log("模型 %s 没有 %dx，自动改用 %s" % (wanted, scale, name))
            return name, scale, denoise

    for name, combos in available.items():
        if name == wanted:
            continue
        same = sorted(dn for (sc, dn) in combos if sc == scale)
        if same:
            nearest = min(same, key=lambda dn: (abs(dn - denoise), dn))
            if emit:
                emit.log("模型 %s 没有 %dx，自动改用 %s（降噪=%d）"
                         % (wanted, scale, name, nearest))
            return name, scale, nearest

    raise JobError(
        "Real-CUGAN 没有 %dx 模型可用" % scale,
        "可用的倍率：%s；换个倍率，或重新运行 setup.cmd 下载完整模型"
        % ("/".join(str(s) for s in scale_list) if scale_list else "无"))


def auto_model(available, scale, denoise, emit=None):
    """内置选型：优先 pro；pro 没有该倍率/降噪档时用 se；再不行就近。

    例：4x 只有 se 有；2x 的「降噪 1/2」也只有 se 有。
    """
    for name in PREFERRED:
        if (scale, denoise) in available.get(name, set()):
            return name, scale, denoise
    for name in PREFERRED:
        if name in available:
            return resolve_model(available, name, scale, denoise, emit)
    return resolve_model(available, next(iter(available), "models-pro"),
                         scale, denoise, emit)
