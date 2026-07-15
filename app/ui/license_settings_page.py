from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.version import APP_VERSION
from app.licensing.constants import LicenseStatus
from app.licensing.license_worker import LicenseOperationWorker
from app.ui.activation_dialog import ActivationDialog
from app.ui.confirm_dialog import confirm_action


STATUS_TEXT = {
    LicenseStatus.UNLICENSED: "未激活",
    LicenseStatus.ACTIVE: "授权有效",
    LicenseStatus.VERIFY_RECOMMENDED: "建议在线验证",
    LicenseStatus.OFFLINE_GRACE: "离线宽限期",
    LicenseStatus.RESTRICTED: "限制模式",
    LicenseStatus.EXPIRED: "授权已过期",
    LicenseStatus.DISABLED: "授权已停用",
    LicenseStatus.REVOKED: "授权已撤销",
    LicenseStatus.DEVICE_MISMATCH: "设备不匹配",
    LicenseStatus.INVALID_LICENSE: "本地授权无效",
    LicenseStatus.SERVER_UNAVAILABLE: "授权服务不可用",
    LicenseStatus.CLOCK_ROLLBACK_SUSPECTED: "系统时间异常",
}

LICENSE_TYPE_TEXT = {
    "monthly": "月度授权",
    "yearly": "年度授权",
    "permanent": "永久授权",
    "fixed_date": "指定日期授权",
}


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "无"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _masked_id(value: str) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value or "无"
    return f"{value[:8]}…{value[-4:]}"


class LicenseSettingsPage(QWidget):
    deactivated = Signal()

    def __init__(self, license_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.license_manager = license_manager
        self._worker: LicenseOperationWorker | None = None
        self._build_ui()
        self.license_manager.status_changed.connect(self._on_license_status_changed)
        self.license_manager.license_updated.connect(self.refresh)
        self.refresh()

    def _on_license_status_changed(self, _status: str) -> None:
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 12)
        root.setSpacing(14)

        card = QFrame(self)
        card.setObjectName("licenseCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)
        heading = QLabel("软件授权", card)
        heading.setObjectName("settingsSectionTitle")
        card_layout.addWidget(heading)
        hint = QLabel("许可证仅绑定当前电脑。本页不会显示激活码、设备凭据或签名原文。", card)
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        fields = (
            ("status", "授权状态"), ("licenseType", "授权类型"), ("edition", "授权版本"),
            ("expiresAt", "到期时间"), ("lastVerifiedAt", "上次在线验证"),
            ("nextRequiredVerifyAt", "下次要求验证"), ("graceUntil", "离线宽限截止"),
            ("deviceId", "当前设备"), ("licenseId", "许可证 ID"),
            ("serverReachable", "服务器状态"), ("appVersion", "客户端版本"),
        )
        self.value_labels: dict[str, QLabel] = {}
        for row, (key, title) in enumerate(fields):
            label = QLabel(title, card)
            label.setObjectName("licenseFieldLabel")
            value = QLabel("-", card)
            value.setObjectName("licenseFieldValue")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            grid.addWidget(label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.value_labels[key] = value
        grid.setColumnStretch(1, 1)
        card_layout.addLayout(grid)
        root.addWidget(card)

        self.operation_status = QLabel("", self)
        self.operation_status.setObjectName("licenseOperationStatus")
        self.operation_status.setWordWrap(True)
        root.addWidget(self.operation_status)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.verify_button = QPushButton("立即验证", self)
        self.verify_button.setObjectName("secondaryButton")
        self.verify_button.clicked.connect(self._verify)
        actions.addWidget(self.verify_button)
        self.copy_button = QPushButton("复制设备编号", self)
        self.copy_button.setObjectName("secondaryButton")
        self.copy_button.clicked.connect(self._copy_device_id)
        actions.addWidget(self.copy_button)
        self.activate_button = QPushButton("激活新授权", self)
        self.activate_button.setObjectName("secondaryButton")
        self.activate_button.clicked.connect(self._activate)
        actions.addWidget(self.activate_button)
        actions.addStretch(1)
        self.deactivate_button = QPushButton("解绑本机", self)
        self.deactivate_button.setProperty("buttonRole", "danger")
        self.deactivate_button.clicked.connect(self._deactivate)
        actions.addWidget(self.deactivate_button)
        root.addLayout(actions)
        root.addStretch(1)

    def refresh(self) -> None:
        info = self.license_manager.get_license_info()
        status = info["status"]
        self.value_labels["status"].setText(STATUS_TEXT.get(status, str(status)))
        self.value_labels["licenseType"].setText(
            LICENSE_TYPE_TEXT.get(str(info["licenseType"]), str(info["licenseType"]) or "无")
        )
        self.value_labels["edition"].setText("专业版" if info["edition"] == "professional" else "无")
        for key in ("expiresAt", "lastVerifiedAt", "nextRequiredVerifyAt", "graceUntil"):
            self.value_labels[key].setText(_format_time(info[key]))
        self.value_labels["deviceId"].setText(_masked_id(info["deviceId"]))
        self.value_labels["licenseId"].setText(_masked_id(info["licenseId"]))
        reachable = info["serverReachable"]
        self.value_labels["serverReachable"].setText(
            "可用" if reachable is True else ("暂不可用" if reachable is False else "尚未检测")
        )
        self.value_labels["appVersion"].setText(f"v{APP_VERSION}")
        has_license = status not in {LicenseStatus.UNLICENSED, LicenseStatus.INVALID_LICENSE}
        self.verify_button.setEnabled(has_license and self._worker is None)
        self.deactivate_button.setEnabled(has_license and self._worker is None)
        self.activate_button.setEnabled(not has_license and self._worker is None)

    def _run(self, operation, success_text: str, on_success=None) -> None:
        if self._worker is not None:
            return
        self.operation_status.setText("正在处理授权请求…")
        self._set_buttons_enabled(False)
        worker = LicenseOperationWorker(operation, self)
        self._worker = worker

        def succeeded(_result) -> None:
            self.operation_status.setText(success_text)
            self.refresh()
            if on_success is not None:
                on_success()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(lambda _code, message: self.operation_status.setText(message))
        worker.finished.connect(self._operation_finished)
        worker.start()

    def _operation_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self.refresh()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.verify_button, self.copy_button, self.activate_button, self.deactivate_button):
            button.setEnabled(enabled)

    def _verify(self) -> None:
        self._run(self.license_manager.verify_online, "授权已完成在线验证")

    def _copy_device_id(self) -> None:
        QApplication.clipboard().setText(self.license_manager.identity.device_id)
        self.operation_status.setText("设备编号已复制")

    def _activate(self) -> None:
        dialog = ActivationDialog(self.license_manager, self)
        if dialog.exec() == QDialog.Accepted:
            self.operation_status.setText("软件授权已激活")
            self.refresh()

    def _deactivate(self) -> None:
        if not confirm_action(
            self,
            title="解绑本机",
            heading="确定解绑当前电脑吗？",
            description="解绑后当前电脑将不能继续使用完整录制功能，但不会删除视频、数据库或配置。",
            confirm_text="解绑本机",
            destructive=True,
            position_key="license_deactivate_confirm",
        ):
            return
        self._run(
            lambda: self.license_manager.deactivate("user_requested"),
            "本机授权已解绑",
            self.deactivated.emit,
        )
