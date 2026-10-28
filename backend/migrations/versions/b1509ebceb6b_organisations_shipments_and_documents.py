"""Organisations, shipments and documents

Revision ID: b1509ebceb6b
Revises: de98665f0995
Create Date: 2026-10-27 10:44:01.734062
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1509ebceb6b"
down_revision: str | Sequence[str] | None = "de98665f0995"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "type IN ('exporter', 'cha', 'forwarder', 'internal')", name="type_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "shipments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IS NULL OR mode IN ('sea', 'air', 'road', 'rail', 'courier')", name="mode_valid"
        ),
        sa.CheckConstraint("status IN ('RECEIVED')", name="status_valid"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "reference", name="reference_unique"),
    )
    op.create_index(op.f("ix_shipments_org_id"), "shipments", ["org_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shipment_id", "sha256", name="file_unique_in_shipment"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(op.f("ix_documents_shipment_id"), "documents", ["shipment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_shipment_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_shipments_org_id"), table_name="shipments")
    op.drop_table("shipments")
    op.drop_table("organizations")
