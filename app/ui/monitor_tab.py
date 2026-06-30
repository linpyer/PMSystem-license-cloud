from __future__ import annotations

import logging
from pathlib import Path

import cv2
from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QPlainTextEdit,
    QTableView,
    QTableWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QApplication,
    QButtonGroup,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.camera import list_camera_devices
from app.core.database import DatabaseManager
from app.core.recorder import RecorderThread
from app.core.scanner import normalize_scan_text
from app.core.scanner_guard import ScannerGuard
from app.core.video_player import open_folder, open_video, reveal_in_file_manager
from app.core.voice_prompt import VoicePrompt
from app.utils.file_utils import ensure_directory
from app.utils.time_utils import format_duration


FPS_OPTIONS = [15, 20, 25, 30, 60]
DEFAULT_FPS = 25
LONG_EDGE_OPTIONS = [0, 960, 1280, 1920]
DEFAULT_LONG_EDGE = 1280

FPS_HELP_TEXT = """帧率表示每秒录制多少张画面。

帧率越高，画面越顺滑，但视频文件会更大，电脑性能压力也会更高。

打包监控主要用于记录打包过程，一般不需要过高帧率，推荐使用 25 FPS。

选项说明：

15 FPS：文件更小，适合低配电脑或只需要基本记录的场景。

20 FPS：比 15 FPS 更顺滑，文件大小适中。

25 FPS：推荐默认值，清晰度、流畅度和文件大小比较均衡。

30 FPS：画面更顺滑，但文件更大，电脑压力更高。

60 FPS：画面非常顺滑，但文件更大，对摄像头和电脑性能要求更高。只有在设备支持且确实需要更高流畅度时再选择。"""

CAMERA_HELP_TEXT = """摄像头设备用于选择当前软件录制使用的摄像头。

如果电脑只连接了一个摄像头，一般选择默认设备即可。

如果连接了多个摄像头，可以在这里切换不同摄像头。

选择后建议先查看预览画面，确认拍摄角度和画面内容正常。

如果摄像头画面打不开，请检查摄像头是否被其他软件占用，或者尝试重新插拔摄像头。"""

RESOLUTION_HELP_TEXT = """分辨率表示摄像头采集画面的宽度和高度。

分辨率越高，画面越清晰，但视频文件会更大，电脑性能压力也会更高。

分辨率越低，视频文件更小，录制更稳定，但画面细节会减少。

打包监控主要用于记录商品、打包过程和发货证据，建议优先选择画面清晰且运行稳定的分辨率。

如果发现画面卡顿或文件过大，可以适当降低分辨率。"""

LONG_EDGE_HELP_TEXT = """录制长边上限用于限制视频最大分辨率。

长边指视频画面中最长的一边。例如 1920×1080 的画面，长边就是 1920。

数值越大，画面越清晰，但视频文件越大，电脑压力也越高。

数值越小，视频文件越小，录制更稳定，但画面清晰度会下降。

推荐使用 1280。

选项说明：

不限制：使用摄像头原始分辨率，画质最高，但文件可能更大。

960：文件更小，适合低配电脑或硬盘空间紧张的场景。

1280：推荐默认值，清晰度和文件大小比较均衡。

1920：更清晰，适合需要看清更多细节的场景，但文件更大。"""

WATERMARK_FONT_HELP_TEXT = """水印字号用于设置视频中单号和日期时间水印文字的大小。

字号越大，水印越清楚，但会占用更多画面空间。

字号越小，画面遮挡更少，但水印可能不够清晰。

建议根据摄像头分辨率调整字号，确保录制视频中单号和时间能够清楚识别。

如果录制画面分辨率较高，可以适当增大字号。

如果水印遮挡商品或打包动作，可以适当减小字号。"""

WATERMARK_MARGIN_HELP_TEXT = """水印边距用于设置水印文字距离视频画面边缘的距离。

边距越大，水印离画面边缘越远。

边距越小，水印越靠近画面边缘。

合适的边距可以避免水印贴边显示，也能减少对打包画面的遮挡。

如果水印太靠近边缘，可以适当增大边距。

如果水印占用画面太多，可以适当减小边距。"""


