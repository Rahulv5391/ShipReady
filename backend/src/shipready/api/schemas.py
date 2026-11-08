"""Request and response bodies of the API."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    # Long enough for any passphrase; the limit keeps a huge body from tying up scrypt.
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    remember: bool = False  # "keep me signed in on this device"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    name: str
    org_id: uuid.UUID


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: Reference
    mode: Literal["sea", "air", "road", "rail", "courier"] | None = None


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    mode: str | None
    status: str
    error: str | None
    # Suggested once checked: ready, needs_fix or needs_review, and a 0-100 score.
    readiness: str | None
    readiness_score: Decimal | None
    created_at: datetime


class BoxOut(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class FieldOut(BaseModel):
    """A field read from a document, with the text it was read from and where that is."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    value: str
    quote: str
    document_id: uuid.UUID
    page_no: int
    box: BoxOut | None
    model: str


class CitationOut(BaseModel):
    """A passage of a regulatory text a result relies on."""

    source_id: str
    title: str
    url: str
    page: int | None
    text: str


class CheckOut(BaseModel):
    """A check's outcome on the shipment: pass, fail, or not verified when a value it needs is
    missing or our reference data cannot decide it."""

    rule_id: str
    title: str
    severity: str
    outcome: str
    message: str
    evidence: list[FieldOut]
    citations: list[CitationOut]
    # The critic's review of a failure against the page images: kept, or misread.
    verification: str | None
    critic_reason: str


class DocumentPartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_page: int
    last_page: int
    doc_type: str
    decided_by: str
    confidence: Decimal | None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shipment_id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    status: str
    error: str | None
    page_count: int | None
    parts: list[DocumentPartOut]


class DuplicateOut(BaseModel):
    """A file left out of an upload because the same bytes are already stored as `same_as`."""

    filename: str
    same_as: str


class UploadOut(BaseModel):
    """The files stored, and those that were the same as a file stored already (D-34)."""

    documents: list[DocumentOut]
    duplicates: list[DuplicateOut]


class ShipmentDetail(ShipmentOut):
    documents: list[DocumentOut]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shipment_id: uuid.UUID
    trigger: str
    status: str  # running, awaiting_review, done, failed
    stage: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    recipient: str
    subject: str
    body: str
    rule_ids: list[str]
    status: str  # draft, approved, discarded
    created_at: datetime


class MessageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None


class Decision(BaseModel):
    """A person's reason: required to mark a shipment ready while blockers are open."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None
    action: str
    target_id: uuid.UUID | None
    decided_by: str
    reason: str | None
    decided_at: datetime
