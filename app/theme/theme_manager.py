from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget

from app.theme.theme_styles import build_theme_styles
from app.theme.theme_tokens import ThemeTokens, normalize_theme_mode, tokens_for
from app.ui.styles import APP_STYLES

if TYPE_CHECKING:
    from app.core.config_manager import ConfigManager


class ThemeManager(QObject):
    """Owns theme resolution, preview and persisted application styling."""

    theme_changed = Signal(str, str)

    def __init__(self, app: QApplication, config_manager: "ConfigManager") -> None:
        super().__init__(app)
        self._app = app
        self._config_manager = config_manager
        self._mode = self._configured_mode()
        self._preview_origin_mode: str | None = None
        self._system_signal_connected = False
        self._app.installEventFilter(self)
        self._connect_system_theme_signal()

    def current_mode(self) -> str:
        return self._mode

    def resolved_theme(self, mode: str | None = None) -> str:
        requested = normalize_theme_mode(mode if mode is not None else self._mode)
        return self._system_theme() if requested == "system" else requested

    def current_tokens(self) -> ThemeTokens:
        return tokens_for(self.resolved_theme())

    def apply_theme(self, mode: str | None = None) -> None:
        if mode is not None:
            self._mode = normalize_theme_mode(mode)
        resolved = self.resolved_theme()
        self._app.setStyleSheet(f"{APP_STYLES}\n{build_theme_styles(tokens_for(resolved))}")
        self._refresh_visible_widgets()
        self.theme_changed.emit(self._mode, resolved)

    def begin_preview(self) -> None:
        if self._preview_origin_mode is None:
            self._preview_origin_mode = self._mode

    def preview_theme(self, mode: str) -> None:
        self.begin_preview()
        self.apply_theme(normalize_theme_mode(mode))

    def commit_theme(self, mode: str) -> None:
        self._mode = normalize_theme_mode(mode)
        self._preview_origin_mode = None
        self.apply_theme()

    def cancel_preview(self) -> None:
        if self._preview_origin_mode is None:
            return
        original_mode = self._preview_origin_mode
        self._preview_origin_mode = None
        self.apply_theme(original_mode)

    def apply_configured_theme(self) -> None:
        self._preview_origin_mode = None
        self.apply_theme(self._configured_mode())

    def _configured_mode(self) -> str:
        raw = self._config_manager.config.get("appearance", {})
        return normalize_theme_mode(raw.get("theme") if isinstance(raw, dict) else "system")

    def _connect_system_theme_signal(self) -> None:
        hints = self._app.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is None:
            return
        try:
            signal.connect(self._on_system_color_scheme_changed)
            self._system_signal_connected = True
        except (RuntimeError, TypeError):
            self._system_signal_connected = False

    def _on_system_color_scheme_changed(self, *_args) -> None:
        if self._mode == "system":
            self.apply_theme()

    def _system_theme(self) -> str:
        hints = self._app.styleHints()
        getter = getattr(hints, "colorScheme", None)
        if callable(getter):
            try:
                scheme = getter()
                if scheme == Qt.ColorScheme.Dark:
                    return "dark"
                if scheme == Qt.ColorScheme.Light:
                    return "light"
            except (AttributeError, RuntimeError):
                pass
        return self._windows_theme_fallback()

    @staticmethod
    def _windows_theme_fallback() -> str:
        if sys.platform != "win32":
            return "light"
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            ) as key:
                apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(apps_use_light_theme) else "dark"
        except (FileNotFoundError, OSError, ValueError):
            return "light"

    def _refresh_visible_widgets(self) -> None:
        for widget in self._app.topLevelWidgets():
            if not widget.isVisible():
                continue
            self._apply_native_window_chrome(widget)
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Show and isinstance(watched, QWidget) and watched.isWindow():
            self._apply_native_window_chrome(watched)
        return super().eventFilter(watched, event)

    def _apply_native_window_chrome(self, widget: QWidget) -> None:
        """Apply the current palette to Windows-managed dialog title bars when available."""
        if sys.platform != "win32" or not widget.isWindow():
            return
        try:
            import ctypes

            tokens = self.current_tokens()

            def color_ref(value: str) -> int:
                value = value.lstrip("#")
                red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
                return red | (green << 8) | (blue << 16)

            hwnd = int(widget.winId())
            dark = ctypes.c_int(1 if self.resolved_theme() == "dark" else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            for attribute, value in ((35, tokens.topbar_background), (36, tokens.text_primary), (34, tokens.border)):
                color = ctypes.c_uint(color_ref(value))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(color), ctypes.sizeof(color))
        except (AttributeError, OSError, ValueError):
            return
