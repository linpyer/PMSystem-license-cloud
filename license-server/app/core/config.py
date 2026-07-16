from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    admin_session_secret: SecretStr = Field(
        default=SecretStr("development-only-admin-session-secret-change-me"),
        alias="LICENSE_ADMIN_SESSION_SECRET",
    )
    admin_totp_encryption_key: SecretStr = Field(
        default=SecretStr("development-only-totp-encryption-key-change-me"),
        alias="LICENSE_ADMIN_TOTP_ENCRYPTION_KEY",
    )
    admin_session_idle_minutes: int = Field(
        default=30, ge=5, le=240, alias="LICENSE_ADMIN_SESSION_IDLE_MINUTES"
    )
    admin_session_max_hours: int = Field(
        default=8, ge=1, le=24, alias="LICENSE_ADMIN_SESSION_MAX_HOURS"
    )
    admin_login_max_failures: int = Field(
        default=5, ge=3, le=20, alias="LICENSE_ADMIN_LOGIN_MAX_FAILURES"
    )
    admin_lockout_minutes: int = Field(
        default=15, ge=1, le=1440, alias="LICENSE_ADMIN_LOCKOUT_MINUTES"
    )
    admin_allowed_origins_raw: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        alias="LICENSE_ADMIN_ALLOWED_ORIGINS",
    )
    admin_cookie_secure: bool = Field(default=False, alias="LICENSE_ADMIN_COOKIE_SECURE")
    admin_cookie_name: str = Field(default="pms_admin_session", alias="LICENSE_ADMIN_COOKIE_NAME")

    @property
    def admin_allowed_origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.admin_allowed_origins_raw.split(",") if item.strip()]

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
        if "*" in self.admin_allowed_origins:
            raise ValueError("LICENSE_ADMIN_ALLOWED_ORIGINS cannot contain a wildcard")
        if self.environment == "production":
            if not self.admin_cookie_secure:
                raise ValueError("production admin cookies must be Secure")
            if self.admin_session_secret.get_secret_value().startswith("development-only"):
                raise ValueError("production requires a unique admin session secret")
            if self.admin_totp_encryption_key.get_secret_value().startswith("development-only"):
                raise ValueError("production requires a unique TOTP encryption key")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
