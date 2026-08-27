from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).parents[1] / "scripts/release/migrate_update_signing_key.py"
SPEC = importlib.util.spec_from_file_location("migrate_update_signing_key", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def key_files(root: Path):
    private = Ed25519PrivateKey.generate()
    source = root / "legacy/key.pem"
    target = root / "current/key.pem"
    public = root / "public.pem"
    source.parent.mkdir(parents=True)
    source.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return source, target, public


def test_dry_run_is_strictly_zero_write(tmp_path):
    source, target, public = key_files(tmp_path)
    result = module.audit_key_migration(source, target, public)
    assert result.action == "COPY_REQUIRED"
    assert result.source_fingerprint_matches_public_key == "PASS"
    assert not target.exists() and not target.parent.exists()


def test_execute_preserves_bytes_and_fingerprint(tmp_path):
    source, target, public = key_files(tmp_path)
    result = module.migrate_key(source, target, public)
    assert result.action == "ALREADY_CURRENT"
    assert result.byte_equality == "PASS"
    assert result.target_fingerprint_matches_public_key == "PASS"
    assert target.read_bytes() == source.read_bytes()


def test_existing_different_target_fails_closed(tmp_path):
    source, target, public = key_files(tmp_path)
    target.parent.mkdir(parents=True)
    other = Ed25519PrivateKey.generate()
    target.write_bytes(
        other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    original = target.read_bytes()
    with pytest.raises(RuntimeError, match="TARGET_CONFLICT_FAIL_CLOSED"):
        module.migrate_key(source, target, public)
    assert target.read_bytes() == original
