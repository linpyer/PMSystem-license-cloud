from __future__ import annotations

from app.theme.theme_tokens import ThemeTokens


def build_theme_styles(tokens: ThemeTokens) -> str:
    """Return the neutral, application-wide part of the Qt stylesheet."""

    is_dark = tokens.window_background.lower() == "#212121"
    recording_background = "#3b2527" if is_dark else "#fef2f2"
    recording_border = "#8a3d45" if is_dark else "#fca5a5"
    recording_text = "#fca5a5" if is_dark else "#b91c1c"
    warning_background = "#3b3020" if is_dark else "#fffbeb"
    warning_border = "#8a6d30" if is_dark else "#fcd34d"
    warning_text = "#fbbf24" if is_dark else "#b45309"
    danger_hover = "#44272b" if is_dark else "#fef2f2"
    danger_hover_text = "#fecaca" if is_dark else "#b91c1c"

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

/* Phase 2: main window and core pages. */
QWidget {{ background: {tokens.window_background}; color: {tokens.text_primary}; }}
QGroupBox {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}
QGroupBox::title {{
    color: {tokens.text_primary};
    background: transparent;
}}
QTabBar::tab {{
    min-height: 34px;
    margin: 7px 2px;
    padding: 0 15px;
    border: none;
    border-radius: 8px;
    font-weight: 500;
}}
QTabBar {{ background: {tokens.topbar_background}; }}
QTabBar::tab:selected {{
    background: {tokens.selected};
    color: {tokens.text_primary};
    border: none;
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    background: {tokens.hover};
    color: {tokens.text_primary};
}}
QToolButton#statsButton, QToolButton#settingsButton, QToolButton#helpIconButton {{
    margin: 7px 0;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: {tokens.text_secondary};
}}
QToolButton#statsButton:hover, QToolButton#settingsButton:hover, QToolButton#helpIconButton:hover {{
    background: {tokens.hover};
    border-color: {tokens.border};
}}
QStatusBar {{
    background: {tokens.topbar_background};
    color: {tokens.text_secondary};
    border-top: 1px solid {tokens.border};
}}
QLabel#statusVersionLabel {{ color: {tokens.text_secondary}; }}

QFrame#previewContainer {{
    background: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: 10px;
}}
QWidget#rightOperationPanel, QWidget#tableActionCell, QWidget#statusCell,
QWidget#statusBadgeHost, QWidget#statusLine, QWidget#voiceTableWidget,
QWidget#transparentSettingsRow {{ background: transparent; }}
QLabel#previewLabel {{ border-color: {tokens.border_strong}; }}
QFrame#recordingStatusBlock {{
    background: {tokens.surface_secondary};
    border-color: {tokens.border};
}}
QFrame#recordingStatusBlock[state="idle"] {{ background: {tokens.surface_secondary}; border-color: {tokens.border}; }}
QFrame#recordingStatusBlock[state="idle"] QLabel {{ color: {tokens.text_secondary}; }}
QFrame#recordingStatusBlock[state="recording"] {{ background: {recording_background}; border-color: {recording_border}; }}
QFrame#recordingStatusBlock[state="recording"] QLabel {{ color: {recording_text}; }}
QFrame#recordingStatusBlock[state="warning"] {{ background: {warning_background}; border-color: {warning_border}; }}
QFrame#recordingStatusBlock[state="warning"] QLabel {{ color: {warning_text}; }}
QFrame#recordingStatusBlock[state="error"] {{ background: {recording_background}; border-color: {recording_border}; }}
QFrame#recordingStatusBlock[state="error"] QLabel {{ color: {recording_text}; }}
QLabel#recordingStatusTitle {{ color: {tokens.text_primary}; }}
QLabel#recordingStatusDetail, QLabel#cameraStatusValue {{ color: {tokens.text_secondary}; }}
QLabel#durationValue {{ color: {tokens.text_primary}; }}
QLineEdit#scanInput, QLineEdit#videoSearchInput {{
    background: {tokens.input_background};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QLineEdit#scanInput:focus, QLineEdit#videoSearchInput:focus {{ border-color: {tokens.focus_border}; }}
