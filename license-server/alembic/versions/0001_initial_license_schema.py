"""Initial PMSystem license schema.

Revision ID: 0001_license_schema
Revises:
Create Date: 2026-07-15 00:00:00 UTC
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0001_license_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


license_type = sa.Enum(
    "monthly", "yearly", "permanent", "fixed_date",
    name="license_type", native_enum=False, create_constraint=True,
)
license_status = sa.Enum(
    "CREATED", "ACTIVE", "EXPIRED", "DISABLED", "REVOKED",
    name="license_status", native_enum=False, create_constraint=True,
)
binding_status = sa.Enum(
    "ACTIVE", "DEACTIVATED", "DISABLED",
    name="binding_status", native_enum=False, create_constraint=True,
)
event_type = sa.Enum(
    "ACTIVATED",
    "REACTIVATED_SAME_DEVICE",
    "VERIFIED",
    "REFRESHED",
    "DEACTIVATED",
    "ACTIVATION_FAILED",
    "VERIFICATION_FAILED",
    "DEACTIVATION_FAILED",
    "REFRESH_FAILED",
    "LICENSE_DISABLED",
    "LICENSE_EXPIRED",
    "ABNORMAL_REQUEST",
    name="license_event_type",
    native_enum=False,
    create_constraint=True,
)
signing_key_status = sa.Enum(
    "ACTIVE", "RETIRED",
    name="signing_key_status", native_enum=False, create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_code_hash", sa.String(length=64), nullable=False),
        sa.Column("license_code_masked", sa.String(length=32), nullable=False),
        sa.Column("license_type", license_type, nullable=False),
        sa.Column("status", license_status, nullable=False),
        sa.Column("valid_days", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_devices", sa.Integer(), server_default="1", nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=True),
        sa.Column("customer_contact", sa.String(length=240), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("max_devices >= 1", name="ck_licenses_max_devices_positive"),
        sa.CheckConstraint(
            "valid_days IS NULL OR valid_days > 0", name="ck_licenses_valid_days_positive"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_licenses"),
        sa.UniqueConstraint("license_code_hash", name="uq_licenses_license_code_hash"),
    )
    op.create_index("ix_licenses_status", "licenses", ["status"])
    op.create_index("ix_licenses_expires_at", "licenses", ["expires_at"])

    op.create_table(
        "device_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.String(length=200), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=40), nullable=False),
        sa.Column("device_name", sa.String(length=200), nullable=True),
        sa.Column("os_version", sa.String(length=160), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=False),
        sa.Column("status", binding_status, nullable=False),
        sa.Column("first_activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivate_reason", sa.Text(), nullable=True),
        sa.Column("last_ip", postgresql.INET(), nullable=True),
        sa.Column("device_credential_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["license_id"], ["licenses.id"], name="fk_device_bindings_license_id_licenses", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_bindings"),
    )
    op.create_index("ix_device_bindings_device_id", "device_bindings", ["device_id"])
    op.create_index("ix_device_bindings_status", "device_bindings", ["status"])
    op.create_index(
        "uq_device_bindings_active_license",
        "device_bindings",
        ["license_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "idempotency_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_requests"),
        sa.UniqueConstraint("request_id", "endpoint", name="uq_idempotency_request_endpoint"),
    )
    op.create_index(
        "ix_idempotency_requests_expires_at", "idempotency_requests", ["expires_at"]
    )

    op.create_table(
        "signing_keys",
        sa.Column("key_id", sa.String(length=80), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.String(length=128), nullable=False),
        sa.Column("status", signing_key_status, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key_id", name="pk_signing_keys"),
    )

    op.create_table(
        "license_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("binding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["device_bindings.id"], name="fk_license_events_binding_id_device_bindings", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["license_id"], ["licenses.id"], name="fk_license_events_license_id_licenses", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_license_events"),
    )
    op.create_index("ix_license_events_binding_id", "license_events", ["binding_id"])
    op.create_index("ix_license_events_created_at", "license_events", ["created_at"])
    op.create_index("ix_license_events_license_id", "license_events", ["license_id"])
    op.create_index("ix_license_events_request_id", "license_events", ["request_id"])


def downgrade() -> None:
    op.drop_table("license_events")
    op.drop_table("signing_keys")
    op.drop_table("idempotency_requests")
    op.drop_table("device_bindings")
    op.drop_table("licenses")
