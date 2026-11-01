"""extracted fields

Revision ID: 07c32d59fcff
Revises: 11f40183a8e8
Create Date: 2026-11-02 00:07:24.260186
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "07c32d59fcff"
down_revision: str | Sequence[str] | None = "11f40183a8e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("part_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("box", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["part_id"], ["document_parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shipment_id", "path", name="path_unique"),
    )
    op.create_index(
        op.f("ix_extracted_fields_part_id"), "extracted_fields", ["part_id"], unique=False
    )
    op.create_index(
        op.f("ix_extracted_fields_shipment_id"), "extracted_fields", ["shipment_id"], unique=False
    )
    op.add_column("shipments", sa.Column("error", sa.Text(), nullable=True))
    # Autogenerate does not detect a changed check constraint.
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.create_check_constraint("status_valid", "shipments", "status IN ('RECEIVED', 'EXTRACTED')")


def downgrade() -> None:
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.execute("UPDATE shipments SET status = 'RECEIVED'")
    op.create_check_constraint("status_valid", "shipments", "status IN ('RECEIVED')")
    op.drop_column("shipments", "error")
    op.drop_index(op.f("ix_extracted_fields_shipment_id"), table_name="extracted_fields")
    op.drop_index(op.f("ix_extracted_fields_part_id"), table_name="extracted_fields")
    op.drop_table("extracted_fields")
