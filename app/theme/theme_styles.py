from __future__ import annotations

from app.theme.theme_tokens import ThemeTokens
from app.utils.runtime_paths import resource_path


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
    checkmark_path = resource_path("app/assets/checkmark-dark.svg" if is_dark else "app/assets/checkmark.svg").as_posix()

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
QComboBox {{ padding-right: 30px; }}
QComboBox:hover, QComboBox:focus, QComboBox:on {{
    background: {tokens.input_background};
    color: {tokens.text_primary};
    border-color: {tokens.focus_border};
}}
QComboBox::drop-down {{
    border: none;
    border-left: 1px solid {tokens.border};
    width: 26px;
    background: {tokens.input_background};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
QComboBox::drop-down:hover, QComboBox::drop-down:on {{ background: {tokens.surface_secondary}; }}
QComboBox:disabled::drop-down {{ background: {tokens.surface_secondary}; border-left-color: {tokens.border}; }}
QComboBox::down-arrow {{ width: 10px; height: 10px; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 4px 8px; }}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{ background: {tokens.selected}; color: {tokens.text_primary}; }}
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
QPushButton[buttonRole="primary"] {{
    background: {tokens.primary_button_background};
    border-color: {tokens.primary_button_background};
    color: {tokens.primary_button_text};
}}
QPushButton[buttonRole="primary"]:hover {{
    background: {tokens.primary_button_hover};
    border-color: {tokens.primary_button_hover};
}}
QPushButton#secondaryButton {{
    background: {tokens.surface};
    border-color: {tokens.border_strong};
    color: {tokens.text_primary};
}}
QPushButton[buttonRole="danger"]:enabled {{
    background: {"#5b3035" if is_dark else "#fef2f2"};
    border-color: {"#9f4048" if is_dark else "#fca5a5"};
    color: {"#fecaca" if is_dark else "#b91c1c"};
}}
QPushButton[buttonRole="danger"]:enabled:hover {{
    background: {"#6f363d" if is_dark else "#fee2e2"};
}}
QPushButton:disabled, QToolButton:disabled {{
    background: {tokens.surface_secondary};
    color: {tokens.text_disabled};
    border-color: {tokens.border};
}}
QPushButton#primaryButton:disabled, QPushButton[buttonRole="primary"]:disabled, QPushButton#secondaryButton:disabled,
QPushButton#stopButton:disabled, QPushButton[buttonRole="danger"]:disabled {{
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
    width: 18px;
    height: 18px;
    border: 1px solid {tokens.border_strong};
    background: {tokens.input_background};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked {{
    background: {tokens.primary_button_background};
    border-color: {tokens.primary_button_background};
    image: url("{checkmark_path}");
}}
QRadioButton::indicator:checked {{
    border: 2px solid {tokens.primary_button_background};
    border-radius: 9px;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {tokens.primary_button_background}, stop:0.36 {tokens.primary_button_background},
        stop:0.42 {tokens.input_background}, stop:1 {tokens.input_background});
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {tokens.text_disabled}; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {tokens.surface_secondary};
    border-color: {tokens.border};
}}
QCheckBox::indicator:checked:disabled {{
    background: {tokens.border_strong};
    border-color: {tokens.border_strong};
    image: url("{checkmark_path}");
}}
QRadioButton::indicator:checked:disabled {{
    border: 2px solid {tokens.border};
    border-radius: 9px;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {tokens.border_strong}, stop:0.36 {tokens.border_strong},
        stop:0.42 {tokens.surface_secondary}, stop:1 {tokens.surface_secondary});
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
QScrollBar::corner {{ background: {tokens.window_background}; border: none; }}
QToolTip {{
    background: {tokens.surface};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 6px;
    padding: 5px 8px;
}}
QMessageBox {{ background: {tokens.surface}; color: {tokens.text_primary}; }}

/* Phase 3: shared auxiliary dialogs, popups and generated controls. */
QDialog {{ background: {tokens.window_background}; color: {tokens.text_primary}; }}
QDialog QLabel {{ background: transparent; color: {tokens.text_primary}; }}
QMessageBox QLabel {{ color: {tokens.text_primary}; }}
QMessageBox QPushButton {{ min-width: 76px; }}
QMessageBox QPushButton#dangerButton {{ background: {"#5b3035" if is_dark else "#fef2f2"}; color: {"#fecaca" if is_dark else "#b91c1c"}; border-color: {"#9f4048" if is_dark else "#fca5a5"}; }}
QMessageBox QPushButton#dangerButton:hover {{ background: {"#6f363d" if is_dark else "#fee2e2"}; }}
QDialog#confirmActionDialog {{ background: transparent; }}
QFrame#confirmDialogSurface {{
    background: {tokens.surface}; border: 1px solid {tokens.border_strong}; border-radius: 12px;
}}
QWidget#confirmDialogHeader, QWidget#confirmDialogFooter, QWidget#confirmDialogContent,
QScrollArea#confirmDialogScrollArea, QScrollArea#confirmDialogScrollArea::viewport {{
    background: transparent; border: none;
}}
QWidget#confirmDialogHeader {{ border-bottom: 1px solid {tokens.border}; }}
QWidget#confirmDialogFooter {{ border-top: 1px solid {tokens.border}; }}
QLabel#confirmDialogTitle, QLabel#confirmDialogHeading {{ color: {tokens.text_primary}; font-weight: 700; }}
QLabel#confirmDialogTitle {{ font-size: 15px; }}
QLabel#confirmDialogHeading {{ font-size: 16px; }}
QLabel#confirmDialogDescription, QLabel#confirmDialogSectionItem {{ color: {tokens.text_secondary}; }}
QLabel#confirmDialogSectionTitle {{ color: {tokens.text_primary}; font-weight: 700; margin-top: 4px; }}
QFrame#confirmDialogInfo {{ background: {tokens.surface_secondary}; border: 1px solid {tokens.border}; border-radius: 8px; }}
QLabel#confirmDialogInfoLabel {{ color: {tokens.text_secondary}; }}
QLabel#confirmDialogInfoValue {{ color: {tokens.text_primary}; font-weight: 600; }}
QToolButton#confirmDialogCloseButton {{
    background: transparent; color: {tokens.text_secondary}; border: none; border-radius: 7px;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0;
}}
QToolButton#confirmDialogCloseButton:hover {{ background: {danger_hover}; color: {danger_hover_text}; }}
QPushButton#confirmDialogCancelButton, QPushButton#confirmDialogConfirmButton {{ min-width: 92px; min-height: 36px; }}
QCalendarWidget {{ background: {tokens.surface}; color: {tokens.text_primary}; border: 1px solid {tokens.border}; border-radius: 8px; }}
QCalendarWidget QWidget {{ background: {tokens.surface}; color: {tokens.text_primary}; }}
QCalendarWidget QToolButton {{ background: transparent; color: {tokens.text_primary}; border: none; min-height: 28px; padding: 2px 6px; }}
QCalendarWidget QToolButton:hover {{ background: {tokens.hover}; border-radius: 6px; }}
QCalendarWidget QMenu {{ background: {tokens.surface}; color: {tokens.text_primary}; }}
QCalendarWidget QSpinBox {{ background: {tokens.input_background}; color: {tokens.text_primary}; border-color: {tokens.border}; }}
QCalendarWidget QAbstractItemView {{ background: {tokens.surface}; color: {tokens.text_primary}; selection-background-color: {tokens.selected}; selection-color: {tokens.text_primary}; }}
QCalendarWidget QAbstractItemView:enabled {{ color: {tokens.text_primary}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {tokens.text_disabled}; }}
QCalendarWidget QTableView {{ background: {tokens.surface}; color: {tokens.text_primary}; selection-background-color: {tokens.selected}; selection-color: {tokens.text_primary}; }}
QCalendarWidget QHeaderView::section {{ background: {tokens.surface_secondary}; color: {tokens.text_secondary}; border-color: {tokens.border}; }}

