# -*- coding: utf-8 -*-
"""主窗口：拖拽 → 队列（≤20）→ 逐个跑 pplib.runner → 进度/日志/取消。"""
import os
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from pplib import __version__
from pplib.ffmpeg import ROOT
from pplib.options import default_out

from ..core import config as cfgmod
from ..core import envcheck
from ..core.bridge import JobRunner
from ..core.queue import (STATUS_CANCELLED, STATUS_DONE, STATUS_FAILED,
                          STATUS_PENDING, STATUS_RUNNING, JobQueue)
from .help import attach, checkbox_with_info, label_with_info
from .install_dialog import InstallDialog
from .links import PROJECT_URL, load_icon, open_url
from .terms_dialog import TermsDialog

MODE_LABELS = [("区域修复", "repair"), ("超分", "sr"), ("区域修复 + 超分", "pipeline")]
ENCODER_LABELS = [("自动（有 NVENC 就用）", "auto"),
                  ("NVIDIA NVENC", "nvenc"), ("CPU x264", "x264")]
DETECT_LABELS = [("自动检测", "auto"), ("手动矩形", "rect"), ("逐帧掩码", "mask")]
DENOISE_LABELS = [("自动", "auto"), ("-1 不降噪", "-1"), ("0 保守", "0"),
                  ("1 轻", "1"), ("2 中", "2"), ("3 强", "3")]

COL_FILE, COL_STATUS, COL_PCT, COL_ELAPSED, COL_OUT = range(5)


