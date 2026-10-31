# -*- coding: utf-8 -*-
"""三块设置面板：区域修复 / 超分 / 输出，以及三档预设。

每个配置项统一为「label + i / 控件 / 一句简介」，一项一行。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from pplib.const import DEFAULT_MAX_OUTPUT_LONG, OUTPUT_LIMITS
from pplib.options import default_out

from .help import SHORT_HINTS
from .widgets import Collapsible, Field, ModuleCard, SegmentedControl

PRESETS = {
    "fast": {
        "title": "快速",
        "desc": "显存小 / 赶时间：上下文更小、码率更低",
        "padding": 0.35, "subvideo": 20, "crf": 22,
    },
    "balanced": {
        "title": "平衡",
        "desc": "默认推荐：质量与速度兼顾",
        "padding": 0.45, "subvideo": 40, "crf": 17,
    },
    "quality": {
        "title": "高质量",
        "desc": "更大上下文 + 更高码率，慢一些",
        "padding": 0.55, "subvideo": 80, "crf": 14,
    },
}

DETECT_OPTIONS = [("自动定位", "auto"), ("手动矩形", "rect"), ("逐帧掩码", "mask")]
QUALITY_OPTIONS = [("高", 17), ("中", 20), ("低", 23)]
DENOISE_OPTIONS = [("自动（按分辨率）", "auto"), ("-1 不降噪", -1), ("0 保守", 0),
                   ("1 轻", 1), ("2 中", 2), ("3 强", 3)]
MODEL_OPTIONS = [("models-pro（推荐）", "models-pro"), ("models-se", "models-se")]

TARGETS = [("1080p", "1080p", 1920), ("2K", "2K", 2560), ("4K", "4K", 3840),
           ("8K", "8K", 7680), ("max", "最高", 0)]
SCALES = (2, 3, 4)


def target_label(key):
    for k, label, _long in TARGETS:
        if k == key:
            return label
    return key


def limit_label(limit):
    for label, value in OUTPUT_LIMITS:
        if value == limit:
            return label
    return str(limit)


def pick_scale(src_w, src_h, target_long, limit=DEFAULT_MAX_OUTPUT_LONG):
    """按长边算倍率，并受输出上限约束。返回 (scale, status)。"""
    if not (src_w and src_h):
        return 2, "unknown"
    long_side = max(int(src_w), int(src_h))
    limit = int(limit or 0)
    allowed = list(SCALES)
    if limit > 0:
        allowed = [s for s in SCALES if long_side * s <= limit]
        if not allowed:
            return 0, "too_big"
    if not target_long:
        s = max(allowed)
        return s, ("max" if s == 4 else "max_limited")
    need = float(target_long) / float(long_side)
    if need < 2 - 1e-6:
        return 2, "unreachable"
    for s in allowed:
        if long_side * s >= target_long - 0.5:
            return s, ("ok" if abs(long_side * s - target_long) <= 1 else "up")
    s = max(allowed)
    return s, ("capped" if s == 4 else "capped_limit")


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
    """区域修复：定位方式 / 外扩 / 高级。"""

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
        self.padding.setRange(0.0, 1.5)
        self.padding.setSingleStep(0.05)
        self.padding.setDecimals(2)
        self.padding.setValue(0.45)
        self.padding.setFixedWidth(78)
        self.padding_slider = QSlider(Qt.Orientation.Horizontal)
        self.padding_slider.setRange(10, 120)
        self.padding_slider.setValue(45)
        self.add_field(Field("padding", "外扩 padding",
                             _row(self.padding_slider, self.padding),
                             _hint("padding")))
        self.padding_slider.valueChanged.connect(lambda v: self.padding.setValue(v / 100.0))
        self.padding.valueChanged.connect(
            lambda v: self.padding_slider.setValue(int(round(v * 100))))

        self.advanced = Collapsible("高级参数")
        self.subvideo = _spin(10, 200, 40, " 帧")
        self.advanced.add_field(Field("subvideo", "分段 subvideo", self.subvideo,
                                      _hint("subvideo")))
        self.mask_dilation = _spin(0, 20, 2, " px")
        self.advanced.add_field(Field("mask_dilation", "掩码膨胀", self.mask_dilation,
                                      _hint("mask_dilation")))
        self.detect_thr = QDoubleSpinBox()
        self.detect_thr.setRange(0.30, 0.95)
        self.detect_thr.setSingleStep(0.01)
        self.detect_thr.setDecimals(2)
        self.detect_thr.setValue(0.62)
        self.advanced.add_field(Field("detect_thr", "匹配阈值", self.detect_thr,
                                      _hint("detect_thr")))
        self.ref_stride = _spin(1, 30, 12)
        self.advanced.add_field(Field("ref_stride", "参考帧步长", self.ref_stride,
                                      _hint("ref_stride")))
        self.vbox.addWidget(self.advanced)
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
            "subvideo": self.subvideo.value(),
            "mask_dilation": self.mask_dilation.value(),
            "neighbor": 10,
            "ref_stride": self.ref_stride.value(),
            "crf": 17,
            "encoder": "auto",
            "detect_thr": round(self.detect_thr.value(), 2),
            "keep": False,
        }

    def apply_preset(self, preset):
        self.padding.setValue(float(preset["padding"]))
        self.subvideo.setValue(int(preset["subvideo"]))


class SRPanel(ModuleCard):
    """超分：目标分辨率 / 降噪 / 高级（输出上限、模型）。"""

    def __init__(self, parent=None, enabled=False):
        super().__init__("超分（Real-CUGAN）", "scale", checked=enabled, parent=parent)

        self.cap = QComboBox()
        for label, value in OUTPUT_LIMITS:
            if not value:
                text = "不限制（按 4x 跑）"
            elif value == DEFAULT_MAX_OUTPUT_LONG:
                text = "上限 %s（推荐）" % label
            else:
                text = "上限 %s" % label
            self.cap.addItem(text, value)

        self.target = QComboBox()
        self.add_field(Field("scale", "目标分辨率", self.target, ""))
        self.scale_hint = QLabel("加入视频后按源长边自动换算倍率")
        self.scale_hint.setObjectName("fieldHint")
        self.scale_hint.setWordWrap(True)
        self.vbox.addWidget(self.scale_hint)

        self._src_w, self._src_h = 0, 0
        self._target_key = "4K"
        self._rebuild()
        self.target.currentIndexChanged.connect(self._on_target_changed)

        self.add_separator()

        self.denoise = _combo(DENOISE_OPTIONS, "auto")
        self.add_field(Field("denoise", "降噪", self.denoise, _hint("denoise")))

        self.advanced = Collapsible("高级参数")
        self.advanced.add_field(Field("cap", "输出上限", self.cap, _hint("cap")))
        self.model = _combo(MODEL_OPTIONS, "models-pro")
        self.advanced.add_field(Field("model", "模型", self.model, _hint("model")))
        self.vbox.addWidget(self.advanced)
        self.vbox.addStretch(1)
        self.cap.currentIndexChanged.connect(lambda _i: self._rebuild())

    # ---------------------------------------------------------- 档位
    def set_source_size(self, width, height):
        self._src_w, self._src_h = int(width or 0), int(height or 0)
        self._rebuild()

    def target_key(self):
        data = self.target.currentData()
        return data[0] if data else self._target_key

    def target_long(self):
        data = self.target.currentData()
        return int(data[1]) if data else 3840

    def cap_limit(self):
        value = self.cap.currentData()
        return int(value) if value is not None else DEFAULT_MAX_OUTPUT_LONG

    def set_cap(self, limit):
        idx = self.cap.findData(int(limit or 0))
        if idx >= 0:
            self.cap.setCurrentIndex(idx)

    def set_target(self, key):
        for i in range(self.target.count()):
            data = self.target.itemData(i)
            if not data:
                continue
            item = self.target.model().item(i)
            if data[0] == key and (item is None or item.isEnabled()):
                self.target.setCurrentIndex(i)
                self._target_key = key
                self._refresh_hint()
                return
        for i in range(self.target.count() - 1, -1, -1):
            item = self.target.model().item(i)
            if item is not None and item.isEnabled():
                self.target.setCurrentIndex(i)
                self._target_key = self.target_key()
                break
        self._refresh_hint()

    def _on_target_changed(self, _idx):
        self._target_key = self.target_key()
        self._refresh_hint()

    def _item_text(self, key, target_long):
        """下拉里保持短：细节放在下方提示行。"""
        label = target_label(key)
        if not (self._src_w and self._src_h):
            return label if target_long else "最高 · 按源自适应"
        limit = self.cap_limit()
        scale, status = pick_scale(self._src_w, self._src_h, target_long, limit)
        if status == "too_big":
            return "%s · 源超上限" % label
        if status == "unreachable":
            return "%s · 源已超" % label
        ow, oh = self._src_w * scale, self._src_h * scale
        text = "%s · %dx · %d×%d" % (label, scale, ow, oh)
        if status in ("capped", "capped_limit"):
            text = "⚠ " + text
        return text

    def _rebuild(self):
        prev = self._target_key
        blocked = self.target.blockSignals(True)
        self.target.clear()
        enabled_keys = []
        limit = self.cap_limit()
        for key, _label, target_long in TARGETS:
            _, status = pick_scale(self._src_w, self._src_h, target_long, limit)
            enabled = status not in ("unreachable", "too_big")
            self.target.addItem(self._item_text(key, target_long), (key, target_long))
            item = self.target.model().item(self.target.count() - 1)
            if item is not None:
                item.setEnabled(enabled)
            if enabled:
                enabled_keys.append(key)
        self.target.blockSignals(blocked)

        want = prev if prev in enabled_keys else (
            "4K" if "4K" in enabled_keys else ("8K" if "8K" in enabled_keys else None))
        if want is None:
            want = enabled_keys[-1] if enabled_keys else None
        if want is not None:
            self.set_target(want)
        else:
            self._refresh_hint()

    def _refresh_hint(self):
        if not (self._src_w and self._src_h):
            self.scale_hint.setText("加入视频后按源长边自动换算倍率")
            return
        limit = self.cap_limit()
        key = self.target_key()
        scale, status = pick_scale(self._src_w, self._src_h, self.target_long(), limit)
        if status == "too_big":
            self.scale_hint.setText(
                "源长边 %d 已超过「%s」上限，无法再放大" % (
                    max(self._src_w, self._src_h), limit_label(limit)))
            return
        ow, oh = self._src_w * scale, self._src_h * scale
        txt = "源 %d×%d → %s 用 %dx · %d×%d（%s）" % (
            self._src_w, self._src_h, target_label(key), scale, ow, oh, _k_label(ow, oh))
        if status == "up":
            txt += " · 该源无法精确命中，取上一档"
        elif status == "capped":
            txt += " · 4x 已是模型上限，达不到 %s" % target_label(key)
        elif status == "capped_limit":
            txt += " · 再放大就超「%s」上限，已截住" % limit_label(limit)
        elif status == "max_limited":
            txt += " · 4x 会超「%s」上限，最高只到 %dx" % (limit_label(limit), scale)
        elif status == "max":
            txt += " · 模型支持的最高倍率"
        if max(ow, oh) > 4096:
            txt += " · 超 4096，自动用 CPU 编码"
        self.scale_hint.setText(txt)

    # ---------------------------------------------------------- 取值
    def options(self, src_w=None, src_h=None):
        w = self._src_w if src_w is None else int(src_w or 0)
        h = self._src_h if src_h is None else int(src_h or 0)
        limit = self.cap_limit()
        scale, status = pick_scale(w, h, self.target_long(), limit)
        if status == "too_big":
            scale = 0
        denoise = self.denoise.currentData()
        return {
            "scale": int(scale or 0),
            "max_output_long": limit,
            "denoise": None if denoise == "auto" else int(denoise),
            "model": self.model.currentData(),
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

        self.encoder = _combo([("自动（有 NVENC 就用）", "auto"),
                               ("NVIDIA NVENC", "nvenc"), ("CPU x264", "x264")], "auto")
        outer.addWidget(Field("encoder", "编码器", self.encoder, _hint("encoder")))

        self.test_mode = QCheckBox("只处理一小段")
        self.test_seconds = _spin(1, 60, 3, " 秒")
        self.test_seconds.setFixedWidth(78)
        self.test_start = QDoubleSpinBox()
        self.test_start.setRange(0.0, 3600.0)
        self.test_start.setDecimals(1)
        self.test_start.setSingleStep(0.5)
        self.test_start.setSuffix(" 秒")
        self.test_start.setFixedWidth(88)
        test_box = QWidget()
        tv = QVBoxLayout(test_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(6)
        tv.addWidget(self.test_mode)
        tv.addWidget(_row(QLabel("时长"), self.test_seconds,
                          QLabel("起始"), self.test_start,
                          stretch_first=False))
        outer.addWidget(Field("test_mode", "测试模式", test_box, _hint("test_mode")))

        self.advanced = Collapsible("高级参数")
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(17)
        self.advanced.add_field(Field(None, "crf 数值", self.crf,
                                      "0 最清晰、51 最糊，常用 17~23"))
        outer.addWidget(self.advanced)
        outer.addStretch(1)

        self.quality.changed.connect(self._on_quality)
        self.crf.valueChanged.connect(self._on_crf_changed)
        self.test_mode.toggled.connect(self._sync_test)
        self._sync_test(False)

    def _sync_test(self, on):
        self.test_seconds.setEnabled(bool(on))
        self.test_start.setEnabled(bool(on))

    def _on_quality(self, value):
        if int(self.crf.value()) != int(value):
            self.crf.setValue(int(value))

    def _on_crf_changed(self, value):
        match = [d for _, d in QUALITY_OPTIONS if int(d) == int(value)]
        if match:
            self.quality.set_value(match[0])
        else:
            for btn, _data in self.quality._buttons:
                btn.setChecked(False)
            self.quality._current = value

    # ---------------------------------------------------------- 取值
    def clip_seconds(self):
        return int(self.test_seconds.value()) if self.test_mode.isChecked() else 0

    def clip_start(self):
        return float(self.test_start.value()) if self.test_mode.isChecked() else 0.0

    def out_dir_text(self):
        return self.out_dir.text().strip()

    def crf_value(self):
        return int(self.crf.value())

    def encoder_value(self):
        return self.encoder.currentData()

    def out_path(self, video, mode, scale, preview=False):
        d = self.out_dir_text()
        if not d:
            return None
        base = default_out(video, mode, scale, preview=preview)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return None
        return os.path.join(d, os.path.basename(base))

    def set_preview(self, text):
        self.preview.setText(text)
