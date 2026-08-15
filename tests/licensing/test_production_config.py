import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.licensing.constants import (
    PRODUCTION_LICENSE_API_BASE_URL,
    PRODUCTION_LICENSE_KEY_ID,
    license_api_base_url,
    license_environment,
    trusted_public_keys_resource,
)
from app.licensing.license_crypto import TrustedPublicKeys
from app.utils.runtime_paths import resource_path
from scripts.check_production_license_config import validate


def test_environment_selects_separate_production_public_keys(monkeypatch):
    monkeypatch.setenv("DDREC_LICENSE_ENVIRONMENT", "production")
    assert trusted_public_keys_resource().endswith("public_keys.production.json")
    monkeypatch.setenv("DDREC_LICENSE_ENVIRONMENT", "staging")
    assert trusted_public_keys_resource().endswith("public_keys.staging.json")
    monkeypatch.setenv("DDREC_LICENSE_ENVIRONMENT", "development")
    assert trusted_public_keys_resource().endswith("public_keys.json")


def test_unknown_environment_does_not_reuse_another_trust_store(monkeypatch):
    monkeypatch.setenv("DDREC_LICENSE_ENVIRONMENT", "test")
    with pytest.raises(ValueError, match="Unsupported license environment"):
        trusted_public_keys_resource()


def test_staging_and_production_trust_stores_are_isolated():
    root = Path(__file__).parents[2] / "app" / "assets" / "license"
    staging = (root / "public_keys.staging.json").read_text(encoding="utf-8")
    production = (root / "public_keys.production.json").read_text(encoding="utf-8")
    assert "staging-local-1" in staging
    assert "staging-local-1" not in production


def test_client_license_resources_do_not_contain_private_keys():
    root = Path(__file__).parents[2] / "app" / "assets" / "license"
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        assert "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore")


def test_production_public_key_pem_matches_registry():
    root = Path(__file__).parents[2] / "app" / "assets" / "license"
    pem_path = root / "production_ed25519_public.pem"
    registry_path = root / "public_keys.production.json"
    loaded = serialization.load_pem_public_key(pem_path.read_bytes())
    assert isinstance(loaded, Ed25519PublicKey)
    raw = loaded.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = next(item for item in registry["keys"] if item["keyId"] == PRODUCTION_LICENSE_KEY_ID)
    assert entry == {
        "keyId": PRODUCTION_LICENSE_KEY_ID,
        "algorithm": "Ed25519",
        "publicKey": encoded,
    }
    trusted = TrustedPublicKeys.from_json_file(registry_path, expected_environment="production")
    assert trusted.get(PRODUCTION_LICENSE_KEY_ID) == raw


def test_frozen_client_ignores_environment_overrides(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("DDREC_LICENSE_API_BASE_URL", "http://127.0.0.1:8000/api/v1")
    monkeypatch.setenv("DDREC_LICENSE_ENVIRONMENT", "development")
    assert license_api_base_url() == PRODUCTION_LICENSE_API_BASE_URL
    assert license_environment() == "production"
    assert trusted_public_keys_resource().endswith("public_keys.production.json")


def test_pyinstaller_resource_path_can_find_production_public_key(tmp_path: Path, monkeypatch):
    relative = Path("app/assets/license/production_ed25519_public.pem")
    packaged = tmp_path / relative
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes((Path(__file__).parents[2] / relative).read_bytes())
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_path(relative) == packaged.resolve()
    assert resource_path(relative).is_file()


def test_production_check_rejects_http_and_placeholder_key_file(tmp_path: Path):
    keys = tmp_path / "keys.json"
    keys.write_text('{"keys": []}', encoding="utf-8")
    errors = validate("http://license.example.test/api/v1", keys)
    assert any("HTTPS" in error for error in errors)
    assert any("empty" in error for error in errors)


def test_production_check_accepts_committed_public_key():
    root = Path(__file__).parents[2] / "app" / "assets" / "license"
    assert validate(
        PRODUCTION_LICENSE_API_BASE_URL,
        root / "public_keys.production.json",
        root / "production_ed25519_public.pem",
    ) == []
