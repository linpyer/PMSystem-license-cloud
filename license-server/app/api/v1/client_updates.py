from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_session
from app.core.config import Settings
from app.services.client_release_service import ClientReleaseService


router = APIRouter(prefix="/client-updates", tags=["client-updates"])


@router.get("/latest")
async def latest_client_update(
    product: Literal["DDREC"],
    edition: Literal["standard", "license"],
    environment: Literal["local", "production"],
    arch: Literal["x64"],
    channel: Literal["stable", "dev"],
    version: str = Query(pattern=r"^\d+\.\d+\.\d+$"),
    build_number: int = Query(alias="buildNumber", ge=1),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    return await ClientReleaseService(settings).latest(
        session, product=product, edition=edition, environment=environment,
        architecture=arch, channel=channel, version=version, build_number=build_number,
    )
