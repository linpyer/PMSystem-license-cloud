from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import CamelModel


class RequestIdentity(CamelModel):
    request_id: str = Field(min_length=8, max_length=80)


class ActivateRequest(RequestIdentity):
    license_code: str = Field(min_length=23, max_length=23)
    device_id: str = Field(min_length=8, max_length=200)
    fingerprint_version: str = Field(min_length=1, max_length=40)
    device_name: str | None = Field(default=None, max_length=200)
    os_version: str | None = Field(default=None, max_length=160)
    app_version: str = Field(min_length=1, max_length=40)
    client_time: datetime | None = None

    @field_validator("license_code")
    @classmethod
    def uppercase_code(cls, value: str) -> str:
        return value.upper()


class CredentialRequest(RequestIdentity):
    license_id: UUID
    device_id: str = Field(min_length=8, max_length=200)
    credential: str = Field(min_length=32, max_length=200)
    app_version: str = Field(min_length=1, max_length=40)


class VerifyRequest(CredentialRequest):
    client_time: datetime | None = None


class RefreshRequest(CredentialRequest):
    client_time: datetime | None = None


class DeactivateRequest(RequestIdentity):
    license_id: UUID
    device_id: str = Field(min_length=8, max_length=200)
    credential: str = Field(min_length=32, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
