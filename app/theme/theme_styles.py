from __future__ import annotations

from app.theme.theme_tokens import ThemeTokens


def build_theme_styles(tokens: ThemeTokens) -> str:
    """Return the neutral, application-wide part of the Qt stylesheet."""

    return f"""
/* Theme foundation. Object-specific business status styles remain local. */
QMainWindow, QDialog, QWidget#settingsDialog, QWidget#mainWindowRoot {{
    background: {tokens.window_background};
    color: {tokens.text_primary};
}}
QFrame#settingsCard, QFrame#customVoicePanel, QFrame#configManagementCard {{
    background: {tokens.surface};
    border-color: {tokens.border};
}}
QLabel {{ color: {tokens.text_primary}; }}
QLabel#settingsHint, QLabel#hintLabel, QLabel#subtleLabel, QLabel#recordDetailLabel {{
    color: {tokens.text_secondary};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox {{
    background: {tokens.input_background};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border_strong};
    border-radius: 8px;
    selection-background-color: {tokens.selected};
    selection-color: {tokens.text_primary};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QAbstractSpinBox:hover, QComboBox:hover {{
    border-color: {tokens.focus_border};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{
    border-color: {tokens.focus_border};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{
    background: {tokens.surface_secondary};
    color: {tokens.text_disabled};
    border-color: {tokens.border};
}}
QComboBox QAbstractItemView {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    selection-background-color: {tokens.selected};
    selection-color: {tokens.text_primary};
}}
QPushButton, QToolButton {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border_strong};
    border-radius: 8px;
    min-height: 32px;
    padding: 4px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background: {tokens.hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {tokens.selected}; }}
QPushButton#primaryButton {{
    background: {tokens.primary_button_background};
    border-color: {tokens.primary_button_background};
    color: {tokens.primary_button_text};
}}
QPushButton#primaryButton:hover {{
    background: {tokens.primary_button_hover};
    border-color: {tokens.primary_button_hover};
}}
QPushButton#secondaryButton {{
    background: {tokens.surface};
    border-color: {tokens.border_strong};
    color: {tokens.text_primary};
}}
QPushButton:disabled, QToolButton:disabled {{
    background: {tokens.surface_secondary};
    color: {tokens.text_disabled};
    border-color: {tokens.border};
}}
QCheckBox, QRadioButton {{
    color: {tokens.text_primary};
    spacing: 7px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {tokens.border_strong};
    background: {tokens.input_background};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {tokens.primary_button_background};
    border-color: {tokens.primary_button_background};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {tokens.surface_secondary};
    border-color: {tokens.border};
}}
QTabWidget::pane {{
    background: {tokens.window_background};
    border: none;
    border-top: 1px solid {tokens.border};
}}
QTabBar::tab {{
    color: {tokens.text_secondary};
    background: transparent;
    border-bottom: 3px solid transparent;
}}
QTabBar::tab:selected {{
    color: {tokens.text_primary};
    border-bottom-color: {tokens.text_primary};
}}
QTabBar::tab:hover {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QTableView, QTableWidget {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    gridline-color: {tokens.border};
}}
QTableView::item, QTableWidget::item {{ color: {tokens.text_primary}; }}
QTableView::item:selected, QTableWidget::item:selected {{
    background: {tokens.selected};
    color: {tokens.text_primary};
}}
QHeaderView::section {{
    background: {tokens.surface_secondary};
    color: {tokens.text_primary};
    border: none;
    border-right: 1px solid {tokens.border};
    border-bottom: 1px solid {tokens.border};
}}
QMenu, QMenu#copyContextMenu {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 8px;
}}
QMenu::item {{ padding: 7px 24px; border-radius: 5px; }}
QMenu::item:selected {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    width: 10px;
    background: {tokens.surface_secondary};
    border: none;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    min-height: 40px;
    background: {tokens.scrollbar_handle};
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{ background: {tokens.border_strong}; }}
QScrollBar:horizontal {{
    height: 10px;
    background: {tokens.surface_secondary};
    border: none;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    min-width: 40px;
    background: {tokens.scrollbar_handle};
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{ background: {tokens.border_strong}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: transparent; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 6px;
    padding: 5px 8px;
}}
QMessageBox {{ background: {tokens.surface}; color: {tokens.text_primary}; }}
"""
