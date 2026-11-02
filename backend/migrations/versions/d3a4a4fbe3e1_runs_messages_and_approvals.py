"""runs messages and approvals

Revision ID: d3a4a4fbe3e1
Revises: 40c1a589d0b2
Create Date: 2026-11-03 00:50:18.648706
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3a4a4fbe3e1"
down_revision: str | Sequence[str] | None = "40c1a589d0b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=12), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('reading', 'extracting', 'checking', 'drafting')",
            name="stage_valid",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'awaiting_review', 'done', 'failed')", name="status_valid"
        ),
        sa.CheckConstraint("trigger IN ('upload', 'recheck')", name="trigger_valid"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runs_org_id"), "runs", ["org_id"], unique=False)
    op.create_index(op.f("ix_runs_shipment_id"), "runs", ["shipment_id"], unique=False)
    op.create_index(
        "one_active_run",
        "runs",
        ["shipment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('running', 'awaiting_review')"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('mark_ready', 'mark_needs_fix', 'approve_message', 'discard_message')",
            name="action_valid",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approvals_shipment_id"), "approvals", ["shipment_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("recipient", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("rule_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recipient IN ('exporter', 'forwarder', 'customs_broker', 'buyer', 'certifier')",
            name="recipient_valid",
        ),
        sa.CheckConstraint("status IN ('draft', 'approved', 'discarded')", name="status_valid"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_shipment_id"), "messages", ["shipment_id"], unique=False)
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_run_events_run_id"), "run_events", ["run_id"], unique=False)
    # Autogenerate does not detect a changed check constraint.
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.create_check_constraint(
        "status_valid",
        "shipments",
        "status IN ('RECEIVED', 'EXTRACTED', 'CHECKED', 'AWAITING_REVIEW', 'READY', 'NEEDS_FIX')",
    )


def downgrade() -> None:
    op.drop_constraint("status_valid", "shipments", type_="check")
    op.execute(
        "UPDATE shipments SET status = 'CHECKED'"
        " WHERE status IN ('AWAITING_REVIEW', 'READY', 'NEEDS_FIX')"
    )
    op.create_check_constraint(
        "status_valid", "shipments", "status IN ('RECEIVED', 'EXTRACTED', 'CHECKED')"
    )
    op.drop_index(op.f("ix_run_events_run_id"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_index(op.f("ix_messages_shipment_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_approvals_shipment_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(
        "one_active_run",
        table_name="runs",
        postgresql_where=sa.text("status IN ('running', 'awaiting_review')"),
    )
    op.drop_index(op.f("ix_runs_shipment_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_org_id"), table_name="runs")
    op.drop_table("runs")
