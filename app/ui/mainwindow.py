# -*- coding: utf-8 -*-
"""主窗口：左边队列、右边设置（区域修复 / 超分 / 输出），底部进度与日志。"""
import os
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from pplib import __version__
from pplib.ffmpeg import ROOT
from pplib.options import default_out

from ..core import config as cfgmod
from ..core import envcheck
from ..core.bridge import JobRunner
from ..core.queue import (STATUS_CANCELLED, STATUS_DONE, STATUS_FAILED,
                          STATUS_PENDING, STATUS_RUNNING, STATUS_SKIPPED,
                          JobQueue)
from .help import checkbox_with_info, info_icon
from .install_dialog import InstallDialog
from .links import PROJECT_URL, load_icon, open_url
from .panels import (PRESETS, OutputPanel, RepairPanel, SRPanel,
                     pick_scale)
from .terms_dialog import TermsDialog
from .widgets import Collapsible

COL_FILE, COL_STATUS, COL_PCT, COL_ELAPSED, COL_SIZE, COL_OUT = range(6)


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
        self.setMinimumHeight(84)
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
        win_cfg = self.cfg.get("window", {})
        self.resize(int(win_cfg.get("w", 1180)), int(win_cfg.get("h", 820)))
        self.setMinimumSize(900, 640)

        self._build_ui()
        self._apply_config()
        self._refresh_runtime()
        self._connect()
        self._on_modules_changed()
        self._update_preview()

    # ================================================================ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ---------- 顶部
        head = QHBoxLayout()
        head.setSpacing(10)
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

        # ---------- 主体：左队列 / 右设置
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)

        self.drop = DropArea()
        lv.addWidget(self.drop)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["文件", "状态", "进度", "用时", "输出尺寸", "输出"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        for col in (COL_STATUS, COL_PCT, COL_ELAPSED, COL_SIZE, COL_OUT):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        lv.addWidget(self.table, 1)

        qrow = QHBoxLayout()
        self.btn_add = QPushButton("添加文件…")
        self.btn_remove = QPushButton("移除选中")
        self.btn_clear = QPushButton("清空")
        qrow.addWidget(self.btn_add)
        qrow.addWidget(self.btn_remove)
        qrow.addWidget(self.btn_clear)
        qrow.addStretch(1)
        self.queue_label = QLabel("0 / 20")
        self.queue_label.setObjectName("hintLabel")
        qrow.addWidget(self.queue_label)
        lv.addLayout(qrow)

        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.Shape.NoFrame)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        rv = QVBoxLayout(inner)
        rv.setContentsMargins(0, 0, 6, 0)
        rv.setSpacing(10)

        preset_bar = QFrame()
        preset_bar.setObjectName("presetBar")
        bar_lay = QVBoxLayout(preset_bar)
        bar_lay.setContentsMargins(12, 9, 12, 9)
        bar_lay.setSpacing(6)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_title = QLabel("整体档位")
        preset_title.setObjectName("sectionTitle")
        preset_row.addWidget(preset_title)
        preset_row.addWidget(info_icon("preset"))
        preset_row.addSpacing(4)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self._preset_buttons = {}
        for key, preset in PRESETS.items():
            btn = QPushButton(preset["title"])
            btn.setObjectName("presetButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(preset["desc"])
            btn.clicked.connect(lambda _=False, k=key: self._apply_preset(k))
            self.preset_group.addButton(btn)
            self._preset_buttons[key] = btn
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        bar_lay.addLayout(preset_row)

        self.preset_hint = QLabel(PRESETS["balanced"]["desc"])
        self.preset_hint.setObjectName("hintLabel")
        self.preset_hint.setWordWrap(True)
        bar_lay.addWidget(self.preset_hint)
        rv.addWidget(preset_bar)

        self.repair_panel = RepairPanel()
        self.sr_panel = SRPanel()
        self.output_panel = OutputPanel()
        rv.addWidget(self.repair_panel)
        rv.addWidget(self.sr_panel)
        rv.addWidget(self.output_panel)

        opts = QHBoxLayout()
        opts.setSpacing(16)
        self.keep = QCheckBox("保留中间文件（排障用）")
        opts.addWidget(checkbox_with_info(self.keep, "keep"))
        self.open_when_done = QCheckBox("完成后自动打开输出目录")
        opts.addWidget(checkbox_with_info(self.open_when_done, "open_when_done"))
        opts.addStretch(1)
        rv.addLayout(opts)
        rv.addStretch(1)
        right.setWidget(inner)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([660, 480])
        root.addWidget(splitter, 1)

        # ---------- 进度与操作
        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.start_btn = QPushButton("开始处理")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(120)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.open_btn = QPushButton("打开输出目录")
        prow.addWidget(self.start_btn)
        prow.addWidget(self.cancel_btn)
        prow.addWidget(self.open_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        prow.addWidget(self.progress, 1)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("hintLabel")
        self.status_label.setMinimumWidth(170)
        prow.addWidget(self.status_label)
        root.addLayout(prow)

        # ---------- 日志（可折叠，出错自动展开）
        self.log_box = Collapsible("运行日志", expanded=False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setObjectName("log")
        self.log.setPlaceholderText("运行日志会显示在这里")
        self.log.setMinimumHeight(120)
        self.log_box.grid.addWidget(self.log, 0, 0)
        root.addWidget(self.log_box)

    def _connect(self):
        self.drop.filesDropped.connect(self.add_files)
        self.drop.clicked.connect(self.pick_files)
        self.btn_add.clicked.connect(self.pick_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_queue)
        self.btn_install.clicked.connect(self.open_install)
        self.btn_terms.clicked.connect(self.show_terms)
        self.btn_github.clicked.connect(lambda: open_url(PROJECT_URL))
        self.btn_env.clicked.connect(self.show_env)
        self.start_btn.clicked.connect(self.start_queue)
        self.cancel_btn.clicked.connect(self.cancel_current)
        self.open_btn.clicked.connect(self.open_output)

        self.repair_panel.btn_mask.clicked.connect(self.pick_mask)
        self.output_panel.btn_outdir.clicked.connect(self.pick_outdir)
        self.repair_panel.toggled.connect(self._on_modules_changed)
        self.sr_panel.toggled.connect(self._on_modules_changed)

        self.repair_panel.detect.changed.connect(self._update_preview)
        self.repair_panel.padding.valueChanged.connect(self._update_preview)
        self.repair_panel.rect.textChanged.connect(self._update_preview)
        self.sr_panel.target.currentIndexChanged.connect(self._update_preview)
        self.output_panel.out_dir.textChanged.connect(self._update_preview)
        self.output_panel.crf.valueChanged.connect(self._update_preview)
        self.output_panel.test_mode.toggled.connect(self._update_preview)
        self.output_panel.test_seconds.valueChanged.connect(self._update_preview)
        self.output_panel.test_start.valueChanged.connect(self._update_preview)

        self.runner.logLine.connect(self.append_log)
        self.runner.stageChanged.connect(self._on_stage)
        self.runner.progressChanged.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)

    # ================================================================ 配置
    def _apply_config(self):
        c = self.cfg
        if "repair_enabled" not in c and "sr_enabled" not in c:
            mode = str(c.get("mode", "repair"))
            c["repair_enabled"] = mode in ("repair", "pipeline")
            c["sr_enabled"] = mode in ("sr", "pipeline")
        self.repair_panel.set_enabled_state(bool(c.get("repair_enabled", True)))
        self.sr_panel.set_enabled_state(bool(c.get("sr_enabled", False)))
        self.repair_panel.detect.set_value(c.get("detect", "auto"))
        self.repair_panel.rect.setText(c.get("rect", ""))
        self.repair_panel.mask.setText(c.get("mask", ""))
        self.repair_panel.padding.setValue(float(c.get("padding", 0.45)))
        self.repair_panel.subvideo.setValue(int(c.get("subvideo", 40)))
        self.repair_panel.mask_dilation.setValue(int(c.get("mask_dilation", 2)))
        self.repair_panel.detect_thr.setValue(float(c.get("detect_thr", 0.62)))
        self.repair_panel.ref_stride.setValue(int(c.get("ref_stride", 12)))
        self.sr_panel.set_target(str(c.get("sr_target", "4K")))
        idx = self.sr_panel.denoise.findData(str(c.get("denoise", "auto")))
        if idx < 0:
            idx = self.sr_panel.denoise.findData(c.get("denoise", "auto"))
        if idx >= 0:
            self.sr_panel.denoise.setCurrentIndex(idx)
        idx = self.sr_panel.model.findData(c.get("model", "models-pro"))
        if idx >= 0:
            self.sr_panel.model.setCurrentIndex(idx)
        self.output_panel.out_dir.setText(c.get("out_dir", ""))
        self.output_panel.test_mode.setChecked(bool(c.get("test_mode", False)))
        self.output_panel.test_seconds.setValue(int(c.get("test_seconds", 3)))
        self.output_panel.test_start.setValue(float(c.get("test_start", 0.0)))
        self.output_panel.crf.setValue(int(c.get("crf", 17)))
        idx = self.output_panel.encoder.findData(c.get("encoder", "auto"))
        if idx >= 0:
            self.output_panel.encoder.setCurrentIndex(idx)
        self.keep.setChecked(bool(c.get("keep", False)))
        self.open_when_done.setChecked(bool(c.get("open_when_done", True)))
        preset = str(c.get("preset", "balanced"))
        if preset in self._preset_buttons:
            self._preset_buttons[preset].setChecked(True)
            self.preset_hint.setText(PRESETS[preset]["desc"])
        self.repair_panel.advanced.set_expanded(bool(c.get("advanced_open", False)))
        self.log_box.set_expanded(bool(c.get("log_open", False)))

    def _collect_config(self):
        return {
            "repair_enabled": self.repair_panel.is_enabled(),
            "sr_enabled": self.sr_panel.is_enabled(),
            "detect": self.repair_panel.detect.value(),
            "rect": self.repair_panel.rect.text().strip(),
            "mask": self.repair_panel.mask.text().strip(),
            "padding": round(self.repair_panel.padding.value(), 2),
            "subvideo": self.repair_panel.subvideo.value(),
            "mask_dilation": self.repair_panel.mask_dilation.value(),
            "detect_thr": round(self.repair_panel.detect_thr.value(), 2),
            "ref_stride": self.repair_panel.ref_stride.value(),
            "sr_target": self.sr_panel.target_key(),
            "scale": self.sr_panel.options(
                self.queue[0].width if len(self.queue) else 0,
                self.queue[0].height if len(self.queue) else 0)["scale"],
            "denoise": str(self.sr_panel.denoise.currentData()),
            "model": self.sr_panel.model.currentData(),
            "out_dir": self.output_panel.out_dir_text(),
            "test_mode": self.output_panel.test_mode.isChecked(),
            "test_seconds": self.output_panel.test_seconds.value(),
            "test_start": round(self.output_panel.test_start.value(), 1),
            "crf": self.output_panel.crf_value(),
            "encoder": self.output_panel.encoder_value(),
            "keep": self.keep.isChecked(),
            "open_when_done": self.open_when_done.isChecked(),
            "preset": self._current_preset(),
            "advanced_open": self.repair_panel.advanced.is_expanded(),
            "log_open": self.log_box.is_expanded(),
            "last_dir": self.cfg.get("last_dir", ""),
            "window": {"w": self.width(), "h": self.height()},
        }

    def _current_preset(self):
        for key, btn in self._preset_buttons.items():
            if btn.isChecked():
                return key
        return ""

    # ================================================================ 模式与预览
    def _mode(self):
        repair = self.repair_panel.is_enabled()
        sr = self.sr_panel.is_enabled()
        if repair and sr:
            return "pipeline"
        if repair:
            return "repair"
        if sr:
            return "sr"
        return None

    def _on_modules_changed(self, *_):
        mode = self._mode()
        if mode is None:
            self.status_label.setText("至少启用一项")
            self.status_label.setStyleSheet("color:#c62828")
        else:
            self.status_label.setText("就绪")
            self.status_label.setStyleSheet("")
        self.start_btn.setEnabled(bool(mode) and len(self.queue) > 0
                                   and not self.runner.is_running())
        self._update_preview()

    def _update_preview(self, *_):
        video = self.queue[0].path if len(self.queue) else os.path.join("D:\\video", "a.mp4")
        mode = self._mode() or "repair"
        _src_w = self.queue[0].width if len(self.queue) else 0
        _src_h = self.queue[0].height if len(self.queue) else 0
        scale = pick_scale(_src_w, _src_h, self.sr_panel.target_long())[0]
        preview = self.output_panel.test_mode.isChecked()
        path = self.output_panel.out_path(video, mode, scale, preview=preview)
        if not path:
            path = default_out(video, mode, scale, preview=preview)
        where = os.path.dirname(path)
        name = os.path.basename(path)
        if self.output_panel.out_dir_text():
            self.output_panel.set_preview("将输出：%s\n到 %s" % (name, where))
        else:
            self.output_panel.set_preview("将输出：%s（与源视频同目录）" % name)

    def _apply_preset(self, key):
        preset = PRESETS.get(key)
        if not preset:
            return
        btn = self._preset_buttons.get(key)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self.repair_panel.apply_preset(preset)
        self.output_panel.crf.setValue(int(preset["crf"]))
        self.preset_hint.setText(preset["desc"])
        self._update_preview()

    # ================================================================ 运行时
    def _refresh_runtime(self):
        self.runtime = envcheck.check()
        st = self.runtime
        if st.ready:
            self.runtime_label.setText("运行时就绪 · %s" % st.gpu_text())
            self.runtime_label.setStyleSheet("color:#2e7d32")
            self.btn_install.setVisible(False)
        else:
            self.runtime_label.setText("缺少运行时：%s" % st.missing_text())
            self.runtime_label.setStyleSheet("color:#c62828")
            self.btn_install.setVisible(True)
        self.runtime_label.setToolTip(st.gpu_text() + ("\n支持 NVENC" if st.nvenc else ""))
        self._on_modules_changed()

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
        text = ("<b>Python</b>：%s<br><b>torch</b>：%s<br><b>显卡</b>：%s<br>"
                "<b>NVENC</b>：%s<br><b>权重</b>：%s<br><b>Real-CUGAN</b>：%s<br>"
                "<b>ffmpeg</b>：%s<br><b>项目目录</b>：%s"
                % (st.venv_python, info, st.gpu_text(),
                   "支持" if st.nvenc else "不支持",
                   "齐全" if st.weights_ok else ("缺少 " + "、".join(st.weights_missing)),
                   "已安装" if st.cugan_ok else "未安装",
                   "可用" if st.ffmpeg_ok else "不可用", ROOT))
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
        for item in added:
            self._probe_item(item)
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
        self._sync_scale_labels()
        self._update_preview()

    def _probe_item(self, item):
        """记录源分辨率，用于把倍率显示成实际输出尺寸。"""
        if item.width and item.height:
            return
        try:
            from pplib.ffmpeg import probe_size
            w, h = probe_size(item.path)
            if w and h:
                item.width, item.height = w, h
        except Exception:
            pass

    def _sync_scale_labels(self):
        if len(self.queue):
            it = self.queue[0]
            self.sr_panel.set_source_size(it.width, it.height)
        else:
            self.sr_panel.set_source_size(0, 0)

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
        self._sync_scale_labels()
        self._update_preview()

    def clear_queue(self):
        if self.runner.is_running():
            QMessageBox.information(self, "提示", "请先取消当前任务")
            return
        self.queue.clear()
        self._rebuild_table()
        self._refresh_queue_label()
        self._sync_scale_labels()
        self._update_preview()

    def _refresh_queue_label(self):
        self.queue_label.setText("%d / 20" % len(self.queue))
        self.start_btn.setEnabled(bool(self._mode()) and len(self.queue) > 0
                                  and not self.runner.is_running())

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
        self.table.setItem(row, COL_ELAPSED,
                           QTableWidgetItem("%.0fs" % item.elapsed if item.elapsed else ""))
        scale, status = pick_scale(item.width, item.height,
                                   self.sr_panel.target_long())
        if item.width and item.height:
            size_txt = "%d×%d" % (item.width * scale, item.height * scale)
            if status == "capped":
                size_txt += "（封顶）"
        else:
            size_txt = "—"
        size_cell = QTableWidgetItem(size_txt)
        size_cell.setToolTip("按目标 %s 计算：%dx" % (self.sr_panel.target_key(), scale))
        self.table.setItem(row, COL_SIZE, size_cell)

        out = QTableWidgetItem(item.out or item.message)
        out.setToolTip(item.out or item.message)
        self.table.setItem(row, COL_OUT, out)

    # ================================================================ 处理
    def _build_spec(self, video, width=0, height=0):
        mode = self._mode()
        if mode is None:
            raise ValueError("至少启用区域修复或超分")
        repair = self.repair_panel.options()
        sr = self.sr_panel.options(width, height)
        repair["crf"] = self.output_panel.crf_value()
        repair["encoder"] = self.output_panel.encoder_value()
        repair["keep"] = self.keep.isChecked()
        sr["crf"] = self.output_panel.crf_value()
        sr["encoder"] = self.output_panel.encoder_value()
        sr["keep"] = self.keep.isChecked()
        return {
            "mode": mode,
            "video": video,
                        "out": self.output_panel.out_path(video, mode, sr["scale"],
                                       preview=self.output_panel.test_mode.isChecked()),
            "intermediate_crf": 12,
            "clip_seconds": self.output_panel.clip_seconds(),
            "clip_start": self.output_panel.clip_start(),
            "repair": repair,
            "sr": sr,
        }

    def start_queue(self):
        if self.runner.is_running():
            return
        if not self.runtime.ready:
            if QMessageBox.question(self, "缺少运行时",
                                    "还没有安装好运行环境（%s）。现在去安装吗？"
                                    % self.runtime.missing_text()) == QMessageBox.StandardButton.Yes:
                self.open_install()
            return
        if self._mode() is None:
            QMessageBox.warning(self, "没有启用的模块", "请至少勾选「区域修复」或「超分」。")
            return
        if len(self.queue) == 0:
            QMessageBox.information(self, "提示", "先把视频拖进来吧")
            return
        detect = self.repair_panel.detect.value()
        if self.repair_panel.is_enabled() and detect == "rect" \
                and not self.repair_panel.rect.text().strip():
            QMessageBox.warning(self, "缺少矩形", "选了「手动矩形」，请填写 x,y,w,h")
            return
        if self.repair_panel.is_enabled() and detect == "mask" \
                and not os.path.exists(self.repair_panel.mask.text().strip() or "x"):
            QMessageBox.warning(self, "找不到掩码", "请选择掩码文件或目录")
            return

        self.queue.reset()
        self._rebuild_table()
        self._cancel_all = False
        self._t_start = time.time()
        self.cfg.update(self._collect_config())
        cfgmod.save(self.cfg)
        if not self.log_box.is_expanded():
            self.log_box.set_expanded(True)
        self.append_log("===== 开始处理 %d 个文件（%s）=====" % (len(self.queue), self._mode()))
        self._log_target_summary()
        self.set_running(True)
        self._start_next()

    def _log_target_summary(self):
        if not len(self.queue):
            return
        buckets = {}
        for it in self.queue:
            scale, status = pick_scale(it.width, it.height, self.sr_panel.target_long())
            tag = "%dx" % scale if status != "capped" else "%dx封顶" % scale
            buckets[tag] = buckets.get(tag, 0) + 1
        detail = "，".join("%s ×%d" % (k, v) for k, v in sorted(buckets.items()))
        self.append_log("目标 %s：%s" % (self.sr_panel.target_key(), detail))
        over = [it for it in self.queue if pick_scale(
            it.width, it.height, self.sr_panel.target_long())[1] == "unreachable"]
        if over:
            self.append_log("⚠ 有 %d 个文件的源分辨率已接近/超过目标，最小只能 2x（会超出目标）"
                            % len(over))

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
        self.runner.start(self._build_spec(item.path, item.width, item.height))

    def _on_stage(self, name, pct):
        self.progress.setValue(int(pct))
        self.status_label.setText("%s · %d%%" % (name, int(pct)))
        if self._current is not None:
            item = self.queue[self._current]
            item.pct = pct
            self._fill_row(self._current, item)

    def _on_progress(self, cur, total, pct, eta, note):
        self.progress.setValue(int(pct))
        eta_txt = _fmt_eta(eta)
        self.status_label.setText("%s %d/%d · %s"
                                  % (note or "", cur, total, eta_txt or "%d%%" % int(pct)))
        if self._current is not None:
            item = self.queue[self._current]
            item.pct = pct
            item.elapsed = time.time() - self._t_start
            self._fill_row(self._current, item)

    def _on_finished(self, state, payload):
        if self._current is None:
            return
        item = self.queue[self._current]
        skipped = payload.get("skipped")
        reason = payload.get("reason") or ""
        if state == "done" and skipped and not payload.get("out"):
            # 一条龙里只勾了修复、又没检测到目标：跳过，不算失败
            item.status = STATUS_SKIPPED
            item.message = "未检测到目标：%s" % (reason or "无")
            item.pct = 100
            item.elapsed = float(payload.get("elapsed") or 0)
            self.append_log("⚠ 跳过：%s —— %s" % (item.name, item.message))
            self.append_log("   只做超分请取消勾选「区域修复」；要指定位置用「手动矩形」/「逐帧掩码」")
        elif state == "done":
            preview = bool(payload.get("preview"))
            if preview:
                item.status = "完成（预览）"
            else:
                item.status = "完成（跳修复）" if skipped else STATUS_DONE
            item.out = payload.get("out") or ""
            item.pct = 100
            item.elapsed = float(payload.get("elapsed") or 0)
            self._last_out = item.out
            if skipped:
                self.append_log("⚠ %s 未检测到稳定目标，已跳过区域修复，只做了超分" % item.name)
                self.append_log("   %s" % reason)
            self.append_log("✔ %s完成：%s（%s）"
                            % ("预览" if payload.get("preview") else "",
                               item.out, self._size_text(payload.get("size"))))
        elif state == "cancelled":
            item.status = STATUS_CANCELLED
            item.message = "已取消"
            self._cancel_all = True
            self.append_log("✖ 已取消：%s" % item.name)
        else:
            item.status = STATUS_FAILED
            msg = payload.get("msg") or "任务失败（没有返回具体原因）"
            hint = payload.get("hint") or ""
            code = payload.get("code")
            item.message = msg
            self.append_log("✖ 失败：%s" % item.name)
            self.append_log("   原因：%s" % msg)
            if hint:
                self.append_log("   建议：%s" % hint)
            if code is not None:
                self.append_log("   退出码：%s（完整日志见上方）" % code)
            self.status_label.setText(msg[:60])
            self.status_label.setStyleSheet("color:#c62828")
            if not self.log_box.is_expanded():
                self.log_box.set_expanded(True)
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
        done = sum(1 for it in self.queue if it.status in (STATUS_DONE, "完成（跳修复）", "完成（预览）"))
        skipped = sum(1 for it in self.queue if it.status == STATUS_SKIPPED)
        failed = sum(1 for it in self.queue if it.status in (STATUS_FAILED, STATUS_CANCELLED))
        self.status_label.setText("完成 %d 个，跳过 %d 个，失败/取消 %d 个"
                                  % (done, skipped, failed))
        self.append_log("===== 队列结束：成功 %d，跳过 %d，失败/取消 %d，总用时 %.0fs ====="
                        % (done, skipped, failed, time.time() - self._t_start))
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
                  self.drop, self.repair_panel, self.sr_panel, self.output_panel,
                  self.keep, self.open_when_done):
            w.setEnabled(not running)
        for btn in self._preset_buttons.values():
            btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        if not running:
            self._on_modules_changed()
            self._refresh_queue_label()

    def append_log(self, text):
        if not text:
            return
        for line in str(text).splitlines():
            self.log.appendPlainText(line)

    # ================================================================ 其它
    def pick_mask(self):
        current = self.repair_panel.mask.text().strip()
        if os.path.isdir(current or ""):
            d = QFileDialog.getExistingDirectory(self, "选择掩码目录", current)
            if d:
                self.repair_panel.mask.setText(d)
            return
        f, _ = QFileDialog.getOpenFileName(self, "选择掩码（单张 png，或目录里的任意一张）",
                                           "", "PNG (*.png);;所有文件 (*.*)")
        if f:
            self.repair_panel.mask.setText(f)

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录",
                                             self.output_panel.out_dir_text())
        if d:
            self.output_panel.out_dir.setText(d)

    def open_output(self):
        target = self._last_out or ""
        if not target:
            done = [it for it in self.queue if it.status == STATUS_DONE and it.out]
            if done:
                target = done[-1].out
        if not target:
            d = self.output_panel.out_dir_text()
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
