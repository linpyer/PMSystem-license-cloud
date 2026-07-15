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

