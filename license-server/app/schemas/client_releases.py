from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core.product_identity import ACTIVE_UPDATE_PROTOCOL_PRODUCT
from app.schemas.base import CamelModel


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
FILE_RE = re.compile(r"^iVRec-\d+\.\d+\.\d+-(?:standard|license)-Setup\.exe$")


class ClientReleaseDraftRequest(CamelModel):
    product: Literal[ACTIVE_UPDATE_PROTOCOL_PRODUCT] = ACTIVE_UPDATE_PROTOCOL_PRODUCT
    version: str
    build_number: int = Field(gt=0)
    git_commit: str
    edition: Literal["standard", "license"]
    environment: Literal["production"]
    architecture: Literal["x64"] = "x64"
    channel: Literal["stable"]
    title: str = Field(min_length=1, max_length=200)
    # Retained for wire/database compatibility; new Admin builds intentionally omit it.
    release_notes: str = Field(default="", max_length=20_000)
    file_name: str = Field(max_length=260)
    download_path: str = Field(min_length=1, max_length=1000)
    file_size: int = Field(gt=0)
    sha256: str
    signature: str = Field(min_length=80, max_length=200)
    mandatory: bool = False
    published_at: datetime

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not VERSION_RE.fullmatch(value):
            raise ValueError("version must be a three-part semantic version")
        return value

    @field_validator("git_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if not COMMIT_RE.fullmatch(value):
            raise ValueError("gitCommit must be a hexadecimal Git commit")
        return value.lower()

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must contain 64 hexadecimal characters")
        return value.upper()

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        if not FILE_RE.fullmatch(value):
            raise ValueError("fileName does not follow the iVRec installer naming convention")
        return value

    @field_validator("download_path")
    @classmethod
    def validate_download_path(cls, value: str) -> str:
        if not value.startswith("/releases/") or value.endswith(".part") or ".." in value:
            raise ValueError("downloadPath must be an immutable /releases/ path")
        return value

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("publishedAt must include a timezone")
        return value

    @model_validator(mode="after")
    def enforce_release_lane(self) -> "ClientReleaseDraftRequest":
        if self.mandatory:
            raise ValueError("the first update release must not be mandatory")
        if self.environment != "production" or self.channel != "stable":
            raise ValueError("formal releases must use production/stable")
        if not self.download_path.endswith("/" + self.file_name):
            raise ValueError("downloadPath must end with fileName")
        expected_lane = "standard" if self.edition == "standard" else "license"
        if f"/{self.channel}/{expected_lane}/{self.version}/" not in self.download_path:
            raise ValueError("downloadPath does not match release channel, edition, and version")
        if self.edition == "standard" and "-standard-Setup.exe" not in self.file_name:
            raise ValueError("standard release requires a standard installer")
        if self.edition == "license" and "-license-Setup.exe" not in self.file_name:
            raise ValueError("production license release requires a license installer")
        return self


class ClientReleaseUpdateRequest(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    release_notes: str = Field(min_length=1, max_length=20_000)