/* Phase 2: main window and core pages.
   Keep generic containers transparent. Surfaces are opt-in through an objectName
   or a semantic role so layouts do not turn into nested cards. */
QWidget {{ color: {tokens.text_primary}; }}
QGroupBox {{
    background: transparent;
    color: {tokens.text_primary};
    border: none;
    margin: 0;
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
QToolButton#windowMinButton, QToolButton#windowMaxButton, QToolButton#windowCloseButton {{
    margin: 7px 0;
    min-width: 34px; max-width: 34px;
    min-height: 34px; max-height: 34px;
    padding: 0;
    background: transparent;
    color: {tokens.text_secondary};
    border: 1px solid transparent;
    border-radius: 8px;
    font-size: 14px;
}}
QToolButton#windowMinButton:hover, QToolButton#windowMaxButton:hover {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QToolButton#windowCloseButton:hover {{ background: {"#5b3035" if is_dark else "#fef2f2"}; color: {"#fecaca" if is_dark else "#b91c1c"}; border-color: {"#9f4048" if is_dark else "#fca5a5"}; }}
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
QToolButton#clearInputButton {{
    min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px;
    margin: 0;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 6px;
}}
QToolButton#clearInputButton:hover {{ background: {tokens.hover}; border: none; }}
QToolButton#clearInputButton:pressed {{ background: {tokens.selected}; border: none; }}
QToolButton#clearInputButton:disabled {{ background: transparent; border: none; }}
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
QWidget#settingsBasicTab, QScrollArea#settingsBasicScrollArea,
QScrollArea#settingsBasicScrollArea::viewport, QWidget#settingsBasicScrollContent,
QWidget#settingsBasicActionBar, QWidget#settingsVoiceTab,
QScrollArea#settingsVoiceScrollArea, QScrollArea#settingsVoiceScrollArea::viewport,
QWidget#settingsVoiceScrollContent {{
    background: {tokens.window_background};
    border: none;
}}
QWidget#settingsBasicActionBar, QWidget#settingsVoiceActionBar, QWidget#settingsNetdiskActionBar {{
    background: {tokens.window_background};
    border: none;
    border-top: 1px solid {tokens.border};
    min-height: 60px;
    padding: 0;
    margin: 0;
}}
QFrame#settingsCard, QFrame#customVoicePanel, QFrame#configManagementCard, QFrame#changelogCard {{
    background: {tokens.surface};
    border-color: {tokens.border};
}}
QLabel#settingsCardTitle, QLabel#configManagementTitle, QLabel#changelogVersion {{ color: {tokens.text_primary}; }}
QLabel#configManagementHint, QLabel#changelogItem, QLabel#changelogSection {{ color: {tokens.text_secondary}; }}
QWidget#voiceModePanel, QWidget#transparentSettingsRow, QWidget#voiceTableWidget {{
    background: transparent;
}}
QWidget#voiceRecordActions {{ background: transparent; border: none; }}
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
    image: url("{checkmark_path}");
}}
QWidget#voiceModePanel QRadioButton {{ color: {tokens.text_primary}; }}
QWidget#voiceModePanel QRadioButton::indicator {{ border-color: {tokens.border_strong}; background: {tokens.input_background}; }}
QWidget#voiceModePanel QRadioButton::indicator:checked {{
    border: 2px solid {tokens.primary_button_background};
    border-radius: 9px;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {tokens.primary_button_background}, stop:0.36 {tokens.primary_button_background},
        stop:0.42 {tokens.input_background}, stop:1 {tokens.input_background});
}}
QFrame#voiceRecordRow {{ background: transparent; border: none; }}
QFrame#voiceRecordRow:hover {{ background: {tokens.hover}; }}
QFrame#voiceRecordSeparator {{ background: {tokens.border}; }}
QToolButton#voiceUploadIconButton, QToolButton#voicePreviewIconButton, QToolButton#voiceResetIconButton {{
    background: transparent;
    color: {tokens.text_secondary};
    border: none;
    border-radius: 6px;
    padding: 0;
}}
QToolButton#voiceUploadIconButton:hover, QToolButton#voicePreviewIconButton:hover, QToolButton#voiceResetIconButton:hover {{
    background: {tokens.hover};
    color: {tokens.text_primary};
}}
QToolButton#voiceUploadIconButton:pressed, QToolButton#voicePreviewIconButton:pressed, QToolButton#voiceResetIconButton:pressed {{ background: {tokens.selected}; }}
QToolButton#voiceUploadIconButton:disabled, QToolButton#voicePreviewIconButton:disabled, QToolButton#voiceResetIconButton:disabled {{ color: {tokens.text_disabled}; background: transparent; }}
QLabel#authStatusLabel {{ color: {tokens.text_secondary}; font-weight: 700; }}
QLabel#settingsCurrentVersion {{ color: {tokens.text_secondary}; font-weight: 600; }}
QLabel#authStatusLabel[status="ok"] {{ color: #22c55e; }}
QLabel#authStatusLabel[status="none"] {{ color: {tokens.text_secondary}; }}
QLabel#authStatusTag {{ background: {tokens.surface_secondary}; border-color: {tokens.border}; color: {tokens.text_secondary}; }}
QLabel#authStatusTag[status="ok"] {{ background: {"#173824" if is_dark else "#f0fdf4"}; border-color: {"#2d6a42" if is_dark else "#bbf7d0"}; color: {"#86efac" if is_dark else "#047857"}; }}
QToolButton#netdiskAuthIconButton, QToolButton#netdiskTestIconButton {{
    background: transparent; border: none; border-radius: 6px; padding: 0;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
}}
QToolButton#netdiskAuthIconButton:hover, QToolButton#netdiskTestIconButton:hover {{ background: {tokens.hover}; }}
QToolButton#netdiskAuthIconButton:pressed, QToolButton#netdiskTestIconButton:pressed {{ background: {tokens.selected}; }}
QToolButton#netdiskAuthIconButton:disabled, QToolButton#netdiskTestIconButton:disabled {{ background: transparent; color: {tokens.text_disabled}; }}

