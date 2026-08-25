from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QIntValidator, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager, normalize_cloud_sync_config
from app.core.database import (
    DatabaseManager,
    MISSING_STATUS,
    NORMAL_STATUS,
    UPLOAD_DONE,
    UPLOAD_FAILED,
    UPLOAD_PENDING,
    UPLOAD_UPLOADING,
)
from app.core.file_hash import calculate_file_hash, normalize_hash_algorithm
from app.core.important_reasons import (
    DEFAULT_IMPORTANT_REASON_TYPE,
    IMPORTANT_REASON_OPTIONS,
    important_reason_text as build_important_reason_text,
    important_note_from_reason,
    is_important_entry as build_is_important_entry,
    normalize_important_reason_type,
    remark_display_parts as build_remark_display_parts,
)
from app.core.netdisk_sync import NetdiskUploadWorker, normalize_netdisk_config
from app.core.video_player import open_folder, open_video, reveal_in_file_manager
from app.ui.confirm_dialog import DELETE_CONFIRM_POSITION_KEY, ConfirmActionDialog, confirm_action
from app.ui.dialog_utils import DialogSizeManager
from app.ui.themed_line_edit import ThemedClearableLineEdit
from app.ui.toast import show_toast
from app.utils.runtime_paths import resource_path
from app.utils.time_utils import format_duration


class ClickableDateEdit(QPushButton):
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
        self.setMinimumWidth(118)
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


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, h_spacing: int = 5, v_spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int):  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # type: ignore[override]
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # type: ignore[override]
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class ImportantMarkDialog(QDialog):
    def __init__(self, order_no: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("importantMarkDialog")
        self.setWindowTitle("标记为重要")
        DialogSizeManager.apply(self, "important_mark", parent, "small", (420, 260))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel("该记录将被标记为重要，删除时会额外提醒。")
        title.setWordWrap(True)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        order_label = QLabel(f"单号：{order_no or '-'}")
        order_label.setObjectName("dialogSubtleLabel")
        layout.addWidget(order_label)

        layout.addWidget(QLabel("重要原因："))
        self.reason_combo = QComboBox()
        for reason_key, reason_label in IMPORTANT_REASON_OPTIONS:
            self.reason_combo.addItem(reason_label, reason_key)
        layout.addWidget(self.reason_combo)

        self.custom_reason_edit = QLineEdit()
        self.custom_reason_edit.setPlaceholderText("请输入其他原因")
        layout.addWidget(self.custom_reason_edit)

        def sync_custom_reason() -> None:
            visible = self.reason_combo.currentData() == "other"
            self.custom_reason_edit.setVisible(visible)

        self.reason_combo.currentIndexChanged.connect(lambda _index=0: sync_custom_reason())
        sync_custom_reason()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.reject)
        confirm_button = QPushButton("确认标记")
        confirm_button.setObjectName("primaryButton")
        confirm_button.clicked.connect(self.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(confirm_button)
        layout.addLayout(buttons)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "important_mark")
        super().closeEvent(event)

    def reason_type(self) -> str:
        return normalize_important_reason_type(self.reason_combo.currentData(), True) or DEFAULT_IMPORTANT_REASON_TYPE

    def custom_reason(self) -> str:
        return self.custom_reason_edit.text().strip() if self.reason_type() == "other" else ""

    def note(self) -> str:
        return important_note_from_reason(self.reason_type(), self.custom_reason())


