from __future__ import annotations

import sys
from datetime import timedelta

import pytest

from app.licensing.dpapi_storage import WindowsDpapiProtector
from app.licensing.errors import LicenseStorageError
from app.licensing.license_storage import LicenseStorage, default_license_path
from app.licensing.models import LocalLicenseRecord
from tests.licensing.helpers import DEVICE_ID, LICENSE_ID, NOW, signed_envelope


class ReversibleProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return b"PROTECTED:" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"PROTECTED:"):
            raise ValueError("not protected")
        return ciphertext.removeprefix(b"PROTECTED:")[::-1]


def record(private_key, credential="credential-secret-value"):
    return LocalLicenseRecord(
        1, LICENSE_ID, DEVICE_ID, "win-v1", signed_envelope(private_key), credential,
        NOW, NOW - timedelta(minutes=1),
    )


def test_missing_file_returns_none(tmp_path):
    assert LicenseStorage(tmp_path / "license.dat", protector=ReversibleProtector()).load() is None


def test_save_and_load_round_trip(tmp_path, private_key):
    storage = LicenseStorage(tmp_path / "license.dat", protector=ReversibleProtector())
    storage.save(record(private_key))
    loaded = storage.load()
    assert loaded and loaded.license_id == LICENSE_ID and loaded.credential == "credential-secret-value"


def test_stored_bytes_do_not_contain_credential(tmp_path, private_key):
    storage = LicenseStorage(tmp_path / "license.dat", protector=ReversibleProtector())
    storage.save(record(private_key, "highly-sensitive-credential"))
    assert b"highly-sensitive-credential" not in storage.path.read_bytes()


def test_corrupt_file_is_isolated(tmp_path):
    path = tmp_path / "license.dat"
    path.write_bytes(b"corrupt")
    with pytest.raises(LicenseStorageError):
        LicenseStorage(path, protector=ReversibleProtector()).load()
    assert not path.exists() and len(list(tmp_path.glob("license.dat.corrupt-*"))) == 1


def test_failed_atomic_save_preserves_existing_file(tmp_path, private_key, monkeypatch):
    storage = LicenseStorage(tmp_path / "license.dat", protector=ReversibleProtector())
    storage.save(record(private_key, "old-credential"))
    original = storage.path.read_bytes()
    monkeypatch.setattr("app.licensing.license_storage.os.replace", lambda *_: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(LicenseStorageError):
        storage.save(record(private_key, "new-credential"))
    assert storage.path.read_bytes() == original


def test_delete_only_removes_license_file(tmp_path, private_key):
    storage = LicenseStorage(tmp_path / "license" / "license.dat", protector=ReversibleProtector())
    unrelated_db, video = tmp_path / "data" / "pmsystem.db", tmp_path / "videos" / "recording.mp4"
    unrelated_db.parent.mkdir(); video.parent.mkdir()
    unrelated_db.write_bytes(b"database"); video.write_bytes(b"video")
    storage.save(record(private_key)); storage.delete()
    assert not storage.path.exists()
    assert unrelated_db.read_bytes() == b"database" and video.read_bytes() == b"video"


def test_frozen_client_ignores_storage_path_override(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PMSYSTEM_LICENSE_STORAGE_PATH", str(tmp_path / "redirected.dat"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    assert default_license_path() == tmp_path / "local-app-data" / "PMSystem" / "license" / "license.dat"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI is only available on Windows")
def test_windows_dpapi_round_trip():
    plaintext = b"credential-and-license"
    encrypted = WindowsDpapiProtector().protect(plaintext)
    assert encrypted != plaintext and plaintext not in encrypted
    assert WindowsDpapiProtector().unprotect(encrypted) == plaintext
