# -*- coding: utf-8 -*-
"""参数旁的「i」图标气泡：鼠标进入立刻弹出，不依赖系统 tooltip 的延迟。

**不要再加 eventFilter / event() 拦截 ToolTip**：
2026-11 以前的实现给全窗口控件装 `installEventFilter`，在 PySide6 6.9 + Windows 上
会偶发 0xC0000005（访问冲突，栈落在 `event.type()` / `super().event()`），实测
40 次启动崩 9 次。现在普通控件一律用 Qt 原生 tooltip（样式在 style.qss 的 QToolTip
里统一成深色卡片），只有「i」图标用这里的自绘气泡，全程不碰 QEvent。
"""
from PySide6.QtCore import QPoint, Qt
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
    """参数旁的「i」：进入即弹，离开即收；点一下也能看。

    故意不挂原生 tooltip（否则会和自绘气泡重叠出现两个）。
    """

    def __init__(self, html, native_tooltip="", parent=None):
        super().__init__("i", parent)
        self.setObjectName("infoIcon")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(15, 15)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._bubble_html = html or ""
        self.setToolTip("")            # 见模块说明：原生气泡会和自绘气泡打架
        self.setAccessibleName(native_tooltip or "")

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

    # ---------------------------------------------------------- 其它
    @property
    def bubble_html(self):
        return self._bubble_html


# ---------------------------------------------------------------- 兼容接口
# 旧代码里调用过这些函数；保留成空实现，避免外部脚本 / 第三方插件报错，
# 同时告诉后来的人：这里**不再**装事件过滤器。

def watch(widget):
    """兼容旧接口：不再安装事件过滤器（会偶发访问冲突）。"""
    return widget


def watch_tree(root):
    """兼容旧接口：不再安装事件过滤器（会偶发访问冲突）。"""
    return root


def install(app):
    """兼容旧接口：不再安装事件过滤器（会偶发访问冲突）。"""
    return None
