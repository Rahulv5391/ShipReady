"""ITC-HS, exchange rate and location tables

Revision ID: ad073e9a266c
Revises: 5058a5eb348c
Create Date: 2026-10-22 22:01:56.456949
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ad073e9a266c"
down_revision: str | Sequence[str] | None = "5058a5eb348c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ref_exchange_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=False),
        sa.Column("rate_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("notification", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("currency", "valid_from"),
    )
    op.create_table(
        "ref_itc_hs",
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("chapter", sa.Text(), nullable=False),
        sa.Column("export_policy", sa.String(length=10), nullable=False),
        sa.Column("uqc", sa.String(length=3), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "export_policy IN ('Free', 'Restricted', 'Prohibited', 'STE')",
            name="export_policy_valid",
        ),
        sa.ForeignKeyConstraint(
            ["uqc"],
            ["ref_uqc.code"],
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_locations",
        sa.Column("code", sa.String(length=5), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subdivision", sa.String(length=3), nullable=True),
        sa.Column("functions", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["country"],
            ["ref_countries.code"],
        ),
        sa.PrimaryKeyConstraint("code"),
    )


def downgrade() -> None:
    op.drop_table("ref_locations")
    op.drop_table("ref_itc_hs")
    op.drop_table("ref_exchange_rates")
