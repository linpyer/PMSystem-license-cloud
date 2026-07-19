from __future__ import annotations

from datetime import timedelta

import pytest
from PySide6.QtCore import QObject, Signal

from app.core.netdisk_sync import NetdiskUploadWorker
from app.core.recorder import RecorderThread
from app.licensing.constants import LicenseStatus
from app.ui.activation_dialog import ActivationDialog
from app.ui.help_dialog import HELP_TABS, HelpDialog
from app.ui.license_settings_page import LicenseSettingsPage
from app.ui.main_window import RESTRICTED_LICENSE_BANNER_TEXT
from main import _license_requires_activation
from tests.licensing.helpers import DEVICE_ID, LICENSE_ID, NOW


class FakeManager(QObject):
    status_changed = Signal(str)
    license_updated = Signal()

    def __init__(self, status=LicenseStatus.ACTIVE):
        super().__init__()
        self.status = status
        self.activate_calls = []
        self.identity = type(
            "Identity",
            (),
            {"device_id": DEVICE_ID, "fingerprint_version": "win-v1", "device_name": "Test PC"},
        )()

    def get_status(self): return self.status

    def get_license_info(self):
        is_trial = self.status in {
            LicenseStatus.TRIAL_ACTIVE,
            LicenseStatus.TRIAL_EXPIRING,
            LicenseStatus.TRIAL_EXPIRED,
        }
        pending = self.status in {LicenseStatus.TRIAL_PENDING, LicenseStatus.SERVER_UNAVAILABLE}
        return {
            "status": self.status,
            "licenseId": None if pending else LICENSE_ID,
            "licenseType": "TRIAL" if is_trial else "monthly",
            "edition": "professional",
            "expiresAt": NOW + timedelta(days=30),
            "lastVerifiedAt": NOW,
            "nextRequiredVerifyAt": NOW + timedelta(days=7),
            "graceUntil": NOW + timedelta(days=21),
            "deviceId": DEVICE_ID,
            "fingerprintVersion": "win-v1",
            "serverReachable": True,
            "lastErrorCode": "",
            "trialStartedAt": NOW - timedelta(days=1) if is_trial else None,
            "trialExpiresAt": NOW + timedelta(days=6) if is_trial else None,
            "environment": "staging-should-not-be-visible",
            "apiBaseUrl": "https://internal-should-not-be-visible.example/api/v1",
        }

    def clock(self): return NOW

    def activate(self, code):
        self.activate_calls.append(code)
        self.status = LicenseStatus.ACTIVE
        self.status_changed.emit(self.status.value)
        return self.status

    def activate_trial(self):
        self.status = LicenseStatus.TRIAL_ACTIVE
        self.status_changed.emit(self.status.value)
        return self.status

    def verify_online(self): return self.status
    def deactivate(self, reason):
        self.status = LicenseStatus.UNLICENSED
        self.status_changed.emit(self.status.value)
        return self.status


def test_activation_code_formats_without_spaces(qtbot):
    dialog = ActivationDialog(FakeManager(LicenseStatus.UNLICENSED))
    qtbot.addWidget(dialog)
    dialog._format_code("pms 2345 6789 abcd efgh")
    assert dialog.code_input.text() == "PMS-2345-6789-ABCD-EFGH"


def test_activation_runs_in_worker_and_accepts(qtbot):
    manager = FakeManager(LicenseStatus.UNLICENSED)
    dialog = ActivationDialog(manager)
    qtbot.addWidget(dialog)
    dialog.code_input.setText("PMS-2345-6789-ABCD-EFGH")
    with qtbot.waitSignal(dialog.accepted, timeout=2000):
        dialog._start_activation()
    assert manager.activate_calls == ["PMS-2345-6789-ABCD-EFGH"]


def test_license_settings_masks_identifiers_and_never_shows_credential(qtbot):
    page = LicenseSettingsPage(FakeManager())
    qtbot.addWidget(page)
    visible = " ".join(label.text() for label in page.findChildren(type(page.value_labels["status"])))
    assert LICENSE_ID not in visible
    assert DEVICE_ID not in visible
    assert "credential" not in visible.lower()
    assert "API地址" not in visible
    assert "授权环境" not in visible
    assert "许可证 ID" not in visible
    assert "上次在线验证" not in visible


