from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import request_meta, require_admin, require_roles
from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.db.models.enums import AdminRole
from app.schemas.client_releases import ClientReleaseDraftRequest, ClientReleaseUpdateRequest
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.client_release_service import ClientReleaseService, serialize_client_release


router = APIRouter(prefix="/client-releases", tags=["admin-client-releases"])


def service(settings: Settings = Depends(get_app_settings)) -> ClientReleaseService:
    return ClientReleaseService(settings)


@router.get("")
async def list_releases(
    request: Request, page: int = Query(1, ge=1), page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: AsyncSession = Depends(get_session), _auth: AuthenticatedAdmin = Depends(require_admin),
    manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, **await manager.list(session, page, page_size)}


@router.get("/{release_id}")
async def get_release(
    release_id: UUID, request: Request, session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin), manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "release": serialize_client_release(await manager.get(session, release_id))}


@router.post("")
async def create_release(
    payload: ClientReleaseDraftRequest, request: Request, session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER, AdminRole.ADMIN)),
    manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "release": await manager.create_draft(session, auth, payload, request_meta(request))}


@router.patch("/{release_id}")
async def edit_release(
    release_id: UUID, payload: ClientReleaseUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER, AdminRole.ADMIN)),
    manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "release": await manager.edit(session, auth, release_id, payload, request_meta(request))}


@router.post("/{release_id}/publish")
async def publish_release(
    release_id: UUID, request: Request, session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER)),
    manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "release": await manager.publish(session, auth, release_id, request_meta(request))}


@router.post("/{release_id}/withdraw")
async def withdraw_release(
    release_id: UUID, request: Request, session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER)),
    manager: ClientReleaseService = Depends(service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "release": await manager.withdraw(session, auth, release_id, request_meta(request))}
