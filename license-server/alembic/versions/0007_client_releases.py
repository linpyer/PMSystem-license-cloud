"""Add signed DDREC client release publishing.

Revision ID: 0007_client_releases
Revises: 0006_trial_management_actions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_client_releases"
down_revision: str | None = "0006_trial_management_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("build_number", sa.Integer(), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("edition", sa.String(length=20), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False),
        sa.Column("architecture", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(length=260), nullable=False),
        sa.Column("download_path", sa.String(length=1000), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("edition IN ('standard','license')", name=op.f("ck_client_releases_client_release_edition")),
        sa.CheckConstraint("environment IN ('local','production')", name=op.f("ck_client_releases_client_release_environment")),
        sa.CheckConstraint("architecture IN ('x64')", name=op.f("ck_client_releases_client_release_architecture")),
        sa.CheckConstraint("channel IN ('stable','dev')", name=op.f("ck_client_releases_client_release_channel")),
        sa.CheckConstraint("status IN ('draft','published','withdrawn')", name=op.f("ck_client_releases_client_release_status")),
        sa.CheckConstraint("build_number > 0", name=op.f("ck_client_releases_client_release_positive_build")),
        sa.CheckConstraint("file_size > 0", name=op.f("ck_client_releases_client_release_positive_size")),
        sa.ForeignKeyConstraint(["created_by"], ["admin_users.id"], name=op.f("fk_client_releases_created_by_admin_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_releases")),
        sa.UniqueConstraint(
            "product", "version", "build_number", "edition", "environment",
            "architecture", "channel", name="uq_client_release_identity",
        ),
    )
    op.create_index(op.f("ix_client_releases_created_by"), "client_releases", ["created_by"])
    op.create_index(
        "ix_client_releases_lookup", "client_releases",
        ["product", "edition", "environment", "architecture", "channel", "status", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_releases_lookup", table_name="client_releases")
    op.drop_index(op.f("ix_client_releases_created_by"), table_name="client_releases")
    op.drop_table("client_releases")
