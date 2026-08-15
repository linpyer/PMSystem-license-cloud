from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SIGNED_UPDATE_FIELDS = (
    "product", "version", "buildNumber", "edition", "environment",
    "architecture", "channel", "fileName", "fileSize", "sha256", "publishedAt",
)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_update_manifest(values: dict[str, Any]) -> dict[str, Any]:
    return {field: values[field] for field in SIGNED_UPDATE_FIELDS}


def canonical_update_bytes(values: dict[str, Any]) -> bytes:
    return json.dumps(
        canonical_update_manifest(values), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def base64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def load_update_public_key(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("DDREC update public key is not Ed25519")
    return key


def verify_update_signature(values: dict[str, Any], signature: str, public_key_path: Path) -> None:
    key = load_update_public_key(public_key_path)
    key.verify(base64url_decode(signature), canonical_update_bytes(values))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()
