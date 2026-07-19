from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import (
    get_admin_management_service,
    request_meta,
    require_admin,
    require_roles,
)
from app.api.dependencies import get_session
from app.db.models.enums import AdminRole, DeviceTrialStatus
from app.schemas.admin import ReasonRequest, TrialDeleteRequest, TrialExtendRequest, TrialListQuery
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_management_service import AdminManagementService


router = APIRouter(prefix="/trials", tags=["admin-trials"])


@router.get("")
async def list_trials(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize"),
    device_id: str | None = Query(None, alias="deviceId"),
    status: DeviceTrialStatus | None = None,
    app_version: str | None = Query(None, alias="appVersion"),
    converted: bool | None = None,
    started_from: datetime | None = Query(None, alias="startedFrom"),
    started_to: datetime | None = Query(None, alias="startedTo"),
    expires_from: datetime | None = Query(None, alias="expiresFrom"),
    expires_to: datetime | None = Query(None, alias="expiresTo"),
    include_deleted: bool = Query(False, alias="includeDeleted"),
    session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    query = TrialListQuery(
        page=page,
        pageSize=page_size,
        deviceId=device_id,
        status=status,
        appVersion=app_version,
        converted=converted,
        startedFrom=started_from,
        startedTo=started_to,
        expiresFrom=expires_from,
        expiresTo=expires_to,
        includeDeleted=include_deleted,
    )
    return {"success": True, "traceId": request.state.trace_id, **await service.list_trials(session, query)}


@router.get("/{trial_id}")
async def trial_detail(
    trial_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    return {
        "success": True,
        "traceId": request.state.trace_id,
        "trial": await service.trial_detail(session, trial_id),
    }


@router.post("/{trial_id}/disable")
async def disable_trial(
    trial_id: UUID,
    payload: ReasonRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER, AdminRole.ADMIN)),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    result = await service.disable_trial(
        session, auth, trial_id, payload, request_meta(request)
    )
    return {"success": True, "traceId": request.state.trace_id, "trial": result}


@router.post("/{trial_id}/reset")
async def reset_trial(
    trial_id: UUID,
    payload: ReasonRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER)),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    result = await service.reset_trial(session, auth, trial_id, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "trial": result}


@router.post("/{trial_id}/extend")
async def extend_trial(
    trial_id: UUID,
    payload: TrialExtendRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER, AdminRole.ADMIN)),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    result = await service.extend_trial(session, auth, trial_id, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "trial": result}


@router.post("/{trial_id}/delete")
async def delete_trial(
    trial_id: UUID,
    payload: TrialDeleteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER)),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    result = await service.delete_trial(session, auth, trial_id, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "trial": result}
