"""The background worker: reads each uploaded file's pages and splits it into documents, then,
once every file of a shipment is read, reads the shipment's fields with their evidence and runs
the deterministic checks on them.

    uv run --env-file .env celery -A shipready.worker worker --pool=solo --loglevel=info
    uv run --env-file .env python -m shipready.worker requeue    # queue files still "uploaded"

The API queues `process_document` after an upload; that queues `extract_shipment` when it read
the shipment's last waiting file. Each run replaces what an earlier run wrote, so running a task
again (a retry, a requeue) is safe.
"""

import argparse
import io
import logging
import os
import uuid
from dataclasses import asdict
from functools import cache
from typing import Any

from celery import Celery
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from shipready.ai import (
    PageClassifier,
    RateLimited,
    ai_mode,
    classifier_from_env,
    extractor_from_env,
)
from shipready.checks.engine import run_checks
from shipready.checks.reference import DbReference
from shipready.classify import split_into_parts
from shipready.db.models import (
    CheckResult,
    Document,
    DocumentPage,
    DocumentPart,
    ExtractedField,
    Shipment,
)
from shipready.db.session import make_engine
from shipready.extract import DocumentText, FieldExtractor, extract_fields
from shipready.pages import Page, Word, read_pages, text_source
from shipready.storage import Storage, make_storage, settings_from_env

logger = logging.getLogger(__name__)
# A failure message is kept short: enough to see what went wrong, never a whole document.
MAX_ERROR_CHARS = 500

app = Celery("shipready", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
app.conf.update(
    # A task is acknowledged when it finishes, so a worker that dies mid-file does not lose it.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # The API must answer quickly even when Redis is down.
    broker_connection_timeout=5,
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0.5, "interval_step": 1},
)


# An explicit name: `python -m shipready.worker requeue` loads this module as __main__, and
# Celery would otherwise name the task after that, which the worker does not know.
@app.task(name="shipready.worker.process_document", bind=True, max_retries=8)  # type: ignore[untyped-decorator]
def process_document(self: Any, document_id: str) -> None:
    try:
        ready = process(_engine(), _storage(), _classifier(), uuid.UUID(document_id))
    except RateLimited as error:
        # The AI quota resets with time; the file waits rather than fails.
        raise self.retry(countdown=error.retry_after) from error
    if ready is not None:
        extract_shipment.delay(str(ready))


@app.task(name="shipready.worker.extract_shipment", bind=True, max_retries=8)  # type: ignore[untyped-decorator]
def extract_shipment(self: Any, shipment_id: str) -> None:
    try:
        extract(_engine(), _extractor(), uuid.UUID(shipment_id))
    except RateLimited as error:
        raise self.retry(countdown=error.retry_after) from error
    check(_engine(), uuid.UUID(shipment_id))


def process(
    engine: Engine, storage: Storage, ai: PageClassifier | None, document_id: uuid.UUID
) -> uuid.UUID | None:
    """Read the file's pages and split it into parts. Returns its shipment's ID when every file
    of the shipment has now been read, so the shipment is ready for extraction."""
    with Session(engine) as session:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("document %s no longer exists", document_id)
            return None
        document.status, document.error = "processing", None
        session.commit()
        try:
            pages = read_pages(storage.get(document.storage_key), document.media_type)
            parts = split_into_parts(pages, ai_mode(), ai)
            session.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
            session.execute(delete(DocumentPart).where(DocumentPart.document_id == document.id))
            for page in pages:
                session.add(_page_row(storage, document, page))
            session.add_all(DocumentPart(document_id=document.id, **asdict(part)) for part in parts)
            document.page_count, document.status = len(pages), "processed"
            session.commit()
            return document.shipment_id if _all_read(session, document.shipment_id) else None
        except RateLimited:
            session.rollback()
            document.status = "uploaded"
            session.commit()
            raise
        except Exception as error:
            session.rollback()
            document.status = "failed"
            document.error = f"{type(error).__name__}: {error}"[:MAX_ERROR_CHARS]
            session.commit()
            logger.exception("processing document %s failed", document_id)
            raise


def _all_read(session: Session, shipment_id: uuid.UUID) -> bool:
    statuses = session.scalars(select(Document.status).where(Document.shipment_id == shipment_id))
    return all(status == "processed" for status in statuses)