class VideoQueryLoadWorker(QThread):
    loaded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(
        self,
        request_id: int,
        database: DatabaseManager,
        video_dir: Path,
        filters: dict[str, Any],
        page_size: int,
        current_page: int,
        rebuild: bool,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.database = database
        self.video_dir = Path(video_dir)
        self.filters = dict(filters)
        self.page_size = max(1, int(page_size or 20))
        self.current_page = max(1, int(current_page or 1))
        self.rebuild = bool(rebuild)
        self.logger = logger

    def run(self) -> None:  # type: ignore[override]
        try:
            total_start = time.perf_counter()
            timings: dict[str, float] = {}
            with self.database._lock:
                if self.rebuild:
                    started = time.perf_counter()
                    self.database.refresh_video_directory(self.video_dir)
                    timings["scan_directory"] = (time.perf_counter() - started) * 1000
                else:
                    timings["scan_directory"] = 0.0
                started = time.perf_counter()
                total_count = self.database.count_videos(self.filters)
                timings["count_query"] = (time.perf_counter() - started) * 1000
                total_pages = max(1, (total_count + self.page_size - 1) // self.page_size)
                current_page = max(1, min(self.current_page, total_pages))
                offset = (current_page - 1) * self.page_size
                started = time.perf_counter()
                rows = self.database.query_videos(
                    {
                        **self.filters,
                        "limit": self.page_size,
                        "offset": offset,
                    }
                )
                timings["page_query"] = (time.perf_counter() - started) * 1000
            timings["total"] = (time.perf_counter() - total_start) * 1000
            self.logger.debug(
                "video_query_perf worker request=%s scan_directory=%.2fms count_query=%.2fms page_query=%.2fms total=%.2fms filters=%s",
                self.request_id,
                timings.get("scan_directory", 0.0),
                timings.get("count_query", 0.0),
                timings.get("page_query", 0.0),
                timings.get("total", 0.0),
                self.filters,
            )
            self.loaded.emit(
                self.request_id,
                {
                    "rows": rows,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "current_page": current_page,
                    "offset": offset,
                    "rebuild": self.rebuild,
                    "timings": timings,
                },
            )
        except Exception as exc:
            self.logger.exception("视频查询后台加载失败：dir=%s, rebuild=%s", self.video_dir, self.rebuild)
            self.failed.emit(self.request_id, str(exc))


class VideoHashWorker(QThread):
    succeeded = Signal(str, str, float)
    failed = Signal(str)

    def __init__(self, file_path: str, algorithm: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self.algorithm = normalize_hash_algorithm(algorithm)

    def run(self) -> None:  # type: ignore[override]
        start_time = time.perf_counter()
        try:
            file_hash = calculate_file_hash(self.file_path, self.algorithm)
            self.succeeded.emit(file_hash, self.algorithm, time.perf_counter() - start_time)
        except Exception as exc:
            self.failed.emit(str(exc))


class RecordDetailDialog(QDialog):
    DETAIL_LABEL_WIDTH = 94

    def __init__(
        self,
        record: dict[str, Any],
        duplicates: list[dict[str, Any]],
        parent: QWidget | None = None,
        database: DatabaseManager | None = None,
        config: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
        notice_callback=None,
        record_updated_callback=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("recordDetailDialog")
        self.record = self._normalize_record_data(record)
        self.duplicates = [self._normalize_record_data(item) for item in (duplicates or [])]
        self.database = database
        self.config = config or {}
        self.logger = logger or logging.getLogger(__name__)
        self.notice_callback = notice_callback
        self.record_updated_callback = record_updated_callback
        self.hash_worker: VideoHashWorker | None = None
        self._hash_worker_mode = ""
        self.is_important = False
        self.remark = ""
        self.important_reason_type = ""
        self.important_reason_custom = ""
        self.important_note = ""
        self.record_type = "发货"
        self._refresh_record_state_from_record()
        self.setWindowTitle("单号详情")
        DialogSizeManager.apply(self, "record_detail", parent, "large", (900, 560))
        self._build_ui()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "record_detail")
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.detail_scroll_area = QScrollArea(self)
        self.detail_scroll_area.setObjectName("recordDetailScrollArea")
        self.detail_scroll_area.setWidgetResizable(True)
        self.detail_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName("recordDetailContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)
        self.detail_scroll_area.setWidget(content)
        root_layout.addWidget(self.detail_scroll_area)

        detail_card, detail_layout = self._detail_card("单号详情")

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        order_title = QLabel(self._field("order_no", "-"))
        order_title.setObjectName("detailOrderTitle")
        header_layout.addWidget(order_title, 1)
        file_status = self._field("status", NORMAL_STATUS)
        header_layout.addWidget(self._status_badge(file_status, self._file_status_color(file_status)))
        upload_status = self._field("upload_status", UPLOAD_PENDING)
        header_layout.addWidget(self._status_badge(upload_status, self._upload_status_color(upload_status)))
        detail_layout.addLayout(header_layout)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(26)
        info_grid.setVerticalSpacing(8)
        info_grid.setColumnMinimumWidth(0, self.DETAIL_LABEL_WIDTH)
        info_grid.setColumnMinimumWidth(1, 250)
        info_grid.setColumnMinimumWidth(2, self.DETAIL_LABEL_WIDTH)
        info_grid.setColumnMinimumWidth(3, 220)
        info_grid.setColumnStretch(1, 1)
        info_grid.setColumnStretch(3, 1)
        self._add_basic_info_cell(info_grid, 0, 0, "单号", self._field("order_no", "-"))
        self._add_basic_info_cell(info_grid, 0, 2, "录制时间", self._recording_time(self.record))
        self._add_basic_info_cell(info_grid, 1, 0, "视频大小", self._field("file_size_text", "-"))
        self._add_basic_info_cell(info_grid, 1, 2, "视频时长", self._field("duration_text", "-"))
        self._add_basic_info_cell(info_grid, 2, 0, "文件状态", file_status)
        self._add_basic_info_cell(info_grid, 2, 2, "上传状态", upload_status)
        detail_layout.addLayout(info_grid)

        detail_grid = QGridLayout()
        detail_grid.setHorizontalSpacing(12)
        detail_grid.setVerticalSpacing(10)
        detail_grid.setColumnMinimumWidth(0, self.DETAIL_LABEL_WIDTH)
        detail_grid.setColumnStretch(1, 1)
        row = 0
        upload_error = self._field("upload_error", "")
        if upload_error:
            row = self._add_text_row(detail_grid, row, "失败原因", upload_error)
        row = self._add_copy_row(detail_grid, row, "本地路径", self._field("file_path", "暂无"))
        row = self._add_copy_row(detail_grid, row, "网盘路径", self._field("upload_remote_path", "暂无"))
        row = self._add_record_type_row(detail_grid, row)

        remark_header = QHBoxLayout()
        remark_header.setContentsMargins(0, 0, 0, 0)
        remark_header.setSpacing(10)
        self.important_checkbox = QCheckBox("标记为重要")
        self.important_checkbox.setObjectName("detailImportantCheckbox")
        self.important_checkbox.setChecked(self.is_important)
        self.important_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        remark_header.addWidget(self.important_checkbox, 0, Qt.AlignVCenter)

        self.important_reason_label = QLabel("重要原因：")
        self.important_reason_label.setObjectName("recordDetailLabel")
        self.important_reason_combo = QComboBox()
        self.important_reason_combo.setObjectName("detailImportantReasonCombo")
        for reason_key, reason_label in IMPORTANT_REASON_OPTIONS:
            self.important_reason_combo.addItem(reason_label, reason_key)
        self.important_reason_combo.setFixedSize(168, 30)
        remark_header.addWidget(self.important_reason_label, 0, Qt.AlignVCenter)
        remark_header.addWidget(self.important_reason_combo, 0, Qt.AlignVCenter)
        remark_header.addStretch(1)
        detail_grid.addWidget(self._detail_label("备注"), row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        detail_grid.addLayout(remark_header, row, 1)
        row += 1

        self.important_reason_custom_input = QLineEdit()
        self.important_reason_custom_input.setObjectName("detailCustomReasonInput")
        self.important_reason_custom_input.setPlaceholderText("请输入其他原因")
        self.important_reason_custom_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        custom_palette = self.important_reason_custom_input.palette()
        custom_palette.setColor(QPalette.PlaceholderText, QColor("#94A3B8"))
        self.important_reason_custom_input.setPalette(custom_palette)
        detail_grid.addWidget(self.important_reason_custom_input, row, 1)
        row += 1

        self.remark_edit = QTextEdit()
        self.remark_edit.setObjectName("detailRemarkEdit")
        self.remark_edit.setPlaceholderText("请输入备注")
        self.remark_edit.setPlainText(self.remark)
        self.remark_edit.setMinimumHeight(36)
        self.remark_edit.setMaximumHeight(126)
        self.remark_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.remark_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        placeholder_palette = self.remark_edit.palette()
        placeholder_palette.setColor(QPalette.PlaceholderText, QColor("#94A3B8"))
        self.remark_edit.setPalette(placeholder_palette)
        self.remark_edit.textChanged.connect(self._adjust_remark_editor_height)
        detail_grid.addWidget(self.remark_edit, row, 1)
        row += 1

        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 2, 0, 0)
        save_row.addStretch(1)
        self.save_detail_button = QPushButton("保存修改")
        self.save_detail_button.setObjectName("primaryButton")
        self.save_detail_button.setFixedSize(140, 36)
        self.save_detail_button.clicked.connect(self._save_detail_changes)
        save_row.addWidget(self.save_detail_button)
        save_row.addStretch(1)
        detail_grid.addLayout(save_row, row, 1)
        detail_layout.addLayout(detail_grid)
        layout.addWidget(detail_card)
        self._sync_detail_fields_from_record()
        self.important_checkbox.toggled.connect(lambda _checked: self._sync_detail_importance_controls())
        self.important_reason_combo.currentIndexChanged.connect(lambda _index: self._sync_detail_importance_controls())
        QTimer.singleShot(0, self._adjust_remark_editor_height)

        hash_card, hash_layout = self._detail_card("视频哈希")
        self._build_hash_section(hash_layout)
        layout.addWidget(hash_card)

        duplicate_card, duplicate_layout = self._detail_card("重复录制记录")
        duplicate_table = QTableWidget(0, 7)
        self.duplicate_table = duplicate_table
        duplicate_table.setHorizontalHeaderLabels(["录制时间", "类型", "视频大小", "视频时长", "文件状态", "上传状态", "标记"])
        duplicate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        duplicate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        duplicate_table.verticalHeader().setVisible(False)
        duplicate_header = duplicate_table.horizontalHeader()
        duplicate_header.setStretchLastSection(False)
        duplicate_header.setMinimumSectionSize(64)
        duplicate_header.setSectionResizeMode(0, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(1, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(2, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(3, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(4, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(5, QHeaderView.Fixed)
        duplicate_header.setSectionResizeMode(6, QHeaderView.Stretch)
        duplicate_table.setColumnWidth(0, 176)
        duplicate_table.setColumnWidth(1, 78)
        duplicate_table.setColumnWidth(2, 104)
        duplicate_table.setColumnWidth(3, 104)
        duplicate_table.setColumnWidth(4, 104)
        duplicate_table.setColumnWidth(5, 104)
        duplicate_table.setColumnWidth(6, 120)
        duplicate_table.setAlternatingRowColors(True)
        current_id = self._record_id(self.record)
        for row_index, item in enumerate(self.duplicates or [self.record]):
            duplicate_table.insertRow(row_index)
            values = [
                self._recording_time(item),
                self._text(item.get("record_type"), "发货"),
                self._text(item.get("file_size_text"), "-"),
                self._text(item.get("duration_text"), "-"),
                self._text(item.get("status"), NORMAL_STATUS),
                self._text(item.get("upload_status"), UPLOAD_PENDING),
                "当前记录" if self._record_id(item) == current_id else "",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                cell.setTextAlignment(Qt.AlignCenter)
                if column == 0:
                    cell.setToolTip(value)
                if column == 4:
                    cell.setForeground(QColor(self._file_status_color(value)))
                elif column == 5:
                    cell.setForeground(QColor(self._upload_status_color(value)))
                elif column == 6 and value:
                    cell.setForeground(QColor("#0f766e"))
                duplicate_table.setItem(row_index, column, cell)
        duplicate_table.setMinimumHeight(160)
        duplicate_layout.addWidget(duplicate_table, 1)
        layout.addWidget(duplicate_card)

    def _detail_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("recordDetailCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(14)
        title_label = QLabel(title)
        title_label.setObjectName("detailCardTitle")
        card_layout.addWidget(title_label)
        return card, card_layout

    def _detail_label(self, label: str) -> QLabel:
        name = QLabel(f"{label}：")
        name.setObjectName("recordDetailLabel")
        name.setFixedWidth(self.DETAIL_LABEL_WIDTH)
        name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return name

    def _add_basic_info_cell(self, grid: QGridLayout, row: int, label_column: int, label: str, value: str) -> None:
        name = self._detail_label(label)
        value_label = QLabel(value)
        value_label.setMinimumHeight(26)
        value_label.setWordWrap(False)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value_label.setObjectName("detailValue")
        value_label.setToolTip(value)
        grid.addWidget(name, row, label_column, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(value_label, row, label_column + 1, Qt.AlignLeft | Qt.AlignVCenter)

    def _add_text_row(self, grid: QGridLayout, row: int, label: str, value: str) -> int:
        name = self._detail_label(label)
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setObjectName("detailValue")
        grid.addWidget(name, row, 0, Qt.AlignLeft | Qt.AlignTop)
        grid.addWidget(value_label, row, 1)
        return row + 1

    def _add_record_type_row(self, grid: QGridLayout, row: int) -> int:
        name = self._detail_label("类型")
        self.record_type_combo = QComboBox()
        self.record_type_combo.setObjectName("detailRecordTypeCombo")
        self.record_type_combo.addItems(["发货", "退货"])
        self.record_type_combo.setCurrentText(self._text(self.record.get("record_type"), "发货"))
        self.record_type_combo.setFixedSize(100, 30)

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(self.record_type_combo)
        row_layout.addStretch(1)
        grid.addWidget(name, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addLayout(row_layout, row, 1, Qt.AlignVCenter)
        return row + 1

    def _save_detail_changes(self) -> None:
        if self.database is None:
            self._notice("修改保存失败：数据库未初始化", "error")
            return
        record_id = self._record_id(self.record)
        if record_id <= 0:
            self._notice("修改保存失败：未找到视频记录", "error")
            return
        record_type = self.record_type_combo.currentText().strip()
        if record_type not in {"发货", "退货"}:
            self._notice("修改保存失败：类型只能选择发货或退货", "error")
            return
        remark = self.remark_edit.toPlainText().strip()[:500]
        important_checked = self.important_checkbox.isChecked()
        reason_type = ""
        reason_custom = ""
        if important_checked:
            reason_type = (
                normalize_important_reason_type(self.important_reason_combo.currentData(), True)
                or DEFAULT_IMPORTANT_REASON_TYPE
            )
            reason_custom = self.important_reason_custom_input.text().strip()[:500] if reason_type == "other" else ""
        try:
            updated_rows = self.database.update_video_detail_fields(
                record_id,
                record_type,
                remark,
                important_checked,
                reason_type,
                reason_custom,
            )
            if updated_rows != 1:
                self._notice("修改保存失败：未找到对应记录", "error")
                return
            self._reload_current_record()
            self._sync_detail_fields_from_record()
            self._refresh_duplicate_current_type()
            if self.record_updated_callback:
                self.record_updated_callback()
            self._notice("修改已保存", "success")
        except Exception as exc:
            self.logger.exception("详情页保存修改失败：record_id=%s, record_type=%s", record_id, record_type)
            self._notice(f"修改保存失败：{exc}", "error")

    def _sync_detail_fields_from_record(self) -> None:
        self._refresh_record_state_from_record()
        if hasattr(self, "record_type_combo"):
            self.record_type_combo.blockSignals(True)
            self.record_type_combo.setCurrentText(self.record_type)
            self.record_type_combo.blockSignals(False)
        if hasattr(self, "remark_edit"):
            self.remark_edit.blockSignals(True)
            self.remark_edit.setPlainText(self.remark)
            self.remark_edit.blockSignals(False)
            QTimer.singleShot(0, self._adjust_remark_editor_height)
        if hasattr(self, "important_checkbox"):
            self.important_checkbox.blockSignals(True)
            self.important_checkbox.setChecked(self.is_important)
            self.important_checkbox.blockSignals(False)
        reason_type = self.important_reason_type
        reason_custom = self.important_reason_custom
        if self.is_important and not reason_type and self.important_note:
            reason_type = "other"
            reason_custom = reason_custom or self.important_note
        reason_type = normalize_important_reason_type(reason_type, self.is_important) or DEFAULT_IMPORTANT_REASON_TYPE
        if hasattr(self, "important_reason_combo"):
            self.important_reason_combo.blockSignals(True)
            index = self.important_reason_combo.findData(reason_type)
            self.important_reason_combo.setCurrentIndex(index if index >= 0 else 0)
            self.important_reason_combo.blockSignals(False)
        if hasattr(self, "important_reason_custom_input"):
            self.important_reason_custom_input.setText(reason_custom if reason_type == "other" else "")
        self._sync_detail_importance_controls()

    def _sync_detail_importance_controls(self) -> None:
        important = self.important_checkbox.isChecked()
        reason_type = self.important_reason_combo.currentData()
        self.important_reason_label.setVisible(important)
        self.important_reason_combo.setVisible(important)
        self.important_reason_label.setEnabled(important)
        self.important_reason_combo.setEnabled(important)
        show_custom = important and reason_type == "other"
        self.important_reason_custom_input.setVisible(show_custom)
        self.important_reason_custom_input.setEnabled(show_custom)

    def _adjust_remark_editor_height(self) -> None:
        editor = getattr(self, "remark_edit", None)
        if editor is None:
            return
        document = editor.document()
        viewport_width = max(1, editor.viewport().width())
        document.setTextWidth(viewport_width)
        content_height = int(document.size().height()) + 14
        min_height = 36
        max_height = 126
        target_height = max(min_height, min(max_height, content_height))
        if editor.height() != target_height:
            editor.setFixedHeight(target_height)
        editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if content_height > max_height else Qt.ScrollBarAlwaysOff
        )

    def _refresh_record_state_from_record(self) -> None:
        self.record = self._normalize_record_data(self.record)
        self.is_important = self._is_important(self.record)
        self.remark = self._text(self._entry_value(self.record, "remark"), "")
        self.important_reason_type = self._text(self._entry_value(self.record, "important_reason_type"), "")
        self.important_reason_custom = self._text(self._entry_value(self.record, "important_reason_custom"), "")
        self.important_note = self._text(self._entry_value(self.record, "important_note"), "")
        self.record_type = self._normalize_record_type_text(self._entry_value(self.record, "record_type"))
        self.record["remark"] = self.remark
        self.record["important_reason_type"] = self.important_reason_type
        self.record["important_reason_custom"] = self.important_reason_custom
        self.record["important_note"] = self.important_note
        self.record["is_important"] = 1 if self.is_important else 0
        self.record["record_type"] = self.record_type

    def _refresh_duplicate_current_type(self) -> None:
        table = getattr(self, "duplicate_table", None)
        if table is None:
            return
        record_id = self._record_id(self.record)
        record_type = self._text(self.record.get("record_type"), "发货")
        for row_index, item in enumerate(self.duplicates):
            if self._record_id(item) == record_id:
                item["record_type"] = record_type
                cell = table.item(row_index, 1)
                if cell is not None:
                    cell.setText(record_type)
                break

    def _add_copy_row(self, grid: QGridLayout, row: int, label: str, value: str) -> int:
        name = self._detail_label(label)
        line = QLineEdit(value)
        line.setObjectName("detailPathInput")
        line.setReadOnly(True)
        button = QPushButton("复制")
        button.setObjectName("secondaryButton")
        button.setFixedWidth(58)
        button.clicked.connect(lambda _checked=False, text=value: QApplication.clipboard().setText(text))
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(line, 1)
        row_layout.addWidget(button)
        grid.addWidget(name, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addLayout(row_layout, row, 1)
        return row + 1

    def _build_hash_section(self, layout: QVBoxLayout) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, self.DETAIL_LABEL_WIDTH)
        grid.setColumnStretch(1, 1)

        self.hash_enabled_value = QLabel()
        self.hash_algorithm_value = QLabel()
        self.hash_generated_value = QLabel()
        self.hash_verify_value = QLabel()
        for label in (
            self.hash_enabled_value,
            self.hash_algorithm_value,
            self.hash_generated_value,
            self.hash_verify_value,
        ):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        row = 0
        row = self._add_hash_label_row(grid, row, "哈希校验", self.hash_enabled_value)
        row = self._add_hash_label_row(grid, row, "哈希算法", self.hash_algorithm_value)

        hash_name = self._detail_label("视频哈希")
        self.hash_value_edit = QLineEdit()
        self.hash_value_edit.setReadOnly(True)
        self.hash_value_edit.setPlaceholderText("暂未生成")
        self.hash_copy_button = QPushButton("复制")
        self.hash_copy_button.setObjectName("secondaryButton")
        self.hash_copy_button.setFixedWidth(58)
        self.hash_copy_button.clicked.connect(self._copy_hash_value)
        hash_row = QHBoxLayout()
        hash_row.setContentsMargins(0, 0, 0, 0)
        hash_row.setSpacing(8)
        hash_row.addWidget(self.hash_value_edit, 1)
        hash_row.addWidget(self.hash_copy_button)
        grid.addWidget(hash_name, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addLayout(hash_row, row, 1)
        row += 1

        row = self._add_hash_label_row(grid, row, "生成时间", self.hash_generated_value)
        row = self._add_hash_label_row(grid, row, "校验状态", self.hash_verify_value)
        layout.addLayout(grid)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.hash_status_label = QLabel("")
        self.hash_status_label.setObjectName("detailHashStatus")
        self.hash_generate_button = QPushButton("生成校验码")
        self.hash_generate_button.setObjectName("secondaryButton")
        self.hash_generate_button.clicked.connect(self._start_hash_generation)
        self.hash_verify_button = QPushButton("校验文件")
        self.hash_verify_button.setObjectName("secondaryButton")
        self.hash_verify_button.clicked.connect(self._start_hash_verify)
        action_row.addWidget(self.hash_status_label, 1)
        action_row.addWidget(self.hash_generate_button)
        action_row.addWidget(self.hash_verify_button)
        layout.addLayout(action_row)
        self._refresh_hash_section()

    def _add_hash_label_row(self, grid: QGridLayout, row: int, label: str, value_widget: QLabel) -> int:
        name = self._detail_label(label)
        value_widget.setObjectName("detailHashValue")
        grid.addWidget(name, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(value_widget, row, 1, Qt.AlignLeft | Qt.AlignVCenter)
        return row + 1

    def _current_hash_config(self) -> tuple[bool, str]:
        hash_config = self.config.get("hash_check", {})
        if not isinstance(hash_config, dict):
            hash_config = {}
        enabled = bool(hash_config.get("enabled", True))
        algorithm = normalize_hash_algorithm(str(hash_config.get("algorithm") or "SHA256"))
        return enabled, algorithm

    def _refresh_hash_section(self) -> None:
        enabled, configured_algorithm = self._current_hash_config()
        hash_value = self._text(self.record.get("file_hash"), "")
        algorithm = self._text(self.record.get("hash_algorithm"), configured_algorithm)
        generated_at = self._text(self.record.get("hash_generated_at"), "暂无")
        verify_status = self._text(self.record.get("hash_verify_status"), "未校验")
        verify_at = self._text(self.record.get("hash_verify_at"), "")

        self.hash_enabled_value.setText("已开启" if enabled else "已关闭")
        self.hash_algorithm_value.setText(algorithm or configured_algorithm)
        self.hash_value_edit.setText(hash_value or ("暂未生成" if enabled else "哈希校验未开启"))
        self.hash_copy_button.setEnabled(bool(hash_value))
        self.hash_generated_value.setText(generated_at)
        verify_text = verify_status
        if verify_at:
            verify_text = f"{verify_status}（{verify_at}）"
        self.hash_verify_value.setText(verify_text)
        verify_state = "error" if verify_status in {"不一致", "文件不存在"} else "success" if verify_status == "通过" else "neutral"
        self.hash_verify_value.setObjectName("detailHashVerify")
        self.hash_verify_value.setProperty("state", verify_state)
        self.hash_verify_value.style().unpolish(self.hash_verify_value)
        self.hash_verify_value.style().polish(self.hash_verify_value)
        self.hash_generate_button.setText("重新生成校验码" if hash_value else "生成校验码")
        self.hash_status_label.setText("" if enabled else "哈希校验未开启，可手动生成或校验。")

    def _copy_hash_value(self) -> None:
        hash_value = self._text(self.record.get("file_hash"), "")
        if not hash_value:
            self._notice("当前视频尚未生成校验码", "warning")
            return
        QApplication.clipboard().setText(hash_value)
        self._notice("视频哈希已复制", "success")

    def _record_file_path(self) -> Path:
        return Path(str(self.record.get("file_path") or ""))

    def _start_hash_generation(self) -> None:
        if self.hash_worker is not None and self.hash_worker.isRunning():
            return
        if self.database is None:
            self._notice("无法生成校验码：数据库未初始化", "error")
            return
        record_id = self._record_id(self.record)
        if record_id <= 0:
            self._notice("无法生成校验码：未找到视频记录", "error")
            return
        path = self._record_file_path()
        if not path.exists() or not path.is_file():
            self._notice("视频文件不存在，无法生成校验码", "error")
            return
        try:
            if path.stat().st_size <= 0:
                self._notice("视频文件大小为 0，无法生成校验码", "error")
                return
        except OSError as exc:
            self._notice(f"无法读取视频文件：{exc}", "error")
            return

        if self._text(self.record.get("file_hash"), ""):
            if not confirm_action(
                self,
                title="重新生成校验码",
                heading="重新生成校验码会覆盖当前哈希记录，是否继续？",
                confirm_text="继续生成",
                destructive=True,
            ):
                return

        _enabled, algorithm = self._current_hash_config()
        self._begin_hash_worker("generate", path, algorithm)

    def _start_hash_verify(self) -> None:
        if self.hash_worker is not None and self.hash_worker.isRunning():
            return
        if self.database is None:
            self._notice("无法校验文件：数据库未初始化", "error")
            return
        record_id = self._record_id(self.record)
        stored_hash = self._text(self.record.get("file_hash"), "")
        if record_id <= 0:
            self._notice("无法校验文件：未找到视频记录", "error")
            return
        if not stored_hash:
            self._notice("当前视频尚未生成校验码", "warning")
            return
        path = self._record_file_path()
        if not path.exists() or not path.is_file():
            self.database.update_video_hash_verify_status(record_id, "文件不存在")
            self._reload_current_record()
            self._refresh_hash_section()
            self._notice("视频文件不存在，无法校验", "error")
            return
        algorithm = normalize_hash_algorithm(str(self.record.get("hash_algorithm") or self._current_hash_config()[1]))
        self._begin_hash_worker("verify", path, algorithm)

    def _begin_hash_worker(self, mode: str, path: Path, algorithm: str) -> None:
        self._hash_worker_mode = mode
        self._set_hash_buttons_enabled(False)
        self.hash_status_label.setText("正在生成视频校验码..." if mode == "generate" else "正在校验视频文件...")
        self.hash_worker = VideoHashWorker(str(path), algorithm, self)
        self.hash_worker.succeeded.connect(self._on_hash_worker_succeeded)
        self.hash_worker.failed.connect(self._on_hash_worker_failed)
        self.hash_worker.finished.connect(self._finish_hash_worker)
        self.hash_worker.start()

    def _on_hash_worker_succeeded(self, file_hash: str, algorithm: str, cost_time: float) -> None:
        if self.database is None:
            return
        record_id = self._record_id(self.record)
        try:
            if self._hash_worker_mode == "verify":
                stored_hash = self._text(self.record.get("file_hash"), "")
                status = "通过" if stored_hash.lower() == file_hash.lower() else "不一致"
                self.database.update_video_hash_verify_status(record_id, status)
                self.logger.info(
                    "手动校验视频哈希：record_id=%s, result=%s, cost=%.2fs, hash_prefix=%s",
                    record_id,
                    status,
                    cost_time,
                    file_hash[:12],
                )
                if status == "通过":
                    self._notice("文件校验通过，视频未发生变化", "success")
                else:
                    self._notice("文件校验不一致，视频可能被修改", "error")
            else:
                updated_rows = self.database.update_video_hash(record_id, file_hash, algorithm)
                if updated_rows != 1:
                    self._notice("校验码生成失败：未找到视频记录", "error")
                    return
                self.logger.info(
                    "手动生成视频哈希：record_id=%s, algorithm=%s, cost=%.2fs, hash_prefix=%s",
                    record_id,
                    algorithm,
                    cost_time,
                    file_hash[:12],
                )
                self._notice("视频校验码已生成", "success")
            self._reload_current_record()
            self._refresh_hash_section()
            if self.record_updated_callback:
                self.record_updated_callback()
        except Exception as exc:
            self.logger.exception("视频哈希结果写入失败：record_id=%s, mode=%s", record_id, self._hash_worker_mode)
            self._notice(f"视频哈希写入失败：{exc}", "error")

    def _on_hash_worker_failed(self, error: str) -> None:
        self.logger.warning("视频哈希计算失败：record_id=%s, error=%s", self._record_id(self.record), error)
        self._notice(f"视频校验码处理失败：{error}", "error")

    def _finish_hash_worker(self) -> None:
        self._set_hash_buttons_enabled(True)
        if self.hash_worker is not None:
            self.hash_worker.deleteLater()
        self.hash_worker = None
        self._hash_worker_mode = ""

    def _set_hash_buttons_enabled(self, enabled: bool) -> None:
        self.hash_generate_button.setEnabled(enabled)
        self.hash_verify_button.setEnabled(enabled)
        self.hash_copy_button.setEnabled(enabled and bool(self._text(self.record.get("file_hash"), "")))

    def _reload_current_record(self) -> None:
        if self.database is None:
            return
        record_id = self._record_id(self.record)
        latest = self.database.get_video_by_id(record_id) if record_id else None
        if latest:
            self.record = self._normalize_record_data(latest)
            for index, item in enumerate(self.duplicates):
                if self._record_id(item) == record_id:
                    self.duplicates[index] = self._normalize_record_data(latest)
                    break
            self._refresh_record_state_from_record()

    def _notice(self, message: str, level: str = "info") -> None:
        if self.notice_callback:
            try:
                self.notice_callback(message, level)
                return
            except Exception:
                self.logger.exception("详情弹窗提示失败：%s", message)
        show_toast(self, message, level, 3500 if level == "error" else 2400, self.logger)

    def _status_badge(self, text: str, color: str) -> QLabel:
        badge = QLabel(text)
        badge.setObjectName("detailStatusBadge")
        badge.setAlignment(Qt.AlignCenter)
        tone = "error" if color.lower() in {"#dc2626", "#ef4444", "#b91c1c"} else "warning" if color.lower() in {"#d97706", "#f59e0b", "#b45309"} else "success"
        badge.setProperty("tone", tone)
        return badge

    def _field(self, key: str, default: str = "") -> str:
        return self._text(self._entry_value(self.record, key), default)

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        text = str(value or "").strip()
        return text if text else default

    @staticmethod
    def _entry_value(entry: Any, key: str, default: Any = None) -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        try:
            return entry[key]
        except (KeyError, IndexError, TypeError):
            return default

    @classmethod
    def _normalize_record_data(cls, entry: Any) -> dict[str, Any]:
        try:
            data = dict(entry or {})
        except (TypeError, ValueError):
            data = {}
        defaults: dict[str, Any] = {
            "id": 0,
            "order_no": "",
            "recorded_at": "",
            "created_time": "",
            "record_type": "发货",
            "file_path": "",
            "file_name": "",
            "file_size_text": "",
            "duration_text": "",
            "status": NORMAL_STATUS,
            "upload_status": UPLOAD_PENDING,
            "upload_remote_path": "",
            "upload_error": "",
            "remark": "",
            "is_important": 0,
            "important_reason_type": "",
            "important_reason_custom": "",
            "important_note": "",
            "important_at": "",
            "file_hash": "",
            "hash_algorithm": "",
            "hash_generated_at": "",
            "hash_verify_status": "",
            "hash_verify_at": "",
        }
        for key, value in defaults.items():
            data.setdefault(key, value)
        data["record_type"] = cls._normalize_record_type_text(data.get("record_type"))
        return data

    @staticmethod
    def _normalize_record_type_text(value: Any) -> str:
        text = str(value or "").strip()
        return text if text in {"发货", "退货"} else "发货"

    @staticmethod
    def _is_important(record: Any) -> bool:
        return bool(
            RecordDetailDialog._entry_value(record, "is_important", 0)
            or str(RecordDetailDialog._entry_value(record, "important_reason_type", "") or "").strip()
            or str(RecordDetailDialog._entry_value(record, "important_reason_custom", "") or "").strip()
            or str(RecordDetailDialog._entry_value(record, "important_note", "") or "").strip()
            or str(RecordDetailDialog._entry_value(record, "important_at", "") or "").strip()
        )

    @staticmethod
    def _record_id(entry: dict[str, Any]) -> int:
        try:
            return int(RecordDetailDialog._entry_value(entry, "id", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _recording_time(cls, entry: dict[str, Any]) -> str:
        return cls._text(cls._entry_value(entry, "recorded_at") or cls._entry_value(entry, "created_time"), "-")

    @staticmethod
    def _file_status_color(status: str) -> str:
        if status == NORMAL_STATUS:
            return "#047857"
        if status == MISSING_STATUS:
            return "#dc2626"
        return "#dc2626"

    @staticmethod
    def _upload_status_color(status: str) -> str:
        if status == UPLOAD_DONE:
            return "#047857"
        if status == UPLOAD_FAILED:
            return "#dc2626"
        if status == UPLOAD_UPLOADING:
            return "#2563eb"
        return "#d97706"


class DuplicateRecordsDialog(QDialog):
    def __init__(
        self,
        database: DatabaseManager,
        order_no: str,
        query_dir: Path,
        current_record_id: int,
        notice_callback,
        changed_callback,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("duplicateRecordsDialog")
        self.database = database
        self.order_no = str(order_no or "").strip()
        self.query_dir = Path(query_dir)
        self.current_record_id = int(current_record_id or 0)
        self.notice_callback = notice_callback
        self.changed_callback = changed_callback
        self.logger = logger
        self.records: list[dict[str, Any]] = []
        self.checkboxes: dict[int, QCheckBox] = {}
        self.select_all_checkbox: QCheckBox | None = None
        self._all_checked = False
        self.setWindowTitle("重复单号记录")
        DialogSizeManager.apply(self, "duplicate_records", parent, "large", (900, 560))
        self._build_ui()
        self.reload_records()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        DialogSizeManager.remember(self, "duplicate_records")
        super().closeEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title = QLabel("重复单号记录")
        title.setObjectName("duplicateDialogTitle")
        title_block.addWidget(title)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("duplicateDialogSubtitle")
        title_block.addWidget(self.subtitle_label)
        header_layout.addLayout(title_block, 1)

        self.batch_delete_button = QPushButton("批量删除")
        self.batch_delete_button.setObjectName("primaryButton")
        self.batch_delete_button.setFixedSize(108, 36)
        self.batch_delete_button.setCursor(Qt.PointingHandCursor)
        self.batch_delete_button.setEnabled(False)
        self.batch_delete_button.clicked.connect(self._delete_selected_records)
        header_layout.addWidget(self.batch_delete_button, 0, Qt.AlignRight | Qt.AlignBottom)
        layout.addLayout(header_layout)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["", "序号", "录制时间", "类型", "视频大小", "视频时长", "文件状态", "上传状态", "操作"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.verticalHeader().setMinimumSectionSize(46)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.sectionClicked.connect(self._on_header_clicked)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 96)
        self.table.setColumnWidth(3, 76)
        self.table.setColumnWidth(6, 98)
        self.table.setColumnWidth(7, 98)
        self.table.setColumnWidth(8, 128)
        self._setup_select_all_checkbox(header)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.selected_label = QLabel("已选择 0 条")
        self.selected_label.setObjectName("duplicateSelectedLabel")
        footer.addWidget(self.selected_label)
        footer.addStretch(1)
        layout.addLayout(footer)

    def reload_records(self) -> None:
        self.records = self.database.get_videos_by_order_no(self.order_no, self.query_dir)
        self.subtitle_label.setText(f"单号：{self.order_no or '-'}    共 {len(self.records)} 条录制记录")
        self.checkboxes.clear()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        try:
            for row_index, record in enumerate(self.records):
                self.table.insertRow(row_index)
                self.table.setRowHeight(row_index, 50)
                self._populate_row(row_index, record)
        finally:
            self.table.setUpdatesEnabled(True)
        self._all_checked = False
        self._sync_select_all_checkbox(0)
        QTimer.singleShot(0, self._position_select_all_checkbox)
        self._update_selected_count()

    def _populate_row(self, row: int, record: dict[str, Any]) -> None:
        record_id = self._record_id(record)
        checkbox = QCheckBox()
        checkbox.setCursor(Qt.PointingHandCursor)
        checkbox.setFixedSize(18, 18)
        checkbox.stateChanged.connect(lambda _state: self._update_selected_count())
        checkbox.setObjectName("duplicateRowCheckbox")
        self.checkboxes[record_id] = checkbox
        checkbox_container = QWidget()
        checkbox_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        checkbox_container.setObjectName("duplicateCheckboxHost")
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox_layout.addWidget(checkbox)
        self.table.setCellWidget(row, 0, checkbox_container)

        sequence = int(record.get("duplicate_sequence") or row + 1)
        sequence_text = f"第 {sequence} 次"
        if record_id == self.current_record_id:
            sequence_text += "（当前）"
        values = [
            sequence_text,
            self._recording_time(record),
            self._text(record.get("record_type"), "发货"),
            self._text(record.get("file_size_text"), "-"),
            self._text(record.get("duration_text"), "-"),
            self._text(record.get("status"), NORMAL_STATUS),
            self._text(record.get("upload_status"), UPLOAD_PENDING),
        ]
        for column_offset, value in enumerate(values, start=1):
            cell = QTableWidgetItem(value)
            cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            cell.setTextAlignment(Qt.AlignCenter)
            if column_offset == 1 and record_id == self.current_record_id:
                cell.setForeground(QColor("#0f766e"))
            elif column_offset == 6:
                cell.setForeground(QColor(RecordDetailDialog._file_status_color(value)))
            elif column_offset == 7:
                cell.setForeground(QColor(RecordDetailDialog._upload_status_color(value)))
                upload_error = str(record.get("upload_error") or "").strip()
                if upload_error:
                    cell.setToolTip(upload_error)
            self.table.setItem(row, column_offset, cell)

        path = Path(str(record.get("file_path") or ""))
        open_button = QPushButton("打开")
        open_button.setObjectName("tableUploadButton")
        open_button.setFixedSize(48, 28)
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setEnabled(path.exists())
        open_button.setToolTip("打开视频" if path.exists() else "视频文件不存在")
        open_button.clicked.connect(lambda _checked=False, rid=record_id: self._open_record_video(rid))
        delete_button = QPushButton("删除")
        delete_button.setObjectName("tableDangerButton")
        delete_button.setFixedSize(48, 28)
        delete_button.clicked.connect(lambda _checked=False, rid=record_id: self._delete_single_record(rid))
        delete_container = QWidget()
        delete_layout = QHBoxLayout(delete_container)
        delete_layout.setContentsMargins(4, 4, 4, 4)
        delete_layout.setSpacing(6)
        delete_layout.setAlignment(Qt.AlignCenter)
        delete_layout.addWidget(open_button)
        delete_layout.addWidget(delete_button)
        self.table.setCellWidget(row, 8, delete_container)

    def _setup_select_all_checkbox(self, header: QHeaderView) -> None:
        self.select_all_checkbox = QCheckBox(header)
        self.select_all_checkbox.setCursor(Qt.PointingHandCursor)
        self.select_all_checkbox.setFixedSize(18, 18)
        self.select_all_checkbox.setObjectName("duplicateRowCheckbox")
        self.select_all_checkbox.stateChanged.connect(self._on_select_all_checkbox_changed)
        header.sectionResized.connect(lambda *_args: self._position_select_all_checkbox())
        header.geometriesChanged.connect(self._position_select_all_checkbox)
        QTimer.singleShot(0, self._position_select_all_checkbox)

    def _position_select_all_checkbox(self) -> None:
        if self.select_all_checkbox is None:
            return
        header = self.table.horizontalHeader()
        section_x = header.sectionViewportPosition(0)
        section_width = header.sectionSize(0)
        x = section_x + max(0, (section_width - self.select_all_checkbox.width()) // 2)
        y = max(0, (header.height() - self.select_all_checkbox.height()) // 2)
        self.select_all_checkbox.move(x, y)
        self.select_all_checkbox.raise_()

    def _on_select_all_checkbox_changed(self, state: int) -> None:
        self._set_all_checked(state == Qt.CheckState.Checked.value)
        self._update_selected_count()

    def _on_header_clicked(self, section: int) -> None:
        if section != 0:
            return
        selected = len(self._selected_records())
        self._set_all_checked(selected < len(self.checkboxes))
        self._update_selected_count()

    def _set_all_checked(self, checked: bool) -> None:
        self._all_checked = bool(checked)
        for checkbox in self.checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(self._all_checked)
            checkbox.blockSignals(False)
        self._sync_select_all_checkbox(len(self.checkboxes) if self._all_checked else 0)

    def _update_selected_count(self) -> None:
        selected = len(self._selected_records())
        self.selected_label.setText(f"已选择 {selected} 条")
        self.batch_delete_button.setEnabled(selected > 0)
        total = len(self.checkboxes)
        if selected == total and total > 0:
            self._all_checked = True
        else:
            self._all_checked = False
        self._sync_select_all_checkbox(selected)

    def _sync_select_all_checkbox(self, selected: int) -> None:
        if self.select_all_checkbox is None:
            return
        total = len(self.checkboxes)
        self.select_all_checkbox.blockSignals(True)
        self.select_all_checkbox.setChecked(total > 0 and selected == total)
        self.select_all_checkbox.blockSignals(False)

    def _selected_records(self) -> list[dict[str, Any]]:
        selected_ids = {record_id for record_id, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        return [record for record in self.records if self._record_id(record) in selected_ids]

    def _open_record_video(self, record_id: int) -> None:
        record = self._record_by_id(record_id)
        if not record:
            self._notice("记录不存在，列表已刷新", "warning")
            self.reload_records()
            return
        path = Path(str(record.get("file_path") or ""))
        if not path.exists():
            self._notice("视频文件不存在", "warning")
            return
        try:
            open_video(path)
            self.logger.info("重复单号记录弹窗打开视频：id=%s, path=%s", record_id, path)
        except Exception as exc:
            self.logger.exception("重复单号记录弹窗打开视频失败：id=%s, path=%s", record_id, path)
            self._notice(f"打开视频失败：{exc}", "error")

    def _delete_single_record(self, record_id: int) -> None:
        record = self._record_by_id(record_id)
        if not record:
            self._notice("记录不存在，列表已刷新", "warning")
            self.reload_records()
            return
        if not self._confirm_delete([record], batch=False):
            return
        success, failed = self._delete_records([record])
        self._after_delete(success, failed)

    def _delete_selected_records(self) -> None:
        records = self._selected_records()
        if not records:
            self._notice("请先选择要删除的记录", "warning")
            return
        if not self._confirm_delete(records, batch=True):
            return
        success, failed = self._delete_records(records)
        self._after_delete(success, failed)

    def _confirm_delete(self, records: list[dict[str, Any]], batch: bool) -> bool:
        if not records:
            return False
        if batch:
            missing_count = sum(1 for record in records if not Path(str(record.get("file_path") or "")).exists())
            description = "删除后将删除本地视频文件和数据库记录；已上传的网盘文件不会删除。"
            if missing_count:
                description += f" 其中 {missing_count} 条本地文件已不存在，将仅移除数据库记录。"
            info_label = "选中记录"
            info_value = f"{len(records)} 条"
        else:
            record = records[0]
            description = f"录制时间：{self._recording_time(record)}。删除后将删除本地视频文件和数据库记录。"
            if str(record.get("upload_status") or "") == UPLOAD_DONE:
                description += " 已上传的网盘文件不会删除。"
            if not Path(str(record.get("file_path") or "")).exists():
                description += " 当前视频文件已不存在，将仅移除数据库记录。"
            info_label = "单号"
            info_value = self.order_no
        important_count = sum(1 for record in records if self._is_important(record))
        if important_count:
            description += f" 其中 {important_count} 条记录已标记为重要，请谨慎删除。"
        return confirm_action(
            self,
            title="批量删除重复录制记录" if batch else "删除重复录制记录",
            heading=f"确定删除选中的 {len(records)} 条录制记录吗？" if batch else "确定删除这条录制记录吗？",
            description=description,
            info_label=info_label,
            info_value=info_value,
            sections=(("将删除：", ("本地数据库记录", "本地视频文件")),),
            confirm_text="仍然删除" if important_count else "删除本地视频",
            destructive=True,
            position_key=DELETE_CONFIRM_POSITION_KEY,
        )

    def _delete_records(self, records: list[dict[str, Any]]) -> tuple[int, list[str]]:
        success = 0
        failed: list[str] = []
        for record in records:
            record_id = self._record_id(record)
            file_path = Path(str(record.get("file_path") or ""))
            try:
                file_exists_before = file_path.exists()
                if file_exists_before:
                    file_path.unlink()
                deleted = self.database.delete_video_by_id(record_id)
                if not deleted:
                    failed.append(f"{record_id}: 数据库记录不存在")
                    continue
                success += 1
                self.logger.info(
                    "重复单号聚合弹窗删除记录：id=%s, order_no=%s, file_exists_before=%s, path=%s",
                    record_id,
                    self.order_no,
                    file_exists_before,
                    file_path,
                )
            except PermissionError as exc:
                failed.append(f"{record_id}: 权限不足或文件被占用")
                self.logger.exception("重复单号记录删除失败：权限不足，id=%s, path=%s", record_id, file_path)
            except OSError as exc:
                failed.append(f"{record_id}: {exc}")
                self.logger.exception("重复单号记录删除失败：id=%s, path=%s", record_id, file_path)
            except Exception as exc:
                failed.append(f"{record_id}: {exc}")
                self.logger.exception("重复单号记录删除未知异常：id=%s, path=%s", record_id, file_path)
        try:
            self.database.recalculate_duplicate_sequences(self.order_no)
        except Exception:
            self.logger.exception("删除重复单号记录后重算序号失败：order_no=%s", self.order_no)
        return success, failed

    def _after_delete(self, success: int, failed: list[str]) -> None:
        self.reload_records()
        self.changed_callback()
        if success and not failed:
            self._notice("视频已删除" if success == 1 else f"删除完成：成功 {success} 条", "success")
        elif success:
            self._notice(f"删除完成：成功 {success} 条，失败 {len(failed)} 条", "warning")
        else:
            self._notice(f"删除失败：{failed[0] if failed else '未知错误'}", "error")

    def _record_by_id(self, record_id: int) -> dict[str, Any] | None:
        for record in self.records:
            if self._record_id(record) == int(record_id or 0):
                return record
        return self.database.get_video_by_id(record_id)

    def _notice(self, message: str, level: str) -> None:
        if self.notice_callback:
            self.notice_callback(message, level)

    @staticmethod
    def _is_important(record: dict[str, Any]) -> bool:
        return bool(
            record.get("is_important")
            or str(record.get("important_reason_type") or "").strip()
            or str(record.get("important_reason_custom") or "").strip()
            or str(record.get("important_note") or "").strip()
            or str(record.get("important_at") or "").strip()
        )

    @staticmethod
    def _record_id(entry: dict[str, Any]) -> int:
        try:
            return int(entry.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        text = str(value or "").strip()
        return text if text else default

    @classmethod
    def _recording_time(cls, entry: dict[str, Any]) -> str:
        return cls._text(entry.get("recorded_at") or entry.get("created_time"), "-")


class NetdiskHistoryDialog(QDialog):
    STATUS_OPTIONS = ("全部", UPLOAD_DONE, UPLOAD_FAILED)

    def __init__(self, database: DatabaseManager, logger: logging.Logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("netdiskHistoryDialog")
        self.database = database
        self.logger = logger
        self.current_page = 1
        self.page_size = 20
        self.total_count = 0
        self.total_pages = 1
        self._last_filter_key: tuple[str, str] | None = None
        self._retry_running = False
        self.setWindowTitle("网盘同步记录")
        DialogSizeManager.apply(self, "sync_history", parent, "large", (860, 520))
        self._build_ui()
        self.reload_records()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel("网盘同步记录")
        title.setObjectName("historyDialogTitle")
        layout.addWidget(title)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel("上传状态："))
        self.status_combo = QComboBox()
        self.status_combo.addItems(self.STATUS_OPTIONS)
        self.status_combo.setFixedWidth(110)
        filter_layout.addWidget(self.status_combo)
        self.order_search_input = QLineEdit()
        self.order_search_input.setPlaceholderText("搜索单号")
        self.order_search_input.setClearButtonEnabled(True)
        filter_layout.addWidget(self.order_search_input, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("secondaryButton")
        filter_layout.addWidget(self.refresh_button)
        self.retry_failed_button = QPushButton("重试上传失败")
        self.retry_failed_button.setObjectName("secondaryButton")
        self.retry_failed_button.setMinimumWidth(116)
        self.retry_failed_button.setToolTip("重试当前同步记录筛选条件下的上传失败记录")
        filter_layout.addWidget(self.retry_failed_button)
        layout.addLayout(filter_layout)

        self.retry_progress_container = QWidget()
        self.retry_progress_container.setObjectName("netdiskProgressPanel")
        retry_progress_layout = QVBoxLayout(self.retry_progress_container)
        retry_progress_layout.setContentsMargins(10, 8, 10, 8)
        retry_progress_layout.setSpacing(6)

        retry_progress_top = QHBoxLayout()
        retry_progress_top.setContentsMargins(0, 0, 0, 0)
        self.retry_progress_title = QLabel("正在重试上传失败：0 / 0")
        self.retry_progress_title.setObjectName("netdiskProgressTitle")
        self.retry_progress_stats = QLabel("")
        self.retry_progress_stats.setObjectName("netdiskProgressStats")
        self.retry_progress_stats.setTextFormat(Qt.RichText)
        retry_progress_top.addWidget(self.retry_progress_title)
        retry_progress_top.addStretch(1)
        retry_progress_top.addWidget(self.retry_progress_stats)

        self.retry_progress_bar = QProgressBar()
        self.retry_progress_bar.setObjectName("netdiskProgressBar")
        self.retry_progress_bar.setTextVisible(False)
        self.retry_progress_bar.setRange(0, 1)
        self.retry_progress_bar.setValue(0)

        self.retry_progress_current = QLabel("")
        self.retry_progress_current.setObjectName("netdiskProgressCurrent")
        self.retry_progress_current.setWordWrap(False)

        retry_progress_layout.addLayout(retry_progress_top)
        retry_progress_layout.addWidget(self.retry_progress_bar)
        retry_progress_layout.addWidget(self.retry_progress_current)
        self.retry_progress_container.hide()
        layout.addWidget(self.retry_progress_container)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["上传时间", "单号", "上传状态", "失败原因", "远程路径", "重试次数"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 86)
        self.table.setColumnWidth(3, 220)
        self.table.setColumnWidth(5, 70)
        layout.addWidget(self.table, 1)

        self.hint_label = QLabel("右键单号或远程路径可复制。")
        self.hint_label.setObjectName("historyDialogHint")
        layout.addWidget(self.hint_label)

        pagination = QHBoxLayout()
        pagination.setSpacing(8)
        self.history_total_label = QLabel("共 0 条")
        pagination.addWidget(self.history_total_label)
        pagination.addStretch(1)
        pagination.addWidget(QLabel("每页："))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["10", "20", "50", "100"])
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.setFixedWidth(76)
        pagination.addWidget(self.page_size_combo)
        self.prev_page_button = QPushButton("<")
        self.prev_page_button.setObjectName("paginationButton")
        self.prev_page_button.setFixedWidth(34)
        self.next_page_button = QPushButton(">")
        self.next_page_button.setObjectName("paginationButton")
        self.next_page_button.setFixedWidth(34)
        self.page_info_label = QLabel("第 1 / 1 页")
        self.jump_page_input = QLineEdit()
        self.jump_page_input.setFixedWidth(56)
        self.jump_page_input.setValidator(QIntValidator(1, 999999, self))
        self.jump_page_input.setAlignment(Qt.AlignCenter)
        self.jump_page_button = QPushButton("跳转")
        self.jump_page_button.setObjectName("secondaryButton")
        pagination.addWidget(self.prev_page_button)
        pagination.addWidget(self.page_info_label)
        pagination.addWidget(self.next_page_button)
        pagination.addWidget(QLabel("跳至"))
        pagination.addWidget(self.jump_page_input)
        pagination.addWidget(self.jump_page_button)
        layout.addLayout(pagination)

        self.status_combo.currentIndexChanged.connect(lambda _index: self._on_filter_changed())
        self.order_search_input.returnPressed.connect(self._on_filter_changed)
        self.refresh_button.clicked.connect(lambda: self.reload_records(reset_page=False))
        self.retry_failed_button.clicked.connect(self._request_retry_failed_uploads)
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        self.prev_page_button.clicked.connect(lambda: self._go_to_page(self.current_page - 1))
        self.next_page_button.clicked.connect(lambda: self._go_to_page(self.current_page + 1))
        self.jump_page_button.clicked.connect(self._jump_to_page)
        self.jump_page_input.returnPressed.connect(self._jump_to_page)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellDoubleClicked.connect(self._copy_cell_from_double_click)

    def reload_records(self, reset_page: bool = False) -> None:
        if self._retry_running:
            return
        if reset_page:
            self.current_page = 1
        status = self.status_combo.currentText().strip()
        status_filter = None if status == "全部" else status
        keyword = self.order_search_input.text().strip()
        filter_key = (status_filter or "", keyword)
        if self._last_filter_key is not None and self._last_filter_key != filter_key:
            self.current_page = 1
        self._last_filter_key = filter_key
        self.total_count = self.database.count_upload_history(status_filter, keyword)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.current_page = max(1, min(self.current_page, self.total_pages))
        offset = (self.current_page - 1) * self.page_size
        rows = self.database.query_upload_history(status_filter, keyword, limit=self.page_size, offset=offset)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        try:
            for row_index, record in enumerate(rows):
                self.table.insertRow(row_index)
                self._populate_row(row_index, record)
        finally:
            self.table.setUpdatesEnabled(True)
        self._update_pagination_controls()
        self.hint_label.setText("右键单号或远程路径可复制。")
        self._update_retry_button_text()

    def current_status_filter(self) -> str | None:
        status = self.status_combo.currentText().strip()
        return None if status == "全部" else status

    def current_keyword(self) -> str:
        return self.order_search_input.text().strip()

    def set_retry_running(self, running: bool) -> None:
        self._retry_running = bool(running)
        for widget in (
            self.status_combo,
            self.order_search_input,
            self.refresh_button,
            self.page_size_combo,
            self.prev_page_button,
            self.next_page_button,
            self.jump_page_input,
            self.jump_page_button,
        ):
            widget.setEnabled(not self._retry_running)
        self.retry_failed_button.setEnabled(not self._retry_running)
        self.retry_failed_button.setText("重试中..." if self._retry_running else "重试上传失败")
        if not self._retry_running:
            self._update_pagination_controls()

    def show_retry_progress(
        self,
        current: int,
        total: int,
        file_name: str,
        success_count: int,
        fail_count: int,
    ) -> None:
        total = max(1, int(total or 1))
        current = max(0, min(int(current or 0), total))
        self.retry_progress_bar.setRange(0, total)
        self.retry_progress_bar.setValue(current)
        self.retry_progress_title.setText(f"正在重试上传失败：{current} / {total}")
        self.retry_progress_stats.setText(
            f"成功 {success_count} 个，<span style='color:#dc2626;'>失败 {fail_count} 个</span>"
            if fail_count
            else f"成功 {success_count} 个，失败 0 个"
        )
        self.retry_progress_current.setText(f"当前：{file_name}" if file_name else "")
        self.retry_progress_current.setToolTip(file_name or "")
        self.retry_progress_container.show()

    def show_retry_finished(self, success_count: int, fail_count: int) -> None:
        total = max(1, success_count + fail_count, self.retry_progress_bar.maximum())
        self.retry_progress_bar.setRange(0, total)
        self.retry_progress_bar.setValue(total)
        self.retry_progress_title.setText(f"重试完成：成功 {success_count} 个，失败 {fail_count} 个")
        self.retry_progress_stats.setText(
            f"成功 {success_count} 个，<span style='color:#dc2626;'>失败 {fail_count} 个</span>"
            if fail_count
            else f"成功 {success_count} 个，失败 0 个"
        )
        self.retry_progress_current.setText("重试完成，列表已刷新。")
        self.retry_progress_container.show()
        self.set_retry_running(False)
        self.reload_records(reset_page=False)

    def _request_retry_failed_uploads(self) -> None:
        parent = self.parent()
        if hasattr(parent, "_retry_failed_uploads_from_history"):
            parent._retry_failed_uploads_from_history(self)

    def _update_retry_button_text(self) -> None:
        try:
            failed_count = self.database.count_upload_history(UPLOAD_FAILED, self.current_keyword())
        except Exception:
            failed_count = 0
        self.retry_failed_button.setText(f"重试上传失败（{failed_count}）" if failed_count else "重试上传失败")

    def _populate_row(self, row: int, record: dict[str, Any]) -> None:
        upload_status = str(record.get("upload_status") or "")
        upload_time = str(record.get("upload_time") or "").strip() or "暂无"
        upload_error = str(record.get("upload_error") or "").strip()
        remote_path = str(record.get("upload_remote_path") or "").strip()
        order_no = str(record.get("order_no") or "").strip()
        values = [
            upload_time,
            order_no,
            upload_status,
            upload_error if upload_status == UPLOAD_FAILED and upload_error else "-",
            remote_path if remote_path else "-",
            str(int(record.get("upload_retry_count") or 0)),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignCenter if column in {0, 1, 2, 5} else Qt.AlignLeft | Qt.AlignVCenter)
            if column == 1 and order_no:
                item.setToolTip(order_no)
                item.setData(Qt.UserRole, order_no)
            if column == 2:
                item.setForeground(QColor(RecordDetailDialog._upload_status_color(upload_status)))
            if column == 3 and upload_error:
                item.setToolTip(upload_error)
            if column == 4 and remote_path:
                item.setToolTip(remote_path)
                item.setData(Qt.UserRole, remote_path)
            self.table.setItem(row, column, item)

    def _on_filter_changed(self) -> None:
        self.reload_records(reset_page=True)

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

    def _jump_to_page(self) -> None:
        try:
            page = int(self.jump_page_input.text().strip() or self.current_page)
        except ValueError:
            page = self.current_page
        self._go_to_page(page)

    def _update_pagination_controls(self) -> None:
        self.history_total_label.setText(f"共 {self.total_count} 条")
        self.page_info_label.setText(f"第 {self.current_page} / {self.total_pages} 页")
        self.jump_page_input.setText(str(self.current_page))
        self.jump_page_input.setValidator(QIntValidator(1, max(1, self.total_pages), self))
        self.prev_page_button.setEnabled(self.current_page > 1)
        self.next_page_button.setEnabled(self.current_page < self.total_pages)

    def reject(self) -> None:
        if self._retry_running:
            show_toast(self, "当前正在重试上传失败，请等待任务完成", "info", 2600, self.logger)
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._retry_running:
            show_toast(self, "当前正在重试上传失败，请等待任务完成", "info", 2600, self.logger)
            event.ignore()
            return
        super().closeEvent(event)

    def _show_context_menu(self, position: QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid() or index.column() not in {1, 4}:
            return
        menu = QMenu(self)
        copy_label = "复制单号" if index.column() == 1 else "复制远程路径"
        copy_action = menu.addAction(copy_label)
        item = self.table.item(index.row(), index.column())
        text = str(item.data(Qt.UserRole) or "").strip() if item else ""
        copy_action.setEnabled(bool(text))
        selected = menu.exec(self.table.viewport().mapToGlobal(position))
        if selected is copy_action:
            self._copy_history_cell(index.row(), index.column())

    def _copy_cell_from_double_click(self, row: int, column: int) -> None:
        if column in {1, 4}:
            self._copy_history_cell(row, column)

    def _copy_history_cell(self, row: int, column: int) -> None:
        if column not in {1, 4}:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        text = str(item.data(Qt.UserRole) or "").strip()
        if not text:
            self._show_copy_notice("暂无可复制内容", "warning")
            return
        QApplication.clipboard().setText(text)
        self._show_copy_notice("单号已复制" if column == 1 else "远程路径已复制", "success")

    def _show_copy_notice(self, message: str, level: str = "success") -> None:
        self.hint_label.setText(message)
        parent = self.parent()
        if hasattr(parent, "_show_notice"):
            try:
                parent._show_notice(message, level)
            except Exception:
                self.logger.exception("同步记录复制提示失败：message=%s", message)


class QueryTab(QWidget):
    video_list_changed = Signal(str)

    PAGE_SIZE_OPTIONS = (10, 20, 50, 100)
    UPLOAD_STATUS_FILTER_OPTIONS = ("全部", UPLOAD_PENDING, UPLOAD_DONE, UPLOAD_FAILED, UPLOAD_UPLOADING)
    RECORD_TYPE_COLUMN = 5
    REMARK_COLUMN = 6
    STATUS_COLUMN = 7
    SCENE_COLUMN = 8
    ACTION_COLUMN = 9
    COPY_COLUMNS = tuple(range(0, 9))
    COPY_TEXT_ROLE = Qt.UserRole + 1
    RECORD_ID_ROLE = Qt.UserRole + 2

    def __init__(
        self,
        config_manager: ConfigManager,
        logger: logging.Logger,
        license_manager=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("videoQueryPage")
        self.config_manager = config_manager
        self.logger = logger
        self.license_manager = license_manager
        self.video_dir = self._initial_query_dir()
        self.database = DatabaseManager(self.config_manager.database_path, logger)
        self.logger.info(
            "查询页 SQLite 数据库路径：database_path=%s, database_exists=%s, video_root_dir=%s",
            self.database.db_path,
            self.database.db_path.exists(),
            self.video_dir,
        )
        self.date_filter_enabled = False
        self.date_filter_mode = "all"
        self.type_filter = "全部"
        self.upload_status_filter = "全部"
        self.remark_filter = "全部"
        self.important_filter = "全部"
        self.important_reason_filter = "全部"
        self.page_size = self._initial_page_size()
        self.current_page = 1
        self.total_count = 0
        self.total_pages = 1
        self.upload_worker: NetdiskUploadWorker | None = None
        self.video_query_dirty = True
        self._has_loaded_once = False
        self._load_worker: VideoQueryLoadWorker | None = None
        self._load_request_id = 0
        self._pending_load = False
        self._pending_load_rebuild = False
        self._pending_load_show_notice = False
        self._restore_scroll_after_load: int | None = None
        self._table_state = "content"
        self._skeleton_active = False
        self._skeleton_blocks: list[QFrame] = []
        self._loading_animation_step = 0
        self._loading_spinner_frames = ("◐", "◓", "◑", "◒")
        self._theme_manager = QApplication.instance().property("theme_manager") if QApplication.instance() else None
        self._skeleton_colors = self._skeleton_palette()
        self._loading_animation_timer = QTimer(self)
        self._loading_animation_timer.setInterval(180)
        self._loading_animation_timer.timeout.connect(self._on_loading_animation_tick)
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(380)
        self.search_debounce_timer.timeout.connect(lambda: self._apply_filter(reset_page=True))
        self._query_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._request_cache_keys: dict[int, tuple[Any, ...] | None] = {}
        self._page_open_started_at = time.perf_counter()
        self.netdisk_task_mode = "sync"
        self.netdisk_history_dialog: NetdiskHistoryDialog | None = None
        self.auto_sync_state = "idle"
        self.auto_sync_deadline: datetime | None = None
        self.auto_sync_timer = QTimer(self)
        self.auto_sync_timer.setInterval(1000)
        self.auto_sync_timer.timeout.connect(self._on_auto_sync_timer_tick)
        self._auto_sync_stop_requested = False
        self._auto_sync_pause_after_current = False
        self._recording_active_for_auto_sync = False
        self.netdisk_progress_hide_timer = QTimer(self)
        self.netdisk_progress_hide_timer.setSingleShot(True)
        self.netdisk_progress_hide_timer.timeout.connect(self._hide_netdisk_progress)
        self._build_ui()
        if self.license_manager is not None:
            self.license_manager.status_changed.connect(self._on_license_status_changed)
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._on_theme_changed)
        self._update_netdisk_controls()
        QTimer.singleShot(1000, self._maybe_schedule_auto_sync_on_startup)
        self.logger.info("查询页初始化视频存储目录：%s", self.video_dir)

    def set_video_dir(self, path: str) -> None:
        self.logger.info("视频存储目录已更新：%s", path)
        self._sync_global_video_dir(rebuild=True, show_notice=False)

    def shutdown(self) -> None:
        self.auto_sync_timer.stop()
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait(3000)
        if self.upload_worker is not None and self.upload_worker.isRunning():
            if hasattr(self.upload_worker, "stop_after_current"):
                self.upload_worker.stop_after_current()
            else:
                self.upload_worker.stop()
            self.upload_worker.wait(3000)
        self.database.close()

    def is_netdisk_syncing(self) -> bool:
        return self.upload_worker is not None

    def reload_config(self, _config: dict[str, Any] | None = None) -> None:
        directory_changed = self._sync_global_video_dir(rebuild=True, show_notice=False)
        if not self._auto_sync_enabled() and self.auto_sync_state == "countdown":
            self._cancel_auto_sync_countdown("自动同步已关闭")
        self._update_netdisk_controls()
        if not directory_changed:
            self.refresh(rebuild=False, show_notice=False)
        self._maybe_schedule_auto_sync_on_startup()

    def mark_dirty(self) -> None:
        self.video_query_dirty = True
        self._clear_query_cache()

    def _sync_global_video_dir(self, rebuild: bool = True, show_notice: bool = False) -> bool:
        try:
            target = self.config_manager.get_video_dir()
            target.mkdir(parents=True, exist_ok=True)
            target = target.resolve()
        except Exception as exc:
            self.logger.exception("同步视频存储目录失败")
            self._show_notice(f"视频存储目录不可用：{exc}", "error")
            return False
        current = self.video_dir.resolve() if self.video_dir.exists() else self.video_dir
        if target == current:
            return False
        self.video_dir = target
        self.current_page = 1
        self.mark_dirty()
        self.logger.info("视频查询页已切换到全局视频存储目录：%s", self.video_dir)
        self.refresh(rebuild=rebuild, show_notice=show_notice)
        return True

    def activate(self) -> None:
        QTimer.singleShot(50, self._load_after_activated)

    def _load_after_activated(self) -> None:
        if not self.isVisible():
            return
        if self._load_worker is not None:
            return
        if not self._has_loaded_once:
            self.refresh(rebuild=False, show_notice=False)
            return
        if self.video_query_dirty:
            self.refresh(rebuild=False, show_notice=False)

    def refresh(self, rebuild: bool = False, show_notice: bool = True) -> None:
        self._update_netdisk_controls()
        self.video_query_dirty = True
        if rebuild:
            self._clear_query_cache()
        self._request_video_load(rebuild=rebuild, show_notice=show_notice)

    def reload_current_query(
        self,
        *,
        preserve_filters: bool = True,
        preserve_page: bool = True,
        preserve_scroll: bool = True,
    ) -> None:
        """Reload the visible query without disturbing the user's current context."""
        del preserve_filters  # Filters live in their controls and remain unchanged by a refresh.
        if not preserve_page:
            self.current_page = 1
        if preserve_scroll:
            self._restore_scroll_after_load = self.table.verticalScrollBar().value()
        self.refresh(rebuild=False, show_notice=False)

    def _notify_video_list_changed(self, reason: str) -> None:
        self.reload_current_query(preserve_filters=True, preserve_page=True, preserve_scroll=True)
        self.video_list_changed.emit(reason)

    def _clear_query_cache(self) -> None:
        if hasattr(self, "_query_cache"):
            self._query_cache.clear()

    def _query_cache_key(self, filters: dict[str, Any], page_size: int, current_page: int) -> tuple[Any, ...]:
        def normalize_value(value: Any) -> str:
            if isinstance(value, Path):
                return str(value.resolve() if value.exists() else value)
            return str(value)

        return (
            str(self.video_dir.resolve() if self.video_dir.exists() else self.video_dir),
            page_size,
            current_page,
            tuple(sorted((str(key), normalize_value(value)) for key, value in filters.items())),
        )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.activate()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.matches(QKeySequence.Copy):
            self._copy_selected_rows()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self.table.viewport():
            if event.type() == QEvent.Leave:
                self.table.viewport().unsetCursor()
            elif event.type() in {QEvent.Resize, QEvent.Show}:
                QTimer.singleShot(0, self._position_table_state_overlay)
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        self.search_input = ThemedClearableLineEdit()
        self.search_input.setObjectName("videoSearchInput")
        self.search_input.setPlaceholderText("输入单号、视频名称或备注搜索。")
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.setObjectName("primaryButton")
        self.open_location_button = QPushButton("打开所在文件夹")
        self.open_location_button.setObjectName("secondaryButton")
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.open_location_button)
        layout.addLayout(toolbar)

        date_toolbar = QHBoxLayout()
        date_toolbar.setSpacing(8)
        netdisk_toolbar = QHBoxLayout()
        netdisk_toolbar.setSpacing(8)
        self.start_date_edit = ClickableDateEdit()
        self.end_date_edit = ClickableDateEdit()
        for editor in (self.start_date_edit, self.end_date_edit):
            editor.setDate(QDate.currentDate())

        self.today_button = QPushButton("今天")
        self.yesterday_button = QPushButton("昨天")
        self.last_7_days_button = QPushButton("最近 7 天")
        self.all_dates_button = QPushButton("全部")
        self.type_all_button = QPushButton("全部")
        self.type_ship_button = QPushButton("发货")
        self.type_return_button = QPushButton("退货")
        self.sync_netdisk_button = QPushButton("同步至网盘")
        self.sync_netdisk_button.setObjectName("secondaryButton")
        self.sync_netdisk_button.setProperty("buttonRole", "sync")
        self.sync_netdisk_button.setToolTip("将视频存储目录中未上传的视频同步到百度网盘")
        self.stop_netdisk_button = QPushButton("停止同步")
        self.stop_netdisk_button.setObjectName("secondaryButton")
        self.stop_netdisk_button.setProperty("buttonRole", "danger")
        self.stop_netdisk_button.setToolTip("取消自动同步倒计时或安全停止当前同步任务")
        self.netdisk_history_button = QPushButton("同步记录")
        self.netdisk_history_button.setObjectName("secondaryButton")
        self.netdisk_history_button.setToolTip("查看百度网盘上传历史和失败原因")
        self.netdisk_auto_status_label = QLabel("")
        self.netdisk_auto_status_label.setObjectName("netdiskAutoStatusLabel")
        self.extended_filters_expanded = False
        self.extended_filters_toggle_button = QToolButton()
        self.extended_filters_toggle_button.setObjectName("extendedFilterToggleButton")
        self.extended_filters_toggle_button.setToolTip("展开扩展筛选")
        self.extended_filters_toggle_button.setFocusPolicy(Qt.NoFocus)
        self.extended_filters_toggle_button.setCursor(Qt.PointingHandCursor)
        self.extended_filters_toggle_button.setFixedSize(36, 36)
        self.extended_filters_toggle_button.setIconSize(QSize(16, 16))
        self.extended_filters_toggle_button.clicked.connect(self._toggle_extended_filters)

        self.date_filter_button_group = QButtonGroup(self)
        self.date_filter_button_group.setExclusive(True)
        for index, date_button in enumerate(
            (self.today_button, self.yesterday_button, self.last_7_days_button, self.all_dates_button),
            start=1,
        ):
            date_button.setObjectName("filterButton")
            date_button.setCheckable(True)
            self.date_filter_button_group.addButton(date_button, index)
        self.all_dates_button.setChecked(True)

        self.type_filter_button_group = QButtonGroup(self)
        self.type_filter_button_group.setExclusive(True)
        for index, type_button in enumerate((self.type_all_button, self.type_ship_button, self.type_return_button), start=1):
            type_button.setObjectName("filterButton")
            type_button.setCheckable(True)
            self.type_filter_button_group.addButton(type_button, index)
        self.type_all_button.setChecked(True)

        self.upload_status_label = QLabel("上传状态：")
        self.upload_status_all_button = QPushButton("全部")
        self.upload_status_pending_button = QPushButton(UPLOAD_PENDING)
        self.upload_status_done_button = QPushButton(UPLOAD_DONE)
        self.upload_status_failed_button = QPushButton(UPLOAD_FAILED)
        self.upload_status_uploading_button = QPushButton(UPLOAD_UPLOADING)
        self.upload_status_filter_button_group = QButtonGroup(self)
        self.upload_status_filter_button_group.setExclusive(True)
        self.upload_status_buttons = (
            self.upload_status_all_button,
            self.upload_status_pending_button,
            self.upload_status_done_button,
            self.upload_status_failed_button,
            self.upload_status_uploading_button,
        )
        for index, status_button in enumerate(self.upload_status_buttons, start=1):
            status_button.setObjectName("filterButton")
            status_button.setCheckable(True)
            self.upload_status_filter_button_group.addButton(status_button, index)
        self.upload_status_all_button.setChecked(True)
        self.netdisk_filter_row = QWidget()
        self.netdisk_filter_row.setObjectName("netdiskFilterRow")
        self.netdisk_filter_row.setLayout(netdisk_toolbar)
        self.upload_status_filter_widgets = (
            self.netdisk_filter_row,
            self.upload_status_label,
            *self.upload_status_buttons,
            self.sync_netdisk_button,
            self.stop_netdisk_button,
            self.netdisk_history_button,
            self.netdisk_auto_status_label,
        )
        self.detail_filter_row = QWidget()
        self.detail_filter_row.setObjectName("videoDetailFilterRow")
        detail_filter_toolbar = QHBoxLayout(self.detail_filter_row)
        detail_filter_toolbar.setContentsMargins(0, 0, 0, 0)
        detail_filter_toolbar.setSpacing(8)
        self.remark_filter_combo = QComboBox()
        self.remark_filter_combo.setObjectName("queryCompactFilterCombo")
        self.remark_filter_combo.addItems(["全部", "有备注", "无备注"])
        self.remark_filter_combo.setFixedSize(110, 34)
        self.important_filter_combo = QComboBox()
        self.important_filter_combo.setObjectName("queryCompactFilterCombo")
        self.important_filter_combo.addItems(["全部", "已标记", "未标记"])
        self.important_filter_combo.setFixedSize(110, 34)
        self.important_reason_filter_combo = QComboBox()
        self.important_reason_filter_combo.setObjectName("queryCompactFilterCombo")
        self.important_reason_filter_combo.addItem("全部", "全部")
        for reason_key, reason_label in IMPORTANT_REASON_OPTIONS:
            self.important_reason_filter_combo.addItem(reason_label, reason_key)
        self.important_reason_filter_combo.setFixedSize(180, 34)

        date_segment = QWidget()
        date_segment.setObjectName("querySegmentControl")
        date_segment_layout = QHBoxLayout(date_segment)
        date_segment_layout.setContentsMargins(0, 0, 0, 0)
        date_segment_layout.setSpacing(0)
        for index, button in enumerate(
            (self.today_button, self.yesterday_button, self.last_7_days_button, self.all_dates_button)
        ):
            button.setProperty("segmentPosition", "first" if index == 0 else "last" if index == 3 else "middle")
            date_segment_layout.addWidget(button)

        type_segment = QWidget()
        type_segment.setObjectName("querySegmentControl")
        type_segment_layout = QHBoxLayout(type_segment)
        type_segment_layout.setContentsMargins(0, 0, 0, 0)
        type_segment_layout.setSpacing(0)
        for index, button in enumerate((self.type_all_button, self.type_ship_button, self.type_return_button)):
            button.setProperty("segmentPosition", "first" if index == 0 else "last" if index == 2 else "middle")
            type_segment_layout.addWidget(button)

        date_toolbar.addWidget(QLabel("开始日期："))
        date_toolbar.addWidget(self.start_date_edit)
        date_toolbar.addWidget(QLabel("结束日期："))
        date_toolbar.addWidget(self.end_date_edit)
        date_toolbar.addWidget(date_segment)
        date_toolbar.addSpacing(12)
        date_toolbar.addWidget(QLabel("类型："))
        date_toolbar.addWidget(type_segment)
        date_toolbar.addStretch(1)
        date_toolbar.addWidget(self.extended_filters_toggle_button)
        layout.addLayout(date_toolbar)

        netdisk_toolbar.addWidget(self.upload_status_label)
        for status_button in self.upload_status_buttons:
            netdisk_toolbar.addWidget(status_button)
        netdisk_toolbar.addStretch(1)
        netdisk_toolbar.addWidget(self.netdisk_auto_status_label)
        netdisk_toolbar.addWidget(self.sync_netdisk_button)
        netdisk_toolbar.addWidget(self.stop_netdisk_button)
        netdisk_toolbar.addWidget(self.netdisk_history_button)
        detail_filter_toolbar.addWidget(QLabel("有无备注："))
        detail_filter_toolbar.addWidget(self.remark_filter_combo)
        detail_filter_toolbar.addWidget(QLabel("标记重要："))
        detail_filter_toolbar.addWidget(self.important_filter_combo)
        detail_filter_toolbar.addWidget(QLabel("重要原因："))
        detail_filter_toolbar.addWidget(self.important_reason_filter_combo)
        detail_filter_toolbar.addStretch(1)
        layout.addWidget(self.detail_filter_row)
        layout.addWidget(self.netdisk_filter_row)
        self._apply_extended_filters_visibility()

        self.netdisk_progress_container = QWidget()
        self.netdisk_progress_container.setObjectName("netdiskProgressPanel")
        netdisk_progress_layout = QVBoxLayout(self.netdisk_progress_container)
        netdisk_progress_layout.setContentsMargins(10, 8, 10, 8)
        netdisk_progress_layout.setSpacing(6)

        netdisk_progress_top = QHBoxLayout()
        netdisk_progress_top.setContentsMargins(0, 0, 0, 0)
        self.netdisk_progress_title = QLabel("网盘同步")
        self.netdisk_progress_title.setObjectName("netdiskProgressTitle")
        self.netdisk_progress_stats = QLabel("")
        self.netdisk_progress_stats.setObjectName("netdiskProgressStats")
        self.netdisk_progress_stats.setTextFormat(Qt.RichText)
        netdisk_progress_top.addWidget(self.netdisk_progress_title)
        netdisk_progress_top.addStretch(1)
        netdisk_progress_top.addWidget(self.netdisk_progress_stats)

        self.netdisk_progress_bar = QProgressBar()
        self.netdisk_progress_bar.setObjectName("netdiskProgressBar")
        self.netdisk_progress_bar.setTextVisible(False)
        self.netdisk_progress_bar.setRange(0, 1)
        self.netdisk_progress_bar.setValue(0)

        self.netdisk_progress_current = QLabel("")
        self.netdisk_progress_current.setObjectName("netdiskProgressCurrent")
        self.netdisk_progress_current.setWordWrap(False)

        netdisk_progress_layout.addLayout(netdisk_progress_top)
        netdisk_progress_layout.addWidget(self.netdisk_progress_bar)
        netdisk_progress_layout.addWidget(self.netdisk_progress_current)
        self.netdisk_progress_container.hide()
        layout.addWidget(self.netdisk_progress_container)

        self.empty_label = QLabel("未找到符合条件的视频。")
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 10)
        self.table.setObjectName("videoQueryTable")
        self.table.setHorizontalHeaderLabels(
            [
                "序号",
                "单号",
                "录制时间",
                "分辨率/编码",
                "大小/时长",
                "类型",
                "备注",
                "文件状态",
                "场景视频",
                "操作",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMouseTracking(True)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setWordWrap(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setColumnWidth(self.ACTION_COLUMN, 80)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(72)
        self.table.verticalHeader().setMinimumSectionSize(68)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(self.STATUS_COLUMN, QHeaderView.Fixed)
        header.setSectionResizeMode(self.SCENE_COLUMN, QHeaderView.Fixed)
        header.setSectionResizeMode(self.ACTION_COLUMN, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 58)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 164)
        self.table.setColumnWidth(3, 134)
        self.table.setColumnWidth(4, 118)
        self.table.setColumnWidth(5, 92)
        self.table.setColumnWidth(self.STATUS_COLUMN, 152)
        self.table.setColumnWidth(self.SCENE_COLUMN, 80)
        self.table.setColumnWidth(self.ACTION_COLUMN, 80)
        self.video_table_container = QFrame()
        self.video_table_container.setObjectName("videoTableContainer")
        video_table_layout = QVBoxLayout(self.video_table_container)
        video_table_layout.setContentsMargins(0, 0, 0, 0)
        video_table_layout.setSpacing(0)
        video_table_layout.addWidget(self.table, 1)
        self._setup_table_state_overlay()

        self.pagination_container = QWidget()
        self.pagination_container.setObjectName("paginationBar")
        self.pagination_container.setMinimumHeight(56)
        self.pagination_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        pagination_layout = QHBoxLayout(self.pagination_container)
        pagination_layout.setContentsMargins(10, 8, 10, 8)
        pagination_layout.setSpacing(8)
        pagination_layout.setAlignment(Qt.AlignVCenter)

        self.total_count_label = QLabel("共 0 条")
        self.total_count_label.setObjectName("paginationTotalLabel")
        self.page_size_combo = QComboBox()
        self.page_size_combo.setObjectName("paginationCombo")
        self.page_size_combo.setFixedWidth(76)
        self.page_size_combo.setMinimumHeight(34)
        self.page_size_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for size in self.PAGE_SIZE_OPTIONS:
            self.page_size_combo.addItem(f"{size}条/页", size)
        size_index = self.page_size_combo.findData(self.page_size)
        self.page_size_combo.setCurrentIndex(size_index if size_index >= 0 else 1)

        self.prev_page_button = QPushButton("<")
        self.prev_page_button.setObjectName("paginationButton")
        self.prev_page_button.setMinimumHeight(34)
        self.prev_page_button.setToolTip("上一页")
        self.next_page_button = QPushButton(">")
        self.next_page_button.setObjectName("paginationButton")
        self.next_page_button.setMinimumHeight(34)
        self.next_page_button.setToolTip("下一页")

        self.page_buttons_host = QWidget()
        self.page_buttons_layout = QHBoxLayout(self.page_buttons_host)
        self.page_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.page_buttons_layout.setSpacing(6)

        self.jump_page_input = QLineEdit()
        self.jump_page_input.setObjectName("paginationJumpInput")
        self.jump_page_validator = QIntValidator(1, 1, self.jump_page_input)
        self.jump_page_input.setValidator(self.jump_page_validator)
        self.jump_page_input.setAlignment(Qt.AlignCenter)
        self.jump_page_input.setFixedWidth(56)
        self.jump_page_input.setMinimumHeight(34)

        pagination_layout.addWidget(self.total_count_label)
        pagination_layout.addWidget(self.page_size_combo)
        pagination_layout.addStretch(1)
        pagination_layout.addWidget(self.prev_page_button)
        pagination_layout.addWidget(self.page_buttons_host)
        pagination_layout.addWidget(self.next_page_button)
        pagination_layout.addSpacing(8)
        pagination_layout.addWidget(QLabel("前往"))
        pagination_layout.addWidget(self.jump_page_input)
        pagination_layout.addWidget(QLabel("页"))
        video_table_layout.addWidget(self.pagination_container)
        layout.addWidget(self.video_table_container, 1)
        self.logger.info("类型列改为只读文本初始化")
        self.logger.info("分页组件初始化：page_size=%s", self.page_size)

        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.refresh_button.clicked.connect(lambda: self.refresh(rebuild=True))
        self.open_location_button.clicked.connect(lambda: self._open_selected_location())
        self.start_date_edit.dateChanged.connect(lambda _date: self._enable_date_filter())
        self.end_date_edit.dateChanged.connect(lambda _date: self._enable_date_filter())
        self.today_button.clicked.connect(lambda: self._set_quick_date_filter("today"))
        self.yesterday_button.clicked.connect(lambda: self._set_quick_date_filter("yesterday"))
        self.last_7_days_button.clicked.connect(lambda: self._set_quick_date_filter("last_7_days"))
        self.all_dates_button.clicked.connect(lambda: self._set_quick_date_filter("all"))
        self.type_all_button.clicked.connect(lambda: self._set_type_filter("全部"))
        self.type_ship_button.clicked.connect(lambda: self._set_type_filter("发货"))
        self.type_return_button.clicked.connect(lambda: self._set_type_filter("退货"))
        self.upload_status_all_button.clicked.connect(lambda: self._set_upload_status_filter("全部"))
        self.upload_status_pending_button.clicked.connect(lambda: self._set_upload_status_filter(UPLOAD_PENDING))
        self.upload_status_done_button.clicked.connect(lambda: self._set_upload_status_filter(UPLOAD_DONE))
        self.upload_status_failed_button.clicked.connect(lambda: self._set_upload_status_filter(UPLOAD_FAILED))
        self.upload_status_uploading_button.clicked.connect(lambda: self._set_upload_status_filter(UPLOAD_UPLOADING))
        self.remark_filter_combo.currentTextChanged.connect(self._set_remark_filter)
        self.important_filter_combo.currentTextChanged.connect(self._set_important_filter)
        self.important_reason_filter_combo.currentIndexChanged.connect(
            lambda _index: self._set_important_reason_filter(self.important_reason_filter_combo.currentData())
        )
        self.sync_netdisk_button.clicked.connect(self._sync_unuploaded_videos)
        self.stop_netdisk_button.clicked.connect(self._stop_netdisk_sync)
        self.netdisk_history_button.clicked.connect(self._show_netdisk_history)
        self.table.itemClicked.connect(self._on_item_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.cellEntered.connect(self._update_table_cursor)
        self.table.viewport().installEventFilter(self)
        self.copy_shortcut = QShortcut(QKeySequence.Copy, self.table)
        self.copy_shortcut.activated.connect(self._copy_selected_rows)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        self.prev_page_button.clicked.connect(lambda: self._go_to_page(self.current_page - 1))
        self.next_page_button.clicked.connect(lambda: self._go_to_page(self.current_page + 1))
        self.jump_page_input.returnPressed.connect(self._jump_to_page)

    def _setup_table_state_overlay(self) -> None:
        self.table_state_overlay = QFrame(self.table.viewport())
        self.table_state_overlay.setObjectName("videoTableStateOverlay")
        self.table_state_overlay.hide()

        overlay_layout = QVBoxLayout(self.table_state_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        overlay_layout.addStretch(1)

        self.table_state_box = QFrame(self.table_state_overlay)
        self.table_state_box.setObjectName("videoTableStateBox")
        box_layout = QVBoxLayout(self.table_state_box)
        box_layout.setContentsMargins(18, 14, 18, 14)
        box_layout.setSpacing(8)
        box_layout.setAlignment(Qt.AlignCenter)

        self.table_state_icon = QLabel("▣")
        self.table_state_icon.setObjectName("videoTableStateIcon")
        self.table_state_icon.setAlignment(Qt.AlignCenter)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.setAlignment(Qt.AlignCenter)
        self.table_state_spinner = QLabel(self._loading_spinner_frames[0])
        self.table_state_spinner.setObjectName("videoLoadingSpinner")
        self.table_state_spinner.setAlignment(Qt.AlignCenter)
        self.table_state_title = QLabel("")
        self.table_state_title.setObjectName("videoTableStateTitle")
        self.table_state_title.setAlignment(Qt.AlignCenter)
        title_row.addWidget(self.table_state_spinner)
        title_row.addWidget(self.table_state_title)

        self.table_state_subtitle = QLabel("")
        self.table_state_subtitle.setObjectName("videoTableStateSubtitle")
        self.table_state_subtitle.setAlignment(Qt.AlignCenter)
        self.table_state_subtitle.setWordWrap(True)

        self.table_state_retry_button = QPushButton("重新加载")
        self.table_state_retry_button.setObjectName("secondaryButton")
        self.table_state_retry_button.setFixedSize(96, 32)
        self.table_state_retry_button.clicked.connect(lambda: self.refresh(rebuild=False, show_notice=False))

        box_layout.addWidget(self.table_state_icon)
        box_layout.addLayout(title_row)
        box_layout.addWidget(self.table_state_subtitle)
        box_layout.addWidget(self.table_state_retry_button, 0, Qt.AlignCenter)

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(self.table_state_box)
        center_row.addStretch(1)
        overlay_layout.addLayout(center_row)
        overlay_layout.addStretch(1)
        self._position_table_state_overlay()

    def _position_table_state_overlay(self) -> None:
        overlay = getattr(self, "table_state_overlay", None)
        if overlay is None:
            return
        overlay.setGeometry(self.table.viewport().rect())
        if overlay.isVisible():
            overlay.raise_()

    def _show_table_state(self, state: str, title: str, subtitle: str = "", error: str = "") -> None:
        self._table_state = state
        self.empty_label.hide()
        self.table_state_title.setText(title)
        self.table_state_subtitle.setText(subtitle)
        self.table_state_icon.setVisible(state in {"empty", "error"})
        self.table_state_spinner.setVisible(state == "loading")
        self.table_state_retry_button.setVisible(state == "error")
        if state == "empty":
            self.table_state_icon.setText("▣")
        elif state == "error":
            self.table_state_icon.setText("!")
            if error:
                self.table_state_subtitle.setToolTip(error)
        self.table_state_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, state == "loading")
        self.table_state_overlay.show()
        self._position_table_state_overlay()
        if state == "loading":
            self._start_loading_animation()
        else:
            self._stop_loading_animation()

    def _hide_table_state(self) -> None:
        self._table_state = "content"
        self.table_state_overlay.hide()
        self._stop_loading_animation()

    def _start_loading_animation(self) -> None:
        self._on_loading_animation_tick()
        if not self._loading_animation_timer.isActive():
            self._loading_animation_timer.start()

    def _stop_loading_animation(self) -> None:
        if self._loading_animation_timer.isActive():
            self._loading_animation_timer.stop()

    def _on_loading_animation_tick(self) -> None:
        self._loading_animation_step = (self._loading_animation_step + 1) % max(
            len(self._skeleton_colors),
            len(self._loading_spinner_frames),
        )
        self.table_state_spinner.setText(
            self._loading_spinner_frames[self._loading_animation_step % len(self._loading_spinner_frames)]
        )
        if not self._skeleton_active:
            return
        color = self._skeleton_colors[self._loading_animation_step % len(self._skeleton_colors)]
        for block in list(self._skeleton_blocks):
            block.setStyleSheet(f"background: {color}; border-radius: 6px; border: none;")

    def _skeleton_palette(self) -> tuple[str, ...]:
        if self._theme_manager is not None and self._theme_manager.resolved_theme() == "dark":
            return ("#424242", "#474747", "#4c4c4c", "#515151", "#4c4c4c", "#474747")
        return ("#E2E8F0", "#E7EDF4", "#EDF3F8", "#F1F5F9", "#EDF3F8", "#E7EDF4")

    def _on_theme_changed(self, _mode: str, _resolved_theme: str) -> None:
        self._skeleton_colors = self._skeleton_palette()
        if self._skeleton_active:
            self._on_loading_animation_tick()
        self._refresh_table_action_icons()

    def _apply_table_action_icon(self, button: QToolButton, icon_name: str) -> None:
        resolved_theme = self._theme_manager.resolved_theme() if self._theme_manager is not None else "light"
        suffix = "-light" if resolved_theme == "dark" else ""
        icon_path = resource_path(f"app/assets/icons/{icon_name}{suffix}.svg")
        button.setIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon())
        button.setIconSize(QSize(17, 17))

    def _refresh_table_action_icons(self) -> None:
        for button in self.table.findChildren(QToolButton):
            icon_name = button.property("actionIcon")
            if icon_name:
                self._apply_table_action_icon(button, str(icon_name))

    def _show_skeleton_rows(self, row_count: int = 7) -> None:
        self._skeleton_active = True
        self._skeleton_blocks.clear()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearSelection()
            self.table.setRowCount(0)
            for row in range(row_count):
                self.table.insertRow(row)
                self.table.setRowHeight(row, 72)
                for column in range(self.table.columnCount()):
                    item = QTableWidgetItem("")
                    item.setFlags(Qt.NoItemFlags)
                    self.table.setItem(row, column, item)
                    self.table.setCellWidget(row, column, self._skeleton_cell(column, row))
        finally:
            self.table.setUpdatesEnabled(True)
        self._start_loading_animation()

    def _clear_skeleton_rows(self) -> None:
        if not self._skeleton_active:
            return
        self._skeleton_active = False
        self._skeleton_blocks.clear()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
        finally:
            self.table.setUpdatesEnabled(True)

    def _skeleton_cell(self, column: int, row: int) -> QWidget:
        container = QWidget()
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if column in {3, 4, self.STATUS_COLUMN}:
            layout = QVBoxLayout(container)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)
            layout.setAlignment(Qt.AlignCenter)
            first_width = {3: 92, 4: 80, self.STATUS_COLUMN: 76}.get(column, 80)
            second_width = {3: 54, 4: 62, self.STATUS_COLUMN: 58}.get(column, 54)
            layout.addWidget(self._skeleton_block(first_width, 12), 0, Qt.AlignCenter)
            layout.addWidget(self._skeleton_block(second_width, 10), 0, Qt.AlignCenter)
            return container
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter if column != self.REMARK_COLUMN else Qt.AlignLeft | Qt.AlignVCenter)
        if column == self.SCENE_COLUMN:
            layout.addWidget(self._skeleton_block(34, 12))
            layout.addWidget(self._skeleton_block(34, 12))
        else:
            widths = {
                0: 24,
                1: 104,
                2: 132,
                5: 48,
                self.REMARK_COLUMN: 150,
                self.ACTION_COLUMN: 48,
            }
            layout.addWidget(self._skeleton_block(widths.get(column, 76), 12))
        return container

    def _skeleton_block(self, width: int, height: int) -> QFrame:
        block = QFrame()
        block.setObjectName("videoSkeletonBlock")
        block.setFixedSize(width, height)
        block.setStyleSheet(f"background: {self._skeleton_colors[0]}; border-radius: 6px; border: none;")
        self._skeleton_blocks.append(block)
        return block

    def _request_video_load(self, rebuild: bool = False, show_notice: bool = True) -> None:
        if self._load_worker is not None:
            self._pending_load = True
            self._pending_load_rebuild = self._pending_load_rebuild or bool(rebuild)
            self._pending_load_show_notice = self._pending_load_show_notice or bool(show_notice)
            self.logger.info("视频查询加载进行中，已合并后续刷新请求：rebuild=%s", rebuild)
            return

        filters = self._current_query_filters(self._current_upload_status_filter())
        self._load_request_id += 1
        request_id = self._load_request_id
        cache_key = None if rebuild else self._query_cache_key(filters, self.page_size, self.current_page)
        if cache_key is not None and cache_key in self._query_cache:
            self.logger.debug("video_query_perf cache_hit request=%s key=%s", request_id, cache_key)
            QTimer.singleShot(
                0,
                lambda payload=dict(self._query_cache[cache_key]), rid=request_id, notice=show_notice: self._on_video_load_finished(
                    rid, payload, notice
                ),
            )
            return
        loading_message = "正在加载视频数据…" if self.table.rowCount() == 0 or not self._has_loaded_once else "正在查询…"
        self._show_loading_state(loading_message)
        self.logger.info(
            "视频查询后台加载开始：request=%s, dir=%s, rebuild=%s, page=%s, page_size=%s",
            request_id,
            self.video_dir,
            rebuild,
            self.current_page,
            self.page_size,
        )
        worker = VideoQueryLoadWorker(
            request_id=request_id,
            database=self.database,
            video_dir=self.video_dir,
            filters=filters,
            page_size=self.page_size,
            current_page=self.current_page,
            rebuild=rebuild,
            logger=self.logger,
            parent=self,
        )
        self._request_cache_keys[request_id] = cache_key
        self._load_worker = worker
        worker.loaded.connect(lambda rid, payload, notice=show_notice: self._on_video_load_finished(rid, payload, notice))
        worker.failed.connect(lambda rid, error, notice=show_notice: self._on_video_load_failed(rid, error, notice))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _show_loading_state(self, message: str) -> None:
        show_skeleton = self.table.rowCount() == 0 or self._skeleton_active
        if show_skeleton:
            self._show_skeleton_rows(7 if not self._has_loaded_once else 5)
            self.total_count_label.setText("正在加载...")
        self._show_table_state("loading", message)

    def _on_video_load_finished(self, request_id: int, payload: object, show_notice: bool) -> None:
        if request_id != self._load_request_id:
            self.logger.info("忽略过期视频查询结果：request=%s, current=%s", request_id, self._load_request_id)
            return
        self._load_worker = None
        result = payload if isinstance(payload, dict) else {}
        rows = result.get("rows") or []
        self.total_count = int(result.get("total_count") or 0)
        self.total_pages = int(result.get("total_pages") or 1)
        self.current_page = int(result.get("current_page") or 1)
        offset = int(result.get("offset") or 0)
        rebuild = bool(result.get("rebuild"))
        render_started = time.perf_counter()
        self._render_rows(rows, offset)
        if self._restore_scroll_after_load is not None:
            scroll_value = self._restore_scroll_after_load
            self._restore_scroll_after_load = None
            QTimer.singleShot(
                0,
                lambda value=scroll_value: self.table.verticalScrollBar().setValue(
                    min(value, self.table.verticalScrollBar().maximum())
                ),
            )
        render_ms = (time.perf_counter() - render_started) * 1000
        cache_key = self._request_cache_keys.pop(request_id, None)
        if cache_key is not None and not rebuild:
            self._query_cache[cache_key] = dict(result)
        if rows:
            self._hide_table_state()
        else:
            self._show_table_state(
                "empty",
                "暂无符合条件的视频记录",
                "请调整筛选条件或检查视频存储目录。",
            )
        self._has_loaded_once = True
        self.video_query_dirty = False
        self.logger.info(
            "视频查询后台加载完成：request=%s, rows=%s, total=%s, page=%s/%s, rebuild=%s",
            request_id,
            len(rows),
            self.total_count,
            self.current_page,
            self.total_pages,
            rebuild,
        )
        timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
        total_ms = float(timings.get("total", 0.0) or 0.0) + render_ms
        page_open_ms = (time.perf_counter() - self._page_open_started_at) * 1000 if not self._has_loaded_once else 0.0
        self.logger.debug(
            "video_query_perf request=%s page_open=%.2fms scan_directory=%.2fms count_query=%.2fms page_query=%.2fms data_process=%.2fms render_table=%.2fms total=%.2fms",
            request_id,
            page_open_ms,
            float(timings.get("scan_directory", 0.0) or 0.0),
            float(timings.get("count_query", 0.0) or 0.0),
            float(timings.get("page_query", 0.0) or 0.0),
            0.0,
            render_ms,
            total_ms,
        )
        if show_notice:
            if rebuild:
                self._show_notice("列表已刷新。", "success")
            if not rows:
                self._show_notice("当前目录未找到视频文件。", "warning")
        self._consume_pending_video_load()

    def _on_video_load_failed(self, request_id: int, error: str, _show_notice: bool) -> None:
        if request_id != self._load_request_id:
            return
        self._load_worker = None
        self._request_cache_keys.pop(request_id, None)
        if self._skeleton_active:
            self._clear_skeleton_rows()
        self._show_table_state(
            "error",
            "视频数据加载失败",
            "请稍后重新加载，或检查视频存储目录。",
            error,
        )
        self._show_notice(f"刷新失败：{error}", "error")
        self.logger.error("视频查询后台加载失败：request=%s, error=%s", request_id, error)
        self._consume_pending_video_load()

    def _consume_pending_video_load(self) -> None:
        if not self._pending_load:
            return
        rebuild = self._pending_load_rebuild
        show_notice = self._pending_load_show_notice
        self._pending_load = False
        self._pending_load_rebuild = False
        self._pending_load_show_notice = False
        QTimer.singleShot(0, lambda: self.refresh(rebuild=rebuild, show_notice=show_notice))

    def _on_search_text_changed(self, text: str) -> None:
        self.search_debounce_timer.start()
        if not text:
            QTimer.singleShot(0, lambda: self.search_input.setFocus(Qt.OtherFocusReason))

    def _apply_filter(self, reset_page: bool = False) -> None:
        keyword = self.search_input.text().strip()
        date_from, date_to = self._date_range()
        record_type = self._current_record_type_filter()
        upload_status = self._current_upload_status_filter()
        if reset_page:
            self.current_page = 1
        self.logger.info(
            "视频存储目录搜索和日期筛选：dir=%s, keyword=%s, date_from=%s, date_to=%s, record_type=%s, upload_status=%s",
            self.video_dir,
            keyword,
            date_from,
            date_to,
            record_type or "全部",
            upload_status or "全部",
        )
        self._request_video_load(rebuild=False, show_notice=False)

    def _render_rows(self, rows: list[dict[str, Any]], offset: int) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self._skeleton_active = False
            self._skeleton_blocks.clear()
            self.table.setRowCount(0)
            self.empty_label.hide()
            for row_index, item in enumerate(rows):
                path = Path(str(item.get("file_path", "")))
                self.table.insertRow(row_index)
                self.table.setRowHeight(row_index, 72)
                self._set_item(row_index, 0, str(offset + row_index + 1), path)
                self._set_order_no_item(row_index, item, path)
                self._set_item(row_index, 2, self._recording_time_text(item), path)
                self._set_two_line_item(
                    row_index,
                    3,
                    str(item.get("resolution") or "-"),
                    str(item.get("codec") or "-"),
                    path,
                )
                self._set_two_line_item(
                    row_index,
                    4,
                    str(item.get("file_size_text") or "-"),
                    self._duration_text(item),
                    path,
                    second_line_state="warning" if self._has_short_duration_warning(item) else None,
                    second_line_tooltip="时长过短" if self._has_short_duration_warning(item) else "",
                )
                self._set_record_type_cell(row_index, item, path)
                self._set_remark_item(row_index, item, path)
                self._set_status_item(row_index, item, path)
                self._set_scene_video_cell(row_index, item, path)
                self._set_delete_button(row_index, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self._update_pagination_bar()

    def _set_item(self, row: int, column: int, text: str, path: Path) -> None:
        item = QTableWidgetItem(text)
        item.setData(Qt.UserRole, str(path))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, column, item)

    def _set_order_no_item(self, row: int, entry: dict[str, Any], path: Path) -> None:
        order_no = str(entry.get("order_no") or "-")
        self.table.removeCellWidget(row, 1)
        item = QTableWidgetItem(order_no)
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, order_no)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 1, item)

    def _set_two_line_item(
        self,
        row: int,
        column: int,
        first_line: str,
        second_line: str,
        path: Path,
        second_line_state: str | None = None,
        second_line_tooltip: str = "",
    ) -> None:
        copy_text = f"{first_line} / {second_line}"
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, copy_text)
        if second_line_tooltip:
            item.setToolTip(second_line_tooltip)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, column, item)

        container = QWidget()
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel(first_line)
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("tablePrimaryText")
        subtitle = QLabel(second_line)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("tableSubText")
        if second_line_state:
            subtitle.setProperty("state", second_line_state)
            if second_line_tooltip:
                subtitle.setToolTip(second_line_tooltip)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.table.setCellWidget(row, column, container)

    def _set_record_type_cell(self, row: int, entry: dict[str, Any], path: Path) -> None:
        current_type = self._normalize_record_type(entry.get("record_type"))
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, current_type)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.RECORD_TYPE_COLUMN, item)

        container = QWidget()
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setAlignment(Qt.AlignCenter)
        tag = QLabel(current_type)
        tag.setObjectName("recordTypeTag")
        tag.setProperty("recordType", "return" if current_type == "退货" else "ship")
        tag.setAlignment(Qt.AlignCenter)
        layout.addWidget(tag)
        self.table.setCellWidget(row, self.RECORD_TYPE_COLUMN, container)

    def _set_remark_item(self, row: int, entry: dict[str, Any], path: Path) -> None:
        display_text, tooltip, remark, important = self._remark_display_parts(entry)
        item = QTableWidgetItem(display_text)
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, tooltip or display_text)
        item.setData(self.RECORD_ID_ROLE, self._record_id_from_entry(entry))
        item.setToolTip(tooltip)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if important:
            item.setForeground(QColor("#DC2626"))
        elif not remark:
            item.setForeground(QColor("#64748b"))
        else:
            item.setForeground(QColor("#1f2937"))
        self.table.setItem(row, self.REMARK_COLUMN, item)

    def _remark_display_parts(self, entry: dict[str, Any]) -> tuple[str, str, str, bool]:
        return build_remark_display_parts(entry)

    @staticmethod
    def _record_id_from_entry(entry: dict[str, Any]) -> int:
        try:
            record_id = int(entry.get("id") or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, record_id)

    @staticmethod
    def _is_important_entry(entry: dict[str, Any]) -> bool:
        return build_is_important_entry(entry)

    @classmethod
    def _important_tooltip(cls, entry: dict[str, Any]) -> str:
        reason_text = cls._important_reason_text(entry)
        if reason_text:
            return f"重要或有争议的单号\n重要原因：{reason_text}"
        return "重要或有争议的单号"

    @staticmethod
    def _important_reason_text(entry: dict[str, Any]) -> str:
        return build_important_reason_text(entry)

    def _set_scene_video_cell(self, row: int, entry: dict[str, Any], path: Path) -> None:
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, str(path))
        item.setToolTip(str(path))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.SCENE_COLUMN, item)

        container = QWidget()
        container.setObjectName("tableSceneActionCell")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        open_button = QToolButton()
        open_button.setObjectName("sceneOpenIconButton")
        open_button.setProperty("actionIcon", "play")
        open_button.setFixedSize(30, 30)
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setToolTip("打开视频")
        open_button.setAccessibleName("打开视频")
        self._apply_table_action_icon(open_button, "play")
        open_button.clicked.connect(lambda _checked=False, video_path=path: self._open_scene_video(video_path))

        reveal_button = QToolButton()
        reveal_button.setObjectName("sceneRevealIconButton")
        reveal_button.setProperty("actionIcon", "folder-open")
        reveal_button.setFixedSize(30, 30)
        reveal_button.setCursor(Qt.PointingHandCursor)
        reveal_button.setToolTip("定位文件")
        reveal_button.setAccessibleName("定位文件")
        self._apply_table_action_icon(reveal_button, "folder-open")
        reveal_button.clicked.connect(lambda _checked=False, video_path=path: self._reveal_scene_video(video_path))

        layout.addWidget(open_button)
        layout.addWidget(reveal_button)
        self.table.setCellWidget(row, self.SCENE_COLUMN, container)

    def _set_video_name_item(self, row: int, entry: dict[str, Any]) -> None:
        path = Path(str(entry.get("file_path", "")))
        item = QTableWidgetItem(str(entry.get("file_name", "")))
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(entry.get("file_name", "")))
        item.setForeground(QColor("#0b5cad"))
        font = QFont(item.font())
        font.setUnderline(True)
        item.setFont(font)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setItem(row, 2, item)

    def _set_path_item(self, row: int, entry: dict[str, Any]) -> None:
        path = Path(str(entry.get("file_path", "")))
        item = QTableWidgetItem(str(path))
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(path))
        item.setForeground(QColor("#0b5cad"))
        font = QFont(item.font())
        font.setUnderline(True)
        item.setFont(font)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setItem(row, self.SCENE_COLUMN, item)

    def _set_status_item(self, row: int, entry: dict[str, Any], path: Path) -> None:
        copy_text = self._status_text(entry, self._netdisk_sync_enabled())
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, copy_text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.STATUS_COLUMN, item)

        container = QWidget()
        container.setObjectName("statusCell")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        status = str(entry.get("status") or ("正常" if bool(entry.get("exists", True)) else MISSING_STATUS))
        normal_status = status == "正常"
        status_line = QWidget()
        status_line.setObjectName("statusLine")
        status_line_layout = QHBoxLayout(status_line)
        status_line_layout.setContentsMargins(0, 0, 0, 0)
        status_line_layout.setSpacing(5)
        status_line_layout.setAlignment(Qt.AlignCenter)

        status_label = QLabel(status)
        status_label.setObjectName("statusText")
        status_label.setProperty("statusState", "normal" if normal_status else "error")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setMinimumHeight(18)
        status_line_layout.addWidget(status_label, 0, Qt.AlignCenter)

        duplicate_count = int(entry.get("duplicate_count") or 0)
        duplicate_sequence = int(entry.get("duplicate_sequence") or 0)
        tooltip_parts: list[str] = []
        if normal_status and bool(entry.get("is_duplicate")) and duplicate_count > 1 and duplicate_sequence > 0:
            duplicate_tip = f"该单号第 {duplicate_sequence} 次录制，共 {duplicate_count} 次"
            tooltip_parts.append(duplicate_tip)
            badge = ClickableLabel(f"重复第 {duplicate_sequence} 次")
            badge.setObjectName("duplicateBadge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setToolTip(duplicate_tip)
            badge.setCursor(Qt.PointingHandCursor)
            badge.setWordWrap(False)
            badge.setMinimumHeight(20)
            badge.setMinimumWidth(badge.sizeHint().width() + 8)
            badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            badge.clicked.connect(lambda row_entry=dict(entry): self._show_duplicate_records(row_entry))
            status_line_layout.addWidget(badge, 0, Qt.AlignCenter)

        validation_error = str(entry.get("validation_error") or "").strip()
        if validation_error:
            tooltip_parts.append(f"校验错误：{validation_error}")
        hash_verify_status = str(entry.get("hash_verify_status") or "").strip()
        if hash_verify_status == "不一致":
            tooltip_parts.append("哈希校验不一致")

        layout.addWidget(status_line, 0, Qt.AlignCenter)

        if self._netdisk_sync_enabled() and normal_status:
            upload_status = str(entry.get("upload_status") or UPLOAD_PENDING)
            upload_label = QLabel(upload_status)
            upload_label.setObjectName("uploadStatusText")
            upload_label.setProperty("uploadState", self._upload_state_name(upload_status))
            upload_label.setAlignment(Qt.AlignCenter)
            upload_label.setMinimumHeight(16)
            upload_error = str(entry.get("upload_error") or "").strip()
            upload_remote_path = str(entry.get("upload_remote_path") or "").strip()
            if upload_error:
                tooltip_parts.append(f"上传错误：{upload_error}")
            if upload_remote_path:
                tooltip_parts.append(f"远程路径：{upload_remote_path}")
            if upload_status == UPLOAD_FAILED and upload_error:
                upload_label.setToolTip(upload_error)
            layout.addWidget(upload_label)

        if tooltip_parts:
            item.setToolTip("\n".join(tooltip_parts))

        self.table.setCellWidget(row, self.STATUS_COLUMN, container)

    def _set_delete_button(self, row: int, entry: dict[str, Any]) -> None:
        path = Path(str(entry.get("file_path", "")))
        container = QWidget()
        container.setObjectName("tableActionCell")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        if self._should_show_upload_action(entry, path):
            upload_status = str(entry.get("upload_status") or UPLOAD_PENDING)
            upload_button = QToolButton()
            upload_button.setObjectName("tableUploadIconButton")
            upload_button.setProperty("actionIcon", "upload")
            upload_button.setFixedSize(30, 30)
            upload_button.setEnabled(upload_status != UPLOAD_UPLOADING)
            upload_button.setCursor(Qt.PointingHandCursor)
            upload_button.setAccessibleName("上传" if upload_status != UPLOAD_UPLOADING else "上传中")
            upload_button.setToolTip("上传" if upload_status != UPLOAD_UPLOADING else "上传中")
            self._apply_table_action_icon(upload_button, "upload")
            upload_button.clicked.connect(lambda _checked=False, row_entry=dict(entry): self._upload_single_video(row_entry))
            layout.addWidget(upload_button)

        button = QToolButton()
        button.setObjectName("tableDangerIconButton")
        button.setProperty("actionIcon", "trash")
        button.setFixedSize(30, 30)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("video_path", str(path))
        button.setAccessibleName("删除")
        button.setToolTip("删除")
        self._apply_table_action_icon(button, "trash")
        button.clicked.connect(lambda _checked=False, video_path=path: self._delete_video(video_path))
        layout.addWidget(button)
        self.table.setCellWidget(row, self.ACTION_COLUMN, container)

    def _netdisk_config(self) -> dict[str, Any]:
        return normalize_netdisk_config(self.config_manager.config.get("netdisk_sync", {}))

    def _netdisk_sync_enabled(self) -> bool:
        return bool(self._netdisk_config().get("enabled", False))

    def _netdisk_has_auth(self) -> bool:
        config = self._netdisk_config()
        return bool(config.get("access_token") or config.get("refresh_token"))

    def _cloud_sync_config(self) -> dict[str, Any]:
        return normalize_cloud_sync_config(self.config_manager.config.get("cloud_sync", {}))

    def _auto_sync_enabled(self) -> bool:
        config = self._cloud_sync_config()
        return self._netdisk_sync_enabled() and bool(config.get("auto_sync_enabled", False))

    def _auto_sync_delay_minutes(self) -> int:
        return int(self._cloud_sync_config().get("auto_sync_delay_minutes") or 10)

    def _can_control_netdisk_stop(self) -> bool:
        return self.auto_sync_state == "countdown" or self.is_netdisk_syncing()

    def _toggle_extended_filters(self) -> None:
        self.extended_filters_expanded = not bool(getattr(self, "extended_filters_expanded", True))
        self._apply_extended_filters_visibility()

    def _apply_extended_filters_visibility(self) -> None:
        if not hasattr(self, "extended_filters_toggle_button"):
            return
        expanded = bool(getattr(self, "extended_filters_expanded", True))
        netdisk_enabled = self._netdisk_sync_enabled()
        if hasattr(self, "netdisk_filter_row"):
            self.netdisk_filter_row.setVisible(netdisk_enabled and expanded)
        if hasattr(self, "detail_filter_row"):
            self.detail_filter_row.setVisible(expanded)
        icon_name = "chevron-up.svg" if expanded else "chevron-down.svg"
        self.extended_filters_toggle_button.setIcon(QIcon(str(resource_path(f"app/assets/icons/{icon_name}"))))
        self.extended_filters_toggle_button.setToolTip("收起扩展筛选" if expanded else "展开扩展筛选")

    def _update_netdisk_controls(self) -> None:
        enabled = self._netdisk_sync_enabled()
        license_allowed = self.license_manager is None or self.license_manager.can_upload()
        self.sync_netdisk_button.setVisible(enabled)
        self.sync_netdisk_button.setEnabled(enabled and license_allowed and not self.is_netdisk_syncing())
        self.sync_netdisk_button.setText("同步中..." if self.is_netdisk_syncing() else "同步至网盘")
        self.stop_netdisk_button.setVisible(enabled)
        self.stop_netdisk_button.setEnabled(enabled and self._can_control_netdisk_stop() and self.auto_sync_state != "stopping")
        self.stop_netdisk_button.setText("正在停止..." if self.auto_sync_state == "stopping" else "停止同步")
        self.netdisk_history_button.setVisible(enabled)
        self.netdisk_history_button.setEnabled(enabled)
        self.netdisk_auto_status_label.setVisible(enabled)
        for widget in getattr(self, "upload_status_filter_widgets", ()):
            if widget is getattr(self, "netdisk_filter_row", None):
                continue
            widget.setVisible(enabled)
        self._apply_extended_filters_visibility()
        if not enabled and self.upload_status_filter != "全部":
            self.upload_status_filter = "全部"
            self._sync_upload_status_filter_buttons()
        self.table.setColumnWidth(self.STATUS_COLUMN, 170 if enabled else 152)
        self.table.setColumnWidth(self.ACTION_COLUMN, 80 if enabled else 56)
        if not enabled and not self.is_netdisk_syncing():
            self._hide_netdisk_progress()
            self._cancel_auto_sync_countdown(update_controls=False)
            self._set_auto_sync_status("")

    def _license_allows_upload(self, *, auto_sync: bool = False, show_notice: bool = True) -> bool:
        if self.license_manager is None:
            return True
        allowed = self.license_manager.can_auto_sync() if auto_sync else self.license_manager.can_upload()
        if not allowed and show_notice:
            self._show_notice("当前授权需要联网验证，暂时不能上传视频。", "warning")
        return allowed

    def _on_license_status_changed(self, _status: str) -> None:
        self._update_netdisk_controls()

    def on_recording_state_changed(self, recording: bool, _order_id: str = "", _start_time: str = "") -> None:
        self._recording_active_for_auto_sync = bool(recording)
        if recording:
            if self.auto_sync_state == "countdown":
                self._cancel_auto_sync_countdown("自动同步：录制中，已暂停")
            if self.upload_worker is not None and self.netdisk_task_mode == "auto":
                self._auto_sync_pause_after_current = True
                self.auto_sync_state = "paused_for_recording"
                if hasattr(self.upload_worker, "stop_after_current"):
                    self.upload_worker.stop_after_current()
                else:
                    self.upload_worker.stop()
                self._set_auto_sync_status("自动同步：录制中，已暂停")
                self._update_netdisk_controls()
            return
        if self.auto_sync_state == "paused_for_recording" and self.upload_worker is None:
            self._set_auto_sync_status("自动同步：等待录制保存完成")
        elif self.auto_sync_state == "idle" and self.netdisk_auto_status_label.text().startswith("自动同步：录制中"):
            self._set_auto_sync_status("")
        self._update_netdisk_controls()

    def on_recording_status_message(self, message: str) -> None:
        if self._is_successful_recording_saved_message(message):
            self.mark_dirty()
            self._schedule_auto_sync_countdown("recording_saved")

    @staticmethod
    def _is_successful_recording_saved_message(message: str) -> bool:
        text = (message or "").strip()
        return (
            text.startswith("视频保存成功")
            or text.startswith("视频已保存并校验通过")
            or text.startswith("视频已保存，但时长过短")
        )

    def _set_auto_sync_status(self, message: str) -> None:
        if not hasattr(self, "netdisk_auto_status_label"):
            return
        self.netdisk_auto_status_label.setText(message)
        self.netdisk_auto_status_label.setToolTip(message)

    def _format_auto_sync_remaining(self) -> str:
        if self.auto_sync_deadline is None:
            return "00:00"
        seconds = max(0, int((self.auto_sync_deadline - datetime.now()).total_seconds()))
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _cancel_auto_sync_countdown(self, message: str = "", update_controls: bool = True) -> None:
        if self.auto_sync_timer.isActive():
            self.auto_sync_timer.stop()
        self.auto_sync_deadline = None
        if self.auto_sync_state == "countdown":
            self.auto_sync_state = "idle"
        if message:
            self._set_auto_sync_status(message)
        if update_controls:
            self._update_netdisk_controls()

    def _schedule_auto_sync_countdown(self, reason: str = "") -> None:
        if not self._license_allows_upload(auto_sync=True, show_notice=False):
            self._cancel_auto_sync_countdown(update_controls=True)
            return
        if not self._auto_sync_enabled():
            self._cancel_auto_sync_countdown(update_controls=True)
            return
        if self._recording_active_for_auto_sync:
            self._cancel_auto_sync_countdown("自动同步：录制中，已暂停")
            return
        if self.is_netdisk_syncing():
            return
        if not self._netdisk_has_auth():
            self._set_auto_sync_status("自动同步：等待网盘授权")
            self._update_netdisk_controls()
            return
        if not self._has_auto_sync_candidates():
            self.auto_sync_state = "idle"
            self._set_auto_sync_status("")
            self._update_netdisk_controls()
            return
        delay_minutes = self._auto_sync_delay_minutes()
        self.auto_sync_deadline = datetime.now() + timedelta(minutes=delay_minutes)
        self.auto_sync_state = "countdown"
        self.auto_sync_timer.start()
        self._set_auto_sync_status(f"自动同步：等待中，{self._format_auto_sync_remaining()} 后开始")
        self._update_netdisk_controls()
        self.logger.info("自动同步倒计时已启动：reason=%s, delay_minutes=%s", reason or "-", delay_minutes)

    def _maybe_schedule_auto_sync_on_startup(self) -> None:
        if self.auto_sync_state not in {"idle", "stopped"}:
            return
        if self._recording_active_for_auto_sync:
            return
        self._schedule_auto_sync_countdown("startup")

    def _on_auto_sync_timer_tick(self) -> None:
        if self.auto_sync_state != "countdown" or self.auto_sync_deadline is None:
            self.auto_sync_timer.stop()
            return
        remaining_seconds = int((self.auto_sync_deadline - datetime.now()).total_seconds())
        if remaining_seconds <= 0:
            self.auto_sync_timer.stop()
            self.auto_sync_deadline = None
            self._start_auto_sync_upload()
            return
        self._set_auto_sync_status(f"自动同步：等待中，{self._format_auto_sync_remaining()} 后开始")

    def _has_auto_sync_candidates(self) -> bool:
        return bool(self._collect_netdisk_upload_entries(limit=1, mark_missing=False))

    def _collect_netdisk_upload_entries(self, limit: int = 5000, mark_missing: bool = False) -> list[dict[str, Any]]:
        candidates = self.database.query_upload_candidates(self.video_dir, include_failed=False, limit=limit)
        upload_entries: list[dict[str, Any]] = []
        missing_count = 0
        invalid_count = 0
        for entry in candidates:
            path = Path(str(entry.get("file_path") or ""))
            if not path.exists():
                missing_count += 1
                if mark_missing:
                    try:
                        self.database.mark_file_missing(path)
                    except Exception:
                        self.logger.exception("网盘同步跳过文件不存在视频时标记失败：%s", path)
                continue
            try:
                if path.stat().st_size <= 0:
                    invalid_count += 1
                    continue
            except OSError:
                invalid_count += 1
                continue
            upload_entries.append(entry)
        if missing_count:
            self.logger.warning("网盘同步跳过文件不存在视频：%s 条", missing_count)
        if invalid_count:
            self.logger.warning("网盘同步跳过本地文件不可用视频：%s 条", invalid_count)
        return upload_entries

    def _start_auto_sync_upload(self) -> None:
        if not self._license_allows_upload(auto_sync=True, show_notice=False):
            self.auto_sync_state = "idle"
            self._set_auto_sync_status("自动同步：当前授权不可用")
            self._update_netdisk_controls()
            return
        if not self._auto_sync_enabled():
            self.auto_sync_state = "idle"
            self._set_auto_sync_status("")
            self._update_netdisk_controls()
            return
        if self._recording_active_for_auto_sync:
            self.auto_sync_state = "paused_for_recording"
            self._set_auto_sync_status("自动同步：录制中，已暂停")
            self._update_netdisk_controls()
            return
        if self.is_netdisk_syncing():
            return
        if not self._netdisk_has_auth():
            self.auto_sync_state = "idle"
            self._set_auto_sync_status("自动同步：等待网盘授权")
            self._update_netdisk_controls()
            return
        upload_entries = self._collect_netdisk_upload_entries(mark_missing=False)
        if not upload_entries:
            self.auto_sync_state = "idle"
            self._set_auto_sync_status("")
            self._update_netdisk_controls()
            return
        self.auto_sync_state = "uploading"
        self._set_auto_sync_status(f"自动同步：正在上传 0/{len(upload_entries)}")
        self._start_netdisk_upload(upload_entries, mode="auto")

    def _stop_netdisk_sync(self) -> None:
        if self.auto_sync_state == "countdown":
            if not confirm_action(
                self,
                title="停止同步",
                heading="确定停止本次自动同步吗？",
                description="已完成的状态会保留，尚未开始的文件不会上传。",
                confirm_text="停止同步",
                destructive=True,
            ):
                return
            self._cancel_auto_sync_countdown("自动同步：已停止")
            self.auto_sync_state = "stopped"
            self._set_auto_sync_status("自动同步：已停止")
            self._show_notice("同步已停止", "info")
            self._update_netdisk_controls()
            return
        if self.upload_worker is None:
            return
        if not confirm_action(
            self,
            title="停止同步",
            heading="确定安全停止当前同步任务吗？",
            description="当前文件会按现有安全停止规则处理，尚未完成的文件可稍后重试。",
            confirm_text="停止同步",
            destructive=True,
        ):
            return
        self.auto_sync_state = "stopping"
        self._auto_sync_stop_requested = True
        self._set_auto_sync_status("同步：正在停止")
        self._update_netdisk_controls()
        if hasattr(self.upload_worker, "stop_after_current"):
            self.upload_worker.stop_after_current()
        else:
            self.upload_worker.stop()
        self.logger.info("用户请求停止网盘同步：mode=%s", self.netdisk_task_mode)

    def _should_show_upload_action(self, entry: dict[str, Any], path: Path) -> bool:
        if not self._netdisk_sync_enabled():
            return False
        if self.is_netdisk_syncing():
            return False
        status = str(entry.get("status") or "")
        if status and status != NORMAL_STATUS:
            return False
        if not path.exists():
            return False
        upload_status = str(entry.get("upload_status") or UPLOAD_PENDING)
        return upload_status in {UPLOAD_PENDING, UPLOAD_FAILED, UPLOAD_UPLOADING}

    @staticmethod
    def _upload_state_name(upload_status: str) -> str:
        if upload_status == UPLOAD_DONE:
            return "done"
        if upload_status == UPLOAD_UPLOADING:
            return "uploading"
        if upload_status == UPLOAD_FAILED:
            return "failed"
        return "pending"

    def _show_netdisk_history(self) -> None:
        if not self._netdisk_sync_enabled():
            self._show_notice("请先开启网盘同步", "warning")
            return
        try:
            dialog = NetdiskHistoryDialog(self.database, self.logger, self)
            self.netdisk_history_dialog = dialog
            dialog.exec()
        except Exception as exc:
            self.logger.exception("打开网盘同步记录窗口失败")
            self._show_notice(f"打开同步记录失败：{exc}", "error")
        finally:
            self.netdisk_history_dialog = None

    def _toggle_important(self, entry: dict[str, Any]) -> None:
        record_id = self._record_id_from_entry(entry)
        if record_id <= 0:
            self._show_notice("未找到视频记录", "warning")
            return
        try:
            latest = self.database.get_video_by_id(record_id)
            if latest is None:
                self._show_notice("未找到视频记录", "warning")
                return
            order_no = str(latest.get("order_no") or "-")
            if self._is_important_entry(latest):
                if not confirm_action(
                    self,
                    title="取消重要标记",
                    heading="确定要取消该视频的重要标记吗？",
                    info_label="单号",
                    info_value=order_no,
                    confirm_text="确认取消",
                ):
                    return
                affected = self.database.update_video_importance(record_id, False)
                if affected != 1:
                    self._show_notice("取消重要标记失败：未找到对应记录", "error")
                    return
                self.logger.info("取消重要标记：id=%s, order_no=%s", record_id, order_no)
                self._show_notice("已取消重要标记", "success")
            else:
                dialog = ImportantMarkDialog(order_no, self)
                if dialog.exec() != QDialog.Accepted:
                    return
                note = dialog.note()
                affected = self.database.update_video_importance(record_id, True, note, dialog.reason_type(), dialog.custom_reason())
                if affected != 1:
                    self._show_notice("标记重要失败：未找到对应记录", "error")
                    return
                self.logger.info(
                    "标记重要：id=%s, order_no=%s, reason=%s, note_len=%s",
                    record_id,
                    order_no,
                    dialog.reason_type(),
                    len(note),
                )
                self._show_notice("已标记为重要", "success")
            self.refresh(rebuild=False, show_notice=False)
        except Exception as exc:
            self.logger.exception("修改重要标记失败：id=%s", record_id)
            self._show_notice(f"修改重要标记失败：{exc}", "error")

    def _sync_unuploaded_videos(self) -> None:
        if not self._license_allows_upload():
            return
        if self.auto_sync_state == "countdown":
            self._cancel_auto_sync_countdown(update_controls=False)
            self._set_auto_sync_status("")
        if not self._ensure_netdisk_ready():
            return
        upload_entries = self._collect_netdisk_upload_entries(mark_missing=True)
        if not upload_entries:
            self.refresh(rebuild=False, show_notice=False)
            self._show_notice("没有需要同步到网盘的视频。", "info")
            return
        self._start_netdisk_upload(upload_entries, mode="sync")

    def _upload_single_video(self, entry: dict[str, Any]) -> None:
        if not self._license_allows_upload():
            return
        if not self._ensure_netdisk_ready():
            return
        path = Path(str(entry.get("file_path") or ""))
        if not path.exists():
            self.database.mark_file_missing(path)
            self.refresh(rebuild=False, show_notice=False)
            self._show_notice("视频文件不存在", "warning")
            return
        mode = "retry" if str(entry.get("upload_status") or "") == UPLOAD_FAILED else "sync"
        self._start_netdisk_upload([entry], mode=mode)

    def _retry_failed_uploads(self) -> None:
        if not self._license_allows_upload():
            return
        if not self._ensure_netdisk_ready():
            return
        selected_upload_status = self._current_upload_status_filter()
        if selected_upload_status and selected_upload_status != UPLOAD_FAILED:
            self._show_notice("当前没有需要重试的失败记录", "info")
            return
        filters = self._current_query_filters(UPLOAD_FAILED)
        filters["status"] = NORMAL_STATUS
        retry_entries = self.database.query_videos({**filters, "limit": 5000, "offset": 0})
        upload_entries: list[dict[str, Any]] = []
        skipped_count = 0
        for entry in retry_entries:
            path = Path(str(entry.get("file_path") or ""))
            if not path.exists():
                skipped_count += 1
                try:
                    self.database.mark_file_missing(path)
                except Exception:
                    self.logger.exception("重试上传失败时标记本地文件不存在失败：%s", path)
                continue
            try:
                if path.stat().st_size <= 0:
                    skipped_count += 1
                    continue
            except OSError:
                skipped_count += 1
                continue
            upload_entries.append(entry)

        if not upload_entries:
            self.refresh(rebuild=False, show_notice=False)
            self._show_notice("当前没有需要重试的失败记录", "info")
            return

        message = f"即将重试上传 {len(upload_entries)} 条失败记录，是否继续？"
        if skipped_count:
            message += f"\n已跳过 {skipped_count} 条本地文件不可用的记录。"
        if not confirm_action(
            self,
            title="重试上传失败",
            heading=f"即将重试上传 {len(upload_entries)} 条失败记录，是否继续？",
            description=f"已跳过 {skipped_count} 条本地文件不可用的记录。" if skipped_count else "",
            confirm_text="开始重试",
        ):
            return
        self._start_netdisk_upload(upload_entries, mode="retry")

    def _retry_failed_uploads_from_history(self, dialog: NetdiskHistoryDialog) -> None:
        if not self._license_allows_upload():
            return
        if not self._ensure_netdisk_ready():
            return
        selected_upload_status = dialog.current_status_filter()
        if selected_upload_status and selected_upload_status != UPLOAD_FAILED:
            self._show_notice("当前筛选条件下没有需要重试的失败记录", "info")
            return
        keyword = dialog.current_keyword()
        retry_entries = self.database.query_upload_history(UPLOAD_FAILED, keyword, limit=5000, offset=0)
        upload_entries: list[dict[str, Any]] = []
        skipped_count = 0
        for entry in retry_entries:
            if str(entry.get("status") or NORMAL_STATUS) != NORMAL_STATUS:
                skipped_count += 1
                continue
            path = Path(str(entry.get("file_path") or ""))
            if not path.exists():
                skipped_count += 1
                try:
                    self.database.mark_file_missing(path)
                except Exception:
                    self.logger.exception("同步记录重试上传失败时标记本地文件不存在失败：%s", path)
                continue
            try:
                if path.stat().st_size <= 0:
                    skipped_count += 1
                    continue
            except OSError:
                skipped_count += 1
                continue
            upload_entries.append(entry)

        if not upload_entries:
            dialog.reload_records(reset_page=False)
            self.refresh(rebuild=False, show_notice=False)
            self._show_notice("当前没有需要重试的失败记录", "info")
            return

        message = f"即将重试上传 {len(upload_entries)} 条失败记录，是否继续？"
        if skipped_count:
            message += f"\n已跳过 {skipped_count} 条本地文件不可用的记录。"
        if not confirm_action(
            dialog,
            title="重试上传失败",
            heading=f"即将重试上传 {len(upload_entries)} 条失败记录，是否继续？",
            description=f"已跳过 {skipped_count} 条本地文件不可用的记录。" if skipped_count else "",
            confirm_text="开始重试",
        ):
            return
        self.netdisk_history_dialog = dialog
        dialog.set_retry_running(True)
        dialog.show_retry_progress(0, len(upload_entries), "准备重试...", 0, 0)
        self._start_netdisk_upload(upload_entries, mode="retry")

    def _ensure_netdisk_ready(self) -> bool:
        if not self._netdisk_sync_enabled():
            self._show_notice("网盘同步未开启。", "warning")
            return False
        if self.is_netdisk_syncing():
            self._show_notice("网盘正在同步中，请稍候。", "warning")
            return False
        config = self._netdisk_config()
        if not config.get("client_id") or not config.get("client_secret"):
            self._show_notice("请先在设置中填写百度网盘 App Key 和 Secret Key。", "warning")
            return False
        if not self._netdisk_has_auth():
            self._show_notice("请先在设置中完成百度网盘授权", "warning")
            return False
        return True

    def _start_netdisk_upload(self, entries: list[dict[str, Any]], mode: str = "sync") -> None:
        if not self._license_allows_upload(auto_sync=mode == "auto", show_notice=mode != "auto"):
            return
        if not entries:
            return
        if self.upload_worker is not None:
            self._show_notice("网盘正在同步中，请稍候。", "warning")
            return
        if mode == "retry":
            self.netdisk_task_mode = "retry"
        elif mode == "auto":
            self.netdisk_task_mode = "auto"
        else:
            self.netdisk_task_mode = "sync"
        self._auto_sync_stop_requested = False
        self._auto_sync_pause_after_current = False
        task_label = "重试上传失败" if self.netdisk_task_mode == "retry" else ("自动同步" if self.netdisk_task_mode == "auto" else "同步")
        worker = NetdiskUploadWorker(
            config=self._netdisk_config(),
            database_path=self.database.db_path,
            video_root=self.config_manager.get_video_dir(),
            entries=entries,
            task_label=task_label,
            retry_failed=self.netdisk_task_mode == "retry",
            logger=self.logger,
            permission_checker=(
                self.license_manager.can_upload if self.license_manager is not None else None
            ),
            parent=self,
        )
        self.upload_worker = worker
        if self.netdisk_task_mode == "auto":
            self.auto_sync_state = "uploading"
        self._show_netdisk_progress(
            0,
            len(entries),
            "准备重试..." if self.netdisk_task_mode == "retry" else ("准备自动同步..." if self.netdisk_task_mode == "auto" else "准备同步..."),
            0,
            0,
        )
        worker.progress_changed.connect(self._on_netdisk_upload_progress)
        worker.row_changed.connect(self._on_upload_status_changed)
        worker.upload_failed.connect(self._on_netdisk_upload_failed)
        worker.tokens_refreshed.connect(self._save_netdisk_tokens)
        worker.finished_summary.connect(self._on_netdisk_upload_finished)
        worker.finished.connect(worker.deleteLater)
        self._update_netdisk_controls()
        self.refresh(rebuild=False, show_notice=False)
        self.logger.info("网盘%s任务开始：count=%s", task_label, len(entries))
        worker.start()

    def _show_netdisk_progress(self, current: int, total: int, file_name: str, success_count: int, fail_count: int) -> None:
        self.netdisk_progress_hide_timer.stop()
        total = max(1, int(total or 1))
        current = max(0, min(int(current or 0), total))
        self.netdisk_progress_bar.setRange(0, total)
        self.netdisk_progress_bar.setValue(current)
        if self.netdisk_task_mode == "retry":
            self.netdisk_progress_title.setText(f"正在重试上传失败：{current} / {total}")
        elif self.netdisk_task_mode == "auto":
            self.netdisk_progress_title.setText(f"自动同步：正在上传 {current} / {total}")
            self._set_auto_sync_status(f"自动同步：正在上传 {current}/{total}")
        else:
            self.netdisk_progress_title.setText(f"同步中：{current} / {total}")
        self.netdisk_progress_stats.setText(
            f"成功 {success_count} 个，<span style='color:#dc2626;'>失败 {fail_count} 个</span>"
            if fail_count
            else f"成功 {success_count} 个，失败 0 个"
        )
        self.netdisk_progress_current.setText(f"当前：{file_name}" if file_name else "")
        self.netdisk_progress_current.setToolTip(file_name or "")
        self.netdisk_progress_container.show()

    def _on_netdisk_upload_progress(self, current: int, total: int, file_name: str, success_count: int, fail_count: int) -> None:
        self._show_netdisk_progress(current, total, file_name, success_count, fail_count)
        if self.netdisk_task_mode == "retry" and self.netdisk_history_dialog is not None:
            self.netdisk_history_dialog.show_retry_progress(current, total, file_name, success_count, fail_count)

    def _on_upload_status_changed(self, file_path: str) -> None:
        """Update one visible row in the UI thread, then invalidate stale query cache entries."""
        path = Path(file_path)
        self._clear_query_cache()
        try:
            record = self.database.get_video_by_path(path)
        except Exception:
            self.logger.exception("读取上传状态更新失败：path=%s", path)
            record = None

        # A status filter can add or remove the current row, so it needs a full query.
        if record is None or self._current_upload_status_filter() is not None:
            self.reload_current_query(preserve_filters=True, preserve_page=True, preserve_scroll=True)
        else:
            for row in range(self.table.rowCount()):
                if self._path_from_row(row) != path:
                    continue
                self.table.setUpdatesEnabled(False)
                try:
                    self._set_status_item(row, record, path)
                    self._set_delete_button(row, record)
                finally:
                    self.table.setUpdatesEnabled(True)
                self.table.viewport().update()
                break
        self.video_list_changed.emit("upload_status_changed")

    def _hide_netdisk_progress(self) -> None:
        if hasattr(self, "netdisk_progress_container") and not self.is_netdisk_syncing():
            self.netdisk_progress_container.hide()

    def _on_netdisk_upload_failed(self, _file_path: str, error_text: str) -> None:
        message = (error_text or "未知原因").strip()
        self._show_notice(f"上传失败：{message}", "error", 7000)

    def _save_netdisk_tokens(self, tokens: dict[str, Any]) -> None:
        config = self._netdisk_config()
        config.update(tokens)
        try:
            self.config_manager.update({"netdisk_sync": config})
            self.logger.info("百度网盘 token 已刷新并保存")
        except Exception:
            self.logger.exception("保存百度网盘刷新 token 失败")

    def _on_netdisk_upload_finished(self, success_count: int, fail_count: int) -> None:
        finished_mode = self.netdisk_task_mode
        stopped_by_user = self._auto_sync_stop_requested
        paused_for_recording = self._auto_sync_pause_after_current and self._recording_active_for_auto_sync
        task_name = "重试" if finished_mode == "retry" else ("自动同步" if finished_mode == "auto" else "同步")
        self.logger.info("网盘%s任务结束：success=%s, failed=%s", task_name, success_count, fail_count)
        self.upload_worker = None
        self._update_netdisk_controls()
        self.reload_current_query(preserve_filters=True, preserve_page=True, preserve_scroll=True)
        self.video_list_changed.emit("sync_batch_finished")
        if finished_mode == "retry" and self.netdisk_history_dialog is not None:
            self.netdisk_history_dialog.show_retry_finished(success_count, fail_count)

        if stopped_by_user or paused_for_recording:
            self.auto_sync_state = "paused_for_recording" if paused_for_recording else "stopped"
            total = max(1, self.netdisk_progress_bar.maximum())
            done = min(total, max(0, success_count + fail_count))
            self.netdisk_progress_bar.setRange(0, total)
            self.netdisk_progress_bar.setValue(done)
            if paused_for_recording:
                self.netdisk_progress_title.setText(f"自动同步已暂停：已完成 {success_count} 个，失败 {fail_count} 个")
                self.netdisk_progress_current.setText("录制中，当前文件完成后已暂停剩余队列。")
                self._set_auto_sync_status("自动同步：录制中，已暂停")
            else:
                self.netdisk_progress_title.setText(f"同步已停止：已完成 {success_count} 个，失败 {fail_count} 个")
                self.netdisk_progress_current.setText("尚未开始上传的记录保持未上传。")
                self._set_auto_sync_status("自动同步：已停止" if finished_mode == "auto" else "同步：已停止")
                self._show_notice("同步已停止", "info", 4000)
            self.netdisk_progress_stats.setText(
                f"成功 {success_count} 个，<span style='color:#dc2626;'>失败 {fail_count} 个</span>"
                if fail_count
                else f"成功 {success_count} 个，失败 0 个"
            )
            self.netdisk_progress_container.show()
            self.netdisk_progress_hide_timer.start(5000)
            self._auto_sync_stop_requested = False
            self._auto_sync_pause_after_current = False
            self._update_netdisk_controls()
            return

        if finished_mode == "auto":
            self.auto_sync_state = "idle"
            self._set_auto_sync_status(f"自动同步完成：成功 {success_count} 个，失败 {fail_count} 个")
        total = max(success_count + fail_count, self.netdisk_progress_bar.maximum())
        self.netdisk_progress_bar.setRange(0, max(1, total))
        self.netdisk_progress_bar.setValue(total)
        self.netdisk_progress_title.setText(
            f"重试完成：成功 {success_count} 个，失败 {fail_count} 个"
            if finished_mode == "retry"
            else (
                f"自动同步完成：成功 {success_count} 个，失败 {fail_count} 个"
                if finished_mode == "auto"
                else f"同步完成：成功 {success_count} 个，失败 {fail_count} 个"
            )
        )
        self.netdisk_progress_stats.setText(
            f"成功 {success_count} 个，<span style='color:#dc2626;'>失败 {fail_count} 个</span>"
            if fail_count
            else f"成功 {success_count} 个，失败 0 个"
        )
        self.netdisk_progress_current.setText(
            "仍有失败记录，可查看“上传失败”tooltip 后继续重试。"
            if fail_count and finished_mode == "retry"
            else ("可在“上传失败”提示中查看失败原因并重试。" if fail_count else "全部视频已同步完成。")
        )
        self.netdisk_progress_container.show()
        self.netdisk_progress_hide_timer.start(5000)
        if fail_count:
            prefix = "重试完成" if finished_mode == "retry" else ("自动同步完成" if finished_mode == "auto" else "网盘同步完成")
            self._show_notice(f"{prefix}：成功 {success_count} 个，失败 {fail_count} 个", "warning", 6000)
        else:
            prefix = "重试完成" if finished_mode == "retry" else ("自动同步完成" if finished_mode == "auto" else "网盘同步完成")
            self._show_notice(f"{prefix}：成功 {success_count} 个", "success", 5000)
        self._auto_sync_stop_requested = False
        self._auto_sync_pause_after_current = False
        self._update_netdisk_controls()

    def _update_pagination_bar(self) -> None:
        self.total_count_label.setText(f"共 {self.total_count} 条")

        self.page_size_combo.blockSignals(True)
        size_index = self.page_size_combo.findData(self.page_size)
        if size_index >= 0:
            self.page_size_combo.setCurrentIndex(size_index)
        self.page_size_combo.blockSignals(False)

        self.prev_page_button.setEnabled(self.current_page > 1)
        self.next_page_button.setEnabled(self.current_page < self.total_pages)
        self.jump_page_validator.setRange(1, max(1, self.total_pages))
        self.jump_page_input.setText(str(self.current_page))
        self.jump_page_input.setToolTip(f"当前第 {self.current_page} 页，共 {self.total_pages} 页")
        self._rebuild_page_buttons()

    def _rebuild_page_buttons(self) -> None:
        while self.page_buttons_layout.count():
            item = self.page_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for page in self._visible_page_items():
            if page is None:
                ellipsis = QLabel("...")
                ellipsis.setObjectName("paginationEllipsis")
                ellipsis.setAlignment(Qt.AlignCenter)
                self.page_buttons_layout.addWidget(ellipsis)
                continue

            button = QPushButton(str(page))
            button.setObjectName("paginationPageButton")
            button.setCheckable(True)
            button.setChecked(page == self.current_page)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target_page=page: self._go_to_page(target_page))
            self.page_buttons_layout.addWidget(button)

    def _visible_page_items(self) -> list[int | None]:
        total = self.total_pages
        current = self.current_page
        if total <= 7:
            return list(range(1, total + 1))
        if current <= 4:
            return [1, 2, 3, 4, 5, 6, None, total]
        if current >= total - 3:
            return [1, None, total - 5, total - 4, total - 3, total - 2, total - 1, total]
        return [1, None, current - 2, current - 1, current, current + 1, current + 2, None, total]

    def _go_to_page(self, page: int) -> None:
        target_page = max(1, min(int(page), self.total_pages))
        if target_page == self.current_page:
            self._update_pagination_bar()
            return
        self.logger.info("切换页码：%s -> %s", self.current_page, target_page)
        self.current_page = target_page
        self._apply_filter()

    def _jump_to_page(self) -> None:
        text = self.jump_page_input.text().strip()
        if not text.isdigit():
            self._show_notice("请输入有效页码", "warning")
            self._update_pagination_bar()
            return
        target_page = max(1, min(int(text), self.total_pages))
        self.logger.info("跳转页码：input=%s, target=%s", text, target_page)
        self._go_to_page(target_page)

    def _on_page_size_changed(self, _index: int) -> None:
        value = self.page_size_combo.currentData()
        try:
            page_size = int(value)
        except (TypeError, ValueError):
            page_size = 20
        if page_size not in self.PAGE_SIZE_OPTIONS:
            page_size = 20
        if page_size == self.page_size:
            return
        self.page_size = page_size
        self.current_page = 1
        self._save_page_size()
        self.logger.info("切换每页条数：%s", self.page_size)
        self._apply_filter(reset_page=True)

    def _update_table_cursor(self, _row: int, column: int) -> None:
        if self._skeleton_active:
            self.table.viewport().unsetCursor()
            return
        if column in {self.REMARK_COLUMN, self.SCENE_COLUMN, self.ACTION_COLUMN}:
            self.table.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.table.viewport().unsetCursor()

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if self._skeleton_active:
            return
        if item.column() == self.REMARK_COLUMN:
            self._edit_remark(item.row())

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if self._skeleton_active:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        if column == self.REMARK_COLUMN:
            self._edit_remark(row)
            return
        if column in {self.SCENE_COLUMN, self.ACTION_COLUMN}:
            return
        self._show_record_detail(row)

    def _show_record_detail(self, row: int) -> None:
        record_id = self._record_id_from_row(row)
        path = self._path_from_row(row)
        try:
            record = self.database.get_video_by_id(record_id) if record_id else None
            if record is None:
                record = self.database.get_video_by_path(path)
            if record is None:
                self._show_notice("未找到视频记录", "warning")
                return
            order_no = str(record.get("order_no") or "").strip()
            duplicates = self.database.get_videos_by_order_no(order_no, self.video_dir) if order_no else [record]
            if not duplicates:
                duplicates = [record]
            dialog = RecordDetailDialog(
                record,
                duplicates,
                self,
                database=self.database,
                config=self.config_manager.config,
                logger=self.logger,
                notice_callback=self._show_notice,
                record_updated_callback=lambda: self.refresh(rebuild=False, show_notice=False),
            )
            dialog.exec()
        except Exception as exc:
            self.logger.exception("打开单号详情失败：id=%s, path=%s", record_id or "-", path)
            self._show_notice(f"打开详情失败：{exc}", "error")

    def _show_duplicate_records(self, entry: dict[str, Any]) -> None:
        record_id = int(entry.get("id") or 0)
        order_no = str(entry.get("order_no") or "").strip()
        if not order_no:
            self._show_notice("未找到单号", "warning")
            return
        try:
            record = self.database.get_video_by_id(record_id) if record_id else None
            if record is not None:
                order_no = str(record.get("order_no") or order_no).strip()
            records = self.database.get_videos_by_order_no(order_no, self.video_dir)
            if len(records) <= 1:
                self._show_notice("该单号当前只有一条录制记录", "warning")
                self.refresh(rebuild=False, show_notice=False)
                return
            dialog = DuplicateRecordsDialog(
                database=self.database,
                order_no=order_no,
                query_dir=self.video_dir,
                current_record_id=record_id,
                notice_callback=self._show_notice,
                changed_callback=lambda: self.refresh(rebuild=False, show_notice=False),
                logger=self.logger,
                parent=self,
            )
            dialog.exec()
        except Exception as exc:
            self.logger.exception("打开重复单号记录弹窗失败：order_no=%s, id=%s", order_no, record_id or "-")
            self._show_notice(f"打开重复记录失败：{exc}", "error")

    def _show_table_context_menu(self, pos) -> None:
        if self._skeleton_active:
            return
        row = self.table.rowAt(pos.y())
        column = self.table.columnAt(pos.x())
        if row < 0 or column < 0 or column in {self.SCENE_COLUMN, self.ACTION_COLUMN}:
            return

        item = self.table.item(row, column)
        if item is None:
            return
        copy_text = self._copy_text_for_item(item)
        if not copy_text:
            return

        self.table.setCurrentItem(item)
        menu = QMenu(self)
        menu.setObjectName("copyContextMenu")
        copy_cell_action = menu.addAction("复制")

        selected_action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if selected_action is copy_cell_action:
            self._copy_text(copy_text, "内容已复制")

    def _copy_selected_rows(self) -> None:
        rows = self._selected_rows()
        if not rows:
            item = self.table.currentItem()
            if item is not None:
                self._copy_cell(item)
            return

        lines = [self._row_text(row) for row in rows]
        self._copy_text("\n".join(lines), "已复制选中内容")

    def _copy_cell(self, item: QTableWidgetItem) -> None:
        text = self._copy_text_for_item(item)
        self._copy_text(text, "已复制单元格内容")

    def _copy_text_for_item(self, item: QTableWidgetItem) -> str:
        if item.column() == self.SCENE_COLUMN:
            return str(item.data(Qt.UserRole) or item.text()).strip()
        return str(item.data(self.COPY_TEXT_ROLE) or item.text()).strip()

    def _copy_row(self, row: int) -> None:
        self._copy_text(self._row_text(row), "已复制整行")

    def _row_text(self, row: int) -> str:
        values: list[str] = []
        for column in self.COPY_COLUMNS:
            item = self.table.item(row, column)
            if item is None:
                values.append("")
            elif column == self.SCENE_COLUMN:
                values.append(str(item.data(Qt.UserRole) or item.text()))
            else:
                values.append(str(item.data(self.COPY_TEXT_ROLE) or item.text()))
        return "\t".join(values)

    def _copy_text(self, text: str, message: str) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._show_notice(message, "info", timeout_ms=2500)

    def _selected_rows(self) -> list[int]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        rows = {index.row() for index in selection.selectedRows()}
        if not rows:
            rows = {index.row() for index in selection.selectedIndexes() if index.column() != self.ACTION_COLUMN}
        return sorted(rows)

    def _open_video_from_item(self, item: QTableWidgetItem) -> None:
        path_value = item.data(Qt.UserRole)
        if not path_value:
            return
        self._open_scene_video(Path(path_value))

    def _open_scene_video(self, path: Path) -> None:
        path = Path(path)
        try:
            self.logger.info("点击场景视频打开：dir=%s, path=%s", self.video_dir, path)
            open_video(path)
        except FileNotFoundError:
            self.logger.warning("场景视频文件不存在：%s", path)
            self._show_notice("文件不存在", "error")
            self.refresh(rebuild=True)
        except Exception as exc:
            self.logger.exception("打开视频失败")
            self._show_notice(f"打开失败：{exc}", "error")

    def _reveal_video_from_item(self, item: QTableWidgetItem) -> None:
        path_value = item.data(Qt.UserRole)
        if not path_value:
            return
        self._reveal_scene_video(Path(path_value))

    def _reveal_scene_video(self, path: Path) -> None:
        path = Path(path)
        try:
            self.logger.info("点击场景视频定位：dir=%s, path=%s", self.video_dir, path)
            reveal_in_file_manager(path)
        except FileNotFoundError:
            self.logger.warning("场景视频文件不存在，尝试打开目录：%s", path)
            parent = path.parent
            if parent.exists() and parent.is_dir():
                try:
                    open_folder(parent)
                    self._show_notice("文件不存在，已打开所在目录", "warning")
                except Exception as exc:
                    self.logger.exception("定位文件失败后降级打开目录失败：%s", parent)
                    self._show_notice(f"打开失败：{exc}", "error")
            else:
                self._show_notice("文件目录不存在", "error")
            self.refresh(rebuild=True, show_notice=False)
        except Exception as exc:
            self.logger.exception("定位文件失败后降级打开目录：%s", path)
            parent = path.parent
            if parent.exists() and parent.is_dir():
                try:
                    open_folder(parent)
                    self._show_notice("定位失败，已打开所在目录", "warning")
                except Exception as folder_exc:
                    self._show_notice(f"打开失败：{folder_exc}", "error")
            else:
                self._show_notice(f"打开失败：{exc}", "error")

    def _open_selected_location(self) -> None:
        rows = self._selected_rows()
        if not rows:
            try:
                open_folder(self.video_dir)
            except Exception as exc:
                self._show_notice(f"打开失败：{exc}", "error")
            return

        self._reveal_scene_video(self._path_from_row(rows[0]))

    def _selected_item(self) -> QTableWidgetItem | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return selected[0]

    def _delete_video(self, path: Path) -> None:
        path = Path(path)
        try:
            record = self.database.get_video_by_path(path)
        except Exception:
            self.logger.exception("删除前读取视频记录失败：path=%s", path)
            record = None
        is_important = self._is_important_entry(record or {})
        important_note = self._important_reason_text(record or {})
        file_exists = path.exists()
        uploaded = str((record or {}).get("upload_status") or "") == UPLOAD_DONE
        order_no = str((record or {}).get("order_no") or path.name or "-")
        description = (
            "删除后，本地数据库记录与本地视频文件将无法恢复。"
            if file_exists
            else "本地视频文件已不存在，移除后该记录将不再显示。"
        )
        if is_important:
            description += " 该记录已标记为重要，请确认不再需要本地证据。"
        removed = ("本地数据库记录", "本地视频文件") if file_exists else ("本地数据库记录",)
        sections: list[tuple[str, tuple[str, ...]]] = [("将删除：", removed)]
        if uploaded:
            sections.append(("不会删除：", ("已上传至网盘的视频文件",)))
        else:
            sections.append(("提示：", ("此视频尚未上传至网盘，删除后无法从网盘恢复",)))
        if important_note:
            sections.append(("重要原因：", (important_note,)))
        dialog = ConfirmActionDialog(
            title="删除视频",
            heading="确定删除这条视频记录吗？" if file_exists else "确定移除这条视频记录吗？",
            description=description,
            info_label="单号",
            info_value=order_no,
            sections=sections,
            confirm_text="删除本地视频" if file_exists else "移除本地记录",
            destructive=True,
            position_key=DELETE_CONFIRM_POSITION_KEY,
            parent=self,
        )

        def delete_action() -> tuple[bool, str]:
            try:
                removed_file = False
                if path.exists():
                    path.unlink()
                    removed_file = True
                    self.logger.info("视频存储目录下删除视频：dir=%s, path=%s", self.video_dir, path)
                deleted_record = self.database.delete_video_record(path)
                if not deleted_record and record is not None:
                    self.logger.warning("删除视频后未找到 SQLite 记录：path=%s", path)
                    return False, "视频删除失败：未找到对应数据库记录"
                self.logger.info(
                    "视频删除完成：id=%s, path=%s, file_deleted=%s, record_deleted=%s",
                    (record or {}).get("id") or "-",
                    path,
                    removed_file,
                    bool(deleted_record),
                )
                return True, ""
            except PermissionError as exc:
                self.logger.exception("视频删除失败：权限不足或文件被占用，path=%s", path)
                return False, f"视频删除失败：权限不足或文件正在被占用（{exc}）"
            except OSError as exc:
                self.logger.exception("视频删除失败：path=%s", path)
                return False, f"视频删除失败：{exc}"
            except Exception as exc:
                self.logger.exception("视频删除未知异常：path=%s", path)
                return False, f"视频删除失败：{exc}"

        if not dialog.run_action(delete_action):
            return
        self._show_notice("视频已删除", "success")
        self._notify_video_list_changed("deleted")

    def _edit_remark(self, row: int) -> None:
        path = self._path_from_row(row)
        record_id = self._record_id_from_row(row)
        current_item = self.table.item(row, self.REMARK_COLUMN)
        current_text = ""
        if current_item is not None:
            current_text = str(current_item.data(self.COPY_TEXT_ROLE) or "")
        latest_record = self._video_record_for_remark(record_id, path) or {}
        if latest_record:
            current_text = str(latest_record.get("remark") or "")
        current_important = self._is_important_entry(latest_record)
        current_important_note = str(latest_record.get("important_note") or "").strip()
        current_reason_type = normalize_important_reason_type(latest_record.get("important_reason_type"), current_important)
        if current_important and not current_reason_type:
            current_reason_type = "other"
        current_reason_custom = str(latest_record.get("important_reason_custom") or "").strip()
        if current_reason_type == "other" and not current_reason_custom:
            current_reason_custom = current_important_note
        target_record_id = record_id or self._record_id_from_entry(latest_record)

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑备注")
        DialogSizeManager.apply(dialog, "remark_edit", self, "small", (500, 360))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("备注内容："))
        editor = QTextEdit()
        editor.setPlainText(current_text)
        editor.setPlaceholderText("请输入备注，最多 500 字。")
        layout.addWidget(editor)

        important_checkbox = QCheckBox("标记为重要")
        important_checkbox.setChecked(current_important)
        layout.addWidget(important_checkbox)

        important_note_label = QLabel("重要原因：")
        important_reason_combo = QComboBox()
        for reason_key, reason_label in IMPORTANT_REASON_OPTIONS:
            important_reason_combo.addItem(reason_label, reason_key)
        reason_index = important_reason_combo.findData(current_reason_type or DEFAULT_IMPORTANT_REASON_TYPE)
        important_reason_combo.setCurrentIndex(max(0, reason_index))
        important_note_input = QLineEdit()
        important_note_input.setText(current_reason_custom)
        important_note_input.setPlaceholderText("请输入其他原因")
        layout.addWidget(important_note_label)
        layout.addWidget(important_reason_combo)
        layout.addWidget(important_note_input)

        def sync_important_note_visible() -> None:
            visible = important_checkbox.isChecked()
            important_note_label.setVisible(visible)
            important_reason_combo.setVisible(visible)
            important_note_input.setVisible(visible and important_reason_combo.currentData() == "other")

        important_checkbox.toggled.connect(sync_important_note_visible)
        important_reason_combo.currentIndexChanged.connect(lambda _index=0: sync_important_note_visible())
        sync_important_note_visible()

        def save_remark() -> None:
            remark = editor.toPlainText().strip()
            important_checked = important_checkbox.isChecked()
            important_reason_type = (
                normalize_important_reason_type(important_reason_combo.currentData(), True) or DEFAULT_IMPORTANT_REASON_TYPE
                if important_checked
                else ""
            )
            important_reason_custom = important_note_input.text().strip() if important_checked and important_reason_type == "other" else ""
            important_note = important_note_from_reason(important_reason_type, important_reason_custom) if important_checked else ""
            if len(remark) > 500:
                self._show_notice("备注最多支持 500 字。", "warning")
                return
            if len(important_reason_custom) > 500:
                self._show_notice("重要原因最多支持 500 字。", "warning")
                return

            updated_rows = 0
            log_target = ""
            resolved_record_id = target_record_id
            try:
                if resolved_record_id:
                    updated_rows = self.database.update_video_remark(resolved_record_id, remark)
                    log_target = f"id={resolved_record_id}"
                else:
                    path_text = str(path).strip()
                    if not path_text or path_text == ".":
                        self.logger.warning("修改备注失败：当前行缺少记录 id 和视频路径，row=%s", row)
                        self._show_notice("备注保存失败，请查看日志", "error")
                        return
                    updated_rows = self.database.update_video_remark_by_path(path, remark)
                    log_target = f"path={path}"
                if updated_rows != 1:
                    self.logger.warning(
                        "备注保存失败：未找到对应记录，db=%s, %s, rowcount=%s, remark_len=%s",
                        self.database.db_path,
                        log_target,
                        updated_rows,
                        len(remark),
                    )
                    self._show_notice("备注保存失败：未找到对应记录", "error")
                    return

                if not resolved_record_id:
                    resolved_record = self._video_record_for_remark(0, path)
                    resolved_record_id = self._record_id_from_entry(resolved_record or {})
                if not resolved_record_id:
                    self.logger.warning("重要标记保存失败：未找到对应记录 id，row=%s, path=%s", row, path)
                    self._show_notice("重要标记保存失败：未找到对应记录", "error")
                    return

                importance_rows = self.database.update_video_importance(
                    resolved_record_id,
                    important_checked,
                    important_note,
                    important_reason_type,
                    important_reason_custom,
                )
                if importance_rows != 1:
                    self.logger.warning(
                        "重要标记保存失败：未找到对应记录，db=%s, id=%s, rowcount=%s, important=%s, reason=%s, custom_len=%s",
                        self.database.db_path,
                        resolved_record_id,
                        importance_rows,
                        important_checked,
                        important_reason_type,
                        len(important_reason_custom),
                    )
                    self._show_notice("重要标记保存失败：未找到对应记录", "error")
                    return

                saved_record = self._video_record_for_remark(resolved_record_id, path)
                saved_remark = str(saved_record.get("remark") or "") if saved_record else ""
                saved_important = self._is_important_entry(saved_record or {})
                saved_note = str((saved_record or {}).get("important_note") or "").strip()
                saved_reason_type = str((saved_record or {}).get("important_reason_type") or "").strip()
                saved_reason_custom = str((saved_record or {}).get("important_reason_custom") or "").strip()
                self.logger.info(
                    "备注保存回读：db=%s, %s, rowcount=%s, important_rowcount=%s, saved_remark_len=%s, saved_empty=%s, saved_important=%s, saved_reason=%s, saved_custom_len=%s, saved_note_len=%s",
                    self.database.db_path,
                    log_target,
                    updated_rows,
                    importance_rows,
                    len(saved_remark),
                    not bool(saved_remark),
                    saved_important,
                    saved_reason_type,
                    len(saved_reason_custom),
                    len(saved_note),
                )
                if (
                    saved_remark != remark
                    or saved_important != important_checked
                    or (important_checked and saved_reason_type != important_reason_type)
                    or (important_checked and saved_reason_custom != important_reason_custom)
                    or (not important_checked and (saved_note or saved_reason_type or saved_reason_custom))
                ):
                    self.logger.error(
                        "备注保存异常：数据库回读不一致，db=%s, %s, input_len=%s, saved_len=%s, input_important=%s, saved_important=%s, input_reason=%s, saved_reason=%s, input_custom_len=%s, saved_custom_len=%s",
                        self.database.db_path,
                        log_target,
                        len(remark),
                        len(saved_remark),
                        important_checked,
                        saved_important,
                        important_reason_type,
                        saved_reason_type,
                        len(important_reason_custom),
                        len(saved_reason_custom),
                    )
                    self._show_notice("备注保存异常：数据库回读不一致", "error")
                    return

                self.logger.info(
                    "修改备注和重要标记成功：%s, remark_len=%s, important=%s, reason=%s, custom_len=%s",
                    log_target,
                    len(remark),
                    important_checked,
                    important_reason_type,
                    len(important_reason_custom),
                )
                self._update_remark_cell(row, saved_record or {"remark": saved_remark})
                if saved_record:
                    self._set_order_no_item(row, saved_record, path)
                self._show_notice("备注已保存", "success")
                dialog.accept()
            except Exception:
                self.logger.exception(
                    "修改备注失败：id=%s, path=%s, remark_len=%s, important=%s, note_len=%s",
                    record_id or "-",
                    path,
                    len(remark),
                    important_checked,
                    len(important_note),
                )
                self._show_notice("备注保存失败，请查看日志", "error")

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        save_button = QPushButton("保存")
        save_button.setObjectName("primaryButton")
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("secondaryButton")
        save_button.clicked.connect(save_remark)
        cancel_button.clicked.connect(dialog.reject)
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        dialog_result = dialog.exec()
        DialogSizeManager.remember(dialog, "remark_edit")
        self.logger.info(
            "备注编辑弹窗关闭：db=%s, id=%s, path=%s, result=%s",
            self.database.db_path,
            record_id or "-",
            path,
            dialog_result,
        )

    def _record_id_from_row(self, row: int) -> int:
        item = self.table.item(row, self.REMARK_COLUMN)
        if item is None:
            return 0
        try:
            return max(0, int(item.data(self.RECORD_ID_ROLE) or 0))
        except (TypeError, ValueError):
            return 0

    def _latest_remark_text(self, record_id: int, path: Path, fallback: str) -> str:
        try:
            record = self._video_record_for_remark(record_id, path)
            if record is not None:
                return str(record.get("remark") or "")
        except Exception:
            self.logger.exception("读取最新备注失败：id=%s, path=%s", record_id or "-", path)
        return fallback

    def _video_record_for_remark(self, record_id: int, path: Path) -> dict[str, Any] | None:
        self.logger.info("读取备注记录：db=%s, id=%s, path=%s", self.database.db_path, record_id or "-", path)
        record = self.database.get_video_by_id(record_id) if record_id else None
        path_text = str(path).strip()
        if record is None and path_text and path_text != ".":
            record = self.database.get_video_by_path(path)
        return record

    def _update_remark_cell(self, row: int, entry: dict[str, Any] | str) -> None:
        item = self.table.item(row, self.REMARK_COLUMN)
        if item is None:
            return
        if isinstance(entry, dict):
            display_text, tooltip, remark, important = self._remark_display_parts(entry)
        else:
            remark = str(entry or "")
            display_text, tooltip, remark, important = self._remark_display_parts({"remark": remark})
        item.setText(display_text)
        item.setData(self.COPY_TEXT_ROLE, tooltip or display_text)
        item.setToolTip(tooltip)
        if isinstance(entry, dict):
            item.setData(self.RECORD_ID_ROLE, self._record_id_from_entry(entry))
        if important:
            item.setForeground(QColor("#DC2626"))
        elif remark:
            item.setForeground(QColor("#1f2937"))
        else:
            item.setForeground(QColor("#64748b"))

    def _set_type_filter(self, record_type: str) -> None:
        self.type_filter = record_type if record_type in {"全部", "发货", "退货"} else "全部"
        self._sync_type_filter_buttons()
        self.logger.info("类型筛选按钮切换：%s", self.type_filter)
        self._apply_filter(reset_page=True)

    def _set_upload_status_filter(self, upload_status: str) -> None:
        self.upload_status_filter = upload_status if upload_status in self.UPLOAD_STATUS_FILTER_OPTIONS else "全部"
        self._sync_upload_status_filter_buttons()
        self.logger.info("上传状态筛选按钮切换：%s", self.upload_status_filter)
        self._apply_filter(reset_page=True)

    def _set_remark_filter(self, value: str) -> None:
        self.remark_filter = value if value in {"全部", "有备注", "无备注"} else "全部"
        self.logger.info("备注筛选切换：%s", self.remark_filter)
        self._apply_filter(reset_page=True)

    def _set_important_filter(self, value: str) -> None:
        self.important_filter = value if value in {"全部", "已标记", "未标记"} else "全部"
        if self.important_filter == "未标记":
            self.important_reason_filter_combo.blockSignals(True)
            self.important_reason_filter_combo.setCurrentIndex(0)
            self.important_reason_filter_combo.blockSignals(False)
            self.important_reason_filter = "全部"
        self._sync_important_reason_filter_enabled()
        self.logger.info("重要标记筛选切换：%s, reason=%s", self.important_filter, self.important_reason_filter)
        self._apply_filter(reset_page=True)

    def _set_important_reason_filter(self, value: Any) -> None:
        reason_value = str(value or "全部").strip() or "全部"
        if self.important_filter == "未标记":
            reason_value = "全部"
        valid_values = {"全部", *(reason_key for reason_key, _label in IMPORTANT_REASON_OPTIONS)}
        self.important_reason_filter = reason_value if reason_value in valid_values else "全部"
        self._sync_important_reason_filter_enabled()
        self.logger.info("重要原因筛选切换：%s", self.important_reason_filter)
        self._apply_filter(reset_page=True)

    def _current_record_type_filter(self) -> str | None:
        return None if self.type_filter == "全部" else self.type_filter

    def _current_upload_status_filter(self) -> str | None:
        if not self._netdisk_sync_enabled():
            return None
        status = str(self.upload_status_filter or "全部").strip()
        return status if status in {UPLOAD_PENDING, UPLOAD_DONE, UPLOAD_FAILED, UPLOAD_UPLOADING} else None

    def _current_remark_filter(self) -> str | None:
        return self.remark_filter if self.remark_filter in {"有备注", "无备注"} else None

    def _current_important_filter(self) -> str | None:
        return self.important_filter if self.important_filter in {"已标记", "未标记"} else None

    def _current_important_reason_filter(self) -> str | None:
        if self.important_filter == "未标记":
            return None
        reason = str(self.important_reason_filter or "全部").strip()
        return reason if reason != "全部" else None

    def _current_query_filters(self, upload_status: str | None = None) -> dict[str, Any]:
        date_from, date_to = self._date_range()
        return {
            "keyword": self.search_input.text().strip(),
            "date_start": date_from,
            "date_end": date_to,
            "record_type": self._current_record_type_filter(),
            "query_dir": self.video_dir,
            "upload_status": upload_status,
            "remark_filter": self._current_remark_filter(),
            "important_filter": self._current_important_filter(),
            "important_reason": self._current_important_reason_filter(),
        }

    @staticmethod
    def _normalize_record_type(value: Any) -> str:
        return str(value).strip() if str(value).strip() in {"发货", "退货"} else "发货"

    def _show_notice(self, message: str, level: str = "info", timeout_ms: int = 4000) -> None:
        show_toast(self, message, level, timeout_ms, self.logger)

    def _set_quick_date_filter(self, mode: str) -> None:
        today = QDate.currentDate()
        self.start_date_edit.blockSignals(True)
        self.end_date_edit.blockSignals(True)
        self.date_filter_mode = mode if mode in {"today", "yesterday", "last_7_days", "all"} else "all"
        if mode == "today":
            self.date_filter_enabled = True
            self.start_date_edit.setDate(today)
            self.end_date_edit.setDate(today)
        elif mode == "yesterday":
            self.date_filter_enabled = True
            yesterday = today.addDays(-1)
            self.start_date_edit.setDate(yesterday)
            self.end_date_edit.setDate(yesterday)
        elif mode == "last_7_days":
            self.date_filter_enabled = True
            self.start_date_edit.setDate(today.addDays(-6))
            self.end_date_edit.setDate(today)
        else:
            self.date_filter_enabled = False
        self.start_date_edit.blockSignals(False)
        self.end_date_edit.blockSignals(False)
        self._sync_date_filter_buttons()
        self.logger.info("日期筛选按钮切换：%s", self.date_filter_mode)
        self._apply_filter(reset_page=True)

    def _enable_date_filter(self) -> None:
        self.date_filter_enabled = True
        self.date_filter_mode = self._quick_mode_for_current_dates()
        self._sync_date_filter_buttons()
        self.logger.info("日期筛选按钮切换：%s", self.date_filter_mode)
        self._apply_filter(reset_page=True)

    def _sync_date_filter_buttons(self) -> None:
        mapping = {
            "today": self.today_button,
            "yesterday": self.yesterday_button,
            "last_7_days": self.last_7_days_button,
            "all": self.all_dates_button,
        }
        if self.date_filter_mode in mapping:
            mapping[self.date_filter_mode].setChecked(True)
            return
        self.date_filter_button_group.setExclusive(False)
        for button in mapping.values():
            button.setChecked(False)
        self.date_filter_button_group.setExclusive(True)

    def _sync_type_filter_buttons(self) -> None:
        mapping = {
            "全部": self.type_all_button,
            "发货": self.type_ship_button,
            "退货": self.type_return_button,
        }
        mapping.get(self.type_filter, self.type_all_button).setChecked(True)

    def _sync_upload_status_filter_buttons(self) -> None:
        mapping = {
            "全部": self.upload_status_all_button,
            UPLOAD_PENDING: self.upload_status_pending_button,
            UPLOAD_DONE: self.upload_status_done_button,
            UPLOAD_FAILED: self.upload_status_failed_button,
            UPLOAD_UPLOADING: self.upload_status_uploading_button,
        }
        mapping.get(self.upload_status_filter, self.upload_status_all_button).setChecked(True)

    def _sync_important_reason_filter_enabled(self) -> None:
        reason_enabled = self.important_filter != "未标记"
        self.important_reason_filter_combo.setEnabled(reason_enabled)
        if not reason_enabled and self.important_reason_filter_combo.currentIndex() != 0:
            self.important_reason_filter_combo.blockSignals(True)
            self.important_reason_filter_combo.setCurrentIndex(0)
            self.important_reason_filter_combo.blockSignals(False)

    def _quick_mode_for_current_dates(self) -> str:
        today = QDate.currentDate()
        start = self.start_date_edit.date()
        end = self.end_date_edit.date()
        if start == today and end == today:
            return "today"
        yesterday = today.addDays(-1)
        if start == yesterday and end == yesterday:
            return "yesterday"
        if start == today.addDays(-6) and end == today:
            return "last_7_days"
        return "custom"

    def _date_range(self) -> tuple[date | None, date | None]:
        if not self.date_filter_enabled:
            return None, None
        start = self._qdate_to_date(self.start_date_edit.date())
        end = self._qdate_to_date(self.end_date_edit.date())
        if start > end:
            start, end = end, start
        return start, end

    def _initial_query_dir(self) -> Path:
        video_dir = self.config_manager.get_video_dir()
        video_dir.mkdir(parents=True, exist_ok=True)
        return video_dir.resolve()

    def _initial_page_size(self) -> int:
        query_config = self.config_manager.config.get("query", {})
        if isinstance(query_config, dict):
            try:
                page_size = int(query_config.get("page_size") or 20)
            except (TypeError, ValueError):
                page_size = 20
        else:
            page_size = 20
        return page_size if page_size in self.PAGE_SIZE_OPTIONS else 20

    def _resolve_query_path(self, path_value: str) -> Path:
        path = Path(path_value.strip()).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.config_manager.base_dir / path).resolve()

    def _save_page_size(self) -> None:
        query_config = self.config_manager.config.setdefault("query", {})
        query_config["page_size"] = self.page_size
        try:
            self.config_manager.save()
        except Exception:
            self.logger.exception("保存分页每页条数失败：page_size=%s", self.page_size)

    def _directory_dialog_start_dir(self) -> Path:
        if self.video_dir.exists() and self.video_dir.is_dir():
            return self.video_dir
        save_dir = self.config_manager.get_video_dir()
        if save_dir.exists() and save_dir.is_dir():
            return save_dir
        return self.config_manager.base_dir

    def _path_from_row(self, row: int) -> Path:
        item = self.table.item(row, self.SCENE_COLUMN)
        if item is None:
            return Path("")
        return Path(str(item.data(Qt.UserRole) or item.text()))

    @staticmethod
    def _recording_time_text(item: dict[str, Any]) -> str:
        return str(
            item.get("recording_time")
            or item.get("recorded_at")
            or item.get("created_time")
            or item.get("modified_time")
            or ""
        )

    @staticmethod
    def _has_short_duration_warning(item: dict[str, Any]) -> bool:
        warning = str(item.get("validation_warning") or "").strip()
        if warning:
            return "时长过短" in warning or "过短" in warning
        try:
            duration_seconds = float(item.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            return False
        return 0 < duration_seconds < 3

    @staticmethod
    def _duration_text(item: dict[str, Any]) -> str:
        seconds = float(item.get("duration_seconds") or 0)
        if seconds <= 0:
            return "-"
        return format_duration(int(round(seconds)))

    @staticmethod
    def _status_text(item: dict[str, Any], include_upload: bool = False) -> str:
        status = str(item.get("status") or ("正常" if bool(item.get("exists", True)) else MISSING_STATUS))
        if status != "正常":
            return status
        duplicate_count = int(item.get("duplicate_count") or 0)
        duplicate_sequence = int(item.get("duplicate_sequence") or 0)
        parts = ["正常"]
        if duplicate_count > 1 and duplicate_sequence > 0:
            parts.append(f"重复第 {duplicate_sequence} 次")
        if include_upload:
            parts.append(str(item.get("upload_status") or UPLOAD_PENDING))
        return " ".join(parts)

    @staticmethod
    def _qdate_to_date(value: QDate) -> date:
        return date(value.year(), value.month(), value.day())
