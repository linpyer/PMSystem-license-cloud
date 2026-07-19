from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pyotp
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.cli.generate_dev_keys import generate
from app.core.admin_security import encrypt_totp_secret, hash_admin_password, verify_admin_password
from app.core.config import Settings
from app.db.base import Base
from app.db.models import (
    AdminAuditEvent,
    AdminSession,
    AdminUser,
    DeviceBinding,
    DeviceTrial,
    IdempotencyRequest,
    License,
    LicenseEvent,
)
from app.db.models.enums import (
    AdminRole,
    AdminStatus,
    BindingStatus,
    DeviceTrialStatus,
    LicenseEventType,
    LicenseStatus,
)
from app.main import create_app


pytestmark = pytest.mark.integration
PASSWORD = "StrongAdmin!2026"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture(scope="session")
def admin_database_url() -> str:
    value = os.getenv("LICENSE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LICENSE_TEST_DATABASE_URL is not configured")
    if not (make_url(value).database or "").endswith("_test"):
        pytest.fail("Administrator integration tests require the dedicated _test database")
    return value


@pytest.fixture(scope="session")
def admin_private_key(tmp_path_factory) -> Path:
    private_path, _ = generate(tmp_path_factory.mktemp("admin-signing"))
    return private_path


@pytest.fixture
def admin_settings(admin_database_url: str, admin_private_key: Path) -> Settings:
    return Settings.model_validate({
        "LICENSE_DATABASE_URL": admin_database_url,
        "LICENSE_ENVIRONMENT": "test",
        "LICENSE_SIGNING_PRIVATE_KEY_PATH": admin_private_key,
        "LICENSE_SIGNING_KEY_ID": "admin-integration-key",
        "LICENSE_CODE_PEPPER": "admin-integration-code-pepper-32-characters",
        "LICENSE_DEVICE_CREDENTIAL_PEPPER": "admin-device-credential-pepper-32-characters",
        "LICENSE_ADMIN_SESSION_SECRET": "admin-session-secret-for-integration-tests",
        "LICENSE_ADMIN_TOTP_ENCRYPTION_KEY": "admin-totp-secret-for-integration-tests",
        "LICENSE_ADMIN_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
        "LICENSE_ADMIN_LOGIN_MAX_FAILURES": 5,
    })


@pytest_asyncio.fixture
async def admin_api(admin_settings: Settings):
    engine = create_async_engine(admin_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    app = create_app(admin_settings)
    async with app.router.lifespan_context(app):
        async with app.state.database.session_factory() as session:
            now = datetime.now(timezone.utc)
            owner = AdminUser(
                username="owner", password_hash=hash_admin_password(PASSWORD), display_name="Owner",
                role=AdminRole.OWNER, status=AdminStatus.ACTIVE,
                totp_secret_encrypted=encrypt_totp_secret(
                    TOTP_SECRET, admin_settings.admin_totp_encryption_key.get_secret_value()
                ),
                totp_enabled=True, failed_login_count=0, password_changed_at=now,
            )
            session.add(owner)
            await session.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://license.test") as client:
            yield app, client


async def login_with_secret(
    client: httpx.AsyncClient, username: str, password: str, secret: str,
) -> tuple[str, httpx.Response]:
    first = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert first.status_code == 200
    challenge = first.json()["challenge"]
    second = await client.post("/api/v1/admin/auth/totp/verify", json={
        "challenge": challenge, "code": pyotp.TOTP(secret).now(),
    })
    assert second.status_code == 200
    return client.cookies.get("pms_admin_csrf"), second


async def login(client: httpx.AsyncClient, username: str = "owner", password: str = PASSWORD) -> str:
    csrf, _response = await login_with_secret(client, username, password, TOTP_SECRET)
    return csrf


def write_headers(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf, "X-Request-ID": str(uuid4()), "Origin": "http://127.0.0.1:5173"}


async def test_password_totp_cookie_and_logout_security(admin_api) -> None:
    app, client = admin_api
    bad = await client.post("/api/v1/admin/auth/login", json={"username": "owner", "password": "wrong"})
    assert bad.status_code == 401
    first = await client.post("/api/v1/admin/auth/login", json={"username": "owner", "password": PASSWORD})
    wrong_totp = await client.post("/api/v1/admin/auth/totp/verify", json={
        "challenge": first.json()["challenge"], "code": "000000",
    })
    assert wrong_totp.status_code == 401
    csrf, login_response = await login_with_secret(client, "owner", PASSWORD, TOTP_SECRET)
    set_cookie = " ".join(login_response.headers.get_list("set-cookie")).lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    me = await client.get("/api/v1/admin/auth/me")
    assert me.status_code == 200 and me.json()["user"]["role"] == "OWNER"
    no_csrf = await client.post("/api/v1/admin/auth/logout")
    assert no_csrf.status_code == 403
    ok = await client.post("/api/v1/admin/auth/logout", headers=write_headers(csrf))
    assert ok.status_code == 200
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    async with app.state.database.session_factory() as session:
        stored = (await session.scalars(select(AdminSession))).all()
        assert all(PASSWORD not in item.token_hash for item in stored)


async def test_create_is_idempotent_and_plaintext_is_returned_once(admin_api) -> None:
    app, client = admin_api
    csrf = await login(client)
    request_id = str(uuid4())
    body = {"requestId": request_id, "licenseType": "monthly", "customerName": "测试客户"}
    first = await client.post("/api/v1/admin/licenses", json=body, headers=write_headers(csrf))
    assert first.status_code == 201
    code = first.json()["items"][0]["licenseCode"]
    assert code.startswith("PMS-")
    second = await client.post("/api/v1/admin/licenses", json=body, headers=write_headers(csrf))
    assert second.status_code == 201 and second.headers["Idempotency-Replayed"] == "true"
    assert "licenseCode" not in second.json()["items"][0]
    listing = await client.get("/api/v1/admin/licenses", params={"keyword": code[-4:]})
    assert listing.status_code == 200
    assert listing.json()["items"][0]["maskedCode"].endswith(code[-4:])
    assert code not in str(listing.json())
    async with app.state.database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(License)) == 1
        stored = await session.scalar(select(IdempotencyRequest.response_body))
        assert code not in str(stored)


