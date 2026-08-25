from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class PostgresTestDatabaseNotConfigured(RuntimeError):
    """Raised when the opt-in integration database URL is absent."""


KNOWN_PRODUCTION_HOSTS = {
    "47.98.206.68",
    "license.aixcc.top",
    "pmsystem-prod",
    "postgres",
}
KNOWN_PRODUCTION_DATABASES = {"ddrec_license"}
KNOWN_PRODUCTION_USERS = {"ddrec_license"}


def validate_postgres_test_url(value: str | None) -> str:
    """Return an explicitly configured, isolated PostgreSQL test URL or fail closed."""
    raw = str(value or "").strip()
    if not raw:
        raise PostgresTestDatabaseNotConfigured("LICENSE_TEST_DATABASE_URL is not configured")

    try:
        url = make_url(raw)
    except ArgumentError as exc:
        raise ValueError("LICENSE_TEST_DATABASE_URL is not a valid SQLAlchemy URL") from exc

    database = str(url.database or "").strip().lower()
    username = str(url.username or "").strip().lower()
    host = str(url.host or "").strip().lower()

    if url.drivername != "postgresql+asyncpg":
        raise ValueError("LICENSE_TEST_DATABASE_URL must use postgresql+asyncpg")
    if not database.endswith("_test"):
        raise ValueError("LICENSE_TEST_DATABASE_URL database name must end in _test")
    if not username:
        raise ValueError("LICENSE_TEST_DATABASE_URL must name an explicit test user")
    if not host:
        raise ValueError("LICENSE_TEST_DATABASE_URL must name an explicit test host")
    if database in KNOWN_PRODUCTION_DATABASES:
        raise ValueError("LICENSE_TEST_DATABASE_URL must not use the production database")
    if username in KNOWN_PRODUCTION_USERS:
        raise ValueError("LICENSE_TEST_DATABASE_URL must not use the production database user")
    if host in KNOWN_PRODUCTION_HOSTS:
        raise ValueError("LICENSE_TEST_DATABASE_URL must not use a known production host")
    return raw
