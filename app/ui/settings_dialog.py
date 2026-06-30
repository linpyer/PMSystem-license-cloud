from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.camera import list_camera_devices
from app.core.config_manager import ConfigManager
from app.core.voice_prompt import DEFAULT_VOICE_PROMPT_CONFIG, VoicePrompt
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

        self.setObjectName("settingsDialog")
        self.setWindowTitle("设置")
        self.resize(620, 430)
        self._build_ui()
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
        self.logger.info("基础配置页签初始化")
        self.logger.info("语音提示页签初始化")

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
        root_layout.addWidget(self.tabs, 1)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.close)
        bottom_layout.addWidget(self.close_button)
        root_layout.addLayout(bottom_layout)

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
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.voice_enabled_check = QCheckBox("开启系统语音提示")
        self.voice_start_edit = QLineEdit()
        self.voice_stop_edit = QLineEdit()
        self.voice_switch_edit = QLineEdit()
        self.voice_duplicate_edit = QLineEdit()

        form.addRow("语音提示：", self.voice_enabled_check)
        form.addRow("开始录制提示语：", self.voice_start_edit)
        form.addRow("结束录制提示语：", self.voice_stop_edit)
        form.addRow("切换录制提示语：", self.voice_switch_edit)
        form.addRow("重复录制提示语：", self.voice_duplicate_edit)
        layout.addLayout(form)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.test_voice_button = QPushButton("保存并测试语音")
        self.test_voice_button.setObjectName("primaryButton")
        self.test_voice_button.clicked.connect(self._save_and_test_voice)
        action_layout.addWidget(self.test_voice_button)
        layout.addLayout(action_layout)
        layout.addStretch(1)
        return widget

    def refresh_state(self, is_recording: bool | None = None) -> None:
        self._load_basic_config_to_ui()
        self._load_voice_config_to_ui()
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
        self.voice_enabled_check.setChecked(bool(voice_config.get("enabled", True)))
        self.voice_start_edit.setText(str(voice_config.get("start_text", "")))
        self.voice_stop_edit.setText(str(voice_config.get("stop_text", "")))
        self.voice_switch_edit.setText(str(voice_config.get("switch_text", "")))
        self.voice_duplicate_edit.setText(str(voice_config.get("duplicate_text", "")))

    def _current_voice_config(self) -> dict[str, str | bool]:
        voice_config = dict(DEFAULT_VOICE_PROMPT_CONFIG)
        raw = self.config_manager.config.get("voice_prompt", {})
        if isinstance(raw, dict):
            voice_config.update(raw)
        return voice_config

    def _voice_config_from_ui(self) -> dict[str, str | bool]:
        return {
            "enabled": self.voice_enabled_check.isChecked(),
            "start_text": self.voice_start_edit.text().strip(),
            "stop_text": self.voice_stop_edit.text().strip(),
            "switch_text": self.voice_switch_edit.text().strip(),
            "duplicate_text": self.voice_duplicate_edit.text().strip(),
        }

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
        if "（索引 " in text:
            return text.split("（索引 ", 1)[0]
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

    def _save_and_test_voice(self) -> None:
        try:
            voice_config = self._voice_config_from_ui()
            updated_config = self.config_manager.update({"voice_prompt": voice_config})
            self.voice_prompt.update_config(updated_config)
            self.config_saved.emit(updated_config)
            self.logger.info("语音配置保存成功：enabled=%s", voice_config.get("enabled", True))

            if not bool(voice_config.get("enabled", True)):
                self._set_status("语音提示已关闭，请开启后再测试。", "warning")
                self.logger.info("语音提示已关闭，测试语音未播放")
                return

            text = str(voice_config.get("start_text", "") or "").strip()
            if not text:
                text = str(DEFAULT_VOICE_PROMPT_CONFIG["start_text"])
                self._set_status("测试语音文本为空，已使用默认提示语。", "warning")

            self.logger.info("保存并测试语音使用的文本：%s", text)
            if self.voice_prompt.speak(text):
                self._set_status("正在播放测试语音。", "success")
            elif self.voice_prompt.backend_name() == "none":
                self._set_status("语音引擎不可用，请检查系统语音服务或依赖安装。", "error")
            else:
                self._set_status("测试语音播放失败，请查看日志。", "error")
        except Exception as exc:
            self.logger.exception("语音配置保存失败")
            self._set_status(f"语音配置保存失败：{exc}", "error")

    def _set_status(self, message: str, level: str = "info") -> None:
        show_toast(self, message, level, 2600, self.logger)
