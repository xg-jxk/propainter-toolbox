# -*- coding: utf-8 -*-
"""应用入口。

开发时：  .venv\\Scripts\\python.exe -m app
打包后：  ProPainterToolbox.exe（build/launcher.py 调 main()）
"""
import os
import sys

from PySide6.QtCore import QSharedMemory, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QMessageBox, QProxyStyle,
                               QSplashScreen, QStyle)

from pplib import __version__

from .core import applog
from .ui import bubble as bubble_ui
from .core import config as cfgmod
from .ui.mainwindow import MainWindow
from .ui.terms_dialog import TermsDialog



class _InstantTipStyle(QProxyStyle):
    """系统 tooltip 默认要等 ~700ms；这里改成 0，悬停立刻出现。"""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint in (QStyle.StyleHint.SH_ToolTip_WakeUpDelay,
                    QStyle.StyleHint.SH_ToolTip_FallAsleepDelay):
            return 0
        return super().styleHint(hint, option, widget, returnData)

def _resource(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", name)


def _apply_style(app):
    qss = _resource("style.qss")
    if os.path.isfile(qss):
        try:
            with open(qss, "r", encoding="utf-8") as fh:
                app.setStyleSheet(fh.read())
        except OSError:
            pass


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ProPainter Toolbox")
    app.setApplicationVersion(__version__)
    app.setStyle(_InstantTipStyle("Fusion"))
    bubble_ui.install(app)  # 全应用统一气泡，替掉原生 tooltip
    _apply_style(app)
    icon = _resource("app.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))

    # 单实例：两个窗口同时跑会抢显存
    shared = QSharedMemory("ProPainterToolbox-single-instance")
    if not shared.create(1):
        QMessageBox.information(None, "ProPainter 工具箱",
                                "已经有一个窗口在运行了，请切换到那个窗口。")
        return 1

    # 首次启动：必须勾选同意使用条款
    cfg = cfgmod.load()
    if int(cfg.get("terms_version", 0)) < cfgmod.TERMS_VERSION:
        dlg = TermsDialog(require_accept=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return 1
        cfg["terms_version"] = cfgmod.TERMS_VERSION
        cfgmod.save(cfg)

    splash = None
    if os.path.isfile(icon):
        pix = QIcon(icon).pixmap(320, 320)
        if not pix.isNull():
            splash = QSplashScreen(pix)
            splash.showMessage("ProPainter 工具箱 v%s · 正在启动…" % __version__,
                               Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                               Qt.GlobalColor.white)
            splash.show()
            app.processEvents()

    win = MainWindow(cfg)
    win.show()
    if splash is not None:
        splash.finish(win)
    win.start_env_probe()      # 后台探测，不阻塞首屏
    applog.setup()
    applog.write("启动 v%s · Python %s" % (__version__, sys.version.split()[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
