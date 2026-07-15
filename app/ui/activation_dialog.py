from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.licensing.errors import LicenseApiError, localized_error
from app.licensing.license_api import LICENSE_CODE_ALPHABET
from app.licensing.license_worker import LicenseOperationWorker
from app.ui.dialog_utils import DialogSizeManager
from app.ui.themed_line_edit import ThemedClearableLineEdit


class ActivationDialog(QDialog):
    """Online activation dialog shown before the main window has a valid license."""

    def __init__(self, license_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.license_manager = license_manager
        self._worker: LicenseOperationWorker | None = None
        self._busy = False
        self.setObjectName("activationDialog")
        self.setWindowTitle("PMSystem 软件激活")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMaximumWidth(620)
        self._build_ui()
        DialogSizeManager.apply(self, "activation", parent, "small", (540, 400))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        title = QLabel("PMSystem 软件激活", self)
        title.setObjectName("activationTitle")
        root.addWidget(title)

        intro = QLabel("首次激活需要连接授权服务器。激活完成后，本机可按授权期限使用。", self)
        intro.setObjectName("settingsHint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        card = QFrame(self)
        card.setObjectName("licenseCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)
        code_label = QLabel("激活码", card)
        code_label.setObjectName("licenseFieldLabel")
        card_layout.addWidget(code_label)
        self.code_input = ThemedClearableLineEdit(card)
        self.code_input.setObjectName("licenseCodeInput")
        self.code_input.setPlaceholderText("PMS-XXXX-XXXX-XXXX-XXXX")
        self.code_input.setMaxLength(23)
        self.code_input.setMinimumHeight(42)
        self.code_input.textEdited.connect(self._format_code)
        self.code_input.returnPressed.connect(self._start_activation)
        card_layout.addWidget(self.code_input)

        identity = self.license_manager.identity
        device = QLabel(f"当前设备：{identity.device_id[:12].upper()}…  ({identity.fingerprint_version})", card)
        device.setObjectName("subtleLabel")
        device.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(device)
        root.addWidget(card)

        self.status_label = QLabel("授权服务：等待激活", self)
        self.status_label.setObjectName("licenseOperationStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.exit_button = QPushButton("退出程序", self)
        self.exit_button.setObjectName("secondaryButton")
        self.exit_button.clicked.connect(self.reject)
        actions.addWidget(self.exit_button)
        self.activate_button = QPushButton("激活", self)
        self.activate_button.setObjectName("primaryButton")
        self.activate_button.setDefault(True)
        self.activate_button.clicked.connect(self._start_activation)
        actions.addWidget(self.activate_button)
        root.addLayout(actions)

    def _format_code(self, value: str) -> None:
        compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        if compact.startswith("PMS"):
            compact = compact[3:]
        compact = "".join(char for char in compact if char in LICENSE_CODE_ALPHABET)[:16]
        formatted = "PMS" + ("-" if compact else "")
        formatted += "-".join(compact[index:index + 4] for index in range(0, len(compact), 4))
        if formatted != value:
            cursor = len(formatted)
            self.code_input.blockSignals(True)
            self.code_input.setText(formatted)
            self.code_input.setCursorPosition(cursor)
            self.code_input.blockSignals(False)

    def _start_activation(self) -> None:
        if self._busy:
            return
        code = self.code_input.text().strip()
        compact = code.replace("-", "")
        if len(compact) != 19 or not compact.startswith("PMS"):
            self.status_label.setText("请输入完整的 PMS 激活码。")
            self.code_input.setFocus(Qt.OtherFocusReason)
            return
        self._set_busy(True)
        self.status_label.setText("正在连接授权服务器并验证…")
        worker = LicenseOperationWorker(lambda: self.license_manager.activate(code), self)
        self._worker = worker
        worker.succeeded.connect(self._on_activation_succeeded)
        worker.failed.connect(self._on_activation_failed)
        worker.finished.connect(self._clear_worker)
        worker.start()

    def _on_activation_succeeded(self, _status) -> None:
        self.status_label.setText("激活成功，正在进入系统…")
        self.accept()

    def _on_activation_failed(self, code: str, message: str) -> None:
        if code in {"CLIENT_LICENSE_ERROR", "CLIENT_VALIDATION_ERROR"}:
            display = message
        else:
            display = localized_error(LicenseApiError(code, message))
        self.status_label.setText(display)
        self._set_busy(False)
        self.code_input.setFocus(Qt.OtherFocusReason)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.code_input.setEnabled(not busy)
        self.activate_button.setEnabled(not busy)
        self.activate_button.setText("激活中…" if busy else "激活")
        self.exit_button.setEnabled(not busy)

    def _clear_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)
