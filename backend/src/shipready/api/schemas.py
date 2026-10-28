"""Request and response bodies of the API."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


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
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shipment_id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime


class ShipmentDetail(ShipmentOut):
    documents: list[DocumentOut]
