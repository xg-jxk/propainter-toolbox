# -*- coding: utf-8 -*-
"""三块设置面板：区域修复 / 超分 / 输出，以及三档预设。

每个配置项统一为「label + i / 控件 / 一句简介」，一项一行。
"""
import math
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from pplib.const import DEFAULT_MAX_OUTPUT_LONG
from pplib.scaling import final_size, plan_scale
from pplib.options import default_out

from .help import SHORT_HINTS, info_icon
from .widgets import Collapsible, Field, ModuleCard, SegmentedControl

PRESETS = {
    "fast": {
        "title": "快速",
        "desc": "显存占用最小、最快：上下文更小，修复还原度略低",
        "padding": 0.35, "subvideo": 20,
    },
    "balanced": {
        "title": "平衡",
        "desc": "默认推荐：速度与修复效果兼顾",
        "padding": 0.45, "subvideo": 40,
    },
    "detail": {
        "title": "精修",
        "desc": "上下文更大：修复更稳，但更慢、更吃显存",
        "padding": 0.55, "subvideo": 80,
    },
}

DETECT_OPTIONS = [("自动定位", "auto"), ("手动矩形", "rect"), ("逐帧掩码", "mask")]
QUALITY_OPTIONS = [("高", 17), ("中", 20), ("低", 23)]


def quality_from_crf(value):
    """把任意 crf（含旧配置里的 14/22）映射到三档之一。"""
    try:
        crf = int(value)
    except (TypeError, ValueError):
        return 17
    if crf <= 17:
        return 17
    return 20 if crf <= 20 else 23

DENOISE_OPTIONS = [("自动（按分辨率）", "auto"), ("不降噪", -1), ("弱", 1),
                   ("中", 2), ("强", 3)]
MODEL_OPTIONS = [("models-pro（推荐）", "models-pro"), ("models-se", "models-se")]

#: 目标档位 = 输出长边（统一尺寸）；没有「最高」档——那与统一尺寸自相矛盾
TARGETS = [("1080p", "1080p", 1920), ("2K", "2K", 2560), ("4K", "4K", 3840),
           ("8K", "8K", 7680)]


def target_label(key):
    for k, label, _long in TARGETS:
        if k == key:
            return label
    return key


def _k_label(width, height):
    if not (width and height):
        return ""
    if width >= 15000:
        return "16K"
    if width >= 7600:
        return "8K"
    if width >= 5000:
        return "5K"
    if width >= 3700:
        return "4K"
    if width >= 2500:
        return "2K"
    if width >= 1880:
        return "1080p"
    return "%dp" % int(height)


def _row(*widgets, **kw):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    stretch_first = kw.get("stretch_first", True)
    for i, x in enumerate(widgets):
        lay.addWidget(x, 1 if (stretch_first and i == 0) else 0)
    return w


def _spin(lo, hi, val, suffix=""):
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setValue(val)
    if suffix:
        sp.setSuffix(suffix)
    return sp


