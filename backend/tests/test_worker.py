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
from shipready.db.models import (
    Document,
    DocumentPage,
    DocumentPart,
    ExtractedField,
    Organization,
    Shipment,
)
from shipready.db.seed import DEMO_ORG, DEMO_ORG_ID
from shipready.extract import DocumentText, RawField
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


class FakeExtractor:
    """Reads the invoice number off the first document, quoting it as printed."""

    model = "fake-model"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[list[DocumentText]] = []

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        self.calls.append(documents)
        if self.error is not None:
            raise self.error
        number = build_documents(generate_shipment(11, 0)).commercial_invoice.invoice_number
        return [
            RawField(1, "invoice_number", number, number, 1),
            RawField(1, "iec", "0000000000", "not on the page", 1),
        ]


def processed_shipment(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> uuid.UUID:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "never")
    document_id = stored_document(session, storage, bundle_pdf(), "application/pdf")
    ready = worker.process(engine_of, storage, None, document_id)
    assert ready is not None
    return ready


def test_last_file_read_makes_the_shipment_ready(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    waiting = Document(
        org_id=DEMO_ORG_ID,
        shipment_id=shipment_id,
        filename="later.pdf",
        media_type="application/pdf",
        size_bytes=1,
        sha256="1" * 64,
        storage_key="orgs/x/later.pdf",
    )
    session.add(waiting)
    session.commit()
    first = session.scalars(select(Document.id).where(Document.filename == "file")).one()
    # With a file still waiting, reading the other again does not make the shipment ready.
    assert worker.process(engine_of, storage, None, first) is None


def test_extraction_stores_fields_with_evidence(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    extractor = FakeExtractor()
    worker.extract(engine_of, extractor, shipment_id)
    worker.extract(engine_of, extractor, shipment_id)  # replaces

    (documents,) = {tuple(d.doc_type for d in call) for call in extractor.calls}
    assert documents[:2] == ("commercial_invoice", "packing_list")
    assert extractor.calls[0][0].pages[0].words  # words read back from the database
    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None and (shipment.status, shipment.error) == ("EXTRACTED", None)
    fields = {f.path: f for f in session.scalars(select(ExtractedField))}
    assert set(fields) == {"commercial_invoice.invoice_number", "commercial_invoice.iec"}
    number = fields["commercial_invoice.invoice_number"]
    assert number.box is not None and 0 <= number.box["x0"] < number.box["x1"] <= 1
    assert (number.page_no, number.model) == (1, "fake-model")
    assert fields["commercial_invoice.iec"].box is None


def test_failed_extraction_is_recorded(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    with pytest.raises(ValueError, match="unexpected AI answer"):
        worker.extract(engine_of, FakeExtractor(ValueError("unexpected AI answer")), shipment_id)
    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None and shipment.status == "RECEIVED"
    assert shipment.error == "ValueError: unexpected AI answer"


def test_rate_limited_extraction_waits(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    with pytest.raises(RateLimited):
        worker.extract(engine_of, FakeExtractor(RateLimited(5)), shipment_id)
    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None and (shipment.status, shipment.error) == ("RECEIVED", None)


def test_reading_the_last_file_queues_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    shipment_id = uuid.uuid4()
    queued: list[str] = []
    monkeypatch.setattr(worker, "process", lambda *args: shipment_id)
    monkeypatch.setattr(worker, "_engine", lambda: None)
    monkeypatch.setattr(worker, "_storage", lambda: None)
    monkeypatch.setattr(worker, "_classifier", lambda: None)
    monkeypatch.setattr(worker.extract_shipment, "delay", queued.append)
    worker.process_document.run(str(uuid.uuid4()))
    assert queued == [str(shipment_id)]
