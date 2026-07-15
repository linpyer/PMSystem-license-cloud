from __future__ import annotations

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing.constants import LicenseStatus
from app.licensing.device_fingerprint import DeviceIdentity
from app.licensing.errors import LicenseApiError, LicenseValidationError
from app.licensing.license_crypto import LicenseVerifier
from app.licensing.license_manager import LicenseManager
from app.licensing.models import LocalLicenseRecord
from tests.licensing.helpers import DEVICE_ID, LICENSE_ID, NOW, signed_envelope, trusted_keys


class MemoryStorage:
    def __init__(self, value=None):
        self.value = value
        self.save_count = 0
        self.delete_count = 0

    def load(self):
        return self.value

    def save(self, value):
        self.value = value
        self.save_count += 1

    def delete(self):
        self.value = None
        self.delete_count += 1


class FixedFingerprint:
    def collect(self):
        return DeviceIdentity(DEVICE_ID, "win-v1", "Test PC", "Windows 11")


class FakeApi:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def _result(self, name):
        self.calls.append(name)
        if self.error:
            raise self.error
        return self.response

    def activate(self, code, identity): return self._result("activate")
    def verify(self, record): return self._result("verify")
    def refresh(self, record): return self._result("refresh")
    def deactivate(self, record, reason): return self._result("deactivate")


def license_response(private_key, **overrides):
    return {
        "success": True,
        "credential": "c" * 48,
        "license": signed_envelope(private_key, **overrides).as_dict(),
    }


def manager(private_key, *, storage=None, api=None, now=NOW):
    return LicenseManager(
        storage=storage or MemoryStorage(),
        api=api or FakeApi(),
        verifier=LicenseVerifier(trusted_keys(private_key)),
        fingerprint_provider=FixedFingerprint(),
        clock=lambda: now,
    )


def local_record(private_key, **overrides):
    return LocalLicenseRecord(
        1, LICENSE_ID, DEVICE_ID, "win-v1", signed_envelope(private_key, **overrides),
        "c" * 48, NOW, NOW,
    )


def test_initialize_without_license_is_unlicensed(private_key):
    instance = manager(private_key, storage=MemoryStorage())
    assert instance.initialize() is LicenseStatus.UNLICENSED


def test_valid_local_license_enters_active(private_key):
    instance = manager(private_key, storage=MemoryStorage(local_record(private_key)))
    assert instance.initialize() is LicenseStatus.ACTIVE


def test_invalid_local_signature_fails_closed(private_key):
    other_key = Ed25519PrivateKey.generate()
    instance = manager(private_key, storage=MemoryStorage(local_record(other_key)))
    assert instance.initialize() is LicenseStatus.INVALID_LICENSE


def test_activation_verifies_before_atomic_storage(private_key):
    storage = MemoryStorage()
    api = FakeApi(license_response(private_key))
    instance = manager(private_key, storage=storage, api=api)
    instance.initialize()
    assert instance.activate("PMS-2345-6789-ABCD-EFGH") is LicenseStatus.ACTIVE
    assert storage.save_count == 1 and storage.value.credential == "c" * 48


def test_activation_with_invalid_signature_does_not_replace_storage(private_key):
    storage = MemoryStorage()
    api = FakeApi(license_response(Ed25519PrivateKey.generate()))
    instance = manager(private_key, storage=storage, api=api)
    instance.initialize()
    with pytest.raises(LicenseValidationError):
        instance.activate("PMS-2345-6789-ABCD-EFGH")
    assert storage.value is None and storage.save_count == 0


def test_verify_success_updates_license(private_key):
    storage = MemoryStorage(local_record(private_key))
    api = FakeApi(license_response(private_key))
    instance = manager(private_key, storage=storage, api=api)
    instance.initialize()
    assert instance.verify_online() is LicenseStatus.ACTIVE
    assert api.calls == ["verify"] and storage.save_count >= 2


def test_server_unavailable_uses_valid_local_policy(private_key):
    storage = MemoryStorage(local_record(private_key, lastVerifiedAt=(NOW - timedelta(days=8)).isoformat()))
    api = FakeApi(error=LicenseApiError("SERVER_TEMPORARILY_UNAVAILABLE", "offline", True))
    instance = manager(private_key, storage=storage, api=api)
    assert instance.initialize() is LicenseStatus.OFFLINE_GRACE
    assert instance.verify_online() is LicenseStatus.OFFLINE_GRACE


@pytest.mark.parametrize(
    ("code", "status"),
    [("LICENSE_EXPIRED", LicenseStatus.EXPIRED), ("LICENSE_DISABLED", LicenseStatus.DISABLED),
     ("LICENSE_REVOKED", LicenseStatus.REVOKED), ("DEVICE_MISMATCH", LicenseStatus.DEVICE_MISMATCH)],
)
def test_authoritative_server_status_restricts_client(private_key, code, status):
    storage = MemoryStorage(local_record(private_key))
    instance = manager(
        private_key, storage=storage,
        api=FakeApi(error=LicenseApiError(code, "denied")),
    )
    instance.initialize()
    assert instance.verify_online() is status
    assert not instance.can_start_recording()
    restarted = manager(private_key, storage=storage, api=FakeApi())
    assert restarted.initialize() is status


def test_successful_deactivation_removes_only_local_license(private_key):
    storage = MemoryStorage(local_record(private_key))
    instance = manager(private_key, storage=storage, api=FakeApi({"success": True, "deactivated": True}))
    instance.initialize()
    assert instance.deactivate() is LicenseStatus.UNLICENSED
    assert storage.delete_count == 1 and storage.value is None


def test_failed_deactivation_preserves_local_license(private_key):
    original = local_record(private_key)
    storage = MemoryStorage(original)
    instance = manager(
        private_key, storage=storage,
        api=FakeApi(error=LicenseApiError("SERVER_TEMPORARILY_UNAVAILABLE", "offline", True)),
    )
    instance.initialize()
    with pytest.raises(LicenseApiError):
        instance.deactivate()
    assert storage.delete_count == 0 and storage.value is not None