def test_license_settings_shows_only_formal_license_core_information(qtbot):
    page = LicenseSettingsPage(FakeManager(LicenseStatus.ACTIVE))
    qtbot.addWidget(page)
    visible = " ".join(label.text() for label in page.findChildren(type(page.status_title)))
    assert "已激活" in visible
    assert "有效期" in visible
    assert "设备编号" in visible
    assert not page.verify_button.isHidden()
    assert not page.deactivate_button.isHidden()
    assert page.activate_button.isHidden()


def test_license_settings_trial_and_invalid_copy_is_concise(qtbot):
    trial_page = LicenseSettingsPage(FakeManager(LicenseStatus.TRIAL_ACTIVE))
    invalid_page = LicenseSettingsPage(FakeManager(LicenseStatus.EXPIRED))
    qtbot.addWidget(trial_page)
    qtbot.addWidget(invalid_page)
    assert trial_page.status_title.text() == "免费试用"
    assert "天" in trial_page.validity_value.text()
    assert not trial_page.trial_deadline_value.isHidden()
    assert invalid_page.status_title.text() == "授权已失效"
    assert invalid_page.status_description.text() == "历史查询与视频播放仍可使用，激活后可恢复录制和上传功能。"
    assert invalid_page.verify_button.text() == "重新验证"


def test_restricted_banner_uses_exact_user_copy():
    assert RESTRICTED_LICENSE_BANNER_TEXT == (
        "当前授权已失效，暂时不能开始新的录制或上传任务。查询与播放仍可使用"
    )
    assert not RESTRICTED_LICENSE_BANNER_TEXT.endswith("。")


def test_help_content_covers_current_trial_recording_and_safe_exit(qtbot):
    titles = {title for title, _html in HELP_TABS}
    all_html = " ".join(html for _title, html in HELP_TABS)
    assert {"快速开始", "7天免费试用", "扫码录制", "授权失效", "安全退出"} <= titles
    assert "首次成功开启后的168小时" in all_html
    assert "扫描相同订单号：结束当前录制，不开始新的录制" in all_html
    assert "正在进行的录制会安全完成" in all_html
    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    assert dialog.tabs.count() == len(HELP_TABS)


@pytest.mark.parametrize(
    ("status", "required"),
    [(LicenseStatus.UNLICENSED, False), (LicenseStatus.INVALID_LICENSE, False),
     (LicenseStatus.DEVICE_MISMATCH, False), (LicenseStatus.SERVER_UNAVAILABLE, False),
     (LicenseStatus.TRIAL_PENDING, False), (LicenseStatus.TRIAL_EXPIRED, False),
     (LicenseStatus.ACTIVE, False), (LicenseStatus.OFFLINE_GRACE, False),
     (LicenseStatus.RESTRICTED, False), (LicenseStatus.EXPIRED, False)],
)
def test_startup_activation_routing(status, required):
    assert _license_requires_activation(status) is required


def test_recorder_service_gate_runs_before_camera_or_database(tmp_path, qtbot):
    checked = []
    recorder = RecorderThread(
        config={"current_record_type": "发货"},
        base_dir=tmp_path,
        logger=__import__("logging").getLogger("test"),
        db_path=tmp_path / "never-created.db",
        recording_permission_checker=lambda record_type: checked.append(record_type) or False,
    )
    with qtbot.waitSignal(recorder.warning_message, timeout=1000) as signal:
        recorder._start_recording("ORDER-1")
    assert checked == ["发货"]
    assert "授权" in signal.args[0]
    assert not (tmp_path / "never-created.db").exists()


def test_upload_worker_gate_runs_before_database_connection(tmp_path, qtbot):
    worker = NetdiskUploadWorker(
        config={},
        database_path=tmp_path / "never-created.db",
        video_root=tmp_path,
        entries=[{"file_path": str(tmp_path / "video.mp4")}],
        permission_checker=lambda: False,
    )
    with qtbot.waitSignal(worker.finished_summary, timeout=1000) as signal:
        worker.run()
    assert signal.args == [0, 0]
    assert not (tmp_path / "never-created.db").exists()
