from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.db.models.enums import AdminRole
from app.services.admin_auth_service import AdminAuthService, AuthenticatedAdmin, RequestMeta
from app.services.admin_management_service import AdminManagementService


def get_admin_auth_service(settings: Settings = Depends(get_app_settings)) -> AdminAuthService:
    return AdminAuthService(settings)


def get_admin_management_service(
    settings: Settings = Depends(get_app_settings),
) -> AdminManagementService:
    return AdminManagementService(settings)


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        trace_id=request.state.trace_id,
        request_id=getattr(request.state, "request_id", str(uuid4())),
        ip=getattr(request.state, "client_ip", None),
        user_agent=request.headers.get("user-agent", "")[:500] or None,
    )


async def require_admin(
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: AdminAuthService = Depends(get_admin_auth_service),
) -> AuthenticatedAdmin:
    settings = request.app.state.settings
    token = request.cookies.get(settings.admin_cookie_name)
    auth = await service.authenticate(session, token)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        service.verify_csrf(auth, request.headers.get("x-csrf-token"))
    return auth


def require_roles(*roles: AdminRole) -> Callable:
    async def dependency(auth: AuthenticatedAdmin = Depends(require_admin)) -> AuthenticatedAdmin:
        if auth.user.role not in roles:
            raise LicenseServiceError(ErrorCode.ADMIN_FORBIDDEN, "当前账号无权执行此操作")
        return auth

    return dependency
