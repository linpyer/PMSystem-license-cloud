from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.cli.generate_dev_keys import generate
from app.core.config import Settings
from app.core.security import base64url_decode
from app.db.base import Base
from app.db.models import DeviceBinding, License, LicenseEvent, SigningKey
from app.db.models.enums import LicenseStatus, LicenseType
from app.main import create_app
from app.services.license_code_service import LicenseCodeService


pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    value = os.getenv("LICENSE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LICENSE_TEST_DATABASE_URL is not configured; dedicated PostgreSQL tests skipped")
    database = make_url(value).database or ""
    if not database.endswith("_test"):
        pytest.fail("LICENSE_TEST_DATABASE_URL database name must end in _test")
    return value


@pytest.fixture(scope="session")
def integration_private_key(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("license-signing")
    private_path, _ = generate(directory)
    return private_path


@pytest.fixture
def integration_settings(integration_database_url: str, integration_private_key: Path) -> Settings:
    return Settings.model_validate(
        {
            "LICENSE_DATABASE_URL": integration_database_url,
            "LICENSE_ENVIRONMENT": "test",
            "LICENSE_SIGNING_PRIVATE_KEY_PATH": integration_private_key,
            "LICENSE_SIGNING_KEY_ID": "integration-key-1",
            "LICENSE_CODE_PEPPER": "integration-code-pepper-at-least-32-characters",
            "LICENSE_DEVICE_CREDENTIAL_PEPPER": "integration-device-pepper-at-least-32-characters",
            "LICENSE_OPENAPI_ENABLED": True,
            "LICENSE_MINIMUM_CLIENT_VERSION": "1.0.4",
        }
    )


@pytest_asyncio.fixture
async def api(integration_settings: Settings):
    engine = create_async_engine(integration_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    application = create_app(integration_settings)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://license.test") as client:
            yield application, client


async def create_license(
    application,
    license_type: LicenseType,
    *,
    expires_at: datetime | None = None,
    status: LicenseStatus | None = None,
) -> tuple[str, License]:
    async with application.state.database.session_factory() as session:
        created = await LicenseCodeService(application.state.settings).create(
            session, license_type=license_type, expires_at=expires_at
        )
        if status is not None:
            created.record.status = status
        await session.commit()
        return created.plaintext_code, created.record


def activation_body(code: str, device_id: str, request_id: str | None = None) -> dict:
    return {
        "licenseCode": code,
        "deviceId": device_id,
        "fingerprintVersion": "1",
        "deviceName": "Integration Device",
        "osVersion": "Windows 11",
        "appVersion": "1.0.4",
        "requestId": request_id or str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    }


async def activate(client: httpx.AsyncClient, code: str, device_id: str, request_id: str | None = None):
    return await client.post(
        "/api/v1/licenses/activate", json=activation_body(code, device_id, request_id)
    )


def signed_payload(response: httpx.Response) -> dict:
    import json

    encoded = response.json()["license"]["payload"]
    return json.loads(base64url_decode(encoded).decode("utf-8"))


async def test_first_activation_creates_one_binding(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    response = await activate(client, code, "device-first")
    assert response.status_code == 200
    assert response.json()["credential"]
    async with application.state.database.session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(DeviceBinding).where(DeviceBinding.license_id == record.id)
        )
    assert count == 1


async def test_same_device_reactivation_rotates_credential_without_duplicate_binding(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    first = await activate(client, code, "device-repeat")
    second = await activate(client, code, "device-repeat")
    assert second.status_code == 200
    assert second.json()["credential"] != first.json()["credential"]
    async with application.state.database.session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(DeviceBinding).where(DeviceBinding.license_id == record.id)
        )
    assert count == 1


async def test_second_device_is_rejected(api) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY)
    assert (await activate(client, code, "device-owner")).status_code == 200
    response = await activate(client, code, "device-other")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LICENSE_ALREADY_BOUND"


@pytest.mark.parametrize(
    ("license_type", "days"),
    [(LicenseType.MONTHLY, 30), (LicenseType.YEARLY, 365)],
)
async def test_duration_expiration_is_calculated_from_first_activation(api, license_type, days) -> None:
    application, client = api
    code, _ = await create_license(application, license_type)
    response = await activate(client, code, f"device-{license_type.value}")
    payload = signed_payload(response)
    issued = datetime.fromisoformat(payload["issuedAt"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(payload["expiresAt"].replace("Z", "+00:00"))
    assert abs((expires - issued) - timedelta(days=days)) < timedelta(seconds=2)


async def test_permanent_license_has_no_business_expiration(api) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.PERMANENT)
    response = await activate(client, code, "device-permanent")
    assert signed_payload(response)["expiresAt"] is None
    assert signed_payload(response)["nextRequiredVerifyAt"] is not None


async def test_fixed_date_license_keeps_configured_expiration(api) -> None:
    application, client = api
    expiration = datetime(2027, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    code, _ = await create_license(
        application, LicenseType.FIXED_DATE, expires_at=expiration
    )
    response = await activate(client, code, "device-fixed")
    assert signed_payload(response)["expiresAt"] == "2027-12-31T23:59:59Z"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (LicenseStatus.DISABLED, "LICENSE_DISABLED"),
        (LicenseStatus.REVOKED, "LICENSE_REVOKED"),
    ],
)
async def test_unusable_license_cannot_activate(api, status, error_code) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY, status=status)
    response = await activate(client, code, f"device-{status.value.lower()}")
    assert response.json()["error"]["code"] == error_code


