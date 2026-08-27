from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.logging import configure_logging, get_logger
from app.core.network import resolve_client_ip
from app.core.product_identity import PRODUCT_DISPLAY_NAME
from app.core.rate_limiting import ApplicationRateLimiter
from app.core.signing import Ed25519Signer
from app.db.session import create_database_runtime
from app.repositories.signing_key_repository import SigningKeyRepository


def _safe_header(value: str | None, fallback: str) -> str:
    cleaned = "".join(char for char in str(value or "") if char.isalnum() or char in "-_.:")
    return cleaned[:80] or fallback


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger().bind(
        service="ddrec-license-server",
        environment=resolved_settings.environment,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.settings = resolved_settings
        application.state.database = create_database_runtime(resolved_settings)
        application.state.signer = Ed25519Signer.from_pem_file(
            resolved_settings.signing_private_key_path,
            resolved_settings.signing_key_id,
        )
        application.state.rate_limiter = ApplicationRateLimiter()
        async with application.state.database.session_factory() as session:
            await SigningKeyRepository().ensure_active_key(
                session,
                key_id=application.state.signer.key_id,
                public_key=application.state.signer.public_key_base64url,
                now=datetime.now(timezone.utc),
            )
            await session.commit()
        yield
        await application.state.database.engine.dispose()

    application = FastAPI(
        title=f"{PRODUCT_DISPLAY_NAME} License API",
        version=resolved_settings.service_version,
        debug=False,
        docs_url="/docs" if resolved_settings.openapi_enabled else None,
        redoc_url="/redoc" if resolved_settings.openapi_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.openapi_enabled else None,
        lifespan=lifespan,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=resolved_settings.allowed_hosts,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.admin_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "X-Trace-ID"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        trace_id = _safe_header(request.headers.get("x-trace-id"), str(uuid4()))
        request_id = _safe_header(request.headers.get("x-request-id"), str(uuid4()))
        request.state.trace_id = trace_id
        request.state.request_id = request_id
        request.state.client_ip = resolve_client_ip(
            request, resolved_settings.trusted_proxy_count
        )
        started = time.perf_counter()
        try:
            declared_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            declared_length = resolved_settings.request_max_bytes + 1
        if declared_length > resolved_settings.request_max_bytes:
            error = LicenseServiceError(ErrorCode.INVALID_REQUEST, "Request body is too large")
            return JSONResponse(status_code=413, content=error.response_body(trace_id))
        body = await request.body()
        if len(body) > resolved_settings.request_max_bytes:
            error = LicenseServiceError(ErrorCode.INVALID_REQUEST, "Request body is too large")
            return JSONResponse(status_code=413, content=error.response_body(trace_id))
        try:
            if resolved_settings.rate_limit_enabled:
                await application.state.rate_limiter.enforce(
                    request, body, request.state.client_ip
                )
            response = await call_next(request)
        except LicenseServiceError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content=exc.response_body(trace_id),
            )
        response.headers["X-Trace-ID"] = trace_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request_completed",
            trace_id=trace_id,
            request_id=request_id,
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    @application.exception_handler(LicenseServiceError)
    async def service_error_handler(request: Request, exc: LicenseServiceError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", str(uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.response_body(trace_id),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _exc: RequestValidationError) -> JSONResponse:
        error = LicenseServiceError(ErrorCode.INVALID_REQUEST, "Request validation failed")
        return JSONResponse(
            status_code=error.status_code,
            content=error.response_body(getattr(request.state, "trace_id", str(uuid4()))),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", str(uuid4()))
        logger.exception(
            "unhandled_request_error",
            trace_id=trace_id,
            endpoint=request.url.path,
            error_type=type(exc).__name__,
        )
        error = LicenseServiceError(
            ErrorCode.SERVER_TEMPORARILY_UNAVAILABLE,
            "The license service is temporarily unavailable",
            retryable=True,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=error.response_body(trace_id),
        )

    application.include_router(api_router)
    return application


app = create_app()
