from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any


LICENSE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LICENSE_PATTERN = re.compile(r"^PMS-(?:[A-HJ-KM-NP-Z2-9]{4}-){3}[A-HJ-KM-NP-Z2-9]{4}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def normalize_license_code(value: str) -> str:
    return value.strip().upper()


def validate_license_code(value: str) -> str:
    normalized = normalize_license_code(value)
    if not LICENSE_PATTERN.fullmatch(normalized):
        raise ValueError("invalid PMSystem license code format")
    return normalized


def generate_license_code() -> str:
    groups = ["".join(secrets.choice(LICENSE_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "PMS-" + "-".join(groups)


def mask_license_code(value: str) -> str:
    normalized = normalize_license_code(value)
    final_group = normalized.rsplit("-", 1)[-1] if "-" in normalized else "????"
    return f"PMS-****-****-****-{final_group[-4:]}"


def hmac_sha256_hex(value: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_license_code(value: str, pepper: str) -> str:
    return hmac_sha256_hex(validate_license_code(value), pepper)


def generate_device_credential() -> str:
    return base64url_encode(secrets.token_bytes(32))


def hash_device_credential(value: str, pepper: str) -> str:
    return hmac_sha256_hex(value, pepper)


def credential_matches(value: str, expected_hash: str, pepper: str) -> bool:
    actual = hash_device_credential(value, pepper)
    return hmac.compare_digest(actual, expected_hash)


def request_payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def device_id_prefix(device_id: str) -> str:
    return device_id[:8]

