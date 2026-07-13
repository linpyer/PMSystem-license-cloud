from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton, QWidget

from app.ui.theme_icons import themed_svg_icon


class ThemedClearableLineEdit(QLineEdit):
    """A line edit with one precisely positioned, theme-aware clear button."""

    BUTTON_SIZE = 30
    ICON_SIZE = 18
    RIGHT_MARGIN = 7
    TEXT_GAP = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setClearButtonEnabled(False)
        self._theme_manager = QApplication.instance().property("theme_manager") if QApplication.instance() else None
        self._clear_button = QToolButton(self)
        self._clear_button.setObjectName("clearInputButton")
        self._clear_button.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        self._clear_button.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.setFocusPolicy(Qt.NoFocus)
        self._clear_button.setToolTip("清空")
        self._clear_button.setAccessibleName("清空")
        self._clear_button.clicked.connect(self._clear_and_refocus)
        self._clear_button.hide()

        margins = self.textMargins()
        self.setTextMargins(
            margins.left(),
            margins.top(),
            self.BUTTON_SIZE + self.RIGHT_MARGIN + self.TEXT_GAP,
            margins.bottom(),
        )
        self.textChanged.connect(self._sync_clear_button_visibility)
        if self._theme_manager is not None:
            self._theme_manager.theme_changed.connect(self._refresh_clear_icon)
        self._refresh_clear_icon()
        self._position_clear_button()

    def clear_button(self) -> QToolButton:
        return self._clear_button

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_clear_button()

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._position_clear_button()
        self._sync_clear_button_visibility(self.text())

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange and hasattr(self, "_clear_button"):
            self._sync_clear_button_visibility(self.text())

    def _position_clear_button(self) -> None:
        rect = self.contentsRect()
        x = rect.x() + rect.width() - self.BUTTON_SIZE - self.RIGHT_MARGIN
        y = rect.y() + (rect.height() - self.BUTTON_SIZE) // 2
        self._clear_button.setGeometry(x, y, self.BUTTON_SIZE, self.BUTTON_SIZE)
        self._clear_button.raise_()

    def _sync_clear_button_visibility(self, text: str) -> None:
        self._clear_button.setVisible(self.isEnabled() and bool(text))

    def _clear_and_refocus(self) -> None:
        self.clear()
        self.setFocus(Qt.MouseFocusReason)

    def _refresh_clear_icon(self, *_args) -> None:
        self._clear_button.setIcon(themed_svg_icon("x", self._theme_manager, size=self.ICON_SIZE))
