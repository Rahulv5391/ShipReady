import random
import runpy
import uuid
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.render.sheets import render_pdf
from shipready import worker
from shipready.ai import AiAnswer, RateLimited
from shipready.db.models import Document, DocumentPage, DocumentPart, Organization, Shipment
from shipready.db.seed import DEMO_ORG, DEMO_ORG_ID
from shipready.storage import Storage

BUCKET = "shipready-test"


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield Storage(client, BUCKET)


def bundle_pdf() -> bytes:
    """An invoice followed by an untitled page and a packing list, in one file."""
    documents = build_documents(generate_shipment(11, 0))
    parts = [
        ("commercial_invoice", documents.commercial_invoice, "erp"),
        ("packing_list", documents.packing_list, "word"),
    ]
    return render_pdf(parts, random.Random(0))  # type: ignore[arg-type]


def stored_document(session: Session, storage: Storage, data: bytes, media: str) -> uuid.UUID:
    session.add(Organization(**DEMO_ORG))
    shipment = Shipment(org_id=DEMO_ORG_ID, reference="JOB-1")
    session.add(shipment)
    session.flush()
    key = f"orgs/{DEMO_ORG_ID}/shipments/{shipment.id}/documents/d/file"
    storage.put(key, data, media)
    document = Document(
        org_id=DEMO_ORG_ID,
        shipment_id=shipment.id,
        filename="file",
        media_type=media,
        size_bytes=len(data),
        sha256="0" * 64,
        storage_key=key,
    )
    session.add(document)
    session.commit()
    return document.id


@pytest.fixture
def engine_of(session: Session) -> Engine:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    return bind


def test_processing_stores_pages_and_parts(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "never")
    document_id = stored_document(session, storage, bundle_pdf(), "application/pdf")
    worker.process(engine_of, storage, None, document_id)

    session.expire_all()
    document = session.get(Document, document_id)
    assert document is not None
    assert (document.status, document.error) == ("processed", None)
    assert [(p.doc_type, p.decided_by) for p in document.parts][:2] == [
        ("commercial_invoice", "title"),
        ("packing_list", "title"),
    ]
    pages = session.scalars(select(DocumentPage).order_by(DocumentPage.page_no)).all()
    assert document.page_count == len(pages) >= 2
    assert pages[0].text_source == "pdf_text"
    assert pages[0].image_key is not None
    assert storage.get(pages[0].image_key).startswith(b"\x89PNG")
    assert {"t", "x0", "y0", "x1", "y1"} == set(pages[0].words[0])


def test_processing_twice_replaces_the_results(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "never")
    document_id = stored_document(session, storage, bundle_pdf(), "application/pdf")
    worker.process(engine_of, storage, None, document_id)
    worker.process(engine_of, storage, None, document_id)
    pages = session.scalar(select(func.count()).select_from(DocumentPage))
    parts = session.scalar(select(func.count()).select_from(DocumentPart))
    document = session.get(Document, document_id)
    assert document is not None and document.page_count == pages
    assert parts == len(document.parts)


def test_unreadable_file_is_marked_failed(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "never")
    document_id = stored_document(session, storage, b"%PDF-1.7 broken", "application/pdf")
    with pytest.raises(Exception, match=r"(?i)pdf"):
        worker.process(engine_of, storage, None, document_id)
    session.expire_all()
    document = session.get(Document, document_id)
    assert document is not None and document.status == "failed"
    assert document.error is not None and len(document.error) <= worker.MAX_ERROR_CHARS
    assert session.scalar(select(func.count()).select_from(DocumentPage)) == 0


class LimitedAi:
    def classify(self, page_text: str) -> AiAnswer:
        raise RateLimited(30)


def test_rate_limit_leaves_the_file_waiting(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "always")
    document_id = stored_document(session, storage, bundle_pdf(), "application/pdf")
    with pytest.raises(RateLimited):
        worker.process(engine_of, storage, LimitedAi(), document_id)
    session.expire_all()
    document = session.get(Document, document_id)
    assert document is not None and document.status == "uploaded"
    assert session.scalar(select(func.count()).select_from(DocumentPart)) == 0


def test_task_retries_after_a_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def limited(*args: object) -> None:
        raise RateLimited(42)

    retries: list[float] = []

    def retry(countdown: float) -> Exception:
        retries.append(countdown)
        return RuntimeError("retry scheduled")

    monkeypatch.setattr(worker, "process", limited)
    monkeypatch.setattr(worker, "_engine", lambda: None)
    monkeypatch.setattr(worker, "_storage", lambda: None)
    monkeypatch.setattr(worker, "_classifier", lambda: None)
    monkeypatch.setattr(worker.process_document, "retry", retry)
    with pytest.raises(RuntimeError, match="retry scheduled"):
        worker.process_document.run(str(uuid.uuid4()))
    assert retries == [42]


def test_missing_document_is_skipped(session: Session, engine_of: Engine, storage: Storage) -> None:
    worker.process(engine_of, storage, None, uuid.uuid4())  # no error: nothing to do


def test_requeue_queues_waiting_files(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = stored_document(session, storage, bundle_pdf(), "application/pdf")
    queued: list[str] = []
    monkeypatch.setattr(worker.process_document, "delay", queued.append)
    assert worker.requeue(engine_of) == 1
    assert queued == [str(document_id)]


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_task_name_does_not_depend_on_how_the_module_is_loaded() -> None:
    # `python -m shipready.worker requeue` runs the module under another name (__main__); the
    # task it queues must still be the one the worker knows.
    loaded_elsewhere = runpy.run_module("shipready.worker", run_name="loaded_elsewhere")
    assert loaded_elsewhere["process_document"].name == worker.process_document.name
