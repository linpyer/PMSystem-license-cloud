from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.signing import Ed25519Signer
from app.repositories.event_repository import EventRepository
from app.repositories.idempotency_repository import IdempotencyRepository
from app.repositories.license_repository import LicenseRepository
from app.services.activation_service import ActivationService
from app.services.deactivation_service import DeactivationService
from app.services.idempotency_service import IdempotencyService
from app.services.license_signing_service import LicenseSigningService
from app.services.verification_service import VerificationService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_signer(request: Request) -> Ed25519Signer:
    return request.app.state.signer


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.database.session_factory() as session:
        yield session


def _idempotency(settings: Settings) -> IdempotencyService:
    return IdempotencyService(IdempotencyRepository(), settings.idempotency_ttl_hours)


def get_activation_service(
    settings: Settings = Depends(get_app_settings),
    signer: Ed25519Signer = Depends(get_signer),
) -> ActivationService:
    signing = LicenseSigningService(settings, signer)
    return ActivationService(
        settings,
        signing,
        licenses=LicenseRepository(),
        events=EventRepository(),
        idempotency=_idempotency(settings),
    )


def get_verification_service(
    settings: Settings = Depends(get_app_settings),
    signer: Ed25519Signer = Depends(get_signer),
) -> VerificationService:
    signing = LicenseSigningService(settings, signer)
    return VerificationService(
        settings,
        signing,
        licenses=LicenseRepository(),
        events=EventRepository(),
        idempotency=_idempotency(settings),
    )


def get_deactivation_service(
    settings: Settings = Depends(get_app_settings),
) -> DeactivationService:
    return DeactivationService(
        settings,
        licenses=LicenseRepository(),
        events=EventRepository(),
        idempotency=_idempotency(settings),
    )

