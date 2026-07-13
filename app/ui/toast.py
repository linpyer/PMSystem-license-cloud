from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QWidget,
)


class ToastManager(QObject):
    """A single non-blocking notification queue anchored to its owning window."""

    _show_requested = Signal(str, str, int)
    _dedupe_seconds = 1.8
    _max_queue_length = 5
    _fade_in_duration_ms = 140
    _default_dwell_duration_ms = 2400
    _fade_out_duration_ms = 180

    def __init__(self, parent: QWidget, logger: logging.Logger | None = None) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.logger = logger
        self.container = QWidget(parent)
        self.container.setObjectName("toastOverlay")
        self.container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(8, 6, 8, 10)
        container_layout.setSpacing(0)

        self.label = QLabel(self.container)
        self.label.setObjectName("toastLabel")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setMinimumHeight(40)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        container_layout.addWidget(self.label)

        self.container.hide()

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._begin_fade_out)
        self._opacity_effect = QGraphicsOpacityEffect(self.container)
        self._opacity_effect.setOpacity(1.0)
        self.container.setGraphicsEffect(self._opacity_effect)
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_in.setDuration(self._fade_in_duration_ms)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_in.finished.connect(self._on_fade_in_finished)
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_out.setDuration(self._fade_out_duration_ms)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_finished)
        self._state = "idle"
        self._queue: list[tuple[str, str, int]] = []
        self._active_message = ""
        self._active_level = "info"
        self._active_duration_ms = self._default_dwell_duration_ms
        self._last_message = ""
        self._last_message_time = 0.0
        self._position_sources: list[QWidget] = []
        self._phase_started_at = 0.0

        self._show_requested.connect(self._enqueue, Qt.QueuedConnection)

        parent.installEventFilter(self)
        if self.logger:
            self.logger.info("Toast manager initialized: %s", parent.__class__.__name__)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.parent_widget and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.Move,
            QEvent.WindowStateChange,
            QEvent.ScreenChangeInternal,
            QEvent.LayoutRequest,
        ):
            self.reposition()
        elif watched is self.parent_widget and event.type() in (QEvent.Close, QEvent.Destroy):
            self.clear()
        elif watched is self.parent_widget and event.type() == QEvent.Hide and isinstance(self.parent_widget, QDialog):
            self.clear()
        elif watched in self._position_sources and event.type() in (
            QEvent.Resize,
            QEvent.Move,
            QEvent.Show,
            QEvent.Hide,
            QEvent.LayoutRequest,
        ):
            QTimer.singleShot(0, self.reposition)
        return super().eventFilter(watched, event)

    def watch_position_sources(self, *widgets: QWidget) -> None:
        """Reposition when title-bar navigation widgets are relaid out."""
        for widget in widgets:
            if widget in self._position_sources:
                continue
            self._position_sources.append(widget)
            widget.installEventFilter(self)

    def reposition(self) -> None:
        """Recalculate size and position without changing the active toast."""
        if not self._active_message or not self.label.text():
            return
        if not self._resize_to_content():
            self.container.hide()
            return
        self._reposition()
        if self._state != "idle" and self.parent_widget.isVisible() and not self.container.isVisible():
            self.container.show()
            self.container.raise_()

    def show(self, message: str, level: str = "info", duration_ms: int = 2400) -> None:
        message = str(message or "").strip()
        if not message:
            return
        normalized_level = level if level in {"success", "info", "warning", "error", "critical"} else "info"
        effective_duration = (
            max(3500, int(duration_ms))
            if normalized_level in {"error", "critical"}
            else max(self._default_dwell_duration_ms, int(duration_ms))
        )
        self._log_phase("request", text=message, duration=effective_duration)
        if QThread.currentThread() is not self.thread():
            self._show_requested.emit(message, normalized_level, effective_duration)
            return
        self._enqueue(message, normalized_level, effective_duration)

    @Slot(str, str, int)
    def _enqueue(self, message: str, level: str, duration_ms: int) -> None:
        try:
            now = time.monotonic()
            if message == self._active_message and now - self._last_message_time < self._dedupe_seconds:
                self._last_message_time = now
                return
            if message == self._last_message and now - self._last_message_time < self._dedupe_seconds:
                return
            if any(item[0] == message for item in self._queue):
                return

            self._last_message = message
            self._last_message_time = now
            if len(self._queue) >= self._max_queue_length:
                self._queue.pop(0)
            self._queue.append((message, level, duration_ms))
            if self._state == "idle":
                self._show_next()
        except Exception:
            if self.logger:
                self.logger.exception("Toast display failed")

    def clear(self) -> None:
        """Discard pending notifications when their owning window closes."""
        self.timer.stop()
        self._fade_in.stop()
        self._fade_out.stop()
        self._queue.clear()
        self._active_message = ""
        self._active_level = "info"
        self._active_duration_ms = self._default_dwell_duration_ms
        self._last_message = ""
        self._last_message_time = 0.0
        self._phase_started_at = 0.0
        self._state = "idle"
        self.label.clear()
        self.container.hide()
        self._opacity_effect.setOpacity(1.0)

    def _show_next(self) -> None:
        if not self._queue:
            return
        message, level, duration_ms = self._queue.pop(0)
        self._active_message = message
        self._active_level = level
        self._active_duration_ms = duration_ms
        self.timer.stop()
        self._fade_in.stop()
        self._fade_out.stop()
        self.label.setStyleSheet(self._style(level))
        self.label.setText(message)
        if not self._resize_to_content():
            self.label.clear()
            self._active_message = ""
            self._state = "idle"
            QTimer.singleShot(0, self._show_next)
            return
        self._reposition()
        self._state = "fading_in"
        self._opacity_effect.setOpacity(0.0)
        self.container.show()
        self.container.raise_()
        self._phase_started_at = time.monotonic()
        self._log_phase("fade_in_started")
        self._fade_in.start()

    def _on_fade_in_finished(self) -> None:
        if self._state != "fading_in":
            return
        self._state = "visible"
        self._opacity_effect.setOpacity(1.0)
        self.container.show()
        self.container.raise_()
        self.container.update()
        self.label.update()
        self._log_phase("fade_in_finished", elapsed_ms=self._phase_elapsed_ms())
        self._phase_started_at = time.monotonic()
        self._log_phase("dwell_started", duration=self._active_duration_ms)
        self.timer.start(self._active_duration_ms)
        QTimer.singleShot(0, self._ensure_visible_during_dwell)

    def _ensure_visible_during_dwell(self) -> None:
        """Reassert the overlay after the animation releases its paint cache."""
        if self._state != "visible":
            return
        self._opacity_effect.setOpacity(1.0)
        self.container.show()
        self.container.raise_()
        self.container.update()
        self.label.update()

    def _begin_fade_out(self) -> None:
        if self._state != "visible":
            return
        self.timer.stop()
        self._state = "fading_out"
        self._fade_out.stop()
        self._fade_out.setStartValue(self._opacity_effect.opacity())
        self._log_phase("dwell_finished", elapsed_ms=self._phase_elapsed_ms())
        self._phase_started_at = time.monotonic()
        self._log_phase("fade_out_started")
        self._fade_out.start()

    def _on_fade_out_finished(self) -> None:
        if self._state != "fading_out":
            return
        self.container.hide()
        self.label.clear()
        self._active_message = ""
        self._active_level = "info"
        self._state = "idle"
        self._opacity_effect.setOpacity(1.0)
        self._log_phase("hidden", elapsed_ms=self._phase_elapsed_ms())
        QTimer.singleShot(0, self._show_next)

    def _resize_to_content(self) -> bool:
        anchor = self._titlebar_anchor_rect()
        if anchor is not None:
            shadow_width = 16
            available_width = anchor.width()
            if available_width < 160:
                return False
            horizontal_padding = 42
            desired_width = self.label.fontMetrics().horizontalAdvance(self._active_message) + horizontal_padding + shadow_width
            container_width = min(560, available_width, max(220, desired_width))
            label_width = container_width - shadow_width
            text_width = max(16, label_width - horizontal_padding)
            display_text = self.label.fontMetrics().elidedText(self._active_message, Qt.ElideRight, text_width)
            self.label.setWordWrap(False)
            self.label.setText(display_text)
            self.label.setFixedSize(label_width, 34)
            self.container.setFixedSize(container_width, 50)
            return True

        max_width = max(220, min(560, self.parent_widget.width() - 32))
        text_width = self.label.fontMetrics().horizontalAdvance(self._active_message) + 44
        width = min(max_width, max(220, text_width))
        self.label.setWordWrap(True)
        self.label.setText(self._active_message)
        self.label.setFixedWidth(width)
        self.label.setMinimumHeight(40)
        self.label.setMaximumHeight(self.label.fontMetrics().lineSpacing() * 2 + 24)
        self.label.adjustSize()
        self.container.setMinimumSize(0, 0)
        self.container.setMaximumSize(16777215, 16777215)
        self.container.adjustSize()
        return True

    def _phase_elapsed_ms(self) -> int:
        if self._phase_started_at <= 0:
            return 0
        return int(round((time.monotonic() - self._phase_started_at) * 1000))

    def _log_phase(self, phase: str, **details) -> None:
        if self.logger is None:
            return
        suffix = " ".join(f"{key}={value}" for key, value in details.items())
        self.logger.debug("[Toast] %s%s", phase, f" {suffix}" if suffix else "")

    def _reposition(self) -> None:
        if not self.label.isVisible() and not self.label.text():
            return
        anchor = self._titlebar_anchor_rect()
        if anchor is not None:
            x = anchor.left() + max(0, (anchor.width() - self.container.width()) // 2)
            y = anchor.top() + max(0, (anchor.height() - self.container.height()) // 2)
            self.container.move(x, y)
            return
        parent_width = max(1, self.parent_widget.width())
        x = max(16, (parent_width - self.container.width()) // 2)
        y = 16
        navigation = getattr(self.parent_widget, "tabs", None)
        if isinstance(navigation, QTabWidget):
            y = navigation.geometry().top() + navigation.tabBar().height() + 14
        self.container.move(x, y)

    def _titlebar_anchor_rect(self) -> QRect | None:
        resolver = getattr(self.parent_widget, "toast_titlebar_available_rect", None)
        if not callable(resolver):
            return None
        try:
            rect = resolver()
        except Exception:
            if self.logger:
                self.logger.exception("Toast title-bar geometry calculation failed")
            return None
        return rect if isinstance(rect, QRect) and rect.isValid() else None

    def _style(self, _level: str) -> str:
        app = QApplication.instance()
        theme_manager = app.property("theme_manager") if app is not None else None
        tokens = theme_manager.current_tokens() if theme_manager is not None else None
        if tokens is None:
            background, foreground, border = "#ffffff", "#202123", "#d1d5db"
        else:
            background, foreground, border = tokens.surface, tokens.text_primary, tokens.border
        compact = self._titlebar_anchor_rect() is not None
        geometry_style = "border-radius: 17px; padding: 0 16px;" if compact else "border-radius: 12px; padding: 10px 16px;"
        return (
            f"background: {_with_alpha(background, 225)}; color: {foreground}; "
            f"border: 1px solid {_with_alpha(border, 210)}; "
            f"{geometry_style} font-weight: 600; line-height: 1.35;"
        )


def _with_alpha(color: str, alpha: int) -> str:
    value = color.lstrip("#")
    if len(value) != 6:
        return color
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {max(0, min(255, alpha))})"


def _status_tip_target(parent: QWidget) -> QWidget | None:
    window = parent.window()
    if isinstance(window, QDialog):
        return None
    widget: QWidget | None = parent
    while widget is not None:
        if callable(getattr(widget, "show_status_tip", None)):
            return widget
        widget = widget.parentWidget()
    if isinstance(window, QWidget) and callable(getattr(window, "show_status_tip", None)):
        return window
    return None


def show_toast(
    parent: QWidget,
    message: str,
    level: str = "info",
    duration_ms: int = 2400,
    logger: logging.Logger | None = None,
) -> None:
    try:
        target = _status_tip_target(parent)
        if target is not None:
            target.show_status_tip(message, level, duration_ms)  # type: ignore[attr-defined]
            return

        toast_parent = parent.window() if isinstance(parent.window(), QDialog) else parent
        manager = getattr(toast_parent, "_toast_manager", None)
        if not isinstance(manager, ToastManager):
            manager = ToastManager(toast_parent, logger)
            setattr(toast_parent, "_toast_manager", manager)
        manager.show(message, level, duration_ms)
    except Exception:
        if logger:
            logger.exception("Toast manager initialization failed")
