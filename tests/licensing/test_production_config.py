from pathlib import Path

import pytest

from app.licensing.constants import trusted_public_keys_resource
from scripts.check_production_license_config import validate


def test_environment_selects_separate_production_public_keys(monkeypatch):
    monkeypatch.setenv("PMSYSTEM_LICENSE_ENVIRONMENT", "production")
    assert trusted_public_keys_resource().endswith("public_keys.production.json")
    monkeypatch.setenv("PMSYSTEM_LICENSE_ENVIRONMENT", "staging")
    assert trusted_public_keys_resource().endswith("public_keys.staging.json")
    monkeypatch.setenv("PMSYSTEM_LICENSE_ENVIRONMENT", "development")
    assert trusted_public_keys_resource().endswith("public_keys.json")


def test_unknown_environment_does_not_reuse_another_trust_store(monkeypatch):
    monkeypatch.setenv("PMSYSTEM_LICENSE_ENVIRONMENT", "test")
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
        assert path.suffix.lower() not in {".pem", ".key"}
        assert "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore")


def test_production_check_rejects_http_and_placeholder_key_file(tmp_path: Path):
    keys = tmp_path / "keys.json"
    keys.write_text('{"keys": []}', encoding="utf-8")
    errors = validate("http://license.example.test/api/v1", keys)
    assert any("HTTPS" in error for error in errors)
    assert any("empty" in error for error in errors)
