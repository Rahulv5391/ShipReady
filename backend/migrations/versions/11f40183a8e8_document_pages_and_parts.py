"""Document pages and parts

Revision ID: 11f40183a8e8
Revises: b1509ebceb6b
Create Date: 2026-10-28 14:14:52.017630
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "11f40183a8e8"
down_revision: str | Sequence[str] | None = "b1509ebceb6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.Text(), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("text_source", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("words", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("text_source IN ('pdf_text', 'ocr', 'cells')", name="text_source_valid"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "page_no"),
    )
    op.create_table(
        "document_parts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=8), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.CheckConstraint(
            "decided_by IN ('title', 'follows', 'ai', 'none')", name="decided_by_valid"
        ),
        sa.CheckConstraint(
            "doc_type IN ('commercial_invoice', 'packing_list', 'purchase_order', "
            "'shipping_bill', 'bill_of_lading', 'air_waybill', 'certificate_of_origin', "
            "'lut', 'other')",
            name="doc_type_valid",
        ),
        sa.CheckConstraint("first_page >= 1 AND last_page >= first_page", name="pages_valid"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_parts_document_id"), "document_parts", ["document_id"], unique=False
    )
    op.add_column(
        "documents",
        sa.Column("status", sa.String(length=16), server_default="uploaded", nullable=False),
    )
    op.add_column("documents", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    # Autogenerate does not detect check constraints on an existing table.
    op.create_check_constraint(
        "status_valid", "documents", "status IN ('uploaded', 'processing', 'processed', 'failed')"
    )


def downgrade() -> None:
    op.drop_constraint("status_valid", "documents", type_="check")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "error")
    op.drop_column("documents", "status")
    op.drop_index(op.f("ix_document_parts_document_id"), table_name="document_parts")
    op.drop_table("document_parts")
    op.drop_table("document_pages")
