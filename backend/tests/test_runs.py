import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.ai import Problem
from shipready.checks.engine import Result
from shipready.db.models import Organization, Run, RunEvent, Shipment
from shipready.db.seed import DEMO_ORG, DEMO_ORG_ID
from shipready.drafts import recipients, requests
from shipready.runs import (
    active_run,
    await_review,
    current_run,
    enter_stage,
    finish,
    record,
    start_run,
)


@pytest.fixture
def shipment(session: Session) -> Shipment:
    session.add(Organization(**DEMO_ORG))
    shipment = Shipment(org_id=DEMO_ORG_ID, reference="JOB-1")
    session.add(shipment)
    session.commit()
    return shipment


def events(session: Session, run: Run) -> list[tuple[str, dict[str, object]]]:
    rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id))
    return [(e.type, e.data) for e in rows]


def test_a_run_goes_through_its_stages_to_review_and_ends(
    session: Session, shipment: Shipment
) -> None:
    run = current_run(session, shipment)
    enter_stage(session, run, "reading")
    record(session, run, "document_read", file="invoice.pdf")
    await_review(session, run, shipment)
    session.commit()
    assert (run.trigger, run.status, run.stage) == ("upload", "awaiting_review", None)
    assert shipment.status == "AWAITING_REVIEW"
    assert active_run(session, shipment.id) == run

    finish(session, run)
    session.commit()
    assert (run.status, run.finished_at is not None) == ("done", True)
    assert active_run(session, shipment.id) is None
    assert [t for t, _ in events(session, run)] == [
        "run_started",
        "stage_started",
        "document_read",
        "awaiting_review",
        "run_done",
    ]


def test_files_uploaded_during_review_reopen_the_run(session: Session, shipment: Shipment) -> None:
    run = current_run(session, shipment)
    await_review(session, run, shipment)
    session.commit()
    assert current_run(session, shipment) == run  # the same run, back at work
    assert run.status == "running"
    assert events(session, run)[-1][0] == "review_reopened"


def test_a_failed_run_keeps_its_error(session: Session, shipment: Shipment) -> None:
    run = current_run(session, shipment)
    finish(session, run, "extracting failed: ValueError")
    session.commit()
    assert (run.status, run.error) == ("failed", "extracting failed: ValueError")
    assert events(session, run)[-1] == ("run_failed", {"error": "extracting failed: ValueError"})
    assert current_run(session, shipment) != run  # a new upload starts a new run


def test_the_database_refuses_two_active_runs(session: Session, shipment: Shipment) -> None:
    start_run(session, shipment, "upload")
    session.commit()
    with pytest.raises(IntegrityError, match="one_active_run"):
        start_run(session, shipment, "recheck")


def test_problems_go_to_the_issuer_of_the_document_found_wrong() -> None:
    def result(*paths: str) -> Result:
        return Result("QTY-01", "fail", "line 1 differs", paths)

    invoice_and_bill = result("commercial_invoice.lines[0].quantity", "bill_of_lading.total")
    assert recipients(invoice_and_bill) == {"forwarder"}
    assert recipients(result("commercial_invoice.total", "packing_list.total")) == {"exporter"}
    assert recipients(result()) == {"exporter"}  # a missing document: nothing to point to
    three = result("shipping_bill.x", "purchase_order.y", "certificate_of_origin.z")
    assert recipients(three) == {"customs_broker", "buyer", "certifier"}


def test_only_failures_are_asked_about() -> None:
    results = [
        Result("INV-01", "fail", "numbers differ", ("shipping_bill.invoice_number",)),
        Result("FX-01", "not_verified", "no rate", ("shipping_bill.exchange_rate",)),
        Result("ID-02", "pass", "", ("shipping_bill.gstin",)),
        Result("DOC-01", "fail", "missing: bill of lading", ()),
    ]
    assert requests(results) == {
        "customs_broker": [
            Problem("INV-01", "Invoice number and date match the shipping bill", "numbers differ")
        ],
        "exporter": [Problem("DOC-01", "Required documents present", "missing: bill of lading")],
    }
    assert requests([]) == {}
