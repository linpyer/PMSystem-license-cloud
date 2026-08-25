from __future__ import annotations

import pytest

from tests.postgres_guard import PostgresTestDatabaseNotConfigured, validate_postgres_test_url


def test_missing_integration_database_is_not_guessed() -> None:
    with pytest.raises(PostgresTestDatabaseNotConfigured):
        validate_postgres_test_url(None)


@pytest.mark.parametrize(
    "value",
    [
        "sqlite+aiosqlite:///ddrec_license_test",
        "postgresql+asyncpg://license_test:secret@127.0.0.1/ddrec_license",
        "postgresql+asyncpg://ddrec_license:secret@127.0.0.1/ddrec_license_test",
        "postgresql+asyncpg://license_test:secret@postgres/ddrec_license_test",
        "postgresql+asyncpg://license_test:secret@47.98.206.68/ddrec_license_test",
        "postgresql+asyncpg://license_test:secret@/ddrec_license_test",
        "postgresql+asyncpg://127.0.0.1/ddrec_license_test",
    ],
)
def test_unsafe_or_ambiguous_integration_database_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_postgres_test_url(value)


def test_ci_isolated_database_url_is_accepted() -> None:
    value = "postgresql+asyncpg://license_test:test-password-not-for-production@127.0.0.1:5432/ddrec_license_test"
    assert validate_postgres_test_url(value) == value


def test_explicit_remote_test_database_is_accepted() -> None:
    value = "postgresql+asyncpg://isolated_user:secret@test-db.example/ddrec_license_integration_test"
    assert validate_postgres_test_url(value) == value
