from __future__ import annotations

from app.utils.runtime_paths import resource_path


def _qss_url(relative_path: str) -> str:
    return resource_path(relative_path).as_posix()


APP_STYLES = """
* {
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #1f2937;
}

QMainWindow,
QWidget {
    background: #f4f6f8;
}

QTabWidget::pane {
    border: none;
    border-top: 1px solid #d8dee8;
    background: #f4f6f8;
}

QTabBar::tab {
    background: transparent;
    color: #64748b;
    padding: 12px 20px;
    border: none;
    border-bottom: 3px solid transparent;
    min-width: 104px;
}

QTabBar::tab:selected {
    color: #0f766e;
    border-bottom-color: #0f766e;
    font-weight: 600;
}

QTabBar::tab:hover {
    color: #0f766e;
    background: #eef6f5;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #dde5ec;
    border-radius: 8px;
    margin-top: 16px;
    padding: 16px 14px 14px 14px;
    font-weight: 700;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #334155;
    background: #f4f6f8;
    font-weight: 700;
}

QGroupBox#plainRightCard {
    margin-top: 0;
    padding: 10px 12px;
}

QGroupBox#plainRightCard::title {
    padding: 0;
    background: transparent;
}

QGroupBox#recentCard::title {
    padding: 0;
    background: transparent;
}

QGroupBox#recentCard {
    margin-top: 0;
    padding: 10px 12px;
}

QScrollArea#rightOperationScroll {
    background: transparent;
    border: none;
}

QScrollArea#rightOperationScroll > QWidget > QWidget {
    background: transparent;
}

QScrollArea#recordDetailScrollArea {
    background: #ffffff;
    border: none;
}

QScrollArea#recordDetailScrollArea > QWidget > QWidget,
QWidget#recordDetailContent {
    background: #ffffff;
}

QFrame#recordDetailCard {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}

QLabel#detailCardTitle {
    color: #0f172a;
    font-size: 15px;
    font-weight: 700;
}

QLabel#recordDetailLabel {
    color: #64748b;
    font-size: 13px;
    font-weight: 500;
}

QLineEdit#detailCustomReasonInput,
QTextEdit#detailRemarkEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    color: #0f172a;
    padding: 7px 10px;
    selection-background-color: #ccfbf1;
    selection-color: #0f172a;
    placeholder-text-color: #94a3b8;
}

QLineEdit#detailCustomReasonInput:hover,
QTextEdit#detailRemarkEdit:hover {
    border-color: #94a3b8;
}

QLineEdit#detailCustomReasonInput:focus,
QTextEdit#detailRemarkEdit:focus {
    border-color: #14b8a6;
}

QWidget#rightOperationPanel {
    background: transparent;
}

QFrame#recentTitleAccent {
    background: #0f766e;
    border: none;
    border-radius: 1px;
}

QLabel#recentCardTitle {
    color: #0f766e;
    font-weight: 700;
}

QLabel {
    background: transparent;
}

QLabel#pathLabel {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 8px 12px;
    color: #64748b;
}

QLabel#previewLabel {
    background: #111827;
    color: #d1d5db;
    border: 1px solid #243244;
    border-radius: 8px;
}

QLabel#previewLabel[recordingAlert="weak"],
QLabel#previewLabel[recordingAlert="steady"] {
    border: 3px solid rgba(220, 38, 38, 0.42);
}

QLabel#previewLabel[recordingAlert="strong"] {
    border: 3px solid rgba(220, 38, 38, 0.55);
}

QLabel#recBadge {
    background: #dc2626;
    color: #ffffff;
    border-radius: 4px;
    padding: 6px 10px;
    font-weight: 700;
}

QLabel#durationValue {
    color: #0f766e;
    font-weight: 700;
    font-size: 11pt;
}

QLabel#cameraStatusValue {
    color: #64748b;
    font-size: 9pt;
}

QFrame#recordingStatusBlock {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 16px;
}

QLabel#recordingStatusTitle {
    color: #475569;
    font-weight: 700;
    font-size: 26px;
}

QLabel#recordingStatusDetail {
    color: #64748b;
    font-weight: 600;
    font-size: 10pt;
    font-family: "Microsoft YaHei", "Consolas", sans-serif;
}

QFrame#recordingStatusBlock[state="idle"] {
    background: #f8fafc;
    border-color: #cbd5e1;
}

QFrame#recordingStatusBlock[state="idle"] QLabel {
    color: #475569;
}

QFrame#recordingStatusBlock[state="recording"] {
    background: #ecfdf5;
    border-color: #5eead4;
}

QFrame#recordingStatusBlock[state="recording"] QLabel {
    color: #047857;
}

QFrame#recordingStatusBlock[state="start"] {
    background: #ecfdf5;
    border-color: #2dd4bf;
}

QFrame#recordingStatusBlock[state="start"] QLabel {
    color: #047857;
}

QFrame#recordingStatusBlock[state="stop"] {
    background: #eff6ff;
    border-color: #93c5fd;
}

QFrame#recordingStatusBlock[state="stop"] QLabel {
    color: #2563eb;
}

QFrame#recordingStatusBlock[state="switch"] {
    background: #f0fdfa;
    border-color: #5eead4;
}

QFrame#recordingStatusBlock[state="switch"] QLabel {
    color: #0f766e;
}

QFrame#recordingStatusBlock[state="warning"] {
    background: #fffbeb;
    border-color: #fcd34d;
}

QFrame#recordingStatusBlock[state="warning"] QLabel {
    color: #d97706;
}

QFrame#recordingStatusBlock[state="error"] {
    background: #fef2f2;
    border-color: #fca5a5;
}

QFrame#recordingStatusBlock[state="error"] QLabel {
    color: #dc2626;
}

QLabel#hintLabel {
    color: #64748b;
}

QLabel#subtleLabel {
    color: #64748b;
    font-weight: 500;
}

QLabel#sectionTitle,
QLabel#recordTypeTitle {
    color: #334155;
    font-weight: 700;
}

QLineEdit {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 4px;
    padding: 7px 9px;
    min-height: 22px;
    selection-background-color: #bfdbfe;
}

QLineEdit:focus,
QAbstractSpinBox:focus {
    border-color: #0f766e;
}

QComboBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    color: #0f172a;
    font-size: 14px;
    min-height: 34px;
    padding: 6px 34px 6px 12px;
    selection-background-color: #bfdbfe;
}

QComboBox:hover {
    border-color: #14b8a6;
}

QComboBox:focus {
    border-color: #0f766e;
}

QComboBox:disabled {
    color: #94a3b8;
    background-color: #f8fafc;
    border-color: #e2e8f0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: transparent;
}

QComboBox::drop-down:hover {
    background: #f0fdfa;
}

QComboBox::down-arrow {
    image: url("__CHEVRON_DOWN__");
    width: 12px;
    height: 12px;
}

QComboBox::down-arrow:disabled {
    image: url("__CHEVRON_DOWN_DISABLED__");
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    color: #0f172a;
    selection-background-color: #ccfbf1;
    selection-color: #0f172a;
    outline: none;
    padding: 4px;
}

QComboBox#detailRecordTypeCombo,
QComboBox#detailImportantReasonCombo {
    min-height: 28px;
    max-height: 30px;
    min-width: 90px;
    padding: 4px 28px 4px 10px;
    font-size: 13px;
}

QComboBox#detailRecordTypeCombo {
    max-width: 112px;
}

QComboBox#detailImportantReasonCombo {
    max-width: 168px;
}

QComboBox#detailRecordTypeCombo::drop-down,
QComboBox#detailImportantReasonCombo::drop-down {
    width: 26px;
}

QComboBox#detailRecordTypeCombo::down-arrow,
QComboBox#detailImportantReasonCombo::down-arrow {
    width: 10px;
    height: 10px;
}

QCheckBox#detailImportantCheckbox {
    background: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
    spacing: 8px;
    color: #0f172a;
    font-size: 13px;
}

QCheckBox#detailImportantCheckbox:hover,
QCheckBox#detailImportantCheckbox:pressed,
QCheckBox#detailImportantCheckbox:checked,
QCheckBox#detailImportantCheckbox:disabled {
    background: transparent;
    border: none;
}

QCheckBox#detailImportantCheckbox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
}

QCheckBox#detailImportantCheckbox::indicator:hover {
    border-color: #14b8a6;
    background: #f0fdfa;
}

QCheckBox#detailImportantCheckbox::indicator:pressed {
    border-color: #0f766e;
    background: #ccfbf1;
}

QCheckBox#detailImportantCheckbox::indicator:checked {
    border-color: #0f766e;
    background: #0f766e;
    image: url("__CHECKMARK__");
}

QCheckBox#detailImportantCheckbox::indicator:disabled {
    border-color: #e2e8f0;
    background: #f8fafc;
}

QCheckBox#detailImportantCheckbox:disabled {
    color: #94a3b8;
}

QComboBox#queryCompactFilterCombo {
    min-height: 30px;
    max-height: 34px;
    padding: 4px 28px 4px 10px;
    border-radius: 8px;
    font-size: 14px;
}

QComboBox#queryCompactFilterCombo::drop-down {
    width: 26px;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

QComboBox#queryCompactFilterCombo::down-arrow {
    width: 10px;
    height: 10px;
}

QAbstractSpinBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    color: #0f172a;
    min-height: 34px;
    padding: 6px 28px 6px 10px;
    selection-background-color: #bfdbfe;
}

QAbstractSpinBox:hover {
    border-color: #14b8a6;
}

QAbstractSpinBox:disabled {
    color: #94a3b8;
    background-color: #f8fafc;
    border-color: #e2e8f0;
}

QAbstractSpinBox::up-button,
QAbstractSpinBox::down-button {
    width: 22px;
    border: none;
    background: transparent;
}

QAbstractSpinBox::up-button:hover,
QAbstractSpinBox::down-button:hover {
    background: #f0fdfa;
}

QAbstractSpinBox::up-arrow {
    image: url("__CHEVRON_UP__");
    width: 10px;
    height: 10px;
}

QAbstractSpinBox::down-arrow {
    image: url("__CHEVRON_DOWN__");
    width: 10px;
    height: 10px;
}

QAbstractSpinBox::up-arrow:disabled {
    image: url("__CHEVRON_UP_DISABLED__");
}

QAbstractSpinBox::down-arrow:disabled {
    image: url("__CHEVRON_DOWN_DISABLED__");
}

QLineEdit#scanInput {
    min-height: 36px;
    padding: 8px 10px;
    font-size: 11pt;
}

QRadioButton#recordTypeRadio {
    background: transparent;
    border: none;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 11pt;
    spacing: 10px;
    padding: 3px 12px 3px 0;
    color: #1f2937;
}

QRadioButton#recordTypeRadio:hover,
QRadioButton#recordTypeRadio:checked,
QRadioButton#recordTypeRadio:disabled {
    background: transparent;
    border: none;
}

QRadioButton#recordTypeRadio::indicator {
    width: 20px;
    height: 20px;
    border-radius: 10px;
    border: 2px solid #cbd5e1;
    background: #ffffff;
}

QRadioButton#recordTypeRadio::indicator:hover {
    border-color: #60a5fa;
}

QRadioButton#recordTypeRadio::indicator:checked {
    border: 2px solid #2563eb;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.58, fx:0.5, fy:0.5, stop:0 #2563eb, stop:0.42 #2563eb, stop:0.45 #ffffff, stop:1 #ffffff);
}

QRadioButton#recordTypeRadio::indicator:disabled {
    border-color: #d1d5db;
    background: #f3f4f6;
}

QRadioButton#recordTypeRadio:checked {
    font-weight: 400;
    color: #0f766e;
}

QRadioButton#recordTypeRadio:disabled {
    color: #64748b;
}

QRadioButton#recordTypeRadio:checked:disabled {
    color: #0f766e;
}

QRadioButton#recordTypeRadio::indicator:checked:disabled {
    border: 2px solid #2563eb;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.58, fx:0.5, fy:0.5, stop:0 #2563eb, stop:0.42 #2563eb, stop:0.45 #ffffff, stop:1 #ffffff);
}

QFrame#recordTypeSeparator {
    background-color: #e5e7eb;
    border: none;
    max-height: 1px;
}

QPushButton {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 6px;
    padding: 5px 11px;
    min-height: 24px;
    color: #1f2937;
    font-weight: 600;
}

QPushButton:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background: #e2e8f0;
}

QPushButton#primaryButton {
    background: #0f766e;
    border-color: #0f766e;
    color: #ffffff;
    font-weight: 700;
}

QPushButton#primaryButton:hover {
    background: #115e59;
}

QPushButton#stopButton,
QPushButton#dangerButton {
    background: #dc2626;
    border-color: #dc2626;
    color: #ffffff;
    font-weight: 700;
}

QPushButton#stopButton:hover,
QPushButton#dangerButton:hover {
    background: #b91c1c;
}

QPushButton#secondaryButton {
    background: #ffffff;
    border-color: #cfd8e3;
    color: #334155;
}

QPushButton#secondaryButton:hover {
    background: #f8fafc;
    border-color: #94a3b8;
    color: #0f766e;
}

QPushButton#retryUploadButton {
    background: #fffbeb;
    border-color: #f59e0b;
    color: #b45309;
    font-weight: 700;
}

QPushButton#retryUploadButton:hover {
    background: #fef3c7;
    border-color: #d97706;
    color: #92400e;
}

QPushButton:disabled,
QPushButton#primaryButton:disabled,
QPushButton#stopButton:disabled,
QPushButton#dangerButton:disabled,
QPushButton#secondaryButton:disabled,
QPushButton#retryUploadButton:disabled {
    background: #f1f5f9;
    border-color: #dbe2ea;
    color: #94a3b8;
}

QWidget#tableActionCell {
    background: transparent;
}

QWidget#recentRecordingRow {
    background: transparent;
    border-bottom: 1px solid #eef2f7;
}

QLabel#recentOrderText {
    color: #1f2937;
    font-weight: 700;
}

QLabel#recentMetaText {
    color: #64748b;
    font-size: 9pt;
}

QLabel#recentTypeTag {
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 9pt;
    font-weight: 700;
}

QLabel#recentTypeTag[recordType="ship"] {
    background: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #047857;
}

QLabel#recentTypeTag[recordType="return"] {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    color: #c2410c;
}

QPushButton#recentDeleteButton {
    background: #ffffff;
    border: 1px solid #fca5a5;
    border-radius: 8px;
    color: #dc2626;
    font-weight: 700;
    padding: 0;
    min-width: 76px;
    max-width: 76px;
    min-height: 36px;
    max-height: 36px;
}

QPushButton#recentDeleteButton:hover {
    background: #fef2f2;
    border-color: #ef4444;
    color: #b91c1c;
}

QPushButton#recentDeleteButton:pressed {
    background: #fee2e2;
    border-color: #dc2626;
    color: #991b1b;
}

QLabel#recordTypeTag {
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 9pt;
    font-weight: 700;
    min-height: 18px;
}

QLabel#recordTypeTag[recordType="ship"] {
    background: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #047857;
}

QLabel#recordTypeTag[recordType="return"] {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    color: #c2410c;
}

QWidget#statusCell {
    background: transparent;
}

QWidget#statusBadgeHost {
    background: transparent;
}

QWidget#statusLine {
    background: transparent;
}

QLabel#statusText {
    background: transparent;
    color: #1f2937;
}

QLabel#statusText[statusState="normal"] {
    color: #1f2937;
}

QLabel#statusText[statusState="error"] {
    color: #b91c1c;
    font-weight: 600;
}

QLabel#tablePrimaryText {
    background: transparent;
    color: #1f2937;
}

QLabel#tableSubText {
    background: transparent;
    color: #64748b;
    font-size: 9pt;
}

QLabel#tableSubText[state="warning"] {
    color: #dc2626;
    font-weight: 700;
}

QLabel#duplicateBadge {
    background: #fee2e2;
    color: #dc2626;
    border: 1px solid #fca5a5;
    border-radius: 8px;
    min-width: 18px;
    min-height: 18px;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 6px;
    qproperty-wordWrap: false;
}

QLabel#validationWarningBadge {
    background: #fef3c7;
    color: #d97706;
    border: 1px solid #fbbf24;
    border-radius: 8px;
    min-height: 18px;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 7px;
    qproperty-wordWrap: false;
}

QLabel#uploadStatusText {
    background: transparent;
    color: #64748b;
    font-size: 9pt;
    font-weight: 600;
}

QLabel#uploadStatusText[uploadState="done"] {
    color: #047857;
}

QLabel#uploadStatusText[uploadState="uploading"] {
    color: #2563eb;
}

QLabel#uploadStatusText[uploadState="failed"] {
    color: #dc2626;
}

QLabel#uploadStatusText[uploadState="pending"] {
    color: #d97706;
}

QPushButton#tableUploadButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #0f766e;
    font-weight: 600;
    padding: 0;
    min-height: 26px;
    min-width: 48px;
    max-height: 26px;
    max-width: 48px;
}

QPushButton#tableUploadButton:hover {
    background: transparent;
    border: none;
    color: #0b5f59;
    text-decoration: underline;
}

QPushButton#tableUploadButton:disabled {
    color: #94a3b8;
    text-decoration: none;
}

QPushButton#tableDangerButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #b91c1c;
    font-weight: 600;
    padding: 0;
    min-height: 26px;
    min-width: 48px;
    max-height: 26px;
    max-width: 48px;
}

QPushButton#tableDangerButton:hover {
    background: transparent;
    border: none;
    color: #991b1b;
    text-decoration: underline;
}

QPushButton#tableDangerButton:pressed {
    background: transparent;
    border: none;
}

QPushButton#sceneLinkButton,
QPushButton#openSceneLinkButton,
QPushButton#revealSceneLinkButton {
    background: transparent;
    border: none;
    padding: 0;
    min-width: 32px;
    min-height: 22px;
    font-weight: 600;
}

QPushButton#sceneLinkButton {
    color: #0b5cad;
}

QPushButton#openSceneLinkButton {
    color: #0f766e;
}

QPushButton#revealSceneLinkButton {
    color: #2563eb;
}

QPushButton#sceneLinkButton:hover,
QPushButton#openSceneLinkButton:hover,
QPushButton#revealSceneLinkButton:hover {
    background: transparent;
    border: none;
    text-decoration: underline;
}

QPushButton#sceneLinkButton:hover {
    color: #075985;
}

QPushButton#openSceneLinkButton:hover {
    color: #115e59;
}

QPushButton#revealSceneLinkButton:hover {
    color: #1d4ed8;
}

QPushButton#datePickerButton {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 4px;
    padding: 7px 28px 7px 10px;
    min-height: 22px;
    color: #1f2937;
    text-align: left;
}

QPushButton#datePickerButton:hover {
    background: #f8fafc;
    border-color: #94a3b8;
}

QPushButton#datePickerButton:focus {
    border-color: #0f766e;
}

QPushButton#filterButton {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 14px;
    padding: 6px 13px;
    min-height: 24px;
}

QPushButton#filterButton:hover {
    background: #eef6f5;
    border-color: #0f766e;
    color: #0f766e;
}

QPushButton#filterButton:checked {
    background: #0f766e;
    border-color: #0f766e;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#filterButton:checked:hover {
    background: #115e59;
    border-color: #115e59;
}

QWidget#netdiskProgressPanel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}

QLabel#netdiskProgressTitle {
    color: #1f2937;
    font-weight: 700;
}

QLabel#netdiskProgressStats {
    color: #64748b;
    font-size: 12px;
}

QLabel#netdiskProgressCurrent {
    color: #64748b;
    font-size: 12px;
}

QProgressBar#netdiskProgressBar {
    background: #e5e7eb;
    border: none;
    border-radius: 4px;
    min-height: 7px;
    max-height: 7px;
}

QProgressBar#netdiskProgressBar::chunk {
    background: #0f766e;
    border-radius: 4px;
}

QWidget#paginationBar {
    background: transparent;
}

QLabel#paginationTotalLabel {
    color: #475569;
    font-weight: 500;
}

QLabel#paginationEllipsis {
    color: #64748b;
    min-width: 28px;
    max-width: 28px;
}

QComboBox#paginationCombo {
    background: #ffffff;
    border: 1px solid #dbe2ea;
    border-radius: 6px;
    padding: 4px 28px 4px 8px;
    min-height: 28px;
    max-height: 28px;
    min-width: 86px;
    max-width: 96px;
}

QComboBox#paginationCombo:hover,
QComboBox#paginationCombo:focus {
    border-color: #0f766e;
}

QComboBox#paginationCombo::drop-down {
    width: 24px;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

QComboBox#paginationCombo::down-arrow {
    width: 11px;
    height: 11px;
}

QPushButton#paginationButton,
QPushButton#paginationPageButton {
    background: #ffffff;
    border: 1px solid #dbe2ea;
    border-radius: 6px;
    color: #334155;
    font-weight: 700;
    min-width: 34px;
    max-width: 34px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
}

QPushButton#paginationButton:hover,
QPushButton#paginationPageButton:hover {
    background: #eef6f5;
    border-color: #0f766e;
    color: #0f766e;
}

QPushButton#paginationPageButton:checked {
    background: #0f766e;
    border-color: #0f766e;
    color: #ffffff;
}

QFrame#settingsCard,
QFrame#customVoicePanel {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}

QLabel#settingsCardTitle {
    color: #0f172a;
    font-size: 15px;
    font-weight: 700;
}

QLabel#settingsHint,
QLabel#hintLabel {
    color: #64748b;
    font-size: 12px;
}

QLabel#authStatusTag {
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    color: #64748b;
    font-size: 12px;
    font-weight: 700;
}

QLabel#authStatusTag[status="ok"] {
    border-color: #bbf7d0;
    background: #f0fdf4;
    color: #047857;
}

QLabel#authStatusTag[status="none"] {
    border-color: #e2e8f0;
    background: #f8fafc;
    color: #64748b;
}

QWidget#transparentSettingsRow,
QWidget#voiceTableWidget {
    background: transparent;
}

QComboBox#settingsCompactCombo {
    min-height: 32px;
    max-height: 36px;
    padding: 5px 30px 5px 10px;
    border-radius: 8px;
}

QComboBox#settingsCompactCombo::drop-down {
    width: 28px;
}

QComboBox#settingsCompactCombo::down-arrow {
    width: 10px;
    height: 10px;
}

QSpinBox#settingsCompactSpin {
    min-height: 32px;
    max-height: 36px;
    padding: 5px 24px 5px 10px;
    border-radius: 8px;
}

QCheckBox#settingsInlineCheckBox {
    background: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
    min-height: 32px;
    spacing: 8px;
    color: #0f172a;
}

QCheckBox#settingsInlineCheckBox:hover,
QCheckBox#settingsInlineCheckBox:pressed,
QCheckBox#settingsInlineCheckBox:checked,
QCheckBox#settingsInlineCheckBox:disabled {
    background: transparent;
    border: none;
}

QCheckBox#settingsInlineCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
}

QCheckBox#settingsInlineCheckBox::indicator:hover {
    border-color: #14b8a6;
    background: #f0fdfa;
}

QCheckBox#settingsInlineCheckBox::indicator:checked {
    border-color: #0f766e;
    background: #0f766e;
    image: url("__CHECKMARK__");
}

QCheckBox#settingsInlineCheckBox::indicator:disabled {
    border-color: #e2e8f0;
    background: #f8fafc;
}

QMenu,
QMenu#copyContextMenu {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px;
    color: #0f172a;
}

QMenu::item {
    min-width: 112px;
    min-height: 28px;
    padding: 4px 18px;
    border-radius: 6px;
}

QMenu::item:selected {
    background: #ccfbf1;
    color: #0f172a;
}

QPushButton#paginationButton:disabled {
    background: #f8fafc;
    border-color: #e5e7eb;
    color: #cbd5e1;
}

QLineEdit#paginationJumpInput {
    background: #ffffff;
    border: 1px solid #dbe2ea;
    border-radius: 6px;
    min-height: 26px;
    max-height: 26px;
    padding: 2px 8px;
}

QLineEdit#paginationJumpInput:focus {
    border-color: #0f766e;
}

QToolButton#statsButton,
QToolButton#settingsButton,
QToolButton#helpIconButton {
    margin: 6px 0 6px 0;
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 6px;
    color: #334155;
    font-size: 13pt;
    font-weight: 700;
    min-width: 34px;
    max-width: 34px;
    min-height: 32px;
    max-height: 32px;
}

QToolButton#statsButton:hover,
QToolButton#settingsButton:hover,
QToolButton#helpIconButton:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
    color: #0f766e;
}

QPushButton#helpEntryButton {
    margin: 6px 0 6px 0;
    padding: 6px 12px;
    min-height: 24px;
    border-radius: 6px;
    font-weight: 600;
}

QToolButton#helpButton {
    background: #eef2f7;
    border: 1px solid #cbd5e1;
    border-radius: 9px;
    color: #475569;
    font-weight: 700;
    padding: 0;
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    max-height: 18px;
}

QToolButton#helpButton:hover {
    background: #dbeafe;
    border-color: #93c5fd;
    color: #1d4ed8;
}

QToolButton#extendedFilterToggleButton {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 8px;
    color: #475569;
    padding: 0;
}

QToolButton#extendedFilterToggleButton:hover {
    background: #f0fdfa;
    border-color: #14b8a6;
    color: #0f766e;
}

QToolButton#extendedFilterToggleButton:pressed {
    background: #ccfbf1;
    border-color: #0f766e;
    color: #0f766e;
}

QTableWidget {
    background: #ffffff;
    border: 1px solid #dde5ec;
    border-radius: 8px;
    gridline-color: #f1f5f9;
    alternate-background-color: #f8fafc;
    selection-background-color: transparent;
    selection-color: #0f172a;
    outline: 0;
}

QTableWidget::item {
    padding: 8px 10px;
    border: none;
}

QTableWidget::item:hover {
    background: #ecfdf5;
    color: #0f172a;
    border: none;
}

QTableWidget::item:selected,
QTableWidget::item:selected:active,
QTableWidget::item:selected:!active {
    background: #ccfbf1;
    color: #0f172a;
    border: none;
}

QTableWidget::item:focus {
    border: none;
    outline: none;
}

QFrame#videoTableStateOverlay {
    background: transparent;
    border: none;
}

QFrame#videoTableStateBox {
    background: rgba(255, 255, 255, 232);
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}

QLabel#videoLoadingSpinner {
    color: #0f766e;
    font-size: 18px;
    font-weight: 800;
    min-width: 22px;
}

QLabel#videoTableStateIcon {
    color: #94a3b8;
    font-size: 30px;
    font-weight: 700;
}

QLabel#videoTableStateTitle {
    color: #475569;
    font-size: 15px;
    font-weight: 700;
}

QLabel#videoTableStateSubtitle {
    color: #94a3b8;
    font-size: 12px;
}

QFrame#videoSkeletonBlock {
    background: #e2e8f0;
    border: none;
    border-radius: 6px;
}

QHeaderView::section {
    background: #f1f5f9;
    color: #334155;
    border: none;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #dbe2ea;
    padding: 9px 8px;
    font-weight: 700;
}

QLabel#queryNotice {
    margin: 0;
}

QDialog#helpDialog {
    background: #f4f6f8;
}

QDialog#settingsDialog {
    background: #f4f6f8;
}

QTextBrowser#helpContent {
    background: #ffffff;
    border: 1px solid #dbe2ea;
    border-radius: 6px;
    padding: 14px;
}

QTabBar#helpTabBar::scroller {
    width: 88px;
}

QToolButton#helpPrevButton,
QToolButton#helpNextButton,
QTabBar#helpTabBar QToolButton {
    width: 36px;
    height: 36px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    border: 1px solid #cbd5e1;
    border-radius: 9px;
    background: #ffffff;
    color: #475569;
    padding: 0px;
    margin: 0px;
}

QToolButton#helpPrevButton:hover,
QToolButton#helpNextButton:hover,
QTabBar#helpTabBar QToolButton:hover {
    border-color: #14b8a6;
    background: #f0fdfa;
    color: #0f766e;
}

QToolButton#helpPrevButton:pressed,
QToolButton#helpNextButton:pressed,
QTabBar#helpTabBar QToolButton:pressed {
    border-color: #0f766e;
    background: #ccfbf1;
    color: #0f766e;
}

QToolButton#helpPrevButton:disabled,
QToolButton#helpNextButton:disabled,
QTabBar#helpTabBar QToolButton:disabled {
    border-color: #e2e8f0;
    background: #f8fafc;
    color: #94a3b8;
}

QDialog#packagingStatsDialog {
    background: #f8fafc;
}

QScrollArea#statsTabScrollArea {
    background: #f8fafc;
    border: none;
}

QScrollArea#statsTabScrollArea > QWidget > QWidget,
QWidget#statsTabContent {
    background: #f8fafc;
}

QLabel#statsDialogTitle {
    color: #0f172a;
    font-size: 20px;
    font-weight: 800;
}

QLabel#statsDialogSubtitle {
    color: #64748b;
    font-size: 12px;
}

QFrame#statsMetricCard,
QFrame#statsChartCard {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}

QFrame#statsOverviewSection {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
}

QLabel#statsCardTitle {
    color: #64748b;
    font-size: 13px;
    font-weight: 700;
}

QLabel#statsCardValue {
    color: #0f172a;
    font-size: 34px;
    font-weight: 800;
}

QLabel#statsCardHint,
QLabel#statsSummaryLabel {
    color: #94a3b8;
    font-size: 12px;
}

QLabel#statsCardDrillHint {
    color: #94a3b8;
    font-size: 12px;
}

QPushButton#statsQuickButton,
QPushButton#statsSegmentButton {
    min-height: 30px;
    border-radius: 8px;
    padding: 4px 12px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    color: #334155;
}

QPushButton#statsQuickButton:hover,
QPushButton#statsSegmentButton:hover {
    background: #f0fdfa;
    border-color: #14b8a6;
    color: #0f766e;
}

QPushButton#statsQuickButton:checked,
QPushButton#statsSegmentButton:checked {
    background: #14b8a6;
    border-color: #14b8a6;
    color: #ffffff;
}

QToolTip {
    background-color: #ffffff;
    color: #111827;
    border: 1px solid #cbd5e1;
    padding: 6px 8px;
    border-radius: 4px;
}

QStatusBar {
    background: #ffffff;
    border-top: 1px solid #dbe2ea;
    color: #475569;
}

QWidget#statusTipLabel {
    background: transparent;
    border: none;
    margin-left: 8px;
}

QLabel#statusVersionLabel {
    background: transparent;
    border: none;
    color: #64748b;
    padding: 0 10px 0 8px;
    font-weight: 500;
}

QScrollBar:vertical {
    width: 10px;
    background: #f1f5f9;
    border: none;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 40px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::handle:vertical:pressed {
    background: #64748b;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    height: 10px;
    background: #f1f5f9;
    border: none;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 40px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #94a3b8;
}

QScrollBar::handle:horizontal:pressed {
    background: #64748b;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
""".replace("__CHECKMARK__", _qss_url("app/assets/checkmark.svg")).replace(
    "__CHEVRON_DOWN__", _qss_url("app/assets/icons/chevron-down.svg")
).replace(
    "__CHEVRON_DOWN_DISABLED__", _qss_url("app/assets/icons/chevron-down-disabled.svg")
).replace("__CHEVRON_UP__", _qss_url("app/assets/icons/chevron-up.svg")).replace(
    "__CHEVRON_UP_DISABLED__", _qss_url("app/assets/icons/chevron-up-disabled.svg")
)
