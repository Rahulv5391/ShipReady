"""check results

Revision ID: cd029ce19d78
Revises: 07c32d59fcff
Create Date: 2026-11-02 01:27:36.826909
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cd029ce19d78"
down_revision: str | Sequence[str] | None = "07c32d59fcff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "check_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=12), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("outcome IN ('pass', 'fail', 'not_verified')", name="outcome_valid"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shipment_id", "rule_id", name="rule_unique"),
    )
    op.create_index(
        op.f("ix_check_results_shipment_id"), "check_results", ["shipment_id"], unique=False
    )
    # Autogenerate does not detect a changed check constraint.
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.create_check_constraint(
        "status_valid", "shipments", "status IN ('RECEIVED', 'EXTRACTED', 'CHECKED')"
    )


def downgrade() -> None:
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.execute("UPDATE shipments SET status = 'EXTRACTED' WHERE status = 'CHECKED'")
    op.create_check_constraint("status_valid", "shipments", "status IN ('RECEIVED', 'EXTRACTED')")
    op.drop_index(op.f("ix_check_results_shipment_id"), table_name="check_results")
    op.drop_table("check_results")
