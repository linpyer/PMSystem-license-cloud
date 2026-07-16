from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import get_admin_management_service, require_admin
from app.api.dependencies import get_session
from app.schemas.admin import AuditQuery
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_management_service import AdminManagementService


router = APIRouter(tags=["admin-audit"])


@router.get("/audit-events")
async def admin_audit(
    request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, alias="pageSize"),
    action: str | None = None, target_id: str | None = Query(None, alias="targetId"),
    admin_user_id: UUID | None = Query(None, alias="adminUserId"),
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
    session: AsyncSession = Depends(get_session), _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    query = AuditQuery(
        page=page, page_size=page_size, action=action, target_id=target_id,
        admin_user_id=admin_user_id, created_from=created_from, created_to=created_to,
    )
    return {"success": True, "traceId": request.state.trace_id, **await service.list_admin_audit(session, query)}


@router.get("/license-events")
async def license_events(
    request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, alias="pageSize"),
    session: AsyncSession = Depends(get_session), _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, **await service.list_license_events(session, page, page_size)}
