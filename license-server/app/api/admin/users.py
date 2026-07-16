from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import request_meta, require_roles
from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.db.models.enums import AdminRole, AdminStatus
from app.schemas.admin import AdminCreateRequest, AdminStatusRequest
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_user_service import AdminUserService


router = APIRouter(prefix="/users", tags=["admin-users"])
owner = require_roles(AdminRole.OWNER)


def get_service(settings: Settings = Depends(get_app_settings)) -> AdminUserService:
    return AdminUserService(settings)


@router.get("")
async def list_users(
    request: Request, session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(owner),
    service: AdminUserService = Depends(get_service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "items": await service.list_users(session)}


@router.post("")
async def create_user(
    payload: AdminCreateRequest, request: Request,
    session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(owner),
    service: AdminUserService = Depends(get_service),
) -> dict:
    result = await service.create_user(session, auth, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, **result}


@router.post("/{user_id}/disable")
async def disable_user(
    user_id: UUID, payload: AdminStatusRequest, request: Request,
    session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(owner),
    service: AdminUserService = Depends(get_service),
) -> dict:
    user = await service.set_status(session, auth, user_id, AdminStatus.DISABLED, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "user": user}


@router.post("/{user_id}/enable")
async def enable_user(
    user_id: UUID, payload: AdminStatusRequest, request: Request,
    session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(owner),
    service: AdminUserService = Depends(get_service),
) -> dict:
    user = await service.set_status(session, auth, user_id, AdminStatus.ACTIVE, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "user": user}
