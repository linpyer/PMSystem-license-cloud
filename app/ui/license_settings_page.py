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
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.licensing.constants import LicenseStatus
from app.licensing.license_worker import LicenseOperationWorker
from app.ui.activation_dialog import ActivationDialog
from app.ui.confirm_dialog import confirm_action


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
        status_header = QHBoxLayout()
        status_header.setSpacing(12)
        self.status_icon = QLabel(card)
        self.status_icon.setObjectName("licenseStatusIcon")
        self.status_icon.setFixedSize(34, 34)
        self.status_icon.setAlignment(Qt.AlignCenter)
        status_header.addWidget(self.status_icon, 0, Qt.AlignTop)
        status_text = QVBoxLayout()
        status_text.setSpacing(4)
        self.status_title = QLabel("-", card)
        self.status_title.setObjectName("licenseStatusTitle")
        self.status_description = QLabel("", card)
        self.status_description.setObjectName("licenseStatusDescription")
        self.status_description.setWordWrap(True)
        status_text.addWidget(self.status_title)
        status_text.addWidget(self.status_description)
        status_header.addLayout(status_text, 1)
        card_layout.addLayout(status_header)

        summary = QGridLayout()
        summary.setHorizontalSpacing(24)
        summary.setVerticalSpacing(10)
        self.validity_label = QLabel("有效期", card)
        self.validity_label.setObjectName("licenseFieldLabel")
        self.validity_value = QLabel("-", card)
        self.validity_value.setObjectName("licenseValidityValue")
        self.trial_deadline_label = QLabel("试用截止时间", card)
        self.trial_deadline_label.setObjectName("licenseFieldLabel")
        self.trial_deadline_value = QLabel("-", card)
        self.trial_deadline_value.setObjectName("licenseFieldValue")
        device_label = QLabel("设备编号", card)
        device_label.setObjectName("licenseFieldLabel")
        self.device_value = QLabel("-", card)
        self.device_value.setObjectName("licenseFieldValue")
        self.device_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary.addWidget(self.validity_label, 0, 0)
        summary.addWidget(self.validity_value, 0, 1)
        summary.addWidget(self.trial_deadline_label, 1, 0)
        summary.addWidget(self.trial_deadline_value, 1, 1)
        summary.addWidget(device_label, 2, 0)
        summary.addWidget(self.device_value, 2, 1)
        summary.setColumnStretch(1, 1)
        card_layout.addLayout(summary)

        self.value_labels: dict[str, QLabel] = {
            "status": self.status_title,
            "validity": self.validity_value,
            "trialExpiresAt": self.trial_deadline_value,
            "deviceId": self.device_value,
            "description": self.status_description,
        }

        self.operation_status = QLabel("", card)
        self.operation_status.setObjectName("licenseOperationStatus")
        self.operation_status.setWordWrap(True)
        card_layout.addWidget(self.operation_status)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.verify_button = QPushButton("立即验证", self)
        self.verify_button.setObjectName("secondaryButton")
        self.verify_button.clicked.connect(self._verify)
        actions.addWidget(self.verify_button)
        self.trial_button = QPushButton("重试", self)
        self.trial_button.setObjectName("secondaryButton")
        self.trial_button.clicked.connect(self._retry_trial)
        actions.addWidget(self.trial_button)
        self.copy_button = QPushButton("复制设备编号", self)
        self.copy_button.setObjectName("secondaryButton")
        self.copy_button.clicked.connect(self._copy_device_id)
        actions.addWidget(self.copy_button)
        self.activate_button = QPushButton("立即激活", self)
        self.activate_button.setObjectName("secondaryButton")
        self.activate_button.clicked.connect(self._activate)
        actions.addWidget(self.activate_button)
        actions.addStretch(1)
        self.deactivate_button = QPushButton("解绑设备", self)
        self.deactivate_button.setProperty("buttonRole", "danger")
        self.deactivate_button.clicked.connect(self._deactivate)
        actions.addWidget(self.deactivate_button)
        card_layout.addLayout(actions)
        root.addWidget(card)
        root.addStretch(1)

    def refresh(self) -> None:
        info = self.license_manager.get_license_info()
        status = info["status"]
        license_type = str(info.get("licenseType") or "")
        is_trial = license_type == "TRIAL"
        formal_active = status in {
            LicenseStatus.ACTIVE,
            LicenseStatus.VERIFY_RECOMMENDED,
            LicenseStatus.OFFLINE_GRACE,
        } and not is_trial
        trial_active = status in {LicenseStatus.TRIAL_ACTIVE, LicenseStatus.TRIAL_EXPIRING}
        pending = status == LicenseStatus.TRIAL_PENDING or (
            status == LicenseStatus.SERVER_UNAVAILABLE and not info.get("licenseId")
        )

        trial_deadline = info.get("trialExpiresAt")
        if trial_deadline is not None:
            remaining = max(0, int((trial_deadline - self.license_manager.clock()).total_seconds()))
            days, remainder = divmod(remaining, 86400)
            hours = remainder // 3600
            remaining_text = f"{days}天{hours}小时" if remaining else "已结束"
        elif status == LicenseStatus.SERVER_UNAVAILABLE:
            title = "暂时无法验证授权"
            description = "授权服务暂时不可用，请稍后重新验证。"
            self.validity_label.setText("当前状态")
            self.validity_value.setText("等待验证")
            self._set_trial_deadline_visible(False)
            state = "pending"
        else:
            remaining_text = "无"

        if trial_active:
            title = "免费试用"
            description = (
                "免费试用即将结束，激活后可继续使用完整录制功能。"
                if status == LicenseStatus.TRIAL_EXPIRING
                else "试用期间可使用录制、查询、播放和上传功能。"
            )
            self.validity_label.setText("剩余时间")
            self.validity_value.setText(remaining_text)
            self.trial_deadline_value.setText(_format_time(trial_deadline))
            self._set_trial_deadline_visible(True)
            state = "active"
        elif formal_active:
            title = "已激活"
            description = (
                "当前授权仍可使用，建议联网完成验证。"
                if status in {LicenseStatus.VERIFY_RECOMMENDED, LicenseStatus.OFFLINE_GRACE}
                else "当前电脑已获得完整功能授权。"
            )
            self.validity_label.setText("有效期")
            self.validity_value.setText(
                "永久有效" if license_type == "permanent" else _format_time(info.get("expiresAt"))
            )
            self._set_trial_deadline_visible(False)
            state = "active"
        elif pending:
            title = "等待开启免费试用"
            description = "首次开启免费试用需要连接网络。"
            self.validity_label.setText("当前状态")
            self.validity_value.setText("尚未开始")
            self._set_trial_deadline_visible(False)
            state = "pending"
        else:
            title = "授权已失效"
            description = "历史查询与视频播放仍可使用，激活后可恢复录制和上传功能。"
            self.validity_label.setText("有效期")
            self.validity_value.setText("已失效")
            self._set_trial_deadline_visible(False)
            state = "invalid"

        self.status_title.setText(title)
        self.status_description.setText(description)
        self.device_value.setText(_masked_id(info.get("deviceId")))
        self._set_status_icon(state)
        self.setProperty("licenseState", state)
        self.style().unpolish(self)
        self.style().polish(self)

        has_license = bool(info.get("licenseId"))
        self.verify_button.setEnabled(has_license and self._worker is None)
        self.deactivate_button.setEnabled(formal_active and self._worker is None)
        self.activate_button.setEnabled((not formal_active or is_trial) and self._worker is None)
        self.trial_button.setEnabled(
            pending and self._worker is None
        )
        self.verify_button.setVisible(has_license and not pending)
        self.deactivate_button.setVisible(formal_active)
        self.activate_button.setVisible(not formal_active or is_trial)
        self.trial_button.setVisible(pending)
        self.activate_button.setText("输入激活码" if pending else "立即激活")
        self.verify_button.setText("重新验证" if state == "invalid" else "立即验证")

    def _set_trial_deadline_visible(self, visible: bool) -> None:
        self.trial_deadline_label.setVisible(visible)
        self.trial_deadline_value.setVisible(visible)

    def _set_status_icon(self, state: str) -> None:
        icon_type = {
            "active": QStyle.StandardPixmap.SP_DialogApplyButton,
            "pending": QStyle.StandardPixmap.SP_MessageBoxInformation,
            "invalid": QStyle.StandardPixmap.SP_MessageBoxWarning,
        }[state]
        icon = self.style().standardIcon(icon_type)
        self.status_icon.setPixmap(icon.pixmap(30, 30))

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
        for button in (
            self.verify_button,
            self.trial_button,
            self.copy_button,
            self.activate_button,
            self.deactivate_button,
        ):
            button.setEnabled(enabled)

    def _verify(self) -> None:
        self._run(self.license_manager.verify_online, "授权已完成在线验证")

    def _retry_trial(self) -> None:
        self._run(self.license_manager.activate_trial, "7天免费试用已开启")

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
