from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base


pytestmark = pytest.mark.integration


def test_initial_migration_upgrades_and_downgrades_dedicated_database(monkeypatch) -> None:
    database_url = os.getenv("LICENSE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LICENSE_TEST_DATABASE_URL is not configured; Alembic test skipped")
    if not database_url.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        pytest.fail("Alembic tests require a database name ending in _test")

    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("LICENSE_DATABASE_URL", database_url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    get_settings.cache_clear()

    async def reset_test_schema() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(reset_test_schema())
    command.upgrade(config, "head")

    async def table_names() -> set[str]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
        finally:
            await engine.dispose()

    assert {
        "licenses",
        "device_bindings",
        "license_events",
        "idempotency_requests",
        "signing_keys",
        "alembic_version",
        "admin_users",
        "admin_sessions",
        "admin_audit_events",
        "admin_login_attempts",
        "app_version_policy",
        "device_trials",
    } <= asyncio.run(table_names())

    async def event_type_width() -> int:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                value = await connection.scalar(text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name = 'license_events' AND column_name = 'event_type'"
                ))
                return int(value)
        finally:
            await engine.dispose()

    assert asyncio.run(event_type_width()) >= len("TRIAL_REACTIVATED_SAME_DEVICE")

    command.downgrade(config, "-1")
    after_event_width_downgrade = asyncio.run(table_names())
    assert "device_trials" in after_event_width_downgrade
    command.downgrade(config, "0003_signing_key_rotation")
    after_trial_downgrade = asyncio.run(table_names())
    assert "device_trials" not in after_trial_downgrade
    assert "admin_users" in after_trial_downgrade
    assert "signing_keys" in after_trial_downgrade
    command.downgrade(config, "-1")
    after_rotation_downgrade = asyncio.run(table_names())
    assert "admin_users" in after_rotation_downgrade
    assert "signing_keys" in after_rotation_downgrade
    command.downgrade(config, "-1")
    after_admin_downgrade = asyncio.run(table_names())
    assert "admin_users" not in after_admin_downgrade
    assert "licenses" in after_admin_downgrade
    command.downgrade(config, "base")
    assert "licenses" not in asyncio.run(table_names())
    command.upgrade(config, "head")
