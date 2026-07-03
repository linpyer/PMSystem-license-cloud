from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.database import (
    DatabaseManager,
    MISSING_STATUS,
    NORMAL_STATUS,
    UPLOAD_DONE,
    UPLOAD_FAILED,
    UPLOAD_PENDING,
    UPLOAD_UPLOADING,
)
from app.core.netdisk_sync import NetdiskUploadWorker, normalize_netdisk_config
from app.core.video_player import open_folder, open_video, reveal_in_file_manager
from app.ui.toast import show_toast
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
        self.setWindowTitle("标记重要视频")
        self.resize(420, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel("该视频将被标记为重要，删除时会额外提醒。")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 700; color: #0f172a;")
        layout.addWidget(title)

        order_label = QLabel(f"单号：{order_no or '-'}")
        order_label.setStyleSheet("color: #475569;")
        layout.addWidget(order_label)

        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("例如：售后争议、客户反馈、待核实")
        self.note_edit.setMaximumHeight(110)
        layout.addWidget(self.note_edit)

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

    def note(self) -> str:
        return self.note_edit.toPlainText().strip()


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
            with self.database._lock:
                if self.rebuild:
                    self.database.refresh_video_directory(self.video_dir)
                total_count = self.database.count_videos(self.filters)
                total_pages = max(1, (total_count + self.page_size - 1) // self.page_size)
                current_page = max(1, min(self.current_page, total_pages))
                offset = (current_page - 1) * self.page_size
                rows = self.database.query_videos(
                    {
                        **self.filters,
                        "limit": self.page_size,
                        "offset": offset,
                    }
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
                },
            )
        except Exception as exc:
            self.logger.exception("视频查询后台加载失败：dir=%s, rebuild=%s", self.video_dir, self.rebuild)
            self.failed.emit(self.request_id, str(exc))


class RecordDetailDialog(QDialog):
    def __init__(self, record: dict[str, Any], duplicates: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = dict(record)
        self.duplicates = [dict(item) for item in duplicates]
        self.setWindowTitle("单号详情")
        self.resize(820, 620)
        self.setMinimumSize(720, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        order_title = QLabel(self._field("order_no", "-"))
        order_title.setObjectName("detailOrderTitle")
        order_title.setStyleSheet("font-size: 22px; font-weight: 700; color: #0f172a;")
        header_layout.addWidget(order_title, 1)
        file_status = self._field("status", NORMAL_STATUS)
        header_layout.addWidget(self._status_badge(file_status, self._file_status_color(file_status)))
        upload_status = self._field("upload_status", UPLOAD_PENDING)
        header_layout.addWidget(self._status_badge(upload_status, self._upload_status_color(upload_status)))
        layout.addLayout(header_layout)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(16)
        info_grid.setVerticalSpacing(10)
        row = 0
        row = self._add_text_row(info_grid, row, "单号", self._field("order_no", "-"))
        row = self._add_text_row(info_grid, row, "录制时间", self._recording_time(self.record))
        row = self._add_text_row(info_grid, row, "类型", self._field("record_type", "发货"))
        row = self._add_text_row(info_grid, row, "视频大小", self._field("file_size_text", "-"))
        row = self._add_text_row(info_grid, row, "视频时长", self._field("duration_text", "-"))
        row = self._add_text_row(info_grid, row, "文件状态", file_status)
        row = self._add_text_row(info_grid, row, "上传状态", upload_status)
        important = bool(self.record.get("is_important"))
        row = self._add_text_row(info_grid, row, "重要标记", "是" if important else "否")
        if important:
            row = self._add_text_row(info_grid, row, "重要原因", self._field("important_note", "暂无"))
            row = self._add_text_row(info_grid, row, "标记时间", self._field("important_at", "暂无"))
        upload_error = self._field("upload_error", "")
        if upload_error:
            row = self._add_text_row(info_grid, row, "失败原因", upload_error)
        row = self._add_copy_row(info_grid, row, "本地路径", self._field("file_path", "暂无"))
        row = self._add_copy_row(info_grid, row, "网盘路径", self._field("upload_remote_path", "暂无"))
        layout.addLayout(info_grid)

        remark_label = QLabel("备注")
        remark_label.setObjectName("detailSectionTitle")
        remark_label.setStyleSheet("font-weight: 700; color: #334155;")
        layout.addWidget(remark_label)
        remark = self._field("remark", "暂无备注")
        remark_box = QTextEdit()
        remark_box.setReadOnly(True)
        remark_box.setPlainText(remark)
        remark_box.setMinimumHeight(70)
        remark_box.setMaximumHeight(120)
        layout.addWidget(remark_box)

        duplicate_label = QLabel("重复录制记录")
        duplicate_label.setObjectName("detailSectionTitle")
        duplicate_label.setStyleSheet("font-weight: 700; color: #334155;")
        layout.addWidget(duplicate_label)
        duplicate_table = QTableWidget(0, 7)
        duplicate_table.setHorizontalHeaderLabels(["录制时间", "类型", "视频大小", "视频时长", "文件状态", "上传状态", "标记"])
        duplicate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        duplicate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        duplicate_table.verticalHeader().setVisible(False)
        duplicate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
                if column == 4:
                    cell.setForeground(QColor(self._file_status_color(value)))
                elif column == 5:
                    cell.setForeground(QColor(self._upload_status_color(value)))
                elif column == 6 and value:
                    cell.setForeground(QColor("#0f766e"))
                duplicate_table.setItem(row_index, column, cell)
        duplicate_table.setMinimumHeight(160)
        layout.addWidget(duplicate_table, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def _add_text_row(self, grid: QGridLayout, row: int, label: str, value: str) -> int:
        name = QLabel(f"{label}：")
        name.setStyleSheet("color: #64748b;")
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setStyleSheet("color: #0f172a;")
        grid.addWidget(name, row, 0, Qt.AlignTop)
        grid.addWidget(value_label, row, 1)
        return row + 1

    def _add_copy_row(self, grid: QGridLayout, row: int, label: str, value: str) -> int:
        name = QLabel(f"{label}：")
        name.setStyleSheet("color: #64748b;")
        line = QLineEdit(value)
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
        grid.addWidget(name, row, 0, Qt.AlignTop)
        grid.addLayout(row_layout, row, 1)
        return row + 1

    def _status_badge(self, text: str, color: str) -> QLabel:
        badge = QLabel(text)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color: {color}; border: 1px solid {color}; border-radius: 10px; "
            "padding: 2px 10px; font-weight: 700; background: #ffffff;"
        )
        return badge

    def _field(self, key: str, default: str = "") -> str:
        return self._text(self.record.get(key), default)

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        text = str(value or "").strip()
        return text if text else default

    @staticmethod
    def _record_id(entry: dict[str, Any]) -> int:
        try:
            return int(entry.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _recording_time(cls, entry: dict[str, Any]) -> str:
        return cls._text(entry.get("recorded_at") or entry.get("created_time"), "-")

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
        self.database = database
        self.order_no = str(order_no or "").strip()
        self.query_dir = Path(query_dir)
        self.current_record_id = int(current_record_id or 0)
        self.notice_callback = notice_callback
        self.changed_callback = changed_callback
        self.logger = logger
        self.records: list[dict[str, Any]] = []
        self.checkboxes: dict[int, QCheckBox] = {}
        self._all_checked = False
        self.setWindowTitle("重复单号记录")
        self.resize(980, 640)
        self.setMinimumSize(900, 560)
        self._build_ui()
        self.reload_records()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel("重复单号记录")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #0f172a;")
        layout.addWidget(title)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setStyleSheet("color: #475569; font-size: 13px;")
        layout.addWidget(self.subtitle_label)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["☐", "序号", "录制时间", "类型", "视频大小", "视频时长", "文件状态", "上传状态", "备注", "操作"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
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
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        header.setSectionResizeMode(9, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 96)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(6, 92)
        self.table.setColumnWidth(7, 92)
        self.table.setColumnWidth(9, 76)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.selected_label = QLabel("已选择 0 条")
        self.selected_label.setStyleSheet("color: #64748b;")
        footer.addWidget(self.selected_label)
        footer.addStretch(1)
        self.batch_delete_button = QPushButton("批量删除")
        self.batch_delete_button.setObjectName("tableDangerButton")
        self.batch_delete_button.setEnabled(False)
        self.batch_delete_button.clicked.connect(self._delete_selected_records)
        footer.addWidget(self.batch_delete_button)
        close_button = QPushButton("关闭")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
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
                self._populate_row(row_index, record)
        finally:
            self.table.setUpdatesEnabled(True)
        self._all_checked = False
        self.table.horizontalHeaderItem(0).setText("☐")
        self._update_selected_count()

    def _populate_row(self, row: int, record: dict[str, Any]) -> None:
        record_id = self._record_id(record)
        checkbox = QCheckBox()
        checkbox.setCursor(Qt.PointingHandCursor)
        checkbox.stateChanged.connect(self._update_selected_count)
        self.checkboxes[record_id] = checkbox
        checkbox_container = QWidget()
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
            self._text(record.get("remark"), "点击添加备注"),
        ]
        for column_offset, value in enumerate(values, start=1):
            cell = QTableWidgetItem(value)
            cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            cell.setTextAlignment(Qt.AlignCenter if column_offset != 8 else Qt.AlignLeft | Qt.AlignVCenter)
            if column_offset == 1 and record_id == self.current_record_id:
                cell.setForeground(QColor("#0f766e"))
            elif column_offset == 6:
                cell.setForeground(QColor(RecordDetailDialog._file_status_color(value)))
            elif column_offset == 7:
                cell.setForeground(QColor(RecordDetailDialog._upload_status_color(value)))
                upload_error = str(record.get("upload_error") or "").strip()
                if upload_error:
                    cell.setToolTip(upload_error)
            elif column_offset == 8:
                remark = str(record.get("remark") or "").strip()
                if remark:
                    cell.setToolTip(remark)
            self.table.setItem(row, column_offset, cell)

        delete_button = QPushButton("删除")
        delete_button.setObjectName("tableDangerButton")
        delete_button.setFixedSize(50, 26)
        delete_button.clicked.connect(lambda _checked=False, rid=record_id: self._delete_single_record(rid))
        delete_container = QWidget()
        delete_layout = QHBoxLayout(delete_container)
        delete_layout.setContentsMargins(0, 0, 0, 0)
        delete_layout.setAlignment(Qt.AlignCenter)
        delete_layout.addWidget(delete_button)
        self.table.setCellWidget(row, 9, delete_container)

    def _on_header_clicked(self, section: int) -> None:
        if section != 0:
            return
        self._all_checked = not self._all_checked
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(self._all_checked)
        self.table.horizontalHeaderItem(0).setText("☑" if self._all_checked else "☐")
        self._update_selected_count()

    def _update_selected_count(self) -> None:
        selected = len(self._selected_records())
        self.selected_label.setText(f"已选择 {selected} 条")
        self.batch_delete_button.setEnabled(selected > 0)
        if selected != len(self.checkboxes):
            self._all_checked = False
            if self.table.horizontalHeaderItem(0):
                self.table.horizontalHeaderItem(0).setText("☐")

    def _selected_records(self) -> list[dict[str, Any]]:
        selected_ids = {record_id for record_id, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        return [record for record in self.records if self._record_id(record) in selected_ids]

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
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        if batch:
            box.setWindowTitle("批量删除重复录制记录")
            box.setText(f"确定要删除选中的 {len(records)} 条录制记录吗？")
            detail = "删除后将删除本地视频文件和数据库记录。\n如其中部分视频已上传网盘，本次不会删除网盘文件。"
            missing_count = sum(1 for record in records if not Path(str(record.get("file_path") or "")).exists())
            if missing_count:
                detail += f"\n其中 {missing_count} 条本地视频文件已不存在，确认后仅移除数据库记录。"
        else:
            record = records[0]
            box.setWindowTitle("删除重复录制记录")
            box.setText("确定要删除这条录制记录吗？")
            detail = (
                f"单号：{self.order_no}\n"
                f"录制时间：{self._recording_time(record)}\n"
                "删除后将删除本地视频文件和数据库记录。"
            )
            if str(record.get("upload_status") or "") == UPLOAD_DONE:
                detail += "\n如该视频已上传网盘，本次仅删除本地文件和本地记录，不会删除网盘文件。"
            if not Path(str(record.get("file_path") or "")).exists():
                detail += "\n当前视频文件已不存在，确认后仅移除数据库记录。"
        important_count = sum(1 for record in records if self._is_important(record))
        if important_count:
            if batch:
                detail += f"\n选中记录中包含 {important_count} 条重要视频，请谨慎删除。"
            else:
                detail += "\n该视频已标记为重要，可能涉及售后争议，是否仍要删除？"
        box.setInformativeText(detail)
        confirm_button = box.addButton("仍然删除" if important_count else "确认删除", QMessageBox.AcceptRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is confirm_button

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
    STATUS_OPTIONS = ("全部", UPLOAD_DONE, UPLOAD_FAILED, UPLOAD_UPLOADING, UPLOAD_PENDING)

    def __init__(self, database: DatabaseManager, logger: logging.Logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.logger = logger
        self.setWindowTitle("网盘同步记录")
        self.resize(980, 620)
        self.setMinimumSize(860, 520)
        self._build_ui()
        self.reload_records()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        title = QLabel("网盘同步记录")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #0f172a;")
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
        layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["上传时间", "单号", "文件名", "上传状态", "失败原因", "远程路径", "重试次数"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 86)
        self.table.setColumnWidth(6, 70)
        layout.addWidget(self.table, 1)

        self.hint_label = QLabel("双击远程路径可复制。")
        self.hint_label.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.hint_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.status_combo.currentIndexChanged.connect(lambda _index: self.reload_records())
        self.order_search_input.returnPressed.connect(self.reload_records)
        self.refresh_button.clicked.connect(self.reload_records)
        self.table.cellDoubleClicked.connect(self._copy_remote_path)

    def reload_records(self) -> None:
        status = self.status_combo.currentText().strip()
        status_filter = None if status == "全部" else status
        keyword = self.order_search_input.text().strip()
        rows = self.database.query_upload_history(status_filter, keyword)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        try:
            for row_index, record in enumerate(rows):
                self.table.insertRow(row_index)
                self._populate_row(row_index, record)
        finally:
            self.table.setUpdatesEnabled(True)
        self.hint_label.setText(f"共 {len(rows)} 条记录。双击远程路径可复制。")

    def _populate_row(self, row: int, record: dict[str, Any]) -> None:
        upload_status = str(record.get("upload_status") or UPLOAD_PENDING)
        upload_time = str(record.get("upload_time") or "").strip() or "暂无"
        upload_error = str(record.get("upload_error") or "").strip()
        remote_path = str(record.get("upload_remote_path") or "").strip()
        values = [
            upload_time,
            str(record.get("order_no") or ""),
            str(record.get("file_name") or ""),
            upload_status,
            upload_error if upload_status == UPLOAD_FAILED and upload_error else "-",
            remote_path if remote_path else "-",
            str(int(record.get("upload_retry_count") or 0)),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignCenter if column in {0, 1, 3, 6} else Qt.AlignLeft | Qt.AlignVCenter)
            if column == 3:
                item.setForeground(QColor(RecordDetailDialog._upload_status_color(upload_status)))
            if column == 4 and upload_error:
                item.setToolTip(upload_error)
            if column == 5 and remote_path:
                item.setToolTip(remote_path)
                item.setData(Qt.UserRole, remote_path)
            self.table.setItem(row, column, item)

    def _copy_remote_path(self, row: int, column: int) -> None:
        if column != 5:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        remote_path = str(item.data(Qt.UserRole) or "").strip()
        if not remote_path:
            return
        QApplication.clipboard().setText(remote_path)
        self.hint_label.setText("远程路径已复制。")


class QueryTab(QWidget):
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

    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logger
        self.video_dir = self._initial_query_dir()
        self.database = DatabaseManager(self.config_manager.base_dir / "pm_system.db", logger)
        self.logger.info("查询页 SQLite 数据库路径：%s", self.database.db_path)
        self.date_filter_enabled = False
        self.date_filter_mode = "all"
        self.type_filter = "全部"
        self.upload_status_filter = "全部"
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
        self.netdisk_task_mode = "sync"
        self.netdisk_progress_hide_timer = QTimer(self)
        self.netdisk_progress_hide_timer.setSingleShot(True)
        self.netdisk_progress_hide_timer.timeout.connect(self._hide_netdisk_progress)
        self._build_ui()
        self._sync_query_dir_input()
        self._update_netdisk_controls()
        self.logger.info("查询页初始化当前查询目录：%s", self.video_dir)

    def set_video_dir(self, path: str) -> None:
        self.logger.info("录制保存目录已更新，查询目录保持不变：save_dir=%s, query_dir=%s", path, self.video_dir)
        self.mark_dirty()

    def shutdown(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait(3000)
        if self.upload_worker is not None and self.upload_worker.isRunning():
            self.upload_worker.stop()
            self.upload_worker.wait(3000)
        self.database.close()

    def is_netdisk_syncing(self) -> bool:
        return self.upload_worker is not None

    def reload_config(self, _config: dict[str, Any] | None = None) -> None:
        self._update_netdisk_controls()
        self.refresh(rebuild=False, show_notice=False)

    def mark_dirty(self) -> None:
        self.video_query_dirty = True

    def activate(self) -> None:
        QTimer.singleShot(50, self._load_after_activated)

    def _load_after_activated(self) -> None:
        if not self.isVisible():
            return
        if self._load_worker is not None:
            return
        if not self._has_loaded_once:
            self.refresh(rebuild=True, show_notice=False)
            return
        if self.video_query_dirty:
            self.refresh(rebuild=False, show_notice=False)

    def refresh(self, rebuild: bool = False, show_notice: bool = True) -> None:
        self._update_netdisk_controls()
        self.video_query_dirty = True
        self._request_video_load(rebuild=rebuild, show_notice=show_notice)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.activate()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.matches(QKeySequence.Copy):
            self._copy_selected_rows()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self.table.viewport() and event.type() == QEvent.Leave:
            self.table.viewport().unsetCursor()
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        query_dir_layout = QHBoxLayout()
        query_dir_layout.setSpacing(8)
        query_dir_label = QLabel("当前查询目录：")
        query_dir_label.setObjectName("subtleLabel")
        self.query_dir_input = QLineEdit()
        self.query_dir_input.setPlaceholderText("输入视频查询目录，按 Enter 生效")
        self.choose_query_dir_button = QPushButton("选择目录")
        self.choose_query_dir_button.setObjectName("secondaryButton")
        self.restore_default_dir_button = QPushButton("恢复默认")
        self.restore_default_dir_button.setObjectName("secondaryButton")
        query_dir_layout.addWidget(query_dir_label)
        query_dir_layout.addWidget(self.query_dir_input, 1)
        query_dir_layout.addWidget(self.choose_query_dir_button)
        query_dir_layout.addWidget(self.restore_default_dir_button)
        layout.addLayout(query_dir_layout)

        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
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
        self.sync_netdisk_button.setObjectName("primaryButton")
        self.sync_netdisk_button.setToolTip("将当前查询目录中未上传的视频同步到百度网盘")
        self.retry_failed_upload_button = QPushButton("重试上传失败")
        self.retry_failed_upload_button.setObjectName("retryUploadButton")
        self.retry_failed_upload_button.setToolTip("重试当前筛选条件下上传失败的视频")
        self.netdisk_history_button = QPushButton("同步记录")
        self.netdisk_history_button.setObjectName("secondaryButton")
        self.netdisk_history_button.setToolTip("查看百度网盘上传历史和失败原因")

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
            self.retry_failed_upload_button,
            self.netdisk_history_button,
        )

        date_toolbar.addWidget(QLabel("开始日期："))
        date_toolbar.addWidget(self.start_date_edit)
        date_toolbar.addWidget(QLabel("结束日期："))
        date_toolbar.addWidget(self.end_date_edit)
        date_toolbar.addWidget(self.today_button)
        date_toolbar.addWidget(self.yesterday_button)
        date_toolbar.addWidget(self.last_7_days_button)
        date_toolbar.addWidget(self.all_dates_button)
        date_toolbar.addSpacing(12)
        date_toolbar.addWidget(QLabel("类型："))
        date_toolbar.addWidget(self.type_all_button)
        date_toolbar.addWidget(self.type_ship_button)
        date_toolbar.addWidget(self.type_return_button)
        date_toolbar.addStretch(1)
        layout.addLayout(date_toolbar)

        netdisk_toolbar.addWidget(self.upload_status_label)
        for status_button in self.upload_status_buttons:
            netdisk_toolbar.addWidget(status_button)
        netdisk_toolbar.addStretch(1)
        netdisk_toolbar.addWidget(self.sync_netdisk_button)
        netdisk_toolbar.addWidget(self.retry_failed_upload_button)
        netdisk_toolbar.addWidget(self.netdisk_history_button)
        layout.addWidget(self.netdisk_filter_row)

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
        self.table.setColumnWidth(self.ACTION_COLUMN, 112)
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
        self.table.setColumnWidth(self.SCENE_COLUMN, 118)
        self.table.setColumnWidth(self.ACTION_COLUMN, 112)
        layout.addWidget(self.table, 1)

        self.pagination_container = QWidget()
        self.pagination_container.setObjectName("paginationBar")
        pagination_layout = QHBoxLayout(self.pagination_container)
        pagination_layout.setContentsMargins(2, 6, 2, 0)
        pagination_layout.setSpacing(8)

        self.total_count_label = QLabel("共 0 条")
        self.total_count_label.setObjectName("paginationTotalLabel")
        self.page_size_combo = QComboBox()
        self.page_size_combo.setObjectName("paginationCombo")
        self.page_size_combo.setFixedWidth(76)
        self.page_size_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for size in self.PAGE_SIZE_OPTIONS:
            self.page_size_combo.addItem(f"{size}条/页", size)
        size_index = self.page_size_combo.findData(self.page_size)
        self.page_size_combo.setCurrentIndex(size_index if size_index >= 0 else 1)

        self.prev_page_button = QPushButton("<")
        self.prev_page_button.setObjectName("paginationButton")
        self.prev_page_button.setToolTip("上一页")
        self.next_page_button = QPushButton(">")
        self.next_page_button.setObjectName("paginationButton")
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
        layout.addWidget(self.pagination_container)
        self.logger.info("类型列改为只读文本初始化")
        self.logger.info("分页组件初始化：page_size=%s", self.page_size)

        self.query_dir_input.returnPressed.connect(self.apply_query_dir_from_input)
        self.choose_query_dir_button.clicked.connect(self.choose_query_dir)
        self.restore_default_dir_button.clicked.connect(self.restore_default_query_dir)
        self.search_input.textChanged.connect(lambda _text: self._apply_filter(reset_page=True))
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
        self.sync_netdisk_button.clicked.connect(self._sync_unuploaded_videos)
        self.retry_failed_upload_button.clicked.connect(self._retry_failed_uploads)
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

    def apply_query_dir_from_input(self) -> None:
        raw_path = self.query_dir_input.text().strip()
        self.logger.info("用户在查询目录输入框中按回车应用路径：%s", raw_path)
        valid, path, message = self.validate_query_dir(raw_path)
        if not valid or path is None:
            self.logger.warning("查询目录路径校验失败：input=%s, message=%s", raw_path, message)
            self._sync_query_dir_input()
            self._show_notice(message, "error")
            return
        self.set_current_query_dir(path, "查询目录已切换。")

    def choose_query_dir(self) -> None:
        self.logger.info("用户点击选择目录")
        start_dir = self._directory_dialog_start_dir()
        selected = QFileDialog.getExistingDirectory(self, "选择查询目录", str(start_dir))
        if not selected:
            self.logger.info("用户取消选择目录")
            return
        self.logger.info("用户选择目录成功：%s", selected)
        self.query_dir_input.setText(selected)
        self.set_current_query_dir(Path(selected), "查询目录已切换。")

    def restore_default_query_dir(self) -> None:
        self.logger.info("恢复默认查询目录")
        target = self.config_manager.get_video_dir()
        if not target.exists() or not target.is_dir():
            target = self.config_manager.base_dir / "videos"
            target.mkdir(parents=True, exist_ok=True)
        self.set_current_query_dir(target, "已恢复默认查询目录。")

    def set_current_query_dir(self, path: str | Path, success_message: str) -> None:
        try:
            target = self._resolve_query_path(str(path))
            if not target.exists():
                self._sync_query_dir_input()
                self._show_notice("查询目录不存在，请检查路径。", "error")
                return
            if not target.is_dir():
                self._sync_query_dir_input()
                self._show_notice("查询目录不是文件夹，请重新输入。", "error")
                return
            self.video_dir = target
            self._sync_query_dir_input()
            self._save_last_query_dir()
            self.current_page = 1
            self.refresh(rebuild=True, show_notice=False)
            self.logger.info("查询目录切换成功：%s", self.video_dir)
            self._show_notice(f"{success_message} 正在加载视频列表。", "info")
        except Exception as exc:
            self.logger.exception("查询目录切换失败：%s", path)
            self._sync_query_dir_input()
            self._show_notice(f"查询目录切换失败：{exc}", "error")

    def validate_query_dir(self, path_value: str) -> tuple[bool, Path | None, str]:
        try:
            path = self._resolve_query_path(path_value)
        except Exception as exc:
            return False, None, f"查询目录切换失败：{exc}"
        if not path.exists():
            return False, None, "查询目录不存在，请检查路径。"
        if not path.is_dir():
            return False, None, "查询目录不是文件夹，请重新输入。"
        return True, path, ""

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
        self._show_loading_state("正在加载视频列表...")
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
        self._load_worker = worker
        worker.loaded.connect(lambda rid, payload, notice=show_notice: self._on_video_load_finished(rid, payload, notice))
        worker.failed.connect(lambda rid, error, notice=show_notice: self._on_video_load_failed(rid, error, notice))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _show_loading_state(self, message: str) -> None:
        self.empty_label.setText(message)
        self.empty_label.show()
        if self.table.rowCount() == 0:
            self.total_count_label.setText("正在加载...")

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
        self._render_rows(rows, offset)
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
        self.empty_label.setText(f"加载失败：{error}")
        self.empty_label.show()
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

    def _apply_filter(self, reset_page: bool = False) -> None:
        keyword = self.search_input.text().strip()
        date_from, date_to = self._date_range()
        record_type = self._current_record_type_filter()
        upload_status = self._current_upload_status_filter()
        if reset_page:
            self.current_page = 1
        self.logger.info(
            "当前查询目录搜索和日期筛选：dir=%s, keyword=%s, date_from=%s, date_to=%s, record_type=%s, upload_status=%s",
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
            self.table.setRowCount(0)
            self.empty_label.setText("未找到符合条件的视频。")
            self.empty_label.setVisible(not rows)
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
        item = QTableWidgetItem(order_no)
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, order_no)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        tooltip = ""
        if self._is_important_entry(entry):
            tooltip = self._important_tooltip(entry)
            item.setToolTip(tooltip)
        self.table.setItem(row, 1, item)

        if not self._is_important_entry(entry):
            return

        container = QWidget()
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("❗")
        icon.setAlignment(Qt.AlignCenter)
        icon.setToolTip(tooltip)
        icon.setStyleSheet("color: #DC2626; font-size: 14px; font-weight: 800;")
        text = QLabel(order_no)
        text.setAlignment(Qt.AlignCenter)
        text.setToolTip(tooltip)
        text.setStyleSheet("color: #0f172a;")
        layout.addWidget(icon, 0, Qt.AlignCenter)
        layout.addWidget(text, 0, Qt.AlignCenter)
        self.table.setCellWidget(row, 1, container)

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
        remark = str(entry.get("remark") or "")
        display_text = remark if remark else "点击添加备注"
        item = QTableWidgetItem(display_text)
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, remark)
        item.setData(self.RECORD_ID_ROLE, self._record_id_from_entry(entry))
        item.setToolTip(remark or "点击添加备注")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if not remark:
            item.setForeground(QColor("#64748b"))
        else:
            item.setForeground(QColor("#1f2937"))
        self.table.setItem(row, self.REMARK_COLUMN, item)

    @staticmethod
    def _record_id_from_entry(entry: dict[str, Any]) -> int:
        try:
            record_id = int(entry.get("id") or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, record_id)

    @staticmethod
    def _is_important_entry(entry: dict[str, Any]) -> bool:
        return bool(
            entry.get("is_important")
            or str(entry.get("important_note") or "").strip()
            or str(entry.get("important_at") or "").strip()
        )

    @classmethod
    def _important_tooltip(cls, entry: dict[str, Any]) -> str:
        note = str(entry.get("important_note") or "").strip()
        if note:
            return f"重要或有争议的单号\n备注：{note}"
        return "重要或有争议的单号"

    def _set_scene_video_cell(self, row: int, entry: dict[str, Any], path: Path) -> None:
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, str(path))
        item.setToolTip(str(path))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.SCENE_COLUMN, item)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        open_button = QPushButton("打开")
        open_button.setObjectName("openSceneLinkButton")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(lambda _checked=False, video_path=path: self._open_scene_video(video_path))

        reveal_button = QPushButton("定位")
        reveal_button.setObjectName("revealSceneLinkButton")
        reveal_button.setCursor(Qt.PointingHandCursor)
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

        important = self._is_important_entry(entry)
        important_button = QPushButton("★" if important else "☆")
        important_button.setFixedSize(30, 26)
        important_button.setCursor(Qt.PointingHandCursor)
        important_button.setToolTip("取消重要标记" if important else "标记为重要视频")
        important_button.setStyleSheet(
            "QPushButton { color: #DC2626; font-weight: 800; border: 1px solid #FCA5A5; "
            "background: #FFF1F2; border-radius: 4px; }"
            "QPushButton:hover { background: #FEE2E2; }"
        )
        important_button.clicked.connect(lambda _checked=False, row_entry=dict(entry): self._toggle_important(row_entry))
        layout.addWidget(important_button)

        if self._should_show_upload_action(entry, path):
            upload_status = str(entry.get("upload_status") or UPLOAD_PENDING)
            upload_button = QPushButton("上传" if upload_status != UPLOAD_UPLOADING else "上传中")
            upload_button.setObjectName("tableUploadButton")
            upload_button.setFixedSize(48, 26)
            upload_button.setEnabled(upload_status != UPLOAD_UPLOADING)
            upload_button.setCursor(Qt.PointingHandCursor)
            upload_button.setToolTip("上传该视频到百度网盘")
            upload_button.clicked.connect(lambda _checked=False, row_entry=dict(entry): self._upload_single_video(row_entry))
            layout.addWidget(upload_button)

        button = QPushButton("删除")
        button.setObjectName("tableDangerButton")
        button.setFixedSize(48, 26)
        button.setProperty("video_path", str(path))
        button.setToolTip("删除该视频物理文件")
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

    def _update_netdisk_controls(self) -> None:
        enabled = self._netdisk_sync_enabled()
        self.sync_netdisk_button.setVisible(enabled)
        self.sync_netdisk_button.setEnabled(enabled and not self.is_netdisk_syncing())
        self.sync_netdisk_button.setText("同步中..." if self.is_netdisk_syncing() else "同步至网盘")
        self.retry_failed_upload_button.setVisible(enabled)
        self.retry_failed_upload_button.setEnabled(enabled and not self.is_netdisk_syncing())
        self.retry_failed_upload_button.setText("重试中..." if self.is_netdisk_syncing() and self.netdisk_task_mode == "retry" else "重试上传失败")
        self.netdisk_history_button.setVisible(enabled)
        self.netdisk_history_button.setEnabled(enabled)
        for widget in getattr(self, "upload_status_filter_widgets", ()):
            widget.setVisible(enabled)
        if not enabled and self.upload_status_filter != "全部":
            self.upload_status_filter = "全部"
            self._sync_upload_status_filter_buttons()
        self.table.setColumnWidth(self.STATUS_COLUMN, 170 if enabled else 152)
        self.table.setColumnWidth(self.ACTION_COLUMN, 158 if enabled else 112)
        if not enabled and not self.is_netdisk_syncing():
            self._hide_netdisk_progress()

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
            dialog.exec()
        except Exception as exc:
            self.logger.exception("打开网盘同步记录窗口失败")
            self._show_notice(f"打开同步记录失败：{exc}", "error")

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
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle("取消重要标记")
                box.setText("确定要取消该视频的重要标记吗？")
                box.setInformativeText(f"单号：{order_no}")
                cancel_button = box.addButton("取消", QMessageBox.RejectRole)
                confirm_button = box.addButton("确认取消", QMessageBox.AcceptRole)
                box.setDefaultButton(cancel_button)
                box.exec()
                if box.clickedButton() is not confirm_button:
                    return
                affected = self.database.update_video_importance(record_id, False)
                if affected != 1:
                    self._show_notice("取消重要标记失败：未找到对应记录", "error")
                    return
                self.logger.info("取消重要视频标记：id=%s, order_no=%s", record_id, order_no)
                self._show_notice("已取消重要标记", "success")
            else:
                dialog = ImportantMarkDialog(order_no, self)
                if dialog.exec() != QDialog.Accepted:
                    return
                note = dialog.note()
                affected = self.database.update_video_importance(record_id, True, note)
                if affected != 1:
                    self._show_notice("标记重要失败：未找到对应记录", "error")
                    return
                self.logger.info(
                    "标记重要视频：id=%s, order_no=%s, note_len=%s",
                    record_id,
                    order_no,
                    len(note),
                )
                self._show_notice("已标记为重要视频", "success")
            self.refresh(rebuild=False, show_notice=False)
        except Exception as exc:
            self.logger.exception("修改重要视频标记失败：id=%s", record_id)
            self._show_notice(f"修改重要标记失败：{exc}", "error")

    def _sync_unuploaded_videos(self) -> None:
        if not self._ensure_netdisk_ready():
            return
        candidates = self.database.query_upload_candidates(self.video_dir, include_failed=False)
        upload_entries: list[dict[str, Any]] = []
        missing_count = 0
        for entry in candidates:
            path = Path(str(entry.get("file_path") or ""))
            if path.exists():
                upload_entries.append(entry)
            else:
                missing_count += 1
                try:
                    self.database.mark_file_missing(path)
                except Exception:
                    self.logger.exception("网盘同步跳过文件不存在视频时标记失败：%s", path)
        if missing_count:
            self.logger.warning("网盘同步跳过文件不存在视频：%s 条", missing_count)
        if not upload_entries:
            self.refresh(rebuild=False, show_notice=False)
            self._show_notice("没有需要同步到网盘的视频。", "info")
            return
        self._start_netdisk_upload(upload_entries, mode="sync")

    def _upload_single_video(self, entry: dict[str, Any]) -> None:
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
        answer = QMessageBox.question(
            self,
            "重试上传失败",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
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
        if not entries:
            return
        self.netdisk_task_mode = "retry" if mode == "retry" else "sync"
        worker = NetdiskUploadWorker(
            config=self._netdisk_config(),
            database_path=self.database.db_path,
            video_root=self.config_manager.get_video_dir(),
            entries=entries,
            task_label="重试上传失败" if self.netdisk_task_mode == "retry" else "同步",
            retry_failed=self.netdisk_task_mode == "retry",
            logger=self.logger,
            parent=self,
        )
        self.upload_worker = worker
        self._show_netdisk_progress(0, len(entries), "准备重试..." if self.netdisk_task_mode == "retry" else "准备同步...", 0, 0)
        worker.progress_changed.connect(self._on_netdisk_upload_progress)
        worker.row_changed.connect(lambda _path: self.refresh(rebuild=False, show_notice=False))
        worker.upload_failed.connect(self._on_netdisk_upload_failed)
        worker.tokens_refreshed.connect(self._save_netdisk_tokens)
        worker.finished_summary.connect(self._on_netdisk_upload_finished)
        worker.finished.connect(worker.deleteLater)
        self._update_netdisk_controls()
        self.refresh(rebuild=False, show_notice=False)
        self.logger.info("网盘%s任务开始：count=%s", "重试" if self.netdisk_task_mode == "retry" else "同步", len(entries))
        worker.start()

    def _show_netdisk_progress(self, current: int, total: int, file_name: str, success_count: int, fail_count: int) -> None:
        self.netdisk_progress_hide_timer.stop()
        total = max(1, int(total or 1))
        current = max(0, min(int(current or 0), total))
        self.netdisk_progress_bar.setRange(0, total)
        self.netdisk_progress_bar.setValue(current)
        if self.netdisk_task_mode == "retry":
            self.netdisk_progress_title.setText(f"正在重试上传失败：{current} / {total}")
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
        self.logger.info("网盘%s任务结束：success=%s, failed=%s", "重试" if finished_mode == "retry" else "同步", success_count, fail_count)
        self.upload_worker = None
        self._update_netdisk_controls()
        self.refresh(rebuild=False, show_notice=False)
        total = max(success_count + fail_count, self.netdisk_progress_bar.maximum())
        self.netdisk_progress_bar.setRange(0, max(1, total))
        self.netdisk_progress_bar.setValue(total)
        self.netdisk_progress_title.setText(
            f"重试完成：成功 {success_count} 个，失败 {fail_count} 个"
            if finished_mode == "retry"
            else f"同步完成：成功 {success_count} 个，失败 {fail_count} 个"
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
            prefix = "重试完成" if finished_mode == "retry" else "网盘同步完成"
            self._show_notice(f"{prefix}：成功 {success_count} 个，失败 {fail_count} 个", "warning", 6000)
        else:
            prefix = "重试完成" if finished_mode == "retry" else "网盘同步完成"
            self._show_notice(f"{prefix}：成功 {success_count} 个", "success", 5000)

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
        if column in {self.REMARK_COLUMN, self.SCENE_COLUMN, self.ACTION_COLUMN}:
            self.table.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.table.viewport().unsetCursor()

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() == self.REMARK_COLUMN:
            self._edit_remark(item.row())

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
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
            dialog = RecordDetailDialog(record, duplicates, self)
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
        row = self.table.rowAt(pos.y())
        column = self.table.columnAt(pos.x())
        if row < 0:
            return

        item = self.table.item(row, column)
        if item is None:
            item = self.table.item(row, self.SCENE_COLUMN)
        if item is None:
            return

        self.table.setCurrentItem(item)
        menu = QMenu(self)
        copy_cell_action = menu.addAction("复制单元格内容")
        copy_row_action = menu.addAction("复制整行")
        copy_path_action = menu.addAction("复制视频路径")
        menu.addSeparator()
        open_video_action = menu.addAction("打开视频")
        reveal_action = menu.addAction("打开所在文件夹")

        selected_action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if selected_action is copy_cell_action:
            self._copy_cell(item)
        elif selected_action is copy_row_action:
            self._copy_row(row)
        elif selected_action is copy_path_action:
            self._copy_text(str(self._path_from_row(row)), "已复制视频路径")
        elif selected_action is open_video_action:
            self._open_scene_video(self._path_from_row(row))
        elif selected_action is reveal_action:
            self._reveal_scene_video(self._path_from_row(row))

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
        if item.column() == self.SCENE_COLUMN:
            text = str(item.data(Qt.UserRole) or item.text())
        else:
            text = str(item.data(self.COPY_TEXT_ROLE) or item.text())
        self._copy_text(text, "已复制单元格内容")

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
        important_note = str((record or {}).get("important_note") or "").strip()
        if not path.exists():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("删除记录")
            if is_important:
                box.setText("该视频已标记为重要，可能涉及售后争议。\n当前视频文件已不存在，确定仍要从列表中移除此记录吗？")
            else:
                box.setText("当前视频文件已不存在，是否从列表中移除此记录？")
            detail = f"记录路径：{path}"
            if important_note:
                detail += f"\n重要原因：{important_note}"
            box.setInformativeText(detail)
            confirm_button = box.addButton("仍然移除" if is_important else "确认", QMessageBox.AcceptRole)
            cancel_button = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(cancel_button)
            box.exec()

            if box.clickedButton() is not confirm_button:
                return

            try:
                deleted = self.database.delete_video_record(path)
                if deleted:
                    self.logger.info(
                        "file missing, remove db record only: dir=%s, path=%s",
                        self.video_dir,
                        path,
                    )
                    self._show_notice("记录已移除", "success")
                else:
                    self.logger.warning("文件不存在记录移除失败：SQLite 记录不存在，dir=%s, path=%s", self.video_dir, path)
                    self._show_notice("记录不存在，列表已刷新", "warning")
                self.refresh(rebuild=False, show_notice=False)
            except Exception as exc:
                self.logger.exception("文件不存在记录移除失败：dir=%s, path=%s", self.video_dir, path)
                self._show_notice(f"记录移除失败：{exc}", "error")
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("确认删除")
        if is_important:
            box.setText("该视频已标记为重要，可能涉及售后争议。\n确定仍要删除吗？")
        else:
            box.setText("确定要删除该视频文件吗？")
        detail = f"文件名：{path.name}\n位置：{path}"
        if important_note:
            detail += f"\n重要原因：{important_note}"
        box.setInformativeText(detail)
        confirm_button = box.addButton("仍然删除" if is_important else "确认", QMessageBox.AcceptRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()

        if box.clickedButton() is not confirm_button:
            return

        try:
            path.unlink()
            self.logger.info("当前查询目录下删除视频：dir=%s, path=%s", self.video_dir, path)
            deleted = self.database.delete_video_record(path)
            if deleted:
                self.logger.info("删除后 SQLite 记录同步更新：%s", path)
            else:
                self.logger.warning("删除视频文件后未找到 SQLite 记录：%s", path)
            self._show_notice("视频已删除", "success")
            self.refresh(rebuild=False, show_notice=False)
        except FileNotFoundError:
            try:
                deleted = self.database.delete_video_record(path)
                if deleted:
                    self.logger.info(
                        "file missing during unlink, remove db record only: dir=%s, path=%s",
                        self.video_dir,
                        path,
                    )
                    self._show_notice("记录已移除", "success")
                else:
                    self.logger.warning("删除时文件已不存在且 SQLite 记录不存在：dir=%s, path=%s", self.video_dir, path)
                    self._show_notice("记录不存在，列表已刷新", "warning")
                self.refresh(rebuild=False, show_notice=False)
            except Exception as exc:
                self.logger.exception("删除时文件已不存在，移除 SQLite 记录失败：dir=%s, path=%s", self.video_dir, path)
                self._show_notice(f"记录移除失败：{exc}", "error")
        except PermissionError as exc:
            self.logger.exception("当前查询目录下删除视频失败：权限不足，dir=%s, path=%s", self.video_dir, path)
            self._show_notice(f"删除失败：权限不足或文件正在被占用（{exc}）", "error")
        except OSError as exc:
            self.logger.exception("当前查询目录下删除视频失败：dir=%s, path=%s", self.video_dir, path)
            self._show_notice(f"删除失败：{exc}", "error")
        except Exception as exc:
            self.logger.exception("当前查询目录下删除视频未知异常：dir=%s, path=%s", self.video_dir, path)
            self._show_notice(f"删除失败：未知异常（{exc}）", "error")

    def _edit_remark(self, row: int) -> None:
        path = self._path_from_row(row)
        record_id = self._record_id_from_row(row)
        current_item = self.table.item(row, self.REMARK_COLUMN)
        current_text = ""
        if current_item is not None:
            current_text = str(current_item.data(self.COPY_TEXT_ROLE) or "")
        current_text = self._latest_remark_text(record_id, path, current_text)

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑备注")
        dialog.resize(460, 300)
        layout = QVBoxLayout(dialog)
        editor = QTextEdit()
        editor.setPlainText(current_text)
        editor.setPlaceholderText("请输入备注，最多 500 字。")
        layout.addWidget(editor)

        def save_remark() -> None:
            remark = editor.toPlainText().strip()
            if len(remark) > 500:
                self._show_notice("备注最多支持 500 字。", "warning")
                return

            updated_rows = 0
            log_target = ""
            try:
                if record_id:
                    updated_rows = self.database.update_video_remark(record_id, remark)
                    log_target = f"id={record_id}"
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

                saved_record = self._video_record_for_remark(record_id, path)
                saved_remark = str(saved_record.get("remark") or "") if saved_record else ""
                self.logger.info(
                    "备注保存回读：db=%s, %s, rowcount=%s, saved_remark_len=%s, saved_empty=%s",
                    self.database.db_path,
                    log_target,
                    updated_rows,
                    len(saved_remark),
                    not bool(saved_remark),
                )
                if saved_remark != remark:
                    self.logger.error(
                        "备注保存异常：数据库回读不一致，db=%s, %s, input_len=%s, saved_len=%s",
                        self.database.db_path,
                        log_target,
                        len(remark),
                        len(saved_remark),
                    )
                    self._show_notice("备注保存异常：数据库回读不一致", "error")
                    return

                self.logger.info("修改备注成功：%s, remark_len=%s", log_target, len(remark))
                self._update_remark_cell(row, saved_remark)
                self._show_notice("备注已保存", "success")
                dialog.accept()
            except Exception:
                self.logger.exception("修改备注失败：id=%s, path=%s, remark_len=%s", record_id or "-", path, len(remark))
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

    def _update_remark_cell(self, row: int, remark: str) -> None:
        item = self.table.item(row, self.REMARK_COLUMN)
        if item is None:
            return
        remark = str(remark or "")
        display_text = remark if remark else "点击添加备注"
        item.setText(display_text)
        item.setData(self.COPY_TEXT_ROLE, remark)
        item.setToolTip(remark or "点击添加备注")
        item.setForeground(QColor("#1f2937" if remark else "#64748b"))

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

    def _current_record_type_filter(self) -> str | None:
        return None if self.type_filter == "全部" else self.type_filter

    def _current_upload_status_filter(self) -> str | None:
        if not self._netdisk_sync_enabled():
            return None
        status = str(self.upload_status_filter or "全部").strip()
        return status if status in {UPLOAD_PENDING, UPLOAD_DONE, UPLOAD_FAILED, UPLOAD_UPLOADING} else None

    def _current_query_filters(self, upload_status: str | None = None) -> dict[str, Any]:
        date_from, date_to = self._date_range()
        return {
            "keyword": self.search_input.text().strip(),
            "date_start": date_from,
            "date_end": date_to,
            "record_type": self._current_record_type_filter(),
            "query_dir": self.video_dir,
            "upload_status": upload_status,
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
        query_config = self.config_manager.config.get("query", {})
        candidates = []
        if isinstance(query_config, dict):
            candidates.append(str(query_config.get("last_query_dir", "") or ""))
        candidates.append(str(self.config_manager.get_video_dir()))
        candidates.append(str(self.config_manager.base_dir / "videos"))
        for candidate in candidates:
            if not candidate:
                continue
            path = self._resolve_query_path(candidate)
            if path.exists() and path.is_dir():
                return path
        default_dir = self.config_manager.base_dir / "videos"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir.resolve()

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

    def _sync_query_dir_input(self) -> None:
        query_dir_text = str(self.video_dir)
        self.query_dir_input.setText(query_dir_text)
        self.query_dir_input.setToolTip(query_dir_text)
        self.query_dir_input.setCursorPosition(0)

    def _save_last_query_dir(self) -> None:
        query_config = self.config_manager.config.setdefault("query", {})
        query_config["last_query_dir"] = str(self.video_dir)
        self.config_manager.save()

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
