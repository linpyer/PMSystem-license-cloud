from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_activation_service,
    get_deactivation_service,
    get_session,
    get_verification_service,
)
from app.schemas.licenses import ActivateRequest, DeactivateRequest, RefreshRequest, VerifyRequest
from app.services.activation_service import ActivationService
from app.services.deactivation_service import DeactivationService
from app.services.idempotency_service import ServiceResult
from app.services.verification_service import VerificationService


router = APIRouter(prefix="/licenses", tags=["licenses"])


def _client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None)


def _response(result: ServiceResult) -> JSONResponse:
    response = JSONResponse(status_code=result.status_code, content=result.body)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


@router.post("/activate")
async def activate(
    payload: ActivateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: ActivationService = Depends(get_activation_service),
) -> JSONResponse:
    result = await service.activate(
        session, payload, trace_id=request.state.trace_id, ip=_client_ip(request)
    )
    return _response(result)


@router.post("/verify")
async def verify(
    payload: VerifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: VerificationService = Depends(get_verification_service),
) -> JSONResponse:
    result = await service.verify(
        session, payload, trace_id=request.state.trace_id, ip=_client_ip(request)
    )
    return _response(result)


@router.post("/refresh")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: VerificationService = Depends(get_verification_service),
) -> JSONResponse:
    result = await service.refresh(
        session, payload, trace_id=request.state.trace_id, ip=_client_ip(request)
    )
    return _response(result)


@router.post("/deactivate")
async def deactivate(
    payload: DeactivateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: DeactivationService = Depends(get_deactivation_service),
) -> JSONResponse:
    result = await service.deactivate(
        session, payload, trace_id=request.state.trace_id, ip=_client_ip(request)
    )
    return _response(result)
