"""Add the RETIRING signing-key state.

Revision ID: 0003_signing_key_rotation
Revises: 0002_admin_management
"""

from typing import Sequence

from alembic import op


revision: str = "0003_signing_key_rotation"
down_revision: str | None = "0002_admin_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("signing_key_status", "signing_keys", type_="check")
    op.create_check_constraint(
        "signing_key_status",
        "signing_keys",
        "status IN ('ACTIVE','RETIRING','RETIRED')",
    )


def downgrade() -> None:
    op.drop_constraint("signing_key_status", "signing_keys", type_="check")
    op.create_check_constraint(
        "signing_key_status",
        "signing_keys",
        "status IN ('ACTIVE','RETIRED')",
    )
