from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.dialog_utils import DialogSizeManager
from app.ui.toast import show_toast


ActionResult = bool | tuple[bool, str]
DELETE_CONFIRM_POSITION_KEY = "delete_confirm"


class ConfirmActionDialog(QDialog):
    """Theme-aware confirmation dialog with cancellation as the safe default."""

    def __init__(
        self,
        *,
        title: str,
        heading: str,
        description: str = "",
        info_label: str = "",
        info_value: str = "",
        sections: Sequence[tuple[str, Sequence[str]]] = (),
        confirm_text: str = "确定",
        destructive: bool = False,
        position_key: str = "",
        parent: QWidget | None = None,
    ) -> None:
        position_parent = parent.window() if position_key and parent is not None else parent
        super().__init__(position_parent)
        self.setObjectName("confirmActionDialog")
        self.setModal(True)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._busy = False
        self._action: Callable[[], ActionResult] | None = None
        self._action_succeeded = False
        self._confirm_text = confirm_text
        self._position_key = position_key.strip().rstrip("/")
        self._position_parent = position_parent
        self._position_initialized = False
        self._last_saved_offset: tuple[int, int] | None = None
        self._drag_offset: QPoint | None = None
        self._drag_source: QWidget | None = None
        self._system_move_active = False
        self._system_move_poll = QTimer(self)
        self._system_move_poll.setInterval(40)
        self._system_move_poll.timeout.connect(self._poll_system_move)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        surface = QFrame(self)
        surface.setObjectName("confirmDialogSurface")
        outer.addWidget(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)

        self.header = QWidget(surface)
        self.header.setObjectName("confirmDialogHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(20, 14, 12, 12)
        header_layout.setSpacing(10)
        self.title_label = QLabel(title, self.header)
        self.title_label.setObjectName("confirmDialogTitle")
        header_layout.addWidget(self.title_label, 1)
        self.close_button = QToolButton(self.header)
        self.close_button.setObjectName("confirmDialogCloseButton")
        self.close_button.setText("×")
        self.close_button.setToolTip("关闭")
        self.close_button.setAccessibleName("关闭")
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button, 0, Qt.AlignVCenter)
        surface_layout.addWidget(self.header)
        self.header.installEventFilter(self)
        self.title_label.installEventFilter(self)

        self.scroll_area = QScrollArea(surface)
        self.scroll_area.setObjectName("confirmDialogScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("confirmDialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 20, 22, 20)
        content_layout.setSpacing(12)

        heading_label = QLabel(heading, content)
        heading_label.setObjectName("confirmDialogHeading")
        heading_label.setWordWrap(True)
        content_layout.addWidget(heading_label)

        if description:
            description_label = QLabel(description, content)
            description_label.setObjectName("confirmDialogDescription")
            description_label.setWordWrap(True)
            content_layout.addWidget(description_label)

        if info_value:
            info_box = QFrame(content)
            info_box.setObjectName("confirmDialogInfo")
            info_layout = QVBoxLayout(info_box)
            info_layout.setContentsMargins(12, 9, 12, 9)
            info_layout.setSpacing(3)
            if info_label:
                label = QLabel(info_label, info_box)
                label.setObjectName("confirmDialogInfoLabel")
                info_layout.addWidget(label)
            value = QLabel(info_value, info_box)
            value.setObjectName("confirmDialogInfoValue")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            info_layout.addWidget(value)
            content_layout.addWidget(info_box)

        for section_title, items in sections:
            section_label = QLabel(section_title, content)
            section_label.setObjectName("confirmDialogSectionTitle")
            content_layout.addWidget(section_label)
            for item in items:
                item_label = QLabel(f"• {item}", content)
                item_label.setObjectName("confirmDialogSectionItem")
                item_label.setWordWrap(True)
                content_layout.addWidget(item_label)

        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        surface_layout.addWidget(self.scroll_area, 1)

        footer = QWidget(surface)
        footer.setObjectName("confirmDialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 14)
        footer_layout.setSpacing(10)
        footer_layout.addStretch(1)
        self.cancel_button = QPushButton("取消", footer)
        self.cancel_button.setObjectName("confirmDialogCancelButton")
        self.cancel_button.setMinimumHeight(36)
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        footer_layout.addWidget(self.cancel_button)
        self.confirm_button = QPushButton(confirm_text, footer)
        self.confirm_button.setObjectName("confirmDialogConfirmButton")
        self.confirm_button.setProperty("buttonRole", "danger" if destructive else "primary")
        self.confirm_button.setMinimumHeight(36)
        self.confirm_button.setDefault(False)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self._on_confirm_clicked)
        footer_layout.addWidget(self.confirm_button)
        surface_layout.addWidget(footer)

        self.setMinimumWidth(430)
        self.setMaximumWidth(520)
        self.resize(470, 320)

    @property
    def action_succeeded(self) -> bool:
        return self._action_succeeded

    def confirm(self) -> bool:
        return self.exec() == QDialog.Accepted

    def run_action(self, action: Callable[[], ActionResult]) -> bool:
        self._action = action
        self.exec()
        return self._action_succeeded

    def exec(self) -> int:  # type: ignore[override]
        if self._position_key:
            self._position_initialized = False
            self._restore_or_center_position()
        return super().exec()

    def accept(self) -> None:  # type: ignore[override]
        self._clamp_and_save_position()
        super().accept()

    def reject(self) -> None:  # type: ignore[override]
        if self._busy:
            return
        self._clamp_and_save_position()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._busy:
            event.ignore()
            return
        self._clamp_and_save_position()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self._busy:
            self.cancel_button.click()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched not in (self.header, self.title_label):
            return super().eventFilter(watched, event)
        if not isinstance(event, QMouseEvent):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            window_handle = self.windowHandle()
            if window_handle is not None and window_handle.startSystemMove():
                self._system_move_active = True
                self._system_move_poll.start()
                event.accept()
                return True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_source = watched
            watched.grabMouse()
            event.accept()
            return True
        if event.type() == QEvent.MouseMove and self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            candidate = event.globalPosition().toPoint() - self._drag_offset
            self.move(candidate if self._position_key else self._bounded_drag_position(candidate))
            event.accept()
            return True
        if event.type() == QEvent.MouseButtonRelease and self._system_move_active:
            self._finish_system_move()
            event.accept()
            return True
        if event.type() == QEvent.MouseButtonRelease and self._drag_offset is not None:
            self._finish_manual_drag()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _bounded_drag_position(self, candidate: QPoint) -> QPoint:
        screen = QGuiApplication.screenAt(candidate + QPoint(self.width() // 2, self.header.height() // 2))
        if screen is None:
            screen = DialogSizeManager._screen_for_parent(self.parentWidget(), self)
        if screen is None:
            return candidate
        available = screen.availableGeometry()
        visible_title_width = min(120, self.width())
        min_x = available.left() - self.width() + visible_title_width
        max_x = available.right() - visible_title_width + 1
        min_y = available.top()
        max_y = available.bottom() - max(1, self.header.height()) + 1
        return QPoint(
            min(max(candidate.x(), min_x), max_x),
            min(max(candidate.y(), min_y), max_y),
        )

    def _finish_manual_drag(self) -> None:
        if self._drag_source is not None:
            self._drag_source.releaseMouse()
        self._drag_source = None
        self._drag_offset = None
        self._clamp_and_save_position()

    def _poll_system_move(self) -> None:
        if not self._system_move_active:
            self._system_move_poll.stop()
            return
        if not QApplication.mouseButtons() & Qt.LeftButton:
            self._finish_system_move()

    def _finish_system_move(self) -> None:
        self._system_move_poll.stop()
        self._system_move_active = False
        self._clamp_and_save_position()

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._position_key:
            if not self._position_initialized:
                QTimer.singleShot(0, self._restore_or_center_position)
        else:
            QTimer.singleShot(0, self._fit_and_center)
        self.cancel_button.setFocus(Qt.OtherFocusReason)

    def _parent_rect(self):
        return DialogSizeManager.parent_rect(self, self._position_parent)

    def _prepare_positioned_size(self) -> None:
        self.adjustSize()
        parent_rect = self._parent_rect()
        if parent_rect is None:
            return
        max_width = max(1, int(parent_rect.width() * 0.90))
        max_height = max(1, int(parent_rect.height() * 0.85))
        minimum_width = min(430, max_width)
        maximum_width = max(minimum_width, min(520, max_width))
        self.setMinimumWidth(minimum_width)
        self.setMaximumWidth(maximum_width)
        self.setMaximumHeight(max_height)
        hint = self.sizeHint()
        target_width = min(max(hint.width(), minimum_width), maximum_width)
        target_height = min(hint.height(), max_height)
        self.resize(QSize(target_width, target_height))

    def _clamped_parent_position(self, candidate: QPoint) -> QPoint:
        return DialogSizeManager.clamp_to_parent(self, candidate, self._position_parent)

    def _centered_parent_position(self) -> QPoint:
        return DialogSizeManager.centered_position(self, self._position_parent)

    def _saved_parent_position(self) -> QPoint | None:
        return DialogSizeManager.restore_position(self, self._position_key, self._position_parent)

    def _restore_or_center_position(self) -> None:
        if not self._position_key or self._position_initialized:
            return
        self._prepare_positioned_size()
        position = self._saved_parent_position() or self._centered_parent_position()
        self.move(position)
        self._position_initialized = True

    def _clamp_and_save_position(self) -> None:
        if not self._position_key or not self._position_initialized or not self.isVisible():
            return
        parent_rect = self._parent_rect()
        if parent_rect is None:
            return
        safe_position = self._clamped_parent_position(self.frameGeometry().topLeft())
        if safe_position != self.frameGeometry().topLeft():
            self.move(safe_position)
        offset = (safe_position.x() - parent_rect.left(), safe_position.y() - parent_rect.top())
        if offset == self._last_saved_offset:
            return
        DialogSizeManager.remember(self, self._position_key, self._position_parent)
        self._last_saved_offset = offset

    def _fit_and_center(self) -> None:
        self.adjustSize()
        parent = DialogSizeManager.resolve_dialog_parent(self, self.parentWidget())
        parent_rect = DialogSizeManager.parent_rect(self, parent)
        if parent_rect is not None:
            max_width = max(1, int(parent_rect.width() * 0.90))
            max_height = max(1, int(parent_rect.height() * 0.85))
            self.setMinimumWidth(min(430, max_width))
            self.setMaximumSize(max_width, max_height)
            self.resize(min(self.width(), max_width), min(self.height(), max_height))
        DialogSizeManager.center_on_parent(self, parent)

    def _on_confirm_clicked(self) -> None:
        if self._busy:
            return
        if self._action is None:
            self.accept()
            return
        self._set_busy(True)
        QTimer.singleShot(0, self._execute_action)

    def _execute_action(self) -> None:
        try:
            result = self._action() if self._action is not None else True
            if isinstance(result, tuple):
                success, error_message = bool(result[0]), str(result[1] or "")
            else:
                success, error_message = bool(result), ""
        except Exception as exc:
            success, error_message = False, str(exc)
        if success:
            self._action_succeeded = True
            self.accept()
            return
        self._set_busy(False)
        show_toast(self, error_message or "操作失败", "error", 3500)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.cancel_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.confirm_button.setEnabled(not busy)
        self.confirm_button.setText("处理中…" if busy else self._confirm_text)


def confirm_action(
    parent: QWidget,
    *,
    title: str,
    heading: str,
    description: str = "",
    info_label: str = "",
    info_value: str = "",
    sections: Sequence[tuple[str, Sequence[str]]] = (),
    confirm_text: str = "确定",
    destructive: bool = False,
    position_key: str = "",
) -> bool:
    dialog = ConfirmActionDialog(
        title=title,
        heading=heading,
        description=description,
        info_label=info_label,
        info_value=info_value,
        sections=sections,
        confirm_text=confirm_text,
        destructive=destructive,
        position_key=position_key,
        parent=parent,
    )
    return dialog.confirm()
