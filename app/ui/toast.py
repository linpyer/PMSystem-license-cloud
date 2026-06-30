from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import QLabel, QWidget


class ToastManager(QObject):
    def __init__(self, parent: QWidget, logger: logging.Logger | None = None) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.logger = logger
        self.label = QLabel(parent)
        self.label.setObjectName("toastLabel")
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.label.hide()

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.label.hide)

        parent.installEventFilter(self)
        if self.logger:
            self.logger.info("Toast 组件初始化成功：%s", parent.__class__.__name__)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.parent_widget and event.type() in (QEvent.Resize, QEvent.Show):
            self._reposition()
        return super().eventFilter(watched, event)

    def show(self, message: str, level: str = "info", duration_ms: int = 2200) -> None:
        if not message:
            return
        try:
            self.timer.stop()
            self.label.setStyleSheet(self._style(level))
            self.label.setText(message)

            max_width = max(180, min(420, self.parent_widget.width() - 24))
            min_width = min(160, max_width)
            self.label.setMinimumWidth(min_width)
            self.label.setMaximumWidth(max_width)
            self.label.adjustSize()
            if self.label.width() > max_width:
                self.label.setFixedWidth(max_width)
                self.label.adjustSize()

            self._reposition()
            self.label.raise_()
            self.label.show()
            self.timer.start(max(800, int(duration_ms)))
        except Exception:
            if self.logger:
                self.logger.exception("Toast 显示异常")

    def _reposition(self) -> None:
        if not self.label.isVisible() and not self.label.text():
            return
        parent_height = max(1, self.parent_widget.height())
        x = 12
        y = max(12, parent_height - self.label.height() - 12)
        self.label.move(x, y)

    @staticmethod
    def _style(level: str) -> str:
        styles = {
            "success": (
                "background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 600; line-height: 1.35;"
            ),
            "error": (
                "background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 600; line-height: 1.35;"
            ),
            "warning": (
                "background: #fffbeb; color: #92400e; border: 1px solid #fde68a; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 600; line-height: 1.35;"
            ),
            "critical": (
                "background: #fef2f2; color: #7f1d1d; border: 1px solid #fca5a5; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 700; line-height: 1.35;"
            ),
            "info": (
                "background: #eff6ff; color: #1e3a8a; border: 1px solid #bfdbfe; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 600; line-height: 1.35;"
            ),
        }
        return styles.get(level, styles["info"])


def _status_tip_target(parent: QWidget) -> QWidget | None:
    widget: QWidget | None = parent
    while widget is not None:
        if callable(getattr(widget, "show_status_tip", None)):
            return widget
        widget = widget.parentWidget()
    window = parent.window()
    if isinstance(window, QWidget) and callable(getattr(window, "show_status_tip", None)):
        return window
    return None


def show_toast(
    parent: QWidget,
    message: str,
    level: str = "info",
    duration_ms: int = 2200,
    logger: logging.Logger | None = None,
) -> None:
    try:
        target = _status_tip_target(parent)
        if target is not None:
            target.show_status_tip(message, level, duration_ms)  # type: ignore[attr-defined]
            return

        manager = getattr(parent, "_toast_manager", None)
        if not isinstance(manager, ToastManager):
            manager = ToastManager(parent, logger)
            setattr(parent, "_toast_manager", manager)
        manager.show(message, level, duration_ms)
    except Exception:
        if logger:
            logger.exception("Toast 组件初始化失败")
