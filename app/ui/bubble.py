# -*- coding: utf-8 -*-
"""即时气泡说明：鼠标一进入就弹出，不依赖系统 tooltip 的 ~700ms 延迟。"""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QLabel)

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
# ---------------------------------------------------------------- 统一气泡
def _as_html(text):
    """纯文本转富文本（保留换行、转义尖括号）；已经是 HTML 就原样用。"""
    import html as _html

    text = str(text)
    if "<" in text and ">" in text:
        return text
    escaped = _html.escape(text).replace("\n", "<br>")
    return "<p style='margin:0'>%s</p>" % escaped


def show_at(global_pos, html):
    """在鼠标位置右下弹出；贴边自动翻转，始终留在可视区内。"""
    if not html:
        return
    b = bubble()
    b.setText(html)
    b.adjustSize()
    screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
    area = screen.availableGeometry()
    x = global_pos.x() + 14
    y = global_pos.y() + 20
    if x + b.width() > area.right():
        x = global_pos.x() - b.width() - 10
    if y + b.height() > area.bottom():
        y = global_pos.y() - b.height() - 12
    x = max(area.left() + 4, min(x, area.right() - b.width() - 4))
    y = max(area.top() + 4, y)
    b.move(x, y)
    b.show()
    b.raise_()


def _plain(html):
    """把带样式的 HTML 压成纯文本，避免深色字落在深色气泡上。"""
    try:
        doc = QTextDocument()
        doc.setHtml(str(html))
        return doc.toPlainText()
    except Exception:
        return str(html)


def _text_for(widget, event):
    try:
        if isinstance(widget, QAbstractItemView):
            index = widget.indexAt(event.pos())
            if index.isValid():
                tip = index.data(Qt.ItemDataRole.ToolTipRole)
                return _as_html(tip) if tip else ""
            return ""
        # 控件可以预先挂一份"专门给气泡用"的浅色文案
        rich = widget.property("bubble_html")
        if rich:
            return str(rich)
        tip = widget.toolTip()
    except Exception:
        return ""
    if not tip:
        return ""
    if "<" in tip and ">" in tip:
        tip = _plain(tip)      # 原生 tooltip 的深色样式 → 纯文本
    return _as_html(tip)


class _TooltipFilter(QObject):
    """把 app 内所有原生 tooltip 换成自绘气泡。"""

    _HIDE_ON = (
        QEvent.Type.Leave,
        QEvent.Type.Hide,
        QEvent.Type.Wheel,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.FocusOut,
        QEvent.Type.WindowDeactivate,
    )

    def eventFilter(self, obj, event):
        try:
            etype = event.type()
        except Exception:
            return False
        if etype == QEvent.Type.ToolTip:
            if isinstance(obj, HelpIcon):
                return False  # 「i」自己处理（内容更详细）
            html = _text_for(obj, event)
            if html:
                show_at(event.globalPos(), html)
                return True
            hide_bubble()
            return False
        if etype in self._HIDE_ON:
            hide_bubble()
        return False


_filter = None


def install(app):
    """在 QApplication 上装一次，整个应用的气泡就统一了。"""
    global _filter
    if _filter is None:
        _filter = _TooltipFilter(app)
        app.installEventFilter(_filter)
    return _filter