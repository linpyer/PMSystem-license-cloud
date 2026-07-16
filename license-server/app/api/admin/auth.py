from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import (
    get_admin_auth_service,
    request_meta,
    require_admin,
)
from app.api.dependencies import get_session
from app.schemas.admin import AdminLoginRequest, AdminTotpRequest, ChangePasswordRequest
from app.services.admin_auth_service import AdminAuthService, AuthenticatedAdmin


router = APIRouter(prefix="/auth", tags=["admin-auth"])


def _user_body(auth_user) -> dict:
    return {
        "id": str(auth_user.id),
        "username": auth_user.username,
        "displayName": auth_user.display_name,
        "role": auth_user.role.value,
    }


@router.post("/login")
async def login(
    payload: AdminLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: AdminAuthService = Depends(get_admin_auth_service),
) -> dict:
    challenge = await service.login(session, payload, request_meta(request))
    return {
        "success": True,
        "traceId": request.state.trace_id,
        "totpRequired": True,
        "challenge": challenge.token,
        "expiresAt": challenge.expires_at.isoformat(),
    }


@router.post("/totp/verify")
async def totp_verify(
    payload: AdminTotpRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    service: AdminAuthService = Depends(get_admin_auth_service),
) -> dict:
    result = await service.verify_totp(session, payload, request_meta(request))
    settings = request.app.state.settings
    max_age = int((result.expires_at - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        settings.admin_cookie_name,
        result.session_token,
        max_age=max(1, max_age),
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/api/v1/admin",
    )
    response.set_cookie(
        "pms_admin_csrf",
        result.csrf_token,
        max_age=max(1, max_age),
        httponly=False,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"success": True, "traceId": request.state.trace_id, "user": _user_body(result.user)}


@router.get("/me")
async def me(request: Request, auth: AuthenticatedAdmin = Depends(require_admin)) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "user": _user_body(auth.user)}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminAuthService = Depends(get_admin_auth_service),
) -> dict:
    await service.logout(session, auth, request_meta(request))
    response.delete_cookie(request.app.state.settings.admin_cookie_name, path="/api/v1/admin")
    response.delete_cookie("pms_admin_csrf", path="/")
    return {"success": True, "traceId": request.state.trace_id}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminAuthService = Depends(get_admin_auth_service),
) -> dict:
    await service.change_password(session, auth, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id}
