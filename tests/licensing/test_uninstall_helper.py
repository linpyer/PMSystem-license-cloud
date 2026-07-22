from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.licensing.models import LocalLicenseRecord, SignedLicense
from app.licensing.uninstall_helper import (
    MAX_UNINSTALL_WAIT_SECONDS,
    deactivate_before_uninstall,
    main,
)


class IdentityProtector:
    def protect(self, value: bytes) -> bytes:
        return value

    def unprotect(self, value: bytes) -> bytes:
        return value


class FakeApi:
    def __init__(self, deactivated: bool) -> None:
        self.deactivated = deactivated
        self.calls = 0

    def deactivate(self, record, reason: str):
        self.calls += 1
        assert record.credential == "credential-value"
        assert reason == "uninstall"
        return {"success": True, "deactivated": self.deactivated}


def write_record(path: Path) -> None:
    now = datetime.now(timezone.utc)
    record = LocalLicenseRecord(
        schema_version=1,
        license_id="license-id",
        device_id="device-id",
        fingerprint_version="win-v1",
        signed_license=SignedLicense("payload", "signature", "key-id", "Ed25519"),
        credential="credential-value",
        saved_at=now,
        last_seen_utc=now,
    )
    path.write_text(json.dumps(record.as_dict()), encoding="utf-8")


def test_confirmed_deactivation_removes_only_license_file(tmp_path: Path):
    path = tmp_path / "license.dat"
    sibling = tmp_path / "business.db"
    write_record(path)
    sibling.write_text("unchanged", encoding="utf-8")
    api = FakeApi(True)
    assert deactivate_before_uninstall(path=path, protector=IdentityProtector(), api=api)
    assert not path.exists()
    assert sibling.read_text(encoding="utf-8") == "unchanged"


def test_failed_deactivation_preserves_license_file(tmp_path: Path):
    path = tmp_path / "license.dat"
    write_record(path)
    assert not deactivate_before_uninstall(
        path=path,
        protector=IdentityProtector(),
        api=FakeApi(False),
    )
    assert path.is_file()


def test_damaged_license_is_not_renamed_or_deleted(tmp_path: Path):
    path = tmp_path / "license.dat"
    path.write_bytes(b"not-json")
    assert not deactivate_before_uninstall(
        path=path,
        protector=IdentityProtector(),
        api=FakeApi(True),
    )
    assert path.read_bytes() == b"not-json"
    assert list(tmp_path.iterdir()) == [path]


def test_helper_requires_explicit_uninstall_switch():
    assert main([]) == 0


def test_helper_network_wait_leaves_startup_time_inside_eight_second_limit():
    assert MAX_UNINSTALL_WAIT_SECONDS <= 6.0