class MonitorTab(QWidget):
    status_message = Signal(str)
    video_dir_changed = Signal(str)
    warning_message = Signal(str)
    critical_message = Signal(str)

    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logger
        self.config = self.config_manager.config
        self.is_recording = False
        self.current_order_id = ""
        self._pending_voice_action: str | None = None
        self._event_filter_installed = False
        self._normalize_video_config_on_startup()
        self.scanner_guard = ScannerGuard(self.config, logger)
        self.voice_prompt = VoicePrompt(self.config, logger)

        self.recorder = RecorderThread(config=self.config, base_dir=self.config_manager.base_dir, logger=logger)
        self._build_ui()
        self._connect_signals()
        self._load_config_to_controls()
        self._update_video_dir_label()

        self.recorder.start()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._event_filter_installed = True
        self.focus_scan_input()
        QTimer.singleShot(0, self.refresh_recent_recordings)

    def shutdown(self) -> None:
        if self._event_filter_installed:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._event_filter_installed = False
        self.recorder.stop_thread()
        self.recorder.wait(5000)
        self.voice_prompt.stop()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        focus_widget = QApplication.focusWidget()
        if event.type() == QEvent.MouseButtonPress and self._should_refocus_after_mouse_press(watched):
            self.focus_scan_input(80)
        if (
            event.type() == QEvent.KeyPress
            and self.isVisible()
            and self.is_recording
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and focus_widget is not self.scan_input
            and not normalize_scan_text(self.scan_input.text())
        ):
            self.logger.info("检测到空回车，停止当前录制")
            self._pending_voice_action = "stop"
            self.recorder.manual_stop()
            self.scan_input.clear()
            self.focus_scan_input()
            return True
        return super().eventFilter(watched, event)

    def _should_refocus_after_mouse_press(self, watched) -> bool:
        if not self.isVisible():
            return False
        if not isinstance(watched, QWidget):
            return False
        if watched is self.scan_input or self._has_parent_widget(watched, self.scan_input):
            return False
        if not (watched is self or self.isAncestorOf(watched)):
            return False
        if self._is_interactive_widget(watched):
            return False
        if self._is_text_input_widget(watched):
            return False

        app = QApplication.instance()
        focus_widget = app.focusWidget() if app is not None else None
        if isinstance(focus_widget, QWidget) and focus_widget is not self.scan_input:
            if self._is_text_input_widget(focus_widget):
                return False

        return True

    def _is_interactive_widget(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(
                current,
                (
                    QAbstractButton,
                    QCheckBox,
                    QComboBox,
                    QLineEdit,
                    QTextEdit,
                    QPlainTextEdit,
                    QAbstractSpinBox,
                    QDateEdit,
                    QTableWidget,
                    QTableView,
                    QAbstractItemView,
                    QHeaderView,
                    QScrollBar,
                    QTabBar,
                ),
            ):
                return True
            if isinstance(current, QLabel) and current.textInteractionFlags() & Qt.TextSelectableByMouse:
                return True
            current = current.parentWidget()
        return False

    def _is_text_input_widget(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return True
            if isinstance(current, QComboBox) and current.isEditable():
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _has_parent_widget(widget: QWidget, parent: QWidget) -> bool:
        current = widget.parentWidget()
        while current is not None:
            if current is parent:
                return True
            current = current.parentWidget()
        return False

    def focus_scan_input(self, delay_ms: int = 0, select_all: bool = False) -> None:
        def apply_focus() -> None:
            if not self._can_focus_scan_input():
                return
            self.scan_input.setFocus(Qt.OtherFocusReason)
            if select_all:
                self.scan_input.selectAll()

        QTimer.singleShot(max(0, delay_ms), apply_focus)

    def _can_focus_scan_input(self) -> bool:
        if not self.isVisible() or not self.scan_input.isVisible() or not self.scan_input.isEnabled():
            return False

        app = QApplication.instance()
        if app is None:
            return True
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return False

        root_window = self.window()
        active_window = app.activeWindow()
        if active_window is not None and active_window is not root_window:
            return False

        focus_widget = app.focusWidget()
        if focus_widget is None or focus_widget is self.scan_input:
            return True
        if focus_widget.window() is not root_window:
            return False
        if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return False
        if isinstance(focus_widget, QComboBox) and focus_widget.isEditable():
            return False
        return True

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        top_layout = QHBoxLayout()
        self.video_dir_label = QLabel()
        self.video_dir_label.setObjectName("pathLabel")
        self.video_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.video_dir_label.setWordWrap(True)
        self.choose_dir_button = QPushButton("选择保存目录")
        top_layout.addWidget(self.video_dir_label, 1)
        top_layout.addWidget(self.choose_dir_button)
        self.choose_dir_button.setObjectName("secondaryButton")
        root_layout.addLayout(top_layout)

        content_layout = QGridLayout()
        content_layout.setColumnStretch(0, 3)
        content_layout.setColumnStretch(1, 1)
        content_layout.setColumnMinimumWidth(1, 400)
        root_layout.addLayout(content_layout, 1)

        self.preview_label = QLabel("正在打开摄像头...")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(720, 480)
        content_layout.addWidget(self.preview_label, 0, 0)

        side_scroll = QScrollArea()
        side_scroll.setObjectName("rightOperationScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setMinimumWidth(400)
        side_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        side_panel_container = QWidget()
        side_panel_container.setObjectName("rightOperationPanel")
        side_panel_container.setMinimumWidth(380)
        side_panel_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        side_panel = QVBoxLayout(side_panel_container)
        side_panel.setContentsMargins(0, 0, 0, 0)
        side_panel.setSpacing(6)
        side_scroll.setWidget(side_panel_container)
        content_layout.addWidget(side_scroll, 0, 1)

        status_group = QGroupBox("")
        status_group.setObjectName("plainRightCard")
        status_layout = QFormLayout(status_group)
        status_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.setFormAlignment(Qt.AlignTop)
        status_layout.setHorizontalSpacing(10)
        status_layout.setVerticalSpacing(6)
        self.status_label = QLabel("未录制")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setProperty("state", "idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.rec_label = QLabel("REC")
        self.rec_label.setObjectName("recBadge")
        self.rec_label.setAlignment(Qt.AlignCenter)
        self.rec_label.setVisible(False)
        self.order_label = QLabel("-")
        self.start_time_label = QLabel("-")
        self.start_time_title_label = QLabel("开始时间：")
        self.duration_label = QLabel("00:00:00")
        self.duration_label.setObjectName("durationValue")
        self.camera_status_label = QLabel("摄像头初始化中")
        self.camera_status_label.setObjectName("cameraStatusValue")
        self.camera_status_label.setWordWrap(True)
        status_layout.addRow("状态：", self.status_label)
        status_layout.addRow("当前物流单号：", self.order_label)
        status_layout.addRow(self.start_time_title_label, self.start_time_label)
        status_layout.addRow("录制时长：", self.duration_label)
        status_layout.addRow("摄像头：", self.camera_status_label)
        self._set_start_time_visible(False)
        side_panel.addWidget(status_group)

        scan_group = QGroupBox("")
        scan_group.setObjectName("plainRightCard")
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setSpacing(6)
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("请扫描物流单号，扫码后自动回车。")
        self.scan_input.setClearButtonEnabled(True)
        self.scan_input.setObjectName("scanInput")
        self.scan_input.setPlaceholderText("请扫描或输入物流单号")

        record_type_title = QLabel("录制类型")
        record_type_title.setObjectName("recordTypeTitle")
        record_type_separator = QFrame()
        record_type_separator.setObjectName("recordTypeSeparator")
        record_type_separator.setFrameShape(QFrame.HLine)
        record_type_separator.setFrameShadow(QFrame.Plain)

        record_type_layout = QHBoxLayout()
        record_type_layout.setContentsMargins(0, 0, 0, 0)
        record_type_layout.setSpacing(24)
        self.ship_record_type_radio = QRadioButton("发货")
        self.return_record_type_radio = QRadioButton("退货")
        self.ship_record_type_radio.setObjectName("recordTypeRadio")
        self.return_record_type_radio.setObjectName("recordTypeRadio")
        self.ship_record_type_radio.setChecked(True)
        self.record_type_button_group = QButtonGroup(self)
        self.record_type_button_group.setExclusive(True)
        self.record_type_button_group.addButton(self.ship_record_type_radio, 1)
        self.record_type_button_group.addButton(self.return_record_type_radio, 2)
        record_type_layout.addWidget(self.ship_record_type_radio)
        record_type_layout.addWidget(self.return_record_type_radio)
        record_type_layout.addStretch(1)

        scan_title = QLabel("扫描物流单号")
        scan_title.setObjectName("sectionTitle")
        scan_layout.addWidget(record_type_title)
        scan_layout.addLayout(record_type_layout)
        scan_layout.addSpacing(5)
        scan_layout.addWidget(record_type_separator)
        scan_layout.addSpacing(5)
        scan_layout.addWidget(scan_title)
        scan_layout.addWidget(self.scan_input)
        side_panel.addWidget(scan_group)

        button_group = QGroupBox("")
        button_group.setObjectName("plainRightCard")
        button_layout = QGridLayout(button_group)
        button_layout.setHorizontalSpacing(8)
        button_layout.setVerticalSpacing(8)
        self.manual_start_button = QPushButton("手动开始录制")
        self.manual_start_button.setObjectName("primaryButton")
        self.manual_stop_button = QPushButton("手动停止录制")
        self.manual_stop_button.setObjectName("stopButton")
        self.open_folder_button = QPushButton("打开视频保存文件夹")
        self.refresh_camera_button = QPushButton("刷新摄像头")
        button_layout.addWidget(self.manual_start_button, 0, 0)
        button_layout.addWidget(self.manual_stop_button, 0, 1)
        button_layout.addWidget(self.open_folder_button, 1, 0)
        button_layout.addWidget(self.refresh_camera_button, 1, 1)
        self.open_folder_button.setObjectName("secondaryButton")
        self.refresh_camera_button.setObjectName("secondaryButton")
        side_panel.addWidget(button_group)

        recent_group = QGroupBox("")
        recent_group.setObjectName("recentCard")
        recent_layout = QVBoxLayout(recent_group)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(6)
        recent_title_layout = QHBoxLayout()
        recent_title_layout.setContentsMargins(0, 0, 0, 0)
        recent_title_layout.setSpacing(8)
        recent_title_accent = QFrame()
        recent_title_accent.setObjectName("recentTitleAccent")
        recent_title_accent.setFixedSize(3, 16)
        recent_title_label = QLabel("最近录制")
        recent_title_label.setObjectName("recentCardTitle")
        recent_title_layout.addWidget(recent_title_accent)
        recent_title_layout.addWidget(recent_title_label)
        recent_title_layout.addStretch(1)
        self.recent_recordings_layout = QVBoxLayout()
        self.recent_recordings_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_recordings_layout.setSpacing(0)
        recent_layout.addLayout(recent_title_layout)
        recent_layout.addLayout(self.recent_recordings_layout)
        side_panel.addWidget(recent_group)

        side_panel.addStretch(1)
        self.logger.info("录制类型单选框初始化")
        self.logger.info("最近录制模块初始化")
        self.logger.info("打包监控页右侧布局初始化")

    def _connect_signals(self) -> None:
        self.scan_input.returnPressed.connect(self._handle_scan_return)
        self.manual_start_button.clicked.connect(lambda: self._manual_start())
        self.manual_stop_button.clicked.connect(lambda: self._manual_stop())
        self.open_folder_button.clicked.connect(lambda: self._open_video_folder())
        self.refresh_camera_button.clicked.connect(lambda: self._refresh_camera())
        self.choose_dir_button.clicked.connect(lambda: self._choose_video_dir())
        self.ship_record_type_radio.toggled.connect(
            lambda checked: checked and self._on_record_type_changed("发货")
        )
        self.return_record_type_radio.toggled.connect(
            lambda checked: checked and self._on_record_type_changed("退货")
        )
        self.ship_record_type_radio.clicked.connect(lambda: self.focus_scan_input(80))
        self.return_record_type_radio.clicked.connect(lambda: self.focus_scan_input(80))

        self.recorder.frame_ready.connect(self._on_frame_ready)
        self.recorder.camera_status_changed.connect(self._on_camera_status_changed)
        self.recorder.recording_state_changed.connect(self._on_recording_state_changed)
        self.recorder.duration_changed.connect(self._on_duration_changed)
        self.recorder.message.connect(self._on_recorder_message)
        self.recorder.warning_message.connect(self._on_warning_message)
        self.recorder.critical_message.connect(self._on_critical_message)

    def _load_config_to_controls(self) -> None:
        self._set_record_type_selection(str(self.config.get("current_record_type") or "发货"))

    def load_video_config_to_ui(self) -> None:
        fps, _fps_valid = self._coerce_fps(self.config.get("fps", DEFAULT_FPS))
        max_long_edge, _edge_valid = self._coerce_long_edge(
            self.config.get("recording_max_long_edge", DEFAULT_LONG_EDGE)
        )
        self._select_combo_data(self.fps_combo, fps, DEFAULT_FPS)
        self._select_combo_data(self.recording_long_edge_combo, max_long_edge, DEFAULT_LONG_EDGE)
        self.logger.info("加载帧率配置成功：%s FPS", fps)
        self.logger.info("加载录制长边上限配置成功：%s", max_long_edge)

    def save_video_config_from_ui(self) -> dict[str, int]:
        fps = int(self.fps_combo.currentData() or DEFAULT_FPS)
        max_long_edge = int(self.recording_long_edge_combo.currentData() or 0)
        self.logger.info("保存 fps 配置：%s", fps)
        self.logger.info("保存 max_long_edge 配置：%s", max_long_edge)
        return {
            "fps": fps,
            "recording_max_long_edge": max_long_edge,
        }

    def _normalize_video_config_on_startup(self) -> None:
        fps, fps_valid = self._coerce_fps(self.config.get("fps", DEFAULT_FPS))
        max_long_edge, edge_valid = self._coerce_long_edge(
            self.config.get("recording_max_long_edge", DEFAULT_LONG_EDGE)
        )
        changed = False
        if not fps_valid or self.config.get("fps") != fps:
            self.config["fps"] = fps
            changed = True
        if not edge_valid or self.config.get("recording_max_long_edge") != max_long_edge:
            self.config["recording_max_long_edge"] = max_long_edge
            changed = True
        if changed:
            try:
                self.config_manager.save(self.config)
            except Exception:
                self.logger.exception("保存回退后的视频配置失败")

    def _coerce_fps(self, value) -> tuple[int, bool]:
        try:
            fps = int(value)
        except (TypeError, ValueError):
            self.logger.warning("检测到非法 fps 值并回退默认值：%s -> %s", value, DEFAULT_FPS)
            return DEFAULT_FPS, False
        if fps not in FPS_OPTIONS:
            self.logger.warning("检测到非法 fps 值并回退默认值：%s -> %s", value, DEFAULT_FPS)
            return DEFAULT_FPS, False
        return fps, True

    def _coerce_long_edge(self, value) -> tuple[int, bool]:
        if value is None:
            return 0, True
        if isinstance(value, str) and value.strip().lower() == "none":
            return 0, True
        try:
            max_long_edge = int(value)
        except (TypeError, ValueError):
            self.logger.warning(
                "检测到非法 max_long_edge 值并回退默认值：%s -> %s",
                value,
                DEFAULT_LONG_EDGE,
            )
            return DEFAULT_LONG_EDGE, False
        if max_long_edge not in LONG_EDGE_OPTIONS:
            self.logger.warning(
                "检测到非法 max_long_edge 值并回退默认值：%s -> %s",
                value,
                DEFAULT_LONG_EDGE,
            )
            return DEFAULT_LONG_EDGE, False
        return max_long_edge, True

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: int, fallback: int) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _select_combo_text(combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _help_label(self, text: str, title: str, body: str, tooltip: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(text)
        button = QToolButton()
        button.setObjectName("helpButton")
        button.setText("?")
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(lambda: self._show_help_dialog(title, body))
        layout.addWidget(label)
        layout.addWidget(button)
        layout.addStretch(1)
        return widget

    def _show_help_dialog(self, title: str, body: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(body)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()

    def _handle_scan_return(self) -> None:
        result = self.scanner_guard.process(self.scan_input.text())
        if result.should_warn:
            self.warning_message.emit(result.warning_message)
            self.status_message.emit(result.warning_message)
        if not self.is_recording and not result.cleaned_code:
            self._notify_no_order()
            self.scan_input.clear()
            self.focus_scan_input(80)
            return
        if not result.should_ignore:
            is_duplicate = self._warn_if_duplicate_recording(result.cleaned_code)
            self._pending_voice_action = self._voice_action_for_scan(result.cleaned_code, is_duplicate)
            self.recorder.scan(result.cleaned_code)
        self.scan_input.clear()
        self.focus_scan_input(80)

    def _manual_start(self) -> None:
        result = self.scanner_guard.process(self.scan_input.text(), debounce=False)
        if result.should_warn:
            self.warning_message.emit(result.warning_message)
            self.status_message.emit(result.warning_message)
        if not result.cleaned_code:
            if not self.is_recording:
                self._notify_no_order()
            else:
                self.warning_message.emit("请先输入或扫描物流单号。")
            self.focus_scan_input(80)
            return
        is_duplicate = self._warn_if_duplicate_recording(result.cleaned_code)
        self._pending_voice_action = None if is_duplicate else "start"
        self.recorder.manual_start(result.cleaned_code)
        self.scan_input.clear()
        self.focus_scan_input(80)

    def _notify_no_order(self) -> None:
        message = "请先输入或扫描物流单号。"
        self.warning_message.emit(message)
        self.status_message.emit(message)
        if self.voice_prompt.play("no_order"):
            self.logger.info("未输入单号语音已提交播放")

    def _manual_stop(self) -> None:
        if self.is_recording:
            self._pending_voice_action = "stop"
        self.recorder.manual_stop()
        self.focus_scan_input(80)

    def _current_record_type(self) -> str:
        return "退货" if self.return_record_type_radio.isChecked() else "发货"

    def _set_record_type_selection(self, record_type: str) -> None:
        record_type = record_type if record_type in {"发货", "退货"} else "发货"
        self.ship_record_type_radio.blockSignals(True)
        self.return_record_type_radio.blockSignals(True)
        self.record_type_button_group.setExclusive(False)
        if record_type == "退货":
            self.ship_record_type_radio.setChecked(False)
            self.return_record_type_radio.setChecked(True)
        else:
            self.ship_record_type_radio.setChecked(True)
            self.return_record_type_radio.setChecked(False)
        self.record_type_button_group.setExclusive(True)
        self.ship_record_type_radio.blockSignals(False)
        self.return_record_type_radio.blockSignals(False)

    def _set_record_type_enabled(self, enabled: bool) -> None:
        if not self.ship_record_type_radio.isChecked() and not self.return_record_type_radio.isChecked():
            self._set_record_type_selection(str(self.config.get("current_record_type") or "发货"))
        self.ship_record_type_radio.setEnabled(enabled)
        self.return_record_type_radio.setEnabled(enabled)
        for radio in (self.ship_record_type_radio, self.return_record_type_radio):
            radio.style().unpolish(radio)
            radio.style().polish(radio)

    def _on_record_type_changed(self, value: str) -> None:
        record_type = value if value in {"发货", "退货"} else "发货"
        try:
            self.config = self.config_manager.update({"current_record_type": record_type})
            self.scanner_guard.update_config(self.config)
            self.voice_prompt.update_config(self.config)
            self.recorder.update_config(self.config)
            self.logger.info("录制类型切换：%s", record_type)
        except Exception as exc:
            self.logger.exception("录制类型保存失败")
            self.critical_message.emit("录制类型保存失败，请查看日志。")
        self.focus_scan_input(80)

    def _voice_action_for_scan(self, order_id: str, is_duplicate: bool) -> str | None:
        order_id = order_id.strip()
        if self.is_recording:
            if not order_id or order_id == self.current_order_id:
                return "stop"
            return "switch"
        if order_id and not is_duplicate:
            return "start"
        return None

    def _warn_if_duplicate_recording(self, order_id: str) -> bool:
        order_id = order_id.strip()
        if not order_id:
            return False
        if self.is_recording and order_id == self.current_order_id:
            return False

        try:
            video_dir = self.config_manager.get_video_dir()
            database = DatabaseManager(self.config_manager.base_dir / "pm_system.db", self.logger)
            duplicate_count = database.count_order_no(order_id, video_dir)
            database.close()
        except Exception:
            self.logger.exception("重复录制检查失败：物流单号=%s", order_id)
            return False

        if duplicate_count <= 0:
            return False

        message = "检测到该单号已录制过，本次录制不会被阻止，系统会保留多条记录。"
        self.logger.warning("检测到历史重复录制单号：物流单号=%s，历史记录数=%s", order_id, duplicate_count)
        self.logger.info("重复录制继续录制：物流单号=%s", order_id)
        self.warning_message.emit(message)
        self.status_message.emit(message)
        if self.voice_prompt.speak_duplicate():
            self.logger.info("重复录制语音已提交播放：物流单号=%s", order_id)
        return True

    def _open_video_folder(self) -> None:
        video_dir = ensure_directory(self.config_manager.get_video_dir())
        try:
            open_folder(video_dir)
        except Exception as exc:
            self.logger.exception("打开视频保存文件夹失败")
            self.critical_message.emit(f"打开失败：{exc}")
        self.focus_scan_input(100)

    def _refresh_camera(self) -> None:
        if self.is_recording:
            self.warning_message.emit("录制中不能刷新摄像头。")
            self.focus_scan_input(80)
            return
        self.recorder.restart_camera()
        self.status_message.emit("摄像头已刷新")
        self.focus_scan_input(100)

    def _choose_video_dir(self) -> None:
        if self.is_recording:
            self.warning_message.emit("录制中不能修改视频保存目录。")
            self.focus_scan_input(80)
            return

        current_dir = str(self.config_manager.get_video_dir())
        selected = QFileDialog.getExistingDirectory(self, "选择视频保存目录", current_dir)
        if not selected:
            self.focus_scan_input(100)
            return

        selected_path = Path(selected)
        if not selected_path.exists() or not selected_path.is_dir():
            self.logger.warning("保存目录无效：%s", selected)
            self.warning_message.emit("保存目录无效。")
            self.focus_scan_input()
            return

        try:
            self.config = self.config_manager.update({"video_save_dir": selected})
            self.scanner_guard.update_config(self.config)
            ensure_directory(selected_path)
            self.recorder.update_config(self.config)
            self._update_video_dir_label()
            self.video_dir_changed.emit(str(self.config_manager.get_video_dir()))
            self.logger.info("视频保存目录已更新：%s", self.config_manager.get_video_dir())
        except Exception:
            self.logger.exception("保存目录保存失败：%s", selected)
            self.critical_message.emit("保存目录保存失败，请查看日志。")
        self.focus_scan_input(100)

    def _apply_config(self) -> None:
        if self.is_recording:
            self.warning_message.emit("录制中不能修改摄像头配置。")
            return

        try:
            values = {
                "camera_index": int(self.camera_combo.currentData() or 0),
                "camera_name": self._selected_camera_name(),
                "resolution": self.resolution_combo.currentData(),
                **self.save_video_config_from_ui(),
                "current_record_type": self._current_record_type(),
                "watermark_font_size": self.font_size_spin.value(),
                "watermark_margin": self.margin_spin.value(),
            }
            self.config = self.config_manager.update(values)
            self.scanner_guard.update_config(self.config)
            self.voice_prompt.update_config(self.config)
            self.recorder.update_config(self.config)
            self.recorder.restart_camera()
            self.logger.info("监控页配置保存成功")
        except Exception as exc:
            self.logger.exception("配置保存失败")
            self.status_message.emit(f"配置保存失败：{exc}")
        self.focus_scan_input(80)

    def _refresh_camera_options(self, selected_index: int | None = None) -> None:
        selected_index = int(selected_index if selected_index is not None else self.config.get("camera_index", 0) or 0)
        devices = list_camera_devices()
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()

        has_selected = False
        for device in devices:
            label = f"{device.name}（索引 {device.index}）"
            self.camera_combo.addItem(label, device.index)
            if device.index == selected_index:
                has_selected = True

        if not has_selected:
            self.camera_combo.addItem(f"摄像头 {selected_index}（未从系统设备列表识别）", selected_index)

        combo_index = self.camera_combo.findData(selected_index)
        self.camera_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        self.camera_combo.blockSignals(False)

    def _selected_camera_name(self) -> str:
        text = self.camera_combo.currentText()
        if "（索引 " in text:
            return text.split("（索引 ", 1)[0]
        return text

    def _on_frame_ready(self, frame) -> None:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = rgb.shape
            bytes_per_line = channel * width
            image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image)
            self.preview_label.setPixmap(
                pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        except Exception as exc:
            self.logger.exception("预览画面更新失败")
            self.preview_label.setText(f"预览失败：{exc}")

    def _on_camera_status_changed(self, available: bool, message: str) -> None:
        self.camera_status_label.setText(message)
        self.camera_status_label.setToolTip(message)
        if not available:
            self.preview_label.setText("摄像头不可用")
        self.status_message.emit(message)

    def _set_status_badge(self, recording: bool) -> None:
        self.status_label.setText("正在录制" if recording else "未录制")
        self.status_label.setProperty("state", "recording" if recording else "idle")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_start_time_visible(self, visible: bool) -> None:
        self.start_time_title_label.setVisible(visible)
        self.start_time_label.setVisible(visible)

    def _on_recording_state_changed(self, recording: bool, order_id: str, start_time: str) -> None:
        self.is_recording = recording
        self._set_record_type_enabled(not recording)
        if recording:
            self.current_order_id = order_id
            self._set_status_badge(True)
            self._set_start_time_visible(True)
            self.rec_label.setVisible(False)
            self.order_label.setText(order_id)
            self.start_time_label.setText(start_time)
            if self._pending_voice_action == "switch":
                if self.voice_prompt.speak_switch():
                    self.logger.info("切换录制语音已提交播放：物流单号=%s", order_id)
                self._pending_voice_action = None
            elif self._pending_voice_action == "start":
                if self.voice_prompt.speak_start():
                    self.logger.info("开始录制语音已提交播放：物流单号=%s", order_id)
                self._pending_voice_action = None
            elif self._pending_voice_action not in (None, "stop"):
                self._pending_voice_action = None
        else:
            self.current_order_id = ""
            self._set_status_badge(False)
            self._set_start_time_visible(False)
            self.rec_label.setVisible(False)
            self.order_label.setText("-")
            self.start_time_label.setText("-")
            if self._pending_voice_action not in (None, "stop", "switch"):
                self._pending_voice_action = None
        self.focus_scan_input()

    def _on_duration_changed(self, seconds: int) -> None:
        self.duration_label.setText(format_duration(seconds))

    def _on_recorder_message(self, message: str) -> None:
        self.status_message.emit(message)
        if message.startswith("视频保存成功"):
            self.logger.info("新视频保存后刷新最近录制模块")
            QTimer.singleShot(200, self.refresh_recent_recordings)
        if self._pending_voice_action == "stop":
            if message.startswith("视频保存成功"):
                if self.voice_prompt.speak_stop():
                    self.logger.info("结束录制语音已提交播放")
                self._pending_voice_action = None
            elif message.startswith("视频保存失败") or "保存失败" in message or message.startswith("视频可能保存异常"):
                self._pending_voice_action = None
        self.focus_scan_input()

    def _on_warning_message(self, message: str) -> None:
        self.warning_message.emit(message)
        self.status_message.emit(message)
        self.focus_scan_input()

    def _on_critical_message(self, message: str) -> None:
        self.critical_message.emit(message)
        self.status_message.emit(message)
        self.focus_scan_input()

    def _update_video_dir_label(self) -> None:
        video_dir = self.config_manager.get_video_dir()
        self.video_dir_label.setText(f"当前视频保存目录：{video_dir}")
        self.video_dir_label.setToolTip(str(video_dir))

    def apply_external_config(self, config: dict) -> None:
        self.config = config
        self.scanner_guard.update_config(self.config)
        self.voice_prompt.update_config(self.config)
        self.recorder.update_config(self.config)
        self.focus_scan_input()

    def apply_basic_config(self, config: dict) -> None:
        if self.is_recording:
            self.logger.info("录制中尝试修改基础配置")
            self.warning_message.emit("录制中不能修改基础配置，请结束录制后再修改。")
            return
        self.apply_external_config(config)
        self.recorder.restart_camera()

    def refresh_recent_recordings(self) -> None:
        try:
            database = DatabaseManager(self.config_manager.base_dir / "pm_system.db", self.logger)
            rows = database.get_recent_videos(self.config_manager.get_video_dir(), limit=3)
            database.close()
            self._render_recent_recordings(rows)
        except Exception:
            self.logger.exception("最近录制查询失败")
            self._render_recent_recordings([])
            self.warning_message.emit("最近录制查询失败")

    def _render_recent_recordings(self, rows: list[dict]) -> None:
        self._clear_layout(self.recent_recordings_layout)
        if not rows:
            empty_label = QLabel("暂无最近录制")
            empty_label.setObjectName("hintLabel")
            empty_label.setAlignment(Qt.AlignCenter)
            self.recent_recordings_layout.addWidget(empty_label)
            return

        for item in rows[:3]:
            path = Path(str(item.get("file_path", "")))
            row_widget = QWidget()
            row_widget.setObjectName("recentRecordingRow")
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 4)
            row_layout.setSpacing(2)

            order_label = QLabel(str(item.get("order_no") or "-"))
            order_label.setObjectName("recentOrderText")
            order_label.setToolTip(str(path))
            record_type_label = QLabel(str(item.get("record_type") or "发货"))
            record_type_label.setObjectName("recentTypeTag")
            record_type_label.setProperty(
                "recordType",
                "return" if str(item.get("record_type") or "发货") == "退货" else "ship",
            )
            duration_label = QLabel(str(item.get("duration_text") or "-"))
            duration_label.setObjectName("recentMetaText")

            meta_layout = QHBoxLayout()
            meta_layout.setContentsMargins(0, 0, 0, 0)
            meta_layout.setSpacing(8)

            open_button = QPushButton("打开")
            open_button.setObjectName("sceneLinkButton")
            open_button.setCursor(Qt.PointingHandCursor)
            open_button.clicked.connect(lambda _checked=False, video_path=path: self._open_recent_video(video_path))

            reveal_button = QPushButton("定位")
            reveal_button.setObjectName("sceneLinkButton")
            reveal_button.setCursor(Qt.PointingHandCursor)
            reveal_button.clicked.connect(lambda _checked=False, video_path=path: self._reveal_recent_video(video_path))

            row_layout.addWidget(order_label)
            meta_layout.addWidget(record_type_label)
            meta_layout.addWidget(duration_label)
            meta_layout.addStretch(1)
            meta_layout.addWidget(open_button)
            meta_layout.addWidget(reveal_button)
            row_layout.addLayout(meta_layout)
            self.recent_recordings_layout.addWidget(row_widget)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                MonitorTab._clear_layout(child_layout)  # type: ignore[arg-type]

    def _open_recent_video(self, path: Path) -> None:
        try:
            self.logger.info("最近录制点击打开：%s", path)
            if not path.exists():
                self.logger.warning("最近录制视频文件不存在：%s", path)
                self.warning_message.emit("视频文件不存在")
                return
            open_video(path)
        except Exception as exc:
            self.logger.exception("最近录制打开失败：%s", path)
            self.critical_message.emit(f"打开失败：{exc}")

    def _reveal_recent_video(self, path: Path) -> None:
        try:
            self.logger.info("最近录制点击定位：%s", path)
            reveal_in_file_manager(path)
        except FileNotFoundError:
            self.logger.warning("最近录制视频文件不存在：%s", path)
            parent = path.parent
            if parent.exists() and parent.is_dir():
                try:
                    open_folder(parent)
                    self.warning_message.emit("视频文件不存在，已打开所在目录")
                except Exception as exc:
                    self.logger.exception("最近录制定位失败：%s", path)
                    self.critical_message.emit(f"定位失败：{exc}")
            else:
                self.warning_message.emit("视频文件不存在")
        except Exception as exc:
            self.logger.exception("最近录制定位失败：%s", path)
            parent = path.parent
            if parent.exists() and parent.is_dir():
                try:
                    open_folder(parent)
                    self.warning_message.emit("定位失败，已打开所在目录")
                except Exception as folder_exc:
                    self.critical_message.emit(f"定位失败：{folder_exc}")
            else:
                self.critical_message.emit(f"定位失败：{exc}")
