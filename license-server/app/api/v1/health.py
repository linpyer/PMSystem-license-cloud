from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.schemas.health import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> HealthResponse:
    database_status = "ok"
    service_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
        service_status = "degraded"
    return HealthResponse(
        service="pmsystem-license-server",
        status=service_status,
        environment=settings.environment,
        database=database_status,
        utc_time=datetime.now(timezone.utc),
    )

