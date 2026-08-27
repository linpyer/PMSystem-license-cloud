from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.core.signing import Ed25519Signer, SignedEnvelope, verify_envelope
from app.db.models import DeviceBinding, License
from app.db.models.enums import BindingStatus, LicenseStatus, LicenseType
from app.services.license_signing_service import LicenseSigningService


class MemorySigningKeyRepository:
    async def ensure_active_key(self, *_args, **_kwargs):
        return None


def test_ed25519_envelope_round_trip() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "test-key")
    envelope = signer.sign({"schemaVersion": 1, "licenseId": "abc", "deviceId": "device"})
    decoded = verify_envelope(envelope, signer.public_key_base64url)
    assert decoded["licenseId"] == "abc"
    assert envelope.algorithm == "Ed25519"


def test_tampered_payload_fails_signature_verification() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "test-key")
    envelope = signer.sign({"licenseId": "original"})
    tampered = SignedEnvelope(
        payload=envelope.payload[:-1] + ("A" if envelope.payload[-1] != "A" else "B"),
        signature=envelope.signature,
        key_id=envelope.key_id,
    )
    with pytest.raises((InvalidSignature, ValueError)):
        verify_envelope(tampered, signer.public_key_base64url)


def test_different_keys_cannot_verify_signature() -> None:
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "key-a")
    other = Ed25519Signer(Ed25519PrivateKey.generate(), "key-b")
    with pytest.raises(InvalidSignature):
        verify_envelope(signer.sign({"licenseId": "abc"}), other.public_key_base64url)


@pytest.mark.asyncio
async def test_new_license_payload_is_signed_for_ivrec_without_changing_device(settings) -> None:
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    signer = Ed25519Signer(Ed25519PrivateKey.generate(), "test-key")
    license_record = License(
        id=uuid4(), license_type=LicenseType.MONTHLY, status=LicenseStatus.ACTIVE,
        max_devices=1, valid_days=30, activated_at=now, expires_at=None,
    )
    binding = DeviceBinding(
        id=uuid4(), license_id=license_record.id, device_id="existing-device-id",
        fingerprint_version="win-v1", app_version="1.4.0", status=BindingStatus.ACTIVE,
        first_activated_at=now, last_verified_at=now, device_credential_hash="hash",
    )
    envelope = await LicenseSigningService(
        settings, signer, repository=MemorySigningKeyRepository()
    ).issue(None, license_record=license_record, binding=binding, now=now)
    payload = verify_envelope(envelope, signer.public_key_base64url)
    assert payload["product"] == "iVRec"
    assert payload["deviceId"] == "existing-device-id"

