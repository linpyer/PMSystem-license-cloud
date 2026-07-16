from fastapi import APIRouter

from app.api.admin.router import router as admin_router
from app.api.v1.health import router as health_router
from app.api.v1.licenses import router as licenses_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(licenses_router)
api_router.include_router(admin_router)