async def test_verify_updates_time_and_issues_new_license(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    activated = await activate(client, code, "device-verify")
    first_payload = activated.json()["license"]["payload"]
    response = await client.post(
        "/api/v1/licenses/verify",
        json={
            "licenseId": str(record.id),
            "deviceId": "device-verify",
            "credential": activated.json()["credential"],
            "appVersion": "1.0.4",
            "requestId": str(uuid4()),
            "clientTime": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["license"]["payload"] != first_payload


async def test_expired_license_fails_verification(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    activated = await activate(client, code, "device-expired")
    async with application.state.database.session_factory() as session:
        stored = await session.get(License, record.id)
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    response = await client.post(
        "/api/v1/licenses/verify",
        json={
            "licenseId": str(record.id),
            "deviceId": "device-expired",
            "credential": activated.json()["credential"],
            "appVersion": "1.0.4",
            "requestId": str(uuid4()),
        },
    )
    assert response.json()["error"]["code"] == "LICENSE_EXPIRED"


async def test_invalid_device_credential_is_rejected(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    await activate(client, code, "device-credential")
    response = await client.post(
        "/api/v1/licenses/verify",
        json={
            "licenseId": str(record.id),
            "deviceId": "device-credential",
            "credential": "x" * 43,
            "appVersion": "1.0.4",
            "requestId": str(uuid4()),
        },
    )
    assert response.json()["error"]["code"] == "INVALID_CREDENTIAL"


async def test_deactivate_is_semantically_idempotent(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    activated = await activate(client, code, "device-deactivate")
    body = {
        "licenseId": str(record.id),
        "deviceId": "device-deactivate",
        "credential": activated.json()["credential"],
        "reason": "user request",
        "requestId": str(uuid4()),
    }
    first = await client.post("/api/v1/licenses/deactivate", json=body)
    body["requestId"] = str(uuid4())
    second = await client.post("/api/v1/licenses/deactivate", json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["alreadyDeactivated"] is True


async def test_repeated_deactivate_still_requires_original_credential(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    activated = await activate(client, code, "device-deactivate-auth")
    body = {
        "licenseId": str(record.id),
        "deviceId": "device-deactivate-auth",
        "credential": activated.json()["credential"],
        "reason": "user request",
        "requestId": str(uuid4()),
    }
    assert (await client.post("/api/v1/licenses/deactivate", json=body)).status_code == 200
    body["requestId"] = str(uuid4())
    body["credential"] = "x" * 43
    response = await client.post("/api/v1/licenses/deactivate", json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIAL"


async def test_never_activated_license_cannot_be_deactivated(api) -> None:
    application, client = api
    _code, record = await create_license(application, LicenseType.MONTHLY)
    response = await client.post(
        "/api/v1/licenses/deactivate",
        json={
            "licenseId": str(record.id),
            "deviceId": "device-never-bound",
            "credential": "x" * 43,
            "reason": "invalid request",
            "requestId": str(uuid4()),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEVICE_MISMATCH"


async def test_new_device_can_activate_after_deactivation(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    first = await activate(client, code, "device-old")
    await client.post(
        "/api/v1/licenses/deactivate",
        json={
            "licenseId": str(record.id),
            "deviceId": "device-old",
            "credential": first.json()["credential"],
            "reason": "replace device",
            "requestId": str(uuid4()),
        },
    )
    assert (await activate(client, code, "device-new")).status_code == 200


async def test_same_request_id_replays_first_response(api) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY)
    request_id = str(uuid4())
    body = activation_body(code, "device-idempotent", request_id)
    first = await client.post("/api/v1/licenses/activate", json=body)
    second = await client.post("/api/v1/licenses/activate", json=body)
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.json() == first.json()


async def test_same_request_id_with_different_payload_is_rejected(api) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY)
    request_id = str(uuid4())
    first_body = activation_body(code, "device-idempotent-a", request_id)
    second_body = {**first_body, "deviceId": "device-idempotent-b"}
    assert (await client.post("/api/v1/licenses/activate", json=first_body)).status_code == 200
    response = await client.post("/api/v1/licenses/activate", json=second_body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_REQUEST"


async def test_concurrent_activation_produces_one_active_binding(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    first, second = await asyncio.gather(
        activate(client, code, "device-concurrent-a"),
        activate(client, code, "device-concurrent-b"),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    async with application.state.database.session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(DeviceBinding).where(
                DeviceBinding.license_id == record.id,
                DeviceBinding.status == "ACTIVE",
            )
        )
    assert count == 1


async def test_refresh_requires_current_device_credential(api) -> None:
    application, client = api
    code, record = await create_license(application, LicenseType.MONTHLY)
    activated = await activate(client, code, "device-refresh")
    body = {
        "licenseId": str(record.id),
        "deviceId": "device-refresh",
        "credential": activated.json()["credential"],
        "appVersion": "1.0.4",
        "requestId": str(uuid4()),
    }
    assert (await client.post("/api/v1/licenses/refresh", json=body)).status_code == 200
    body["requestId"] = str(uuid4())
    body["credential"] = "z" * 43
    assert (await client.post("/api/v1/licenses/refresh", json=body)).status_code == 401


async def test_health_does_not_disclose_sensitive_configuration(api) -> None:
    _application, client = api
    response = await client.get("/api/v1/health")
    serialized = response.text
    assert response.status_code == 200
    assert "password" not in serialized.lower()
    assert "pepper" not in serialized.lower()
    assert "private" not in serialized.lower()


async def test_audit_events_and_public_signing_key_are_persisted(api) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY)
    await activate(client, code, "device-audit")
    async with application.state.database.session_factory() as session:
        events = await session.scalar(select(func.count()).select_from(LicenseEvent))
        key = await session.scalar(select(SigningKey))
    assert events == 1
    assert key is not None
    assert key.public_key
    assert not hasattr(key, "private_key")


async def test_request_logs_do_not_contain_complete_license_code(api, capsys) -> None:
    application, client = api
    code, _ = await create_license(application, LicenseType.MONTHLY)
    await activate(client, code, "device-log-safe")
    captured = capsys.readouterr()
    assert code not in captured.out
    assert code not in captured.err


async def test_postgresql_native_types_and_partial_unique_index(api) -> None:
    application, _client = api
    async with application.state.database.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT table_name, column_name, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND (table_name, column_name) IN (
                        ('device_bindings', 'last_ip'),
                        ('license_events', 'ip'),
                        ('license_events', 'detail'),
                        ('licenses', 'created_at'),
                        ('licenses', 'expires_at')
                      )
                    """
                )
            )
        ).all()
        column_types = {(row.table_name, row.column_name): row.udt_name for row in rows}
        assert column_types[("device_bindings", "last_ip")] == "inet"
        assert column_types[("license_events", "ip")] == "inet"
        assert column_types[("license_events", "detail")] == "jsonb"
        assert column_types[("licenses", "created_at")] == "timestamptz"
        assert column_types[("licenses", "expires_at")] == "timestamptz"

        index_definition = await session.scalar(
            text(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'uq_device_bindings_active_license'
                """
            )
        )
        assert index_definition is not None
        assert "UNIQUE INDEX" in index_definition
        assert "WHERE" in index_definition
        assert "status" in index_definition


async def test_license_creation_transaction_can_be_rolled_back(api) -> None:
    application, _client = api
    async with application.state.database.session_factory() as session:
        created = await LicenseCodeService(application.state.settings).create(
            session, license_type=LicenseType.MONTHLY
        )
        license_id = created.record.id
        await session.rollback()

    async with application.state.database.session_factory() as session:
        assert await session.get(License, license_id) is None
