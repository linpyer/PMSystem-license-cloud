from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    encrypt_totp_secret,
    generate_totp_secret,
    hash_admin_password,
)
from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.db.models import AdminUser
from app.db.models.enums import AdminStatus
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import AdminCreateRequest, AdminStatusRequest
from app.services.admin_auth_service import AuthenticatedAdmin, RequestMeta


class AdminUserService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = AdminRepository()

    async def list_users(self, session: AsyncSession) -> list[dict]:
        return [self._as_dict(user) for user in await self.repository.list_users(session)]

    async def create_user(
        self, session: AsyncSession, actor: AuthenticatedAdmin,
        request: AdminCreateRequest, meta: RequestMeta,
    ) -> dict:
        if await self.repository.get_user_by_username(session, request.username):
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "管理员用户名已存在")
        now = datetime.now(timezone.utc)
        secret = generate_totp_secret()
        user = AdminUser(
            username=request.username.strip().lower(),
            password_hash=hash_admin_password(request.password),
            display_name=request.display_name,
            role=request.role,
            status=AdminStatus.ACTIVE,
            totp_secret_encrypted=encrypt_totp_secret(
                secret, self.settings.admin_totp_encryption_key.get_secret_value()
            ),
            totp_enabled=True,
            failed_login_count=0,
            password_changed_at=now,
        )
        await self.repository.add_user(session, user)
        await self.repository.add_audit(
            session, action="CREATE_ADMIN_USER", request_id=meta.request_id,
            trace_id=meta.trace_id, result="SUCCESS", now=now,
            admin_user_id=actor.user.id, target_type="admin_user", target_id=str(user.id),
            ip=meta.ip, user_agent=meta.user_agent, detail={"role": user.role.value},
        )
        await session.commit()
        return {
            "user": self._as_dict(user),
            "totpSecret": secret,
            "provisioningUri": pyotp.TOTP(secret).provisioning_uri(
                name=user.username, issuer_name="PMSystem License Admin"
            ),
            "enrollmentVisibleOnce": True,
        }

    async def set_status(
        self, session: AsyncSession, actor: AuthenticatedAdmin, user_id: UUID,
        status: AdminStatus, request: AdminStatusRequest, meta: RequestMeta,
    ) -> dict:
        if actor.user.id == user_id and status == AdminStatus.DISABLED:
            raise LicenseServiceError(ErrorCode.INVALID_STATE, "不能禁用当前登录账号")
        user = await self.repository.get_user(session, user_id)
        if user is None:
            raise LicenseServiceError(ErrorCode.RESOURCE_NOT_FOUND, "管理员不存在")
        now = datetime.now(timezone.utc)
        user.status = status
        if status == AdminStatus.DISABLED:
            await self.repository.revoke_user_sessions(session, user.id, now)
        await self.repository.add_audit(
            session, action=f"{status.value}_ADMIN_USER", request_id=meta.request_id,
            trace_id=meta.trace_id, result="SUCCESS", now=now,
            admin_user_id=actor.user.id, target_type="admin_user", target_id=str(user.id),
            ip=meta.ip, user_agent=meta.user_agent,
            detail={"reason": request.reason, "status": status.value},
        )
        await session.commit()
        return self._as_dict(user)

    @staticmethod
    def _as_dict(user: AdminUser) -> dict:
        return {
            "id": str(user.id), "username": user.username,
            "displayName": user.display_name, "role": user.role.value,
            "status": user.status.value,
            "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
            "createdAt": user.created_at.isoformat() if user.created_at else None,
        }
