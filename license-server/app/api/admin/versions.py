from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.dependencies import get_admin_management_service, request_meta, require_admin, require_roles
from app.api.dependencies import get_session
from app.db.models.enums import AdminRole
from app.schemas.admin import VersionPolicyRequest
from app.services.admin_auth_service import AuthenticatedAdmin
from app.services.admin_management_service import AdminManagementService


router = APIRouter(prefix="/version-policy", tags=["admin-version-policy"])


@router.get("")
async def get_policy(
    request: Request, session: AsyncSession = Depends(get_session),
    _auth: AuthenticatedAdmin = Depends(require_admin),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    return {"success": True, "traceId": request.state.trace_id, "policy": await service.get_version_policy(session)}


@router.put("")
async def save_policy(
    payload: VersionPolicyRequest, request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthenticatedAdmin = Depends(require_roles(AdminRole.OWNER)),
    service: AdminManagementService = Depends(get_admin_management_service),
) -> dict:
    policy = await service.save_version_policy(session, auth, payload, request_meta(request))
    return {"success": True, "traceId": request.state.trace_id, "policy": policy}
