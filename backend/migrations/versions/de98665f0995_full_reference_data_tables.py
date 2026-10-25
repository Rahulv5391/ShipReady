"""Full reference data tables

Revision ID: de98665f0995
Revises: ad073e9a266c
Create Date: 2026-10-25 13:11:45.642636

The ITC(HS), port and exchange-rate tables change shape and only ever hold data reloaded from
official downloads (`python -m shipready.db.load`), so they are dropped and recreated rather than
altered. Downgrading recreates the previous, empty tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "de98665f0995"
down_revision: str | Sequence[str] | None = "ad073e9a266c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("ref_ports")
    op.drop_table("ref_itc_hs")
    op.drop_table("ref_exchange_rates")
    op.create_table(
        "ref_ports",
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=6), nullable=False),
        sa.Column("edi", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('sea', 'rail', 'air', 'post', 'inland', 'land')", name="kind_valid"
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_itc_hs",
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint("level IN (2, 4, 6, 8)", name="level_valid"),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_export_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("policy", sa.String(length=10), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("notification", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "policy IN ('Free', 'Restricted', 'Prohibited', 'STE')", name="policy_valid"
        ),
        sa.CheckConstraint("source IN ('dgft', 'override')", name="source_valid"),
        sa.ForeignKeyConstraint(["code"], ["ref_itc_hs.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ref_export_policy_code", "ref_export_policy", ["code"])
    op.create_table(
        "ref_currencies",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("minor_units", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_exchange_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=False),
        sa.Column("rate_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("notification", sa.Text(), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("currency", "valid_from"),
    )


def downgrade() -> None:
    op.drop_table("ref_exchange_rates")
    op.drop_table("ref_currencies")
    op.drop_index("ix_ref_export_policy_code", table_name="ref_export_policy")
    op.drop_table("ref_export_policy")
    op.drop_table("ref_itc_hs")
    op.drop_table("ref_ports")
    op.create_table(
        "ref_ports",
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("unlocode", sa.String(length=5), nullable=False),
        sa.Column("kind", sa.String(length=3), nullable=False),
        sa.CheckConstraint("kind IN ('sea', 'air', 'icd')", name="kind_valid"),
        sa.ForeignKeyConstraint(["country"], ["ref_countries.code"]),
        sa.PrimaryKeyConstraint("code"),
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
        sa.ForeignKeyConstraint(["uqc"], ["ref_uqc.code"]),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_exchange_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=False),
        sa.Column("rate_inr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("notification", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("currency", "valid_from"),
    )
