"""Shipments: create, list and read, always within the caller's organisation."""

import uuid
from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.api.deps import PrincipalDep, SessionDep
from shipready.api.schemas import (
    BoxOut,
    CheckOut,
    CitationOut,
    DocumentOut,
    FieldOut,
    RunBrief,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentListItem,
    ShipmentOut,
)
from shipready.db.models import (
    CheckResult,
    Document,
    DocumentPart,
    ExtractedField,
    Run,
    RunEvent,
    Shipment,
)
from shipready.knowledge.sources import Source, load_sources
from shipready.rules.catalogue import RuleSpec, load_catalogue

router = APIRouter(prefix="/shipments", tags=["shipments"])
# Failures first, then what could not be decided, then what passed.
_OUTCOME_ORDER = {"fail": 0, "not_verified": 1, "pass": 2}
# Where the queue's summary comes from: the first of these fields the shipment has.
SUMMARY_FIELDS: dict[str, tuple[str, ...]] = {
    "exporter": (
        "commercial_invoice.exporter.name",
        "shipping_bill.exporter_name",
        "packing_list.exporter.name",
    ),
    "consignee": (
        "commercial_invoice.consignee.name",
        "shipping_bill.consignee_name",
        "bill_of_lading.consignee.name",
        "air_waybill.consignee.name",
    ),
    "destination_country": (
        "commercial_invoice.destination_country",
        "shipping_bill.consignee_country",
        "certificate_of_origin.destination_country",
    ),
    "port_of_loading": (
        "commercial_invoice.port_of_loading.code",
        "bill_of_lading.port_of_loading.code",
        "air_waybill.airport_of_departure.code",
        "shipping_bill.port_code",
    ),
    "port_of_discharge": (
        "commercial_invoice.port_of_discharge.code",
        "bill_of_lading.port_of_discharge.code",
        "air_waybill.airport_of_destination.code",
    ),
}


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
) -> list[ShipmentListItem]:
    query = select(Shipment).where(Shipment.org_id == principal.org_id)
    if q:
        query = query.where(Shipment.reference.icontains(q, autoescape=True))
    query = query.order_by(Shipment.created_at.desc(), Shipment.id).limit(limit).offset(offset)
    shipments = list(session.scalars(query))
    return _list_items(session, shipments)


def _list_items(session: Session, shipments: list[Shipment]) -> list[ShipmentListItem]:
    """Each shipment with its summary, in four queries for the whole page."""
    ids = [s.id for s in shipments]
    paths = [path for choices in SUMMARY_FIELDS.values() for path in choices]
    values: dict[uuid.UUID, dict[str, str]] = {}
    for shipment_id, path, value in session.execute(
        select(ExtractedField.shipment_id, ExtractedField.path, ExtractedField.value).where(
            ExtractedField.shipment_id.in_(ids), ExtractedField.path.in_(paths)
        )
    ):
        values.setdefault(shipment_id, {})[path] = value
    files = {
        shipment_id: count
        for shipment_id, count in session.execute(
            select(Document.shipment_id, func.count())
            .where(Document.shipment_id.in_(ids))
            .group_by(Document.shipment_id)
        )
    }
    latest = {
        run.shipment_id: run
        for run in session.scalars(
            select(Run)
            .where(Run.shipment_id.in_(ids))
            .order_by(Run.shipment_id, Run.started_at.desc())
            .ext(distinct_on(Run.shipment_id))
        )
    }
    last_event = {
        shipment_id: at
        for shipment_id, at in session.execute(
            select(Run.shipment_id, func.max(RunEvent.at))
            .join(RunEvent, RunEvent.run_id == Run.id)
            .where(Run.shipment_id.in_(ids))
            .group_by(Run.shipment_id)
        )
    }
    items = []
    for shipment in shipments:
        found = values.get(shipment.id, {})
        summary = {
            name: next((found[p] for p in choices if p in found), None)
            for name, choices in SUMMARY_FIELDS.items()
        }
        run = latest.get(shipment.id)
        items.append(
            ShipmentListItem.model_validate(
                {
                    **ShipmentOut.model_validate(shipment).model_dump(),
                    **summary,
                    "files": files.get(shipment.id, 0),
                    "run": RunBrief.model_validate(run) if run else None,
                    "updated_at": last_event.get(shipment.id) or shipment.created_at,
                }
            )
        )
    return items


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
    (summary,) = _list_items(session, [shipment])
    return ShipmentDetail(
        **summary.model_dump(), documents=[DocumentOut.model_validate(d) for d in documents]
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
            citations=[_citation(c) for c in result.citations],
            verification=result.verification,
            critic_reason=result.critic_reason,
        )
        for result in results
    ]
    return sorted(checks, key=lambda c: (_OUTCOME_ORDER[c.outcome], c.rule_id))


@cache
def _catalogue() -> list[RuleSpec]:
    return load_catalogue()


@cache
def _sources() -> dict[str, Source]:
    return {source.id: source for source in load_sources()}


def _citation(stored: dict[str, Any]) -> CitationOut:
    source = _sources()[stored["source_id"]]
    return CitationOut(title=source.title, url=source.url, **stored)


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
