# -*- coding: utf-8 -*-
"""界面基础控件：分段选择、可折叠区、带启用开关的卡片、统一字段。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QRadioButton, QToolButton,
                               QVBoxLayout, QWidget)

from .help import info_icon


class SegmentedControl(QWidget):
    """一排互斥的胶囊按钮（画质等用）。"""

    changed = Signal(object)

    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        self._buttons = []
        self._current = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, (label, data) in enumerate(options):
            btn = QRadioButton(label)
            btn.setObjectName("segButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(btn, i)
            self._buttons.append((btn, data))
            lay.addWidget(btn)
        lay.addStretch(1)
        self._group.buttonClicked.connect(self._on_click)
        first = options[0][1] if options else None
        self.set_value(current if current is not None else first)

    def _on_click(self, btn):
        idx = self._group.id(btn)
        if 0 <= idx < len(self._buttons):
            self._current = self._buttons[idx][1]
            self.changed.emit(self._current)

    def value(self):
        return self._current

    def set_value(self, data):
        for btn, val in self._buttons:
            if val == data:
                btn.setChecked(True)
                self._current = data
                return
        self._current = data


class Field(QWidget):
    """统一字段：label + 「i」 / 控件 / 一句简介。"""

    def __init__(self, key, label, control, hint="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)
        self.label = QLabel(label)
        self.label.setObjectName("fieldLabel")
        head.addWidget(self.label)
        if key:
            head.addWidget(info_icon(key))
        head.addStretch(1)
        lay.addLayout(head)

        try:
            control.setMinimumHeight(30)
        except Exception:
            pass
        self.control = control
        lay.addWidget(control)

        self.hint = hint or ""
        if self.hint:
            lb = QLabel(self.hint)
            lb.setObjectName("fieldHint")
            lb.setWordWrap(True)
            lay.addWidget(lb)


class Collapsible(QWidget):
    """「▸ 高级」折叠区，默认收起。"""

    def __init__(self, title="高级参数", expanded=False, parent=None):
        super().__init__(parent)
        self._expanded = bool(expanded)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.btn = QToolButton()
        self.btn.setObjectName("advButton")
        self.btn.setText(title)
        self.btn.setCheckable(True)
        self.btn.setChecked(self._expanded)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.toggled.connect(self._on_toggle)
        outer.addWidget(self.btn)

        self.body = QWidget()
        self.vbox = QVBoxLayout(self.body)
        self.vbox.setContentsMargins(10, 2, 0, 2)
        self.vbox.setSpacing(12)
        self.body.setVisible(self._expanded)
        outer.addWidget(self.body)

    def add_field(self, field):
        self.vbox.addWidget(field)
        return field

    def _on_toggle(self, on):
        self._expanded = bool(on)
        self.body.setVisible(self._expanded)
        self.btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def is_expanded(self):
        return self._expanded

    def set_expanded(self, on):
        self.btn.setChecked(bool(on))


class ModuleCard(QFrame):
    """带「启用」勾选的卡片：取消勾选时整块变淡。"""

    toggled = Signal(bool)

    def __init__(self, title, info_key=None, checked=True, parent=None):
        super().__init__(parent)
        self.setObjectName("moduleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(title)
        self.check.setObjectName("cardTitle")
        self.check.setChecked(bool(checked))
        head.addWidget(self.check)
        if info_key:
            head.addWidget(info_icon(info_key))
        else:
            head.addSpacing(4)
        head.addStretch(1)
        outer.addLayout(head)

        self.body = QWidget()
        self.vbox = QVBoxLayout(self.body)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(14)
        outer.addWidget(self.body)

        self._effect = QGraphicsOpacityEffect(self.body)
        self._effect.setOpacity(1.0 if checked else 0.45)
        self.body.setGraphicsEffect(self._effect)
        self.check.toggled.connect(self._on_toggle)

    def add_field(self, field):
        self.vbox.addWidget(field)
        return field

    def add_separator(self):
        line = QFrame()
        line.setObjectName("cardSep")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        self.vbox.addWidget(line)
        return line

    def _on_toggle(self, on):
        self._effect.setOpacity(1.0 if bool(on) else 0.45)
        self.toggled.emit(bool(on))

    def set_enabled_state(self, on):
        self.check.setChecked(bool(on))

    def is_enabled(self):
        return self.check.isChecked()
