from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path

import cv2
from PySide6.QtCore import QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
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
    QScrollBar,
    QSizePolicy,
    QSpacerItem,
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
from app.core.database import DatabaseManager, UPLOAD_DONE
from app.core.recorder import RecorderThread
from app.core.scanner import normalize_scan_text
from app.core.scanner_guard import ScannerGuard
from app.core.video_player import open_folder, open_video, reveal_in_file_manager
from app.core.voice_prompt import VoicePrompt
from app.ui.confirm_dialog import DELETE_CONFIRM_POSITION_KEY, ConfirmActionDialog
from app.ui.dialog_utils import DialogSizeManager
from app.ui.themed_line_edit import ThemedClearableLineEdit
from app.utils.file_utils import ensure_directory
from app.utils.runtime_paths import resource_path
from app.utils.time_utils import format_duration


CAMERA_STATUS_TOAST_PHRASES = (
    "摄像头连接异常",
    "摄像头已恢复",
    "摄像头断开",
    "正在重新连接摄像头",
    "重新连接摄像头",
    "摄像头读取失败",
    "摄像头状态",
    "摄像头打开失败",
    "摄像头已打开",
    "摄像头不可用",
    "摄像头正常",
    "摄像头初始化",
    "等待摄像头画面",
    "摄像头画面尚未就绪",
    "检测到正常帧",
    "iVCam 已连接",
    "iVCam 已断开",
    "iVCam 未启动或未连接",
    "摄像头已刷新",
)


