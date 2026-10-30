# -*- coding: utf-8 -*-
"""三块设置面板：区域修复 / 超分 / 输出，以及三档预设。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget)

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
    """超分：倍率 + 降噪 + 高级（模型）。"""

    def __init__(self, parent=None, enabled=False):
        super().__init__("超分（Real-CUGAN）", "scale", checked=enabled, parent=parent)
        g = self.grid

        self.scale = QComboBox()
        self.scale.setMinimumWidth(220)
        g.addWidget(label_with_info("输出分辨率", "scale"), 0, 0)
        g.addWidget(attach(self.scale, "scale"), 0, 1, 1, 3)
        self.scale_hint = QLabel("加入视频后按源尺寸显示实际输出")
        self.scale_hint.setObjectName("hintLabel")
        self.scale_hint.setWordWrap(True)
        g.addWidget(self.scale_hint, 1, 0, 1, 4)
        self._src_w, self._src_h = 0, 0
        self.set_source_size(0, 0)
        self.scale.currentIndexChanged.connect(lambda _i: self._refresh_hint())

        self.denoise = _combo(DENOISE_OPTIONS, "auto")
        g.addWidget(label_with_info("降噪", "denoise"), 2, 0)
        g.addWidget(attach(self.denoise, "denoise"), 2, 1, 1, 3)

        self.advanced = Collapsible("高级：超分模型")
        self.model = _combo(MODEL_OPTIONS, "models-pro")
        self.advanced.grid.addWidget(label_with_info("模型", "model"), 0, 0)
        self.advanced.grid.addWidget(attach(self.model, "model"), 0, 1)
        g.addWidget(self.advanced, 3, 0, 1, 4)

    def set_source_size(self, width, height):
        """按源尺寸重建选项文字（2x/3x/4x 对应的实际分辨率）。"""
        self._src_w, self._src_h = int(width or 0), int(height or 0)
        current = self.scale_value()
        blocked = self.scale.blockSignals(True)
        self.scale.clear()
        for s in (2, 3, 4):
            if self._src_w and self._src_h:
                ow, oh = self._src_w * s, self._src_h * s
                text = "%dx → %d×%d（%s）" % (s, ow, oh, _k_label(ow, oh))
                if ow > 4096 or oh > 4096:
                    text += "  CPU 编码"
            else:
                text = "%dx（加入视频后显示实际尺寸）" % s
            self.scale.addItem(text, s)
        self.scale.blockSignals(blocked)
        self.set_scale(current)
        self._refresh_hint()

    def set_scale(self, scale):
        idx = self.scale.findData(int(scale))
        if idx >= 0:
            self.scale.setCurrentIndex(idx)
        self._refresh_hint()

    def scale_value(self):
        data = self.scale.currentData()
        return int(data) if data else 2

    def _refresh_hint(self):
        if not (self._src_w and self._src_h):
            self.scale_hint.setText("加入视频后按源尺寸显示实际输出")
            return
        s = self.scale_value()
        ow, oh = self._src_w * s, self._src_h * s
        txt = "源 %d×%d · 当前输出 %d×%d（%s）" % (self._src_w, self._src_h, ow, oh, _k_label(ow, oh))
        if ow > 4096 or oh > 4096:
            txt += " · 超过显卡 H.264 上限，会自动用 CPU 编码"
        self.scale_hint.setText(txt)

    def options(self):
        denoise = self.denoise.currentData()
        return {
            "scale": self.scale_value(),
            "denoise": None if denoise == "auto" else int(denoise),
            "model": self.model.currentData(),
            "crf": 17,
            "encoder": "auto",
            "keep": False,
        }

    def apply_preset(self, preset):
        pass  # 预设不改输出分辨率


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
