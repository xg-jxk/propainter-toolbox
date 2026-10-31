# -*- coding: utf-8 -*-
"""日志分隔行：把"每一条视频"的开始与结束在日志里明确分开。

纯函数，GUI 和 CLI 共用；GUI 里再按类别上色（颜色常量在下面）。
文件日志（app.log）只会拿到纯文本，所以分隔符本身必须自己可读。
"""

SEP = "━"
SEP_WIDTH = 60

# 深色日志底（#0f1420）上的配色
COLOR_START = "#5bc0ff"      # 青色：单条开始
COLOR_META = "#8fa3c0"       # 灰色：源/目标/档位
COLOR_DONE = "#4ade80"       # 绿色：完成
COLOR_SKIP = "#c9d4e6"       # 灰白：跳过
COLOR_FAIL = "#ff7b72"       # 红色：失败
COLOR_CANCEL = "#f5c451"     # 黄色：取消
COLOR_QUEUE = "#7aa2f7"      # 蓝色：队列级

_STATE_STYLE = {
    "done": ("✔", "完成", COLOR_DONE),
    "skip": ("⏭", "跳过", COLOR_SKIP),
    "fail": ("✘", "失败", COLOR_FAIL),
    "cancel": ("⛔", "已取消", COLOR_CANCEL),
}


def _short(text, limit=30):
    s = str(text or "")
    return s if len(s) <= limit else s[:limit - 1] + "…"


def bar(text="", width=SEP_WIDTH):
    """一条分隔线；带标题时左边两条、右边补满。"""
    text = str(text or "")
    if not text:
        return SEP * int(width)
    pad = max(6, int(width) - len(text) - 2)
    return "%s %s %s" % (SEP * 2, text, SEP * pad)


def start_line(index, total, name):
    """单条视频的开始分隔：━━ 【2/5】17c5…mp4 ━━…"""
    head = "【%d/%d】%s" % (int(index), int(total), _short(name))
    return bar(head)


def meta_line(src_w=0, src_h=0, dst_w=0, dst_h=0, preset="", preview=False):
    """开始分隔下面那行灰字：源 → 目标 · 档位 · 测试模式。"""
    parts = []
    if src_w and src_h:
        if dst_w and dst_h:
            parts.append("源 %d×%d → %d×%d" % (src_w, src_h, dst_w, dst_h))
        else:
            parts.append("源 %d×%d" % (src_w, src_h))
    if preset:
        parts.append("档位「%s」" % preset)
    if preview:
        parts.append("测试模式")
    return " · ".join(parts)


def state_style(state):
    """state → (符号, 文字, 颜色)。"""
    return _STATE_STYLE.get(str(state), ("•", str(state), COLOR_META))


def end_line(state, detail=""):
    """单条视频的结束行：✔ 完成：…（2.7 MB，用时 42s） ━━…"""
    sym, word, _color = state_style(state)
    text = "%s %s" % (sym, word)
    if detail:
        text += "：%s" % str(detail)
    return "%s %s" % (text, SEP * 8)


def queue_line(text):
    """队列级分隔：══ 开始处理 5 个文件 ══…"""
    text = str(text or "")
    pad = max(6, SEP_WIDTH - len(text) - 2)
    return "%s %s %s" % ("═" * 2, text, "═" * pad)