def _fmt_eta(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return ""
    if sec < 60:
        return "剩 %d 秒" % sec
    if sec < 3600:
        return "剩 %d 分 %d 秒" % (sec // 60, sec % 60)
    return "剩 %d 小时 %d 分" % (sec // 3600, (sec % 3600) // 60)


class DropArea(QFrame):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        self.label = QLabel("把视频拖到这里，或点击选择文件（最多 20 个）")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setObjectName("dropLabel")
        lay.addWidget(self.label)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or cfgmod.load()
        self.queue = JobQueue()
        self.runtime = envcheck.check()
        self.runner = JobRunner(self.runtime.venv_python, self)
        self._current = None
        self._cancel_all = False
        self._t_start = 0.0
        self._last_out = ""

        self.setWindowTitle("ProPainter 工具箱 v%s" % __version__)
        self.resize(int(self.cfg.get("window", {}).get("w", 1000)),
                    int(self.cfg.get("window", {}).get("h", 760)))
        self._build_ui()
        self._apply_config()
        self._refresh_runtime()
        self._connect()

    # ================================================================ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ---- 标题行
        head = QHBoxLayout()
        title = QLabel("ProPainter 工具箱")
        title.setObjectName("title")
        head.addWidget(title)
        self.runtime_label = QLabel("")
        self.runtime_label.setObjectName("runtime")
        head.addWidget(self.runtime_label, 1)
        self.btn_install = QPushButton("安装运行时")
        self.btn_install.setObjectName("primary")
        head.addWidget(self.btn_install)
        self.btn_github = QToolButton()
        self.btn_github.setObjectName("ghButton")
        self.btn_github.setText("GitHub")
        self.btn_github.setIcon(load_icon("github.svg", 18))
        self.btn_github.setIconSize(QSize(18, 18))
        self.btn_github.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_github.setToolTip("在 GitHub 上查看源码、下载新版本、反馈问题")
        self.btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        head.addWidget(self.btn_github)
        self.btn_terms = QPushButton("使用条款")
        head.addWidget(self.btn_terms)
        self.btn_env = QPushButton("环境信息")
        head.addWidget(self.btn_env)
        root.addLayout(head)

        # ---- 拖拽区
        self.drop = DropArea()
        root.addWidget(self.drop)

        # ---- 队列
        qbox = QGroupBox("待处理队列")
        qlay = QVBoxLayout(qbox)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件", "状态", "进度", "用时", "输出"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        for col in (COL_STATUS, COL_PCT, COL_ELAPSED, COL_OUT):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        qlay.addWidget(self.table)

        qrow = QHBoxLayout()
        self.btn_add = QPushButton("添加文件…")
        self.btn_remove = QPushButton("移除选中")
        self.btn_clear = QPushButton("清空")
        qrow.addWidget(self.btn_add)
        qrow.addWidget(self.btn_remove)
        qrow.addWidget(self.btn_clear)
        qrow.addStretch(1)
        self.queue_label = QLabel("0 / 20")
        qrow.addWidget(self.queue_label)
        qlay.addLayout(qrow)
        root.addWidget(qbox, 2)

        # ---- 参数（每个参数带「i」，悬停看说明）
        pbox = QGroupBox("处理参数")
        grid = QGridLayout(pbox)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)

        self.mode = QComboBox()
        for label, key in MODE_LABELS:
            self.mode.addItem(label, key)
        grid.addWidget(label_with_info("模式", "mode"), 0, 0)
        grid.addWidget(attach(self.mode, "mode"), 0, 1)

        self.detect = QComboBox()
        for label, key in DETECT_LABELS:
            self.detect.addItem(label, key)
        grid.addWidget(label_with_info("区域定位", "detect"), 0, 2)
        grid.addWidget(attach(self.detect, "detect"), 0, 3)

        self.rect = QLineEdit()
        self.rect.setPlaceholderText("x,y,w,h  例如 1314,918,320,120")
        grid.addWidget(label_with_info("矩形", "rect"), 0, 4)
        grid.addWidget(attach(self.rect, "rect"), 0, 5)

        self.mask = QLineEdit()
        self.mask.setPlaceholderText("掩码目录，或单张掩码 png")
        self.btn_mask = QPushButton("选择…")
        self.btn_mask.setFixedWidth(64)
        maskrow = QHBoxLayout()
        maskrow.setContentsMargins(0, 0, 0, 0)
        maskrow.addWidget(self.mask, 1)
        maskrow.addWidget(self.btn_mask)
        grid.addWidget(label_with_info("掩码", "mask"), 1, 0)
        grid.addLayout(maskrow, 1, 1, 1, 5)

        self.padding = QDoubleSpinBox()
        self.padding.setRange(0.0, 1.5)
        self.padding.setSingleStep(0.05)
        self.padding.setDecimals(2)
        grid.addWidget(label_with_info("外扩 padding", "padding"), 2, 0)
        grid.addWidget(attach(self.padding, "padding"), 2, 1)

        self.subvideo = QSpinBox()
        self.subvideo.setRange(10, 200)
        self.subvideo.setSuffix(" 帧")
        grid.addWidget(label_with_info("分段 subvideo", "subvideo"), 2, 2)
        grid.addWidget(attach(self.subvideo, "subvideo"), 2, 3)

        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        grid.addWidget(label_with_info("画质 crf", "crf"), 2, 4)
        grid.addWidget(attach(self.crf, "crf"), 2, 5)

        self.encoder = QComboBox()
        for label, key in ENCODER_LABELS:
            self.encoder.addItem(label, key)
        grid.addWidget(label_with_info("编码器", "encoder"), 3, 0)
        grid.addWidget(attach(self.encoder, "encoder"), 3, 1)

        self.scale = QComboBox()
        for s in (2, 3, 4):
            self.scale.addItem("%dx" % s, s)
        grid.addWidget(label_with_info("超分倍率", "scale"), 3, 2)
        grid.addWidget(attach(self.scale, "scale"), 3, 3)

        self.denoise = QComboBox()
        for label, key in DENOISE_LABELS:
            self.denoise.addItem(label, key)
        grid.addWidget(label_with_info("降噪", "denoise"), 3, 4)
        grid.addWidget(attach(self.denoise, "denoise"), 3, 5)

        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("留空 = 与源视频同目录")
        self.btn_outdir = QPushButton("选择…")
        self.btn_outdir.setFixedWidth(64)
        outrow = QHBoxLayout()
        outrow.setContentsMargins(0, 0, 0, 0)
        outrow.addWidget(self.out_dir, 1)
        outrow.addWidget(self.btn_outdir)
        grid.addWidget(label_with_info("输出目录", "out_dir"), 4, 0)
        grid.addLayout(outrow, 4, 1, 1, 5)

        self.keep = QCheckBox("保留中间文件（排障用）")
        grid.addWidget(checkbox_with_info(self.keep, "keep"), 5, 1, 1, 2)
        self.open_when_done = QCheckBox("完成后自动打开输出目录")
        grid.addWidget(checkbox_with_info(self.open_when_done, "open_when_done"), 5, 3, 1, 3)
        root.addWidget(pbox)

        # ---- 进度与操作
        prow = QHBoxLayout()
        self.start_btn = QPushButton("开始处理")
        self.start_btn.setObjectName("primary")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.open_btn = QPushButton("打开输出目录")
        prow.addWidget(self.start_btn)
        prow.addWidget(self.cancel_btn)
        prow.addWidget(self.open_btn)
        prow.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(280)
        prow.addWidget(self.progress)
        self.status_label = QLabel("就绪")
        prow.addWidget(self.status_label)
        root.addLayout(prow)

        # ---- 日志
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setObjectName("log")
        self.log.setPlaceholderText("运行日志会显示在这里")
        root.addWidget(self.log, 1)

    def _connect(self):
        self.drop.filesDropped.connect(self.add_files)
        self.drop.clicked.connect(self.pick_files)
        self.btn_add.clicked.connect(self.pick_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_queue)
        self.btn_mask.clicked.connect(self.pick_mask)
        self.btn_outdir.clicked.connect(self.pick_outdir)
        self.btn_install.clicked.connect(self.open_install)
        self.btn_terms.clicked.connect(self.show_terms)
        self.btn_github.clicked.connect(lambda: open_url(PROJECT_URL))
        self.btn_env.clicked.connect(self.show_env)
        self.start_btn.clicked.connect(self.start_queue)
        self.cancel_btn.clicked.connect(self.cancel_current)
        self.open_btn.clicked.connect(self.open_output)
        self.mode.currentIndexChanged.connect(self._sync_mode)
        self.detect.currentIndexChanged.connect(self._sync_mode)

        self.runner.logLine.connect(self.append_log)
        self.runner.stageChanged.connect(self._on_stage)
        self.runner.progressChanged.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)

    # ================================================================ 配置
    def _apply_config(self):
        c = self.cfg
        self._set_combo(self.mode, c.get("mode", "repair"))
        self._set_combo(self.detect, c.get("detect", "auto"))
        self.rect.setText(c.get("rect", ""))
        self.mask.setText(c.get("mask", ""))
        self.padding.setValue(float(c.get("padding", 0.45)))
        self.subvideo.setValue(int(c.get("subvideo", 40)))
        self.crf.setValue(int(c.get("crf", 17)))
        self._set_combo(self.encoder, c.get("encoder", "auto"))
        self._set_combo(self.scale, int(c.get("scale", 2)))
        self._set_combo(self.denoise, str(c.get("denoise", "auto")))
        self.out_dir.setText(c.get("out_dir", ""))
        self.keep.setChecked(bool(c.get("keep", False)))
        self.open_when_done.setChecked(bool(c.get("open_when_done", True)))
        self._sync_mode()

    def _collect_config(self):
        return {
            "mode": self.mode.currentData(),
            "detect": self.detect.currentData(),
            "rect": self.rect.text().strip(),
            "mask": self.mask.text().strip(),
            "padding": round(self.padding.value(), 2),
            "subvideo": self.subvideo.value(),
            "neighbor": int(self.cfg.get("neighbor", 10)),
            "crf": self.crf.value(),
            "encoder": self.encoder.currentData(),
            "scale": int(self.scale.currentData()),
            "denoise": str(self.denoise.currentData()),
            "out_dir": self.out_dir.text().strip(),
            "workdir": self.cfg.get("workdir", ""),
            "keep": self.keep.isChecked(),
            "open_when_done": self.open_when_done.isChecked(),
            "last_dir": self.cfg.get("last_dir", ""),
            "window": {"w": self.width(), "h": self.height()},
        }

    @staticmethod
    def _set_combo(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _sync_mode(self):
        mode = self.mode.currentData()
        detect = self.detect.currentData()
        is_wm = mode in ("repair", "pipeline")
        is_sr = mode in ("sr", "pipeline")
        for w in (self.detect,):
            w.setEnabled(is_wm)
        self.rect.setEnabled(is_wm and detect == "rect")
        self.mask.setEnabled(is_wm and detect == "mask")
        self.btn_mask.setEnabled(is_wm and detect == "mask")
        self.padding.setEnabled(is_wm)
        self.subvideo.setEnabled(is_wm)
        self.scale.setEnabled(is_sr)
        self.denoise.setEnabled(is_sr)

    # ================================================================ 运行时
    def _refresh_runtime(self):
        self.runtime = envcheck.check()
        st = self.runtime
        if st.ready:
            gpu = st.gpu_text()
            text = "运行时就绪 · %s" % gpu
            self.runtime_label.setStyleSheet("color:#2e7d32")
            self.btn_install.setVisible(False)
            self.start_btn.setEnabled(len(self.queue) > 0)
        else:
            text = "缺少运行时：%s" % st.missing_text()
            self.runtime_label.setStyleSheet("color:#c62828")
            self.btn_install.setVisible(True)
            self.start_btn.setEnabled(False)
        self.runtime_label.setText(text)
        self.runtime_label.setToolTip(st.gpu_text() + ("\n支持 NVENC" if st.nvenc else ""))

    def open_install(self):
        dlg = InstallDialog(self)
        dlg.finishedOk.connect(self._on_install_ok)
        dlg.start()
        dlg.exec()

    def _on_install_ok(self):
        self._refresh_runtime()
        self.append_log("运行时安装完成，已重新检测环境")

    def show_terms(self):
        TermsDialog(self, require_accept=False).exec()

    def show_env(self):
        st = self.runtime
        info = envcheck.torch_info(st.venv_python)
        text = ("<b>Python</b>：%s<br>"
                "<b>torch</b>：%s<br>"
                "<b>显卡</b>：%s<br>"
                "<b>NVENC</b>：%s<br>"
                "<b>权重</b>：%s<br>"
                "<b>Real-CUGAN</b>：%s<br>"
                "<b>ffmpeg</b>：%s<br>"
                "<b>项目目录</b>：%s"
                % (st.venv_python, info, st.gpu_text(),
                   "支持" if st.nvenc else "不支持",
                   "齐全" if st.weights_ok else ("缺少 " + "、".join(st.weights_missing)),
                   "已安装" if st.cugan_ok else "未安装",
                   "可用" if st.ffmpeg_ok else "不可用",
                   ROOT))
        QMessageBox.information(self, "环境信息", text)

    # ================================================================ 队列
    def pick_files(self):
        start_dir = self.cfg.get("last_dir") or os.path.expanduser("~")
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频", start_dir,
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.ts *.flv *.wmv *.mpg);;所有文件 (*.*)")
        if files:
            self.cfg["last_dir"] = os.path.dirname(files[0])
            self.add_files(files)

    def add_files(self, paths):
        added, rejected = self.queue.add_paths(paths)
        if added:
            self._rebuild_table()
            self.append_log("已加入 %d 个文件" % len(added))
        if rejected:
            lines = ["%s（%s）" % (os.path.basename(p), why) for p, why in rejected[:6]]
            if len(rejected) > 6:
                lines.append("… 另有 %d 个" % (len(rejected) - 6))
            QMessageBox.warning(self, "有文件未加入",
                                "队列上限 20 个，以下文件没加入：\n\n" + "\n".join(lines))
        self._refresh_queue_label()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows:
            return
        if self.runner.is_running() and self._current in rows:
            QMessageBox.information(self, "提示", "当前正在处理的文件不能移除")
            return
        for r in rows:
            self.queue.remove(r)
        self._rebuild_table()
        self._refresh_queue_label()

    def clear_queue(self):
        if self.runner.is_running():
            QMessageBox.information(self, "提示", "请先取消当前任务")
            return
        self.queue.clear()
        self._rebuild_table()
        self._refresh_queue_label()

    def _refresh_queue_label(self):
        self.queue_label.setText("%d / 20" % len(self.queue))
        if self.runtime.ready:
            self.start_btn.setEnabled(len(self.queue) > 0 and not self.runner.is_running())

    def _rebuild_table(self):
        items = self.queue.items()
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            self._fill_row(row, it)
        self._refresh_queue_label()

    def _fill_row(self, row, item):
        name = QTableWidgetItem(item.name)
        name.setToolTip(item.path)
        self.table.setItem(row, COL_FILE, name)
        self.table.setItem(row, COL_STATUS, QTableWidgetItem(item.status))
        self.table.setItem(row, COL_PCT, QTableWidgetItem("%d%%" % int(item.pct)))
        self.table.setItem(row, COL_ELAPSED, QTableWidgetItem(
            "%.0fs" % item.elapsed if item.elapsed else ""))
        out = QTableWidgetItem(item.out or item.message)
        out.setToolTip(item.out or item.message)
        self.table.setItem(row, COL_OUT, out)

    # ================================================================ 处理
    def _build_spec(self, video):
        mode = self.mode.currentData()
        detect = self.detect.currentData()
        denoise = self.denoise.currentData()
        wm = {
            "auto": detect == "auto",
            "rect": self.rect.text().strip() if detect == "rect" else None,
            "mask": self.mask.text().strip() if detect == "mask" else None,
            "padding": round(self.padding.value(), 2),
            "subvideo": self.subvideo.value(),
            "neighbor": int(self.cfg.get("neighbor", 10)),
            "ref_stride": 12,
            "mask_dilation": 2,
            "crf": self.crf.value(),
            "encoder": self.encoder.currentData(),
            "keep": self.keep.isChecked(),
        }
        sr = {
            "scale": int(self.scale.currentData()),
            "denoise": None if denoise == "auto" else int(denoise),
            "crf": self.crf.value(),
            "encoder": self.encoder.currentData(),
            "keep": self.keep.isChecked(),
        }
        out = None
        out_dir = self.out_dir.text().strip()
        if out_dir:
            base = default_out(video, mode, sr["scale"])
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, os.path.basename(base))
        return {"mode": mode, "video": video, "out": out,
                "intermediate_crf": 12, "repair": wm, "sr": sr}

    def start_queue(self):
        if self.runner.is_running():
            return
        if not self.runtime.ready:
            if QMessageBox.question(self, "缺少运行时",
                                    "还没有安装好运行环境（%s）。现在去安装吗？"
                                    % self.runtime.missing_text()) == QMessageBox.StandardButton.Yes:
                self.open_install()
            return
        if len(self.queue) == 0:
            QMessageBox.information(self, "提示", "先把视频拖进来吧")
            return
        detect = self.detect.currentData()
        if detect == "rect" and not self.rect.text().strip():
            QMessageBox.warning(self, "缺少矩形", "选了「手动矩形」，请填写 x,y,w,h")
            return
        if detect == "mask" and not os.path.exists(self.mask.text().strip() or "x"):
            QMessageBox.warning(self, "找不到掩码", "请选择掩码文件或目录")
            return

        self.queue.reset()
        self._rebuild_table()
        self._cancel_all = False
        self._t_start = time.time()
        self.cfg.update(self._collect_config())
        cfgmod.save(self.cfg)
        self.append_log("===== 开始处理 %d 个文件 =====" % len(self.queue))
        self.set_running(True)
        self._start_next()

    def _start_next(self):
        idx = self.queue.next_pending_index()
        if idx is None or self._cancel_all:
            self._all_done()
            return
        item = self.queue[idx]
        self._current = idx
        item.status = STATUS_RUNNING
        self._fill_row(idx, item)
        self.table.selectRow(idx)
        self.progress.setValue(0)
        self.status_label.setText("准备：%s" % item.name)
        self.append_log("→ %s" % item.path)
        self.runner.start(self._build_spec(item.path))

    def _on_stage(self, name, pct):
        self.progress.setValue(int(pct))
        self.status_label.setText("%s · %s" % (name, "%d%%" % int(pct)))
        if self._current is not None:
            item = self.queue[self._current]
            item.pct = pct
            self._fill_row(self._current, item)

    def _on_progress(self, cur, total, pct, eta, note):
        self.progress.setValue(int(pct))
        eta_txt = _fmt_eta(eta)
        self.status_label.setText("%s %d/%d · %s" % (note or "", cur, total, eta_txt or "%d%%" % int(pct)))
        if self._current is not None:
            item = self.queue[self._current]
            item.pct = pct
            item.elapsed = time.time() - self._t_start
            self._fill_row(self._current, item)

    def _on_finished(self, state, payload):
        if self._current is None:
            return
        item = self.queue[self._current]
        if state == "done":
            item.status = STATUS_DONE
            item.out = payload.get("out") or ""
            item.pct = 100
            item.elapsed = float(payload.get("elapsed") or 0)
            self._last_out = item.out
            self.append_log("✔ 完成：%s（%s）" % (item.out, self._size_text(payload.get("size"))))
        elif state == "cancelled":
            item.status = STATUS_CANCELLED
            item.message = "已取消"
            self._cancel_all = True
            self.append_log("✖ 已取消：%s" % item.name)
        else:
            item.status = STATUS_FAILED
            item.message = payload.get("msg") or "失败"
            self.append_log("✖ 失败：%s —— %s" % (item.name, item.message))
            if payload.get("hint"):
                self.append_log("   %s" % payload["hint"])
        self._fill_row(self._current, item)
        self._current = None
        if self._cancel_all:
            self._all_done()
        else:
            self._start_next()

    @staticmethod
    def _size_text(size):
        if not size:
            return "大小未知"
        size = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return "%.1f %s" % (size, unit)
            size /= 1024.0
        return "%.1f TB" % size

    def _all_done(self):
        self.set_running(False)
        done = sum(1 for it in self.queue if it.status == STATUS_DONE)
        failed = sum(1 for it in self.queue if it.status in (STATUS_FAILED, STATUS_CANCELLED))
        self.progress.setValue(100 if not failed else self.progress.value())
        self.status_label.setText("完成 %d 个，失败/取消 %d 个" % (done, failed))
        self.append_log("===== 队列结束：成功 %d，失败/取消 %d，总用时 %.0fs ====="
                        % (done, failed, time.time() - self._t_start))
        if self.open_when_done.isChecked() and done:
            self.open_output()

    def cancel_current(self):
        if not self.runner.is_running():
            return
        self._cancel_all = True
        self.status_label.setText("正在取消…")
        self.append_log("用户取消，正在结束进程 …")
        self.runner.cancel()

    def set_running(self, running):
        for w in (self.start_btn, self.btn_add, self.btn_clear, self.btn_remove,
                  self.mode, self.detect, self.rect, self.mask, self.padding,
                  self.subvideo, self.crf, self.encoder, self.scale, self.denoise,
                  self.out_dir, self.keep, self.open_when_done):
            w.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        if not running:
            self._sync_mode()
            self._refresh_queue_label()

    def append_log(self, text):
        if not text:
            return
        for line in str(text).splitlines():
            self.log.appendPlainText(line)

    # ================================================================ 其它
    def pick_mask(self):
        if os.path.isdir(self.mask.text().strip() or ""):
            d = QFileDialog.getExistingDirectory(self, "选择掩码目录", self.mask.text())
            if d:
                self.mask.setText(d)
            return
        f, _ = QFileDialog.getOpenFileName(self, "选择掩码（单张 png 或目录里的任意一张）",
                                           "", "PNG (*.png);;所有文件 (*.*)")
        if f:
            self.mask.setText(f)

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def open_output(self):
        target = self._last_out or ""
        if not target:
            done = [it for it in self.queue if it.status == STATUS_DONE and it.out]
            if done:
                target = done[-1].out
        if not target:
            d = self.out_dir.text().strip()
            if d and os.path.isdir(d):
                target = d
        if not target:
            QMessageBox.information(self, "提示", "还没有产出文件")
            return
        path = os.path.dirname(target) if os.path.isfile(target) else target
        try:
            os.startfile(path)  # noqa: S606
        except Exception as e:
            QMessageBox.warning(self, "打不开目录", str(e))

    def closeEvent(self, event):
        if self.runner.is_running():
            if QMessageBox.question(self, "还在处理",
                                    "任务正在进行，确定退出吗？（会结束当前任务）") != \
                    QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.cancel()
        self.cfg.update(self._collect_config())
        cfgmod.save(self.cfg)
        event.accept()
