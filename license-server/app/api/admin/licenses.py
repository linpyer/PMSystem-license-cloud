from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import (
    get_admin_management_service,
    request_meta,
    require_admin,
    require_roles,
)
from app.api.dependencies import get_session
from app.db.models.enums import AdminRole, LicenseStatus, LicenseType
from app.schemas.admin import (
    LicenseBatchCreateRequest,
    LicenseCreateRequest,
    LicenseListQuery,
    LicenseUpdateRequest,
    ReasonRequest,
)
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_management_service import AdminManagementService


router = APIRouter(tags=["admin-licenses"])
writer = require_roles(AdminRole.OWNER, AdminRole.ADMIN)


@router.get("/licenses")
async def list_licenses(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize"),
    keyword: str | None = None,
    license_type: LicenseType | None = Query(None, alias="licenseType"),
    status: LicenseStatus | None = None,
    bound: bool | None = None,
    sort_by: str = Query("createdAt", alias="sortBy"),
    sort_order: str = Query("desc", alias="sortOrder"),
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
    expires_from: datetime | None = Query(None, alias="expiresFrom"),
    expires_to: datetime | None = Query(None, alias="expiresTo"),
    verified_from: datetime | None = Query(None, alias="verifiedFrom"),
    verified_to: datetime | None = Query(None, alias="verifiedTo"),
    session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    query = LicenseListQuery(
        page=page, page_size=page_size, keyword=keyword, license_type=license_type,
        status=status, bound=bound, sort_by=sort_by, sort_order=sort_order,
        created_from=created_from, created_to=created_to,
        expires_from=expires_from, expires_to=expires_to,
        verified_from=verified_from, verified_to=verified_to,
    )
    return {"success": True, "traceId": request.state.trace_id, **await service.list_licenses(session, query)}


@router.post("/licenses")
async def create_license(
    payload: LicenseCreateRequest, request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(writer),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> JSONResponse:
    result = await service.create_licenses(session, auth, payload, request_meta(request))
    response = JSONResponse(result.body, status_code=result.status_code)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@router.post("/licenses/batch")
async def create_license_batch(
    payload: LicenseBatchCreateRequest, request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(writer),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> JSONResponse:
    result = await service.create_licenses(session, auth, payload, request_meta(request))
    response = JSONResponse(result.body, status_code=result.status_code)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@router.get("/licenses/{license_id}")
async def license_detail(
    license_id: UUID, request: Request,
    session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "license": await service.license_detail(session, license_id)}


@router.patch("/licenses/{license_id}")
async def update_license(
    license_id: UUID, payload: LicenseUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(writer),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    detail = await service.update_license(session, auth, license_id, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "license": detail}


def _status_route(action: str):
    async def handler(
        license_id: UUID, payload: ReasonRequest, request: Request,
        session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(writer),
        service: AdminManagementService = Depends(get_admin_management_service),
    ) -> dict:
        result = await service.change_status(session, auth, license_id, action, payload, request_meta(request))
        return {"success": True, "traceId": request.state.trace_id, **result}
    return handler


router.add_api_route("/licenses/{license_id}/disable", _status_route("disable"), methods=["POST"])
router.add_api_route("/licenses/{license_id}/enable", _status_route("enable"), methods=["POST"])
router.add_api_route("/licenses/{license_id}/revoke", _status_route("revoke"), methods=["POST"])


@router.get("/licenses/{license_id}/bindings")
async def license_bindings(
    license_id: UUID, request: Request,
    session: AsyncSession = Depends(get_session), _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    detail = await service.license_detail(session, license_id)
    return {"success": True, "traceId": request.state.trace_id, "items": detail["bindings"]}


@router.post("/bindings/{binding_id}/deactivate")
async def deactivate_binding(
    binding_id: UUID, payload: ReasonRequest, request: Request,
    session: AsyncSession = Depends(get_session), auth: AuthenticatedAdmin = Depends(writer),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    result = await service.deactivate_binding(session, auth, binding_id, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, **result}
