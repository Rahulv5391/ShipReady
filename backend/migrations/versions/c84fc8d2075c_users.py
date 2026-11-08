"""users

Revision ID: c84fc8d2075c
Revises: d3a4a4fbe3e1
Create Date: 2026-11-09 02:40:40.365317
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c84fc8d2075c"
down_revision: str | Sequence[str] | None = "d3a4a4fbe3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_org_id"), "users", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_org_id"), table_name="users")
    op.drop_table("users")
