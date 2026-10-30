# -*- coding: utf-8 -*-
"""项目链接与图标。"""
import os
import sys

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PROJECT_URL = "https://github.com/xg-jxk/propainter-toolbox"
ISSUES_URL = PROJECT_URL + "/issues"
RELEASES_URL = PROJECT_URL + "/releases/latest"
GITEE_URL = "https://gitee.com/jiang-xinkai/propainter-toolbox"


def resource_dir():
    """源码运行取 app/resources；PyInstaller 打包后同样落在 <_MEIPASS>/app/resources。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "resources"))


def load_icon(name, size=18):
    """把 resources 里的 svg 渲染成 QIcon（按 2x 渲染，缩小后更锐利）。"""
    path = os.path.join(resource_dir(), name)
    if not os.path.isfile(path):
        return QIcon()
    try:
        renderer = QSvgRenderer(path)
        pix = QPixmap(QSize(size * 2, size * 2))
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        pix.setDevicePixelRatio(2.0)
        return QIcon(pix)
    except Exception:
        return QIcon()


def open_url(url):
    try:
        return QDesktopServices.openUrl(QUrl(url))
    except Exception:
        return False
