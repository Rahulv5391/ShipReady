"""reference load times

Revision ID: 499d6ba0ef5d
Revises: c84fc8d2075c
Create Date: 2026-11-10 12:38:08.774897

Data loaded before this revision has no record until it is loaded again
(`python -m shipready.db.load all`, from the files already downloaded).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "499d6ba0ef5d"
down_revision: str | Sequence[str] | None = "c84fc8d2075c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ref_loads",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("ref_loads")
