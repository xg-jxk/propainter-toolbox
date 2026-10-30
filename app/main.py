# -*- coding: utf-8 -*-
"""应用入口。

开发时：  .venv\\Scripts\\python.exe -m app
打包后：  ProPainterToolbox.exe（build/launcher.py 调 main()）
"""
import os
import sys

from PySide6.QtCore import QSharedMemory
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from pplib import __version__

from .core import config as cfgmod
from .ui.mainwindow import MainWindow
from .ui.terms_dialog import TermsDialog


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
    app.setStyle("Fusion")
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

    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
