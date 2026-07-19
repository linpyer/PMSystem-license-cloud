from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_trial_activation_service
from app.schemas.licenses import TrialActivateRequest
from app.services.trial_activation_service import TrialActivationService


router = APIRouter(prefix="/trials", tags=["trials"])


@router.post("/activate")
async def activate_trial(
    payload: TrialActivateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: TrialActivationService = Depends(get_trial_activation_service),
) -> JSONResponse:
    result = await service.activate(
        session,
        payload,
        trace_id=request.state.trace_id,
        ip=getattr(request.state, "client_ip", None),
    )
    response = JSONResponse(status_code=result.status_code, content=result.body)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response
