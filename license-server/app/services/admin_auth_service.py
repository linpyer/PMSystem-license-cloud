from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    decrypt_totp_secret,
    hash_admin_password,
    hash_admin_token,
    mask_username,
    new_session_tokens,
    password_needs_rehash,
    verify_admin_password,
    verify_totp,
)
from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.db.models import AdminSession, AdminUser
from app.db.models.enums import AdminSessionStatus, AdminStatus
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import AdminLoginRequest, AdminTotpRequest, ChangePasswordRequest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RequestMeta:
    trace_id: str
    request_id: str
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class AuthenticatedAdmin:
    user: AdminUser
    session: AdminSession


@dataclass(frozen=True, slots=True)
class LoginChallenge:
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LoginSuccess:
    session_token: str
    csrf_token: str
    user: AdminUser
    expires_at: datetime


class AdminAuthService:
    def __init__(self, settings: Settings, repository: AdminRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or AdminRepository()

    @property
    def _session_secret(self) -> str:
        return self.settings.admin_session_secret.get_secret_value()

    async def login(
        self, session: AsyncSession, request: AdminLoginRequest, meta: RequestMeta
    ) -> LoginChallenge:
        now = utc_now()
        username = request.username.strip().lower()
        user = await self.repository.get_user_by_username(session, username)
        ip_failures = await self.repository.recent_ip_failures(
            session, meta.ip, now, self.settings.admin_lockout_minutes
        )
        if ip_failures >= self.settings.admin_login_max_failures * 3:
            await self._record_attempt(session, user, username, "PASSWORD", "FAILED", meta, now)
            await session.commit()
            raise LicenseServiceError(ErrorCode.RATE_LIMITED, "登录尝试过于频繁，请稍后再试")

        password_valid = verify_admin_password(request.password, user.password_hash if user else None)
        locked = bool(user and user.locked_until and user.locked_until > now)
        active = bool(user and user.status == AdminStatus.ACTIVE)
        if not user or not password_valid or locked or not active:
            if user and not locked:
                user.failed_login_count += 1
                if user.failed_login_count >= self.settings.admin_login_max_failures:
                    user.locked_until = now + timedelta(minutes=self.settings.admin_lockout_minutes)
            await self._record_attempt(session, user, username, "PASSWORD", "FAILED", meta, now)
            await session.commit()
            code = ErrorCode.ADMIN_ACCOUNT_LOCKED if locked else ErrorCode.ADMIN_INVALID_CREDENTIALS
            raise LicenseServiceError(code, "用户名、密码或动态验证码不正确")

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_admin_password(request.password)
        tokens = new_session_tokens()
        expires_at = now + timedelta(minutes=5)
        record = AdminSession(
            admin_user_id=user.id,
            token_hash=hash_admin_token(tokens.session, self._session_secret),
            csrf_token_hash=None,
            status=AdminSessionStatus.PENDING_TOTP,
            ip=meta.ip,
            user_agent=meta.user_agent,
            expires_at=expires_at,
            created_at=now,
            last_seen_at=now,
        )
        await self.repository.add_session(session, record)
        await self._record_attempt(session, user, username, "PASSWORD", "SUCCESS", meta, now)
        await session.commit()
        return LoginChallenge(tokens.session, expires_at)

    async def verify_totp(
        self, session: AsyncSession, request: AdminTotpRequest, meta: RequestMeta
    ) -> LoginSuccess:
        now = utc_now()
        challenge_hash = hash_admin_token(request.challenge, self._session_secret)
        record = await self.repository.get_session_by_hash(session, challenge_hash, for_update=True)
        if (
            record is None
            or record.status != AdminSessionStatus.PENDING_TOTP
            or record.expires_at <= now
        ):
            raise LicenseServiceError(ErrorCode.ADMIN_TOTP_REQUIRED, "登录验证已失效，请重新登录")
        user = await self.repository.get_user(session, record.admin_user_id)
        if user is None or user.status != AdminStatus.ACTIVE:
            raise LicenseServiceError(ErrorCode.ADMIN_INVALID_CREDENTIALS, "用户名、密码或动态验证码不正确")
        secret = decrypt_totp_secret(
            user.totp_secret_encrypted,
            self.settings.admin_totp_encryption_key.get_secret_value(),
        )
        valid, counter = verify_totp(request.code, secret, now_timestamp=now.timestamp())
        reused = counter is not None and user.last_totp_counter is not None and counter <= user.last_totp_counter
        if not valid or reused:
            user.failed_login_count += 1
            if user.failed_login_count >= self.settings.admin_login_max_failures:
                user.locked_until = now + timedelta(minutes=self.settings.admin_lockout_minutes)
            await self._record_attempt(session, user, user.username, "TOTP", "FAILED", meta, now)
            await session.commit()
            raise LicenseServiceError(ErrorCode.ADMIN_INVALID_CREDENTIALS, "用户名、密码或动态验证码不正确")

        tokens = new_session_tokens()
        record.token_hash = hash_admin_token(tokens.session, self._session_secret)
        record.csrf_token_hash = hash_admin_token(tokens.csrf, self._session_secret)
        record.status = AdminSessionStatus.ACTIVE
        record.created_at = now
        record.last_seen_at = now
        record.expires_at = now + timedelta(hours=self.settings.admin_session_max_hours)
        record.ip = meta.ip
        record.user_agent = meta.user_agent
        user.last_totp_counter = counter
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        await self._record_attempt(session, user, user.username, "TOTP", "SUCCESS", meta, now)
        await self.repository.add_audit(
            session,
            action="LOGIN_SUCCESS",
            request_id=meta.request_id,
            trace_id=meta.trace_id,
            result="SUCCESS",
            now=now,
            admin_user_id=user.id,
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
        await session.commit()
        return LoginSuccess(tokens.session, tokens.csrf, user, record.expires_at)

    async def authenticate(
        self, session: AsyncSession, token: str | None, *, touch: bool = True
    ) -> AuthenticatedAdmin:
        if not token:
            raise LicenseServiceError(ErrorCode.ADMIN_AUTH_REQUIRED, "请先登录")
        now = utc_now()
        record = await self.repository.get_session_by_hash(
            session, hash_admin_token(token, self._session_secret), for_update=touch
        )
        if record is None or record.status != AdminSessionStatus.ACTIVE or record.expires_at <= now:
            raise LicenseServiceError(ErrorCode.ADMIN_AUTH_REQUIRED, "会话已过期，请重新登录")
        if record.last_seen_at + timedelta(minutes=self.settings.admin_session_idle_minutes) <= now:
            record.status = AdminSessionStatus.REVOKED
            record.revoked_at = now
            await session.commit()
            raise LicenseServiceError(ErrorCode.ADMIN_AUTH_REQUIRED, "会话已过期，请重新登录")
        user = await self.repository.get_user(session, record.admin_user_id)
        if user is None or user.status != AdminStatus.ACTIVE:
            record.status = AdminSessionStatus.REVOKED
            record.revoked_at = now
            await session.commit()
            raise LicenseServiceError(ErrorCode.ADMIN_AUTH_REQUIRED, "管理员账号不可用")
        if touch:
            record.last_seen_at = now
            await session.commit()
        return AuthenticatedAdmin(user, record)

    def verify_csrf(self, auth: AuthenticatedAdmin, csrf_token: str | None) -> None:
        if not csrf_token or not auth.session.csrf_token_hash:
            raise LicenseServiceError(ErrorCode.CSRF_FAILED, "CSRF验证失败")
        actual = hash_admin_token(csrf_token, self._session_secret)
        if not hmac_compare(actual, auth.session.csrf_token_hash):
            raise LicenseServiceError(ErrorCode.CSRF_FAILED, "CSRF验证失败")

    async def logout(self, session: AsyncSession, auth: AuthenticatedAdmin, meta: RequestMeta) -> None:
        now = utc_now()
        auth.session.status = AdminSessionStatus.REVOKED
        auth.session.revoked_at = now
        await self.repository.add_audit(
            session, action="LOGOUT", request_id=meta.request_id, trace_id=meta.trace_id,
            result="SUCCESS", now=now, admin_user_id=auth.user.id, ip=meta.ip,
            user_agent=meta.user_agent,
        )
        await session.commit()

    async def change_password(
        self, session: AsyncSession, auth: AuthenticatedAdmin,
        request: ChangePasswordRequest, meta: RequestMeta,
    ) -> None:
        if not verify_admin_password(request.current_password, auth.user.password_hash):
            raise LicenseServiceError(ErrorCode.ADMIN_INVALID_CREDENTIALS, "当前密码不正确")
        now = utc_now()
        auth.user.password_hash = hash_admin_password(request.new_password)
        auth.user.password_changed_at = now
        await self.repository.revoke_user_sessions(session, auth.user.id, now, except_id=auth.session.id)
        await self.repository.add_audit(
            session, action="CHANGE_PASSWORD", request_id=meta.request_id,
            trace_id=meta.trace_id, result="SUCCESS", now=now,
            admin_user_id=auth.user.id, ip=meta.ip, user_agent=meta.user_agent,
        )
        await session.commit()

    async def _record_attempt(
        self, session: AsyncSession, user: AdminUser | None, username: str,
        stage: str, result: str, meta: RequestMeta, now: datetime,
    ) -> None:
        await self.repository.add_login_attempt(
            session, username_masked=mask_username(username), stage=stage, result=result,
            ip=meta.ip, now=now, admin_user_id=user.id if user else None,
        )


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
