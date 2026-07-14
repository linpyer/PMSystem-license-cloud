from __future__ import annotations

import logging
import shutil
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.camera import list_camera_devices
from app.core.changelog import CHANGELOG_ENTRIES
from app.core.config_manager import AUTO_SYNC_DELAY_OPTIONS, ConfigManager, normalize_cloud_sync_config
from app.core.netdisk_sync import (
    BaiduNetdiskClient,
    NetdiskError,
    build_authorize_url,
    normalize_netdisk_config,
    normalize_remote_root,
)
from app.core.version import APP_VERSION
from app.core.video_player import open_folder
from app.core.voice_prompt import (
    DEFAULT_SYSTEM_TEXT,
    DEFAULT_VOICE_PROMPT_CONFIG,
    SUPPORTED_AUDIO_EXTENSIONS,
    VoicePrompt,
)
from app.ui.monitor_tab import (
    CAMERA_HELP_TEXT,
    DEFAULT_FPS,
    DEFAULT_LONG_EDGE,
    FPS_HELP_TEXT,
    FPS_OPTIONS,
    LONG_EDGE_HELP_TEXT,
    LONG_EDGE_OPTIONS,
    RESOLUTION_HELP_TEXT,
    WATERMARK_FONT_HELP_TEXT,
    WATERMARK_MARGIN_HELP_TEXT,
)
from app.ui.toast import ToastManager, show_toast
from app.ui.confirm_dialog import confirm_action
from app.ui.theme_icons import themed_svg_icon
from app.ui.dialog_utils import DialogSizeManager, install_no_wheel_on_children
from app.utils.runtime_paths import resource_path


VOICE_SETTINGS_EVENTS: tuple[tuple[str, str, str, str], ...] = (
    ("start", "开始录制提示语", "开始录制提示音", "start"),
    ("stop", "结束录制提示语", "结束录制提示音", "stop"),
    ("switch", "切换录制提示语", "切换录制提示音", "switch"),
    ("duplicate", "重复录制提示语", "重复录制提示音", "duplicate"),
    ("no_order", "未输入单号提示语", "未输入单号提示音", "no_order"),
    ("camera_lost", "摄像头异常提示语", "摄像头异常提示音", "camera_lost"),
    ("record_error", "录制异常提示语", "录制异常提示音", "record_error"),
    ("disk_full", "磁盘空间不足提示语", "磁盘空间不足提示音", "disk_full"),
)


