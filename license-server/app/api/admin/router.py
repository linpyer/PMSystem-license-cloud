from fastapi import APIRouter

from app.api.admin.audit import router as audit_router
from app.api.admin.auth import router as auth_router
from app.api.admin.dashboard import router as dashboard_router
from app.api.admin.licenses import router as licenses_router
from app.api.admin.versions import router as versions_router
from app.api.admin.users import router as users_router
from app.api.admin.trials import router as trials_router


router = APIRouter(prefix="/admin")
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(licenses_router)
router.include_router(audit_router)
router.include_router(versions_router)
router.include_router(users_router)
router.include_router(trials_router)
