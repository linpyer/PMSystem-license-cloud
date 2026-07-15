from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = Field(alias="LICENSE_DATABASE_URL")
    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="LICENSE_ENVIRONMENT"
    )
    signing_private_key_path: Path = Field(alias="LICENSE_SIGNING_PRIVATE_KEY_PATH")
    signing_key_id: str = Field(min_length=3, max_length=80, alias="LICENSE_SIGNING_KEY_ID")
    code_pepper: str = Field(min_length=24, alias="LICENSE_CODE_PEPPER")
    device_credential_pepper: str = Field(
        min_length=24, alias="LICENSE_DEVICE_CREDENTIAL_PEPPER"
    )
    api_host: str = Field(default="127.0.0.1", alias="LICENSE_API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="LICENSE_API_PORT")
    log_level: str = Field(default="INFO", alias="LICENSE_LOG_LEVEL")
    openapi_enabled: bool = Field(default=True, alias="LICENSE_OPENAPI_ENABLED")
    minimum_client_version: str = Field(
        default="1.0.4", alias="LICENSE_MINIMUM_CLIENT_VERSION"
    )
    idempotency_ttl_hours: int = 24
    required_verify_days: int = 7
    offline_grace_days: int = 14

    @field_validator("database_url")
    @classmethod
    def require_postgresql_asyncpg(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("LICENSE_DATABASE_URL must use postgresql+asyncpg")
        if not url.database:
            raise ValueError("LICENSE_DATABASE_URL must name a database")
        return value

    @model_validator(mode="after")
    def protect_test_database(self) -> "Settings":
        if self.environment == "test":
            database = make_url(self.database_url).database or ""
            if not database.endswith("_test"):
                raise ValueError("test mode requires a database name ending in _test")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
