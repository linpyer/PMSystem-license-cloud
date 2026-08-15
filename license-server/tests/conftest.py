from __future__ import annotations

import os
from pathlib import Path

import pytest


os.environ.setdefault(
    "LICENSE_DATABASE_URL",
    "postgresql+asyncpg://test:test@127.0.0.1:5434/ddrec_license_test",
)
os.environ.setdefault("LICENSE_ENVIRONMENT", "test")
os.environ.setdefault("LICENSE_SIGNING_PRIVATE_KEY_PATH", str(Path(".secrets/test.pem")))
os.environ.setdefault("LICENSE_SIGNING_KEY_ID", "test-key-1")
os.environ.setdefault("LICENSE_CODE_PEPPER", "unit-test-code-pepper-with-32-characters")
os.environ.setdefault(
    "LICENSE_DEVICE_CREDENTIAL_PEPPER", "unit-test-device-pepper-with-32-characters"
)


@pytest.fixture
def settings():
    from app.core.config import Settings

    return Settings()  # type: ignore[call-arg]