/* Detail, history and drilldown dialogs. */
QDialog#importantMarkDialog, QDialog#recordDetailDialog, QDialog#duplicateRecordsDialog,
QDialog#netdiskHistoryDialog, QDialog#statsDetailDialog, QDialog#packagingStatsDialog,
QDialog#helpDialog {{ background: {tokens.window_background}; }}
QScrollArea#recordDetailScrollArea, QScrollArea#recordDetailScrollArea::viewport,
QScrollArea#recordDetailScrollArea > QWidget > QWidget, QWidget#recordDetailContent {{
    background: {tokens.window_background};
    border: none;
}}
QFrame#recordDetailCard, QFrame#statsPanelCard, QFrame#statsMetricCard {{
    background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 12px;
}}
QFrame#recordDetailCard:hover, QFrame#statsMetricCard:hover {{ border-color: {tokens.border_strong}; }}
QLabel#detailOrderTitle {{ color: {tokens.text_primary}; font-size: 22px; font-weight: 700; }}
QLabel#detailCardTitle, QLabel#statsDialogTitle {{ color: {tokens.text_primary}; font-size: 16px; font-weight: 700; }}
QLabel#dialogTitle {{ color: {tokens.text_primary}; font-weight: 700; }}
QLabel#detailValue, QLabel#detailHashValue, QLabel#statsDialogSubtitle, QLabel#dialogSubtleLabel {{ color: {tokens.text_secondary}; }}
QLineEdit#detailPathInput, QLineEdit#detailCustomReasonInput, QTextEdit#detailRemarkEdit {{
    background: {tokens.input_background}; color: {tokens.text_primary}; border-color: {tokens.border_strong};
}}
QLineEdit#detailPathInput:read-only {{ background: {tokens.surface_secondary}; color: {tokens.text_primary}; }}
QTextEdit#detailRemarkEdit {{ padding: 7px 9px; }}
QCheckBox#detailImportantCheckbox {{ background: transparent; color: {tokens.text_primary}; }}
QCheckBox#detailImportantCheckbox::indicator, QCheckBox#duplicateRowCheckbox::indicator {{ background: {tokens.input_background}; border-color: {tokens.border_strong}; }}
QCheckBox#detailImportantCheckbox::indicator:checked, QCheckBox#duplicateRowCheckbox::indicator:checked {{ background: {tokens.primary_button_background}; border-color: {tokens.primary_button_background}; image: url("{checkmark_path}"); }}
QComboBox#detailRecordTypeCombo, QComboBox#detailImportantReasonCombo {{
    background: {tokens.input_background}; color: {tokens.text_primary}; border-color: {tokens.border_strong};
}}
QLabel#detailStatusBadge {{ background: {tokens.surface}; border-radius: 10px; padding: 2px 10px; font-weight: 700; }}
QLabel#detailStatusBadge[tone="success"] {{ color: {"#86efac" if is_dark else "#047857"}; border: 1px solid {"#2d6a42" if is_dark else "#86efac"}; }}
QLabel#detailStatusBadge[tone="warning"] {{ color: {"#fde68a" if is_dark else "#b45309"}; border: 1px solid {"#8a6d30" if is_dark else "#fcd34d"}; }}
QLabel#detailStatusBadge[tone="error"] {{ color: {"#fecaca" if is_dark else "#b91c1c"}; border: 1px solid {"#9f4048" if is_dark else "#fca5a5"}; }}
QLabel#detailHashVerify[state="success"] {{ color: {"#86efac" if is_dark else "#047857"}; font-weight: 700; }}
QLabel#detailHashVerify[state="error"] {{ color: {"#fecaca" if is_dark else "#b91c1c"}; font-weight: 700; }}
QLabel#detailHashVerify[state="neutral"], QLabel#detailHashStatus {{ color: {tokens.text_secondary}; }}
QLabel#duplicateDialogTitle, QLabel#historyDialogTitle {{ color: {tokens.text_primary}; font-size: 20px; font-weight: 700; }}
QLabel#duplicateDialogSubtitle, QLabel#duplicateSelectedLabel, QLabel#historyDialogHint {{ color: {tokens.text_secondary}; }}
QCheckBox#duplicateRowCheckbox {{ background: transparent; padding: 0; margin: 0; }}
QCheckBox#duplicateRowCheckbox::indicator {{ background: {tokens.input_background}; border-color: {tokens.border_strong}; }}
QCheckBox#duplicateRowCheckbox::indicator:checked {{ background: {tokens.primary_button_background}; border-color: {tokens.primary_button_background}; image: url("{checkmark_path}"); }}
QWidget#netdiskProgressPanel {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 10px; }}
QProgressBar#netdiskProgressBar {{ background: {tokens.surface_secondary}; border: 1px solid {tokens.border}; border-radius: 5px; }}
QProgressBar#netdiskProgressBar::chunk {{ background: {tokens.primary_button_background}; border-radius: 4px; }}

