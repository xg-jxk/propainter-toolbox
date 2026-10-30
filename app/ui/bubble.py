# -*- coding: utf-8 -*-
"""即时气泡说明：鼠标一进入就弹出，不依赖系统 tooltip 的 ~700ms 延迟。"""
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel

BUBBLE_MAX_WIDTH = 380


class HelpBubble(QLabel):
    """无边框浮层，深色卡片样式，富文本 + 自动换行。"""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("helpBubble")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self.setMaximumWidth(BUBBLE_MAX_WIDTH)
        self.setMargin(10)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


_bubble = None


def bubble():
    global _bubble
    if _bubble is None:
        _bubble = HelpBubble()
    return _bubble


def show_bubble(anchor, html):
    """在 anchor 下方居中弹出；贴边时自动翻到上方并夹在屏幕内。"""
    if not html:
        return
    b = bubble()
    b.setText(html)
    b.adjustSize()

    screen = (anchor.screen() if hasattr(anchor, "screen") else None) or QApplication.primaryScreen()
    area = screen.availableGeometry()
    w, h = b.width(), b.height()

    top_left = anchor.mapToGlobal(QPoint(0, 0))
    x = top_left.x() + anchor.width() // 2 - w // 2
    y = top_left.y() + anchor.height() + 6

    if x + w > area.right():
        x = area.right() - w - 4
    if x < area.left():
        x = area.left() + 4
    if y + h > area.bottom():
        y = top_left.y() - h - 6
    if y < area.top():
        y = area.top() + 4

    b.move(x, y)
    b.show()
    b.raise_()


def hide_bubble():
    if _bubble is not None and _bubble.isVisible():
        _bubble.hide()


class HelpIcon(QLabel):
    """参数旁的「i」：进入即弹，离开即收；点一下也能看。"""

    def __init__(self, html, native_tooltip="", parent=None):
        super().__init__("i", parent)
        self.setObjectName("infoIcon")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(15, 15)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._bubble_html = html or ""
        # 保留一份 tooltip 文本：无障碍/自动化能读到；但原生气泡被 event() 拦掉
        self.setToolTip(native_tooltip or "")
        self.setToolTipDuration(15000)

    # ---------------------------------------------------------- 事件
    def enterEvent(self, event):
        show_bubble(self, self._bubble_html)
        super().enterEvent(event)

    def leaveEvent(self, event):
        hide_bubble()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        show_bubble(self, self._bubble_html)
        super().mousePressEvent(event)

    def hideEvent(self, event):
        hide_bubble()
        super().hideEvent(event)

    def event(self, event):
        # 交给自定义气泡，屏蔽系统 tooltip（否则会出现两个）
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().event(event)

    # ---------------------------------------------------------- 其它
    @property
    def bubble_html(self):
        return self._bubble_html


