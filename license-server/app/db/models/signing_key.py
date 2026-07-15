from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import SigningKeyStatus


class SigningKey(Base):
    __tablename__ = "signing_keys"

    key_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="Ed25519")
    public_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[SigningKeyStatus] = mapped_column(
        Enum(
            SigningKeyStatus,
            name="signing_key_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=SigningKeyStatus.ACTIVE,
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
