from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.database import DatabaseManager
from app.core.important_reasons import IMPORTANT_REASON_OPTIONS, remark_display_parts
from app.core.video_player import open_video, reveal_in_file_manager
from app.theme.theme_tokens import LIGHT_TOKENS, ThemeTokens
from app.ui.dialog_utils import DialogSizeManager


LOGGER = logging.getLogger(__name__)


CORE_METRICS = (
    ("ship_orders", "发货单数", "发货", "#16A34A", "按单号去重"),
    ("return_orders", "退货单数", "退货", "#D97706", "按单号去重"),
    ("important_orders", "重要单数", "重要", "#DC2626", "售后/拦截/拒收等"),
)
CARD_THEMES = {
    "ship_orders": ("ship", "#16A34A", "#F0FDF4", "#BBF7D0"),
    "return_orders": ("return", "#D97706", "#FFFBEB", "#FDE68A"),
    "important_orders": ("important", "#DC2626", "#FEF2F2", "#FECACA"),
}
REASON_COLORS = {
    "after_sale_dispute": "#14B8A6",
    "merchant_intercept": "#F59E0B",
    "platform_intercept_back": "#60A5FA",
    "user_rejected": "#EF4444",
    "other": "#94A3B8",
}


def _current_theme_tokens() -> ThemeTokens:
    app = QApplication.instance()
    manager = app.property("theme_manager") if app is not None else None
    if manager is not None:
        return manager.current_tokens()
    return LIGHT_TOKENS


