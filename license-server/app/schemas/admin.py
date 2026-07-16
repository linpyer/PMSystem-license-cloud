from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from app.db.models.enums import AdminRole, LicenseStatus, LicenseType
from app.schemas.base import CamelModel


class AdminLoginRequest(CamelModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AdminTotpRequest(CamelModel):
    challenge: str = Field(min_length=32, max_length=200)
    code: str = Field(pattern=r"^\d{6}$")


class ChangePasswordRequest(CamelModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class LicenseCreateRequest(CamelModel):
    request_id: str = Field(min_length=8, max_length=80)
    license_type: LicenseType
    expires_at: datetime | None = None
    customer_name: str | None = Field(default=None, max_length=160)
    customer_contact: str | None = Field(default=None, max_length=240)
    remark: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_expiration(self) -> "LicenseCreateRequest":
        if self.license_type == LicenseType.FIXED_DATE and self.expires_at is None:
            raise ValueError("fixed_date requires expiresAt")
        if self.license_type != LicenseType.FIXED_DATE and self.expires_at is not None:
            raise ValueError("expiresAt is only valid for fixed_date")
        return self


class LicenseBatchCreateRequest(LicenseCreateRequest):
    quantity: int = Field(ge=1, le=100)


class LicenseUpdateRequest(CamelModel):
    customer_name: str | None = Field(default=None, max_length=160)
    customer_contact: str | None = Field(default=None, max_length=240)
    remark: str | None = Field(default=None, max_length=2000)


class ReasonRequest(CamelModel):
    reason: str = Field(min_length=3, max_length=500)


class VersionPolicyRequest(CamelModel):
    recommended_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    minimum_supported_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    download_url: AnyHttpUrl | None = None
    release_notes: str | None = Field(default=None, max_length=10000)


class LicenseListQuery(CamelModel):
    page: int = Field(default=1, ge=1)
    page_size: Literal[20, 50, 100] = 20
    keyword: str | None = Field(default=None, max_length=200)
    license_type: LicenseType | None = None
    status: LicenseStatus | None = None
    bound: bool | None = None
    sort_by: Literal["createdAt", "expiresAt", "activatedAt", "lastVerifiedAt"] = "createdAt"
    sort_order: Literal["asc", "desc"] = "desc"
    created_from: datetime | None = None
    created_to: datetime | None = None
    expires_from: datetime | None = None
    expires_to: datetime | None = None
    verified_from: datetime | None = None
    verified_to: datetime | None = None


class AuditQuery(CamelModel):
    page: int = Field(default=1, ge=1)
    page_size: Literal[20, 50, 100] = 20
    action: str | None = Field(default=None, max_length=80)
    target_id: str | None = Field(default=None, max_length=120)
    admin_user_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


class AdminCreateRequest(CamelModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    role: AdminRole
    password: str = Field(min_length=12, max_length=256)


class AdminStatusRequest(CamelModel):
    reason: str = Field(min_length=3, max_length=500)