/* Statistics cards and read-only drilldown. Business colours stay small and semantic. */
QFrame#statsMetricCard[metricRole="ship"] {{ background: {"#203429" if is_dark else "#f0fdf4"}; border-color: {"#356344" if is_dark else "#bbf7d0"}; }}
QFrame#statsMetricCard[metricRole="return"] {{ background: {"#3a301f" if is_dark else "#fffbeb"}; border-color: {"#80652b" if is_dark else "#fde68a"}; }}
QFrame#statsMetricCard[metricRole="important"] {{ background: {"#3b2527" if is_dark else "#fef2f2"}; border-color: {"#81424a" if is_dark else "#fecaca"}; }}
QLabel#statsCardTitle, QLabel#statsCardHint, QLabel#statsCardDrillHint {{ color: {tokens.text_secondary}; background: transparent; }}
QLabel#statsCardValue[metricRole="ship"] {{ color: {"#86efac" if is_dark else "#16a34a"}; }}
QLabel#statsCardValue[metricRole="return"] {{ color: {"#fde68a" if is_dark else "#d97706"}; }}
QLabel#statsCardValue[metricRole="important"] {{ color: {"#fecaca" if is_dark else "#dc2626"}; }}
QLabel#statsCardValue[diffState="positive"] {{ color: {"#86efac" if is_dark else "#16a34a"}; }}
QLabel#statsCardValue[diffState="negative"] {{ color: {"#fecaca" if is_dark else "#dc2626"}; }}
QLabel#statsCardValue[diffState="neutral"] {{ color: {tokens.text_secondary}; }}
QScrollArea#statsTabScrollArea, QScrollArea#statsTabScrollArea::viewport {{ background: {tokens.window_background}; }}
QScrollArea#statsTabScrollArea > QWidget > QWidget, QWidget#statsTabContent {{ background: {tokens.window_background}; }}
QFrame#statsChartCard, QFrame#statsReasonCard, QFrame#statsCompareCard {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 12px; }}
QFrame#statsOverviewSection {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 12px; }}
QPushButton#statsQuickButton, QPushButton#statsSegmentButton {{ background: {tokens.surface}; color: {tokens.text_primary}; border-color: {tokens.border_strong}; }}
QPushButton#statsQuickButton:hover, QPushButton#statsSegmentButton:hover {{ background: {tokens.hover}; }}
QPushButton#statsQuickButton:checked, QPushButton#statsSegmentButton:checked {{ background: {tokens.selected}; border-color: {tokens.border_strong}; color: {tokens.text_primary}; }}
QLabel#statsSummaryLabel {{ color: {tokens.text_secondary}; }}