QFrame#recordTypeSeparator {{ background: {tokens.border}; }}
QLabel#recentCardTitle, QLabel#recordTypeTitle, QLabel#sectionTitle {{ color: {tokens.text_primary}; }}
QFrame#recentTitleAccent {{ background: {tokens.border_strong}; }}
QWidget#recentRecordingRow {{ border-bottom-color: {tokens.border}; }}
QWidget#recentRecordingRow:hover {{ background: {tokens.hover}; }}
QLabel#recentOrderText {{ color: {tokens.text_primary}; }}
QLabel#recentMetaText {{ color: {tokens.text_secondary}; }}
QPushButton#recentDeleteButton {{
    background: {tokens.surface};
    border-color: #dc626b;
    color: #ef4444;
}}
QPushButton#recentDeleteButton:hover {{ background: {danger_hover}; border-color: #f87171; color: {danger_hover_text}; }}
QRadioButton#recordTypeRadio {{ color: {tokens.text_primary}; background: transparent; }}
QRadioButton#recordTypeRadio::indicator {{
    border-color: {tokens.border_strong};
    background: {tokens.input_background};
}}
QRadioButton#recordTypeRadio::indicator:checked {{
    border-color: {tokens.primary_button_background};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.58, fx:0.5, fy:0.5,
        stop:0 {tokens.primary_button_background}, stop:0.42 {tokens.primary_button_background},
        stop:0.45 {tokens.input_background}, stop:1 {tokens.input_background});
}}

QPushButton#filterButton, QPushButton#datePickerButton {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QPushButton#filterButton:hover, QPushButton#datePickerButton:hover {{
    background: {tokens.hover};
    color: {tokens.text_primary};
    border-color: {tokens.focus_border};
}}
QPushButton#filterButton:checked {{
    background: {tokens.selected};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QToolButton#extendedFilterToggleButton {{
    background: transparent;
    border: 1px solid {tokens.border};
    color: {tokens.text_secondary};
    border-radius: 8px;
}}
QToolButton#extendedFilterToggleButton:hover {{
    background: {tokens.hover};
    border-color: {tokens.border_strong};
    color: {tokens.text_primary};
}}
QWidget#netdiskFilterRow, QWidget#videoDetailFilterRow {{ background: transparent; }}
QLabel#netdiskAutoStatusLabel, QLabel#paginationTotalLabel, QLabel#paginationEllipsis {{ color: {tokens.text_secondary}; }}
QWidget#netdiskProgressPanel {{ background: {tokens.surface}; border-color: {tokens.border}; }}
QLabel#netdiskProgressTitle {{ color: {tokens.text_primary}; }}
QLabel#netdiskProgressStats, QLabel#netdiskProgressCurrent {{ color: {tokens.text_secondary}; }}
QProgressBar#netdiskProgressBar {{ background: {tokens.border}; }}
QProgressBar#netdiskProgressBar::chunk {{ background: {tokens.primary_button_background}; }}
QComboBox#queryCompactFilterCombo, QComboBox#paginationCombo {{
    background: {tokens.input_background};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QLineEdit#paginationJumpInput {{
    background: {tokens.input_background};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QLineEdit#paginationJumpInput:focus {{ border-color: {tokens.focus_border}; }}
