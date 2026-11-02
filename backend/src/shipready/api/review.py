"""A shipment's runs and a person's review of them: drafted messages approved or discarded, and
the shipment marked ready or needing fixes, which ends the run. Every decision is recorded with
who made it and why (the `approvals` table)."""

import json
import time
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from kombu.exceptions import OperationalError
from sqlalchemy import Connection, Engine, select
from sqlalchemy.orm import Session

from shipready.api.deps import PrincipalDep, RecheckDep, SessionDep
from shipready.api.schemas import ApprovalOut, Decision, MessageEdit, MessageOut, RunOut
from shipready.api.shipments import shipment_of
from shipready.db.models import (
    Approval,
    CheckResult,
    Document,
    Message,
    Run,
    RunEvent,
    Shipment,
)
from shipready.rules.catalogue import load_catalogue
from shipready.runs import active_run, enter_stage, finish, start_run

router = APIRouter(tags=["review"])
# The stream checks for new events this often, comments every KEEP_ALIVE_S when quiet, and
# closes after MAX_STREAM_S so connections do not pile up; the client reconnects and resumes.
POLL_S = 1.0
KEEP_ALIVE_S = 15.0
MAX_STREAM_S = 600.0


@router.get("/shipments/{shipment_id}/runs")
def list_runs(shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> list[RunOut]:
    shipment = shipment_of(session, principal.org_id, shipment_id)
    runs = session.scalars(
        select(Run).where(Run.shipment_id == shipment.id).order_by(Run.started_at.desc())
    )
    return [RunOut.model_validate(run) for run in runs]


@router.post("/shipments/{shipment_id}/runs", status_code=status.HTTP_201_CREATED)
def recheck(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, queue: RecheckDep
) -> RunOut:
    """Extract and check the shipment's files again, e.g. after a rule or model changed."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    if active_run(session, shipment.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a run of this shipment is in progress")
    statuses = list(
        session.scalars(select(Document.status).where(Document.shipment_id == shipment.id))
    )
    if not statuses or any(s != "processed" for s in statuses):
        raise HTTPException(status.HTTP_409_CONFLICT, "the shipment's files are not all read")
    run = start_run(session, shipment, "recheck")
    enter_stage(session, run, "extracting")
    session.commit()
    try:
        queue(shipment.id)
    except OperationalError as error:
        finish(session, run, f"the work queue is unavailable: {error}")
        session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the work queue is unavailable"
        ) from None
    return RunOut.model_validate(run)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> RunOut:
    return RunOut.model_validate(run_of(session, principal.org_id, run_id))


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> StreamingResponse:
    """The run's events as Server-Sent Events: those so far, then each as it happens, until the
    run is done or failed. A client that reconnects sends the last ID it saw and resumes."""
    run_of(session, principal.org_id, run_id)
    engine = session.get_bind()
    return StreamingResponse(
        _stream(engine, run_id, last_event_id or 0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _stream(engine: Engine | Connection, run_id: uuid.UUID, after: int) -> Iterator[str]:
    # Its own sessions: the request's may close while the stream is still open.
    started = time.monotonic()
    quiet_since = started
    while time.monotonic() - started < MAX_STREAM_S:
        with Session(engine) as session:
            events = session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.id > after)
                .order_by(RunEvent.id)
            ).all()
            ended = session.get_one(Run, run_id).status in ("done", "failed")
        for event in events:
            data = {**event.data, "at": event.at.isoformat()}
            yield f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(data)}\n\n"
            after, quiet_since = event.id, time.monotonic()
        if ended and not events:
            return
        if time.monotonic() - quiet_since > KEEP_ALIVE_S:
            yield ": keep-alive\n\n"  # a comment: keeps proxies from closing a quiet stream
            quiet_since = time.monotonic()
        time.sleep(POLL_S)


def run_of(session: Session, org_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    """The run if it belongs to `org_id`; another organisation's is not found."""
    run = session.get(Run, run_id)
    if run is None or run.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.get("/shipments/{shipment_id}/messages")
def list_messages(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[MessageOut]:
    shipment = shipment_of(session, principal.org_id, shipment_id)
    messages = session.scalars(
        select(Message)
        .where(Message.shipment_id == shipment.id)
        .order_by(Message.created_at.desc(), Message.recipient)
    )
    return [MessageOut.model_validate(m) for m in messages]


@router.patch("/messages/{message_id}")
def edit_message(
    message_id: uuid.UUID, body: MessageEdit, principal: PrincipalDep, session: SessionDep
) -> MessageOut:
    message = _draft(session, principal.org_id, message_id)
    if body.subject is not None:
        message.subject = body.subject
    if body.body is not None:
        message.body = body.body
    session.commit()
    return MessageOut.model_validate(message)


@router.post("/messages/{message_id}/approve")
def approve_message(
    message_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> MessageOut:
    return _decide_message(session, principal.org_id, principal.user, message_id, "approved")


@router.post("/messages/{message_id}/discard")
def discard_message(
    message_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> MessageOut:
    return _decide_message(session, principal.org_id, principal.user, message_id, "discarded")


def _draft(session: Session, org_id: uuid.UUID, message_id: uuid.UUID) -> Message:
    """A message still a draft, of a shipment of `org_id`."""
    message = session.get(Message, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    shipment_of(session, org_id, message.shipment_id)  # 404 for another organisation
    if message.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"the message is already {message.status}")
    return message


def _decide_message(
    session: Session, org_id: uuid.UUID, user: str, message_id: uuid.UUID, decision: str
) -> MessageOut:
    message = _draft(session, org_id, message_id)
    message.status = decision
    action = "approve_message" if decision == "approved" else "discard_message"
    session.add(
        Approval(
            shipment_id=message.shipment_id,
            run_id=message.run_id,
            action=action,
            target_id=message.id,
            decided_by=user,
        )
    )
    session.commit()
    return MessageOut.model_validate(message)


@router.post("/shipments/{shipment_id}/mark-ready")
def mark_ready(
    shipment_id: uuid.UUID, body: Decision, principal: PrincipalDep, session: SessionDep
) -> ApprovalOut:
    """Mark the shipment ready to file. While a blocker check fails, a reason is required: the
    person takes responsibility for overriding it."""
    shipment, run = _under_review(session, principal.org_id, shipment_id)
    blockers = _failed_blockers(session, shipment.id)
    if blockers and body.reason is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"blocker checks fail ({', '.join(blockers)}); give a reason to mark it ready anyway",
        )
    return _close(session, shipment, run, principal.user, "mark_ready", "READY", body.reason)


@router.post("/shipments/{shipment_id}/mark-needs-fix")
def mark_needs_fix(
    shipment_id: uuid.UUID, body: Decision, principal: PrincipalDep, session: SessionDep
) -> ApprovalOut:
    """Send the shipment back for corrected documents; uploading them starts a new run."""
    shipment, run = _under_review(session, principal.org_id, shipment_id)
    return _close(
        session, shipment, run, principal.user, "mark_needs_fix", "NEEDS_FIX", body.reason
    )


@router.get("/shipments/{shipment_id}/approvals")
def list_approvals(
    shipment_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[ApprovalOut]:
    shipment = shipment_of(session, principal.org_id, shipment_id)
    approvals = session.scalars(
        select(Approval).where(Approval.shipment_id == shipment.id).order_by(Approval.decided_at)
    )
    return [ApprovalOut.model_validate(a) for a in approvals]


def _under_review(
    session: Session, org_id: uuid.UUID, shipment_id: uuid.UUID
) -> tuple[Shipment, Run]:
    shipment = shipment_of(session, org_id, shipment_id)
    run = active_run(session, shipment.id)
    if run is None or run.status != "awaiting_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "the shipment is not awaiting review")
    return shipment, run


def _failed_blockers(session: Session, shipment_id: uuid.UUID) -> list[str]:
    blockers = {rule.id for rule in load_catalogue() if rule.severity == "blocker"}
    failed = session.scalars(
        select(CheckResult.rule_id).where(
            CheckResult.shipment_id == shipment_id, CheckResult.outcome == "fail"
        )
    )
    return sorted(rule for rule in failed if rule in blockers)


def _close(
    session: Session,
    shipment: Shipment,
    run: Run,
    user: str,
    action: str,
    shipment_status: str,
    reason: str | None,
) -> ApprovalOut:
    approval = Approval(
        shipment_id=shipment.id, run_id=run.id, action=action, decided_by=user, reason=reason
    )
    session.add(approval)
    shipment.status = shipment_status
    finish(session, run)
    session.commit()
    return ApprovalOut.model_validate(approval)