/* Help, menus and common state containers. */
QDialog#helpDialog {{ background: {tokens.window_background}; }}
QWidget#helpNavigation {{ background: transparent; border: none; }}
QStackedWidget#helpPages {{ background: transparent; border: none; }}
QTabBar#helpTabBar {{ background: transparent; }}
QTabBar#helpTabBar::tab {{
    background: transparent; color: {tokens.text_secondary}; border: none; border-radius: 8px;
    min-height: 32px; padding: 4px 12px; margin-right: 4px;
}}
QTabBar#helpTabBar::tab:hover:!selected {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QTabBar#helpTabBar::tab:selected {{ background: {tokens.selected}; color: {tokens.text_primary}; font-weight: 600; }}
QTabWidget#helpTabs {{ background: transparent; border: none; }}
QTabWidget#helpTabs::pane {{ background: transparent; border: none; margin-top: 8px; }}
QTabWidget#helpTabs QTabBar {{ background: transparent; }}
QTabWidget#helpTabs QTabBar::tab {{
    background: transparent; color: {tokens.text_secondary}; border: none; border-radius: 8px;
    min-height: 32px; padding: 4px 12px; margin-right: 4px;
}}
QTabWidget#helpTabs QTabBar::tab:hover:!selected {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QTabWidget#helpTabs QTabBar::tab:selected {{ background: {tokens.selected}; color: {tokens.text_primary}; font-weight: 600; }}
QTextBrowser#helpContent {{ background: {tokens.surface}; color: {tokens.text_primary}; border: 1px solid {tokens.border}; border-radius: 12px; padding: 14px; }}
QToolButton#helpPrevButton, QToolButton#helpNextButton {{ background: transparent; color: {tokens.text_primary}; border: none; border-radius: 8px; padding: 0; }}
QToolButton#helpPrevButton:hover, QToolButton#helpNextButton:hover {{ background: {tokens.hover}; }}
QToolButton#helpPrevButton:pressed, QToolButton#helpNextButton:pressed {{ background: {tokens.selected}; }}
QToolButton#helpPrevButton:disabled, QToolButton#helpNextButton:disabled {{ background: transparent; color: {tokens.text_disabled}; }}
QFrame#emptyStateContainer, QFrame#errorStateContainer, QFrame#loadingStateContainer {{ background: transparent; }}
QLabel#emptyStateTitle, QLabel#errorStateTitle {{ color: {tokens.text_secondary}; }}
QLabel#emptyStateHint, QLabel#errorStateHint {{ color: {tokens.text_disabled}; }}

/* Phase 5A: main-window and core-page visual reconstruction. */
QWidget#mainWindowRoot {{ background: {tokens.window_background}; }}
QTabWidget#mainNavigation {{ background: {tokens.window_background}; }}
QTabWidget#mainNavigation::pane {{
    background: {tokens.window_background};
    border: none;
    border-top: 1px solid {tokens.border};
}}
QTabWidget#mainNavigation QTabBar {{ background: {tokens.topbar_background}; }}
QTabWidget#mainNavigation QTabBar::tab {{
    background: transparent;
    color: {tokens.text_secondary};
    min-width: 0;
    min-height: 34px;
    margin: 8px 3px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    font-weight: 500;
}}
QTabWidget#mainNavigation QTabBar::tab:selected {{
    background: {tokens.selected};
    color: {tokens.text_primary};
    border: none;
    font-weight: 700;
}}
QTabWidget#mainNavigation QTabBar::tab:hover:!selected {{
    background: {tokens.hover};
    color: {tokens.text_primary};
}}
QWidget#navigationActions {{ background: {tokens.topbar_background}; }}