def extract(engine: Engine, extractor: FieldExtractor, shipment_id: uuid.UUID) -> None:
    """Read every field of the shipment's documents in one request and store each with its
    evidence, replacing the fields of an earlier run."""
    with Session(engine) as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            logger.warning("shipment %s no longer exists", shipment_id)
            return
        try:
            documents, parts = _documents_of(session, shipment_id)
            fields = extract_fields(documents, extractor)
            session.execute(delete(ExtractedField).where(ExtractedField.shipment_id == shipment_id))
            session.add_all(
                ExtractedField(
                    shipment_id=shipment_id,
                    part_id=parts[field.part].id,
                    path=field.path,
                    value=field.value,
                    quote=field.quote,
                    page_no=field.page,
                    box=asdict(field.box) if field.box else None,
                    model=extractor.model,
                )
                for field in fields
            )
            shipment.status, shipment.error = "EXTRACTED", None
            session.commit()
        except RateLimited:
            session.rollback()
            raise
        except Exception as error:
            _failed(session, shipment, error, "extracting")
            raise


def check(engine: Engine, shipment_id: uuid.UUID) -> None:
    """Run the deterministic checks on the shipment's extracted fields and store each result,
    replacing those of an earlier run."""
    with Session(engine) as session:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            logger.warning("shipment %s no longer exists", shipment_id)
            return
        try:
            rows = session.execute(
                select(ExtractedField.path, ExtractedField.value).where(
                    ExtractedField.shipment_id == shipment_id
                )
            )
            values = {path: value for path, value in rows}
            results = run_checks(values, DbReference(session))
            session.execute(delete(CheckResult).where(CheckResult.shipment_id == shipment_id))
            session.add_all(
                CheckResult(
                    shipment_id=shipment_id,
                    rule_id=result.rule_id,
                    outcome=result.outcome,
                    message=result.message,
                    evidence=list(result.evidence),
                )
                for result in results
            )
            shipment.status, shipment.error = "CHECKED", None
            session.commit()
        except Exception as error:
            _failed(session, shipment, error, "checking")
            raise


def _failed(session: Session, shipment: Shipment, error: Exception, stage: str) -> None:
    """Keep a short reason on the shipment, so the failure shows without reading logs."""
    session.rollback()
    shipment.error = f"{type(error).__name__}: {error}"[:MAX_ERROR_CHARS]
    session.commit()
    logger.exception("%s shipment %s failed", stage, shipment.id)


def _documents_of(
    session: Session, shipment_id: uuid.UUID
) -> tuple[list[DocumentText], dict[int, DocumentPart]]:
    """The shipment's documents of a known type, numbered from 1 in upload order, and the part
    each number stands for. Pages are numbered as in their file."""
    documents: list[DocumentText] = []
    parts: dict[int, DocumentPart] = {}
    files = session.scalars(
        select(Document).where(Document.shipment_id == shipment_id).order_by(Document.uploaded_at)
    )
    for document in files:
        pages = {
            row.page_no: _page_of(row)
            for row in session.scalars(
                select(DocumentPage).where(DocumentPage.document_id == document.id)
            )
        }
        for part in document.parts:
            if part.doc_type == "other":
                continue
            number = len(documents) + 1
            span = tuple(pages[n] for n in range(part.first_page, part.last_page + 1))
            documents.append(DocumentText(number, part.doc_type, document.filename, span))
            parts[number] = part
    return documents, parts


def _page_of(row: DocumentPage) -> Page:
    words = tuple(Word(w["t"], w["x0"], w["y0"], w["x1"], w["y1"]) for w in row.words)
    return Page(row.page_no, row.text, words, text_source(row.text_source), None)


def _page_row(storage: Storage, document: Document, page: Page) -> DocumentPage:
    image_key = None
    width = height = None
    if page.image is not None:
        buffer = io.BytesIO()
        page.image.save(buffer, format="PNG")
        # Next to the file, so deleting a shipment's folder removes its pages too.
        image_key = f"{document.storage_key.rsplit('/', 1)[0]}/pages/{page.number}.png"
        storage.put(image_key, buffer.getvalue(), "image/png")
        width, height = page.image.size
    return DocumentPage(
        document_id=document.id,
        page_no=page.number,
        image_key=image_key,
        width_px=width,
        height_px=height,
        text_source=page.source,
        text=page.text,
        words=[{"t": w.text, "x0": w.x0, "y0": w.y0, "x1": w.x1, "y1": w.y1} for w in page.words],
    )


@cache
def _engine() -> Engine:
    return make_engine()


@cache
def _storage() -> Storage:
    return make_storage(settings_from_env())


@cache
def _classifier() -> PageClassifier | None:
    return classifier_from_env()


@cache
def _extractor() -> FieldExtractor:
    return extractor_from_env()


def requeue(engine: Engine) -> int:
    """Queue every file still waiting ("uploaded"), e.g. after Redis was down at upload."""
    with Session(engine) as session:
        waiting = list(session.scalars(select(Document.id).where(Document.status == "uploaded")))
    for document_id in waiting:
        process_document.delay(str(document_id))
    return len(waiting)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ShipReady worker commands.")
    parser.add_argument("command", choices=["requeue"])
    parser.parse_args(argv)
    engine = make_engine()
    try:
        print(f"queued {requeue(engine)} documents")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
