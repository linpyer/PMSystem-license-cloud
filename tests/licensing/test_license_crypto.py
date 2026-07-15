from __future__ import annotations

import base64
import json

import pytest

from app.licensing.errors import LicenseValidationError
from app.licensing.license_crypto import LicenseVerifier, TrustedPublicKeys
from app.licensing.models import SignedLicense
from tests.licensing.helpers import DEVICE_ID, KEY_ID, signed_envelope, trusted_keys


def test_valid_signature_is_accepted(private_key):
    payload = LicenseVerifier(trusted_keys(private_key)).verify(
        signed_envelope(private_key), expected_device_id=DEVICE_ID
    )
    assert payload.device_id == DEVICE_ID


def test_modified_payload_is_rejected(private_key):
    envelope = signed_envelope(private_key)
    raw = bytearray(base64.urlsafe_b64decode(envelope.payload + "=="))
    raw[-2] ^= 1
    modified = SignedLicense(
        base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), envelope.signature,
        envelope.key_id, envelope.algorithm,
    )
    with pytest.raises(LicenseValidationError):
        LicenseVerifier(trusted_keys(private_key)).verify(modified, expected_device_id=DEVICE_ID)


def test_modified_signature_is_rejected(private_key):
    envelope = signed_envelope(private_key)
    signature = bytearray(base64.urlsafe_b64decode(envelope.signature + "=="))
    signature[0] ^= 1
    modified = SignedLicense(
        envelope.payload, base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
        envelope.key_id, envelope.algorithm,
    )
    with pytest.raises(LicenseValidationError):
        LicenseVerifier(trusted_keys(private_key)).verify(modified, expected_device_id=DEVICE_ID)


def test_unknown_key_is_rejected(private_key):
    with pytest.raises(LicenseValidationError, match="Unknown"):
        LicenseVerifier(TrustedPublicKeys({})).verify(
            signed_envelope(private_key), expected_device_id=DEVICE_ID
        )


def test_wrong_algorithm_is_rejected(private_key):
    envelope = signed_envelope(private_key)
    wrong = SignedLicense(envelope.payload, envelope.signature, envelope.key_id, "RSA")
    with pytest.raises(LicenseValidationError, match="algorithm"):
        LicenseVerifier(trusted_keys(private_key)).verify(wrong, expected_device_id=DEVICE_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [("product", "OtherProduct"), ("edition", "community"), ("deviceId", "b" * 64),
     ("fingerprintVersion", "win-v2"), ("schemaVersion", 99), ("keyId", "different-key")],
)
def test_invalid_payload_identity_is_rejected(private_key, field, value):
    with pytest.raises(LicenseValidationError):
        LicenseVerifier(trusted_keys(private_key)).verify(
            signed_envelope(private_key, **{field: value}), expected_device_id=DEVICE_ID
        )


@pytest.mark.parametrize("field", ["issuedAt", "lastVerifiedAt", "nextRequiredVerifyAt", "graceUntil"])
def test_invalid_utc_timestamp_is_rejected(private_key, field):
    with pytest.raises(LicenseValidationError):
        LicenseVerifier(trusted_keys(private_key)).verify(
            signed_envelope(private_key, **{field: "2026-07-15 08:00:00"}),
            expected_device_id=DEVICE_ID,
        )


def test_trusted_public_key_file_requires_ed25519_key(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"keys": [{"keyId": KEY_ID, "algorithm": "RSA", "publicKey": "AA"}]}))
    with pytest.raises(LicenseValidationError):
        TrustedPublicKeys.from_json_file(path)