QWidget#monitorPage, QWidget#videoQueryPage {{ background: {tokens.window_background}; }}
QFrame#previewContainer {{
    background: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}
QLabel#previewLabel {{ border: 1px solid {tokens.border_strong}; border-radius: 10px; }}
QWidget#rightOperationPanel {{
    background: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}
QGroupBox#plainRightCard, QGroupBox#recentCard {{
    background: transparent;
    border: none;
    margin: 0;
    padding: 0;
}}
QGroupBox#plainRightCard::title, QGroupBox#recentCard::title {{ background: transparent; padding: 0; }}
QFrame#recordingStatusBlock {{
    background: {tokens.surface_secondary};
    border: 1px solid transparent;
    border-radius: 10px;
}}
QFrame#recordingStatusBlock[state="idle"] {{ background: {tokens.surface_secondary}; border-color: transparent; }}
QFrame#recordingStatusBlock[state="recording"] {{ background: {recording_background}; border-color: {recording_border}; }}
QFrame#recordingStatusBlock[state="warning"] {{ background: {warning_background}; border-color: {warning_border}; }}
QFrame#recordingStatusBlock[state="error"] {{ background: {recording_background}; border-color: {recording_border}; }}
QLabel#recordingStatusTitle {{ color: {tokens.text_primary}; font-size: 12pt; font-weight: 700; }}
QLabel#recordingStatusDetail, QLabel#cameraStatusValue {{ color: {tokens.text_secondary}; }}
QLabel#durationValue {{ color: {tokens.text_primary}; font-size: 11pt; font-weight: 700; }}
QLabel#recBadge {{ background: #dc2626; color: #ffffff; border-radius: 6px; padding: 3px 7px; }}
QLabel#recordTypeTitle, QLabel#sectionTitle, QLabel#recentCardTitle {{ color: {tokens.text_primary}; font-weight: 700; }}
QFrame#recordTypeSeparator {{ background: {tokens.border}; max-height: 1px; }}
QRadioButton#recordTypeRadio {{ background: transparent; color: {tokens.text_primary}; }}
QRadioButton#recordTypeRadio[recordType="ship"]:checked {{ color: {"#86efac" if is_dark else "#047857"}; }}
QRadioButton#recordTypeRadio[recordType="return"]:checked {{ color: {"#fde68a" if is_dark else "#c2410c"}; }}
QRadioButton#recordTypeRadio[recordType="ship"]::indicator:checked {{
    border: 2px solid {"#4b9b61" if is_dark else "#16a34a"};
    border-radius: 9px;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {"#4b9b61" if is_dark else "#16a34a"}, stop:0.36 {"#4b9b61" if is_dark else "#16a34a"},
        stop:0.42 {tokens.input_background}, stop:1 {tokens.input_background});
}}
QRadioButton#recordTypeRadio[recordType="return"]::indicator:checked {{
    border: 2px solid {"#c79435" if is_dark else "#d97706"};
    border-radius: 9px;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {"#c79435" if is_dark else "#d97706"}, stop:0.36 {"#c79435" if is_dark else "#d97706"},
        stop:0.42 {tokens.input_background}, stop:1 {tokens.input_background});
}}
QLineEdit#scanInput {{ min-height: 38px; padding: 5px 10px; border-radius: 8px; }}
QPushButton#stopButton {{
    background: {"#5b3035" if is_dark else "#fef2f2"};
    color: {"#fecaca" if is_dark else "#b91c1c"};
    border: 1px solid {"#9f4048" if is_dark else "#fca5a5"};
}}
QPushButton#stopButton:hover {{ background: {"#6f363d" if is_dark else "#fee2e2"}; }}
QFrame#monitorPanelDivider {{ background: {tokens.border}; border: none; max-height: 1px; min-height: 1px; }}
QWidget#recentRecordingRow {{ background: transparent; border: none; border-bottom: 1px solid {tokens.border}; }}
QWidget#recentRecordingRow:hover {{ background: {tokens.hover}; }}
QLabel#recentCardTitle, QLabel#recentOrderText, QLabel#recentEmptyText {{ margin-left: 0; padding-left: 0; }}
QLabel#recentOrderText {{ color: {tokens.text_primary}; }}
QLabel#recentEmptyText {{ color: {tokens.text_secondary}; }}
QLabel#recentMetaText {{ color: {tokens.text_secondary}; }}
QLabel#recentTypeTag {{ border-radius: 6px; padding: 1px 6px; font-size: 9pt; font-weight: 600; }}
QLabel#recentTypeTag[recordType="ship"] {{ background: {"#203429" if is_dark else "#f0fdf4"}; border: 1px solid {"#356344" if is_dark else "#bbf7d0"}; color: {"#86efac" if is_dark else "#047857"}; }}
QLabel#recentTypeTag[recordType="return"] {{ background: {"#3a301f" if is_dark else "#fff7ed"}; border: 1px solid {"#80652b" if is_dark else "#fed7aa"}; color: {"#fde68a" if is_dark else "#c2410c"}; }}
QToolButton#recentDeleteIconButton {{
    background: transparent; border: none; border-radius: 6px;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0;
}}
QToolButton#recentDeleteIconButton:hover {{ background: {"#44272b" if is_dark else "#fef2f2"}; }}
QToolButton#recentDeleteIconButton:pressed {{ background: {"#5b3035" if is_dark else "#fee2e2"}; }}
QWidget#todayTopSection, QWidget#todayBottomSection, QWidget#todaySecondaryMetric {{
    background: transparent;
    border: none;
}}
QFrame#todayRecordSummaryCard {{
    background: {tokens.surface_secondary};
    border: 1px solid {tokens.border};
    border-radius: 11px;
}}
QLabel#todaySummaryTitle {{
    color: {tokens.text_primary};
}}
QLabel#todayShippingValue {{
    color: {"#86c995" if is_dark else "#15803d"};
}}
QLabel#todaySummaryUnit {{
    color: {tokens.text_secondary};
}}
QFrame#todaySummaryDivider {{
    background: {tokens.border};
    border: none;
    min-height: 1px;
    max-height: 1px;
}}
QLabel#todaySecondaryTitle {{ color: {tokens.text_secondary}; }}
QLabel#todayReturnValue {{ color: {"#d6ad62" if is_dark else "#c2410c"}; }}
QLabel#todayTotalValue {{ color: {tokens.text_primary}; }}

