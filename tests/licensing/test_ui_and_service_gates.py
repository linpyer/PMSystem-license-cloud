from __future__ import annotations

from datetime import timedelta

import pytest
from PySide6.QtCore import QObject, Signal

from app.core.netdisk_sync import NetdiskUploadWorker
from app.core.recorder import RecorderThread
from app.licensing.constants import LicenseStatus
from app.ui.activation_dialog import ActivationDialog
from app.ui.license_settings_page import LicenseSettingsPage
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
        return {
            "status": self.status,
            "licenseId": LICENSE_ID,
            "licenseType": "monthly",
            "edition": "professional",
            "expiresAt": NOW + timedelta(days=30),
            "lastVerifiedAt": NOW,
            "nextRequiredVerifyAt": NOW + timedelta(days=7),
            "graceUntil": NOW + timedelta(days=21),
            "deviceId": DEVICE_ID,
            "fingerprintVersion": "win-v1",
            "serverReachable": True,
            "lastErrorCode": "",
        }

    def activate(self, code):
        self.activate_calls.append(code)
        self.status = LicenseStatus.ACTIVE
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


@pytest.mark.parametrize(
    ("status", "required"),
    [(LicenseStatus.UNLICENSED, True), (LicenseStatus.INVALID_LICENSE, True),
     (LicenseStatus.DEVICE_MISMATCH, True), (LicenseStatus.SERVER_UNAVAILABLE, True),
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
