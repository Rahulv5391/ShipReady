"""The background worker: reads each uploaded file's pages and splits it into documents.

    uv run --env-file .env celery -A shipready.worker worker --pool=solo --loglevel=info
    uv run --env-file .env python -m shipready.worker requeue    # queue files still "uploaded"

The API queues `process_document` after an upload. A run replaces the file's pages and parts, so
running it again (a retry, a requeue) is safe.
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

from shipready.ai import PageClassifier, RateLimited, ai_mode, classifier_from_env
from shipready.classify import split_into_parts
from shipready.db.models import Document, DocumentPage, DocumentPart
from shipready.db.session import make_engine
from shipready.pages import Page, read_pages
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
        process(_engine(), _storage(), _classifier(), uuid.UUID(document_id))
    except RateLimited as error:
        # The AI quota resets with time; the file waits rather than fails.
        raise self.retry(countdown=error.retry_after) from error


def process(
    engine: Engine, storage: Storage, ai: PageClassifier | None, document_id: uuid.UUID
) -> None:
    with Session(engine) as session:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("document %s no longer exists", document_id)
            return
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
