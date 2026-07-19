from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _values(database_url: str, environment: str = "test") -> dict:
    return {
        "LICENSE_DATABASE_URL": database_url,
        "LICENSE_ENVIRONMENT": environment,
        "LICENSE_SIGNING_PRIVATE_KEY_PATH": Path("test.pem"),
        "LICENSE_SIGNING_KEY_ID": "test-key",
        "LICENSE_CODE_PEPPER": "code-pepper-longer-than-twenty-four",
        "LICENSE_DEVICE_CREDENTIAL_PEPPER": "device-pepper-longer-than-twenty-four",
    }


def test_sqlite_database_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(_values("sqlite+aiosqlite:///pm_system.db"))


def test_test_mode_requires_test_database_suffix() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            _values("postgresql+asyncpg://user:pass@localhost/pmsystem_license_dev")
        )


def test_dedicated_test_database_is_accepted() -> None:
    settings = Settings.model_validate(
        _values("postgresql+asyncpg://user:pass@localhost/pmsystem_license_test")
    )
    assert settings.environment == "test"
    assert settings.database_url.endswith("pmsystem_license_test")


def _production_values() -> dict:
    values = _values(
        "postgresql+asyncpg://app:secret@postgres/pmsystem_license_prod",
        environment="production",
    )
    values.update(
        LICENSE_OPENAPI_ENABLED=False,
        LICENSE_ADMIN_COOKIE_SECURE=True,
        LICENSE_ADMIN_SESSION_SECRET="production-session-secret-with-32-characters",
        LICENSE_ADMIN_TOTP_ENCRYPTION_KEY="production-totp-secret-with-32-characters",
        LICENSE_ADMIN_ALLOWED_ORIGINS="https://license.example.test",
        LICENSE_PUBLIC_BASE_URL="https://license.example.test",
        LICENSE_ADMIN_BASE_URL="https://license.example.test/admin/",
        LICENSE_ALLOWED_HOSTS="license.example.test",
    )
    return values


def test_production_configuration_accepts_only_hardened_values() -> None:
    settings = Settings.model_validate(_production_values())
    assert settings.environment == "production"
    assert settings.admin_cookie_secure is True
    assert settings.openapi_enabled is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LICENSE_OPENAPI_ENABLED", True),
        ("LICENSE_ADMIN_COOKIE_SECURE", False),
        ("LICENSE_PUBLIC_BASE_URL", "http://license.example.test"),
        ("LICENSE_ALLOWED_HOSTS", "*"),
        ("LICENSE_ADMIN_ALLOWED_ORIGINS", "*"),
    ],
)
def test_production_configuration_rejects_unsafe_values(key: str, value) -> None:
    values = _production_values()
    values[key] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(values)
