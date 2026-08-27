from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


LEGACY_KEY_RELATIVE_PATH = Path(".ddrec/keys/DDREC-update-ed25519-private.pem")
CURRENT_KEY_RELATIVE_PATH = Path(".ivrec/keys/iVRec-update-ed25519-private.pem")


@dataclass(frozen=True, slots=True)
class KeyMigrationAudit:
    mode: str
    source_exists: bool
    target_exists: bool
    byte_equality: str
    source_fingerprint_matches_public_key: str
    target_fingerprint_matches_public_key: str
    action: str


def _private_public_fingerprint(raw: bytes) -> bytes:
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("update signing private key is not Ed25519")
    return hashlib.sha256(key.public_key().public_bytes_raw()).digest()


def _public_fingerprint(path: Path) -> bytes:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("update signing public key is not Ed25519")
    return hashlib.sha256(key.public_bytes_raw()).digest()


def audit_key_migration(source: Path, target: Path, public_key: Path) -> KeyMigrationAudit:
    source_exists = source.is_file()
    target_exists = target.is_file()
    expected = _public_fingerprint(public_key)
    source_raw = source.read_bytes() if source_exists else None
    target_raw = target.read_bytes() if target_exists else None
    source_match = (
        "PASS" if source_raw is not None and _private_public_fingerprint(source_raw) == expected
        else "FAIL" if source_raw is not None
        else "NOT_APPLICABLE"
    )
    target_match = (
        "PASS" if target_raw is not None and _private_public_fingerprint(target_raw) == expected
        else "FAIL" if target_raw is not None
        else "NOT_APPLICABLE"
    )
    equality = (
        "PASS" if source_raw is not None and target_raw is not None and source_raw == target_raw
        else "FAIL" if source_raw is not None and target_raw is not None
        else "NOT_APPLICABLE"
    )
    if not source_exists:
        action = "SOURCE_MISSING"
    elif source_match != "PASS":
        action = "SOURCE_FINGERPRINT_MISMATCH"
    elif target_exists and equality == "PASS" and target_match == "PASS":
        action = "ALREADY_CURRENT"
    elif target_exists:
        action = "TARGET_CONFLICT_FAIL_CLOSED"
    else:
        action = "COPY_REQUIRED"
    return KeyMigrationAudit(
        mode="DRY_RUN",
        source_exists=source_exists,
        target_exists=target_exists,
        byte_equality=equality,
        source_fingerprint_matches_public_key=source_match,
        target_fingerprint_matches_public_key=target_match,
        action=action,
    )


def migrate_key(source: Path, target: Path, public_key: Path) -> KeyMigrationAudit:
    audit = audit_key_migration(source, target, public_key)
    if audit.action == "ALREADY_CURRENT":
        return KeyMigrationAudit(**{**asdict(audit), "mode": "EXECUTE"})
    if audit.action != "COPY_REQUIRED":
        raise RuntimeError(f"signing key migration stopped: {audit.action}")
    raw = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            raise FileExistsError("target appeared during migration")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    verified = audit_key_migration(source, target, public_key)
    if verified.action != "ALREADY_CURRENT":
        raise RuntimeError("copied signing key failed byte/fingerprint verification")
    return KeyMigrationAudit(**{**asdict(verified), "mode": "EXECUTE"})


def _default_public_key() -> Path:
    return Path(__file__).resolve().parents[3] / "client/app/assets/update/update_ed25519_public.pem"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or safely copy the iVRec update signing key")
    parser.add_argument("--source", type=Path, default=Path.home() / LEGACY_KEY_RELATIVE_PATH)
    parser.add_argument("--target", type=Path, default=Path.home() / CURRENT_KEY_RELATIVE_PATH)
    parser.add_argument("--public-key", type=Path, default=_default_public_key())
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = (
        migrate_key(args.source, args.target, args.public_key)
        if args.execute
        else audit_key_migration(args.source, args.target, args.public_key)
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.action in {"COPY_REQUIRED", "ALREADY_CURRENT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
