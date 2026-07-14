from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QScrollArea,
    QWidget,
)

from app.core.version import APP_DATA_DIR_NAME


DialogSizeClass = Literal["small", "medium", "large"]


class WheelPassthroughFilter(QObject):
    """Prevents accidental wheel changes on compact settings controls."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)
        widget = watched if isinstance(watched, QWidget) else None
        if widget is None:
            return super().eventFilter(watched, event)
        if isinstance(widget, QComboBox) and widget.view().isVisible():
            return False
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                QGuiApplication.sendEvent(parent.viewport(), event)
                return True
            parent = parent.parentWidget()
        event.ignore()
        return True


_wheel_filter: WheelPassthroughFilter | None = None


def install_no_wheel_on_children(root: QWidget) -> None:
    global _wheel_filter
    if _wheel_filter is None:
        _wheel_filter = WheelPassthroughFilter(root)
    installed: set[int] = set()
    for widget_type in (QComboBox, QAbstractSpinBox):
        for widget in root.findChildren(widget_type):
            marker = id(widget)
            if marker in installed:
                continue
            installed.add(marker)
            widget.installEventFilter(_wheel_filter)
            widget.setFocusPolicy(Qt.StrongFocus)


class DialogSizeManager:
    _file_name = "dialog_sizes.json"
    _ratios: dict[DialogSizeClass, tuple[float, float]] = {
        "small": (0.50, 0.40),
        "medium": (0.70, 0.65),
        "large": (0.85, 0.80),
    }

    @classmethod
    def _store_path(cls) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_DATA_DIR_NAME / cls._file_name

    @classmethod
    def _load(cls) -> dict[str, dict[str, int]]:
        try:
            path = cls._store_path()
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _save(cls, data: dict[str, dict[str, int]]) -> None:
        path = cls._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def apply(
        cls,
        dialog: QDialog,
        key: str,
        parent: QWidget | None = None,
        size_class: DialogSizeClass = "medium",
        minimum: tuple[int, int] = (520, 360),
    ) -> None:
        cls._install_controller(
            dialog,
            key=key,
            parent=parent,
            size_class=size_class,
            minimum=minimum,
            remember_position=True,
            natural_size=False,
        )

    @classmethod
    def position_transient(cls, dialog: QDialog, parent: QWidget | None = None) -> None:
        """Position a short-lived dialog once without persisting its geometry."""
        cls._install_controller(
            dialog,
            key="",
            parent=parent,
            size_class="small",
            minimum=(1, 1),
            remember_position=False,
            natural_size=True,
        )

    @classmethod
    def _install_controller(
        cls,
        dialog: QDialog,
        *,
        key: str,
        parent: QWidget | None,
        size_class: DialogSizeClass,
        minimum: tuple[int, int],
        remember_position: bool,
        natural_size: bool,
    ) -> None:
        controller = getattr(dialog, "_dialog_position_controller", None)
        if isinstance(controller, _DialogPositionController):
            controller.update_config(key, parent, size_class, minimum, remember_position, natural_size)
        else:
            controller = _DialogPositionController(
                dialog,
                key=key,
                parent=parent,
                size_class=size_class,
                minimum=minimum,
                remember_position=remember_position,
                natural_size=natural_size,
            )
            setattr(dialog, "_dialog_position_controller", controller)
        controller.position_now()

    @staticmethod
    def resolve_dialog_parent(dialog: QDialog, parent: QWidget | None = None) -> QWidget | None:
        candidate = parent or dialog.parentWidget()
        if candidate is None or candidate is dialog:
            return None
        try:
            top_level = candidate.window()
        except RuntimeError:
            return None
        if top_level is dialog:
            candidate = dialog.parentWidget()
            if candidate is None or candidate is dialog:
                return None
            top_level = candidate.window()
        return top_level if isinstance(top_level, QWidget) and top_level is not dialog else candidate

    @classmethod
    def parent_rect(cls, dialog: QDialog, parent: QWidget | None = None) -> QRect | None:
        top_level = cls.resolve_dialog_parent(dialog, parent)
        if top_level is None or top_level.width() <= 0 or top_level.height() <= 0:
            return None
        return top_level.frameGeometry()

    @staticmethod
    def _storage_key(key: str) -> str:
        normalized = str(key or "").strip().strip("/")
        return f"ui/dialog_positions/{normalized}" if normalized else ""

    @classmethod
    def _saved_geometry(cls, key: str) -> dict[str, int]:
        storage_key = cls._storage_key(key)
        saved = cls._load().get(storage_key, {}) if storage_key else {}
        return saved if isinstance(saved, dict) else {}

    @classmethod
    def _apply_now(
        cls,
        dialog: QDialog,
        *,
        key: str,
        parent: QWidget | None,
        size_class: DialogSizeClass,
        minimum: tuple[int, int],
        remember_position: bool,
        natural_size: bool,
    ) -> QWidget | None:
        parent_widget = cls.resolve_dialog_parent(dialog, parent)
        parent_rect = cls.parent_rect(dialog, parent_widget)
        screen = cls._screen_for_parent(parent_widget, dialog)
        available = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        bounds = parent_rect or available
        max_width = max(1, int(bounds.width() * 0.90))
        max_height = max(1, int(bounds.height() * 0.85))
        saved = cls._saved_geometry(key) if remember_position else {}

        if natural_size:
            if dialog.layout() is not None:
                dialog.layout().activate()
            dialog.adjustSize()
            width = min(max(1, dialog.width()), max_width)
            height = min(max(1, dialog.height()), max_height)
            dialog.setMaximumSize(max_width, max_height)
        else:
            effective_min_width = min(minimum[0], max_width)
            effective_min_height = min(minimum[1], max_height)
            dialog.setMinimumSize(effective_min_width, effective_min_height)
            dialog.setMaximumSize(max_width, max_height)
            if saved.get("width") and saved.get("height"):
                width = int(saved.get("width") or 0)
                height = int(saved.get("height") or 0)
            else:
                ratio_w, ratio_h = cls._ratios.get(size_class, cls._ratios["medium"])
                width = int(bounds.width() * ratio_w)
                height = int(bounds.height() * ratio_h)
            width = max(effective_min_width, min(width, max_width))
            height = max(effective_min_height, min(height, max_height))
        dialog.resize(width, height)

        restore_position = cls.restore_position(dialog, key, parent_widget) if remember_position else None
        candidate = restore_position or cls.centered_position(dialog, parent_widget, available)
        dialog.move(cls.clamp_to_parent(dialog, candidate, parent_widget, available))
        return parent_widget

    @staticmethod
    def _screen_for_parent(parent: QWidget | None, dialog: QDialog):
        if parent is not None:
            screen = QGuiApplication.screenAt(parent.frameGeometry().center())
            if screen is not None:
                return screen
            if parent.screen() is not None:
                return parent.screen()
        return dialog.screen() or QGuiApplication.primaryScreen()

    @classmethod
    def restore_position(cls, dialog: QDialog, key: str, parent: QWidget | None = None) -> QPoint | None:
        saved = cls._saved_geometry(key)
        if not saved or not saved.get("position_saved"):
            return None
        parent_rect = cls.parent_rect(dialog, parent)
        if parent_rect is None:
            return None
        try:
            offset_x = int(saved.get("offset_x"))
            offset_y = int(saved.get("offset_y"))
        except (TypeError, ValueError):
            return None
        candidate = QPoint(parent_rect.left() + offset_x, parent_rect.top() + offset_y)
        candidate_rect = QRect(candidate, dialog.size())
        if not candidate_rect.intersects(parent_rect):
            return None
        return cls.clamp_to_parent(dialog, candidate, parent)

    @classmethod
    def centered_position(
        cls,
        dialog: QDialog,
        parent: QWidget | None = None,
        available: QRect | None = None,
    ) -> QPoint:
        parent_rect = cls.parent_rect(dialog, parent)
        bounds = parent_rect or available
        if bounds is None:
            screen = cls._screen_for_parent(cls.resolve_dialog_parent(dialog, parent), dialog)
            bounds = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        return QPoint(
            bounds.left() + (bounds.width() - dialog.width()) // 2,
            bounds.top() + (bounds.height() - dialog.height()) // 2,
        )

    @classmethod
    def clamp_to_parent(
        cls,
        dialog: QDialog,
        candidate: QPoint,
        parent: QWidget | None = None,
        available: QRect | None = None,
    ) -> QPoint:
        parent_rect = cls.parent_rect(dialog, parent)
        bounds = parent_rect or available
        if bounds is None:
            screen = cls._screen_for_parent(cls.resolve_dialog_parent(dialog, parent), dialog)
            bounds = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        max_x = bounds.right() - dialog.width() + 1
        max_y = bounds.bottom() - dialog.height() + 1
        x = bounds.left() if max_x < bounds.left() else min(max(candidate.x(), bounds.left()), max_x)
        y = bounds.top() if max_y < bounds.top() else min(max(candidate.y(), bounds.top()), max_y)
        return QPoint(x, y)

    @staticmethod
    def center_on_parent(dialog: QDialog, parent: QWidget | None = None, available=None) -> None:
        top_level = DialogSizeManager.resolve_dialog_parent(dialog, parent)
        candidate = DialogSizeManager.centered_position(dialog, top_level, available)
        dialog.move(DialogSizeManager.clamp_to_parent(dialog, candidate, top_level, available))

    @classmethod
    def remember(cls, dialog: QDialog, key: str, parent: QWidget | None = None) -> None:
        if not key:
            return
        parent_widget = cls.resolve_dialog_parent(dialog, parent)
        parent_rect = cls.parent_rect(dialog, parent_widget)
        if parent_rect is None:
            return
        safe_position = cls.clamp_to_parent(dialog, dialog.frameGeometry().topLeft(), parent_widget)
        if safe_position != dialog.frameGeometry().topLeft():
            dialog.move(safe_position)
        data = cls._load()
        data[cls._storage_key(key)] = {
            "width": max(1, dialog.width()),
            "height": max(1, dialog.height()),
            "offset_x": safe_position.x() - parent_rect.left(),
            "offset_y": safe_position.y() - parent_rect.top(),
            "position_saved": True,
        }
        try:
            cls._save(data)
        except Exception:
            return


class _DialogPositionController(QObject):
    """Applies one parent-relative position per show and remembers completed moves."""

    def __init__(
        self,
        dialog: QDialog,
        *,
        key: str,
        parent: QWidget | None,
        size_class: DialogSizeClass,
        minimum: tuple[int, int],
        remember_position: bool,
        natural_size: bool,
    ) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self._positioned = False
        self._show_generation = 0
        self._parent_origin: QPoint | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self._save_after_move)
        self.update_config(key, parent, size_class, minimum, remember_position, natural_size)
        dialog.installEventFilter(self)
        self.parent_widget = DialogSizeManager.resolve_dialog_parent(dialog, parent)
        if self.parent_widget is not None:
            self.parent_widget.installEventFilter(self)
        dialog.finished.connect(self._on_finished)

    def update_config(
        self,
        key: str,
        parent: QWidget | None,
        size_class: DialogSizeClass,
        minimum: tuple[int, int],
        remember_position: bool,
        natural_size: bool,
    ) -> None:
        self.key = key
        self.requested_parent = parent
        self.size_class = size_class
        self.minimum = minimum
        self.remember_position = remember_position
        self.natural_size = natural_size

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self.dialog:
            if event.type() == QEvent.Show:
                self._positioned = False
                self._show_generation += 1
                generation = self._show_generation
                QTimer.singleShot(0, lambda: self._position_after_show(generation))
            elif event.type() == QEvent.Move and self._positioned and self.dialog.isVisible():
                self._save_timer.start()
            elif event.type() in (QEvent.Hide, QEvent.Close):
                self._save_current_position()
                self._positioned = False
        elif watched is self.parent_widget and event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
            if self.dialog.isVisible() and self._positioned:
                QTimer.singleShot(0, self._follow_or_clamp_parent)
        return super().eventFilter(watched, event)

    def position_now(self) -> None:
        self.parent_widget = DialogSizeManager._apply_now(
            self.dialog,
            key=self.key,
            parent=self.requested_parent,
            size_class=self.size_class,
            minimum=self.minimum,
            remember_position=self.remember_position,
            natural_size=self.natural_size,
        )
        parent_rect = DialogSizeManager.parent_rect(self.dialog, self.parent_widget)
        self._parent_origin = parent_rect.topLeft() if parent_rect is not None else None
        self._positioned = True

    def _position_after_show(self, generation: int) -> None:
        if generation != self._show_generation or not self.dialog.isVisible():
            return
        self.position_now()

    def _follow_or_clamp_parent(self) -> None:
        if not self.dialog.isVisible() or not self._positioned:
            return
        parent_rect = DialogSizeManager.parent_rect(self.dialog, self.parent_widget)
        if parent_rect is None:
            return
        candidate = self.dialog.frameGeometry().topLeft()
        if self._parent_origin is not None:
            candidate += parent_rect.topLeft() - self._parent_origin
        self.dialog.move(DialogSizeManager.clamp_to_parent(self.dialog, candidate, self.parent_widget))
        self._parent_origin = parent_rect.topLeft()

    def _save_after_move(self) -> None:
        if QApplication.mouseButtons() & Qt.LeftButton:
            self._save_timer.start()
            return
        self._save_current_position()

    def _save_current_position(self) -> None:
        if self.remember_position and self._positioned:
            DialogSizeManager.remember(self.dialog, self.key, self.parent_widget)

    def _on_finished(self, _result: int) -> None:
        self._save_current_position()
