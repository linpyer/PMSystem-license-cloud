from fastapi import APIRouter

from app.api.admin.router import router as admin_router
from app.api.v1.health import router as health_router
from app.api.v1.licenses import router as licenses_router
from app.api.v1.trials import router as trials_router
from app.api.v1.client_updates import router as client_updates_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(licenses_router)
api_router.include_router(trials_router)
api_router.include_router(client_updates_router)
api_router.include_router(admin_router)
