# -*- coding: utf-8 -*-
"""参数说明：每个参数配一个「i」小图标，悬停显示详细解释。

文案原则：先说"这是什么"，再说"怎么调"，最后给默认值/建议值。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .bubble import HelpIcon

# key -> (标题, 说明, 建议/默认)
PARAM_HELP = {
    "test_mode": (
        "测试模式",
        "只处理一小段（默认 3 秒）用于预览效果，输出到源目录、文件名加 _预览，不会覆盖正式成品。",
        "起始秒数可改：想检查片头就设 0，想跳过开场就填几秒；确认效果后再关掉它跑整段。",
    ),
    "preset": (
        "整体档位",
        "一次性把「外扩 padding / 分段 subvideo / 画质 crf」调到推荐组合；不会改变是否启用区域修复或超分。",
        "快速更省显存、平衡是默认、高质量更慢但细节更多。",
    ),
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
        "外扩范围",
        "在目标框外再扩出多少比例，给模型更多上下文参考。",
        "默认 0.45。残留鬼影就调到 0.6；边缘发糊就降到 0.3。",
    ),
    "crf": (
        "画质",
        "三档：高清 17、标准 20、省体积 23。数值越小越清晰、文件越大。",
        "默认 17。输出会自动按分辨率封顶码率，所以不用再担心 4x 时体积失控。",
    ),
    "scale": (
        "目标分辨率（统一长边）",
        "所有成品统一到这个长边：1080p=1920、2K=2560、4K=3840、8K=7680。"
        "源比它小就超分到刚好够，源比它大就跳过超分只缩小。",
        "批量上传选同一个档，输出尺寸就一致；16:9 素材会吸附到 1920×1080 这类标准尺寸。",
    ),
    "denoise": (
        "降噪强度",
        "Real-CUGAN 的降噪档位：不降噪 / 弱 / 中 / 强，强度越高画面越干净、细节也越少。",
        "自动 = 高度 <720 用「强」，否则用「弱」。1080p 干净源建议选「不降噪」。",
    ),
    "out_dir": (
        "输出目录",
        "结果写到哪里。留空 = 与源视频同目录，文件名加后缀（_已修复 / _1080p / _已修复_4K）。",
        "重名会自动加 (2)(3)，不会覆盖已有文件。",
    ),
    "model": (
        "超分模型",
        "models-pro 细节更好、速度略慢，但上游只提供 2x/3x；models-se 更保守、纹理更平，4x 只能用 se。",
        "默认 models-pro；选 4x 时会自动切到 models-se，日志里会写明。",
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



def bubble_html(key):
    """深色气泡用的富文本（标题白、正文浅灰、建议更暗）。"""
    title, body, tip = PARAM_HELP[key]
    html = ("<p style='margin:0 0 6px 0'><b style='color:#ffffff;font-size:13px'>%s</b></p>"
            "<p style='margin:0;color:#dbe4f3'>%s</p>" % (title, body))
    if tip:
        html += "<p style='margin:8px 0 0 0;color:#93a5c0'>%s</p>" % tip
    return html

def info_icon(key, parent=None):
    return HelpIcon(bubble_html(key), tooltip_html(key), parent)


def attach(widget, key):
    """控件本身也挂说明：气泡用浅色版（bubble_html），原生 tooltip 保留一份。"""
    widget.setToolTip(tooltip_html(key))
    widget.setProperty("bubble_html", bubble_html(key))
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

#: 字段下方的一句简介（不超过 20 字，长文见 PARAM_HELP）
SHORT_HINTS = {
    "mode": "勾选后这一轮做区域修复",
    "detect": "四角自动找浅色角标",
    "rect": "手动画框，最稳",
    "mask": "逐帧精确指定区域",
    "padding": "越大上下文越多，残留鬼影可调 0.6",
    "scale": "按源尺寸自动换算倍率",
    "denoise": "越强越干净，细节也越少",
    "model": "models-pro 无 4x，会自动换 se",
    "out_dir": "留空 = 与源视频同目录",
    "crf": "高=17，中=20，低=23",
    "test_mode": "只跑一小段，输出 _预览 文件",
    "open_when_done": "跑完自动打开文件夹",
    "preset": "只调修复上下文，不动画质",
}