def is_camera_status_message(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    user_action_messages = (
        "录制中不能刷新摄像头",
        "录制中不能修改摄像头配置",
        "摄像头已刷新",
        "摄像头刷新失败",
    )
    if any(message in text for message in user_action_messages):
        return False
    return any(phrase in text for phrase in CAMERA_STATUS_TOAST_PHRASES) or "摄像头" in text or "ivcam" in text.lower()


FPS_OPTIONS = [15, 20, 25, 30, 60]
DEFAULT_FPS = 25
LONG_EDGE_OPTIONS = [0, 960, 1280, 1920]
DEFAULT_LONG_EDGE = 1280
ENABLE_CAMERA_ERROR_WAVE_EFFECT = True
RIGHT_PANEL_CONTENT_MARGIN = 14
RECENT_RECORD_CONTENT_LEFT = 0
SUMMARY_RESIZE_DEBOUNCE_MS = 75

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


class PreviewAlertOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._phase = 0.0
        self._boost_until = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._advance_phase)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hide()

    def set_alert_state(self, state: str) -> None:
        state = state if state in {"none", "weak", "strong", "steady"} else "none"
        if state == "none":
            self.stop_warning()
            return
        self.start_warning(boost=state == "strong")

    def start_warning(self, *, boost: bool = False) -> None:
        now = time.monotonic()
        if boost and not self._active:
            self._boost_until = now + 0.45
        if self._active:
            self.update()
            return
        self._active = True
        self._phase = 0.0
        self.show()
        self._timer.start()
        self.update()

    def stop_warning(self) -> None:
        self._timer.stop()
        self._active = False
        self._phase = 0.0
        self._boost_until = 0.0
        self.hide()
        self.update()

    def _advance_phase(self) -> None:
        if not self._active:
            self._timer.stop()
            return
        self._phase = (self._phase + (2 * math.pi / 22)) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        wave = (math.sin(self._phase) + 1.0) / 2.0
        opacity = 0.13 + 0.05 * math.sin(self._phase)
        if time.monotonic() < self._boost_until:
            opacity = min(0.25, max(opacity, 0.22))
        opacity = max(0.09, min(0.18 if time.monotonic() >= self._boost_until else 0.25, opacity))
        thickness = int(24 + 12 * wave)
        thickness = min(thickness, max(12, rect.width() // 4), max(12, rect.height() // 4))
        edge_alpha = int(255 * opacity)
        soft_alpha = int(edge_alpha * 0.45)

        top = QLinearGradient(0, rect.top(), 0, rect.top() + thickness)
        top.setColorAt(0.0, QColor(153, 27, 27, edge_alpha))
        top.setColorAt(0.55, QColor(220, 38, 38, soft_alpha))
        top.setColorAt(1.0, QColor(220, 38, 38, 0))
        painter.fillRect(rect.left(), rect.top(), rect.width(), thickness, top)

        bottom = QLinearGradient(0, rect.bottom(), 0, rect.bottom() - thickness)
        bottom.setColorAt(0.0, QColor(153, 27, 27, edge_alpha))
        bottom.setColorAt(0.55, QColor(220, 38, 38, soft_alpha))
        bottom.setColorAt(1.0, QColor(220, 38, 38, 0))
        painter.fillRect(rect.left(), rect.bottom() - thickness + 1, rect.width(), thickness, bottom)

        left = QLinearGradient(rect.left(), 0, rect.left() + thickness, 0)
        left.setColorAt(0.0, QColor(153, 27, 27, edge_alpha))
        left.setColorAt(0.55, QColor(220, 38, 38, soft_alpha))
        left.setColorAt(1.0, QColor(220, 38, 38, 0))
        painter.fillRect(rect.left(), rect.top(), thickness, rect.height(), left)

        right = QLinearGradient(rect.right(), 0, rect.right() - thickness, 0)
        right.setColorAt(0.0, QColor(153, 27, 27, edge_alpha))
        right.setColorAt(0.55, QColor(220, 38, 38, soft_alpha))
        right.setColorAt(1.0, QColor(220, 38, 38, 0))
        painter.fillRect(rect.right() - thickness + 1, rect.top(), thickness, rect.height(), right)

        border = QColor(220, 38, 38, min(140, edge_alpha + 26))
        painter.fillRect(rect.left(), rect.top(), rect.width(), 2, border)
        painter.fillRect(rect.left(), rect.bottom() - 1, rect.width(), 2, border)
        painter.fillRect(rect.left(), rect.top(), 2, rect.height(), border)
        painter.fillRect(rect.right() - 1, rect.top(), 2, rect.height(), border)


class MonitorRightPanel(QWidget):
    resized = Signal(QSize)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.resized.emit(event.size())

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.resized.emit(self.contentsRect().size())


class TodayRecordSummaryCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("todayRecordSummaryCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(114)
        self._responsive_profile = ""
        self._available_size = QSize(0, 0)
        self._first_show_style_applied = False
        self._first_show_style_pending = False
        self._theme_style_reapply_pending = False
        self._responsive_timer = QTimer(self)
        self._responsive_timer.setSingleShot(True)
        self._responsive_timer.setInterval(SUMMARY_RESIZE_DEBOUNCE_MS)
        self._responsive_timer.timeout.connect(self._apply_pending_responsive_layout)

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(14, 14, 14, 14)
        self.outer_layout.setSpacing(0)

        self.top_section = QWidget(self)
        self.top_section.setObjectName("todayTopSection")
        self.top_layout = QVBoxLayout(self.top_section)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(0)
        self.top_layout.addStretch(1)

        self.title_label = QLabel("今日发货")
        self.title_label.setObjectName("todaySummaryTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.top_layout.addWidget(self.title_label)
        self.title_number_spacer = QSpacerItem(0, 9, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.top_layout.addItem(self.title_number_spacer)

        self.number_layout = QHBoxLayout()
        self.number_layout.setContentsMargins(0, 0, 0, 0)
        self.number_layout.setSpacing(6)
        self.number_layout.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        self.shipping_value_label = QLabel("0")
        self.shipping_value_label.setObjectName("todayShippingValue")
        self.shipping_value_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.unit_label = QLabel("单")
        self.unit_label.setObjectName("todaySummaryUnit")
        self.unit_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.number_layout.addWidget(self.shipping_value_label, 0, Qt.AlignBottom)
        self.number_layout.addWidget(self.unit_label, 0, Qt.AlignBottom)
        self.top_layout.addLayout(self.number_layout)
        self.top_layout.addStretch(1)

        self.divider = QFrame(self)
        self.divider.setObjectName("todaySummaryDivider")
        self.divider.setFrameShape(QFrame.HLine)

        self.bottom_section = QWidget(self)
        self.bottom_section.setObjectName("todayBottomSection")
        self.metrics_layout = QHBoxLayout(self.bottom_section)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_layout.setSpacing(20)
        (
            return_metric,
            return_title,
            self.return_value_label,
            self.return_unit_label,
            return_number_layout,
        ) = self._build_secondary_metric(
            "今日退货", "todayReturnValue"
        )
        (
            total_metric,
            total_title,
            self.total_value_label,
            self.total_unit_label,
            total_number_layout,
        ) = self._build_secondary_metric(
            "今日扫描总量", "todayTotalValue"
        )
        self.secondary_title_labels = (return_title, total_title)
        self.secondary_unit_labels = (self.return_unit_label, self.total_unit_label)
        self.secondary_metric_layouts = (return_metric.layout(), total_metric.layout())
        self.secondary_number_layouts = (return_number_layout, total_number_layout)
        self.metrics_layout.addWidget(return_metric, 1)
        self.metrics_layout.addWidget(total_metric, 1)

        self.outer_layout.addWidget(self.top_section, 3)
        self.outer_layout.addWidget(self.divider, 0)
        self.outer_layout.addWidget(self.bottom_section, 2)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.schedule_responsive_update(self.contentsRect().size())

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._first_show_style_applied and not self._first_show_style_pending:
            self._first_show_style_pending = True
            self.setUpdatesEnabled(False)
            QTimer.singleShot(0, self._apply_first_show_responsive_style)
            return
        self.schedule_responsive_update(self.contentsRect().size())

    def _apply_first_show_responsive_style(self) -> None:
        self._first_show_style_pending = False
        try:
            self.update_responsive_style(force=True)
            self._first_show_style_applied = True
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def handle_theme_changed(self, _mode: str = "system", _resolved_theme: str = "light") -> None:
        if self._theme_style_reapply_pending:
            return
        self._theme_style_reapply_pending = True
        self.setUpdatesEnabled(False)
        QTimer.singleShot(0, self._reapply_responsive_style_after_theme)

    def _reapply_responsive_style_after_theme(self) -> None:
        self._theme_style_reapply_pending = False
        try:
            self.update_responsive_style(force=True)
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    @staticmethod
    def _build_secondary_metric(
        title: str,
        value_object_name: str,
    ) -> tuple[QWidget, QLabel, QLabel, QLabel, QHBoxLayout]:
        metric = QWidget()
        metric.setObjectName("todaySecondaryMetric")
        metric_layout = QVBoxLayout(metric)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(3)
        metric_layout.addStretch(1)
        title_label = QLabel(title)
        title_label.setObjectName("todaySecondaryTitle")
        title_label.setAlignment(Qt.AlignCenter)
        value_label = QLabel("0")
        value_label.setObjectName(value_object_name)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        unit_label = QLabel("单")
        unit_label.setObjectName("todaySummaryUnit")
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        number_layout = QHBoxLayout()
        number_layout.setContentsMargins(0, 0, 0, 0)
        number_layout.setSpacing(4)
        number_layout.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        number_layout.addWidget(value_label, 0, Qt.AlignBottom)
        number_layout.addWidget(unit_label, 0, Qt.AlignBottom)
        metric_layout.addWidget(title_label)
        metric_layout.addLayout(number_layout)
        metric_layout.addStretch(1)
        return metric, title_label, value_label, unit_label, number_layout

    def set_counts(self, ship_records: int, return_records: int) -> None:
        ship_records = max(0, int(ship_records))
        return_records = max(0, int(return_records))
        self.shipping_value_label.setText(str(ship_records))
        self.return_value_label.setText(str(return_records))
        self.total_value_label.setText(str(ship_records + return_records))

    def schedule_responsive_update(self, available_size: QSize) -> None:
        self._available_size = QSize(available_size)
        self._responsive_timer.start()

    def _apply_pending_responsive_layout(self) -> None:
        self.update_responsive_style()

    def update_responsive_style(self, force: bool = False) -> None:
        size = self.contentsRect().size()
        if size.width() <= 0 or size.height() <= 0:
            size = self._available_size
        profile = self._select_responsive_profile(max(0, size.width()), max(0, size.height()))
        self._apply_responsive_profile(profile, force=force)

    def _select_responsive_profile(self, width: int, height: int) -> str:
        current = self._responsive_profile
        if width <= 0 or height <= 0:
            return current or "normal"
        if current == "compact":
            return "normal" if height >= 230 and width >= 320 else "compact"
        if current == "large":
            return "normal" if height < 285 or width < 320 else "large"
        if current == "normal":
            if height < 210 or width < 310:
                return "compact"
            if height >= 315 and width >= 330:
                return "large"
            return "normal"
        if height < 220 or width < 310:
            return "compact"
        if height >= 300 and width >= 330:
            return "large"
        return "normal"

    def _apply_responsive_profile(self, profile: str, force: bool = False) -> None:
        if profile == self._responsive_profile and not force:
            return
        values = {
            "compact": {
                "margin": 9,
                "title_gap": 6,
                "number_spacing": 5,
                "metrics_spacing": 16,
                "secondary_gap": 5,
                "title_size": 17,
                "title_spacing": 2.0,
                "number_size": 56,
                "unit_size": 15,
                "unit_bottom": 3,
                "secondary_title_size": 13,
                "secondary_title_spacing": 1.5,
                "secondary_value_size": 31,
                "secondary_unit_size": 10,
                "secondary_unit_bottom": 2,
                "secondary_number_spacing": 4,
                "show_secondary": False,
            },
            "normal": {
                "margin": 14,
                "title_gap": 9,
                "number_spacing": 6,
                "metrics_spacing": 24,
                "secondary_gap": 6,
                "title_size": 18,
                "title_spacing": 2.8,
                "number_size": 64,
                "unit_size": 17,
                "unit_bottom": 4,
                "secondary_title_size": 13,
                "secondary_title_spacing": 2.0,
                "secondary_value_size": 35,
                "secondary_unit_size": 12,
                "secondary_unit_bottom": 3,
                "secondary_number_spacing": 5,
                "show_secondary": True,
            },
            "large": {
                "margin": 18,
                "title_gap": 12,
                "number_spacing": 8,
                "metrics_spacing": 32,
                "secondary_gap": 8,
                "title_size": 24,
                "title_spacing": 3.6,
                "number_size": 88,
                "unit_size": 22,
                "unit_bottom": 6,
                "secondary_title_size": 17,
                "secondary_title_spacing": 2.5,
                "secondary_value_size": 48,
                "secondary_unit_size": 16,
                "secondary_unit_bottom": 4,
                "secondary_number_spacing": 6,
                "show_secondary": True,
            },
        }[profile]
        margin = int(values["margin"])
        self.outer_layout.setContentsMargins(margin, margin, margin, margin)
        self.title_number_spacer.changeSize(0, int(values["title_gap"]), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.number_layout.setSpacing(int(values["number_spacing"]))
        self.metrics_layout.setSpacing(int(values["metrics_spacing"]))
        for metric_layout in self.secondary_metric_layouts:
            metric_layout.setSpacing(int(values["secondary_gap"]))
        for number_layout in self.secondary_number_layouts:
            number_layout.setSpacing(int(values["secondary_number_spacing"]))
        self._set_label_font(
            self.title_label,
            int(values["title_size"]),
            QFont.Weight.Bold,
            float(values["title_spacing"]),
        )
        self._set_label_font(self.shipping_value_label, int(values["number_size"]), QFont.Weight.Bold)
        self._set_label_font(self.unit_label, int(values["unit_size"]), QFont.Weight.Normal)
        self.unit_label.setContentsMargins(0, 0, 0, int(values["unit_bottom"]))
        for label in self.secondary_title_labels:
            self._set_label_font(
                label,
                int(values["secondary_title_size"]),
                QFont.Weight.DemiBold,
                float(values["secondary_title_spacing"]),
            )
        self._set_label_font(self.return_value_label, int(values["secondary_value_size"]), QFont.Weight.Bold)
        self._set_label_font(self.total_value_label, int(values["secondary_value_size"]), QFont.Weight.Bold)
        for label in self.secondary_unit_labels:
            self._set_label_font(label, int(values["secondary_unit_size"]), QFont.Weight.Normal)
            label.setContentsMargins(0, 0, 0, int(values["secondary_unit_bottom"]))
        show_secondary = bool(values["show_secondary"])
        self.divider.setVisible(show_secondary)
        self.bottom_section.setVisible(show_secondary)
        self.outer_layout.setStretch(0, 3 if show_secondary else 1)
        self.outer_layout.setStretch(2, 2 if show_secondary else 0)
        self._responsive_profile = profile
        for label in (
            self.title_label,
            self.shipping_value_label,
            self.unit_label,
            *self.secondary_title_labels,
            self.return_value_label,
            self.total_value_label,
            *self.secondary_unit_labels,
        ):
            label.updateGeometry()
        self.top_layout.invalidate()
        self.metrics_layout.invalidate()
        self.outer_layout.invalidate()
        self.top_section.updateGeometry()
        self.bottom_section.updateGeometry()
        self.updateGeometry()

    @staticmethod
    def _set_label_font(
        label: QLabel,
        pixel_size: int,
        weight: QFont.Weight,
        letter_spacing: float = 0.0,
    ) -> None:
        font = label.font()
        font.setPixelSize(pixel_size)
        font.setWeight(weight)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        label.setFont(font)


class MonitorTab(QWidget):
    status_message = Signal(str)
    warning_message = Signal(str)
    critical_message = Signal(str)

    def __init__(
        self,
        config_manager: ConfigManager,
        logger: logging.Logger,
        license_manager=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("monitorPage")
        self.config_manager = config_manager
        self.logger = logger
        self.license_manager = license_manager
        self.config = self.config_manager.config
        self.is_recording = False
        self.current_order_id = ""
        self._pending_voice_action: str | None = None
        self._pending_scan_feedback: dict[str, str] | None = None
        self._event_filter_installed = False
        self._theme_manager = None
        self._right_panel_density = ""
        self.scan_feedback_timer = QTimer(self)
        self.scan_feedback_timer.setSingleShot(True)
        self.scan_feedback_timer.timeout.connect(self._reset_scan_feedback)
        self.recording_alert_timer = QTimer(self)
        self.recording_alert_timer.setInterval(1000)
        self.recording_alert_timer.timeout.connect(self._pulse_recording_alert_border)
        self._recording_alert_steps: list[str] = []
        self._last_recording_alert_reason = ""
        self._last_recording_alert_at = 0.0
        self._camera_error_active = False
        self._camera_error_reason = ""
        self._today_summary_date = date.today()
        self._day_rollover_timer = QTimer(self)
        self._day_rollover_timer.setSingleShot(True)
        self._day_rollover_timer.timeout.connect(self._handle_day_rollover)
        self._normalize_video_config_on_startup()
        self.scanner_guard = ScannerGuard(self.config, logger)
        self.voice_prompt = VoicePrompt(self.config, logger)

        self.recorder = RecorderThread(
            config=self.config,
            base_dir=self.config_manager.base_dir,
            logger=logger,
            db_path=self.config_manager.database_path,
            recording_permission_checker=(
                self.license_manager.can_start_recording if self.license_manager is not None else None
            ),
        )
        self._build_ui()
        self._connect_signals()
        self._load_config_to_controls()
        if self.license_manager is not None:
            self.license_manager.status_changed.connect(self._on_license_status_changed)
            self._apply_license_state()

        self.recorder.start()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._event_filter_installed = True
            self._theme_manager = app.property("theme_manager")
            if self._theme_manager is not None:
                self._theme_manager.theme_changed.connect(self._refresh_action_icons)
                self._theme_manager.theme_changed.connect(self.today_summary_card.handle_theme_changed)
        self.focus_scan_input()
        QTimer.singleShot(0, self.refresh_record_summaries)
        QTimer.singleShot(0, self._schedule_summary_responsive_update)
        self._schedule_day_rollover()

    def shutdown(self) -> None:
        self._clear_recording_alert()
        self._day_rollover_timer.stop()
        if self._event_filter_installed:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._event_filter_installed = False
        self.recorder.stop_thread()
        self.recorder.wait(5000)
        self.voice_prompt.stop()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._clear_recording_alert()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.set_window_maximized(self.window().isMaximized())
        QTimer.singleShot(0, self.refresh_today_summary)
        if self._camera_error_active:
            self.refresh_status_card()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        focus_widget = QApplication.focusWidget()
        if event.type() == QEvent.ScreenChangeInternal:
            QTimer.singleShot(0, self._schedule_summary_responsive_update)
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
            self._pending_scan_feedback = {
                "event": "stop",
                "order_no": self.current_order_id,
            }
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

        content_layout = QGridLayout()
        content_layout.setColumnStretch(0, 3)
        content_layout.setColumnStretch(1, 1)
        content_layout.setColumnMinimumWidth(1, 400)
        root_layout.addLayout(content_layout, 1)

        preview_container = QFrame()
        preview_container.setObjectName("previewContainer")
        preview_container.setMinimumSize(720, 480)
        preview_layout = QGridLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        self.preview_label = QLabel("正在打开摄像头...")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setProperty("recordingAlert", "none")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(720, 480)
        self.preview_alert_overlay = PreviewAlertOverlay(preview_container)
        preview_layout.addWidget(self.preview_label, 0, 0)
        preview_layout.addWidget(self.preview_alert_overlay, 0, 0)
        self.preview_alert_overlay.raise_()
        content_layout.addWidget(preview_container, 0, 0)

        self.side_panel_container = MonitorRightPanel()
        self.side_panel_container.setObjectName("rightOperationPanel")
        self.side_panel_container.setMinimumWidth(400)
        self.side_panel_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.side_panel_layout = QVBoxLayout(self.side_panel_container)
        self.side_panel_layout.setContentsMargins(
            RIGHT_PANEL_CONTENT_MARGIN,
            RIGHT_PANEL_CONTENT_MARGIN,
            RIGHT_PANEL_CONTENT_MARGIN,
            RIGHT_PANEL_CONTENT_MARGIN,
        )
        self.side_panel_layout.setSpacing(12)
        self.side_panel_container.resized.connect(self._update_right_panel_density)
        content_layout.addWidget(self.side_panel_container, 0, 1)

        status_group = QGroupBox("")
        status_group.setObjectName("plainRightCard")
        status_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        status_layout = QVBoxLayout(status_group)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        self.status_block = QFrame()
        self.status_block.setObjectName("recordingStatusBlock")
        self.status_block.setProperty("state", "idle")
        self.status_block.setMinimumHeight(78)
        self.status_block.setMaximumHeight(96)
        status_block_layout = QVBoxLayout(self.status_block)
        status_block_layout.setContentsMargins(12, 8, 12, 8)
        status_block_layout.setSpacing(2)
        self.status_label = QLabel("等待扫码")
        self.status_label.setObjectName("recordingStatusTitle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_detail_label = QLabel("请扫描单号")
        self.status_detail_label.setObjectName("recordingStatusDetail")
        self.status_detail_label.setAlignment(Qt.AlignCenter)
        self.status_detail_label.setWordWrap(True)
        status_block_layout.addStretch(1)
        status_block_layout.addWidget(self.status_label)
        status_block_layout.addWidget(self.status_detail_label)
        status_block_layout.addStretch(1)
        status_layout.addWidget(self.status_block)

        status_info_layout = QFormLayout()
        status_info_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_info_layout.setFormAlignment(Qt.AlignTop)
        status_info_layout.setHorizontalSpacing(10)
        status_info_layout.setVerticalSpacing(5)
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
        status_info_layout.addRow(self.start_time_title_label, self.start_time_label)
        status_info_layout.addRow("录制时长：", self.duration_label)
        status_info_layout.addRow("摄像头：", self.camera_status_label)
        status_layout.addLayout(status_info_layout)
        self._set_start_time_visible(False)
        self.side_panel_layout.addWidget(status_group, 0)

        status_divider = QFrame()
        status_divider.setObjectName("monitorPanelDivider")
        status_divider.setFrameShape(QFrame.HLine)
        self.side_panel_layout.addWidget(status_divider, 0)

        scan_group = QGroupBox("")
        scan_group.setObjectName("plainRightCard")
        scan_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setSpacing(6)
        self.scan_input = ThemedClearableLineEdit()
        self.scan_input.setObjectName("scanInput")
        self.scan_input.setPlaceholderText("请输入或扫描单号")

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
        self.ship_record_type_radio.setProperty("recordType", "ship")
        self.return_record_type_radio.setProperty("recordType", "return")
        self.ship_record_type_radio.setChecked(True)
        self.record_type_button_group = QButtonGroup(self)
        self.record_type_button_group.setExclusive(True)
        self.record_type_button_group.addButton(self.ship_record_type_radio, 1)
        self.record_type_button_group.addButton(self.return_record_type_radio, 2)
        record_type_layout.addWidget(self.ship_record_type_radio)
        record_type_layout.addWidget(self.return_record_type_radio)
        record_type_layout.addStretch(1)

        scan_title = QLabel("扫描单号")
        scan_title.setObjectName("sectionTitle")
        scan_layout.addWidget(record_type_title)
        scan_layout.addLayout(record_type_layout)
        scan_layout.addSpacing(5)
        scan_layout.addWidget(record_type_separator)
        scan_layout.addSpacing(5)
        scan_layout.addWidget(scan_title)
        scan_layout.addWidget(self.scan_input)
        self.side_panel_layout.addWidget(scan_group, 0)

        scan_divider = QFrame()
        scan_divider.setObjectName("monitorPanelDivider")
        scan_divider.setFrameShape(QFrame.HLine)
        self.side_panel_layout.addWidget(scan_divider, 0)

        button_group = QGroupBox("")
        button_group.setObjectName("plainRightCard")
        button_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        button_layout = QGridLayout(button_group)
        button_layout.setHorizontalSpacing(8)
        button_layout.setVerticalSpacing(8)
        self.manual_start_button = QPushButton("手动开始录制")
        self.manual_start_button.setObjectName("primaryButton")
        self.manual_stop_button = QPushButton("手动停止录制")
        self.manual_stop_button.setObjectName("stopButton")
        self.open_folder_button = QPushButton("打开视频存储目录")
        self.refresh_camera_button = QPushButton("刷新摄像头")
        button_layout.addWidget(self.manual_start_button, 0, 0)
        button_layout.addWidget(self.manual_stop_button, 0, 1)
        button_layout.addWidget(self.open_folder_button, 1, 0)
        button_layout.addWidget(self.refresh_camera_button, 1, 1)
        self.open_folder_button.setObjectName("secondaryButton")
        self.refresh_camera_button.setObjectName("secondaryButton")
        self.side_panel_layout.addWidget(button_group, 0)

        action_divider = QFrame()
        action_divider.setObjectName("monitorPanelDivider")
        action_divider.setFrameShape(QFrame.HLine)
        self.side_panel_layout.addWidget(action_divider, 0)

        recent_group = QGroupBox("")
        recent_group.setObjectName("recentCard")
        recent_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        recent_layout = QVBoxLayout(recent_group)
        recent_layout.setContentsMargins(RECENT_RECORD_CONTENT_LEFT, 0, 0, 0)
        recent_layout.setSpacing(6)
        recent_title_layout = QHBoxLayout()
        recent_title_layout.setContentsMargins(RECENT_RECORD_CONTENT_LEFT, 0, 0, 0)
        recent_title_layout.setSpacing(0)
        recent_title_label = QLabel("最近录制")
        recent_title_label.setObjectName("recentCardTitle")
        recent_title_layout.addWidget(recent_title_label)
        recent_title_layout.addStretch(1)
        self.recent_recordings_layout = QVBoxLayout()
        self.recent_recordings_layout.setContentsMargins(RECENT_RECORD_CONTENT_LEFT, 0, 0, 0)
        self.recent_recordings_layout.setSpacing(0)
        recent_layout.addLayout(recent_title_layout)
        recent_layout.addLayout(self.recent_recordings_layout)
        self.side_panel_layout.addWidget(recent_group, 0)

        self.today_summary_card = TodayRecordSummaryCard(self.side_panel_container)
        self.side_panel_layout.addWidget(self.today_summary_card, 1)
        self.logger.info("录制类型单选框初始化")
        self.logger.info("最近录制模块初始化")
        self.logger.info("今日录制统计模块初始化")
        self.logger.info("打包监控页右侧布局初始化")

    def _connect_signals(self) -> None:
        self.scan_input.returnPressed.connect(self._handle_scan_return)
        self.manual_start_button.clicked.connect(lambda: self._manual_start())
        self.manual_stop_button.clicked.connect(lambda: self._manual_stop())
        self.open_folder_button.clicked.connect(lambda: self._open_video_folder())
        self.refresh_camera_button.clicked.connect(lambda: self._refresh_camera())
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
        self.recorder.camera_refresh_finished.connect(self._on_manual_camera_refresh_finished)
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
        DialogSizeManager.position_transient(box, self)
        box.exec()

    def _reset_scan_feedback(self) -> None:
        self.refresh_status_card()

    def refresh_status_card(self) -> None:
        if self._camera_error_active:
            reason = self._camera_error_reason or "摄像头连接异常，请检查 iVCam 或摄像头"
            detail = f"{reason}  请检查 iVCam 或摄像头连接"
            self._set_scan_feedback("error", "异常", detail, auto_reset=False)
            self._start_recording_alert_border()
            return
        if self.is_recording:
            detail = f"单号：{self.current_order_id}" if self.current_order_id else ""
            self._set_scan_feedback("recording", "录制中", detail, auto_reset=False)
            return
        self._set_scan_feedback("idle", "等待扫码", "请扫描单号", auto_reset=False)

    def _set_scan_feedback(
        self,
        feedback_type: str,
        title: str,
        message: str,
        detail: str = "",
        *,
        auto_reset: bool = True,
        duration_ms: int = 2600,
    ) -> None:
        self.scan_feedback_timer.stop()
        feedback_type = (
            feedback_type
            if feedback_type in {"idle", "recording", "start", "stop", "switch", "warning", "error"}
            else "idle"
        )
        subtitle_parts = [part for part in (message, detail) if part]
        self.status_block.setProperty("state", feedback_type)
        self.status_label.setText(title)
        self.status_detail_label.setText("  ".join(subtitle_parts))
        self.status_detail_label.setVisible(bool(subtitle_parts))
        for widget in (
            self.status_block,
            self.status_label,
            self.status_detail_label,
        ):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if auto_reset:
            self.scan_feedback_timer.start(max(1200, int(duration_ms)))

    def show_scan_feedback(self, event_key: str, data: dict[str, str] | None = None) -> None:
        data = dict(data or {})
        if event_key == "start":
            order_no = str(data.get("order_no") or "").strip()
            self._set_scan_feedback("start", "已开始录制", f"单号：{order_no}" if order_no else "")
            return
        if event_key == "stop":
            order_no = str(data.get("order_no") or "").strip()
            self._set_scan_feedback("stop", "已结束录制", f"单号：{order_no}" if order_no else "")
            return
        if event_key == "switch":
            current_order_no = str(data.get("current_order_no") or "").strip()
            detail = f"当前单号：{current_order_no}" if current_order_no else ""
            self._set_scan_feedback("switch", "已切换录制", detail)
            return
        if event_key == "no_order":
            self._set_scan_feedback("warning", "未输入单号", "请先输入或扫描单号")
            return
        if event_key == "invalid":
            self._set_scan_feedback("warning", "扫码无效", "请重新扫描单号")
            return
        self._set_scan_feedback("error", "异常", str(data.get("message") or "请重新扫描"), auto_reset=False)

    def show_recording_alert(self, reason: str, *, play_voice: bool = True) -> None:
        reason = str(reason or "录制异常").strip()
        if self._pending_voice_action in {"start", "switch"}:
            self._pending_voice_action = None
        if self._pending_scan_feedback and self._pending_scan_feedback.get("event") in {"start", "switch"}:
            self._pending_scan_feedback = None
        detail = f"{reason}  请检查摄像头 / iVCam / 磁盘空间后重试"
        self._set_scan_feedback("error", "异常", detail, auto_reset=False)
        self._start_recording_alert_border()
        if not play_voice:
            return
        now = time.monotonic()
        duplicate_voice = reason == self._last_recording_alert_reason and now - self._last_recording_alert_at < 5.0
        self._last_recording_alert_reason = reason
        self._last_recording_alert_at = now
        if duplicate_voice:
            self.logger.info("录制异常语音去重：reason=%s", reason)
            return
        event_key = self._voice_event_for_recording_alert(reason)
        if self.voice_prompt.play(event_key):
            self.logger.info("录制异常语音已提交播放：event=%s, reason=%s", event_key, reason)
        else:
            self.logger.warning("录制异常语音提交失败：event=%s, reason=%s", event_key, reason)

    @staticmethod
    def _voice_event_for_recording_alert(reason: str) -> str:
        if "磁盘" in reason or "空间" in reason:
            return "disk_full"
        if "摄像头" in reason or "iVCam" in reason or "读取失败" in reason or "冻结" in reason:
            return "camera_lost"
        return "record_error"

    def _start_recording_alert_border(self) -> None:
        self.recording_alert_timer.stop()
        self._recording_alert_steps = []
        self._set_preview_alert_state("strong")

    def _pulse_recording_alert_border(self) -> None:
        self.recording_alert_timer.stop()
        self._recording_alert_steps = []
        self._set_preview_alert_state("steady")

    def _set_preview_alert_state(self, state: str) -> None:
        state = state if state in {"none", "weak", "strong", "steady"} else "none"
        self.preview_label.setProperty("recordingAlert", state)
        self.preview_label.style().unpolish(self.preview_label)
        self.preview_label.style().polish(self.preview_label)
        if hasattr(self, "preview_alert_overlay"):
            overlay_state = state if ENABLE_CAMERA_ERROR_WAVE_EFFECT else "none"
            self.preview_alert_overlay.set_alert_state(overlay_state)
            self.preview_alert_overlay.raise_()

    def _clear_recording_alert(self) -> None:
        self.recording_alert_timer.stop()
        self._recording_alert_steps = []
        self._set_preview_alert_state("none")

    def _scan_feedback_for_scan(self, order_id: str, previous_order_id: str) -> dict[str, str] | None:
        order_id = order_id.strip()
        previous_order_id = previous_order_id.strip()
        if self.is_recording:
            if not order_id or order_id == previous_order_id:
                return {"event": "stop", "order_no": previous_order_id}
            return {
                "event": "switch",
                "previous_order_no": previous_order_id,
                "current_order_no": order_id,
            }
        if order_id:
            return {"event": "start", "order_no": order_id}
        return None

    def _camera_start_block_reason(self) -> str:
        try:
            health = self.recorder.camera_health()
        except Exception as exc:
            self.logger.exception("读取摄像头健康状态失败")
            return f"摄像头状态异常：{exc}"
        if bool(health.get("is_healthy", False)):
            return ""
        reason = str(health.get("last_error") or "").strip()
        return reason or "摄像头连接异常，请检查 iVCam 或摄像头"

    def _block_recording_start_for_camera_error(self, reason: str) -> None:
        reason = str(reason or "摄像头连接异常，请检查 iVCam 或摄像头").strip()
        self._pending_voice_action = None
        self._pending_scan_feedback = None
        self._camera_error_active = True
        self._camera_error_reason = reason
        self.logger.warning("摄像头异常，拦截开始录制：%s", reason)
        self.show_recording_alert(reason)
        self.warning_message.emit(reason)
        self.status_message.emit(reason)

    def _handle_scan_return(self) -> None:
        raw_text = self.scan_input.text()
        result = self.scanner_guard.process(raw_text)
        if result.should_warn:
            self.warning_message.emit(result.warning_message)
            self.status_message.emit(result.warning_message)
        if not self.is_recording and not result.cleaned_code:
            if str(result.raw_code or "").strip():
                self.show_scan_feedback("invalid")
            else:
                self._notify_no_order()
            self.scan_input.clear()
            self.focus_scan_input(80)
            return
        if not result.should_ignore:
            if not self.is_recording and result.cleaned_code:
                if not self._license_allows_new_recording():
                    self.scan_input.clear()
                    self.focus_scan_input(80)
                    return
                camera_error = self._camera_start_block_reason()
                if camera_error:
                    self._block_recording_start_for_camera_error(camera_error)
                    self.scan_input.clear()
                    self.focus_scan_input(80)
                    return
            is_duplicate = self._warn_if_duplicate_recording(result.cleaned_code)
            self._pending_voice_action = self._voice_action_for_scan(result.cleaned_code, is_duplicate)
            self._pending_scan_feedback = self._scan_feedback_for_scan(result.cleaned_code, self.current_order_id)
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
                self.warning_message.emit("请先输入或扫描单号。")
            self.focus_scan_input(80)
            return
        if not self.is_recording and not self._license_allows_new_recording():
            self.scan_input.clear()
            self.focus_scan_input(80)
            return
        camera_error = self._camera_start_block_reason()
        if camera_error:
            self._block_recording_start_for_camera_error(camera_error)
            self.scan_input.clear()
            self.focus_scan_input(80)
            return
        is_duplicate = self._warn_if_duplicate_recording(result.cleaned_code)
        self._pending_voice_action = None if is_duplicate else "start"
        self.recorder.manual_start(result.cleaned_code)
        self.scan_input.clear()
        self.focus_scan_input(80)

    def _license_allows_new_recording(self) -> bool:
        if self.license_manager is None:
            return True
        if self.license_manager.can_start_recording(self._current_record_type()):
            return True
        message = "当前授权需要联网验证，暂时不能开始新的录制。"
        self.warning_message.emit(message)
        self.status_message.emit(message)
        return False

    def _apply_license_state(self) -> None:
        if not hasattr(self, "manual_start_button") or self.license_manager is None:
            return
        allowed = self.license_manager.can_start_recording(self._current_record_type())
        self.manual_start_button.setEnabled(bool(self.is_recording or allowed))

    def _on_license_status_changed(self, _status: str) -> None:
        self._apply_license_state()

    def _notify_no_order(self) -> None:
        message = "请先输入或扫描单号。"
        self.warning_message.emit(message)
        self.status_message.emit(message)
        self.show_scan_feedback("no_order")
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
            database = DatabaseManager(self.config_manager.database_path, self.logger)
            duplicate_count = database.count_order_no(order_id, video_dir)
            database.close()
        except Exception:
            self.logger.exception("重复录制检查失败：单号=%s", order_id)
            return False

        if duplicate_count <= 0:
            return False

        message = "检测到该单号已录制过，本次录制不会被阻止，系统会保留多条记录。"
        self.logger.warning("检测到历史重复录制单号：单号=%s，历史记录数=%s", order_id, duplicate_count)
        self.logger.info("重复录制继续录制：单号=%s", order_id)
        self.warning_message.emit(message)
        self.status_message.emit(message)
        if self.voice_prompt.speak_duplicate():
            self.logger.info("重复录制语音已提交播放：单号=%s", order_id)
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
        self.refresh_camera_button.setEnabled(False)
        self.refresh_camera_button.setText("刷新中…")
        self.recorder.restart_camera(report_result=True)
        self.focus_scan_input(100)

    def _on_manual_camera_refresh_finished(self, success: bool, reason: str) -> None:
        self.refresh_camera_button.setText("刷新摄像头")
        self.refresh_camera_button.setEnabled(not self.is_recording)
        if success:
            self.status_message.emit("摄像头已刷新")
        else:
            detail = str(reason or "摄像头不可用").strip()
            self.warning_message.emit(f"摄像头刷新失败：{detail}")
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
            if self.preview_label.pixmap() is None:
                self.preview_label.setText("摄像头不可用")
            was_error = self._camera_error_active
            self._camera_error_active = True
            self._camera_error_reason = message or "摄像头连接异常，请检查 iVCam 或摄像头"
            self.show_recording_alert(self._camera_error_reason, play_voice=not was_error)
        else:
            self._camera_error_active = False
            self._camera_error_reason = ""
            self._last_recording_alert_reason = ""
            self._last_recording_alert_at = 0.0
            self._clear_recording_alert()
            self.refresh_status_card()
        self.logger.info("摄像头状态仅更新持续状态区域，不发送 Toast：%s", message)

    def _set_status_badge(self, recording: bool) -> None:
        if self._camera_error_active:
            self.refresh_status_card()
            return
        if recording:
            detail = f"单号：{self.current_order_id}" if self.current_order_id else ""
            self._set_scan_feedback("recording", "录制中", detail, auto_reset=False)
            return
        self._set_scan_feedback("idle", "等待扫码", "请扫描单号", auto_reset=False)

    def _set_start_time_visible(self, visible: bool) -> None:
        self.start_time_title_label.setVisible(visible)
        self.start_time_label.setVisible(visible)

    def _on_recording_state_changed(self, recording: bool, order_id: str, start_time: str) -> None:
        self.is_recording = recording
        self._set_record_type_enabled(not recording)
        if recording:
            if not self._camera_error_active:
                self._clear_recording_alert()
            self.current_order_id = order_id
            self._set_status_badge(True)
            self._set_start_time_visible(True)
            self.rec_label.setVisible(False)
            self.order_label.setText(order_id)
            self.start_time_label.setText(start_time)
            if self._pending_voice_action == "switch":
                if self.voice_prompt.speak_switch():
                    self.logger.info("切换录制语音已提交播放：单号=%s", order_id)
                self._pending_voice_action = None
            elif self._pending_voice_action == "start":
                if self.voice_prompt.speak_start():
                    self.logger.info("开始录制语音已提交播放：单号=%s", order_id)
                self._pending_voice_action = None
            elif self._pending_voice_action not in (None, "stop"):
                self._pending_voice_action = None
            if self._pending_scan_feedback:
                feedback_event = self._pending_scan_feedback.get("event")
                if feedback_event == "switch":
                    feedback_data = dict(self._pending_scan_feedback)
                    feedback_data["current_order_no"] = order_id
                    self.show_scan_feedback("switch", feedback_data)
                    self._pending_scan_feedback = None
                elif feedback_event == "start":
                    self.show_scan_feedback("start", {"order_no": order_id})
                    self._pending_scan_feedback = None
                elif feedback_event != "stop":
                    self._pending_scan_feedback = None
        else:
            self.current_order_id = ""
            self._set_status_badge(False)
            self._set_start_time_visible(False)
            self.rec_label.setVisible(False)
            self.order_label.setText("-")
            self.start_time_label.setText("-")
            if self._pending_voice_action not in (None, "stop", "switch"):
                self._pending_voice_action = None
            if self._pending_scan_feedback and self._pending_scan_feedback.get("event") not in {"stop", "switch"}:
                self._pending_scan_feedback = None
        self._apply_license_state()
        self.focus_scan_input()

    def _on_duration_changed(self, seconds: int) -> None:
        self.duration_label.setText(format_duration(seconds))

    @staticmethod
    def _is_recording_save_complete_message(message: str) -> bool:
        return (
            message.startswith("视频保存成功")
            or message.startswith("视频已保存并校验通过")
            or message.startswith("视频已保存，但时长过短")
            or message.startswith("视频保存异常")
            or message.startswith("视频文件不存在，校验失败")
            or message.startswith("视频可能保存异常")
        )

    @staticmethod
    def _is_recording_save_failed_message(message: str) -> bool:
        return message.startswith("视频保存失败") or "保存失败" in message

    @staticmethod
    def _is_recording_alert_message(message: str) -> bool:
        text = str(message or "")
        if not text:
            return False
        return any(
            keyword in text
            for keyword in (
                "录制异常",
                "摄像头连接异常",
                "摄像头读取失败",
                "摄像头画面异常",
                "iVCam",
                "视频写入失败",
                "磁盘空间不足",
                "无法开始录制",
                "recording error",
                "camera lost",
                "disk full",
            )
        )

    @staticmethod
    def _recording_alert_reason(message: str) -> str:
        text = str(message or "").strip()
        for prefix in ("录制异常：", "录制异常:", "错误：", "错误:"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        return text or "录制异常"

    def _on_recorder_message(self, message: str) -> None:
        camera_status = is_camera_status_message(message)
        if not camera_status:
            self.status_message.emit(message)
        if not camera_status and self._is_recording_alert_message(message):
            self.show_recording_alert(self._recording_alert_reason(message))
        if self._is_recording_save_complete_message(message):
            self.logger.info("新视频保存后刷新最近录制和今日统计")
            QTimer.singleShot(200, self.refresh_record_summaries)
        if self._pending_voice_action == "stop":
            if self._is_recording_save_complete_message(message):
                if self.voice_prompt.speak_stop():
                    self.logger.info("结束录制语音已提交播放")
                self._pending_voice_action = None
            elif self._is_recording_save_failed_message(message):
                self._pending_voice_action = None
        if self._pending_scan_feedback and self._pending_scan_feedback.get("event") == "stop":
            if self._is_recording_save_complete_message(message):
                self.show_scan_feedback("stop", self._pending_scan_feedback)
                self._pending_scan_feedback = None
            elif self._is_recording_save_failed_message(message):
                self.show_scan_feedback("error", {"message": "录制停止失败，请查看日志"})
                self._pending_scan_feedback = None
        self.focus_scan_input()

    def _on_warning_message(self, message: str) -> None:
        camera_status = is_camera_status_message(message)
        if not camera_status:
            self.warning_message.emit(message)
            self.status_message.emit(message)
        if not camera_status and self._is_recording_alert_message(message):
            self.show_recording_alert(self._recording_alert_reason(message))
        self.focus_scan_input()

    def _on_critical_message(self, message: str) -> None:
        camera_status = is_camera_status_message(message)
        if not camera_status:
            self.critical_message.emit(message)
            self.status_message.emit(message)
        if not camera_status and self._is_recording_alert_message(message):
            self.show_recording_alert(self._recording_alert_reason(message))
        self.focus_scan_input()

    def apply_external_config(self, config: dict) -> None:
        self.config = config
        self.scanner_guard.update_config(self.config)
        self.voice_prompt.update_config(self.config)
        self.recorder.update_config(self.config)
        self.refresh_recent_recordings()
        self.focus_scan_input()

    def apply_basic_config(self, config: dict) -> None:
        if self.is_recording:
            self.logger.info("录制中尝试修改基础配置")
            self.warning_message.emit("录制中不能修改基础配置，请结束录制后再修改。")
            return
        self.apply_external_config(config)
        self.recorder.restart_camera()

    def set_window_maximized(self, _maximized: bool) -> None:
        QTimer.singleShot(0, self._schedule_summary_responsive_update)

    def _schedule_summary_responsive_update(self) -> None:
        if not hasattr(self, "today_summary_card"):
            return
        self.today_summary_card.schedule_responsive_update(self.today_summary_card.contentsRect().size())

    def _update_right_panel_density(self, available_size: QSize) -> None:
        height = max(0, available_size.height())
        if height < 680:
            density = "tight"
            spacing = 6
        elif height < 760:
            density = "compact"
            spacing = 8
        else:
            density = "normal"
            spacing = 12
        if density == self._right_panel_density:
            return
        self._right_panel_density = density
        self.side_panel_layout.setSpacing(spacing)
        top_margin, bottom_margin = self._recent_row_vertical_margins()
        for row_widget in self.findChildren(QWidget, "recentRecordingRow"):
            row_layout = row_widget.layout()
            if row_layout is not None:
                row_layout.setContentsMargins(RECENT_RECORD_CONTENT_LEFT, top_margin, 0, bottom_margin)
        self.side_panel_layout.invalidate()
        QTimer.singleShot(0, self._schedule_summary_responsive_update)

    def _recent_row_vertical_margins(self) -> tuple[int, int]:
        if self._right_panel_density == "tight":
            return 0, 1
        if self._right_panel_density == "compact":
            return 1, 2
        return 2, 4

    def refresh_record_summaries(self) -> None:
        self.refresh_recent_recordings()
        self.refresh_today_summary()

    def refresh_today_summary(self) -> None:
        database: DatabaseManager | None = None
        try:
            today = date.today()
            database = DatabaseManager(self.config_manager.database_path, self.logger)
            counts = database.get_daily_record_counts(today)
            self._today_summary_date = today
            self.today_summary_card.set_counts(
                counts.get("ship_records", 0),
                counts.get("return_records", 0),
            )
        except Exception:
            self.logger.exception("今日录制统计刷新失败")
        finally:
            if database is not None:
                database.close()

    def _schedule_day_rollover(self) -> None:
        now = datetime.now()
        next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime_time.min)
        interval_ms = max(1000, int((next_midnight - now).total_seconds() * 1000) + 1000)
        self._day_rollover_timer.start(interval_ms)

    def _handle_day_rollover(self) -> None:
        self.refresh_today_summary()
        self._schedule_day_rollover()

    def refresh_recent_recordings(self) -> None:
        try:
            database = DatabaseManager(self.config_manager.database_path, self.logger)
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
            empty_label.setObjectName("recentEmptyText")
            empty_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.recent_recordings_layout.addWidget(empty_label)
            return

        for item in rows[:3]:
            path = Path(str(item.get("file_path", "")))
            row_widget = QWidget()
            row_widget.setObjectName("recentRecordingRow")
            row_layout = QHBoxLayout(row_widget)
            top_margin, bottom_margin = self._recent_row_vertical_margins()
            row_layout.setContentsMargins(
                RECENT_RECORD_CONTENT_LEFT,
                top_margin,
                0,
                bottom_margin,
            )
            row_layout.setSpacing(8)
            info_layout = QVBoxLayout()
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(2)

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

            delete_button = QToolButton()
            delete_button.setObjectName("recentDeleteIconButton")
            delete_button.setProperty("actionIcon", "trash")
            delete_button.setCursor(Qt.PointingHandCursor)
            delete_button.setFixedSize(30, 30)
            delete_button.setAccessibleName("删除")
            delete_button.setToolTip("删除")
            self._apply_action_icon(delete_button, "trash")
            delete_button.clicked.connect(
                lambda _checked=False, row_entry=dict(item): self._delete_recent_recording(row_entry)
            )

            info_layout.addWidget(order_label)
            meta_layout.addWidget(record_type_label)
            meta_layout.addWidget(duration_label)
            meta_layout.addStretch(1)
            info_layout.addLayout(meta_layout)
            row_layout.addLayout(info_layout, 1)
            row_layout.addWidget(delete_button, 0, Qt.AlignVCenter)
            self.recent_recordings_layout.addWidget(row_widget)

    def _apply_action_icon(self, button: QToolButton, icon_name: str) -> None:
        resolved_theme = "light"
        if self._theme_manager is not None:
            resolved_theme = self._theme_manager.resolved_theme()
        suffix = "-light" if resolved_theme == "dark" else ""
        icon_path = resource_path(f"app/assets/icons/{icon_name}{suffix}.svg")
        button.setIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon())
        button.setIconSize(QSize(17, 17))

    def _refresh_action_icons(self, _mode: str = "system", _resolved_theme: str = "light") -> None:
        for button in self.findChildren(QToolButton):
            icon_name = button.property("actionIcon")
            if icon_name:
                self._apply_action_icon(button, str(icon_name))

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

    def _delete_recent_recording(self, entry: dict) -> None:
        record_id = self._entry_record_id(entry)
        fallback_path = Path(str(entry.get("file_path") or ""))
        fallback_order_no = str(entry.get("order_no") or "-")
        database: DatabaseManager | None = None
        try:
            database = DatabaseManager(self.config_manager.database_path, self.logger)
            record = database.get_video_by_id(record_id) if record_id else None
            if record is None and str(fallback_path).strip() and str(fallback_path) != ".":
                record = database.get_video_by_path(fallback_path)
            if record is None:
                self.logger.warning(
                    "打包监控页最近录制删除失败：未找到视频记录，record_id=%s, path=%s",
                    record_id or "-",
                    fallback_path,
                )
                self.warning_message.emit("删除失败：未找到视频记录")
                return

            path = Path(str(record.get("file_path") or fallback_path))
            order_no = str(record.get("order_no") or fallback_order_no or "-")
            record_id = self._entry_record_id(record) or record_id
            if self._is_current_recording_path(path):
                self.logger.warning(
                    "打包监控页最近录制拒绝删除正在录制的视频：record_id=%s, order_no=%s, path=%s",
                    record_id or "-",
                    order_no,
                    path,
                )
                self.warning_message.emit("当前视频正在录制中，不能删除")
                return

            file_exists = path.exists()
            dialog = self._confirm_recent_delete(order_no, path, file_exists, record)

            def delete_action() -> tuple[bool, str]:
                if self._is_current_recording_path(path):
                    return False, "当前视频正在录制中，不能删除"
                current_file_exists = path.exists()
                if current_file_exists:
                    try:
                        path.unlink()
                    except PermissionError as exc:
                        self.logger.exception(
                            "最近录制文件删除失败：文件被占用或权限不足，record_id=%s, path=%s",
                            record_id or "-",
                            path,
                        )
                        return False, f"视频删除失败：文件被占用或权限不足（{exc}）"
                    except OSError as exc:
                        self.logger.exception("最近录制文件删除失败：record_id=%s, path=%s", record_id or "-", path)
                        return False, f"视频删除失败：{exc}"
                deleted_record = database.delete_video_record(path)
                if not deleted_record:
                    self.logger.warning(
                        "最近录制 SQLite 记录删除失败：record_id=%s, path=%s, file_deleted=%s",
                        record_id or "-",
                        path,
                        current_file_exists,
                    )
                    return False, "视频删除失败：未找到对应数据库记录"
                return True, ""

            if not dialog.run_action(delete_action):
                self.logger.info(
                    "打包监控页最近录制取消删除：record_id=%s, order_no=%s, path=%s",
                    record_id or "-",
                    order_no,
                    path,
                )
                return

            self.logger.info(
                "打包监控页最近录制删除成功：record_id=%s, order_no=%s, path=%s, file_exists=%s",
                record_id or "-",
                order_no,
                path,
                file_exists,
            )
            self.refresh_recent_recordings()
            self.refresh_today_summary()
            self._refresh_query_tab_after_recent_delete()
            self.status_message.emit("视频已删除")
        except Exception as exc:
            self.logger.exception(
                "打包监控页最近录制删除未知异常：record_id=%s, order_no=%s, path=%s",
                record_id or "-",
                fallback_order_no,
                fallback_path,
            )
            self.critical_message.emit(f"删除失败：{exc}")
        finally:
            if database is not None:
                database.close()
            self.focus_scan_input(80)

    @staticmethod
    def _entry_record_id(entry: dict) -> int:
        try:
            return max(0, int(entry.get("id") or 0))
        except (TypeError, ValueError):
            return 0

    def _is_current_recording_path(self, path: Path) -> bool:
        if not self.is_recording:
            return False
        temp_path = getattr(self.recorder, "_temp_path", None)
        if temp_path is None:
            return False
        try:
            return Path(temp_path).resolve() == path.resolve()
        except OSError:
            return str(temp_path) == str(path)

    def _confirm_recent_delete(
        self,
        order_no: str,
        path: Path,
        file_exists: bool,
        record: dict | None = None,
    ) -> ConfirmActionDialog:
        is_important = self._is_important_record(record or {})
        important_note = str((record or {}).get("important_note") or "").strip()
        uploaded = str((record or {}).get("upload_status") or "") == UPLOAD_DONE
        if file_exists:
            heading = "确定删除这条录制视频吗？"
            description = "删除后，本地记录与本地视频文件将无法恢复。"
            removed = ("本地视频记录", "本地视频文件")
        else:
            heading = "确定移除这条录制记录吗？"
            description = "本地视频文件已不存在，移除后该记录将不再显示。"
            removed = ("本地视频记录",)
        if is_important:
            description += " 该记录已标记为重要，请确认不再需要本地证据。"
        sections: list[tuple[str, tuple[str, ...]]] = [("将删除：", removed)]
        if uploaded:
            sections.append(("不会删除：", ("已上传至网盘的视频文件",)))
        else:
            sections.append(("提示：", ("此视频尚未上传至网盘，删除后无法从网盘恢复",)))
        if important_note:
            sections.append(("重要原因：", (important_note,)))
        return ConfirmActionDialog(
            title="删除最近录制",
            heading=heading,
            description=description,
            info_label="单号",
            info_value=order_no or path.name,
            sections=sections,
            confirm_text="删除本地视频" if file_exists else "移除本地记录",
            destructive=True,
            position_key=DELETE_CONFIRM_POSITION_KEY,
            parent=self,
        )

    @staticmethod
    def _is_important_record(record: dict) -> bool:
        return bool(
            record.get("is_important")
            or str(record.get("important_note") or "").strip()
            or str(record.get("important_at") or "").strip()
        )

    def _refresh_query_tab_after_recent_delete(self) -> None:
        parent = self.parent()
        query_tab = getattr(parent, "query_tab", None)
        if query_tab is None or not hasattr(query_tab, "refresh"):
            return
        try:
            QTimer.singleShot(0, query_tab.refresh)
        except Exception:
            self.logger.exception("最近录制删除后刷新视频查询页失败")

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