class SettingsDialog(QDialog):
    config_saved = Signal(dict)
    basic_config_saved = Signal(dict)
    closed = Signal()

    def __init__(
        self,
        config_manager: ConfigManager,
        logger: logging.Logger,
        voice_prompt: VoicePrompt,
        is_recording_callback=None,
        is_syncing_callback=None,
        theme_manager=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logger
        self.voice_prompt = voice_prompt
        self.is_recording_callback = is_recording_callback or (lambda: False)
        self.is_syncing_callback = is_syncing_callback or (lambda: False)
        self.theme_manager = theme_manager
        self._theme_preview_session_active = False
        self._theme_preview_saved = False
        self._theme_preview_request_id = 0
        self._close_finalized = False
        self.original_theme_mode = "system"
        self.original_resolved_theme = "light"
        self.voice_file_labels: dict[str, QLabel] = {}
        self.voice_row_buttons: dict[str, tuple[QToolButton, QToolButton, QToolButton]] = {}
        self.system_text_edits: dict[str, QLineEdit] = {}

        self.setObjectName("settingsDialog")
        self.setWindowTitle("设置")
        self._build_ui()
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(self._refresh_voice_action_icons)
        self.begin_theme_preview_session()
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
        self._load_netdisk_config_to_ui()
        install_no_wheel_on_children(self)
        DialogSizeManager.apply(self, "settings", parent, "large", (780, 560))
        self.logger.info("基础配置页签初始化")
        self.logger.info("语音提示页签初始化")
        self.logger.info("网盘同步页签初始化")
        self.logger.info("配置管理页签初始化")
        self.logger.info("更新日志页签初始化")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._schedule_close_finalization()
        event.accept()
        super().closeEvent(event)

    def reject(self) -> None:  # type: ignore[override]
        self._schedule_close_finalization()
        super().reject()

    def begin_theme_preview_session(self) -> None:
        """Capture the persisted appearance before this settings session previews it."""
        toast_manager = getattr(self, "_toast_manager", None)
        if isinstance(toast_manager, ToastManager):
            toast_manager.clear()
        self._close_finalized = False
        if self.theme_manager is None:
            return
        self._theme_preview_session_active = True
        self._theme_preview_saved = False
        self.original_theme_mode = self.theme_manager.current_mode()
        self.original_resolved_theme = self.theme_manager.resolved_theme()
        self.theme_manager.begin_preview()
        self._load_appearance_config_to_ui()

    def _cancel_theme_preview_if_needed(self) -> None:
        if self.theme_manager is None or not self._theme_preview_session_active:
            return
        if not self._theme_preview_saved and self.theme_manager.current_mode() != self.original_theme_mode:
            self.theme_manager.cancel_preview()
        self._theme_preview_session_active = False

    def _schedule_close_finalization(self) -> None:
        """Defer non-visual cleanup so the settings window can hide immediately."""
        if self._close_finalized:
            return
        toast_manager = getattr(self, "_toast_manager", None)
        if isinstance(toast_manager, ToastManager):
            toast_manager.clear()
        self._close_finalized = True
        QTimer.singleShot(0, self._finalize_close_session)

    def _finalize_close_session(self) -> None:
        started = time.perf_counter()
        self._cancel_theme_preview_if_needed()
        rollback_ms = (time.perf_counter() - started) * 1000
        geometry_started = time.perf_counter()
        DialogSizeManager.remember(self, "settings")
        geometry_ms = (time.perf_counter() - geometry_started) * 1000
        total_ms = (time.perf_counter() - started) * 1000
        self.logger.debug(
            "[SettingsClose] theme rollback: %.1f ms; save geometry: %.1f ms; cleanup: %.1f ms",
            rollback_ms,
            geometry_ms,
            max(0.0, total_ms - rollback_ms - geometry_ms),
        )
        QTimer.singleShot(0, self.closed.emit)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_basic_tab(), "基础配置")
        self.tabs.addTab(self._build_voice_tab(), "语音提示")
        self.tabs.addTab(self._build_netdisk_tab(), "网盘同步")
        self.tabs.addTab(self._build_config_management_tab(), "配置管理")
        self.tabs.addTab(self._build_changelog_tab(), "更新日志")
        root_layout.addWidget(self.tabs, 1)
        self._clear_theme_conflicting_styles()

    def _clear_theme_conflicting_styles(self) -> None:
        """Let the application stylesheet own the core settings appearance."""
        for object_name in (
            "configManagementCard",
            "changelogCard",
            "voiceModePanel",
            "customVoicePanel",
        ):
            for widget in self.findChildren(QWidget, object_name):
                widget.setStyleSheet("")
        for widget in (
            getattr(self, "voice_enabled_check", None),
            getattr(self, "netdisk_enabled_check", None),
            getattr(self, "auto_sync_enabled_check", None),
        ):
            if widget is not None:
                widget.setStyleSheet("")

    def _settings_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("settingsCardTitle")
        layout.addWidget(title_label)
        return card, layout

    @staticmethod
    def _set_compact_control(widget: QWidget, width: int | None = None) -> QWidget:
        widget.setMinimumHeight(32)
        widget.setMaximumHeight(36)
        widget.setSizePolicy(QSizePolicy.Fixed if width else QSizePolicy.Expanding, QSizePolicy.Fixed)
        if isinstance(widget, QComboBox) and not widget.objectName():
            widget.setObjectName("settingsCompactCombo")
        elif isinstance(widget, QSpinBox) and not widget.objectName():
            widget.setObjectName("settingsCompactSpin")
        if width:
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width)
        return widget

    @staticmethod
    def _fit_combo_width_to_items(combo: QComboBox, min_width: int = 160, extra_padding: int = 58) -> int:
        max_text_width = 0
        metrics = combo.fontMetrics()
        for index in range(combo.count()):
            max_text_width = max(max_text_width, metrics.horizontalAdvance(combo.itemText(index)))
        width = max(min_width, max_text_width + extra_padding)
        combo.setMinimumWidth(width)
        combo.setMaximumWidth(width)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        combo.view().setMinimumWidth(width)
        return width

    def _build_config_management_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("configManagementCard")
        card.setStyleSheet(
            """
            QFrame#configManagementCard {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
            QLabel#configManagementTitle {
                color: #0f172a;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#configManagementHint {
                color: #475569;
                line-height: 1.45;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        title = QLabel("配置导出 / 导入")
        title.setObjectName("configManagementTitle")
        card_layout.addWidget(title)

        hint = QLabel(
            "用于换电脑或重装软件时迁移主要配置。导出文件不会包含数据库、视频、日志，也不会包含网盘 Secret 和授权 Token；导入后如需网盘同步，请重新授权。"
        )
        hint.setObjectName("configManagementHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.export_config_button = QPushButton("导出配置")
        self.export_config_button.setObjectName("primaryButton")
        self.export_config_button.clicked.connect(self._export_config)
        self.import_config_button = QPushButton("导入配置")
        self.import_config_button.setObjectName("secondaryButton")
        self.import_config_button.clicked.connect(self._import_config)
        button_row.addWidget(self.export_config_button)
        button_row.addWidget(self.import_config_button)
        button_row.addStretch(1)
        card_layout.addLayout(button_row)

        note = QLabel("自定义语音包会随配置导出到同名 _voice 文件夹；导入时会复制到本机用户数据目录。")
        note.setObjectName("configManagementHint")
        note.setWordWrap(True)
        card_layout.addWidget(note)

        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def _build_changelog_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        current_version = QLabel(f"当前版本：v{APP_VERSION}")
        current_version.setObjectName("settingsCurrentVersion")
        layout.addWidget(current_version, 0, Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        for entry in CHANGELOG_ENTRIES:
            card = QFrame()
            card.setObjectName("changelogCard")
            card.setStyleSheet(
                """
                QFrame#changelogCard {
                    background: #ffffff;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                }
                QLabel#changelogVersion {
                    color: #0f172a;
                    font-size: 15pt;
                    font-weight: 700;
                }
                QLabel#changelogSection {
                    color: #0f766e;
                    font-size: 10pt;
                    font-weight: 700;
                    margin-top: 6px;
                }
                QLabel#changelogItem {
                    color: #334155;
                    font-size: 9pt;
                    line-height: 1.45;
                }
                """
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)

            version_text = str(entry.get("version", ""))
            release_date = str(entry.get("date", "") or "")
            version_label = QLabel(f"{version_text}  ·  {release_date}" if release_date else version_text)
            version_label.setObjectName("changelogVersion")
            card_layout.addWidget(version_label)

            sections = (
                ("新增", entry.get("features", [])),
                ("优化", entry.get("optimizations", [])),
                ("修复", entry.get("fixes", [])),
                ("说明", entry.get("notes", [])),
            )
            for title, items in sections:
                if not items:
                    continue
                section_label = QLabel(title)
                section_label.setObjectName("changelogSection")
                card_layout.addWidget(section_label)
                for item in items:
                    item_label = QLabel(f"• {item}")
                    item_label.setObjectName("changelogItem")
                    item_label.setWordWrap(True)
                    card_layout.addWidget(item_label)

            content_layout.addWidget(card)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return widget

    def _build_basic_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("settingsBasicTab")
        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setObjectName("settingsBasicScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setObjectName("settingsBasicScrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignTop)

        label_width = 132

        def compact(widget: QWidget, width: int | None = None) -> QWidget:
            self._set_compact_control(widget, width)
            widget.setMinimumHeight(32)
            widget.setMaximumHeight(34)
            return widget

        def label(text: str) -> QLabel:
            item = QLabel(text)
            item.setMinimumWidth(label_width)
            item.setMaximumWidth(label_width)
            item.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return item

        def help_label(text: str, title: str, body: str, tooltip: str) -> QWidget:
            item = self._help_label(text, title, body, tooltip)
            item.setMinimumWidth(label_width)
            item.setMaximumWidth(label_width)
            item.setStyleSheet("QWidget { background: transparent; } QLabel { background: transparent; }")
            return item

        def tune_button(button: QPushButton) -> QPushButton:
            button.setMinimumHeight(32)
            button.setMaximumHeight(34)
            return button

        self.camera_combo = QComboBox()
        compact(self.camera_combo)
        self.camera_combo.setMinimumWidth(360)
        self.camera_combo.setMaximumWidth(560)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("原始分辨率", "original")
        self.resolution_combo.addItem("720p", "720p")
        self.resolution_combo.addItem("1080p", "1080p")
        compact(self.resolution_combo, 200)

        self.fps_combo = QComboBox()
        for fps in FPS_OPTIONS:
            self.fps_combo.addItem(f"{fps} FPS", fps)
        compact(self.fps_combo, 130)

        self.recording_long_edge_combo = QComboBox()
        self.recording_long_edge_combo.addItem("不限制，使用摄像头原始分辨率", 0)
        for edge in LONG_EDGE_OPTIONS[1:]:
            self.recording_long_edge_combo.addItem(str(edge), edge)
        compact(self.recording_long_edge_combo)
        self._fit_combo_width_to_items(self.recording_long_edge_combo, min_width=170)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(14, 72)
        compact(self.font_size_spin, 120)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(4, 80)
        compact(self.margin_spin, 120)

        appearance_card, appearance_layout = self._settings_card("外观设置")
        appearance_row = QHBoxLayout()
        appearance_row.setContentsMargins(0, 0, 0, 0)
        appearance_row.setSpacing(12)
        appearance_label = label("系统主题：")
        appearance_row.addWidget(appearance_label)
        self.theme_mode_group = QButtonGroup(self)
        self.theme_mode_buttons: dict[str, QRadioButton] = {}
        for mode, text in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            button = QRadioButton(text)
            button.setObjectName("appearanceThemeRadio")
            button.clicked.connect(lambda _checked=False, value=mode: self._queue_theme_preview(value))
            self.theme_mode_group.addButton(button)
            self.theme_mode_buttons[mode] = button
            appearance_row.addWidget(button)
        appearance_row.addStretch(1)
        appearance_layout.addLayout(appearance_row)
        appearance_hint = QLabel("选择后立即预览；点击“保存并应用配置”后才会写入配置。")
        appearance_hint.setObjectName("settingsHint")
        appearance_hint.setWordWrap(True)
        appearance_layout.addWidget(appearance_hint)
        layout.addWidget(appearance_card)

        video_card, video_layout = self._settings_card("视频存储")
        video_dir_row = QHBoxLayout()
        video_dir_row.setContentsMargins(0, 0, 0, 0)
        video_dir_row.setSpacing(8)
        self.video_root_dir_input = QLineEdit()
        self.video_root_dir_input.setPlaceholderText("请选择视频存储目录")
        compact(self.video_root_dir_input)
        self.video_root_dir_choose_button = QPushButton("选择目录")
        self.video_root_dir_choose_button.setObjectName("secondaryButton")
        self.video_root_dir_open_button = QPushButton("打开目录")
        self.video_root_dir_open_button.setObjectName("secondaryButton")
        tune_button(self.video_root_dir_choose_button)
        tune_button(self.video_root_dir_open_button)
        self.video_root_dir_choose_button.clicked.connect(self._choose_video_root_dir)
        self.video_root_dir_open_button.clicked.connect(self._open_video_root_dir)
        video_dir_row.addWidget(self.video_root_dir_input, 1)
        video_dir_row.addWidget(self.video_root_dir_choose_button)
        video_dir_row.addWidget(self.video_root_dir_open_button)
        video_grid = QGridLayout()
        video_grid.setContentsMargins(0, 0, 0, 0)
        video_grid.setHorizontalSpacing(12)
        video_grid.setVerticalSpacing(8)
        video_grid.setColumnMinimumWidth(0, label_width)
        video_grid.setColumnStretch(1, 1)
        video_grid.addWidget(label("视频存储目录："), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        video_grid.addLayout(video_dir_row, 0, 1)
        video_dir_hint = QLabel("新录制视频将保存到此目录，视频查询页也将从此目录读取数据。")
        video_dir_hint.setObjectName("settingsHint")
        video_dir_hint.setWordWrap(True)
        video_grid.addWidget(video_dir_hint, 1, 1)
        video_layout.addLayout(video_grid)
        layout.addWidget(video_card)

        camera_card, camera_layout = self._settings_card("摄像头与录制参数")
        camera_grid = QGridLayout()
        camera_grid.setContentsMargins(0, 0, 0, 0)
        camera_grid.setHorizontalSpacing(12)
        camera_grid.setVerticalSpacing(12)
        camera_grid.setColumnMinimumWidth(0, label_width)
        camera_grid.setColumnStretch(1, 1)

        self.camera_refresh_button = QPushButton("刷新设备")
        self.camera_refresh_button.setObjectName("secondaryButton")
        tune_button(self.camera_refresh_button)
        self.camera_refresh_button.clicked.connect(lambda: self._refresh_camera_options())
        camera_row = QHBoxLayout()
        camera_row.setContentsMargins(0, 0, 0, 0)
        camera_row.setSpacing(8)
        camera_row.addWidget(self.camera_combo, 0)
        camera_row.addWidget(self.camera_refresh_button, 0, Qt.AlignVCenter)
        camera_row.addStretch(1)
        camera_grid.addWidget(
            help_label("摄像头设备：", "摄像头设备说明", CAMERA_HELP_TEXT, "选择用于打包录制的摄像头设备。"),
            0,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        camera_grid.addLayout(camera_row, 0, 1)
        camera_grid.addWidget(
            help_label("分辨率：", "分辨率说明", RESOLUTION_HELP_TEXT, "设置摄像头采集画面的清晰度。"),
            1,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        camera_grid.addWidget(self.resolution_combo, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        camera_grid.addWidget(
            help_label("帧率：", "帧率说明", FPS_HELP_TEXT, "设置每秒录制画面数量，推荐 25 FPS。"),
            2,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        camera_grid.addWidget(self.fps_combo, 2, 1, Qt.AlignLeft | Qt.AlignVCenter)
        camera_grid.addWidget(
            help_label("录制长边上限：", "录制长边上限说明", LONG_EDGE_HELP_TEXT, "限制录制视频的最大边长，推荐 1280。"),
            3,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        camera_grid.addWidget(self.recording_long_edge_combo, 3, 1, Qt.AlignLeft | Qt.AlignVCenter)
        camera_layout.addLayout(camera_grid)
        layout.addWidget(camera_card)

        watermark_card, watermark_layout = self._settings_card("水印设置")
        watermark_grid = QGridLayout()
        watermark_grid.setContentsMargins(0, 0, 0, 0)
        watermark_grid.setHorizontalSpacing(12)
        watermark_grid.setVerticalSpacing(12)
        watermark_grid.setColumnMinimumWidth(0, label_width)
        watermark_grid.setColumnStretch(1, 1)
        watermark_grid.addWidget(
            help_label("水印字号：", "水印字号说明", WATERMARK_FONT_HELP_TEXT, "设置视频中单号和时间水印的文字大小。"),
            0,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        watermark_grid.addWidget(self.font_size_spin, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        watermark_grid.addWidget(
            help_label("水印边距：", "水印边距说明", WATERMARK_MARGIN_HELP_TEXT, "设置水印距离画面边缘的距离。"),
            1,
            0,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        watermark_grid.addWidget(self.margin_spin, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        watermark_layout.addLayout(watermark_grid)
        layout.addWidget(watermark_card)

        evidence_card, evidence_layout = self._settings_card("证据校验")
        evidence_grid = QGridLayout()
        evidence_grid.setContentsMargins(0, 0, 0, 0)
        evidence_grid.setHorizontalSpacing(12)
        evidence_grid.setVerticalSpacing(12)
        evidence_grid.setColumnMinimumWidth(0, label_width)
        evidence_grid.setColumnStretch(1, 1)

        self.hash_check_enabled = QCheckBox("开启视频哈希校验")
        self.hash_check_enabled.setObjectName("settingsInlineCheckBox")
        evidence_grid.addWidget(label("视频哈希校验："), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        evidence_grid.addWidget(self.hash_check_enabled, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        self.hash_algorithm_combo = QComboBox()
        self.hash_algorithm_combo.addItem("SHA256", "SHA256")
        compact(self.hash_algorithm_combo, 170)
        evidence_grid.addWidget(label("哈希算法："), 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        evidence_grid.addWidget(self.hash_algorithm_combo, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        hash_hint = QLabel("录制完成后自动生成 SHA256，用于校验视频文件是否被修改。大文件可能会增加少量后台处理时间。")
        hash_hint.setObjectName("settingsHint")
        hash_hint.setWordWrap(True)
        evidence_grid.addWidget(hash_hint, 2, 1)
        evidence_layout.addLayout(evidence_grid)
        layout.addWidget(evidence_card)

        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        action_bar = QWidget()
        action_bar.setObjectName("settingsBasicActionBar")
        action_bar.setFixedHeight(60)
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 8, 0, 0)
        self.restore_recommended_button = QPushButton("恢复推荐参数")
        self.restore_recommended_button.setObjectName("secondaryButton")
        tune_button(self.restore_recommended_button)
        self.restore_recommended_button.clicked.connect(self._restore_recommended_defaults)
        action_layout.addWidget(self.restore_recommended_button)
        action_layout.addStretch(1)
        self.apply_basic_config_button = QPushButton("保存并应用配置")
        self.apply_basic_config_button.setObjectName("primaryButton")
        tune_button(self.apply_basic_config_button)
        self.apply_basic_config_button.clicked.connect(self._save_basic_config)
        action_layout.addWidget(self.apply_basic_config_button)
        root_layout.addWidget(action_bar)
        return widget

    def _build_voice_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("settingsVoiceTab")
        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("settingsVoiceScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        content.setObjectName("settingsVoiceScrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 16)
        layout.setSpacing(14)

        self.voice_enabled_check = QCheckBox("开启语音提示")
        self.voice_enabled_check.setObjectName("settingsMainCheckBox")
        self.voice_enabled_check.toggled.connect(self._sync_voice_mode_ui)
        voice_enabled_row = QHBoxLayout()
        voice_enabled_row.setContentsMargins(0, 0, 0, 0)
        voice_enabled_row.addWidget(self.voice_enabled_check, 0, Qt.AlignLeft | Qt.AlignVCenter)
        voice_enabled_row.addStretch(1)
        voice_enabled_widget = QWidget()
        voice_enabled_widget.setFixedHeight(42)
        voice_enabled_widget.setLayout(voice_enabled_row)
        layout.addWidget(voice_enabled_widget)

        self.voice_mode_stack = QStackedWidget()
        self.voice_mode_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.voice_mode_stack.setMaximumHeight(42)
        self.voice_mode_blank = QWidget()
        self.voice_mode_stack.addWidget(self.voice_mode_blank)
        self.voice_mode_panel = QWidget()
        self.voice_mode_panel.setMinimumHeight(36)
        self.voice_mode_panel.setMaximumHeight(42)
        self.voice_mode_panel.setObjectName("voiceModePanel")
        mode_row = QHBoxLayout(self.voice_mode_panel)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(18)
        mode_row.addWidget(QLabel("语音模式："))
        self.voice_mode_group = QButtonGroup(self)
        self.voice_mode_group.setExclusive(True)
        self.system_voice_radio = QRadioButton("系统默认语音")
        self.custom_voice_radio = QRadioButton("自定义语音包")
        for radio, mode in (
            (self.system_voice_radio, "system"),
            (self.custom_voice_radio, "custom"),
        ):
            radio.setProperty("voice_mode", mode)
            radio.toggled.connect(self._sync_voice_mode_ui)
            self.voice_mode_group.addButton(radio)
            mode_row.addWidget(radio)
        mode_row.addStretch(1)
        self.voice_mode_stack.addWidget(self.voice_mode_panel)
        layout.addWidget(self.voice_mode_stack)

        self.voice_config_stack = QStackedWidget()
        self.voice_config_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.voice_config_stack.setMinimumHeight(0)
        self.voice_config_blank = QWidget()
        self.voice_config_stack.addWidget(self.voice_config_blank)

        self.system_voice_panel, system_layout = self._settings_card("系统默认语音")

        system_form = QFormLayout()
        system_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        system_form.setHorizontalSpacing(12)
        system_form.setVerticalSpacing(8)
        for event_key, text_label, _audio_label, _file_stem in VOICE_SETTINGS_EVENTS:
            edit = QLineEdit()
            edit.setPlaceholderText(DEFAULT_SYSTEM_TEXT.get(event_key, ""))
            self.system_text_edits[event_key] = edit
            system_form.addRow(f"{text_label}：", edit)
        system_layout.addLayout(system_form)
        system_layout.addStretch(1)
        self.voice_config_stack.addWidget(self.system_voice_panel)

        self.custom_voice_panel, custom_layout = self._settings_card("自定义语音包")
        self.custom_voice_panel.setObjectName("customVoicePanel")

        table_widget = QWidget()
        table_widget.setObjectName("voiceTableWidget")
        grid = QGridLayout(table_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.addWidget(self._header_label("提示场景"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self._header_label("当前音频文件"), 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self._header_label("操作"), 0, 2, Qt.AlignLeft | Qt.AlignVCenter)

        for item_index, (event_key, _text_label, audio_label, _file_stem) in enumerate(VOICE_SETTINGS_EVENTS, start=1):
            row_frame = QFrame()
            row_frame.setObjectName("voiceRecordRow")
            row_frame.setMinimumHeight(44)
            row_layout = QGridLayout(row_frame)
            row_layout.setContentsMargins(0, 4, 0, 4)
            row_layout.setHorizontalSpacing(8)
            row_layout.setVerticalSpacing(4)
            row_layout.setColumnStretch(0, 22)
            row_layout.setColumnStretch(1, 1)
            row_layout.setColumnMinimumWidth(2, 114)

            scene_label = QLabel(audio_label)
            file_label = QLabel("未设置")
            file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.voice_file_labels[event_key] = file_label

            upload_button = QToolButton()
            preview_button = QToolButton()
            reset_button = QToolButton()
            upload_button.setObjectName("voiceUploadIconButton")
            preview_button.setObjectName("voicePreviewIconButton")
            reset_button.setObjectName("voiceResetIconButton")
            upload_button.setProperty("voiceActionIcon", "upload")
            preview_button.setProperty("voiceActionIcon", "volume")
            reset_button.setProperty("voiceActionIcon", "restore")
            upload_button.setToolTip("上传音频")
            preview_button.setToolTip("试听")
            reset_button.setToolTip("恢复默认")
            upload_button.setAccessibleName("上传音频")
            preview_button.setAccessibleName("试听")
            reset_button.setAccessibleName("恢复默认")
            for button in (upload_button, preview_button, reset_button):
                button.setFixedSize(30, 30)
                button.setCursor(Qt.PointingHandCursor)
            upload_button.clicked.connect(lambda _checked=False, key=event_key: self._upload_voice_file(key))
            preview_button.clicked.connect(lambda _checked=False, key=event_key: self._preview_voice_event(key))
            reset_button.clicked.connect(lambda _checked=False, key=event_key: self._reset_voice_event(key))
            self.voice_row_buttons[event_key] = (upload_button, preview_button, reset_button)

            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 0, 0, 0)
            button_row.setSpacing(8)
            button_row.addWidget(upload_button)
            button_row.addWidget(preview_button)
            button_row.addWidget(reset_button)
            button_widget = QWidget()
            button_widget.setObjectName("voiceRecordActions")
            button_widget.setLayout(button_row)
            button_widget.setMinimumHeight(36)

            row_layout.addWidget(scene_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
            row_layout.addWidget(file_label, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
            row_layout.addWidget(button_widget, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)

            if item_index < len(VOICE_SETTINGS_EVENTS):
                separator = QFrame()
                separator.setObjectName("voiceRecordSeparator")
                row_layout.addWidget(separator, 1, 0, 1, 3)

            grid.addWidget(row_frame, item_index, 0, 1, 3)

        grid.setColumnStretch(0, 22)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 114)
        custom_layout.addWidget(table_widget)
        self.voice_config_stack.addWidget(self.custom_voice_panel)
        layout.addWidget(self.voice_config_stack)
        layout.addStretch(1)

        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 8, 0, 8)
        action_layout.addStretch(1)
        self.voice_action_button = QPushButton("保存设置")
        self.voice_action_button.setObjectName("primaryButton")
        self.voice_action_button.setMinimumWidth(150)
        self.voice_action_button.clicked.connect(self._on_voice_action_clicked)
        action_layout.addWidget(self.voice_action_button)
        action_widget = QWidget()
        action_widget.setObjectName("settingsVoiceActionBar")
        action_widget.setFixedHeight(60)
        action_widget.setLayout(action_layout)
        root_layout.addWidget(action_widget)
        self._refresh_voice_action_icons()
        return widget

    def _refresh_voice_action_icons(self, *_args) -> None:
        for button in self.findChildren(QToolButton):
            icon_name = str(button.property("settingsActionIcon") or button.property("voiceActionIcon") or "")
            if not icon_name:
                continue
            button.setIcon(themed_svg_icon(icon_name, self.theme_manager))
            button.setIconSize(QSize(17, 17))

    def _build_netdisk_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        self.netdisk_enabled_check = QCheckBox("开启网盘同步")
        self.netdisk_enabled_check.setObjectName("settingsMainCheckBox")
        self.netdisk_enabled_check.toggled.connect(self._sync_netdisk_ui)
        enabled_row = QHBoxLayout()
        enabled_row.setContentsMargins(0, 0, 0, 0)
        enabled_row.addWidget(self.netdisk_enabled_check, 0, Qt.AlignLeft | Qt.AlignVCenter)
        enabled_row.addStretch(1)
        enabled_row.addWidget(QLabel("授权状态："))
        self.netdisk_auth_status_summary_label = QLabel("未授权")
        self.netdisk_auth_status_summary_label.setObjectName("authStatusTag")
        enabled_row.addWidget(self.netdisk_auth_status_summary_label)
        layout.addLayout(enabled_row)

        self.netdisk_config_stack = QStackedWidget()
        self.netdisk_config_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.netdisk_blank_panel = QWidget()
        self.netdisk_config_stack.addWidget(self.netdisk_blank_panel)

        self.netdisk_panel = QWidget()
        self.netdisk_panel.setObjectName("netdiskPanel")
        panel_layout = QVBoxLayout(self.netdisk_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(14)

        netdisk_card, netdisk_card_layout = self._settings_card("百度网盘配置")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.netdisk_client_id_input = QLineEdit()
        self.netdisk_client_id_input.setPlaceholderText("请输入百度网盘 App Key / Client ID")
        self.netdisk_client_id_input.setMaximumWidth(640)
        self._set_compact_control(self.netdisk_client_id_input)
        form.addRow("App Key：", self.netdisk_client_id_input)

        self.netdisk_client_secret_input = QLineEdit()
        self.netdisk_client_secret_input.setPlaceholderText("请输入百度网盘 Secret Key / Client Secret")
        self.netdisk_client_secret_input.setEchoMode(QLineEdit.Password)
        self.netdisk_client_secret_input.setMaximumWidth(640)
        self._set_compact_control(self.netdisk_client_secret_input)
        form.addRow("Secret Key：", self.netdisk_client_secret_input)

        self.netdisk_remote_root_input = QLineEdit()
        self.netdisk_remote_root_input.setPlaceholderText("/电商溯源/videos/")
        self.netdisk_remote_root_input.setMaximumWidth(640)
        self._set_compact_control(self.netdisk_remote_root_input)
        form.addRow("远程上传根目录：", self.netdisk_remote_root_input)

        auth_row = QHBoxLayout()
        auth_row.setContentsMargins(0, 0, 0, 0)
        auth_row.setSpacing(8)
        self.netdisk_auth_status_label = QLabel("未授权")
        self.netdisk_auth_status_label.setObjectName("authStatusLabel")
        self.netdisk_auth_button = QToolButton()
        self.netdisk_auth_button.setObjectName("netdiskAuthIconButton")
        self.netdisk_auth_button.setProperty("settingsActionIcon", "refresh")
        self.netdisk_auth_button.setToolTip("重新授权")
        self.netdisk_auth_button.setAccessibleName("重新授权")
        self.netdisk_auth_button.setFixedSize(30, 30)
        self.netdisk_auth_button.setCursor(Qt.PointingHandCursor)
        self.netdisk_auth_button.clicked.connect(self._authorize_netdisk)
        self.netdisk_test_button = QToolButton()
        self.netdisk_test_button.setObjectName("netdiskTestIconButton")
        self.netdisk_test_button.setProperty("settingsActionIcon", "link")
        self.netdisk_test_button.setToolTip("测试连接")
        self.netdisk_test_button.setAccessibleName("测试连接")
        self.netdisk_test_button.setFixedSize(30, 30)
        self.netdisk_test_button.setCursor(Qt.PointingHandCursor)
        self.netdisk_test_button.clicked.connect(self._test_netdisk_connection)
        auth_row.addWidget(self.netdisk_auth_status_label)
        auth_row.addSpacing(18)
        auth_row.addWidget(self.netdisk_auth_button)
        auth_row.addSpacing(10)
        auth_row.addWidget(self.netdisk_test_button)
        auth_row.addStretch(1)
        auth_widget = QWidget()
        auth_widget.setObjectName("transparentSettingsRow")
        auth_widget.setLayout(auth_row)
        form.addRow("授权状态：", auth_widget)
        self._refresh_voice_action_icons()

        self.netdisk_debug_check = QCheckBox("启用调试日志")
        self.netdisk_debug_check.setObjectName("settingsInlineCheckBox")
        self.netdisk_debug_check.setToolTip("仅排查上传问题时开启；不会记录 token、refresh_token 或 Secret Key。")
        form.addRow("调试日志：", self.netdisk_debug_check)

        netdisk_card_layout.addLayout(form)
        hint = QLabel("提示：access_token 和 refresh_token 仅保存在本机配置文件中，不会显示在界面和日志里。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        netdisk_card_layout.addWidget(hint)
        panel_layout.addWidget(netdisk_card)

        auto_sync_frame, auto_sync_layout = self._settings_card("自动同步")

        self.auto_sync_enabled_check = QCheckBox("开启自动同步")
        self.auto_sync_enabled_check.setObjectName("settingsInlineCheckBox")
        self.auto_sync_enabled_check.toggled.connect(self._sync_netdisk_ui)
        auto_title_row = QHBoxLayout()
        auto_title_row.setContentsMargins(0, 0, 0, 0)
        auto_title_row.addWidget(self.auto_sync_enabled_check)
        auto_title_row.addStretch(1)
        auto_sync_layout.addLayout(auto_title_row)

        self.auto_sync_fields_widget = QWidget()
        self.auto_sync_fields_widget.setObjectName("transparentSettingsRow")
        auto_sync_fields = QHBoxLayout(self.auto_sync_fields_widget)
        auto_sync_fields.setContentsMargins(0, 0, 0, 0)
        auto_sync_fields.setSpacing(12)
        self.auto_sync_trigger_combo = QComboBox()
        self.auto_sync_trigger_combo.addItem("最后一次录制结束后", "after_last_recording")
        self._set_compact_control(self.auto_sync_trigger_combo, 240)
        auto_sync_fields.addWidget(QLabel("触发时机："))
        auto_sync_fields.addWidget(self.auto_sync_trigger_combo)

        self.auto_sync_delay_combo = QComboBox()
        for minutes in AUTO_SYNC_DELAY_OPTIONS:
            self.auto_sync_delay_combo.addItem(f"{minutes}分钟", minutes)
        self._set_compact_control(self.auto_sync_delay_combo, 120)
        auto_sync_fields.addWidget(QLabel("延迟时间："))
        auto_sync_fields.addWidget(self.auto_sync_delay_combo)
        auto_sync_fields.addStretch(1)
        auto_sync_layout.addWidget(self.auto_sync_fields_widget)

        auto_sync_hint = QLabel("录制结束并持续空闲指定时间后，自动上传符合条件的未上传视频；上传失败记录仍需在同步记录中手动重试。")
        auto_sync_hint.setObjectName("settingsHint")
        auto_sync_hint.setWordWrap(True)
        auto_sync_layout.addWidget(auto_sync_hint)
        panel_layout.addWidget(auto_sync_frame)
        panel_layout.addStretch(1)
        self.netdisk_config_stack.addWidget(self.netdisk_panel)
        layout.addWidget(self.netdisk_config_stack)

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 8, 0, 0)
        action_layout.addStretch(1)
        self.netdisk_save_button = QPushButton("保存设置")
        self.netdisk_save_button.setObjectName("primaryButton")
        self.netdisk_save_button.setMinimumWidth(150)
        self.netdisk_save_button.clicked.connect(self._save_netdisk_settings)
        action_layout.addWidget(self.netdisk_save_button)
        action_widget = QWidget()
        action_widget.setObjectName("settingsNetdiskActionBar")
        action_widget.setFixedHeight(60)
        action_widget.setLayout(action_layout)
        layout.addWidget(action_widget)
        return widget

    def _export_config(self) -> None:
        default_name = f"PMSystem_Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "导出配置",
            str(Path.home() / default_name),
            "ZIP 配置包 (*.zip)",
        )
        if not selected:
            return
        export_path = Path(selected)
        if export_path.suffix.lower() != ".zip":
            export_path = export_path.with_suffix(".zip")

        try:
            result = self.config_manager.export_config(export_path)
            voice_count = len(result.get("voice_files", {}) or {})
            warnings = result.get("warnings", []) or []
            self.logger.info(
                "配置导出成功：path=%s, voice_files=%s, excluded=%s, warnings=%s",
                result.get("path"),
                voice_count,
                result.get("excluded_sensitive_fields"),
                len(warnings),
            )
            detail = f"配置已导出：{result.get('path')}\n出于安全考虑，已排除网盘 Secret 和授权 Token，导入后需要重新授权。"
            if voice_count:
                detail += f"\n已打包自定义语音文件 {voice_count} 个。"
            if warnings:
                detail += "\n部分语音文件未导出，请查看日志。"
            self._set_status("配置已导出", "success")
        except Exception as exc:
            self.logger.exception("配置导出失败：path=%s", export_path)
            self._set_status(f"配置导出失败：{exc}", "error")

    def _import_config(self) -> None:
        if self.is_recording_callback():
            self._set_status("录制中不能导入配置，请结束录制后再导入。", "warning")
            return

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "导入配置",
            "",
            "配置文件 (*.zip *.json);;ZIP 配置包 (*.zip);;旧版 JSON 配置 (*.json)",
        )
        if not selected:
            return

        if not confirm_action(
            self,
            title="导入配置",
            heading="导入配置将覆盖当前部分设置，是否继续？",
            description="导入前会自动备份当前 config.json。网盘授权 Token 和 Secret 不会导入，导入后需要重新授权。",
            sections=(("将覆盖：", ("当前可导入配置项",)), ("不会导入：", ("网盘授权 Token", "App Secret"))),
            confirm_text="继续导入",
            destructive=True,
        ):
            return

        import_path = Path(selected)
        try:
            result = self.config_manager.import_config(import_path)
            self.voice_prompt.update_config(self.config_manager.config)
            if self.theme_manager is not None:
                self.theme_manager.apply_configured_theme()
                self._theme_preview_saved = True
            self._load_basic_config_to_ui()
            self._load_voice_config_to_ui()
            self._load_netdisk_config_to_ui()
            self.config_saved.emit(self.config_manager.config)
            self.basic_config_saved.emit(self.config_manager.config)
            warnings = result.get("warnings", []) or []
            self.logger.info(
                "配置导入成功：path=%s, config_version=%s, keys=%s, backup=%s, voice_files=%s, warnings=%s",
                import_path,
                result.get("config_version"),
                result.get("imported_keys"),
                result.get("backup_path"),
                len(result.get("voice_files", {}) or {}),
                len(warnings),
            )
            detail = f"已备份原配置：{result.get('backup_path')}"
            if result.get("requires_netdisk_reauth"):
                detail += "\n网盘授权信息未导入，请重新授权。"
            if result.get("legacy_json"):
                detail += "\n已导入旧版 JSON 配置，建议后续使用新版 zip 格式导出配置。"
            if warnings:
                detail += "\n部分自定义语音文件未恢复，请查看日志。"
            self._set_status("配置已导入", "success")
        except Exception as exc:
            self.logger.exception("配置导入失败：path=%s", import_path)
            self._set_status(f"配置导入失败：{exc}", "error")

    def refresh_state(self, is_recording: bool | None = None) -> None:
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
        self._load_netdisk_config_to_ui()
        self._set_basic_config_enabled(not bool(is_recording if is_recording is not None else self.is_recording_callback()))

    def _load_basic_config_to_ui(self) -> None:
        self._load_appearance_config_to_ui()
        selected_index = int(self.config_manager.config.get("camera_index", 0) or 0)
        self._refresh_camera_options(selected_index)
        video_dir_text = str(self.config_manager.get_video_dir())
        self.video_root_dir_input.setText(video_dir_text)
        self.video_root_dir_input.setToolTip(video_dir_text)
        self.video_root_dir_input.setCursorPosition(0)
        self._select_combo_data(self.resolution_combo, str(self.config_manager.config.get("resolution", "original")), "original")
        fps, _fps_valid = self._coerce_fps(self.config_manager.config.get("fps", DEFAULT_FPS))
        max_long_edge, _edge_valid = self._coerce_long_edge(
            self.config_manager.config.get("recording_max_long_edge", DEFAULT_LONG_EDGE)
        )
        self._select_combo_data(self.fps_combo, fps, DEFAULT_FPS)
        self._select_combo_data(self.recording_long_edge_combo, max_long_edge, DEFAULT_LONG_EDGE)
        self.font_size_spin.setValue(int(self.config_manager.config.get("watermark_font_size", 28) or 28))
        self.margin_spin.setValue(int(self.config_manager.config.get("watermark_margin", 16) or 16))
        hash_config = self.config_manager.config.get("hash_check", {})
        if not isinstance(hash_config, dict):
            hash_config = {}
        self.hash_check_enabled.setChecked(bool(hash_config.get("enabled", True)))
        self._select_combo_data(self.hash_algorithm_combo, str(hash_config.get("algorithm") or "SHA256").upper(), "SHA256")

    def _load_appearance_config_to_ui(self) -> None:
        if not hasattr(self, "theme_mode_buttons"):
            return
        raw = self.config_manager.config.get("appearance", {})
        mode = str(raw.get("theme") if isinstance(raw, dict) else "system").strip().lower()
        if mode not in self.theme_mode_buttons:
            mode = "system"
        for button_mode, button in self.theme_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(button_mode == mode)
            button.blockSignals(False)

    def _queue_theme_preview(self, mode: str) -> None:
        if self.theme_manager is None:
            return
        if mode not in self.theme_mode_buttons or not self.theme_mode_buttons[mode].isChecked():
            return
        self._theme_preview_saved = False
        self._theme_preview_request_id += 1
        request_id = self._theme_preview_request_id
        QTimer.singleShot(0, lambda: self._preview_theme_mode(mode, request_id))

    def _preview_theme_mode(self, mode: str, request_id: int) -> None:
        if self.theme_manager is None or request_id != self._theme_preview_request_id:
            return
        if self._selected_theme_mode() != mode:
            return
        self.theme_manager.preview_theme(mode)

    def _set_basic_config_enabled(self, enabled: bool) -> None:
        for widget in (
            *getattr(self, "theme_mode_buttons", {}).values(),
            self.camera_combo,
            self.video_root_dir_input,
            self.video_root_dir_choose_button,
            self.video_root_dir_open_button,
            getattr(self, "camera_refresh_button", self.camera_combo),
            self.resolution_combo,
            self.fps_combo,
            self.recording_long_edge_combo,
            self.font_size_spin,
            self.margin_spin,
            self.hash_check_enabled,
            self.hash_algorithm_combo,
            getattr(self, "restore_recommended_button", self.apply_basic_config_button),
            self.apply_basic_config_button,
        ):
            widget.setEnabled(enabled)

    def _restore_recommended_defaults(self) -> None:
        message = (
            "将恢复以下推荐参数：\n"
            "分辨率：原始分辨率\n"
            "帧率：30 FPS\n"
            "录制长边上限：1280\n"
            "水印字号：28\n"
            "水印边距：16\n"
            "视频哈希校验：开启\n"
            "哈希算法：SHA256\n\n"
            "不会修改摄像头设备、视频存储目录、网盘授权、自定义语音包等设备或账号相关配置。\n"
            "恢复后需要点击“保存并应用配置”才会生效。"
        )
        if not confirm_action(
            self,
            title="恢复推荐参数",
            heading="确定恢复基础配置的推荐参数吗？",
            description="恢复后仍需点击“保存并应用配置”才会正式生效。",
            sections=(("不会修改：", ("摄像头设备", "视频存储目录", "网盘授权", "自定义语音包")),),
            confirm_text="恢复推荐参数",
            destructive=True,
        ):
            return
        self._select_combo_data(self.resolution_combo, "original", "original")
        self._select_combo_data(self.fps_combo, 30, DEFAULT_FPS)
        self._select_combo_data(self.recording_long_edge_combo, 1280, DEFAULT_LONG_EDGE)
        self.font_size_spin.setValue(28)
        self.margin_spin.setValue(16)
        self.hash_check_enabled.setChecked(True)
        self._select_combo_data(self.hash_algorithm_combo, "SHA256", "SHA256")
        self._set_status("已恢复推荐参数，保存后生效", "info")

    def _save_basic_config(self) -> None:
        if self.is_recording_callback():
            self.logger.info("录制中尝试修改基础配置")
            self._set_status("录制中不能修改基础配置，请结束录制后再修改。", "warning")
            self._set_basic_config_enabled(False)
            return

        try:
            current_video_dir = self.config_manager.get_video_dir()
            raw_video_dir = self.video_root_dir_input.text().strip()
            candidate_video_dir = self.config_manager.resolve_path(raw_video_dir or "videos").resolve()
            if candidate_video_dir != current_video_dir and self.is_syncing_callback():
                self._set_status("当前正在同步网盘，请先停止同步后再修改视频存储目录。", "warning")
                self.video_root_dir_input.setText(str(current_video_dir))
                return
            video_root_dir = self.config_manager.ensure_video_root_dir_writable(raw_video_dir or "videos")
            values = {
                "appearance": {
                    "theme": self._selected_theme_mode(),
                },
                "video_root_dir": str(video_root_dir),
                "camera_index": int(self.camera_combo.currentData() or 0),
                "camera_name": self._selected_camera_name(),
                "resolution": self.resolution_combo.currentData(),
                "fps": int(self.fps_combo.currentData() or DEFAULT_FPS),
                "recording_max_long_edge": int(self.recording_long_edge_combo.currentData() or 0),
                "watermark_font_size": self.font_size_spin.value(),
                "watermark_margin": self.margin_spin.value(),
                "hash_check": {
                    "enabled": self.hash_check_enabled.isChecked(),
                    "algorithm": str(self.hash_algorithm_combo.currentData() or "SHA256").upper(),
                    "auto_generate_after_recording": True,
                },
            }
            updated_config = self.config_manager.update(values)
            if self.theme_manager is not None:
                self.theme_manager.commit_theme(self._selected_theme_mode())
            self._theme_preview_saved = True
            self.basic_config_saved.emit(updated_config)
            self.video_root_dir_input.setText(str(self.config_manager.get_video_dir()))
            self.logger.info("基础配置保存成功：video_root_dir=%s", self.config_manager.get_video_dir())
            if video_root_dir != current_video_dir:
                self._set_status("视频存储目录已更新", "success")
            else:
                self._set_status("基础配置已保存并应用", "success")
        except Exception as exc:
            self.logger.exception("基础配置保存失败")
            self._set_status(f"基础配置保存失败：{exc}", "error")

    def _selected_theme_mode(self) -> str:
        for mode, button in getattr(self, "theme_mode_buttons", {}).items():
            if button.isChecked():
                return mode
        return "system"

    def _choose_video_root_dir(self) -> None:
        if self.is_recording_callback():
            self._set_status("当前正在录制，请结束录制后再修改视频存储目录。", "warning")
            return
        current_dir = str(self.config_manager.get_video_dir())
        selected = QFileDialog.getExistingDirectory(self, "选择视频存储目录", current_dir)
        if selected:
            self.video_root_dir_input.setText(str(Path(selected).resolve()))
            self.video_root_dir_input.setCursorPosition(0)

    def _open_video_root_dir(self) -> None:
        try:
            video_dir = self.config_manager.ensure_video_root_dir_writable(self.video_root_dir_input.text().strip() or "videos")
            open_folder(video_dir)
        except Exception as exc:
            self.logger.exception("打开视频存储目录失败")
            self._set_status(f"打开视频存储目录失败：{exc}", "error")

    def _load_voice_config_to_ui(self) -> None:
        voice_config = self._current_voice_config()
        self.voice_enabled_check.blockSignals(True)
        self.system_voice_radio.blockSignals(True)
        self.custom_voice_radio.blockSignals(True)

        enabled = bool(voice_config.get("enabled", True))
        mode = str(voice_config.get("mode", "system") or "system")
        if mode == "off":
            enabled = False
            mode = "system"
        self.voice_enabled_check.setChecked(enabled)
        if mode == "custom":
            self.custom_voice_radio.setChecked(True)
        else:
            self.system_voice_radio.setChecked(True)

        system_text = voice_config.get("system_text", {})
        system_text = system_text if isinstance(system_text, dict) else {}
        for event_key, edit in self.system_text_edits.items():
            edit.setText(str(system_text.get(event_key, DEFAULT_SYSTEM_TEXT.get(event_key, "")) or ""))

        self.voice_enabled_check.blockSignals(False)
        self.system_voice_radio.blockSignals(False)
        self.custom_voice_radio.blockSignals(False)

        self._refresh_voice_file_labels(voice_config)
        self._sync_voice_mode_ui()

    def _current_voice_config(self) -> dict[str, object]:
        return VoicePrompt.normalize_config({"voice_prompt": self.config_manager.config.get("voice_prompt", {})})

    def _voice_config_from_ui(self) -> dict[str, object]:
        current = self._current_voice_config()
        mode = self._selected_voice_mode()
        enabled = self.voice_enabled_check.isChecked()
        system_text = dict(current.get("system_text", DEFAULT_SYSTEM_TEXT))
        for event_key, edit in self.system_text_edits.items():
            value = edit.text().strip()
            system_text[event_key] = value if value else DEFAULT_SYSTEM_TEXT.get(event_key, "")
        return {
            "enabled": enabled,
            "mode": mode,
            "custom_voice_dir": str(current.get("custom_voice_dir") or DEFAULT_VOICE_PROMPT_CONFIG["custom_voice_dir"]),
            "custom_files": dict(current.get("custom_files", {})),
            "system_text": system_text,
        }

    def _selected_voice_mode(self) -> str:
        for radio in (self.system_voice_radio, self.custom_voice_radio):
            if radio.isChecked():
                return str(radio.property("voice_mode") or "system")
        return "system"

    def _sync_voice_mode_ui(self, *_args) -> None:
        enabled = self.voice_enabled_check.isChecked()
        for radio in (self.system_voice_radio, self.custom_voice_radio):
            radio.setEnabled(enabled)
        self.voice_mode_stack.setCurrentWidget(self.voice_mode_panel if enabled else self.voice_mode_blank)
        if not enabled:
            self.voice_config_stack.setCurrentWidget(self.voice_config_blank)
        elif self.custom_voice_radio.isChecked():
            self.voice_config_stack.setCurrentWidget(self.custom_voice_panel)
        else:
            self.voice_config_stack.setCurrentWidget(self.system_voice_panel)
        self.voice_action_button.setText("保存并测试语音" if enabled and self.system_voice_radio.isChecked() else "保存设置")

    def _refresh_voice_file_labels(self, voice_config: dict[str, object] | None = None) -> None:
        voice_config = voice_config or self._current_voice_config()
        custom_files = voice_config.get("custom_files", {})
        custom_files = custom_files if isinstance(custom_files, dict) else {}
        for event_key, label in self.voice_file_labels.items():
            path_text = str(custom_files.get(event_key, "") or "")
            if path_text:
                path = Path(path_text)
                label.setText(path.name)
                label.setToolTip(str(path))
            else:
                label.setText("未设置")
                label.setToolTip("")

    def _upload_voice_file(self, event_key: str) -> None:
        file_filter = "音频文件 (*.wav *.mp3 *.m4a *.aac)"
        selected, _ = QFileDialog.getOpenFileName(self, "选择自定义语音文件", "", file_filter)
        if not selected:
            return
        source = Path(selected)
        if not source.exists():
            self._set_status("音频文件不存在", "warning")
            return
        if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            self._set_status("音频格式不支持，请选择 wav、mp3、m4a 或 aac。", "warning")
            return

        try:
            voice_config = self._current_voice_config()
            voice_dir = Path(str(voice_config.get("custom_voice_dir") or DEFAULT_VOICE_PROMPT_CONFIG["custom_voice_dir"]))
            voice_dir.mkdir(parents=True, exist_ok=True)
            target = voice_dir / f"{event_key}{source.suffix.lower()}"
            shutil.copy2(source, target)
            custom_files = dict(voice_config.get("custom_files", {}))
            custom_files[event_key] = str(target)
            voice_config["custom_files"] = custom_files
            updated_config = self._save_voice_config(voice_config)
            self._refresh_voice_file_labels(VoicePrompt.normalize_config({"voice_prompt": updated_config["voice_prompt"]}))
            self.logger.info("自定义语音已更新：event=%s, file=%s", event_key, target)
            self._set_status("自定义语音已更新", "success")
        except Exception as exc:
            self.logger.exception("自定义语音上传失败：event=%s", event_key)
            self._set_status(f"上传失败：{exc}", "error")

    def _preview_voice_event(self, event_key: str) -> None:
        voice_config = self._voice_config_from_ui()
        mode = str(voice_config.get("mode", "system") or "system")
        if not bool(voice_config.get("enabled", True)):
            self._set_status("当前语音提示已关闭", "warning")
            return

        custom_files = voice_config.get("custom_files", {})
        custom_files = custom_files if isinstance(custom_files, dict) else {}
        path_text = str(custom_files.get(event_key, "") or "")
        if path_text and Path(path_text).exists():
            if self.voice_prompt.play_audio_file(path_text, event_key=event_key):
                self._set_status("正在试听自定义语音", "success")
            else:
                self._set_status("试听失败，请查看日志。", "error")
            return

        system_text = voice_config.get("system_text", {})
        system_text = system_text if isinstance(system_text, dict) else {}
        text = str(system_text.get(event_key, DEFAULT_SYSTEM_TEXT.get(event_key, "")) or "")
        if self.voice_prompt.speak(text, event_key=event_key, respect_mode=False):
            message = "正在播放系统默认语音" if mode == "system" else "未设置自定义音频，正在播放系统语音"
            self._set_status(message, "success")
        else:
            self._set_status("试听失败，请查看日志。", "error")

    def _reset_voice_event(self, event_key: str) -> None:
        if not confirm_action(
            self,
            title="恢复默认语音",
            heading="确定恢复这个提示场景的默认语音吗？",
            description="当前自定义音频关联将被移除，其他语音场景不受影响。",
            confirm_text="恢复默认",
            destructive=True,
        ):
            return
        try:
            voice_config = self._current_voice_config()
            custom_files = dict(voice_config.get("custom_files", {}))
            custom_files[event_key] = ""
            voice_config["custom_files"] = custom_files
            updated_config = self._save_voice_config(voice_config)
            self._refresh_voice_file_labels(VoicePrompt.normalize_config({"voice_prompt": updated_config["voice_prompt"]}))
            self.logger.info("自定义语音恢复默认：event=%s", event_key)
            self._set_status("已恢复默认语音", "success")
        except Exception as exc:
            self.logger.exception("恢复默认语音失败：event=%s", event_key)
            self._set_status(f"恢复默认失败：{exc}", "error")

    def _save_voice_config(self, voice_config: dict[str, object]) -> dict:
        normalized = VoicePrompt.normalize_config({"voice_prompt": voice_config})
        updated_config = self.config_manager.update({"voice_prompt": normalized})
        self.voice_prompt.update_config(updated_config)
        self.config_saved.emit(updated_config)
        self.logger.info("语音配置保存成功：enabled=%s, mode=%s", normalized.get("enabled"), normalized.get("mode"))
        return updated_config

    def _on_voice_action_clicked(self) -> None:
        if self.voice_enabled_check.isChecked() and self.system_voice_radio.isChecked():
            self._save_and_test_voice()
        else:
            self._save_voice_settings()

    def _save_voice_settings(self) -> None:
        try:
            self._save_voice_config(self._voice_config_from_ui())
            self._set_status("语音提示设置已保存", "success")
        except Exception as exc:
            self.logger.exception("语音配置保存失败")
            self._set_status(f"语音配置保存失败：{exc}", "error")

    def _save_and_test_voice(self) -> None:
        try:
            voice_config = self._voice_config_from_ui()
            updated_config = self._save_voice_config(voice_config)
            normalized = VoicePrompt.normalize_config({"voice_prompt": updated_config["voice_prompt"]})
            mode = str(normalized.get("mode", "system"))

            if not bool(normalized.get("enabled", True)):
                self._set_status("当前语音提示已关闭", "warning")
                self.logger.info("语音提示已关闭，测试语音未播放")
                return

            if mode == "custom":
                if self.voice_prompt.play("start"):
                    self._set_status("正在播放测试语音", "success")
                else:
                    self._set_status("测试语音播放失败，请查看日志。", "error")
                return

            if self.voice_prompt.speak("这是一条测试语音", event_key="test", respect_mode=False):
                self._set_status("正在播放测试语音", "success")
            elif self.voice_prompt.backend_name() == "none":
                self._set_status("语音引擎不可用，请检查系统语音服务或依赖安装。", "error")
            else:
                self._set_status("测试语音播放失败，请查看日志。", "error")
        except Exception as exc:
            self.logger.exception("语音配置保存失败")
            self._set_status(f"语音配置保存失败：{exc}", "error")

    def _load_netdisk_config_to_ui(self) -> None:
        netdisk_config = self._current_netdisk_config()
        cloud_sync_config = self._current_cloud_sync_config()
        self.netdisk_enabled_check.blockSignals(True)
        self.netdisk_enabled_check.setChecked(bool(netdisk_config.get("enabled", False)))
        self.netdisk_enabled_check.blockSignals(False)

        self.netdisk_client_id_input.setText(str(netdisk_config.get("client_id") or ""))
        self.netdisk_client_secret_input.setText(str(netdisk_config.get("client_secret") or ""))
        self.netdisk_remote_root_input.setText(str(netdisk_config.get("remote_root") or "/电商溯源/videos/"))
        self.netdisk_debug_check.setChecked(bool(netdisk_config.get("debug", False)))
        self.auto_sync_enabled_check.blockSignals(True)
        self.auto_sync_enabled_check.setChecked(bool(cloud_sync_config.get("auto_sync_enabled", False)))
        self.auto_sync_enabled_check.blockSignals(False)
        self._select_combo_data(
            self.auto_sync_trigger_combo,
            str(cloud_sync_config.get("auto_sync_trigger") or "after_last_recording"),
            "after_last_recording",
        )
        self._select_combo_data(
            self.auto_sync_delay_combo,
            int(cloud_sync_config.get("auto_sync_delay_minutes") or 10),
            10,
        )
        self._refresh_netdisk_auth_status(netdisk_config)
        self._sync_netdisk_ui()

    def _current_netdisk_config(self) -> dict[str, object]:
        return normalize_netdisk_config(self.config_manager.config.get("netdisk_sync", {}))

    def _current_cloud_sync_config(self) -> dict[str, object]:
        return normalize_cloud_sync_config(self.config_manager.config.get("cloud_sync", {}))

    def _netdisk_config_from_ui(self) -> dict[str, object]:
        current = self._current_netdisk_config()
        return {
            "enabled": self.netdisk_enabled_check.isChecked(),
            "provider": "baidu",
            "remote_root": normalize_remote_root(self.netdisk_remote_root_input.text().strip()),
            "client_id": self.netdisk_client_id_input.text().strip(),
            "client_secret": self.netdisk_client_secret_input.text().strip(),
            "access_token": str(current.get("access_token") or ""),
            "refresh_token": str(current.get("refresh_token") or ""),
            "token_expires_at": str(current.get("token_expires_at") or ""),
            "last_auth_time": str(current.get("last_auth_time") or ""),
            "debug": self.netdisk_debug_check.isChecked(),
        }

    def _cloud_sync_config_from_ui(self) -> dict[str, object]:
        return normalize_cloud_sync_config(
            {
                "auto_sync_enabled": self.auto_sync_enabled_check.isChecked(),
                "auto_sync_trigger": str(self.auto_sync_trigger_combo.currentData() or "after_last_recording"),
                "auto_sync_delay_minutes": int(self.auto_sync_delay_combo.currentData() or 10),
            }
        )

    def _sync_netdisk_ui(self, *_args) -> None:
        enabled = self.netdisk_enabled_check.isChecked()
        auto_enabled = enabled and self.auto_sync_enabled_check.isChecked()
        self.netdisk_config_stack.setCurrentWidget(self.netdisk_panel if enabled else self.netdisk_blank_panel)
        for widget in (
            self.netdisk_client_id_input,
            self.netdisk_client_secret_input,
            self.netdisk_remote_root_input,
            self.netdisk_debug_check,
            self.netdisk_auth_button,
            self.netdisk_test_button,
            self.auto_sync_enabled_check,
        ):
            widget.setEnabled(enabled)
        for widget in (self.auto_sync_trigger_combo, self.auto_sync_delay_combo):
            widget.setEnabled(auto_enabled)
        if hasattr(self, "auto_sync_fields_widget"):
            self.auto_sync_fields_widget.setVisible(auto_enabled)

    def _refresh_netdisk_auth_status(self, netdisk_config: dict[str, object] | None = None) -> None:
        netdisk_config = netdisk_config or self._current_netdisk_config()
        if netdisk_config.get("access_token") or netdisk_config.get("refresh_token"):
            self.netdisk_auth_status_label.setText("已授权")
            self.netdisk_auth_status_label.setProperty("status", "ok")
            self.netdisk_auth_status_label.style().unpolish(self.netdisk_auth_status_label)
            self.netdisk_auth_status_label.style().polish(self.netdisk_auth_status_label)
            if hasattr(self, "netdisk_auth_status_summary_label"):
                self.netdisk_auth_status_summary_label.setText("已授权")
                self.netdisk_auth_status_summary_label.setProperty("status", "ok")
                self.netdisk_auth_status_summary_label.style().unpolish(self.netdisk_auth_status_summary_label)
                self.netdisk_auth_status_summary_label.style().polish(self.netdisk_auth_status_summary_label)
            self.netdisk_auth_button.setToolTip("重新授权")
            self.netdisk_auth_button.setAccessibleName("重新授权")
        else:
            self.netdisk_auth_status_label.setText("未授权")
            self.netdisk_auth_status_label.setProperty("status", "none")
            self.netdisk_auth_status_label.style().unpolish(self.netdisk_auth_status_label)
            self.netdisk_auth_status_label.style().polish(self.netdisk_auth_status_label)
            if hasattr(self, "netdisk_auth_status_summary_label"):
                self.netdisk_auth_status_summary_label.setText("未授权")
                self.netdisk_auth_status_summary_label.setProperty("status", "none")
                self.netdisk_auth_status_summary_label.style().unpolish(self.netdisk_auth_status_summary_label)
                self.netdisk_auth_status_summary_label.style().polish(self.netdisk_auth_status_summary_label)
            self.netdisk_auth_button.setToolTip("重新授权")
            self.netdisk_auth_button.setAccessibleName("重新授权")

    def _save_netdisk_config(self, netdisk_config: dict[str, object], cloud_sync_config: dict[str, object] | None = None) -> dict:
        normalized = normalize_netdisk_config(netdisk_config)
        values: dict[str, object] = {"netdisk_sync": normalized}
        if cloud_sync_config is not None:
            values["cloud_sync"] = normalize_cloud_sync_config(cloud_sync_config)
        updated_config = self.config_manager.update(values)
        self.config_saved.emit(updated_config)
        self.logger.info(
            "网盘同步配置保存成功：enabled=%s, provider=%s, remote_root=%s, has_client_id=%s, has_token=%s, auto_sync=%s, delay=%s",
            normalized.get("enabled"),
            normalized.get("provider"),
            normalized.get("remote_root"),
            bool(normalized.get("client_id")),
            bool(normalized.get("access_token") or normalized.get("refresh_token")),
            bool((cloud_sync_config or self._current_cloud_sync_config()).get("auto_sync_enabled", False)),
            int((cloud_sync_config or self._current_cloud_sync_config()).get("auto_sync_delay_minutes", 10) or 10),
        )
        return updated_config

    def _save_netdisk_settings(self) -> None:
        try:
            netdisk_config = self._netdisk_config_from_ui()
            cloud_sync_config = self._cloud_sync_config_from_ui()
            self._save_netdisk_config(netdisk_config, cloud_sync_config)
            self.netdisk_remote_root_input.setText(str(netdisk_config.get("remote_root") or "/电商溯源/videos/"))
            self._refresh_netdisk_auth_status(netdisk_config)
            self._sync_netdisk_ui()
            self._set_status("网盘同步设置已保存", "success")
        except Exception as exc:
            self.logger.exception("网盘同步配置保存失败")
            self._set_status(f"网盘同步配置保存失败：{exc}", "error")

    def _authorize_netdisk(self) -> None:
        try:
            netdisk_config = self._netdisk_config_from_ui()
            if not netdisk_config.get("client_id") or not netdisk_config.get("client_secret"):
                self._set_status("请先填写百度网盘 App Key 和 Secret Key", "warning")
                return
            self._save_netdisk_config(netdisk_config)
            auth_url = build_authorize_url(str(netdisk_config.get("client_id") or ""))
            webbrowser.open(auth_url)
            code, ok = QInputDialog.getText(
                self,
                "百度网盘授权",
                "浏览器授权完成后，请复制授权码并粘贴到这里：",
            )
            if not ok or not code.strip():
                self.logger.info("用户取消百度网盘授权码输入")
                return
            client = BaiduNetdiskClient(netdisk_config, self.logger)
            tokens = client.exchange_code(code.strip())
            netdisk_config.update(tokens)
            netdisk_config["enabled"] = True
            updated_config = self._save_netdisk_config(netdisk_config)
            self._refresh_netdisk_auth_status(updated_config.get("netdisk_sync", {}))
            self._set_status("百度网盘授权成功", "success")
        except NetdiskError as exc:
            self.logger.exception("百度网盘授权失败")
            self._set_status(f"百度网盘授权失败：{exc}", "error")
        except Exception as exc:
            self.logger.exception("百度网盘授权异常")
            self._set_status(f"百度网盘授权失败：{exc}", "error")

    def _test_netdisk_connection(self) -> None:
        try:
            netdisk_config = self._netdisk_config_from_ui()
            if not netdisk_config.get("client_id") or not netdisk_config.get("client_secret"):
                self._set_status("请先填写百度网盘 App Key 和 Secret Key", "warning")
                return
            if not (netdisk_config.get("access_token") or netdisk_config.get("refresh_token")):
                self._set_status("请先完成百度网盘授权", "warning")
                return
            client = BaiduNetdiskClient(netdisk_config, self.logger, token_refreshed_callback=self._save_netdisk_tokens)
            client.test_connection()
            self._set_status("百度网盘连接正常", "success")
            self.logger.info("百度网盘测试连接成功")
        except NetdiskError as exc:
            self.logger.exception("百度网盘测试连接失败")
            self._set_status(f"百度网盘连接失败：{exc}", "error")
        except Exception as exc:
            self.logger.exception("百度网盘测试连接异常")
            self._set_status(f"百度网盘连接失败：{exc}", "error")

    def _save_netdisk_tokens(self, tokens: dict[str, object]) -> None:
        netdisk_config = self._current_netdisk_config()
        netdisk_config.update(tokens)
        self._save_netdisk_config(netdisk_config)
        self._refresh_netdisk_auth_status(netdisk_config)

    def _refresh_camera_options(self, selected_index: int | None = None) -> None:
        selected_index = int(selected_index if selected_index is not None else self.config_manager.config.get("camera_index", 0) or 0)
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
        if "（索引" in text:
            return text.split("（索引", 1)[0]
        return text

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
        DialogSizeManager.position_transient(box, self)
        box.exec()

    @staticmethod
    def _header_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("tableHeaderLabel")
        return label

    @staticmethod
    def _select_combo_data(combo: QComboBox, value, fallback) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(index if index >= 0 else 0)

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
            self.logger.warning("检测到非法 max_long_edge 值并回退默认值：%s -> %s", value, DEFAULT_LONG_EDGE)
            return DEFAULT_LONG_EDGE, False
        if max_long_edge not in LONG_EDGE_OPTIONS:
            self.logger.warning("检测到非法 max_long_edge 值并回退默认值：%s -> %s", value, DEFAULT_LONG_EDGE)
            return DEFAULT_LONG_EDGE, False
        return max_long_edge, True

    def _set_status(self, message: str, level: str = "info") -> None:
        show_toast(self, message, level, 2600, self.logger)
