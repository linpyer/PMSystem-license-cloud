from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing.license_crypto import TrustedPublicKeys
from app.licensing.models import LicensePayload, SignedLicense


UTC = timezone.utc
NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
DEVICE_ID = "a" * 64
LICENSE_ID = "11111111-1111-4111-8111-111111111111"
KEY_ID = "test-key"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def payload_dict(**overrides):
    value = {
        "schemaVersion": 1,
        "licenseId": LICENSE_ID,
        "product": "DDREC",
        "edition": "professional",
        "deviceId": DEVICE_ID,
        "fingerprintVersion": "win-v1",
        "licenseType": "monthly",
        "issuedAt": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "expiresAt": (NOW + timedelta(days=29)).isoformat().replace("+00:00", "Z"),
        "lastVerifiedAt": NOW.isoformat().replace("+00:00", "Z"),
        "nextRequiredVerifyAt": (NOW + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "graceUntil": (NOW + timedelta(days=21)).isoformat().replace("+00:00", "Z"),
        "features": ["recording", "videoQuery", "statistics", "netdiskSync"],
        "keyId": KEY_ID,
        "nonce": "test-nonce",
    }
    value.update(overrides)
    return value


def signed_envelope(private_key: Ed25519PrivateKey, **overrides) -> SignedLicense:
    payload = json.dumps(
        payload_dict(**overrides), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return SignedLicense(
        payload=b64url(payload),
        signature=b64url(private_key.sign(payload)),
        key_id=KEY_ID,
        algorithm="Ed25519",
    )


def trusted_keys(private_key: Ed25519PrivateKey) -> TrustedPublicKeys:
    return TrustedPublicKeys({KEY_ID: private_key.public_key().public_bytes_raw()})


def policy_payload(*, verified_at: datetime = NOW, expires_at=None) -> LicensePayload:
    return LicensePayload(
        schema_version=1,
        license_id=LICENSE_ID,
        product="DDREC",
        edition="professional",
        device_id=DEVICE_ID,
        fingerprint_version="win-v1",
        license_type="permanent" if expires_at is None else "monthly",
        issued_at=NOW - timedelta(days=1),
        expires_at=expires_at,
        last_verified_at=verified_at,
        next_required_verify_at=verified_at + timedelta(days=7),
        grace_until=verified_at + timedelta(days=21),
        features=("recording",),
        key_id=KEY_ID,
        nonce="nonce",
    )
