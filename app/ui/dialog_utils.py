from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
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
        min_width, min_height = minimum
        dialog.setMinimumSize(min_width, min_height)
        parent_widget = parent or dialog.parentWidget()
        screen = dialog.screen() or (parent_widget.screen() if parent_widget else QGuiApplication.primaryScreen())
        available = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        parent_width = parent_widget.width() if parent_widget and parent_widget.width() > 0 else available.width()
        parent_height = parent_widget.height() if parent_widget and parent_widget.height() > 0 else available.height()
        max_width = max(min_width, int(min(parent_width, available.width()) * 0.90))
        max_height = max(min_height, int(min(parent_height, available.height()) * 0.90))
        saved = cls._load().get(key, {})
        if isinstance(saved, dict) and saved.get("width") and saved.get("height"):
            width = int(saved.get("width") or 0)
            height = int(saved.get("height") or 0)
        else:
            ratio_w, ratio_h = cls._ratios.get(size_class, cls._ratios["medium"])
            width = int(parent_width * ratio_w)
            height = int(parent_height * ratio_h)
        width = max(min_width, min(width, max_width))
        height = max(min_height, min(height, max_height))
        dialog.resize(width, height)
        cls.center_on_parent(dialog, parent_widget, available)

    @staticmethod
    def center_on_parent(dialog: QDialog, parent: QWidget | None = None, available=None) -> None:
        frame = dialog.frameGeometry()
        if parent is not None and parent.isVisible():
            frame.moveCenter(parent.frameGeometry().center())
        elif available is not None:
            frame.moveCenter(available.center())
        dialog.move(frame.topLeft())

    @classmethod
    def remember(cls, dialog: QDialog, key: str) -> None:
        if not key:
            return
        data = cls._load()
        data[key] = {"width": max(1, dialog.width()), "height": max(1, dialog.height())}
        try:
            cls._save(data)
        except Exception:
            return
