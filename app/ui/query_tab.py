from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.database import DatabaseManager, MISSING_STATUS
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


class QueryTab(QWidget):
    PAGE_SIZE_OPTIONS = (10, 20, 50, 100)
    RECORD_TYPE_COLUMN = 5
    REMARK_COLUMN = 6
    STATUS_COLUMN = 7
    SCENE_COLUMN = 8
    ACTION_COLUMN = 9
    COPY_COLUMNS = tuple(range(0, 9))
    COPY_TEXT_ROLE = Qt.UserRole + 1

    def __init__(self, config_manager: ConfigManager, logger: logging.Logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = logger
        self.video_dir = self._initial_query_dir()
        self.database = DatabaseManager(self.config_manager.base_dir / "pm_system.db", logger)
        self.date_filter_enabled = False
        self.date_filter_mode = "all"
        self.type_filter = "全部"
        self.page_size = self._initial_page_size()
        self.current_page = 1
        self.total_count = 0
        self.total_pages = 1
        self._build_ui()
        self._sync_query_dir_input()
        self.logger.info("查询页初始化当前查询目录：%s", self.video_dir)
        self.refresh(rebuild=True, show_notice=False)

    def set_video_dir(self, path: str) -> None:
        self.logger.info("录制保存目录已更新，查询目录保持不变：save_dir=%s, query_dir=%s", path, self.video_dir)

    def shutdown(self) -> None:
        self.database.close()

    def refresh(self, rebuild: bool = False, show_notice: bool = True) -> None:
        try:
            if rebuild:
                self.database.refresh_video_directory(self.video_dir)
            self.logger.info("当前查询目录刷新列表：dir=%s, rebuild=%s", self.video_dir, rebuild)
        except Exception as exc:
            self.logger.exception("刷新视频列表失败：dir=%s", self.video_dir)
            self._show_notice(f"刷新失败：{exc}", "error")

        self.logger.info("查询页重复录制次数重新计算：dir=%s", self.video_dir)
        self._apply_filter()
        if show_notice:
            if rebuild:
                self._show_notice("列表已刷新。", "success")
            if self.table.rowCount() == 0:
                self._show_notice("当前目录未找到视频文件。", "warning")

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.refresh(rebuild=False, show_notice=False)

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
        self.table.setColumnWidth(self.ACTION_COLUMN, 78)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.verticalHeader().setMinimumSectionSize(56)
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
        self.table.setColumnWidth(self.ACTION_COLUMN, 78)
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
            if self.table.rowCount() > 0:
                self._show_notice(success_message, "success")
            else:
                self._show_notice(f"{success_message} 当前目录未找到视频文件。", "warning")
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

    def _apply_filter(self, reset_page: bool = False) -> None:
        keyword = self.search_input.text().strip()
        date_from, date_to = self._date_range()
        record_type = self._current_record_type_filter()
        if reset_page:
            self.current_page = 1
        self.logger.info(
            "当前查询目录搜索和日期筛选：dir=%s, keyword=%s, date_from=%s, date_to=%s, record_type=%s",
            self.video_dir,
            keyword,
            date_from,
            date_to,
            record_type or "全部",
        )
        filters = {
            "keyword": keyword,
            "date_start": date_from,
            "date_end": date_to,
            "record_type": record_type,
            "query_dir": self.video_dir,
        }
        self.total_count = self.database.count_videos(filters)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        if self.current_page > self.total_pages:
            old_page = self.current_page
            self.current_page = self.total_pages
            self.logger.info("分页页码自动修正：%s -> %s", old_page, self.current_page)
        if self.current_page < 1:
            self.current_page = 1

        offset = (self.current_page - 1) * self.page_size
        rows = self.database.query_videos(
            {
                **filters,
                "limit": self.page_size,
                "offset": offset,
            }
        )

        self.table.setRowCount(0)
        self.empty_label.setVisible(not rows)
        for row_index, item in enumerate(rows):
            path = Path(str(item.get("file_path", "")))
            self.table.insertRow(row_index)
            self.table.setRowHeight(row_index, 56)
            self._set_item(row_index, 0, str(offset + row_index + 1), path)
            self._set_item(row_index, 1, str(item.get("order_no", "")) or "-", path)
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
            )
            self._set_record_type_cell(row_index, item, path)
            self._set_remark_item(row_index, item, path)
            self._set_status_item(row_index, item, path)
            self._set_scene_video_cell(row_index, item, path)
            self._set_delete_button(row_index, item)
        self._update_pagination_bar()

    def _set_item(self, row: int, column: int, text: str, path: Path) -> None:
        item = QTableWidgetItem(text)
        item.setData(Qt.UserRole, str(path))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, column, item)

    def _set_two_line_item(self, row: int, column: int, first_line: str, second_line: str, path: Path) -> None:
        copy_text = f"{first_line} / {second_line}"
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, copy_text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, column, item)

        container = QWidget()
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(1)

        title = QLabel(first_line)
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("tablePrimaryText")
        subtitle = QLabel(second_line)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("tableSubText")
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
        item.setToolTip(remark or "点击添加备注")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if not remark:
            item.setForeground(QColor("#64748b"))
        else:
            item.setForeground(QColor("#1f2937"))
        self.table.setItem(row, self.REMARK_COLUMN, item)

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
        copy_text = self._status_text(entry)
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, str(path))
        item.setData(self.COPY_TEXT_ROLE, copy_text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.STATUS_COLUMN, item)

        container = QWidget()
        container.setObjectName("statusCell")
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        status = str(entry.get("status") or ("正常" if bool(entry.get("exists", True)) else MISSING_STATUS))
        normal_status = status == "正常"
        status_label = QLabel(status)
        status_label.setObjectName("statusText")
        status_label.setProperty("statusState", "normal" if normal_status else "error")
        layout.addWidget(status_label)

        duplicate_count = int(entry.get("duplicate_count") or 0)
        duplicate_sequence = int(entry.get("duplicate_sequence") or 0)
        if normal_status and bool(entry.get("is_duplicate")) and duplicate_count > 1 and duplicate_sequence > 0:
            duplicate_tip = f"该单号第 {duplicate_sequence} 次录制，共 {duplicate_count} 次"
            item.setToolTip(duplicate_tip)
            badge = QLabel(f"重复第 {duplicate_sequence} 次")
            badge.setObjectName("duplicateBadge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setToolTip(duplicate_tip)
            layout.addWidget(badge)

        self.table.setCellWidget(row, self.STATUS_COLUMN, container)

    def _set_delete_button(self, row: int, entry: dict[str, Any]) -> None:
        path = Path(str(entry.get("file_path", "")))
        container = QWidget()
        container.setObjectName("tableActionCell")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        button = QPushButton("删除")
        button.setObjectName("tableDangerButton")
        button.setFixedSize(48, 26)
        button.setProperty("video_path", str(path))
        button.setToolTip("删除该视频物理文件")
        button.clicked.connect(lambda _checked=False, video_path=path: self._delete_video(video_path))
        layout.addWidget(button)
        self.table.setCellWidget(row, self.ACTION_COLUMN, container)

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
        else:
            self._open_scene_video(self._path_from_row(row))

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
        if not path.exists():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("删除记录")
            box.setText("当前视频文件已不存在，是否从列表中移除此记录？")
            box.setInformativeText(f"记录路径：{path}")
            confirm_button = box.addButton("确认", QMessageBox.AcceptRole)
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
        box.setText("确定要删除该视频文件吗？")
        box.setInformativeText(f"文件名：{path.name}\n位置：{path}")
        confirm_button = box.addButton("确认", QMessageBox.AcceptRole)
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
        current_item = self.table.item(row, self.REMARK_COLUMN)
        current_text = ""
        if current_item is not None:
            current_text = str(current_item.data(self.COPY_TEXT_ROLE) or "")

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑备注")
        dialog.resize(460, 300)
        layout = QVBoxLayout(dialog)
        editor = QTextEdit()
        editor.setPlainText(current_text)
        editor.setPlaceholderText("请输入备注，最多 500 字。")
        layout.addWidget(editor)

        buttons = QDialogButtonBox()
        save_button = buttons.addButton("保存", QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted or buttons.clickedButton() is cancel_button:
            return

        remark = editor.toPlainText().strip()
        if len(remark) > 500:
            self._show_notice("备注最多支持 500 字。", "warning")
            return

        try:
            if self.database.update_remark(path, remark):
                self.logger.info("修改备注成功：path=%s", path)
                self._show_notice("备注已保存", "success")
                self._apply_filter()
            else:
                self.logger.warning("修改备注失败：索引记录不存在，path=%s", path)
                self._show_notice("备注保存失败，请查看日志", "error")
        except Exception:
            self.logger.exception("修改备注失败：path=%s", path)
            self._show_notice("备注保存失败，请查看日志", "error")

    def _set_type_filter(self, record_type: str) -> None:
        self.type_filter = record_type if record_type in {"全部", "发货", "退货"} else "全部"
        self._sync_type_filter_buttons()
        self.logger.info("类型筛选按钮切换：%s", self.type_filter)
        self._apply_filter(reset_page=True)

    def _current_record_type_filter(self) -> str | None:
        return None if self.type_filter == "全部" else self.type_filter

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
    def _duration_text(item: dict[str, Any]) -> str:
        seconds = float(item.get("duration_seconds") or 0)
        if seconds <= 0:
            return "-"
        return format_duration(int(round(seconds)))

    @staticmethod
    def _status_text(item: dict[str, Any]) -> str:
        status = str(item.get("status") or ("正常" if bool(item.get("exists", True)) else MISSING_STATUS))
        if status != "正常":
            return status
        duplicate_count = int(item.get("duplicate_count") or 0)
        duplicate_sequence = int(item.get("duplicate_sequence") or 0)
        if duplicate_count > 1 and duplicate_sequence > 0:
            return f"正常 重复第 {duplicate_sequence} 次"
        return "正常"

    @staticmethod
    def _qdate_to_date(value: QDate) -> date:
        return date(value.year(), value.month(), value.day())
