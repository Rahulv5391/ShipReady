"""Tables for the check catalogue, reference data, and organisations, shipments and documents
(PLAN.md Section 12).

The catalogue, UQC codes and countries are seeded from packaged files; the other reference tables
are loaded from official downloads by `shipready.db.load`. Organisations, shipments and documents
are written by the API.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shipready.documents.types import DOCUMENT_TYPES
from shipready.reference.export_policy import EXPORT_POLICIES
from shipready.reference.ports import KINDS
from shipready.rules.catalogue import CHECK_TYPES, SEVERITIES

POLICY_SOURCES = ("dgft", "override")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(_one_of("check_type", CHECK_TYPES), name="check_type_valid"),
        CheckConstraint(_one_of("severity", SEVERITIES), name="severity_valid"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(String(8))
    severity: Mapped[str] = mapped_column(String(8))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prevents: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool]


class RefUqc(Base):
    __tablename__ = "ref_uqc"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    description: Mapped[str] = mapped_column(Text)


class RefCountry(Base):
    __tablename__ = "ref_countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class RefPort(Base):
    """An Indian customs location (ICEGATE code), e.g. INNSA1 Nhava Sheva seaport."""

    __tablename__ = "ref_ports"
    __table_args__ = (CheckConstraint(_one_of("kind", tuple(KINDS.values())), name="kind_valid"),)

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(6))
    edi: Mapped[bool]  # connected to ICEGATE's electronic filing


class RefItcHs(Base):
    """An ITC(HS) code: chapter (2 digits), heading (4), subheading (6) or tariff item (8)."""

    __tablename__ = "ref_itc_hs"
    __table_args__ = (CheckConstraint("level IN (2, 4, 6, 8)", name="level_valid"),)

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)
    description: Mapped[str] = mapped_column(Text)


class RefExportPolicy(Base):
    """A period during which an 8-digit code is not Free to export. Codes without a row are Free.

    `effective_from` is the date of the notification DGFT cites (earlier history is not recorded)
    and is empty when DGFT cites none; `effective_to` is empty while the policy is in force.
    """

    __tablename__ = "ref_export_policy"
    __table_args__ = (
        CheckConstraint(_one_of("policy", EXPORT_POLICIES), name="policy_valid"),
        CheckConstraint(_one_of("source", POLICY_SOURCES), name="source_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("ref_itc_hs.code"), index=True)
    policy: Mapped[str] = mapped_column(String(10))
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    notification: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8))


class RefCurrency(Base):
    """An ISO 4217 currency; `minor_units` is empty for funds and metals."""

    __tablename__ = "ref_currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    minor_units: Mapped[int | None] = mapped_column(SmallInteger)


class RefExchangeRate(Base):
    """Customs export rate: INR per `unit` units of `currency`, in force from `valid_from` until
    the next notification for that currency."""

    __tablename__ = "ref_exchange_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    valid_from: Mapped[date] = mapped_column(primary_key=True)
    unit: Mapped[int]
    rate_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    notification: Mapped[str] = mapped_column(Text)  # ICEGATE notification number, e.g. 29/2026
    published_on: Mapped[date]


class RefLocation(Base):
    """UN/LOCODE location (city, port, airport, inland depot)."""

    __tablename__ = "ref_locations"

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    country: Mapped[str] = mapped_column(ForeignKey("ref_countries.code"))
    name: Mapped[str] = mapped_column(Text)
    subdivision: Mapped[str | None] = mapped_column(String(3))
    # Eight positions: 1 port, 2 rail, 3 road, 4 airport, 5 postal, 6 multimodal (e.g. ICD),
    # 7 fixed transport, B border crossing; "-" where the function does not apply.
    functions: Mapped[str] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(2))


ORGANIZATION_TYPES = ("exporter", "cha", "forwarder", "internal")
TRANSPORT_MODES = ("sea", "air", "road", "rail", "courier")
# Later phases add the remaining statuses of PLAN.md Section 10.2 (checked, verified, ...).
# Then awaiting a person's review (PLAN.md Section 10.2), who marks it ready or needing fixes.
SHIPMENT_STATUSES = ("RECEIVED", "EXTRACTED", "CHECKED", "AWAITING_REVIEW", "READY", "NEEDS_FIX")
DOCUMENT_STATUSES = ("uploaded", "processing", "processed", "failed")
TEXT_SOURCES = ("pdf_text", "ocr", "cells")  # the PDF's own text, OCR of an image, Excel cells
# How a part's type was decided: its title, following a titled page, the AI, or not at all
# (no title and AI switched off; the part is "other").
PART_DECISIONS = ("title", "follows", "ai", "none")
# Size of the regulatory passages' embeddings (shipready.knowledge.index).
EMBEDDING_DIMENSIONS = 768
# A check's outcome (shipready.checks.engine): not verified when a value it needs is missing or
# our reference data cannot decide it.
CHECK_OUTCOMES = ("pass", "fail", "not_verified")
READINESS = ("ready", "needs_fix", "needs_review")
# A run processes a shipment, started by an upload or a person asking to check it again.
RUN_TRIGGERS = ("upload", "recheck")
RUN_STATUSES = ("running", "awaiting_review", "done", "failed")
RUN_STAGES = ("reading", "extracting", "checking", "drafting")
# Who fixes a document: the exporter's own team, the forwarder or carrier, the customs broker,
# the buyer, or the body that certifies origin.
RECIPIENTS = ("exporter", "forwarder", "customs_broker", "buyer", "certifier")
MESSAGE_STATUSES = ("draft", "approved", "discarded")
APPROVAL_ACTIONS = ("mark_ready", "mark_needs_fix", "approve_message", "discard_message")
# The critic's review of a failure (shipready.checks.critic).
VERIFICATIONS = ("kept", "misread")


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint(_one_of("type", ORGANIZATION_TYPES), name="type_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16))


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("org_id", "reference", name="reference_unique"),
        CheckConstraint(f"mode IS NULL OR {_one_of('mode', TRANSPORT_MODES)}", name="mode_valid"),
        CheckConstraint(_one_of("status", SHIPMENT_STATUSES), name="status_valid"),
        CheckConstraint(
            f"readiness IS NULL OR {_one_of('readiness', READINESS)}", name="readiness_valid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    reference: Mapped[str] = mapped_column(Text)  # the exporter's job number
    mode: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="RECEIVED")
    error: Mapped[str | None] = mapped_column(Text)  # why extraction failed, if it did
    # Suggested once checked (shipready.checks.readiness); a person marks it ready.
    readiness: Mapped[str | None] = mapped_column(String(12))
    readiness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """An uploaded file; the bytes are in object storage under `storage_key`. The worker reads
    its pages and splits it into parts (status uploaded -> processing -> processed or failed)."""

    __tablename__ = "documents"
    __table_args__ = (
        # The same file twice in one shipment is refused rather than stored twice.
        UniqueConstraint("shipment_id", "sha256", name="file_unique_in_shipment"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint(_one_of("status", DOCUMENT_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)  # detected from the file's bytes
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(16), server_default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)  # why processing failed
    page_count: Mapped[int | None]
    parts: Mapped[list["DocumentPart"]] = relationship(
        order_by="DocumentPart.first_page", lazy="selectin", passive_deletes=True
    )


class DocumentPage(Base):
    """One page of an uploaded file: its rendered image and the words on it with their boxes."""

    __tablename__ = "document_pages"
    __table_args__ = (
        CheckConstraint(_one_of("text_source", TEXT_SOURCES), name="text_source_valid"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(primary_key=True)  # from 1
    image_key: Mapped[str | None] = mapped_column(Text)  # rendered image; none for a workbook
    width_px: Mapped[int | None]
    height_px: Mapped[int | None]
    text_source: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    # [{"t": word, "x0": .., "y0": .., "x1": .., "y1": ..}], coordinates 0..1 from the top left.
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class DocumentPart(Base):
    """Pages first_page..last_page of a file are one document of `doc_type`. A file holding
    several documents (a combined scan) has several parts."""

    __tablename__ = "document_parts"
    __table_args__ = (
        CheckConstraint(_one_of("doc_type", DOCUMENT_TYPES), name="doc_type_valid"),
        CheckConstraint(_one_of("decided_by", PART_DECISIONS), name="decided_by_valid"),
        CheckConstraint("first_page >= 1 AND last_page >= first_page", name="pages_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    first_page: Mapped[int]
    last_page: Mapped[int]
    doc_type: Mapped[str] = mapped_column(String(32))
    decided_by: Mapped[str] = mapped_column(String(8))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))  # the AI's, when it decided


class ExtractedField(Base):
    """A value read from one of the shipment's documents, with the text it was read from and
    where that text is: the evidence a finding points to. A shipment's fields are replaced each
    time it is extracted."""

    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("shipment_id", "path", name="path_unique"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_parts.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text)  # e.g. "commercial_invoice.lines[0].quantity"
    value: Mapped[str] = mapped_column(Text)  # as the model wrote it, in the guide's format
    quote: Mapped[str] = mapped_column(Text)  # the text as printed
    page_no: Mapped[int]  # page of the file, from 1
    # {"x0": .., "y0": .., "x1": .., "y1": ..}, 0..1 from the top left; None when the quote
    # was not found on the page.
    box: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(Text)


class CheckResult(Base):
    """The outcome of one check on a shipment, with the fields it read as evidence. A
    shipment's results are replaced each time it is checked."""

    __tablename__ = "check_results"
    __table_args__ = (
        UniqueConstraint("shipment_id", "rule_id", name="rule_unique"),
        CheckConstraint(_one_of("outcome", CHECK_OUTCOMES), name="outcome_valid"),
        CheckConstraint(
            f"verification IS NULL OR {_one_of('verification', VERIFICATIONS)}",
            name="verification_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    # The catalogue's rule ID. Not a foreign key: the checks run where the catalogue table may
    # not be seeded, and the IDs come from the same packaged catalogue.
    rule_id: Mapped[str] = mapped_column(String(8))
    outcome: Mapped[str] = mapped_column(String(12))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSONB)  # paths into extracted_fields
    # Passages of the regulatory texts the result relies on: [{"source_id", "page", "text"}].
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    verification: Mapped[str | None] = mapped_column(String(8))  # None when not reviewed
    critic_reason: Mapped[str] = mapped_column(Text, default="", server_default="")


class KnowledgeChunk(Base):
    """A passage of a regulatory text (shipready.knowledge.sources) with its embedding, for the
    compliance checks to cite. A source's passages are replaced when its file changes."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_no", name="chunk_unique"),
        # Nearest passages by cosine distance without scanning them all.
        Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64))  # of the file the passage came from
    chunk_no: Mapped[int]  # order within the source, from 0
    page: Mapped[int | None]  # from 1; None for a web page
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str] = mapped_column(Text)


class Run(Base):
    """One processing of a shipment, from its files to a person's review. At most one is
    running or awaiting review per shipment; files uploaded meanwhile join it."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(_one_of("trigger", RUN_TRIGGERS), name="trigger_valid"),
        CheckConstraint(_one_of("status", RUN_STATUSES), name="status_valid"),
        CheckConstraint(f"stage IS NULL OR {_one_of('stage', RUN_STAGES)}", name="stage_valid"),
        # One active run per shipment, even when two requests start one at the same moment.
        Index(
            "one_active_run",
            "shipment_id",
            unique=True,
            postgresql_where=text("status IN ('running', 'awaiting_review')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="running")
    stage: Mapped[str | None] = mapped_column(String(12))  # while running
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    """A step of a run, in order: what the live progress stream sends."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)  # increasing: the stream's position
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # e.g. stage_started, document_read
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """A drafted request to the party who must correct a document. Never sent by ShipReady:
    a person approves it and sends it themselves (PLAN.md Phase 18, copy to clipboard)."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(_one_of("recipient", RECIPIENTS), name="recipient_valid"),
        CheckConstraint(_one_of("status", MESSAGE_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    recipient: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    rule_ids: Mapped[list[str]] = mapped_column(JSONB)  # the failed checks it asks to fix
    status: Mapped[str] = mapped_column(String(10), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Approval(Base):
    """A person's decision on a shipment: who, what, when and why. The record of human
    actions; the system's own steps are its runs' events."""

    __tablename__ = "approvals"
    __table_args__ = (CheckConstraint(_one_of("action", APPROVAL_ACTIONS), name="action_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID | None]  # the message approved or discarded
    decided_by: Mapped[str] = mapped_column(Text)  # the token's user until logins (Phase 17)
    reason: Mapped[str | None] = mapped_column(Text)  # required to override open blockers
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
