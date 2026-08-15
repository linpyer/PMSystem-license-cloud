from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pyotp
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.admin_security import encrypt_totp_secret, generate_totp_secret, hash_admin_password
from app.core.config import get_settings
from app.db.models import AdminSession, AdminUser
from app.db.models.enums import AdminRole, AdminSessionStatus, AdminStatus


def _smoke_database_url(value: str) -> str:
    override = os.getenv("DDREC_SMOKE_DATABASE_URL")
    url = make_url(override or value)
    if url.database not in {"ddrec_license_dev", "ddrec_license_staging"}:
        raise RuntimeError("Smoke test may only use development or staging license databases")
    if not override:
        url = url.set(host="127.0.0.1", port=5433)
    return url.render_as_string(hide_password=False)


def _smoke_base_url() -> str:
    value = os.getenv("DDREC_SMOKE_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "caddy"}:
        raise RuntimeError("Smoke API must be a local development or staging HTTP endpoint")
    return value


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(_smoke_database_url(settings.database_url))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    username = f"smoke-{uuid4().hex[:10]}"
    password = f"Dev!{secrets.token_urlsafe(18)}Aa1"
    totp_secret = generate_totp_secret()
    now = datetime.now(timezone.utc)
    async with sessions() as session:
        user = AdminUser(
            username=username,
            password_hash=hash_admin_password(password),
            display_name="Local smoke administrator",
            role=AdminRole.OWNER,
            status=AdminStatus.ACTIVE,
            totp_secret_encrypted=encrypt_totp_secret(
                totp_secret, settings.admin_totp_encryption_key.get_secret_value()
            ),
            totp_enabled=True,
            failed_login_count=0,
            password_changed_at=now,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    summary: dict[str, object] = {}
    try:
        async with httpx.AsyncClient(
            base_url=_smoke_base_url(), timeout=10, trust_env=False
        ) as client:
            login = await client.post("/admin/auth/login", json={"username": username, "password": password})
            login.raise_for_status()
            totp = await client.post("/admin/auth/totp/verify", json={
                "challenge": login.json()["challenge"],
                "code": pyotp.TOTP(totp_secret).now(),
            })
            totp.raise_for_status()
            csrf = client.cookies["pms_admin_csrf"]

            def headers() -> dict[str, str]:
                return {"X-CSRF-Token": csrf, "X-Request-ID": str(uuid4())}

            created = await client.post("/admin/licenses", headers=headers(), json={
                "requestId": str(uuid4()), "licenseType": "monthly",
                "customerName": "Local smoke test", "remark": "automated local integration",
            })
            created.raise_for_status()
            item = created.json()["items"][0]
            license_id = item["licenseId"]
            code = item["licenseCode"]
            device_a = f"smoke-device-a-{uuid4().hex}"
            device_b = f"smoke-device-b-{uuid4().hex}"

            activated = await client.post("/licenses/activate", json={
                "licenseCode": code, "deviceId": device_a, "fingerprintVersion": "win-v1",
                "deviceName": "Smoke A", "osVersion": "Windows test", "appVersion": "1.0.5",
                "requestId": str(uuid4()), "clientTime": datetime.now(timezone.utc).isoformat(),
            })
            activated.raise_for_status()
            credential = activated.json()["credential"]
            detail = await client.get(f"/admin/licenses/{license_id}")
            detail.raise_for_status()
            binding_id = detail.json()["license"]["bindings"][0]["bindingId"]

            disabled = await client.post(
                f"/admin/licenses/{license_id}/disable", headers=headers(), json={"reason": "smoke disable"}
            )
            disabled.raise_for_status()
            verify_body = {
                "licenseId": license_id, "deviceId": device_a, "credential": credential,
                "appVersion": "1.0.5", "clientTime": datetime.now(timezone.utc).isoformat(),
            }
            disabled_verify = await client.post("/licenses/verify", json={
                **verify_body, "requestId": str(uuid4()),
            })
            assert disabled_verify.json()["error"]["code"] == "LICENSE_DISABLED"

            enabled = await client.post(
                f"/admin/licenses/{license_id}/enable", headers=headers(), json={"reason": "smoke enable"}
            )
            enabled.raise_for_status()
            verified = await client.post("/licenses/verify", json={
                **verify_body, "requestId": str(uuid4()),
            })
            verified.raise_for_status()

            unbound = await client.post(
                f"/admin/bindings/{binding_id}/deactivate", headers=headers(), json={"reason": "smoke unbind"}
            )
            unbound.raise_for_status()
            old_credential = await client.post("/licenses/verify", json={
                **verify_body, "requestId": str(uuid4()),
            })
            assert old_credential.json()["error"]["code"] == "DEVICE_MISMATCH"
            rebound = await client.post("/licenses/activate", json={
                "licenseCode": code, "deviceId": device_b, "fingerprintVersion": "win-v1",
                "deviceName": "Smoke B", "osVersion": "Windows test", "appVersion": "1.0.5",
                "requestId": str(uuid4()), "clientTime": datetime.now(timezone.utc).isoformat(),
            })
            rebound.raise_for_status()

            original_policy = (await client.get("/admin/version-policy")).json()["policy"]
            policy_test = await client.put("/admin/version-policy", headers=headers(), json={
                "recommendedVersion": "9.9.9", "minimumSupportedVersion": "9.0.0",
                "downloadUrl": "https://example.invalid/ddrec", "releaseNotes": "smoke only",
            })
            policy_test.raise_for_status()
            unsupported = await client.post("/licenses/refresh", json={
                "licenseId": license_id, "deviceId": device_b,
                "credential": rebound.json()["credential"], "appVersion": "1.0.5",
                "requestId": str(uuid4()), "clientTime": datetime.now(timezone.utc).isoformat(),
            })
            assert unsupported.json()["error"]["code"] == "CLIENT_VERSION_UNSUPPORTED"
            restored = await client.put("/admin/version-policy", headers=headers(), json={
                "recommendedVersion": original_policy["recommendedVersion"],
                "minimumSupportedVersion": original_policy["minimumSupportedVersion"],
                "downloadUrl": original_policy.get("downloadUrl"),
                "releaseNotes": original_policy.get("releaseNotes"),
            })
            restored.raise_for_status()

            audit = await client.get("/admin/audit-events", params={"targetId": license_id})
            audit.raise_for_status()
            revoked = await client.post(
                f"/admin/licenses/{license_id}/revoke", headers=headers(), json={"reason": "smoke cleanup"}
            )
            revoked.raise_for_status()
            logout = await client.post("/admin/auth/logout", headers=headers())
            logout.raise_for_status()
            after_logout = await client.get("/admin/auth/me")
            assert after_logout.status_code == 401
            summary = {
                "login": "ok", "totp": "ok", "create": "ok", "activate": "ok",
                "disableRestriction": "ok", "enableRecovery": "ok", "adminUnbind": "ok",
                "newDeviceActivation": "ok", "versionPolicy": "ok",
                "auditEvents": len(audit.json()["items"]), "logoutRevoked": True,
            }
    finally:
        async with sessions() as session:
            await session.execute(
                update(AdminSession)
                .where(AdminSession.admin_user_id == user_id)
                .values(status=AdminSessionStatus.REVOKED, revoked_at=datetime.now(timezone.utc))
            )
            await session.execute(
                update(AdminUser).where(AdminUser.id == user_id).values(status=AdminStatus.DISABLED)
            )
            await session.commit()
        await engine.dispose()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
