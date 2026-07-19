from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.licensing.constants import (
    FINGERPRINT_VERSION,
    LICENSE_EDITION,
    LICENSE_PRODUCT,
    SUPPORTED_SCHEMA_VERSIONS,
)
from app.licensing.errors import LicenseValidationError
from app.licensing.models import LicensePayload, SignedLicense


UNKNOWN_SIGNING_KEY_MESSAGE = (
    "当前客户端不信任授权服务器使用的签名密钥，请更新客户端授权公钥配置。"
)
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def base64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise LicenseValidationError("Invalid Base64URL value") from exc


class TrustedPublicKeys:
    def __init__(self, keys: dict[str, bytes]) -> None:
        self._keys = dict(keys)

    @classmethod
    def from_json_file(
        cls,
        path: str | Path,
        *,
        expected_environment: str | None = None,
    ) -> "TrustedPublicKeys":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("trusted public key document must be an object")
            configured_environment = str(raw.get("environment") or "").strip().lower()
            if expected_environment and configured_environment != expected_environment.lower():
                raise ValueError("trusted public key environment does not match the client")
            items = raw.get("keys", [])
            if not isinstance(items, list):
                raise TypeError("trusted public keys must be a list")
            keys: dict[str, bytes] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError("trusted public key entry must be an object")
                if str(item.get("algorithm") or "") != "Ed25519":
                    raise ValueError("trusted public key algorithm must be Ed25519")
                key_id = str(item.get("keyId") or "")
                encoded_key = str(item.get("publicKey") or "")
                if not key_id or key_id in keys:
                    raise ValueError("trusted public keyId is missing or duplicated")
                if not _BASE64URL_PATTERN.fullmatch(encoded_key):
                    raise ValueError("trusted public key must use unpadded Base64URL")
                public_key = base64url_decode(encoded_key)
                if len(public_key) != 32:
                    raise ValueError("Ed25519 public key must contain 32 bytes")
                keys[key_id] = public_key
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LicenseValidationError("Unable to load trusted license public keys") from exc
        if not keys:
            raise LicenseValidationError("No trusted Ed25519 public keys are configured")
        return cls(keys)

    def get(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))


class LicenseVerifier:
    def __init__(self, trusted_keys: TrustedPublicKeys) -> None:
        self.trusted_keys = trusted_keys

    def verify(self, envelope: SignedLicense, *, expected_device_id: str) -> LicensePayload:
        if envelope.algorithm != "Ed25519":
            raise LicenseValidationError("Unsupported license signature algorithm")
        public_key_bytes = self.trusted_keys.get(envelope.key_id)
        if public_key_bytes is None:
            raise LicenseValidationError(UNKNOWN_SIGNING_KEY_MESSAGE)
        try:
            payload_bytes = base64url_decode(envelope.payload)
            signature_bytes = base64url_decode(envelope.signature)
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature_bytes, payload_bytes
            )
        except (InvalidSignature, ValueError) as exc:
            raise LicenseValidationError("License signature verification failed") from exc
        try:
            raw: Any = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LicenseValidationError("License payload is not valid UTF-8 JSON") from exc
        if not isinstance(raw, dict):
            raise LicenseValidationError("License payload must be a JSON object")
        payload = LicensePayload.from_mapping(raw)
        if payload.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise LicenseValidationError("Unsupported license schema version")
        if payload.product != LICENSE_PRODUCT:
            raise LicenseValidationError("License product does not match PMSystem")
        if payload.edition != LICENSE_EDITION:
            raise LicenseValidationError("License edition is not professional")
        if payload.device_id != expected_device_id:
            raise LicenseValidationError("License device does not match this computer")
        if payload.fingerprint_version != FINGERPRINT_VERSION:
            raise LicenseValidationError("Unsupported device fingerprint version")
        if payload.key_id != envelope.key_id:
            raise LicenseValidationError("License keyId does not match its envelope")
        if not payload.license_id or not payload.nonce:
            raise LicenseValidationError("License identity fields are incomplete")
        return payload
