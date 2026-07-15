from __future__ import annotations

from datetime import datetime

from app.schemas.base import CamelModel


class HealthResponse(CamelModel):
    service: str
    status: str
    environment: str
    database: str
    utc_time: datetime