async def test_batch_create_filter_pagination_and_dashboard(admin_api) -> None:
    _app, client = admin_api
    csrf = await login(client)
    response = await client.post("/api/v1/admin/licenses/batch", json={
        "requestId": str(uuid4()), "licenseType": "yearly", "quantity": 3,
        "remark": "batch",
    }, headers=write_headers(csrf))
    assert response.status_code == 201 and len(response.json()["items"]) == 3
    listing = await client.get("/api/v1/admin/licenses", params={
        "page": 1, "pageSize": 20, "licenseType": "yearly", "status": "CREATED",
    })
    assert listing.status_code == 200 and listing.json()["total"] == 3
    summary = await client.get("/api/v1/admin/dashboard/summary")
    assert summary.json()["summary"]["total"] == 3
    assert summary.json()["summary"]["created7Days"] == 3
    assert len(summary.json()["recent"]["createdLicenses"]) == 3
    assert "adminOperations" in summary.json()["recent"]


async def test_trial_list_dashboard_masking_and_disable_audit(admin_api) -> None:
    app, client = admin_api
    device_id = "admin-trial-device-0123456789"
    activated = await client.post("/api/v1/trials/activate", json={
        "deviceId": device_id,
        "fingerprintVersion": "win-v1",
        "deviceName": "Trial Admin Device",
        "osVersion": "Windows 11",
        "appVersion": "1.0.5",
        "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    })
    assert activated.status_code == 200
    csrf = await login(client)
    listing = await client.get("/api/v1/admin/trials", params={
        "deviceId": "admin-trial-device",
        "status": "ACTIVE",
        "page": 1,
        "pageSize": 20,
    })
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["device"] == "admin-tr..."
    assert device_id not in str(listing.json())

    summary = await client.get("/api/v1/admin/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["summary"]["trialTotal"] == 1
    assert summary.json()["summary"]["trialActive"] == 1

    disabled = await client.post(
        f"/api/v1/admin/trials/{item['trialId']}/disable",
        json={"reason": "integration security review"},
        headers=write_headers(csrf),
    )
    assert disabled.status_code == 200
    assert disabled.json()["trial"]["status"] == "DISABLED"
    async with app.state.database.session_factory() as session:
        trial = await session.scalar(select(DeviceTrial))
        assert trial.status == DeviceTrialStatus.DISABLED
        actions = set(await session.scalars(select(AdminAuditEvent.action)))
        assert "DISABLE_TRIAL" in actions


async def test_owner_extends_resets_and_logically_deletes_trial(admin_api) -> None:
    app, client = admin_api
    device_id = "managed-trial-device-0123456789"
    activated = await client.post("/api/v1/trials/activate", json={
        "deviceId": device_id,
        "fingerprintVersion": "win-v1",
        "deviceName": "Managed Trial Device",
        "osVersion": "Windows 11",
        "appVersion": "1.0.5",
        "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    })
    assert activated.status_code == 200
    old_credential = activated.json()["credential"]
    async with app.state.database.session_factory() as session:
        initial_trial = await session.scalar(select(DeviceTrial))
        initial_license_id = str(initial_trial.trial_license_id)
    csrf = await login(client)
    item = (await client.get("/api/v1/admin/trials")).json()["items"][0]
    original_expiry = datetime.fromisoformat(item["expiresAt"].replace("Z", "+00:00"))

    extended = await client.post(
        f"/api/v1/admin/trials/{item['trialId']}/extend",
        json={"days": 30, "reason": "customer evaluation extension"},
        headers=write_headers(csrf),
    )
    assert extended.status_code == 200
    extended_trial = extended.json()["trial"]
    extended_expiry = datetime.fromisoformat(
        extended_trial["expiresAt"].replace("Z", "+00:00")
    )
    assert extended_expiry - original_expiry == timedelta(days=30)
    assert extended_trial["extensionCount"] == 1

    reset = await client.post(
        f"/api/v1/admin/trials/{item['trialId']}/reset",
        json={"reason": "restart approved evaluation"},
        headers=write_headers(csrf),
    )
    assert reset.status_code == 200
    reset_trial = reset.json()["trial"]
    reset_start = datetime.fromisoformat(reset_trial["startedAt"].replace("Z", "+00:00"))
    reset_expiry = datetime.fromisoformat(reset_trial["expiresAt"].replace("Z", "+00:00"))
    assert reset_expiry - reset_start == timedelta(hours=168)
    assert reset_trial["resetCount"] == 1
    old_verify = await client.post("/api/v1/licenses/verify", json={
        "licenseId": initial_license_id,
        "deviceId": device_id,
        "credential": old_credential,
        "appVersion": "1.0.5",
        "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    })
    assert old_verify.status_code == 401
    assert old_verify.json()["error"]["code"] == "INVALID_CREDENTIAL"

    deleted = await client.post(
        f"/api/v1/admin/trials/{item['trialId']}/delete",
        json={"reason": "remove test evaluation", "confirmation": "DELETE"},
        headers=write_headers(csrf),
    )
    assert deleted.status_code == 200
    assert deleted.json()["trial"]["status"] == "DELETED"
    assert (await client.get("/api/v1/admin/trials")).json()["total"] == 0
    deleted_listing = await client.get(
        "/api/v1/admin/trials", params={"includeDeleted": "true"}
    )
    assert deleted_listing.json()["total"] == 1

    reactivated = await client.post("/api/v1/trials/activate", json={
        "deviceId": device_id,
        "fingerprintVersion": "win-v1",
        "deviceName": "Managed Trial Device",
        "osVersion": "Windows 11",
        "appVersion": "1.0.5",
        "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    })
    assert reactivated.status_code == 200
    async with app.state.database.session_factory() as session:
        trials = list(await session.scalars(select(DeviceTrial).order_by(DeviceTrial.created_at)))
        assert len(trials) == 2
        assert trials[0].status == DeviceTrialStatus.DELETED
        assert trials[1].status == DeviceTrialStatus.ACTIVE
        old_license = await session.get(License, trials[0].trial_license_id)
        assert old_license.status == LicenseStatus.REVOKED
        old_binding = await session.scalar(
            select(DeviceBinding).where(DeviceBinding.license_id == trials[0].trial_license_id)
        )
        assert old_binding.status == BindingStatus.DISABLED
        event_types = set(await session.scalars(select(LicenseEvent.event_type)))
        assert LicenseEventType.TRIAL_REACTIVATED_AFTER_DELETE in event_types
        actions = set(await session.scalars(select(AdminAuditEvent.action)))
        assert {"TRIAL_EXTENDED", "TRIAL_RESET", "TRIAL_DELETED"} <= actions


async def test_trial_management_role_permissions(admin_api) -> None:
    app, owner = admin_api
    activated = await owner.post("/api/v1/trials/activate", json={
        "deviceId": "role-trial-device-0123456789",
        "fingerprintVersion": "win-v1",
        "deviceName": "Role Trial Device",
        "osVersion": "Windows 11",
        "appVersion": "1.0.5",
        "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    })
    assert activated.status_code == 200
    owner_csrf = await login(owner)
    trial_id = (await owner.get("/api/v1/admin/trials")).json()["items"][0]["trialId"]

    credentials = []
    for username, role in (("trialadmin", "ADMIN"), ("trialaudit", "AUDITOR")):
        created = await owner.post("/api/v1/admin/users", json={
            "username": username,
            "displayName": username,
            "role": role,
            "password": f"{username.title()}!Password2026",
        }, headers=write_headers(owner_csrf))
        assert created.status_code == 200
        credentials.append((username, f"{username.title()}!Password2026", created.json()["totpSecret"], role))

    for username, password, secret, role in credentials:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://license.test") as client:
            csrf, _ = await login_with_secret(client, username, password, secret)
            assert (await client.get("/api/v1/admin/trials")).status_code == 200
            extend = await client.post(
                f"/api/v1/admin/trials/{trial_id}/extend",
                json={"days": 1, "reason": "role permission test"},
                headers=write_headers(csrf),
            )
            assert extend.status_code == (200 if role == "ADMIN" else 403)
            reset = await client.post(
                f"/api/v1/admin/trials/{trial_id}/reset",
                json={"reason": "role permission test"},
                headers=write_headers(csrf),
            )
            delete = await client.post(
                f"/api/v1/admin/trials/{trial_id}/delete",
                json={"reason": "role permission test", "confirmation": "DELETE"},
                headers=write_headers(csrf),
            )
            assert reset.status_code == 403
            assert delete.status_code == 403


async def test_update_disable_enable_revoke_and_audit(admin_api) -> None:
    app, client = admin_api
    csrf = await login(client)
    created = await client.post("/api/v1/admin/licenses", json={
        "requestId": str(uuid4()), "licenseType": "permanent",
    }, headers=write_headers(csrf))
    license_id = created.json()["items"][0]["licenseId"]
    updated = await client.patch(f"/api/v1/admin/licenses/{license_id}", json={
        "customerName": "客户甲", "customerContact": "contact", "remark": "note",
    }, headers=write_headers(csrf))
    assert updated.json()["license"]["customerName"] == "客户甲"
    disabled = await client.post(f"/api/v1/admin/licenses/{license_id}/disable", json={"reason": "test disable"}, headers=write_headers(csrf))
    assert disabled.json()["status"] == "DISABLED"
    enabled = await client.post(f"/api/v1/admin/licenses/{license_id}/enable", json={"reason": "test enable"}, headers=write_headers(csrf))
    assert enabled.json()["status"] == "CREATED"
    revoked = await client.post(f"/api/v1/admin/licenses/{license_id}/revoke", json={"reason": "test revoke"}, headers=write_headers(csrf))
    assert revoked.json()["status"] == "REVOKED"
    cannot_enable = await client.post(f"/api/v1/admin/licenses/{license_id}/enable", json={"reason": "not allowed"}, headers=write_headers(csrf))
    assert cannot_enable.status_code == 409
    audit = await client.get("/api/v1/admin/audit-events")
    assert {item["action"] for item in audit.json()["items"]} >= {
        "UPDATE_LICENSE", "DISABLE_LICENSE", "ENABLE_LICENSE", "REVOKE_LICENSE",
    }
    async with app.state.database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AdminAuditEvent)) >= 5


async def test_version_policy_rejects_old_client_and_advises_supported_client(admin_api) -> None:
    _app, client = admin_api
    csrf = await login(client)
    response = await client.put("/api/v1/admin/version-policy", json={
        "recommendedVersion": "1.1.0", "minimumSupportedVersion": "1.0.5",
        "downloadUrl": "https://example.test/pmsystem", "releaseNotes": "升级建议",
    }, headers=write_headers(csrf))
    assert response.status_code == 200
    created = await client.post("/api/v1/admin/licenses", json={
        "requestId": str(uuid4()), "licenseType": "monthly",
    }, headers=write_headers(csrf))
    code = created.json()["items"][0]["licenseCode"]
    common = {
        "licenseCode": code, "deviceId": "admin-version-device", "fingerprintVersion": "win-v1",
        "deviceName": "test", "osVersion": "Windows", "requestId": str(uuid4()),
        "clientTime": datetime.now(timezone.utc).isoformat(),
    }
    old = await client.post("/api/v1/licenses/activate", json={**common, "appVersion": "1.0.4"})
    assert old.status_code == 426 and old.json()["error"]["code"] == "CLIENT_VERSION_UNSUPPORTED"
    current = await client.post("/api/v1/licenses/activate", json={
        **common, "requestId": str(uuid4()), "appVersion": "1.0.5",
    })
    assert current.status_code == 200 and current.json()["update"]["recommendedVersion"] == "1.1.0"


async def test_cors_rejects_unknown_origin(admin_api) -> None:
    _app, client = admin_api
    response = await client.options("/api/v1/admin/licenses", headers={
        "Origin": "https://unknown.example", "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") is None


async def test_owner_manages_admins_and_secrets_are_not_returned_by_list(admin_api) -> None:
    app, owner_client = admin_api
    csrf = await login(owner_client)
    created = await owner_client.post("/api/v1/admin/users", json={
        "username": "operator", "displayName": "Operator", "role": "ADMIN",
        "password": "Operator!Password2026",
    }, headers=write_headers(csrf))
    assert created.status_code == 200
    enrollment = created.json()
    secret = enrollment["totpSecret"]
    user_id = enrollment["user"]["id"]
    assert secret and enrollment["enrollmentVisibleOnce"] is True

    listing = await owner_client.get("/api/v1/admin/users")
    assert listing.status_code == 200
    assert secret not in str(listing.json())
    assert all("totpSecret" not in user for user in listing.json()["items"])

    async with app.state.database.session_factory() as session:
        operator = await session.scalar(select(AdminUser).where(AdminUser.username == "operator"))
        assert operator is not None
        assert secret not in operator.totp_secret_encrypted
        assert verify_admin_password("Operator!Password2026", operator.password_hash)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://license.test") as operator_client:
        operator_csrf, _ = await login_with_secret(
            operator_client, "operator", "Operator!Password2026", secret
        )
        allowed = await operator_client.post("/api/v1/admin/licenses", json={
            "requestId": str(uuid4()), "licenseType": "monthly",
        }, headers=write_headers(operator_csrf))
        assert allowed.status_code == 201
        assert (await operator_client.get("/api/v1/admin/users")).status_code == 403
        forbidden = await operator_client.put("/api/v1/admin/version-policy", json={
            "recommendedVersion": "1.0.5", "minimumSupportedVersion": "1.0.5",
        }, headers=write_headers(operator_csrf))
        assert forbidden.status_code == 403

        disabled = await owner_client.post(
            f"/api/v1/admin/users/{user_id}/disable",
            json={"reason": "security review"}, headers=write_headers(csrf),
        )
        assert disabled.status_code == 200 and disabled.json()["user"]["status"] == "DISABLED"
        assert (await operator_client.get("/api/v1/admin/auth/me")).status_code == 401

    enabled = await owner_client.post(
        f"/api/v1/admin/users/{user_id}/enable",
        json={"reason": "review complete"}, headers=write_headers(csrf),
    )
    assert enabled.status_code == 200 and enabled.json()["user"]["status"] == "ACTIVE"


async def test_auditor_is_read_only(admin_api) -> None:
    app, owner_client = admin_api
    csrf = await login(owner_client)
    created = await owner_client.post("/api/v1/admin/users", json={
        "username": "auditor", "displayName": "Auditor", "role": "AUDITOR",
        "password": "Auditor!Password2026",
    }, headers=write_headers(csrf))
    secret = created.json()["totpSecret"]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://license.test") as auditor:
        auditor_csrf, _ = await login_with_secret(
            auditor, "auditor", "Auditor!Password2026", secret
        )
        assert (await auditor.get("/api/v1/admin/licenses")).status_code == 200
        denied = await auditor.post("/api/v1/admin/licenses", json={
            "requestId": str(uuid4()), "licenseType": "monthly",
        }, headers=write_headers(auditor_csrf))
        assert denied.status_code == 403
