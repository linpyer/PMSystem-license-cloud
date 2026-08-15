from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.db.models.enums import SigningKeyStatus
from app.repositories.signing_key_repository import SigningKeyRepository
from app.schemas.health import HealthResponse, LivenessResponse, ReadinessResponse


router = APIRouter(tags=["health"])


def _base(settings: Settings) -> dict:
    return {
        "service": "ddrec-license-server",
        "version": settings.service_version,
        "build_commit": settings.build_commit,
        "environment": settings.environment,
        "utc_time": datetime.now(timezone.utc),
    }


@router.get("/health/live", response_model=LivenessResponse)
async def live(settings: Settings = Depends(get_app_settings)) -> LivenessResponse:
    return LivenessResponse(**_base(settings), status="ok")


async def _readiness(
    request: Request, session: AsyncSession, settings: Settings
) -> tuple[str, str, str]:
    database_status = "ok"
    signing_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"

    try:
        key = await SigningKeyRepository().get(session, settings.signing_key_id)
        signer = request.app.state.signer
        if (
            key is None
            or key.status != SigningKeyStatus.ACTIVE
            or key.public_key != signer.public_key_base64url
            or not settings.signing_private_key_path.is_file()
        ):
            signing_status = "unavailable"
    except Exception:
        signing_status = "unavailable"
    status = "ok" if database_status == signing_status == "ok" else "degraded"
    return status, database_status, signing_status


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    status, database_status, signing_status = await _readiness(request, session, settings)
    body = ReadinessResponse(
        **_base(settings),
        status=status,
        database=database_status,
        signing_key=signing_status,
    )
    if status != "ok":
        return JSONResponse(status_code=503, content=body.model_dump(mode="json", by_alias=True))
    return body


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> HealthResponse:
    service_status, database_status, _signing_status = await _readiness(
        request, session, settings
    )
    return HealthResponse(
        **_base(settings),
        status=service_status,
        database=database_status,
    )
