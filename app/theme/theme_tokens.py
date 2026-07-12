from __future__ import annotations

from dataclasses import dataclass


THEME_MODES = ("system", "light", "dark")


@dataclass(frozen=True)
class ThemeTokens:
    window_background: str
    topbar_background: str
    surface: str
    surface_secondary: str
    input_background: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    border: str
    border_strong: str
    hover: str
    selected: str
    primary_button_background: str
    primary_button_text: str
    primary_button_hover: str
    focus_border: str
    scrollbar_handle: str


LIGHT_TOKENS = ThemeTokens(
    window_background="#F7F7F8",
    topbar_background="#FFFFFF",
    surface="#FFFFFF",
    surface_secondary="#F7F7F8",
    input_background="#FFFFFF",
    text_primary="#202123",
    text_secondary="#6B7280",
    text_disabled="#9CA3AF",
    border="#E5E7EB",
    border_strong="#D1D5DB",
    hover="#F3F4F6",
    selected="#ECECF1",
    primary_button_background="#202123",
    primary_button_text="#FFFFFF",
    primary_button_hover="#343541",
    focus_border="#9CA3AF",
    scrollbar_handle="#C7C7C7",
)


DARK_TOKENS = ThemeTokens(
    window_background="#212121",
    topbar_background="#171717",
    surface="#2F2F2F",
    surface_secondary="#292929",
    input_background="#303030",
    text_primary="#ECECEC",
    text_secondary="#B4B4B4",
    text_disabled="#777777",
    border="#424242",
    border_strong="#565656",
    hover="#3A3A3A",
    selected="#3A3A3A",
    primary_button_background="#ECECEC",
    primary_button_text="#202123",
    primary_button_hover="#D9D9E3",
    focus_border="#8E8EA0",
    scrollbar_handle="#666666",
)


def normalize_theme_mode(value: object) -> str:
    mode = str(value or "system").strip().lower()
    return mode if mode in THEME_MODES else "system"


def tokens_for(theme: str) -> ThemeTokens:
    return DARK_TOKENS if normalize_theme_mode(theme) == "dark" else LIGHT_TOKENS
