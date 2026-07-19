from __future__ import annotations

from datetime import datetime

from app.schemas.base import CamelModel


class HealthResponse(CamelModel):
    service: str
    version: str
    build_commit: str
    status: str
    environment: str
    database: str
    utc_time: datetime


class LivenessResponse(CamelModel):
    service: str
    version: str
    build_commit: str
    environment: str
    status: str
    utc_time: datetime


class ReadinessResponse(HealthResponse):
    signing_key: str
