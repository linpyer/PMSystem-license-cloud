from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.models.enums import LicenseEventType


class LicenseEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "license_events"
    __table_args__ = (Index("ix_license_events_created_at", "created_at"),)

    license_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("licenses.id", ondelete="SET NULL"), index=True
    )
    binding_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("device_bindings.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[LicenseEventType] = mapped_column(
        Enum(
            LicenseEventType,
            name="license_event_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(INET)
    app_version: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    license = relationship("License", back_populates="events", lazy="raise")
    binding = relationship("DeviceBinding", back_populates="events", lazy="raise")