class ThemeAwarePaintWidget(QWidget):
    """Cache tokens between paint calls and repaint only when the theme changes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_tokens = _current_theme_tokens()
        app = QApplication.instance()
        manager = app.property("theme_manager") if app is not None else None
        if manager is not None:
            manager.theme_changed.connect(self._refresh_theme)

    def _refresh_theme(self, *_args) -> None:
        self._theme_tokens = _current_theme_tokens()
        self.update()


class StatsDateEdit(QPushButton):
    dateChanged = Signal(QDate)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datePickerButton")
        self._date = QDate.currentDate()
        self._calendar = QCalendarWidget(self)
        self._calendar.setWindowFlags(Qt.Popup)
        self._calendar.clicked.connect(self.setDate)
        self.clicked.connect(self._show_calendar)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(128)
        self.setDate(self._date)

    def date(self) -> QDate:
        return QDate(self._date)

    def setDate(self, value: QDate) -> None:
        if not value.isValid():
            return
        changed = value != self._date
        self._date = QDate(value)
        self.setText(self._date.toString("yyyy-MM-dd"))
        self._calendar.setSelectedDate(self._date)
        if changed:
            self.dateChanged.emit(QDate(self._date))
        if self._calendar.isVisible():
            self._calendar.hide()

    def _show_calendar(self) -> None:
        self._calendar.setSelectedDate(self._date)
        self._calendar.setMinimumWidth(max(self.width(), 260))
        self._calendar.move(self.mapToGlobal(QPoint(0, self.height() + 2)))
        self._calendar.show()
        self._calendar.setFocus()


class MetricCard(QFrame):
    doubleClicked = Signal(str)

    def __init__(self, metric_key: str, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.metric_key = metric_key
        role, *_ = CARD_THEMES.get(metric_key, ("neutral", "#0F172A", "#FFFFFF", "#E2E8F0"))
        self.setObjectName("statsMetricCard")
        self.setProperty("metricRole", role)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("statsCardTitle")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statsCardValue")
        self.value_label.setProperty("metricRole", role)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("statsCardHint")
        self.hint_label.setWordWrap(True)
        self.drill_hint_label = QLabel("双击查看明细")
        self.drill_hint_label.setObjectName("statsCardDrillHint")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.drill_hint_label)

    def set_value(self, value: int, hint: str | None = None) -> None:
        self.value_label.setText(str(value))
        if hint is not None:
            self.hint_label.setText(hint)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.metric_key)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class StatsBarChartWidget(ThemeAwarePaintWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._title = "核心数据概览"
        self._data: list[tuple[str, int, QColor]] = []

    def set_data(self, data: list[tuple[str, int, str]], title: str = "核心数据概览") -> None:
        self._title = title
        self._data = [(label, int(value), QColor(color)) for label, value, color in data]
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tokens = self._theme_tokens
        painter.fillRect(self.rect(), QColor(tokens.surface))
        painter.setPen(QColor(tokens.text_primary))
        title_font = QFont(self.font())
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(16, 24, self._title)

        chart = self.rect().adjusted(48, 44, -24, -38)
        if not self._data:
            painter.setPen(QColor(tokens.text_disabled))
            painter.drawText(chart, Qt.AlignCenter, "暂无统计数据")
            return

        values = [value for _, value, _ in self._data]
        min_value = min(0, min(values))
        max_value = max(0, max(values))
        if min_value == max_value:
            max_value = 1
        span = max(1, max_value - min_value)
        baseline = chart.bottom() - (0 - min_value) / span * chart.height()

        grid_pen = QPen(QColor(tokens.border), 1)
        painter.setPen(grid_pen)
        for index in range(5):
            y = chart.top() + chart.height() * index / 4
            painter.drawLine(chart.left(), int(y), chart.right(), int(y))
        painter.setPen(QPen(QColor(tokens.border_strong), 1))
        painter.drawLine(chart.left(), int(baseline), chart.right(), int(baseline))

        count = len(self._data)
        effective_width = min(float(chart.width()), max(1, count) * 112.0)
        start_x = chart.center().x() - effective_width / 2
        slot = effective_width / max(1, count)
        bar_width = min(56.0, max(28.0, slot * 0.42))
        label_font = QFont(self.font())
        label_font.setPointSize(9)
        painter.setFont(label_font)
        for index, (label, value, color) in enumerate(self._data):
            center_x = start_x + slot * (index + 0.5)
            value_y = chart.bottom() - (value - min_value) / span * chart.height()
            top = min(value_y, baseline)
            height = max(2.0, abs(baseline - value_y))
            rect = QRectF(center_x - bar_width / 2, top, bar_width, height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QColor(tokens.text_primary))
            value_text_y = top - 6 if value >= 0 else top + height + 16
            painter.drawText(QRectF(center_x - 45, value_text_y - 14, 90, 18), Qt.AlignCenter, str(value))
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(QRectF(center_x - 45, chart.bottom() + 8, 90, 22), Qt.AlignCenter, label)


class CompareBarChartWidget(ThemeAwarePaintWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(370)
        self._title = "核心指标对比"
        self._labels: list[str] = []
        self._a_values: list[int] = []
        self._b_values: list[int] = []
        self._a_name = "区间 A"
        self._b_name = "区间 B"

    def set_data(
        self,
        title: str,
        labels: list[str],
        a_values: list[int],
        b_values: list[int],
        a_name: str,
        b_name: str,
    ) -> None:
        self._title = title
        self._labels = labels
        self._a_values = [int(value) for value in a_values]
        self._b_values = [int(value) for value in b_values]
        self._a_name = a_name
        self._b_name = b_name
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tokens = self._theme_tokens
        painter.fillRect(self.rect(), QColor(tokens.surface))

        title_font = QFont(self.font())
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(tokens.text_primary))
        painter.drawText(16, 24, self._title)
        self._draw_legend(painter)

        chart = self.rect().adjusted(52, 50, -28, -42)
        if not self._labels:
            painter.setPen(QColor(tokens.text_disabled))
            painter.drawText(chart, Qt.AlignCenter, "暂无对比数据")
            return

        values = self._a_values + self._b_values
        min_value = min(0, min(values))
        max_value = max(0, max(values))
        if min_value == max_value:
            max_value = 1
        span = max(1, max_value - min_value)
        baseline = chart.bottom() - (0 - min_value) / span * chart.height()

        painter.setPen(QPen(QColor(tokens.border), 1))
        for index in range(5):
            y = chart.top() + chart.height() * index / 4
            painter.drawLine(chart.left(), int(y), chart.right(), int(y))
        painter.setPen(QPen(QColor(tokens.border_strong), 1))
        painter.drawLine(chart.left(), int(baseline), chart.right(), int(baseline))

        label_count = len(self._labels)
        effective_width = min(float(chart.width()), max(1, label_count) * 126.0)
        start_x = chart.center().x() - effective_width / 2
        slot = effective_width / max(1, label_count)
        bar_width = min(28.0, max(16.0, slot * 0.22))
        label_font = QFont(self.font())
        label_font.setPointSize(9)
        painter.setFont(label_font)
        for index, label in enumerate(self._labels):
            center_x = start_x + slot * (index + 0.5)
            for offset, value, color in (
                (-bar_width * 0.62, self._a_values[index], QColor("#14B8A6")),
                (bar_width * 0.62, self._b_values[index], QColor("#60A5FA")),
            ):
                value_y = chart.bottom() - (value - min_value) / span * chart.height()
                top = min(value_y, baseline)
                height = max(2.0, abs(baseline - value_y))
                rect = QRectF(center_x + offset - bar_width / 2, top, bar_width, height)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 5, 5)
                painter.setPen(QColor(tokens.text_primary))
                text_y = top - 5 if value >= 0 else top + height + 14
                painter.drawText(QRectF(center_x + offset - 28, text_y - 12, 56, 16), Qt.AlignCenter, str(value))
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(QRectF(center_x - 56, chart.bottom() + 8, 112, 24), Qt.AlignCenter, label)

    def _draw_legend(self, painter: QPainter) -> None:
        y = 18
        x = self.width() - 220
        for name, color in ((self._a_name, "#14B8A6"), (self._b_name, "#60A5FA")):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, y - 8, 12, 12), 3, 3)
            painter.setPen(QColor(self._theme_tokens.text_secondary))
            painter.drawText(x + 18, y + 2, name)
            x += 92


class ReasonBreakdownWidget(ThemeAwarePaintWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._data = {key: 0 for key, _ in IMPORTANT_REASON_OPTIONS}

    def set_data(self, data: dict[str, int]) -> None:
        self._data = {key: int(data.get(key, 0) or 0) for key, _ in IMPORTANT_REASON_OPTIONS}
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tokens = self._theme_tokens
        painter.fillRect(self.rect(), QColor(tokens.surface))
        painter.setPen(QColor(tokens.text_primary))
        title_font = QFont(self.font())
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(16, 24, "重要原因拆分")

        area = self.rect().adjusted(16, 42, -16, -12)
        if sum(self._data.values()) <= 0:
            painter.setPen(QColor(tokens.text_disabled))
            painter.drawText(area, Qt.AlignCenter, "当前时间范围内暂无重要标记")
            return

        max_value = max(1, max(self._data.values()))
        row_height = max(24, area.height() // len(IMPORTANT_REASON_OPTIONS))
        label_font = QFont(self.font())
        label_font.setPointSize(9)
        painter.setFont(label_font)
        for index, (reason_key, reason_label) in enumerate(IMPORTANT_REASON_OPTIONS):
            value = self._data.get(reason_key, 0)
            y = area.top() + index * row_height
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(area.left(), y + 17, reason_label)
            painter.setPen(QColor(tokens.text_primary))
            painter.drawText(area.left() + 126, y + 17, str(value))
            bar_x = area.left() + 164
            bar_w = max(1, area.right() - bar_x)
            bg_rect = QRectF(bar_x, y + 6, bar_w, 10)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tokens.surface_secondary))
            painter.drawRoundedRect(bg_rect, 5, 5)
            if value > 0:
                fill_rect = QRectF(bar_x, y + 6, bar_w * value / max_value, 10)
                painter.setBrush(QColor(REASON_COLORS.get(reason_key, "#94A3B8")))
                painter.drawRoundedRect(fill_rect, 5, 5)


class StatsDetailDialog(QDialog):
    PAGE_SIZE_OPTIONS = ("10", "20", "50", "100")

    def __init__(
        self,
        database: DatabaseManager,
        metric_key: str,
        metric_title: str,
        start_date: date | None,
        end_date: date | None,
        notice_callback=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statsDetailDialog")
        self.database = database
        self.metric_key = metric_key
        self.metric_title = metric_title
        self.start_date = start_date
        self.end_date = end_date
        self.notice_callback = notice_callback
        self.current_page = 1
        self.page_size = 20
        self.total_records = 0
        self.total_orders = 0
        self.total_pages = 1
        self.setWindowTitle(f"{metric_title}明细")
        DialogSizeManager.apply(self, "statistics_drilldown", parent, "large", (1080, 560))
        self._build_ui()
        self.reload_records(reset_page=True)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "statistics_drilldown")
        super().closeEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel(f"{self.metric_title}明细")
        title.setObjectName("statsDialogTitle")
        subtitle = QLabel(f"统计范围：{self._range_text()}")
        subtitle.setObjectName("statsDialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.summary_label = QLabel("正在加载...")
        self.summary_label.setObjectName("statsSummaryLabel")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["序号", "单号", "录制时间", "分辨率/编码", "大小/时长", "类型", "备注", "文件状态", "场景视频"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(64)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 58)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 176)
        self.table.setColumnWidth(3, 126)
        self.table.setColumnWidth(4, 118)
        self.table.setColumnWidth(5, 76)
        self.table.setColumnWidth(7, 98)
        self.table.setColumnWidth(8, 118)
        self.table.cellDoubleClicked.connect(self._copy_order_no_from_cell)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.notice_label = QLabel("双击单号可复制。")
        self.notice_label.setObjectName("statsSummaryLabel")
        footer.addWidget(self.notice_label)
        footer.addStretch(1)
        footer.addWidget(QLabel("每页"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(self.PAGE_SIZE_OPTIONS)
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.setFixedWidth(76)
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        footer.addWidget(self.page_size_combo)
        self.prev_page_button = QPushButton("<")
        self.prev_page_button.setObjectName("paginationButton")
        self.prev_page_button.clicked.connect(lambda: self._go_to_page(self.current_page - 1))
        self.next_page_button = QPushButton(">")
        self.next_page_button.setObjectName("paginationButton")
        self.next_page_button.clicked.connect(lambda: self._go_to_page(self.current_page + 1))
        self.page_info_label = QLabel("第 1 / 1 页")
        footer.addWidget(self.prev_page_button)
        footer.addWidget(self.page_info_label)
        footer.addWidget(self.next_page_button)
        layout.addLayout(footer)

    def reload_records(self, reset_page: bool = False) -> None:
        if reset_page:
            self.current_page = 1
        self.summary_label.setText("正在加载...")
        counts = self.database.count_packaging_stat_detail(self.metric_key, self.start_date, self.end_date)
        self.total_orders = int(counts.get("order_count", 0))
        self.total_records = int(counts.get("record_count", 0))
        self.total_pages = max(1, (self.total_records + self.page_size - 1) // self.page_size)
        self.current_page = max(1, min(self.current_page, self.total_pages))
        offset = (self.current_page - 1) * self.page_size
        rows = self.database.query_packaging_stat_detail(
            self.metric_key,
            self.start_date,
            self.end_date,
            limit=self.page_size,
            offset=offset,
        )
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        try:
            for row_index, record in enumerate(rows):
                self.table.insertRow(row_index)
                self.table.setRowHeight(row_index, 64)
                self._populate_row(row_index, record, offset)
        finally:
            self.table.setUpdatesEnabled(True)
        self.summary_label.setText(f"共 {self.total_orders} 个单号，{self.total_records} 条视频记录")
        self._update_pagination()

    def _populate_row(self, row: int, record: dict[str, Any], offset: int) -> None:
        path = Path(str(record.get("file_path") or ""))
        remark_text, remark_tooltip, remark, important = remark_display_parts(record)
        values = [
            str(offset + row + 1),
            str(record.get("order_no") or "-"),
            str(record.get("recorded_at") or record.get("created_time") or "-"),
            f"{record.get('resolution') or '-'}\n{record.get('codec') or '-'}",
            f"{record.get('file_size_text') or '-'}\n{self._duration_text(record)}",
            str(record.get("record_type") or "发货"),
            remark_text,
            str(record.get("status") or "正常"),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignCenter if column not in {6} else Qt.AlignLeft | Qt.AlignVCenter)
            if column == 1:
                order_no = str(record.get("order_no") or "")
                item.setData(Qt.UserRole, order_no)
                item.setToolTip(order_no)
            elif column == 6:
                item.setToolTip(remark_tooltip)
                if important:
                    item.setForeground(QColor("#DC2626"))
                elif not remark:
                    item.setForeground(QColor(_current_theme_tokens().text_secondary))
                else:
                    item.setForeground(QColor(_current_theme_tokens().text_primary))
            self.table.setItem(row, column, item)
        self._set_scene_cell(row, path)

    def _set_scene_cell(self, row: int, path: Path) -> None:
        item = QTableWidgetItem("")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(path))
        self.table.setItem(row, 8, item)
        container = QWidget()
        cell_layout = QHBoxLayout(container)
        cell_layout.setContentsMargins(4, 4, 4, 4)
        cell_layout.setSpacing(10)
        cell_layout.setAlignment(Qt.AlignCenter)
        open_button = QPushButton("打开")
        open_button.setObjectName("openSceneLinkButton")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(lambda _checked=False, video_path=path: self._open_video(video_path))
        reveal_button = QPushButton("定位")
        reveal_button.setObjectName("revealSceneLinkButton")
        reveal_button.setCursor(Qt.PointingHandCursor)
        reveal_button.clicked.connect(lambda _checked=False, video_path=path: self._reveal_video(video_path))
        cell_layout.addWidget(open_button)
        cell_layout.addWidget(reveal_button)
        self.table.setCellWidget(row, 8, container)

    def _copy_order_no_from_cell(self, row: int, column: int) -> None:
        if column != 1:
            return
        item = self.table.item(row, column)
        order_no = str(item.data(Qt.UserRole) if item is not None else "").strip()
        if not order_no:
            return
        QApplication.clipboard().setText(order_no)
        self._notice("单号已复制", "success")

    def _open_video(self, path: Path) -> None:
        if not path.exists():
            self._notice("视频文件不存在", "warning")
            return
        try:
            open_video(path)
        except Exception as exc:
            self._notice(f"打开视频失败：{exc}", "error")

    def _reveal_video(self, path: Path) -> None:
        if not path.exists():
            self._notice("视频文件不存在", "warning")
            return
        try:
            reveal_in_file_manager(path)
        except Exception as exc:
            self._notice(f"定位视频失败：{exc}", "error")

    def _on_page_size_changed(self, text: str) -> None:
        try:
            self.page_size = max(1, int(text))
        except ValueError:
            self.page_size = 20
        self.reload_records(reset_page=True)

    def _go_to_page(self, page: int) -> None:
        target = max(1, min(int(page or 1), self.total_pages))
        if target == self.current_page:
            return
        self.current_page = target
        self.reload_records(reset_page=False)

    def _update_pagination(self) -> None:
        self.page_info_label.setText(f"第 {self.current_page} / {self.total_pages} 页")
        self.prev_page_button.setEnabled(self.current_page > 1)
        self.next_page_button.setEnabled(self.current_page < self.total_pages)

    def _notice(self, message: str, level: str = "info") -> None:
        self.notice_label.setText(message)
        if callable(self.notice_callback):
            self.notice_callback(message, level)

    def _range_text(self) -> str:
        if self.start_date is None and self.end_date is None:
            return "全部录制时间"
        return f"{self.start_date.isoformat()} 至 {self.end_date.isoformat()}"

    @staticmethod
    def _duration_text(record: dict[str, Any]) -> str:
        duration_text = str(record.get("duration_text") or "").strip()
        if duration_text:
            return duration_text
        try:
            seconds = int(round(float(record.get("duration_seconds") or 0)))
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0:
            return "-"
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"

class PackagingStatsDialog(QDialog):
    def __init__(
        self,
        database: DatabaseManager,
        notice_callback=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.notice_callback = notice_callback
        self.setObjectName("packagingStatsDialog")
        self.setWindowTitle("打包发货统计")
        DialogSizeManager.apply(self, "statistics", parent, "large", (1040, 560))

        self._single_quick = "today"
        self._compare_chart_mode = "core"
        self._compare_stats: dict[str, Any] | None = None
        self._compare_names = ("今天", "昨天")
        self._detail_dialogs: list[StatsDetailDialog] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        title = QLabel("打包发货统计")
        title.setObjectName("statsDialogTitle")
        subtitle = QLabel("按录制时间 recorded_at 统计")
        subtitle.setObjectName("statsDialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("statsTabs")
        self.tabs.addTab(self._scrollable_page(self._build_single_tab()), "单期统计")
        self.tabs.addTab(self._scrollable_page(self._build_compare_tab()), "对比分析")
        root.addWidget(self.tabs, 1)

        self._apply_single_quick("today", load=False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "statistics")
        super().closeEvent(event)

    def _scrollable_page(self, page: QWidget) -> QScrollArea:
        page.setObjectName("statsTabContent")
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("statsTabScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setWidget(page)
        return scroll_area

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._load_single_stats()
        self._load_compare_stats()

    def _build_single_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(14)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.single_buttons: dict[str, QPushButton] = {}
        for key, text in (("today", "今天"), ("yesterday", "昨天"), ("7days", "最近7天"), ("month", "本月"), ("all", "全部")):
            button = QPushButton(text)
            button.setObjectName("statsQuickButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, mode=key: self._apply_single_quick(mode))
            self.single_buttons[key] = button
            filter_row.addWidget(button)

        filter_row.addSpacing(10)
        filter_row.addWidget(QLabel("开始日期"))
        self.single_start_date = self._date_edit()
        self.single_end_date = self._date_edit()
        self.single_start_date.dateChanged.connect(lambda _date=None: self._mark_single_custom())
        self.single_end_date.dateChanged.connect(lambda _date=None: self._mark_single_custom())
        filter_row.addWidget(self.single_start_date)
        filter_row.addWidget(QLabel("结束日期"))
        filter_row.addWidget(self.single_end_date)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self._load_single_stats)
        filter_row.addWidget(refresh_button)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        overview_section = QFrame()
        overview_section.setObjectName("statsOverviewSection")
        overview_layout = QHBoxLayout(overview_section)
        overview_layout.setContentsMargins(14, 14, 14, 14)
        overview_layout.setSpacing(16)

        card_column = QVBoxLayout()
        card_column.setSpacing(12)
        self.metric_cards: dict[str, MetricCard] = {}
        for key, title, _short, _color, hint in CORE_METRICS:
            card = MetricCard(key, title, hint)
            card.doubleClicked.connect(self._show_metric_detail)
            self.metric_cards[key] = card
            card_column.addWidget(card, 1)
        overview_layout.addLayout(card_column, 36)

        chart_panel = QWidget()
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.single_chart = StatsBarChartWidget()
        chart_layout.addWidget(self.single_chart)
        overview_layout.addWidget(chart_panel, 64)
        layout.addWidget(overview_section, 1)

        reason_card = QFrame()
        reason_card.setObjectName("statsChartCard")
        reason_layout = QVBoxLayout(reason_card)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        self.reason_widget = ReasonBreakdownWidget()
        reason_layout.addWidget(self.reason_widget)
        layout.addWidget(reason_card)
        return page

    def _build_compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(14)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("对比方式"))
        self.compare_mode_combo = QComboBox()
        self.compare_mode_combo.addItem("今天 vs 昨天", "today_yesterday")
        self.compare_mode_combo.addItem("本月 vs 上月", "month_last_month")
        self.compare_mode_combo.addItem("自定义区间对比", "custom")
        self.compare_mode_combo.currentIndexChanged.connect(lambda _index=0: self._sync_compare_custom_visible())
        filter_row.addWidget(self.compare_mode_combo)
        self.compare_start_button = QPushButton("开始对比")
        self.compare_start_button.setObjectName("primaryButton")
        self.compare_start_button.clicked.connect(self._load_compare_stats)
        filter_row.addWidget(self.compare_start_button)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.compare_custom_panel = QWidget()
        custom_layout = QGridLayout(self.compare_custom_panel)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setHorizontalSpacing(8)
        custom_layout.setVerticalSpacing(8)
        self.a_start_date = self._date_edit()
        self.a_end_date = self._date_edit()
        self.b_start_date = self._date_edit()
        self.b_end_date = self._date_edit()
        custom_layout.addWidget(QLabel("区间 A"), 0, 0)
        custom_layout.addWidget(self.a_start_date, 0, 1)
        custom_layout.addWidget(QLabel("至"), 0, 2)
        custom_layout.addWidget(self.a_end_date, 0, 3)
        custom_layout.addWidget(QLabel("区间 B"), 0, 4)
        custom_layout.addWidget(self.b_start_date, 0, 5)
        custom_layout.addWidget(QLabel("至"), 0, 6)
        custom_layout.addWidget(self.b_end_date, 0, 7)
        custom_layout.setColumnStretch(8, 1)
        layout.addWidget(self.compare_custom_panel)

        diff_row = QHBoxLayout()
        diff_row.setSpacing(14)
        self.diff_cards: dict[str, MetricCard] = {}
        for key, title, _short, _color, _hint in CORE_METRICS:
            card = MetricCard(key, title.replace("单数", "变化"), "区间 A - 区间 B")
            card.setCursor(Qt.ArrowCursor)
            self.diff_cards[key] = card
            diff_row.addWidget(card, 1)
        layout.addLayout(diff_row)

        segment_row = QHBoxLayout()
        segment_row.setSpacing(8)
        self.core_segment = QPushButton("核心指标")
        self.core_segment.setObjectName("statsSegmentButton")
        self.core_segment.setCheckable(True)
        self.core_segment.setChecked(True)
        self.reason_segment = QPushButton("重要原因")
        self.reason_segment.setObjectName("statsSegmentButton")
        self.reason_segment.setCheckable(True)
        self.segment_group = QButtonGroup(self)
        self.segment_group.setExclusive(True)
        self.segment_group.addButton(self.core_segment)
        self.segment_group.addButton(self.reason_segment)
        self.core_segment.clicked.connect(lambda _checked=False: self._set_compare_chart_mode("core"))
        self.reason_segment.clicked.connect(lambda _checked=False: self._set_compare_chart_mode("reason"))
        segment_row.addWidget(self.core_segment)
        segment_row.addWidget(self.reason_segment)
        segment_row.addStretch(1)
        layout.addLayout(segment_row)

        compare_card = QFrame()
        compare_card.setObjectName("statsChartCard")
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_chart = CompareBarChartWidget()
        compare_layout.addWidget(self.compare_chart)
        layout.addWidget(compare_card, 1)

        self.compare_summary = QLabel("")
        self.compare_summary.setObjectName("statsSummaryLabel")
        self.compare_summary.setWordWrap(True)
        layout.addWidget(self.compare_summary)

        self._set_custom_ranges_to_today_yesterday()
        self._sync_compare_custom_visible()
        return page

    def _date_edit(self) -> StatsDateEdit:
        return StatsDateEdit(self)

    def _apply_single_quick(self, mode: str, load: bool = True) -> None:
        self._single_quick = mode
        today = date.today()
        start: date | None
        end: date | None
        if mode == "today":
            start = end = today
        elif mode == "yesterday":
            start = end = today - timedelta(days=1)
        elif mode == "7days":
            start = today - timedelta(days=6)
            end = today
        elif mode == "month":
            start = today.replace(day=1)
            end = today
        else:
            start = end = None

        self._sync_single_buttons(mode)
        self.single_start_date.blockSignals(True)
        self.single_end_date.blockSignals(True)
        if start is not None:
            self.single_start_date.setDate(QDate(start.year, start.month, start.day))
        if end is not None:
            self.single_end_date.setDate(QDate(end.year, end.month, end.day))
        self.single_start_date.setEnabled(mode != "all")
        self.single_end_date.setEnabled(mode != "all")
        self.single_start_date.blockSignals(False)
        self.single_end_date.blockSignals(False)
        if load:
            self._load_single_stats()

    def _sync_single_buttons(self, selected: str | None) -> None:
        for key, button in self.single_buttons.items():
            button.setChecked(key == selected)

    def _mark_single_custom(self) -> None:
        if self._single_quick == "custom":
            return
        self._single_quick = "custom"
        self._sync_single_buttons(None)

    def _single_range(self) -> tuple[date | None, date | None]:
        if self._single_quick == "all":
            return None, None
        return self._qdate_to_date(self.single_start_date.date()), self._qdate_to_date(self.single_end_date.date())

    def _load_single_stats(self) -> None:
        start, end = self._single_range()
        try:
            stats = self.database.get_packaging_stats(start, end)
            for key, _title, _short, _color, hint in CORE_METRICS:
                self.metric_cards[key].set_value(int(stats.get(key, 0)), hint)
            self.single_chart.set_data(
                [
                    (short, int(stats.get(key, 0)), color)
                    for key, _title, short, color, _hint in CORE_METRICS
                ]
            )
            self.reason_widget.set_data(stats.get("important_reasons", {}))
        except Exception as exc:
            LOGGER.exception("统计数据加载失败：%s", exc)

    def _show_metric_detail(self, metric_key: str) -> None:
        metric_map = {key: title for key, title, _short, _color, _hint in CORE_METRICS}
        metric_title = metric_map.get(metric_key)
        if not metric_title:
            return
        start, end = self._single_range()
        dialog = StatsDetailDialog(
            self.database,
            metric_key,
            metric_title,
            start,
            end,
            notice_callback=self.notice_callback,
            parent=self,
        )
        self._detail_dialogs.append(dialog)
        dialog.finished.connect(lambda _result=0, item=dialog: self._forget_detail_dialog(item))
        dialog.show()

    def _forget_detail_dialog(self, dialog: StatsDetailDialog) -> None:
        if dialog in self._detail_dialogs:
            self._detail_dialogs.remove(dialog)

    def _sync_compare_custom_visible(self) -> None:
        custom = self.compare_mode_combo.currentData() == "custom"
        self.compare_custom_panel.setVisible(custom)
        if custom:
            self._set_custom_ranges_to_today_yesterday()

    def _set_custom_ranges_to_today_yesterday(self) -> None:
        today = date.today()
        yesterday = today - timedelta(days=1)
        for editor, value in (
            (self.a_start_date, today),
            (self.a_end_date, today),
            (self.b_start_date, yesterday),
            (self.b_end_date, yesterday),
        ):
            editor.setDate(QDate(value.year, value.month, value.day))

    def _compare_ranges(self) -> tuple[tuple[date | None, date | None], tuple[date | None, date | None], tuple[str, str]]:
        today = date.today()
        mode = self.compare_mode_combo.currentData()
        if mode == "month_last_month":
            this_start = today.replace(day=1)
            last_end = this_start - timedelta(days=1)
            last_start = last_end.replace(day=1)
            return (this_start, today), (last_start, last_end), ("本月", "上月")
        if mode == "custom":
            return (
                (self._qdate_to_date(self.a_start_date.date()), self._qdate_to_date(self.a_end_date.date())),
                (self._qdate_to_date(self.b_start_date.date()), self._qdate_to_date(self.b_end_date.date())),
                ("区间 A", "区间 B"),
            )
        return (today, today), (today - timedelta(days=1), today - timedelta(days=1)), ("今天", "昨天")

    def _load_compare_stats(self) -> None:
        range_a, range_b, names = self._compare_ranges()
        try:
            self._compare_stats = self.database.get_packaging_compare_stats(range_a, range_b)
            self._compare_names = names
            diff = self._compare_stats.get("diff", {})
            for key, card in self.diff_cards.items():
                value = int(diff.get(key, 0))
                text = f"+{value}" if value > 0 else str(value)
                card.value_label.setText(text)
                card.value_label.setProperty("diffState", "positive" if value > 0 else "negative" if value < 0 else "neutral")
                card.value_label.style().unpolish(card.value_label)
                card.value_label.style().polish(card.value_label)
            self._refresh_compare_chart()
            self.compare_summary.setText(self._summary_text(diff, names[0], names[1]))
        except Exception as exc:
            LOGGER.exception("对比统计加载失败：%s", exc)

    def _set_compare_chart_mode(self, mode: str) -> None:
        self._compare_chart_mode = mode
        self._refresh_compare_chart()

    def _refresh_compare_chart(self) -> None:
        if not self._compare_stats:
            return
        range_a = self._compare_stats.get("range_a", {})
        range_b = self._compare_stats.get("range_b", {})
        if self._compare_chart_mode == "reason":
            labels = [label for _key, label in IMPORTANT_REASON_OPTIONS]
            a_values = [int(range_a.get("important_reasons", {}).get(key, 0)) for key, _label in IMPORTANT_REASON_OPTIONS]
            b_values = [int(range_b.get("important_reasons", {}).get(key, 0)) for key, _label in IMPORTANT_REASON_OPTIONS]
            self.compare_chart.set_data("重要原因对比", labels, a_values, b_values, self._compare_names[0], self._compare_names[1])
            return
        labels = [short for _key, _title, short, _color, _hint in CORE_METRICS]
        a_values = [int(range_a.get(key, 0)) for key, _title, _short, _color, _hint in CORE_METRICS]
        b_values = [int(range_b.get(key, 0)) for key, _title, _short, _color, _hint in CORE_METRICS]
        self.compare_chart.set_data("核心指标对比", labels, a_values, b_values, self._compare_names[0], self._compare_names[1])

    @staticmethod
    def _summary_text(diff: dict[str, Any], a_name: str, b_name: str) -> str:
        parts: list[str] = []
        for key, label in (("ship_orders", "发货"), ("return_orders", "退货"), ("important_orders", "重要")):
            value = int(diff.get(key, 0) or 0)
            if value > 0:
                parts.append(f"{label}多 {value} 单")
            elif value < 0:
                parts.append(f"{label}少 {abs(value)} 单")
        if not parts:
            return "两个区间核心指标暂无明显变化。"
        return f"{a_name}比{b_name}" + "，".join(parts) + "。"

    def _notice(self, message: str, level: str = "info") -> None:
        if callable(self.notice_callback):
            self.notice_callback(message, level)

    @staticmethod
    def _qdate_to_date(value: QDate) -> date:
        return date(value.year(), value.month(), value.day())
