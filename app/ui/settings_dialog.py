from __future__ import annotations

import logging
import shutil
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
from app.core.config_manager import ConfigManager
from app.core.netdisk_sync import (
    BaiduNetdiskClient,
    NetdiskError,
    build_authorize_url,
    normalize_netdisk_config,
    normalize_remote_root,
)
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
from app.ui.toast import show_toast
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logger
        self.voice_prompt = voice_prompt
        self.is_recording_callback = is_recording_callback or (lambda: False)
        self.voice_file_labels: dict[str, QLabel] = {}
        self.voice_row_buttons: dict[str, tuple[QPushButton, QPushButton, QPushButton]] = {}
        self.system_text_edits: dict[str, QLineEdit] = {}

        self.setObjectName("settingsDialog")
        self.setWindowTitle("设置")
        self.resize(780, 620)
        self._build_ui()
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
        self._load_netdisk_config_to_ui()
        self.logger.info("基础配置页签初始化")
        self.logger.info("语音提示页签初始化")
        self.logger.info("网盘同步页签初始化")
        self.logger.info("配置管理页签初始化")
        self.logger.info("更新日志页签初始化")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

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

            version_label = QLabel(str(entry.get("version", "")))
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
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.camera_combo = QComboBox()
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("原始分辨率", "original")
        self.resolution_combo.addItem("720p", "720p")
        self.resolution_combo.addItem("1080p", "1080p")

        self.fps_combo = QComboBox()
        for fps in FPS_OPTIONS:
            self.fps_combo.addItem(f"{fps} FPS", fps)

        self.recording_long_edge_combo = QComboBox()
        self.recording_long_edge_combo.addItem("不限制，使用摄像头原始分辨率", 0)
        for edge in LONG_EDGE_OPTIONS[1:]:
            self.recording_long_edge_combo.addItem(str(edge), edge)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(14, 72)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(4, 80)

        form.addRow(
            self._help_label("摄像头设备：", "摄像头设备说明", CAMERA_HELP_TEXT, "选择用于打包录制的摄像头设备。"),
            self.camera_combo,
        )
        form.addRow(
            self._help_label("分辨率：", "分辨率说明", RESOLUTION_HELP_TEXT, "设置摄像头采集画面的清晰度。"),
            self.resolution_combo,
        )
        form.addRow(
            self._help_label("帧率：", "帧率说明", FPS_HELP_TEXT, "设置每秒录制画面数量，推荐 25 FPS。"),
            self.fps_combo,
        )
        form.addRow(
            self._help_label(
                "录制长边上限：",
                "录制长边上限说明",
                LONG_EDGE_HELP_TEXT,
                "限制录制视频的最大边长，推荐 1280。",
            ),
            self.recording_long_edge_combo,
        )
        form.addRow(
            self._help_label("水印字号：", "水印字号说明", WATERMARK_FONT_HELP_TEXT, "设置视频中单号和时间水印的文字大小。"),
            self.font_size_spin,
        )
        form.addRow(
            self._help_label("水印边距：", "水印边距说明", WATERMARK_MARGIN_HELP_TEXT, "设置水印距离画面边缘的距离。"),
            self.margin_spin,
        )
        layout.addLayout(form)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.apply_basic_config_button = QPushButton("保存并应用配置")
        self.apply_basic_config_button.setObjectName("primaryButton")
        self.apply_basic_config_button.clicked.connect(self._save_basic_config)
        action_layout.addWidget(self.apply_basic_config_button)
        layout.addLayout(action_layout)
        layout.addStretch(1)
        return widget

    def _build_voice_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.voice_enabled_check = QCheckBox("开启语音提示")
        checkmark_path = resource_path("app/assets/checkmark.svg").as_posix()
        self.voice_enabled_check.setStyleSheet(
            """
            QCheckBox {
                color: #1f2937;
                font-size: 14px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                border-color: #0f766e;
                background: #0f766e;
                image: url("%s");
            }
            QCheckBox::indicator:unchecked:hover {
                border-color: #0f766e;
            }
            """
            % checkmark_path
        )
        self.voice_enabled_check.toggled.connect(self._sync_voice_mode_ui)
        voice_enabled_row = QHBoxLayout()
        voice_enabled_row.setContentsMargins(0, 0, 0, 0)
        voice_enabled_row.addStretch(1)
        voice_enabled_row.addWidget(self.voice_enabled_check, 0, Qt.AlignCenter)
        voice_enabled_row.addStretch(1)
        layout.addLayout(voice_enabled_row)

        self.voice_mode_stack = QStackedWidget()
        self.voice_mode_stack.setFixedHeight(30)
        self.voice_mode_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.voice_mode_blank = QWidget()
        self.voice_mode_stack.addWidget(self.voice_mode_blank)
        self.voice_mode_panel = QWidget()
        self.voice_mode_panel.setObjectName("voiceModePanel")
        self.voice_mode_panel.setStyleSheet(
            """
            QRadioButton {
                color: #1f2937;
                font-size: 14px;
                spacing: 8px;
                padding: 2px 0;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #0f766e;
                background: qradialgradient(
                    cx: 0.5, cy: 0.5, radius: 0.5,
                    fx: 0.5, fy: 0.5,
                    stop: 0 #0f766e,
                    stop: 0.42 #0f766e,
                    stop: 0.46 #ffffff,
                    stop: 1 #ffffff
                );
            }
            QRadioButton::indicator:unchecked:hover {
                border-color: #0f766e;
            }
            QRadioButton:disabled {
                color: #94a3b8;
            }
            QRadioButton::indicator:disabled {
                border-color: #cbd5e1;
                background: #f8fafc;
            }
            """
        )
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
        self.voice_config_stack.setFixedHeight(360)
        self.voice_config_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.voice_config_blank = QWidget()
        self.voice_config_stack.addWidget(self.voice_config_blank)

        self.system_voice_panel = QWidget()
        system_layout = QVBoxLayout(self.system_voice_panel)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(8)

        system_header = QLabel("系统默认语音文字配置")
        system_header.setObjectName("sectionTitle")
        system_layout.addWidget(system_header)

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

        self.custom_voice_panel = QWidget()
        self.custom_voice_panel.setObjectName("customVoicePanel")
        self.custom_voice_panel.setStyleSheet(
            """
            QLabel#sectionTitle {
                color: #0f766e;
                font-weight: 700;
            }
            QLabel#tableHeaderLabel {
                color: #475569;
                font-weight: 700;
            }
            QPushButton {
                min-height: 28px;
                padding: 3px 10px;
            }
            QPushButton#voiceUploadButton {
                color: #0f766e;
                border: 1px solid #0f766e;
                background: #ffffff;
                border-radius: 5px;
                font-weight: 600;
            }
            QPushButton#voiceUploadButton:hover {
                background: #ecfdf5;
            }
            QPushButton#voicePreviewButton {
                color: #2563eb;
                border: 1px solid #93c5fd;
                background: #ffffff;
                border-radius: 5px;
                font-weight: 600;
            }
            QPushButton#voicePreviewButton:hover {
                background: #eff6ff;
            }
            QPushButton#voiceResetButton {
                color: #64748b;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                border-radius: 5px;
                font-weight: 600;
            }
            QPushButton#voiceResetButton:hover {
                background: #f8fafc;
            }
            """
        )
        custom_layout = QVBoxLayout(self.custom_voice_panel)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)

        header = QLabel("自定义语音包")
        header.setObjectName("sectionTitle")
        custom_layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        table_widget = QWidget()
        grid = QGridLayout(table_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._header_label("提示场景"), 0, 0)
        grid.addWidget(self._header_label("当前音频文件"), 0, 1)
        grid.addWidget(self._header_label("操作"), 0, 2)

        for row, (event_key, _text_label, audio_label, _file_stem) in enumerate(VOICE_SETTINGS_EVENTS, start=1):
            scene_label = QLabel(audio_label)
            file_label = QLabel("未设置")
            file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.voice_file_labels[event_key] = file_label

            upload_button = QPushButton("上传")
            preview_button = QPushButton("试听")
            reset_button = QPushButton("恢复默认")
            upload_button.setObjectName("voiceUploadButton")
            preview_button.setObjectName("voicePreviewButton")
            reset_button.setObjectName("voiceResetButton")
            upload_button.setFixedWidth(64)
            preview_button.setFixedWidth(64)
            reset_button.setFixedWidth(82)
            upload_button.clicked.connect(lambda _checked=False, key=event_key: self._upload_voice_file(key))
            preview_button.clicked.connect(lambda _checked=False, key=event_key: self._preview_voice_event(key))
            reset_button.clicked.connect(lambda _checked=False, key=event_key: self._reset_voice_event(key))
            self.voice_row_buttons[event_key] = (upload_button, preview_button, reset_button)

            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 0, 0, 0)
            button_row.setSpacing(6)
            button_row.addWidget(upload_button)
            button_row.addWidget(preview_button)
            button_row.addWidget(reset_button)
            button_row.addStretch(1)
            button_widget = QWidget()
            button_widget.setLayout(button_row)

            grid.addWidget(scene_label, row, 0)
            grid.addWidget(file_label, row, 1)
            grid.addWidget(button_widget, row, 2)

        grid.setColumnStretch(1, 1)
        scroll.setWidget(table_widget)
        custom_layout.addWidget(scroll, 1)
        self.voice_config_stack.addWidget(self.custom_voice_panel)
        layout.addWidget(self.voice_config_stack)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.voice_action_button = QPushButton("保存设置")
        self.voice_action_button.setObjectName("primaryButton")
        self.voice_action_button.setMinimumWidth(150)
        self.voice_action_button.clicked.connect(self._on_voice_action_clicked)
        action_layout.addWidget(self.voice_action_button)
        action_layout.addStretch(1)
        layout.addLayout(action_layout)
        return widget

    def _build_netdisk_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.netdisk_enabled_check = QCheckBox("开启网盘同步")
        self.netdisk_enabled_check.setStyleSheet(self.voice_enabled_check.styleSheet())
        self.netdisk_enabled_check.toggled.connect(self._sync_netdisk_ui)
        enabled_row = QHBoxLayout()
        enabled_row.setContentsMargins(0, 0, 0, 0)
        enabled_row.addStretch(1)
        enabled_row.addWidget(self.netdisk_enabled_check, 0, Qt.AlignCenter)
        enabled_row.addStretch(1)
        layout.addLayout(enabled_row)

        self.netdisk_config_stack = QStackedWidget()
        self.netdisk_config_stack.setFixedHeight(360)
        self.netdisk_config_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.netdisk_blank_panel = QWidget()
        self.netdisk_config_stack.addWidget(self.netdisk_blank_panel)

        self.netdisk_panel = QWidget()
        self.netdisk_panel.setObjectName("netdiskPanel")
        self.netdisk_panel.setStyleSheet(
            """
            QLabel#sectionTitle {
                color: #0f766e;
                font-weight: 700;
            }
            QLabel#authStatusLabel {
                color: #475569;
                font-weight: 600;
            }
            QPushButton#netdiskAuthButton {
                color: #0f766e;
                border: 1px solid #0f766e;
                background: #ffffff;
                border-radius: 5px;
                font-weight: 600;
                min-height: 30px;
                padding: 4px 12px;
            }
            QPushButton#netdiskAuthButton:hover {
                background: #ecfdf5;
            }
            QPushButton#netdiskTestButton {
                color: #2563eb;
                border: 1px solid #93c5fd;
                background: #ffffff;
                border-radius: 5px;
                font-weight: 600;
                min-height: 30px;
                padding: 4px 12px;
            }
            QPushButton#netdiskTestButton:hover {
                background: #eff6ff;
            }
            """
        )
        panel_layout = QVBoxLayout(self.netdisk_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)

        header = QLabel("百度网盘同步配置")
        header.setObjectName("sectionTitle")
        panel_layout.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.netdisk_client_id_input = QLineEdit()
        self.netdisk_client_id_input.setPlaceholderText("请输入百度网盘 App Key / Client ID")
        form.addRow("App Key：", self.netdisk_client_id_input)

        self.netdisk_client_secret_input = QLineEdit()
        self.netdisk_client_secret_input.setPlaceholderText("请输入百度网盘 Secret Key / Client Secret")
        self.netdisk_client_secret_input.setEchoMode(QLineEdit.Password)
        form.addRow("Secret Key：", self.netdisk_client_secret_input)

        self.netdisk_remote_root_input = QLineEdit()
        self.netdisk_remote_root_input.setPlaceholderText("/电商溯源/videos/")
        form.addRow("远程上传根目录：", self.netdisk_remote_root_input)

        self.netdisk_debug_check = QCheckBox("启用调试日志")
        self.netdisk_debug_check.setToolTip("仅排查上传问题时开启；不会记录 token、refresh_token 或 Secret Key。")
        form.addRow("调试日志：", self.netdisk_debug_check)

        auth_row = QHBoxLayout()
        auth_row.setContentsMargins(0, 0, 0, 0)
        auth_row.setSpacing(8)
        self.netdisk_auth_status_label = QLabel("未授权")
        self.netdisk_auth_status_label.setObjectName("authStatusLabel")
        self.netdisk_auth_button = QPushButton("登录授权")
        self.netdisk_auth_button.setObjectName("netdiskAuthButton")
        self.netdisk_auth_button.clicked.connect(self._authorize_netdisk)
        self.netdisk_test_button = QPushButton("测试连接")
        self.netdisk_test_button.setObjectName("netdiskTestButton")
        self.netdisk_test_button.clicked.connect(self._test_netdisk_connection)
        auth_row.addWidget(self.netdisk_auth_status_label)
        auth_row.addSpacing(8)
        auth_row.addWidget(self.netdisk_auth_button)
        auth_row.addWidget(self.netdisk_test_button)
        auth_row.addStretch(1)
        auth_widget = QWidget()
        auth_widget.setLayout(auth_row)
        form.addRow("授权状态：", auth_widget)

        panel_layout.addLayout(form)
        hint = QLabel("提示：access_token 和 refresh_token 仅保存在本机配置文件中，不会显示在界面和日志里。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        panel_layout.addWidget(hint)
        panel_layout.addStretch(1)
        self.netdisk_config_stack.addWidget(self.netdisk_panel)
        layout.addWidget(self.netdisk_config_stack)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.netdisk_save_button = QPushButton("保存设置")
        self.netdisk_save_button.setObjectName("primaryButton")
        self.netdisk_save_button.setMinimumWidth(150)
        self.netdisk_save_button.clicked.connect(self._save_netdisk_settings)
        action_layout.addWidget(self.netdisk_save_button)
        action_layout.addStretch(1)
        layout.addLayout(action_layout)
        return widget

    def _export_config(self) -> None:
        default_name = f"PMSystem_Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "导出配置",
            str(Path.home() / default_name),
            "JSON 配置文件 (*.json)",
        )
        if not selected:
            return
        export_path = Path(selected)
        if export_path.suffix.lower() != ".json":
            export_path = export_path.with_suffix(".json")

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
            detail = "出于安全考虑，已排除网盘 Secret 和授权 Token，导入后需要重新授权。"
            if voice_count:
                detail += f"\n已导出自定义语音文件 {voice_count} 个。"
            if warnings:
                detail += "\n部分语音文件未导出，请查看日志。"
            self._set_status("配置已导出", "success")
            QMessageBox.information(self, "导出配置", f"配置已导出\n\n{detail}")
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
            "JSON 配置文件 (*.json)",
        )
        if not selected:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("导入配置")
        box.setText("导入配置将覆盖当前部分设置，是否继续？")
        box.setInformativeText("导入前会自动备份当前 config.json。网盘授权 Token 和 Secret 不会导入，导入后需要重新授权。")
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        confirm_button = box.addButton("继续导入", QMessageBox.AcceptRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() is not confirm_button:
            return

        import_path = Path(selected)
        try:
            result = self.config_manager.import_config(import_path)
            self.voice_prompt.update_config(self.config_manager.config)
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
            if warnings:
                detail += "\n部分自定义语音文件未恢复，请查看日志。"
            self._set_status("配置已导入，部分设置重启后生效", "success")
            QMessageBox.information(self, "导入配置", f"配置已导入，部分设置重启后生效。\n\n{detail}")
        except Exception as exc:
            self.logger.exception("配置导入失败：path=%s", import_path)
            self._set_status(f"配置导入失败：{exc}", "error")

    def refresh_state(self, is_recording: bool | None = None) -> None:
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
        self._load_netdisk_config_to_ui()
        self._set_basic_config_enabled(not bool(is_recording if is_recording is not None else self.is_recording_callback()))

    def _load_basic_config_to_ui(self) -> None:
        selected_index = int(self.config_manager.config.get("camera_index", 0) or 0)
        self._refresh_camera_options(selected_index)
        self._select_combo_data(self.resolution_combo, str(self.config_manager.config.get("resolution", "original")), "original")
        fps, _fps_valid = self._coerce_fps(self.config_manager.config.get("fps", DEFAULT_FPS))
        max_long_edge, _edge_valid = self._coerce_long_edge(
            self.config_manager.config.get("recording_max_long_edge", DEFAULT_LONG_EDGE)
        )
        self._select_combo_data(self.fps_combo, fps, DEFAULT_FPS)
        self._select_combo_data(self.recording_long_edge_combo, max_long_edge, DEFAULT_LONG_EDGE)
        self.font_size_spin.setValue(int(self.config_manager.config.get("watermark_font_size", 28) or 28))
        self.margin_spin.setValue(int(self.config_manager.config.get("watermark_margin", 16) or 16))

    def _set_basic_config_enabled(self, enabled: bool) -> None:
        for widget in (
            self.camera_combo,
            self.resolution_combo,
            self.fps_combo,
            self.recording_long_edge_combo,
            self.font_size_spin,
            self.margin_spin,
            self.apply_basic_config_button,
        ):
            widget.setEnabled(enabled)

    def _save_basic_config(self) -> None:
        if self.is_recording_callback():
            self.logger.info("录制中尝试修改基础配置")
            self._set_status("录制中不能修改基础配置，请结束录制后再修改。", "warning")
            self._set_basic_config_enabled(False)
            return

        try:
            values = {
                "camera_index": int(self.camera_combo.currentData() or 0),
                "camera_name": self._selected_camera_name(),
                "resolution": self.resolution_combo.currentData(),
                "fps": int(self.fps_combo.currentData() or DEFAULT_FPS),
                "recording_max_long_edge": int(self.recording_long_edge_combo.currentData() or 0),
                "watermark_font_size": self.font_size_spin.value(),
                "watermark_margin": self.margin_spin.value(),
            }
            updated_config = self.config_manager.update(values)
            self.basic_config_saved.emit(updated_config)
            self.logger.info("基础配置保存成功")
            self._set_status("基础配置保存成功", "success")
        except Exception as exc:
            self.logger.exception("基础配置保存失败")
            self._set_status(f"基础配置保存失败：{exc}", "error")

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
            self._set_status("语音设置已保存", "success")
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
        self.netdisk_enabled_check.blockSignals(True)
        self.netdisk_enabled_check.setChecked(bool(netdisk_config.get("enabled", False)))
        self.netdisk_enabled_check.blockSignals(False)

        self.netdisk_client_id_input.setText(str(netdisk_config.get("client_id") or ""))
        self.netdisk_client_secret_input.setText(str(netdisk_config.get("client_secret") or ""))
        self.netdisk_remote_root_input.setText(str(netdisk_config.get("remote_root") or "/电商溯源/videos/"))
        self.netdisk_debug_check.setChecked(bool(netdisk_config.get("debug", False)))
        self._refresh_netdisk_auth_status(netdisk_config)
        self._sync_netdisk_ui()

    def _current_netdisk_config(self) -> dict[str, object]:
        return normalize_netdisk_config(self.config_manager.config.get("netdisk_sync", {}))

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

    def _sync_netdisk_ui(self, *_args) -> None:
        enabled = self.netdisk_enabled_check.isChecked()
        self.netdisk_config_stack.setCurrentWidget(self.netdisk_panel if enabled else self.netdisk_blank_panel)
        for widget in (
            self.netdisk_client_id_input,
            self.netdisk_client_secret_input,
            self.netdisk_remote_root_input,
            self.netdisk_debug_check,
            self.netdisk_auth_button,
            self.netdisk_test_button,
        ):
            widget.setEnabled(enabled)

    def _refresh_netdisk_auth_status(self, netdisk_config: dict[str, object] | None = None) -> None:
        netdisk_config = netdisk_config or self._current_netdisk_config()
        if netdisk_config.get("access_token") or netdisk_config.get("refresh_token"):
            self.netdisk_auth_status_label.setText("已授权")
            self.netdisk_auth_status_label.setStyleSheet("color: #047857; font-weight: 700;")
            self.netdisk_auth_button.setText("重新授权")
        else:
            self.netdisk_auth_status_label.setText("未授权")
            self.netdisk_auth_status_label.setStyleSheet("color: #d97706; font-weight: 700;")
            self.netdisk_auth_button.setText("登录授权")

    def _save_netdisk_config(self, netdisk_config: dict[str, object]) -> dict:
        normalized = normalize_netdisk_config(netdisk_config)
        updated_config = self.config_manager.update({"netdisk_sync": normalized})
        self.config_saved.emit(updated_config)
        self.logger.info(
            "网盘同步配置保存成功：enabled=%s, provider=%s, remote_root=%s, has_client_id=%s, has_token=%s",
            normalized.get("enabled"),
            normalized.get("provider"),
            normalized.get("remote_root"),
            bool(normalized.get("client_id")),
            bool(normalized.get("access_token") or normalized.get("refresh_token")),
        )
        return updated_config

    def _save_netdisk_settings(self) -> None:
        try:
            netdisk_config = self._netdisk_config_from_ui()
            self._save_netdisk_config(netdisk_config)
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
