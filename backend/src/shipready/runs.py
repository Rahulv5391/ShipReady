"""A shipment's run: its processing from the files to a person's review, as stages and events
(PLAN.md Section 10.2; without the Agents SDK, Decision.md D-33).

reading -> extracting -> checking -> drafting -> awaiting review -> done (a person's decision)

Every step adds an event, which the live progress stream sends. A run that fails keeps its
error. These functions change the session only; the caller commits, so a run's state changes
with the work it describes.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shipready.db.models import Run, RunEvent, Shipment

ACTIVE = ("running", "awaiting_review")


def active_run(session: Session, shipment_id: uuid.UUID) -> Run | None:
    return session.scalar(select(Run).where(Run.shipment_id == shipment_id, Run.status.in_(ACTIVE)))


def start_run(session: Session, shipment: Shipment, trigger: str) -> Run:
    """A new run of `shipment`; the caller checks none is active (the database refuses a
    second one)."""
    run = Run(org_id=shipment.org_id, shipment_id=shipment.id, trigger=trigger)
    session.add(run)
    session.flush()
    record(session, run, "run_started", trigger=trigger)
    return run


def current_run(session: Session, shipment: Shipment) -> Run:
    """The shipment's active run, or a new one. Files uploaded while a run is active join it;
    a run awaiting review goes back to work on them."""
    run = active_run(session, shipment.id) or start_run(session, shipment, "upload")
    if run.status == "awaiting_review":
        run.status = "running"
        record(session, run, "review_reopened")
    return run


def record(session: Session, run: Run, event: str, **data: Any) -> None:
    session.add(RunEvent(run_id=run.id, type=event, data=data))


def enter_stage(session: Session, run: Run, stage: str) -> None:
    run.stage = stage
    record(session, run, "stage_started", stage=stage)


def await_review(session: Session, run: Run, shipment: Shipment) -> None:
    run.status, run.stage = "awaiting_review", None
    shipment.status = "AWAITING_REVIEW"
    record(session, run, "awaiting_review", readiness=shipment.readiness)


def finish(session: Session, run: Run, error: str | None = None) -> None:
    """End the run: done after a person's decision, failed with `error`."""
    run.status = "failed" if error else "done"
    run.stage, run.error = None, error
    run.finished_at = datetime.now(UTC)
    if error:
        record(session, run, "run_failed", error=error)
    else:
        record(session, run, "run_done")
