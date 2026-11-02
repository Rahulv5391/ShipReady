"""Shipments: create, list and read, always within the caller's organisation."""

import uuid
from functools import cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.api.deps import PrincipalDep, SessionDep
from shipready.api.schemas import (
    BoxOut,
    CheckOut,
    DocumentOut,
    FieldOut,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentOut,
)
from shipready.db.models import (
    CheckResult,
    Document,
    DocumentPart,
    ExtractedField,
    Shipment,
)
from shipready.rules.catalogue import RuleSpec, load_catalogue

router = APIRouter(prefix="/shipments", tags=["shipments"])
# Failures first, then what could not be decided, then what passed.
_OUTCOME_ORDER = {"fail": 0, "not_verified": 1, "pass": 2}


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


@router.get("/{shipment_id}/fields")
def list_fields(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[FieldOut]:
    """The fields read from the shipment's documents, each with its evidence: empty until the
    shipment is extracted."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    return list(_fields_of(session, shipment.id).values())


@router.get("/{shipment_id}/checks")
def list_checks(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[CheckOut]:
    """The outcome of each check, failures first, with the fields it read as evidence: empty
    until the shipment is checked."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    fields = _fields_of(session, shipment.id)
    rules = {rule.id: rule for rule in _catalogue()}
    results = session.scalars(select(CheckResult).where(CheckResult.shipment_id == shipment.id))
    checks = [
        CheckOut(
            rule_id=result.rule_id,
            title=rules[result.rule_id].title,
            severity=rules[result.rule_id].severity,
            outcome=result.outcome,
            message=result.message,
            evidence=[fields[path] for path in result.evidence if path in fields],
        )
        for result in results
    ]
    return sorted(checks, key=lambda c: (_OUTCOME_ORDER[c.outcome], c.rule_id))


@cache
def _catalogue() -> list[RuleSpec]:
    return load_catalogue()


def _fields_of(session: Session, shipment_id: uuid.UUID) -> dict[str, FieldOut]:
    rows = session.execute(
        select(ExtractedField, DocumentPart.document_id)
        .join(DocumentPart, ExtractedField.part_id == DocumentPart.id)
        .where(ExtractedField.shipment_id == shipment_id)
        .order_by(ExtractedField.path)
    )
    return {
        field.path: FieldOut(
            path=field.path,
            value=field.value,
            quote=field.quote,
            document_id=document_id,
            page_no=field.page_no,
            box=BoxOut.model_validate(field.box) if field.box else None,
            model=field.model,
        )
        for field, document_id in rows
    }


def shipment_of(session: Session, org_id: uuid.UUID, shipment_id: uuid.UUID) -> Shipment:
    """The shipment if it belongs to `org_id`. Another organisation's shipment is reported as
    not found, so its existence is not revealed."""
    shipment = session.get(Shipment, shipment_id)
    if shipment is None or shipment.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "shipment not found")
    return shipment
