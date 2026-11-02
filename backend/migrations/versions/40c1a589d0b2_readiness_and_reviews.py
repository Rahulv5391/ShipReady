"""readiness and reviews

Revision ID: 40c1a589d0b2
Revises: 520402638ec8
Create Date: 2026-11-02 17:33:26.104674
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "40c1a589d0b2"
down_revision: str | Sequence[str] | None = "520402638ec8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("check_results", sa.Column("verification", sa.String(length=8), nullable=True))
    op.add_column(
        "check_results", sa.Column("critic_reason", sa.Text(), server_default="", nullable=False)
    )
    op.add_column("shipments", sa.Column("readiness", sa.String(length=12), nullable=True))
    op.add_column(
        "shipments", sa.Column("readiness_score", sa.Numeric(precision=5, scale=2), nullable=True)
    )
    # Autogenerate does not detect check constraints on existing tables.
    op.create_check_constraint(
        "readiness_valid",
        "shipments",
        "readiness IS NULL OR readiness IN ('ready', 'needs_fix', 'needs_review')",
    )
    op.create_check_constraint(
        "verification_valid",
        "check_results",
        "verification IS NULL OR verification IN ('kept', 'misread')",
    )


def downgrade() -> None:
    op.drop_constraint("verification_valid", "check_results", type_="check")
    op.drop_constraint("readiness_valid", "shipments", type_="check")
    op.drop_column("shipments", "readiness_score")
    op.drop_column("shipments", "readiness")
    op.drop_column("check_results", "critic_reason")
    op.drop_column("check_results", "verification")
