"""Add administrator management schema.

Revision ID: 0002_admin_management
Revises: 0001_license_schema
Create Date: 2026-07-15 14:00:00 UTC
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_admin_management"
down_revision: str | None = "0001_license_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


admin_role = sa.Enum(
    "OWNER", "ADMIN", "AUDITOR", name="admin_role", native_enum=False, create_constraint=True
)
admin_status = sa.Enum(
    "ACTIVE", "DISABLED", name="admin_status", native_enum=False, create_constraint=True
)
admin_session_status = sa.Enum(
    "PENDING_TOTP", "ACTIVE", "REVOKED",
    name="admin_session_status", native_enum=False, create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", admin_role, nullable=False),
        sa.Column("status", admin_status, nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_totp_counter", sa.BigInteger(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_admin_users"),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
    )
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)
    op.create_index("ix_admin_users_role", "admin_users", ["role"])
    op.create_index("ix_admin_users_status", "admin_users", ["status"])

    op.create_table(
        "admin_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=True),
        sa.Column("status", admin_session_status, nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["admin_users.id"],
            name="fk_admin_sessions_admin_user_id_admin_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
    )
    op.create_index("ix_admin_sessions_status", "admin_sessions", ["status"])
    op.create_index("ix_admin_sessions_user_status", "admin_sessions", ["admin_user_id", "status"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("trace_id", sa.String(length=80), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["admin_users.id"],
            name="fk_admin_audit_events_admin_user_id_admin_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit_events"),
    )
    op.create_index("ix_admin_audit_events_admin_user_id", "admin_audit_events", ["admin_user_id"])
    op.create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
    op.create_index("ix_admin_audit_events_created_at", "admin_audit_events", ["created_at"])
    op.create_index("ix_admin_audit_events_request_id", "admin_audit_events", ["request_id"])
    op.create_index("ix_admin_audit_events_trace_id", "admin_audit_events", ["trace_id"])
    op.create_index("ix_admin_audit_events_target", "admin_audit_events", ["target_type", "target_id"])

    op.create_table(
        "admin_login_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username_masked", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["admin_users.id"],
            name="fk_admin_login_attempts_admin_user_id_admin_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_login_attempts"),
    )
    op.create_index("ix_admin_login_attempts_admin_user_id", "admin_login_attempts", ["admin_user_id"])
    op.create_index("ix_admin_login_attempts_ip_created", "admin_login_attempts", ["ip", "created_at"])

    op.create_table(
        "app_version_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("recommended_version", sa.String(length=40), nullable=False),
        sa.Column("minimum_supported_version", sa.String(length=40), nullable=False),
        sa.Column("download_url", sa.String(length=1000), nullable=True),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["admin_users.id"],
            name="fk_app_version_policy_updated_by_admin_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_version_policy"),
        sa.UniqueConstraint("product", "platform", name="uq_app_version_product_platform"),
    )

    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type",
        "license_events",
        "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
        "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
        "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_ENABLED','LICENSE_REVOKED',"
        "'ADMIN_DEACTIVATED','LICENSE_EXPIRED','ABNORMAL_REQUEST')",
    )


def downgrade() -> None:
    op.drop_constraint("license_event_type", "license_events", type_="check")
    op.create_check_constraint(
        "license_event_type",
        "license_events",
        "event_type IN ('ACTIVATED','REACTIVATED_SAME_DEVICE','VERIFIED','REFRESHED',"
        "'DEACTIVATED','ACTIVATION_FAILED','VERIFICATION_FAILED','DEACTIVATION_FAILED',"
        "'REFRESH_FAILED','LICENSE_DISABLED','LICENSE_EXPIRED','ABNORMAL_REQUEST')",
    )
    op.drop_table("app_version_policy")
    op.drop_table("admin_login_attempts")
    op.drop_table("admin_audit_events")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
