# -*- coding: utf-8 -*-
"""参数说明：每个参数配一个「i」小图标，悬停显示详细解释。

文案原则：先说"这是什么"，再说"怎么调"，最后给默认值/建议值。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

# key -> (标题, 说明, 建议/默认)
PARAM_HELP = {
    "mode": (
        "区域修复（模块开关）",
        "勾选后这一轮会做区域修复；和右侧「超分」同时勾选就是先修复再放大。",
        "区域修复会抹掉指定区域并用前后帧补全；超分负责放大 2/3/4 倍。",
    ),
    "detect": (
        "区域定位",
        "告诉程序要修哪块区域。自动 = 在四角找浅色角标/文字；矩形 = 你给坐标；掩码 = 每帧一张黑白图。",
        "自动定位不准时，改用「手动矩形」最稳；目标会移动就用「逐帧掩码」。",
    ),
    "rect": (
        "手动矩形 x,y,w,h",
        "目标区域左上角坐标与宽高，单位像素。可以用截图工具量，例如 1314,918,320,120。",
        "宁可框大一点——外扩参数还会再放大一圈。",
    ),
    "mask": (
        "逐帧掩码",
        "每帧一张 png：白色（255）是要修掉的区域，黑色是保留。分辨率必须与视频一致。",
        "适合目标会移动、或同时有多个目标的情况。",
    ),
    "padding": (
        "外扩 padding",
        "在目标框外再扩出多少比例，给模型更多上下文参考。",
        "默认 0.45。残留鬼影就调到 0.6；边缘发糊就降到 0.3。",
    ),
    "subvideo": (
        "分段 subvideo",
        "长视频按这个帧数切成若干段分别处理：段越小越省显存，但衔接处略慢。",
        "默认 40。显存不足（CUDA out of memory）时降到 20。",
    ),
    "crf": (
        "画质 crf",
        "控制输出清晰度与体积：数值越小越清晰、文件越大。",
        "默认 17（接近无损）；20~23 体积明显变小，肉眼差异很小。",
    ),
    "encoder": (
        "编码器",
        "输出视频用什么编码。auto 检测到 NVENC 就用显卡编码（快 5~10 倍），否则用 CPU 的 x264。",
        "默认 auto；追求兼容性可选 x264。",
    ),
    "scale": (
        "超分倍率",
        "把视频放大几倍。2x 对应 1080p → 4K 这类常见场景。",
        "倍率越高越慢、越吃显存；4x 建议先拿一小段试。",
    ),
    "denoise": (
        "降噪强度",
        "Real-CUGAN 的降噪档位：-1 不降噪，0 保守，1~3 递增强度。",
        "自动 = 高度 <720 用 3，否则 0。1080p 干净源建议 0。",
    ),
    "out_dir": (
        "输出目录",
        "结果写到哪里。留空 = 与源视频同目录，文件名加后缀（_已修复 / _2x / _已修复_2x）。",
        "重名会自动加 (2)(3)，不会覆盖已有文件。",
    ),
    "mask_dilation": (
        "掩码膨胀",
        "把掩码边缘向外扩几个像素，避免修复后残留一圈毛边。",
        "默认 2 px；边缘有残影可加到 3~4。",
    ),
    "detect_thr": (
        "匹配阈值",
        "自动定位时逐帧模板匹配的置信度门槛：越高越严格，越容易判定跟丢。",
        "默认 0.62；镜头运动剧烈可降到 0.5。",
    ),
    "ref_stride": (
        "参考帧步长",
        "每隔多少帧取一张全局参考帧，用来保持长视频的颜色与纹理一致。",
        "默认 12；显存紧张可加大到 20。",
    ),
    "model": (
        "超分模型",
        "models-pro 细节更好、速度略慢；models-se 更保守、纹理更平。",
        "默认 models-pro。",
    ),
    "keep": (
        "保留中间文件",
        "把抽帧、裁剪、推理输出等临时文件留在磁盘上，便于排查问题。",
        "正常使用请保持关闭，否则一次可能多占几 GB。",
    ),
    "open_when_done": (
        "完成后打开输出目录",
        "整个队列跑完后自动用资源管理器打开输出目录。",
        "批量处理时建议关闭，避免反复弹窗。",
    ),
}


def tooltip_html(key):
    title, body, tip = PARAM_HELP[key]
    html = ("<p style='margin:0 0 4px 0'><b>%s</b></p>"
            "<p style='margin:0'>%s</p>" % (title, body))
    if tip:
        html += ("<p style='margin:6px 0 0 0;color:#5b6472'>%s</p>" % tip)
    return html


def info_icon(key, parent=None):
    lb = QLabel("i", parent)
    lb.setObjectName("infoIcon")
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lb.setFixedSize(15, 15)
    lb.setCursor(Qt.CursorShape.WhatsThisCursor)
    lb.setToolTip(tooltip_html(key))
    lb.setToolTipDuration(15000)
    return lb


def attach(widget, key):
    """给控件本身也挂一份同样的说明，扩大悬停热区。"""
    widget.setToolTip(tooltip_html(key))
    return widget


def label_with_info(text, key, parent=None):
    """「参数名 + i」的组合控件，放进网格当标签用。"""
    holder = QWidget(parent)
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(QLabel(text))
    lay.addWidget(info_icon(key))
    lay.addStretch(1)
    return holder


def checkbox_with_info(checkbox, key, parent=None):
    """复选框后面跟一个 i（复选框本身保留原对象，方便取状态）。"""
    holder = QWidget(parent)
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(checkbox)
    lay.addWidget(info_icon(key))
    lay.addStretch(1)
    return holder