def _combo(options, current=None):
    cb = QComboBox()
    for label, data in options:
        cb.addItem(label, data)
    if current is not None:
        idx = cb.findData(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
    return cb


def _hint(key, default=""):
    return SHORT_HINTS.get(key, default)


class RepairPanel(ModuleCard):
    """区域修复：定位方式 / 外扩范围。

    分段、掩码膨胀、匹配阈值、参考帧步长都是算法内部的量，界面上不再暴露：
    分段跟随档位预设（显存不够时 repair.py 会自动减半重试）。
    """

    def __init__(self, parent=None, enabled=True):
        super().__init__("区域修复", "mode", checked=enabled, parent=parent)

        self.detect = _combo(DETECT_OPTIONS, "auto")
        self.add_field(Field("detect", "定位方式", self.detect, _hint("detect")))

        self._detect_extra = QWidget()
        ex = QVBoxLayout(self._detect_extra)
        ex.setContentsMargins(0, 0, 0, 0)
        ex.setSpacing(10)

        self.auto_hint = QLabel("")
        self.auto_hint.setVisible(False)
        ex.addWidget(self.auto_hint)

        self.rect = QLineEdit()
        self.rect.setPlaceholderText("x,y,w,h   例如 1314,918,320,120")
        ex.addWidget(self.rect)

        self.mask = QLineEdit()
        self.mask.setPlaceholderText("掩码目录，或单张掩码 png")
        self.btn_mask = QPushButton("选择…")
        self.btn_mask.setFixedWidth(64)
        self.mask_row = _row(self.mask, self.btn_mask)
        ex.addWidget(self.mask_row)
        self.vbox.addWidget(self._detect_extra)

        self.add_separator()

        self.padding = QDoubleSpinBox()
        self.padding.setRange(0.10, 1.20)
        self.padding.setSingleStep(0.05)
        self.padding.setDecimals(2)
        self.padding.setValue(0.45)
        self.padding.setFixedWidth(78)
        self.padding_slider = QSlider(Qt.Orientation.Horizontal)
        self.padding_slider.setRange(10, 120)
        self.padding_slider.setValue(45)
        self.add_field(Field("padding", "外扩范围",
                             _row(self.padding_slider, self.padding),
                             _hint("padding")))
        self.padding_slider.valueChanged.connect(lambda v: self.padding.setValue(v / 100.0))
        self.padding.valueChanged.connect(
            lambda v: self.padding_slider.setValue(int(round(v * 100))))

        self._subvideo = 40            # 跟随档位预设，界面上不展示
        self.vbox.addStretch(1)

        self.detect.currentIndexChanged.connect(self._on_detect_changed)
        self._on_detect_changed()

    def _on_detect_changed(self, _idx=None):
        page = self.detect.currentData() or "auto"
        self._detect_extra.setVisible(page != "auto")   # 自动定位时不需要额外控件
        self.rect.setVisible(page == "rect")
        self.mask_row.setVisible(page == "mask")

    # ---------------------------------------------------------- 取值
    def detect_value(self):
        return self.detect.currentData() or "auto"

    def set_detect(self, key):
        idx = self.detect.findData(key)
        if idx >= 0:
            self.detect.setCurrentIndex(idx)

    def options(self):
        detect = self.detect_value()
        return {
            "auto": detect == "auto",
            "rect": self.rect.text().strip() if detect == "rect" else None,
            "mask": self.mask.text().strip() if detect == "mask" else None,
            "padding": round(self.padding.value(), 2),
            "subvideo": int(self._subvideo),
            "mask_dilation": 2,
            "neighbor": 10,
            "ref_stride": 12,
            "crf": 17,
            "encoder": "auto",
            "detect_thr": 0.62,
            "keep": False,
        }

    def apply_preset(self, preset):
        self.padding.setValue(float(preset["padding"]))
        self._subvideo = int(preset["subvideo"])


class SRPanel(ModuleCard):
    """超分：目标分辨率（统一长边）/ 降噪。

    目标档位 = **输出长边**：源小就超分到恰好这个长边，源已经达标就跳过超分只缩小，
    4x 仍够不到目标时用 4x 结果补齐 —— 批量出片的尺寸始终一致。
    """

    def __init__(self, parent=None, enabled=False):
        super().__init__("超分（Real-CUGAN）", "scale", checked=enabled, parent=parent)

        self.target = QComboBox()
        self.add_field(Field("scale", "目标分辨率", self.target, ""))
        self.scale_hint = QLabel("加入视频后按长边自动换算")
        self.scale_hint.setObjectName("fieldHint")
        self.scale_hint.setWordWrap(True)
        self.vbox.addWidget(self.scale_hint)

        self._src_w, self._src_h = 0, 0
        self._target_key = "1080p"
        self._rebuild()
        self.target.currentIndexChanged.connect(self._on_target_changed)

        self.add_separator()

        self.denoise = _combo(DENOISE_OPTIONS, "auto")
        self.add_field(Field("denoise", "降噪", self.denoise, _hint("denoise")))
        self.vbox.addStretch(1)

    # ---------------------------------------------------------- 档位
    def set_source_size(self, width, height):
        self._src_w, self._src_h = int(width or 0), int(height or 0)
        self._rebuild()

    def target_key(self):
        return self._target_key

    def want_key(self):
        """兼容旧调用：现在目标就是用户选的那一档。"""
        return self._target_key

    def target_long(self):
        for key, _label, long_side in TARGETS:
            if key == self._target_key:
                return long_side
        return 1920

    def cap_limit(self):
        return DEFAULT_MAX_OUTPUT_LONG

    def plan(self, src_w=None, src_h=None):
        """按当前档位算这一条怎么出片（缩到哪、要不要跑模型）。"""
        w = self._src_w if src_w is None else int(src_w or 0)
        h = self._src_h if src_h is None else int(src_h or 0)
        if not (w and h):
            return {"need_sr": True, "scale": 2, "final": (0, 0), "reason": ""}
        return plan_scale(w, h, self.target_long(), self.cap_limit())

    def set_target(self, key):
        self._target_key = key
        if not self._select(key):
            self._target_key = "1080p"
            self._select("1080p")
        self._refresh_hint()

    def _select(self, key):
        for i in range(self.target.count()):
            data = self.target.itemData(i)
            if data and data[0] == key:
                prev = self.target.blockSignals(True)
                self.target.setCurrentIndex(i)
                self.target.blockSignals(prev)
                self._target_key = key
                return True
        return False

    def _on_target_changed(self, _idx):
        data = self.target.currentData()
        if data:
            self._target_key = data[0]
        self._refresh_hint()

    def _item_text(self, key, target_long):
        label = target_label(key)
        if not (self._src_w and self._src_h):
            return "%s · 长边 %d" % (label, target_long)
        final = final_size(self._src_w, self._src_h, target_long, self.cap_limit())
        return "%s · 输出 %d×%d" % (label, final[0], final[1])

    def _rebuild(self):
        blocked = self.target.blockSignals(True)
        self.target.clear()
        for key, _label, target_long in TARGETS:
            self.target.addItem(self._item_text(key, target_long), (key, target_long))
        self.target.blockSignals(blocked)
        if not self._select(self._target_key):
            self._select("1080p")
        self._refresh_hint()

    def _refresh_hint(self):
        if not (self._src_w and self._src_h):
            self.scale_hint.setText("加入视频后按长边换算：小图超分到目标，大图只缩小")
            return
        w, h = self._src_w, self._src_h
        plan = self.plan()
        fw, fh = plan["final"]
        if not plan["need_sr"]:
            txt = "源 %d×%d 长边已到 %d：跳过超分，缩到 %d×%d" % (
                w, h, max(w, h), fw, fh)
        else:
            txt = "源 %d×%d → %dx 超分 %d×%d → 缩到 %d×%d" % (
                w, h, plan["scale"], w * plan["scale"], h * plan["scale"], fw, fh)
            if plan.get("reason"):
                txt += " · " + plan["reason"]
        if max(fw, fh) > 4096:
            txt += " · 超 4096，自动用 CPU 编码"
        self.scale_hint.setText(txt)

    # ---------------------------------------------------------- 取值
    def options(self, src_w=None, src_h=None):
        plan = self.plan(src_w, src_h)
        denoise = self.denoise.currentData()
        return {
            "scale": int(plan["scale"] or 2),
            "target_long": self.target_long(),
            "skip_reason": "",
            "max_output_long": self.cap_limit(),
            "denoise": None if denoise == "auto" else int(denoise),
            "model": "auto",
            "crf": 17,
            "encoder": "auto",
            "keep": False,
        }

    def apply_preset(self, preset):
        pass  # 预设不改目标分辨率
class OutputPanel(QFrame):
    """输出：目录 / 画质 / 编码器 / 测试模式（两张卡共用）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("moduleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("输出")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        outer.addLayout(head)

        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("留空 = 与源视频同目录")
        self.btn_outdir = QPushButton("选择…")
        self.btn_outdir.setFixedWidth(64)
        outer.addWidget(Field("out_dir", "输出目录",
                              _row(self.out_dir, self.btn_outdir), ""))

        self.preview = QLabel("将输出：—")
        self.preview.setObjectName("fieldHint")
        self.preview.setWordWrap(True)
        outer.addWidget(self.preview)

        self.quality = SegmentedControl(QUALITY_OPTIONS, 17)
        outer.addWidget(Field("crf", "画质", self.quality, _hint("crf")))
        outer.addStretch(1)

    # ---------------------------------------------------------- 取值
    def out_dir_text(self):
        return self.out_dir.text().strip()

    def crf_value(self):
        value = self.quality.value()
        return int(value if value is not None else 17)

    def encoder_value(self):
        """编码器固定自动：有 NVENC 用显卡，超 4096 自动退 CPU。"""
        return "auto"

    def out_path(self, video, mode, scale, preview=False, tag=""):
        d = self.out_dir_text()
        if not d:
            return None
        base = default_out(video, mode, scale, preview=preview, tag=tag)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return None
        return os.path.join(d, os.path.basename(base))

    def set_preview(self, text):
        self.preview.setText(text)


class TestPanel(QFrame):
    """测试模式：只处理一小段，输出 _预览 文件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("moduleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("测试模式")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addWidget(info_icon("test_mode"))
        head.addStretch(1)
        outer.addLayout(head)

        self.test_mode = QCheckBox("只处理一小段")
        self.test_seconds = _spin(1, 60, 3, " 秒")
        self.test_seconds.setFixedWidth(78)
        self.test_start = QDoubleSpinBox()
        self.test_start.setRange(0.0, 3600.0)
        self.test_start.setDecimals(1)
        self.test_start.setSingleStep(0.5)
        self.test_start.setSuffix(" 秒")
        self.test_start.setFixedWidth(88)

        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self.test_mode)
        bv.addWidget(_row(QLabel("时长"), self.test_seconds,
                          QLabel("起始"), self.test_start,
                          stretch_first=False))
        outer.addWidget(box)

        self.hint = QLabel(_hint("test_mode"))
        self.hint.setObjectName("fieldHint")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

        self.test_mode.toggled.connect(self._sync)
        self._sync(False)

    def _sync(self, on):
        self.test_seconds.setEnabled(bool(on))
        self.test_start.setEnabled(bool(on))

    def clip_seconds(self):
        return int(self.test_seconds.value()) if self.test_mode.isChecked() else 0

    def clip_start(self):
        return float(self.test_start.value()) if self.test_mode.isChecked() else 0.0
