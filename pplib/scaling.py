# -*- coding: utf-8 -*-
"""输出尺寸规划：统一长边 + 16:9 吸附 + 4x 不够时补齐。

产品决策（2026-11-01）：
- 目标档位 = **输出长边 L**（1080p=1920 / 2K=2560 / 4K=3840 / 8K=7680）。
- 源长边 >= L：**不跑超分模型**，只做降采样，输出仍然是标准尺寸。
- 源长边 < L：取能覆盖 L 的最小整数倍（2/3/4），超分后再缩到 L。
- 4x 之后仍 < L：用 4x 结果再普通缩放到 L（尺寸一定统一，最后那步是插值）。
- 宽高比接近 16:9（±1%）时直接吸附到标准尺寸，避免 2560×1438 这种毛刺。
"""
import math

#: 目标长边 -> 该档的标准尺寸（16:9）
STANDARD_SIZES = {
    1920: (1920, 1080),
    2560: (2560, 1440),
    3840: (3840, 2160),
    7680: (7680, 4320),
}

AR_WIDE = 16.0 / 9.0
#: 宽高比与 16:9 的允许偏差（相对值）：854×480 的 0.08% 也算 16:9
AR_TOLERANCE = 0.01

MIN_SCALE = 2
MAX_SCALE = 4

#: 目标长边 -> 文件名后缀
TARGET_TAGS = {1920: "1080p", 2560: "2K", 3840: "4K", 7680: "8K"}


def target_tag(target_long):
    """1920 → "1080p"，用在输出文件名上。"""
    target = int(target_long or 0)
    return TARGET_TAGS.get(target, "%dp" % target if target else "sr")


def _even(value):
    """取最接近的偶数（yuv420p 要求宽高为偶数）。"""
    return max(2, int(round(float(value) / 2.0)) * 2)


def is_wide(w, h):
    """是否算 16:9 片源（含 0.08% 这类常见误差）。"""
    if not (w and h):
        return False
    return abs(float(w) / float(h) - AR_WIDE) <= AR_TOLERANCE


def final_size(width, height, target_long, limit=0):
    """按目标长边算最终输出 (宽, 高)。

    16:9 片源吸附到标准尺寸；其它比例保持比例、只钉长边。
    limit>0 时再兜一次硬上限（默认 8K）。
    """
    width, height = int(width or 0), int(height or 0)
    target = int(target_long or 0)
    if width <= 0 or height <= 0 or target <= 0:
        return width, height
    if is_wide(width, height) and target in STANDARD_SIZES:
        out_w, out_h = STANDARD_SIZES[target]
    else:
        factor = float(target) / float(max(width, height))
        out_w, out_h = _even(width * factor), _even(height * factor)
    limit = int(limit or 0)
    if limit and max(out_w, out_h) > limit:
        factor = float(limit) / float(max(out_w, out_h))
        out_w, out_h = _even(out_w * factor), _even(out_h * factor)
    return int(out_w), int(out_h)


def plan_scale(width, height, target_long, limit=0):
    """规划这一条视频怎么出片。

    返回 dict：
      need_sr  是否要跑 Real-CUGAN（源已达标时为 False，只降采样）
      scale    模型倍率（need_sr=False 时为 0）
      final    最终输出 (宽, 高)
      reason   给人看的一句话（跳过/补齐的原因）
    """
    width, height = int(width or 0), int(height or 0)
    target = int(target_long or 0)
    if width <= 0 or height <= 0 or target <= 0:
        return {"need_sr": False, "scale": 0, "final": (width, height), "reason": ""}

    long_side = max(width, height)
    final = final_size(width, height, target, limit)
    if long_side >= target:
        return {"need_sr": False, "scale": 0, "final": final,
                "reason": "源长边 %d 已达到 %d，跳过超分" % (long_side, target)}

    need = float(target) / float(long_side)
    scale = int(math.ceil(need - 1e-6))
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    if long_side * scale < target:
        reason = ("需要 %.2fx 才够 %d，超分最高 %dx：先 %dx 再插值补齐"
                  % (need, target, MAX_SCALE, scale))
    else:
        reason = ""
    return {"need_sr": True, "scale": scale, "final": final, "reason": reason}