QPushButton#paginationButton, QPushButton#paginationPageButton {{
    background: {tokens.surface};
    border-color: {tokens.border};
    color: {tokens.text_primary};
}}
QPushButton#paginationButton:hover, QPushButton#paginationPageButton:hover {{
    background: {tokens.hover};
    border-color: {tokens.border_strong};
    color: {tokens.text_primary};
}}
QPushButton#paginationPageButton:checked {{
    background: {tokens.selected};
    border-color: {tokens.border_strong};
    color: {tokens.text_primary};
}}
QTableWidget {{
    background: {tokens.surface};
    alternate-background-color: {tokens.surface_secondary};
    border-color: {tokens.border};
    gridline-color: {tokens.border};
    color: {tokens.text_primary};
}}
QTableWidget::item:hover {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QTableWidget::item:selected, QTableWidget::item:selected:active, QTableWidget::item:selected:!active {{
    background: {tokens.selected};
    color: {tokens.text_primary};
}}
QHeaderView::section {{
    background: {tokens.surface_secondary};
    color: {tokens.text_primary};
    border-right-color: {tokens.border};
    border-bottom-color: {tokens.border};
}}
QLabel#tablePrimaryText, QLabel#statusText {{ color: {tokens.text_primary}; }}
QLabel#tableSubText, QLabel#uploadStatusText {{ color: {tokens.text_secondary}; }}
QFrame#videoTableStateBox {{ background: {tokens.surface}; border-color: {tokens.border}; }}
QLabel#videoLoadingSpinner {{ color: {tokens.text_primary}; }}
QLabel#videoTableStateIcon, QLabel#videoTableStateSubtitle {{ color: {tokens.text_secondary}; }}
QLabel#videoTableStateTitle {{ color: {tokens.text_primary}; }}
QFrame#videoSkeletonBlock {{ background: {tokens.border}; }}

QDialog#settingsDialog {{ background: {tokens.window_background}; }}
QFrame#settingsCard, QFrame#customVoicePanel, QFrame#configManagementCard, QFrame#changelogCard {{
    background: {tokens.surface};
    border-color: {tokens.border};
}}
QLabel#settingsCardTitle, QLabel#configManagementTitle, QLabel#changelogVersion {{ color: {tokens.text_primary}; }}
QLabel#configManagementHint, QLabel#changelogItem, QLabel#changelogSection {{ color: {tokens.text_secondary}; }}
QWidget#voiceModePanel, QWidget#transparentSettingsRow, QWidget#voiceTableWidget, QScrollArea#voiceTableScroll {{
    background: transparent;
}}
QCheckBox#settingsMainCheckBox, QCheckBox#settingsInlineCheckBox {{
    color: {tokens.text_primary};
    background: transparent;
}}
QCheckBox#settingsMainCheckBox::indicator, QCheckBox#settingsInlineCheckBox::indicator {{
    border-color: {tokens.border_strong};
    background: {tokens.input_background};
}}
QCheckBox#settingsMainCheckBox::indicator:checked, QCheckBox#settingsInlineCheckBox::indicator:checked {{
    background: {tokens.primary_button_background};
    border-color: {tokens.primary_button_background};
}}
QWidget#voiceModePanel QRadioButton {{ color: {tokens.text_primary}; }}
QWidget#voiceModePanel QRadioButton::indicator {{ border-color: {tokens.border_strong}; background: {tokens.input_background}; }}
QWidget#voiceModePanel QRadioButton::indicator:checked {{
    border-color: {tokens.primary_button_background};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {tokens.primary_button_background}, stop:0.42 {tokens.primary_button_background},
        stop:0.46 {tokens.input_background}, stop:1 {tokens.input_background});
}}
QFrame#voiceRecordRow {{ background: {tokens.surface}; border: none; }}
QFrame#voiceRecordRow:hover {{ background: {tokens.hover}; }}
QFrame#voiceRecordSeparator {{ background: {tokens.border}; }}
QPushButton#voiceUploadButton, QPushButton#voicePreviewButton, QPushButton#voiceResetButton {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border-color: {tokens.border_strong};
}}
QPushButton#voiceUploadButton:hover, QPushButton#voicePreviewButton:hover, QPushButton#voiceResetButton:hover {{
    background: {tokens.hover};
    color: {tokens.text_primary};
}}
QLabel#authStatusLabel {{ color: {tokens.text_secondary}; font-weight: 700; }}
QLabel#authStatusLabel[status="ok"] {{ color: #22c55e; }}
QLabel#authStatusLabel[status="none"] {{ color: {tokens.text_secondary}; }}
QLabel#authStatusTag {{ background: {tokens.surface_secondary}; border-color: {tokens.border}; color: {tokens.text_secondary}; }}
QLabel#authStatusTag[status="ok"] {{ background: {"#173824" if is_dark else "#f0fdf4"}; border-color: {"#2d6a42" if is_dark else "#bbf7d0"}; color: {"#86efac" if is_dark else "#047857"}; }}
"""
