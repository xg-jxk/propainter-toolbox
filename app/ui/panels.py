# -*- coding: utf-8 -*-
"""三块设置面板：区域修复 / 超分 / 输出，以及三档预设。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from pplib.const import DEFAULT_MAX_OUTPUT_LONG, OUTPUT_LIMITS
from pplib.options import default_out

from .help import attach, checkbox_with_info, label_with_info
from .widgets import Collapsible, ModuleCard, SegmentedControl

#: 三档预设：只动"画质/上下文"这类数值，不动功能开关
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
SCALE_OPTIONS = [("2x", 2), ("3x", 3), ("4x", 4)]
QUALITY_OPTIONS = [("高", 17), ("中", 20), ("低", 23)]
DENOISE_OPTIONS = [("自动", "auto"), ("-1 不降噪", -1), ("0 保守", 0),
                   ("1 轻", 1), ("2 中", 2), ("3 强", 3)]
MODEL_OPTIONS = [("models-pro（推荐）", "models-pro"), ("models-se", "models-se")]



def _k_label(width, height):
    """按输出宽给出消费级分辨率叫法。"""
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



#: 分辨率档位：(键, 显示名, 目标长边)。0 表示"最高"，尽可能大
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
    """按长边算倍率，并受输出上限约束。返回 (scale, status)。

    status: unknown 无源 / unreachable 源已达目标 / ok 正好 / up 超出目标 /
            capped 4x 也到不了 / capped_limit 被输出上限截住 / max 最高 /
            max_limited 最高但受上限限制 / too_big 源已超过上限
    """
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


class RepairPanel(ModuleCard):
    """区域修复：定位方式 + 外扩 + 高级（分段/膨胀/阈值/参考帧）。"""

    def __init__(self, parent=None, enabled=True):
        super().__init__("区域修复（字幕 / 台标 / 杂物 / 角标）", "mode", checked=enabled, parent=parent)
        g = self.grid

        self.detect = SegmentedControl(DETECT_OPTIONS, "auto")
        g.addWidget(label_with_info("定位方式", "detect"), 0, 0)
        g.addWidget(attach(self.detect, "detect"), 0, 1, 1, 3)

        self.stack = QStackedWidget()
        hint = QLabel("自动在画面四角寻找浅色角标 / 文字，适合大多数情况")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.stack.addWidget(hint)

        self.rect = QLineEdit()
        self.rect.setPlaceholderText("x,y,w,h   例如 1314,918,320,120")
        self.stack.addWidget(self.rect)

        mask_page = QWidget()
        mrow = QHBoxLayout(mask_page)
        mrow.setContentsMargins(0, 0, 0, 0)
        self.mask = QLineEdit()
        self.mask.setPlaceholderText("掩码目录，或单张掩码 png")
        self.btn_mask = QPushButton("选择…")
        self.btn_mask.setFixedWidth(64)
        mrow.addWidget(self.mask, 1)
        mrow.addWidget(self.btn_mask)
        self.stack.addWidget(mask_page)

        g.addWidget(self.stack, 1, 0, 1, 4)

        row = QWidget()
        rlay = QHBoxLayout(row)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(8)
        self.padding = QDoubleSpinBox()
        self.padding.setRange(0.0, 1.5)
        self.padding.setSingleStep(0.05)
        self.padding.setDecimals(2)
        self.padding.setValue(0.45)
        self.padding.setFixedWidth(78)
        self.padding_slider = QSlider(Qt.Orientation.Horizontal)
        self.padding_slider.setRange(10, 120)
        self.padding_slider.setValue(45)
        rlay.addWidget(self.padding_slider, 1)
        rlay.addWidget(attach(self.padding, "padding"))
        g.addWidget(label_with_info("外扩 padding", "padding"), 2, 0)
        g.addWidget(row, 2, 1, 1, 3)
        self.padding_slider.valueChanged.connect(lambda v: self.padding.setValue(v / 100.0))
        self.padding.valueChanged.connect(
            lambda v: self.padding_slider.setValue(int(round(v * 100))))

        self.advanced = Collapsible("高级：分段 / 掩码膨胀 / 匹配阈值 / 参考帧")
        adv = self.advanced.grid
        self.subvideo = _spin(10, 200, 40, " 帧")
        adv.addWidget(label_with_info("分段 subvideo", "subvideo"), 0, 0)
        adv.addWidget(attach(self.subvideo, "subvideo"), 0, 1)
        self.mask_dilation = _spin(0, 20, 2, " px")
        adv.addWidget(label_with_info("掩码膨胀", "mask_dilation"), 0, 2)
        adv.addWidget(attach(self.mask_dilation, "mask_dilation"), 0, 3)
        self.detect_thr = QDoubleSpinBox()
        self.detect_thr.setRange(0.30, 0.95)
        self.detect_thr.setSingleStep(0.01)
        self.detect_thr.setDecimals(2)
        self.detect_thr.setValue(0.62)
        adv.addWidget(label_with_info("匹配阈值", "detect_thr"), 1, 0)
        adv.addWidget(attach(self.detect_thr, "detect_thr"), 1, 1)
        self.ref_stride = _spin(1, 30, 12)
        adv.addWidget(label_with_info("参考帧步长", "ref_stride"), 1, 2)
        adv.addWidget(attach(self.ref_stride, "ref_stride"), 1, 3)
        g.addWidget(self.advanced, 3, 0, 1, 4)

        self.detect.changed.connect(self._on_detect_changed)
        self._on_detect_changed("auto")

    def _on_detect_changed(self, value):
        self.stack.setCurrentIndex({"auto": 0, "rect": 1, "mask": 2}.get(value, 0))

    def options(self):
        detect = self.detect.value()
        return {
            "auto": detect == "auto",
            "rect": self.rect.text().strip() if detect == "rect" else None,
            "mask": self.mask.text().strip() if detect == "mask" else None,
            "padding": round(self.padding.value(), 2),
            "subvideo": self.subvideo.value(),
            "mask_dilation": self.mask_dilation.value(),
            "neighbor": 10,
            "ref_stride": self.ref_stride.value(),
            "crf": 17,          # 由 OutputPanel 覆盖
            "encoder": "auto",  # 由 OutputPanel 覆盖
            "detect_thr": round(self.detect_thr.value(), 2),
            "keep": False,
        }

    def apply_preset(self, preset):
        self.padding.setValue(float(preset["padding"]))
        self.subvideo.setValue(int(preset["subvideo"]))


class SRPanel(ModuleCard):
    """超分：目标分辨率（长边）+ 输出上限 + 降噪 + 模型。"""

    def __init__(self, parent=None, enabled=False):
        super().__init__("超分（Real-CUGAN）", "scale", checked=enabled, parent=parent)
        g = self.grid

        # 先建上限控件：_rebuild 里的文案要用到它
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
        self.target.setMinimumWidth(300)
        g.addWidget(label_with_info("目标分辨率", "scale"), 0, 0)
        g.addWidget(attach(self.target, "scale"), 0, 1, 1, 3)
        self.scale_hint = QLabel("加入视频后按源长边自动换算倍率")
        self.scale_hint.setObjectName("hintLabel")
        self.scale_hint.setWordWrap(True)
        g.addWidget(self.scale_hint, 1, 0, 1, 4)

        self._src_w, self._src_h = 0, 0
        self._target_key = "4K"
        self._rebuild()
        self.target.currentIndexChanged.connect(self._on_target_changed)

        self.denoise = _combo(DENOISE_OPTIONS, "auto")
        g.addWidget(label_with_info("降噪", "denoise"), 2, 0)
        g.addWidget(attach(self.denoise, "denoise"), 2, 1, 1, 3)

        self.advanced = Collapsible("高级：输出上限 / 超分模型")
        adv = self.advanced.grid
        adv.addWidget(label_with_info("输出上限", "cap"), 0, 0)
        adv.addWidget(attach(self.cap, "cap"), 0, 1)
        self.model = _combo(MODEL_OPTIONS, "models-pro")
        adv.addWidget(label_with_info("模型", "model"), 0, 2)
        adv.addWidget(attach(self.model, "model"), 0, 3)
        g.addWidget(self.advanced, 3, 0, 1, 4)
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
        label = target_label(key)
        if not (self._src_w and self._src_h):
            if not target_long:
                return "最高 · 按源自适应"
            return "%s · 加入视频后显示实际尺寸" % label
        limit = self.cap_limit()
        scale, status = pick_scale(self._src_w, self._src_h, target_long, limit)
        cap_name = limit_label(limit) if limit else "不限制"
        if status == "too_big":
            return "%s · 源已超 %s 上限，无法放大" % (label, cap_name)
        if status == "unreachable":
            return "%s · 源长边 %d，最小 2x 已超目标" % (
                label, max(self._src_w, self._src_h))
        ow, oh = self._src_w * scale, self._src_h * scale
        text = "%s · %dx · %d×%d" % (label, scale, ow, oh)
        if status == "up":
            text += "（超出目标）"
        elif status == "capped":
            text += "（模型上限）"
        elif status == "capped_limit":
            text += "（%s 上限）" % cap_name
        elif status == "max_limited":
            text += "（受 %s 上限，非 4x）" % cap_name
        elif status == "max":
            text += "（最高）"
        if max(ow, oh) > 4096:
            text += "  CPU 编码"
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

    # ---------------------------------------------------------- 提示
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
            scale = 0       # 交给上层报错，绝不悄悄按 2x 放大
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
    """输出：目录、文件名预览、画质、编码器（两个模块共用）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("moduleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("输出")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        outer.addLayout(head)

        grid = QHBoxLayout()
        grid.setSpacing(8)
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("留空 = 与源视频同目录")
        self.btn_outdir = QPushButton("选择…")
        self.btn_outdir.setFixedWidth(64)
        grid.addWidget(self.out_dir, 1)
        grid.addWidget(self.btn_outdir)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label_with_info("输出目录", "out_dir"))
        row.addLayout(grid, 1)
        outer.addLayout(row)

        self.preview = QLabel("将输出：—")
        self.preview.setObjectName("hintLabel")
        outer.addWidget(self.preview)

        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self.test_mode = QCheckBox("测试模式")
        test_row.addWidget(checkbox_with_info(self.test_mode, "test_mode"))
        test_row.addSpacing(6)
        test_row.addWidget(QLabel("只处理"))
        self.test_seconds = QSpinBox()
        self.test_seconds.setRange(1, 60)
        self.test_seconds.setValue(3)
        self.test_seconds.setSuffix(" 秒")
        self.test_seconds.setFixedWidth(78)
        test_row.addWidget(self.test_seconds)
        test_row.addWidget(QLabel("从第"))
        self.test_start = QDoubleSpinBox()
        self.test_start.setRange(0.0, 3600.0)
        self.test_start.setDecimals(1)
        self.test_start.setSingleStep(0.5)
        self.test_start.setSuffix(" 秒")
        self.test_start.setFixedWidth(88)
        test_row.addWidget(self.test_start)
        test_row.addSpacing(4)
        test_row.addWidget(QLabel("开始"))
        test_row.addStretch(1)
        outer.addLayout(test_row)

        self.test_mode.toggled.connect(self._sync_test)
        self._sync_test(False)

        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        self.quality = SegmentedControl(QUALITY_OPTIONS, 17)
        qrow.addWidget(label_with_info("画质", "crf"))
        qrow.addWidget(attach(self.quality, "crf"))
        qrow.addSpacing(12)
        self.encoder = _combo([("自动（有 NVENC 就用）", "auto"),
                               ("NVIDIA NVENC", "nvenc"), ("CPU x264", "x264")], "auto")
        qrow.addWidget(label_with_info("编码器", "encoder"))
        qrow.addWidget(attach(self.encoder, "encoder"), 1)
        outer.addLayout(qrow)

        self.advanced = Collapsible("高级：精确 crf")
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(17)
        self.advanced.grid.addWidget(QLabel("crf 数值"), 0, 0)
        self.advanced.grid.addWidget(self.crf, 0, 1)
        outer.addWidget(self.advanced)

        self.quality.changed.connect(self._on_quality)
        self.crf.valueChanged.connect(self._on_crf_changed)

    def _on_quality(self, value):
        if int(self.crf.value()) != int(value):
            self.crf.setValue(int(value))

    def _on_crf_changed(self, value):
        match = [d for _, d in QUALITY_OPTIONS if int(d) == int(value)]
        if match:
            self.quality.set_value(match[0])
        else:
            for btn, data in self.quality._buttons:
                btn.setChecked(False)
            self.quality._current = value

    def _sync_test(self, on):
        self.test_seconds.setEnabled(bool(on))
        self.test_start.setEnabled(bool(on))

    def clip_seconds(self):
        return int(self.test_seconds.value()) if self.test_mode.isChecked() else 0

    def clip_start(self):
        return float(self.test_start.value()) if self.test_mode.isChecked() else 0.0

    # ---------------------------------------------------------- 取值
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
