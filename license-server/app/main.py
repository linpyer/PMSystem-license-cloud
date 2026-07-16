from __future__ import annotations

import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, LicenseServiceError
from app.core.logging import configure_logging, get_logger
from app.core.signing import Ed25519Signer
from app.db.session import create_database_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.settings = resolved_settings
        application.state.database = create_database_runtime(resolved_settings)
        application.state.signer = Ed25519Signer.from_pem_file(
            resolved_settings.signing_private_key_path,
            resolved_settings.signing_key_id,
        )
        yield
        await application.state.database.engine.dispose()

    application = FastAPI(
        title="PMSystem License API",
        version="1.0",
        docs_url="/docs" if resolved_settings.openapi_enabled else None,
        redoc_url="/redoc" if resolved_settings.openapi_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.openapi_enabled else None,
        lifespan=lifespan,
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
        trace_id = request.headers.get("x-trace-id", str(uuid4()))[:80]
        request.state.trace_id = trace_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        logger.info(
            "request_completed",
            trace_id=trace_id,
            request_id=request.headers.get("x-request-id"),
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    @application.exception_handler(LicenseServiceError)
    async def service_error_handler(request: Request, exc: LicenseServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.response_body(request.state.trace_id),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _exc: RequestValidationError) -> JSONResponse:
        error = LicenseServiceError(ErrorCode.INVALID_REQUEST, "Request validation failed")
        return JSONResponse(
            status_code=error.status_code,
            content=error.response_body(request.state.trace_id),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_request_error",
            trace_id=request.state.trace_id,
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
            content=error.response_body(request.state.trace_id),
        )

    application.include_router(api_router)
    return application


app = create_app()
