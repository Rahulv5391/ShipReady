"""Rules and reference tables

Revision ID: 5058a5eb348c
Revises:
Create Date: 2026-10-22 17:58:55.763428
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5058a5eb348c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ref_countries",
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "ref_uqc",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("check_type", sa.String(length=8), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prevents", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "check_type IN ('DET', 'DEC', 'LLM', 'DET+DEC', 'DET+LLM', 'LLM+DET')",
            name="check_type_valid",
        ),
        sa.CheckConstraint(
            "severity IN ('blocker', 'major', 'minor', 'info')", name="severity_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ref_ports",
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("unlocode", sa.String(length=5), nullable=False),
        sa.Column("kind", sa.String(length=3), nullable=False),
        sa.CheckConstraint("kind IN ('sea', 'air', 'icd')", name="kind_valid"),
        sa.ForeignKeyConstraint(
            ["country"],
            ["ref_countries.code"],
        ),
        sa.PrimaryKeyConstraint("code"),
    )


def downgrade() -> None:
    op.drop_table("ref_ports")
    op.drop_table("rules")
    op.drop_table("ref_uqc")
    op.drop_table("ref_countries")
