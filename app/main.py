# -*- coding: utf-8 -*-
"""应用入口。

开发时：  .venv\\Scripts\\python.exe -m app
打包后：  ProPainterToolbox.exe（build/launcher.py 调 main()）
"""
import os
import sys

from PySide6.QtCore import QSharedMemory, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QMessageBox, QProxyStyle,
                               QStyle)

from pplib import __version__

from .core import applog
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

    # 日志与崩溃转储尽早就位：原生崩溃也能留下线索
    applog.setup()
    _enable_faulthandler()
    applog.write("启动 v%s · Python %s" % (__version__, sys.version.split()[0]))
    try:
        from pplib import cleanup
        n, freed = cleanup.sweep(max_age_hours=24)
        if n:
            applog.write("清理上次遗留的临时文件：%d 个，%s" % (n, cleanup.human(freed)))
    except Exception:
        pass

    win = MainWindow(cfg)
    win.show()
    # 探测延后一拍再启动，避免与窗口映射抢事件循环（1.3.18 的启动崩溃嫌疑）
    QTimer.singleShot(150, _start_probe_safe)
    return app.exec()


def _start_probe_safe():
    try:
        from .ui.mainwindow import MainWindow  # noqa: F401
        for widget in QApplication.topLevelWidgets():
            probe = getattr(widget, "start_env_probe", None)
            if callable(probe):
                probe()
                return
    except Exception:
        import traceback
        applog.write("环境探测启动失败：\n" + traceback.format_exc())


def _enable_faulthandler():
    """把原生崩溃（访问冲突等）的栈写到 logs/crash.log。"""
    try:
        import faulthandler
        path = os.path.join(applog.log_dir(), "crash.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=fh, all_threads=True)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
