"""check citations

Revision ID: 520402638ec8
Revises: 026de302e1e0
Create Date: 2026-11-02 12:13:14.404894
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "520402638ec8"
down_revision: str | Sequence[str] | None = "026de302e1e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "check_results",
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("check_results", "citations")
