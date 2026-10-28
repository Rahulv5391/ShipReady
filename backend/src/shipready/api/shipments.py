"""Shipments: create, list and read, always within the caller's organisation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.api.deps import PrincipalDep, SessionDep
from shipready.api.schemas import DocumentOut, ShipmentCreate, ShipmentDetail, ShipmentOut
from shipready.db.models import Document, Shipment

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_shipment(
    body: ShipmentCreate, principal: PrincipalDep, session: SessionDep
) -> ShipmentOut:
    shipment = Shipment(org_id=principal.org_id, reference=body.reference, mode=body.mode)
    session.add(shipment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a shipment with reference {body.reference!r} exists"
        ) from None
    return ShipmentOut.model_validate(shipment)


@router.get("")
def list_shipments(
    principal: PrincipalDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=64, description="part of the reference")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ShipmentOut]:
    query = select(Shipment).where(Shipment.org_id == principal.org_id)
    if q:
        query = query.where(Shipment.reference.icontains(q, autoescape=True))
    query = query.order_by(Shipment.created_at.desc(), Shipment.id).limit(limit).offset(offset)
    return [ShipmentOut.model_validate(s) for s in session.scalars(query)]


@router.get("/{shipment_id}")
def get_shipment(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> ShipmentDetail:
    shipment = shipment_of(session, principal.org_id, shipment_id)
    documents = session.scalars(
        select(Document)
        .where(Document.shipment_id == shipment.id)
        .order_by(Document.uploaded_at, Document.filename)
    )
    return ShipmentDetail(
        **ShipmentOut.model_validate(shipment).model_dump(),
        documents=[DocumentOut.model_validate(d) for d in documents],
    )


def shipment_of(session: Session, org_id: uuid.UUID, shipment_id: uuid.UUID) -> Shipment:
    """The shipment if it belongs to `org_id`. Another organisation's shipment is reported as
    not found, so its existence is not revealed."""
    shipment = session.get(Shipment, shipment_id)
    if shipment is None or shipment.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "shipment not found")
    return shipment