QWidget#videoQueryPage QLineEdit#videoSearchInput {{ min-height: 38px; padding: 5px 10px; }}
QWidget#videoQueryPage QWidget#querySegmentControl {{
    background: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: 8px;
}}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton {{
    min-height: 32px;
    margin: 0;
    padding: 3px 12px;
    background: transparent;
    border: none;
    border-right: 1px solid {tokens.border};
    border-radius: 0;
}}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton[segmentPosition="first"] {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton[segmentPosition="last"] {{ border-right: none; border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton:hover {{ background: {tokens.hover}; border-color: {tokens.border}; }}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton:checked {{ background: {tokens.selected}; color: {tokens.text_primary}; border-color: {tokens.border}; font-weight: 700; }}
QWidget#videoQueryPage QPushButton#filterButton, QWidget#videoQueryPage QPushButton#datePickerButton {{
    min-height: 34px; border-radius: 8px; padding: 4px 12px; background: {tokens.surface}; color: {tokens.text_primary}; border-color: {tokens.border};
}}
QWidget#videoQueryPage QPushButton#filterButton:hover, QWidget#videoQueryPage QPushButton#datePickerButton:hover {{ background: {tokens.hover}; border-color: {tokens.border_strong}; }}
QWidget#videoQueryPage QPushButton#filterButton:checked {{ background: {tokens.selected}; color: {tokens.text_primary}; border-color: transparent; font-weight: 700; }}
QWidget#videoQueryPage QToolButton#extendedFilterToggleButton {{ background: transparent; border-color: transparent; color: {tokens.text_secondary}; }}
QWidget#videoQueryPage QToolButton#extendedFilterToggleButton:hover {{ background: {tokens.hover}; border-color: {tokens.border}; color: {tokens.text_primary}; }}
QWidget#videoQueryPage QWidget#netdiskFilterRow, QWidget#videoQueryPage QWidget#videoDetailFilterRow {{ background: transparent; }}
QFrame#videoTableContainer {{
    background: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: 10px;
}}
QWidget#videoQueryPage QTableWidget#videoQueryTable {{
    background: transparent;
    alternate-background-color: {tokens.surface};
    border: none;
    border-radius: 0;
    gridline-color: transparent;
    selection-background-color: {tokens.selected};
    selection-color: {tokens.text_primary};
}}
QWidget#videoQueryPage QTableWidget#videoQueryTable::item {{
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {tokens.border};
    color: {tokens.text_primary};
}}
QWidget#videoQueryPage QTableWidget#videoQueryTable::item:hover {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QWidget#videoQueryPage QTableWidget#videoQueryTable::item:selected {{ background: {tokens.selected}; color: {tokens.text_primary}; }}
QWidget#videoQueryPage QTableWidget#videoQueryTable QWidget {{ background: transparent; border: none; }}
QWidget#videoQueryPage QTableWidget#videoQueryTable QHeaderView::section {{
    background: {tokens.surface_secondary};
    color: {tokens.text_secondary};
    border: none;
    border-bottom: 1px solid {tokens.border};
    padding: 9px 8px;
    font-weight: 700;
}}
QWidget#videoQueryPage QLabel#tablePrimaryText {{ color: {tokens.text_primary}; background: transparent; }}
QWidget#videoQueryPage QLabel#tableSubText {{ color: {tokens.text_secondary}; background: transparent; }}
QWidget#videoQueryPage QLabel#tableSubText[state="warning"] {{ color: {"#fecaca" if is_dark else "#dc2626"}; }}
QWidget#videoQueryPage QLabel#recordTypeTag {{ border-radius: 6px; padding: 1px 6px; min-height: 18px; font-weight: 600; }}
QWidget#videoQueryPage QLabel#recordTypeTag[recordType="ship"] {{ background: {"#203429" if is_dark else "#f0fdf4"}; border: 1px solid {"#356344" if is_dark else "#bbf7d0"}; color: {"#86efac" if is_dark else "#047857"}; }}
QWidget#videoQueryPage QLabel#recordTypeTag[recordType="return"] {{ background: {"#3a301f" if is_dark else "#fff7ed"}; border: 1px solid {"#80652b" if is_dark else "#fed7aa"}; color: {"#fde68a" if is_dark else "#c2410c"}; }}
QWidget#videoQueryPage QLabel#statusText[statusState="normal"] {{ color: {tokens.text_secondary}; }}
QWidget#videoQueryPage QLabel#statusText[statusState="error"], QWidget#videoQueryPage QLabel#uploadStatusText[uploadState="failed"] {{ color: {"#fecaca" if is_dark else "#b91c1c"}; }}
QWidget#videoQueryPage QLabel#uploadStatusText[uploadState="done"] {{ color: {"#86efac" if is_dark else "#047857"}; }}
QWidget#videoQueryPage QLabel#uploadStatusText[uploadState="pending"] {{ color: {"#fde68a" if is_dark else "#b45309"}; }}
QWidget#videoQueryPage QLabel#uploadStatusText[uploadState="uploading"] {{ color: {"#bfdbfe" if is_dark else "#2563eb"}; }}
QWidget#videoQueryPage QToolButton#sceneOpenIconButton, QWidget#videoQueryPage QToolButton#sceneRevealIconButton {{
    background: transparent; border: none; border-radius: 6px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0;
}}
QWidget#videoQueryPage QToolButton#sceneOpenIconButton:hover, QWidget#videoQueryPage QToolButton#sceneRevealIconButton:hover {{ background: {tokens.hover}; }}
QWidget#videoQueryPage QToolButton#sceneOpenIconButton:pressed, QWidget#videoQueryPage QToolButton#sceneRevealIconButton:pressed {{ background: {tokens.selected}; }}
QWidget#videoQueryPage QToolButton#tableUploadIconButton, QWidget#videoQueryPage QToolButton#tableDangerIconButton {{
    background: transparent; border: none; border-radius: 6px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0;
}}
QWidget#videoQueryPage QToolButton#tableUploadIconButton:hover {{ background: {tokens.hover}; }}
QWidget#videoQueryPage QToolButton#tableUploadIconButton:pressed {{ background: {tokens.selected}; }}
QWidget#videoQueryPage QToolButton#tableDangerIconButton:hover {{ background: {"#44272b" if is_dark else "#fef2f2"}; }}
QWidget#videoQueryPage QToolButton#tableDangerIconButton:pressed {{ background: {"#5b3035" if is_dark else "#fee2e2"}; }}
QWidget#videoQueryPage QToolButton#tableUploadIconButton:disabled, QWidget#videoQueryPage QToolButton#tableDangerIconButton:disabled {{
    background: transparent; color: {tokens.text_disabled};
}}
QWidget#videoQueryPage QWidget#paginationBar {{ background: transparent; border-top: 1px solid {tokens.border}; }}
QWidget#videoQueryPage QPushButton#paginationButton, QWidget#videoQueryPage QPushButton#paginationPageButton {{ background: transparent; border-color: transparent; color: {tokens.text_secondary}; min-height: 34px; min-width: 32px; padding: 2px 7px; }}
QWidget#videoQueryPage QPushButton#paginationButton:hover, QWidget#videoQueryPage QPushButton#paginationPageButton:hover {{ background: {tokens.hover}; color: {tokens.text_primary}; }}
QWidget#videoQueryPage QPushButton#paginationPageButton:checked {{ background: {tokens.selected}; color: {tokens.text_primary}; border-color: transparent; }}
QWidget#videoQueryPage QComboBox#paginationCombo, QWidget#videoQueryPage QLineEdit#paginationJumpInput {{ min-height: 34px; border-color: {tokens.border}; }}

/* The generic filter rule is declared above, so apply the segmented state last. */
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton:hover {{ background: {tokens.hover}; border-color: {tokens.border}; }}
QWidget#videoQueryPage QWidget#querySegmentControl QPushButton#filterButton:checked {{ background: {tokens.selected}; color: {tokens.text_primary}; border-color: {tokens.border}; font-weight: 700; }}
"""
