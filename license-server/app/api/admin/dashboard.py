from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import get_admin_management_service, require_admin
from app.api.dependencies import get_session
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_management_service import AdminManagementService


router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])


@router.get("/summary")
async def summary(
    request: Request, session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, **await service.dashboard(session)}
