# -*- coding: utf-8 -*-
"""使用条款对话框：首启必须勾选同意，也可从主界面随时查看。"""
import os

from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QTextBrowser, QVBoxLayout)

from pplib.ffmpeg import ROOT

TERMS_FILE = os.path.join(str(ROOT), "TERMS.md")

FALLBACK = ("本工具仅用于处理你拥有版权或已获得授权的视频；"
            "不得用于去除他人作品的署名/权利管理信息，或用于搬运、二次分发他人内容。")
CHECK_TEXT = "我已阅读并同意上述条款，并确认只处理我拥有版权或已获授权的视频"


class TermsDialog(QDialog):
    def __init__(self, parent=None, require_accept=True):
        super().__init__(parent)
        self.require_accept = require_accept
        self.setWindowTitle("使用条款")
        self.resize(780, 620)

        lay = QVBoxLayout(self)
        title = QLabel("使用条款 / Terms of Use")
        title.setObjectName("title")
        lay.addWidget(title)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        text = FALLBACK
        try:
            with open(TERMS_FILE, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            pass
        try:
            self.view.setMarkdown(text)
        except Exception:
            self.view.setPlainText(text)
        lay.addWidget(self.view, 1)

        self.check = QCheckBox(CHECK_TEXT)
        lay.addWidget(self.check)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_ok = QPushButton("同意并继续" if require_accept else "关闭")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("退出")
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

        if require_accept:
            self.btn_ok.setEnabled(False)
            self.check.toggled.connect(self.btn_ok.setEnabled)
        else:
            self.check.setVisible(False)
            self.btn_cancel.setVisible(False)

        self.setModal(True)
