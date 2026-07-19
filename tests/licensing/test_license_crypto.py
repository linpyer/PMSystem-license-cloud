from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.licensing.errors import LicenseValidationError
from app.licensing.license_crypto import (
    UNKNOWN_SIGNING_KEY_MESSAGE,
    LicenseVerifier,
    TrustedPublicKeys,
    base64url_decode,
)
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
    with pytest.raises(LicenseValidationError, match=UNKNOWN_SIGNING_KEY_MESSAGE):
        LicenseVerifier(TrustedPublicKeys({})).verify(
            signed_envelope(private_key), expected_device_id=DEVICE_ID
        )


def test_key_id_lookup_is_case_sensitive(private_key):
    envelope = signed_envelope(private_key)
    changed_case = SignedLicense(
        envelope.payload,
        envelope.signature,
        envelope.key_id.upper(),
        envelope.algorithm,
    )
    with pytest.raises(LicenseValidationError, match=UNKNOWN_SIGNING_KEY_MESSAGE):
        LicenseVerifier(trusted_keys(private_key)).verify(
            changed_case, expected_device_id=DEVICE_ID
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


def test_trusted_public_key_file_rejects_environment_mismatch(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text(
        json.dumps(
            {
                "environment": "development",
                "keys": [
                    {
                        "keyId": KEY_ID,
                        "algorithm": "Ed25519",
                        "publicKey": "A" * 43,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LicenseValidationError):
        TrustedPublicKeys.from_json_file(path, expected_environment="staging")


def test_trusted_public_key_file_rejects_padded_or_standard_base64(tmp_path):
    for encoded in ("A" * 43 + "=", "+" + "A" * 42):
        path = tmp_path / "keys.json"
        path.write_text(
            json.dumps(
                {
                    "environment": "staging",
                    "keys": [
                        {"keyId": KEY_ID, "algorithm": "Ed25519", "publicKey": encoded}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(LicenseValidationError):
            TrustedPublicKeys.from_json_file(path, expected_environment="staging")


def test_current_staging_key_verifies_server_probe():
    keys_path = (
        Path(__file__).parents[2]
        / "app"
        / "assets"
        / "license"
        / "public_keys.staging.json"
    )
    keys = TrustedPublicKeys.from_json_file(keys_path, expected_environment="staging")
    public_key = keys.get("staging-local-1")
    assert keys.key_ids == ("staging-local-1",)
    assert public_key is not None and len(public_key) == 32
    payload = b'{"probe":"PMSystem-staging-client-trust-v1"}'
    signature = base64url_decode(
        "idMO0314QSVAL0iPPVWw9gsHkVnM8yybgmZIueg9lBI6IKYn-9cNymYr4uT7hh00S9h4tWAl_--8dvlHzsahAA"
    )
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)


def test_wrong_public_key_rejects_staging_probe(private_key):
    payload = b'{"probe":"PMSystem-staging-client-trust-v1"}'
    signature = base64url_decode(
        "idMO0314QSVAL0iPPVWw9gsHkVnM8yybgmZIueg9lBI6IKYn-9cNymYr4uT7hh00S9h4tWAl_--8dvlHzsahAA"
    )
    with pytest.raises(InvalidSignature):
        private_key.public_key().verify(signature, payload)
