import random
import runpy
import uuid
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.render.sheets import render_pdf
from shipready import worker
from shipready.ai import (
    AiAnswer,
    Draft,
    Problem,
    Question,
    RateLimited,
    Review,
    Suspect,
    Verdict,
)
from shipready.checks.engine import deterministic_rules
from shipready.checks.semantic import semantic_rules
from shipready.db.models import (
    EMBEDDING_DIMENSIONS,
    CheckResult,
    Document,
    DocumentPage,
    DocumentPart,
    ExtractedField,
    Message,
    Organization,
    RefItcHs,
    Run,
    RunEvent,
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
    worker.extract(engine_of, extractor, shipment_id, everything=True)  # replaces them all

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


class AgreeingJudge:
    model = "agreeing"

    def judge(self, questions: list[Question]) -> list[Verdict]:
        return [Verdict(q.id, True, 1.0, "") for q in questions]


class NoMisreads:
    """A critic that finds every failure real."""

    model = "no-misreads"

    def __init__(self) -> None:
        self.seen: list[Suspect] = []

    def review(self, suspects: list[Suspect]) -> list[Review]:
        self.seen += suspects
        return [Review(s.id, True, 1.0, "as printed") for s in suspects]


class FlatEmbedder:
    model = "flat"

    def embed(self, texts: list[str], query: bool) -> list[list[float]]:
        return [[1.0] * EMBEDDING_DIMENSIONS for _ in texts]


class DescribedInvoice(FakeExtractor):
    """An invoice line with a description and HS code, so the judge is asked about it."""

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        return [
            RawField(1, "lines[0].description", "Black tea", "Black tea", 1),
            RawField(1, "lines[0].hs_code", "09024020", "0902 40 20", 1),
        ]


class MismatchedQuantities(FakeExtractor):
    """The invoice and the packing list give different quantities for their first line."""

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        return [
            RawField(1, "lines[0].quantity", "10", "10", 1),
            RawField(1, "lines[0].uqc", "PCS", "PCS", 1),
            RawField(2, "lines[0].quantity", "12", "12", 2),
            RawField(2, "lines[0].uqc", "PCS", "PCS", 2),
        ]


def test_checks_run_on_the_extracted_fields(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    worker.extract(engine_of, MismatchedQuantities(), shipment_id)
    worker.check(engine_of, storage, AgreeingJudge(), FlatEmbedder(), NoMisreads(), shipment_id)
    worker.check(
        engine_of, storage, AgreeingJudge(), FlatEmbedder(), NoMisreads(), shipment_id
    )  # replaces them

    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None and (shipment.status, shipment.error) == ("CHECKED", None)
    results = {r.rule_id: r for r in session.scalars(select(CheckResult))}
    assert set(results) == {r.id for r in (*deterministic_rules(), *semantic_rules())}
    quantities = results["QTY-01"]
    assert quantities.outcome == "fail"
    assert quantities.message == "line 1: invoice 10 PCS, packing_list 12 PCS"
    assert quantities.evidence == [
        "commercial_invoice.lines[0].quantity",
        "commercial_invoice.lines[0].uqc",
        "packing_list.lines[0].quantity",
        "packing_list.lines[0].uqc",
    ]
    # Only an invoice and a packing list were read: the shipping bill and transport document are
    # missing (DOC-01), the invoice has no LUT statement (GST-01) and both show few of their
    # mandatory fields (DOC-02). Every other check lacks values, and none fails for that.
    failed = {id_ for id_, r in results.items() if r.outcome == "fail"}
    assert failed == {"QTY-01", "DOC-02", "DOC-01", "GST-01"}
    assert results["DOC-01"].citations == []  # nothing indexed to cite
    assert results["DOC-02"].message.startswith("missing: commercial_invoice.")


def test_a_failed_check_run_is_recorded(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)

    def broken(*args: object) -> None:
        raise RuntimeError("reference tables unreadable")

    monkeypatch.setattr(worker, "run_checks", broken)
    with pytest.raises(RuntimeError):
        worker.check(engine_of, storage, AgreeingJudge(), FlatEmbedder(), NoMisreads(), shipment_id)
    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None
    assert shipment.error == "RuntimeError: reference tables unreadable"
    assert session.scalar(select(func.count()).select_from(CheckResult)) == 0


def test_extraction_task_queues_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    shipment_id = str(uuid.uuid4())
    calls: list[str] = []
    monkeypatch.setattr(worker, "_engine", lambda: None)
    monkeypatch.setattr(worker, "_extractor", lambda: None)
    monkeypatch.setattr(worker, "extract", lambda *args: calls.append(f"extract {args[3]}"))
    monkeypatch.setattr(worker.check_shipment, "delay", lambda id_: calls.append(f"queue {id_}"))
    worker.extract_shipment.run(shipment_id)
    worker.extract_shipment.run(shipment_id, True)
    assert calls == [
        "extract False",
        f"queue {shipment_id}",
        "extract True",
        f"queue {shipment_id}",
    ]


def test_a_rate_limited_judge_retries_the_checks_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def limited(*args: object) -> None:
        raise RateLimited(25)

    retries: list[float] = []

    def retry(countdown: float) -> Exception:
        retries.append(countdown)
        return RuntimeError("retry scheduled")

    for name in ("_engine", "_storage", "_judge", "_embedder", "_critic"):
        monkeypatch.setattr(worker, name, lambda: None)
    monkeypatch.setattr(worker, "check", limited)
    monkeypatch.setattr(worker.check_shipment, "retry", retry)
    with pytest.raises(RuntimeError, match="retry scheduled"):
        worker.check_shipment.run(str(uuid.uuid4()))
    assert retries == [25]


class LimitedJudge:
    model = "limited"

    def judge(self, questions: list[Question]) -> list[Verdict]:
        raise RateLimited(25)


def test_a_rate_limited_check_leaves_no_error(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    session.add(RefItcHs(code="09024020", level=8, description="Black tea"))
    session.commit()
    worker.extract(engine_of, DescribedInvoice(), shipment_id)
    with pytest.raises(RateLimited):
        worker.check(engine_of, storage, LimitedJudge(), FlatEmbedder(), NoMisreads(), shipment_id)
    session.expire_all()
    shipment = session.get(Shipment, shipment_id)
    assert shipment is not None and (shipment.status, shipment.error) == ("EXTRACTED", None)


class AllMisread(NoMisreads):
    """A critic that finds every failure a misreading."""

    def review(self, suspects: list[Suspect]) -> list[Review]:
        self.seen += suspects
        return [Review(s.id, False, 0.95, "the page shows the same quantity") for s in suspects]


def test_the_critic_sees_the_pages_and_its_verdict_is_kept(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    worker.extract(engine_of, MismatchedQuantities(), shipment_id)
    critic = AllMisread()
    worker.check(engine_of, storage, AgreeingJudge(), FlatEmbedder(), critic, shipment_id)

    (quantities,) = [s for s in critic.seen if s.id == "QTY-01"]
    assert quantities.crops and all(c.png.startswith(b"\x89PNG") for c in quantities.crops)
    session.expire_all()
    results = {r.rule_id: r for r in session.scalars(select(CheckResult))}
    reviewed = results["QTY-01"]
    assert (reviewed.outcome, reviewed.verification) == ("not_verified", "misread")
    assert reviewed.critic_reason == "the page shows the same quantity"
    shipment = session.get(Shipment, shipment_id)
    # The missing documents (DOC-01) still hold the shipment: they have nothing to misread.
    assert shipment is not None and shipment.readiness == "needs_fix"
    assert shipment.readiness_score is not None and 0 <= shipment.readiness_score < 100


class ScriptedDrafter:
    model = "scripted"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked: list[dict[str, list[Problem]]] = []

    def draft(self, shipment: str, sender: str, requests: dict[str, list[Problem]]) -> list[Draft]:
        self.asked.append(requests)
        if self.error is not None:
            raise self.error
        return [Draft(r, f"{shipment}: please correct", f"From {sender}") for r in requests]


def run_events(session: Session) -> list[str]:
    return list(session.scalars(select(RunEvent.type).order_by(RunEvent.id)))


def checked_shipment(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> uuid.UUID:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    worker.extract(engine_of, MismatchedQuantities(), shipment_id)
    worker.check(engine_of, storage, AgreeingJudge(), FlatEmbedder(), NoMisreads(), shipment_id)
    return shipment_id


def test_a_run_records_each_step_and_waits_for_review(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = checked_shipment(session, engine_of, storage, monkeypatch)
    drafter = ScriptedDrafter()
    worker.draft(engine_of, drafter, shipment_id)

    session.expire_all()
    (run,) = session.scalars(select(Run))
    assert (run.trigger, run.status, run.stage) == ("upload", "awaiting_review", None)
    assert run_events(session) == [
        "run_started",
        "document_read",
        "stage_started",  # extracting
        "fields_extracted",
        "stage_started",  # checking
        "checks_done",
        "stage_started",  # drafting
        "messages_drafted",
        "awaiting_review",
    ]
    shipment = session.get_one(Shipment, shipment_id)
    assert (shipment.status, shipment.error) == ("AWAITING_REVIEW", None)
    # The packing list disagrees with the invoice, and documents are missing: one message to
    # the exporter's team, who issue both, listing both problems.
    messages = session.scalars(select(Message)).all()
    assert [(m.recipient, m.status) for m in messages] == [("exporter", "draft")]
    assert set(messages[0].rule_ids) >= {"QTY-01", "DOC-01"}
    assert messages[0].subject == "JOB-1: please correct"
    worker.draft(engine_of, drafter, shipment_id)  # again: the drafts are replaced
    assert session.scalar(select(func.count()).select_from(Message)) == 1


def test_nothing_failed_asks_the_drafter_nothing(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = checked_shipment(session, engine_of, storage, monkeypatch)
    for row in session.scalars(select(CheckResult)):
        row.outcome = "pass"
    session.commit()
    drafter = ScriptedDrafter()
    worker.draft(engine_of, drafter, shipment_id)
    assert drafter.asked == []
    session.expire_all()
    assert session.get_one(Shipment, shipment_id).status == "AWAITING_REVIEW"


def test_a_failed_drafting_ends_the_run(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = checked_shipment(session, engine_of, storage, monkeypatch)
    with pytest.raises(ValueError, match="unexpected AI answer"):
        worker.draft(engine_of, ScriptedDrafter(ValueError("unexpected AI answer")), shipment_id)
    session.expire_all()
    (run,) = session.scalars(select(Run))
    assert (run.status, run.error) == (
        "failed",
        "drafting failed: ValueError: unexpected AI answer",
    )
    assert run_events(session)[-1] == "run_failed"


def test_a_rate_limited_drafter_tells_the_watchers(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = checked_shipment(session, engine_of, storage, monkeypatch)
    with pytest.raises(RateLimited):
        worker.draft(engine_of, ScriptedDrafter(RateLimited(30)), shipment_id)
    session.expire_all()
    waiting = session.scalars(select(RunEvent).order_by(RunEvent.id.desc())).first()
    assert waiting is not None
    assert (waiting.type, waiting.data) == ("waiting", {"stage": "drafting", "retry_after_s": 30})
    assert session.get_one(Run, waiting.run_id).status == "running"


def test_an_unreadable_file_fails_its_run(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLASSIFY_WITH_AI", "never")
    document_id = stored_document(session, storage, b"%PDF-1.7 broken", "application/pdf")
    with pytest.raises(Exception, match=r"(?i)pdf"):
        worker.process(engine_of, storage, None, document_id)
    session.expire_all()
    (run,) = session.scalars(select(Run))
    assert run.status == "failed" and run.error is not None
    assert run.error.startswith("file could not be read:")


def test_worker_refuses_to_start_with_two_keys_and_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    with pytest.raises(SystemExit, match="set AI_PROVIDER"):
        worker._check_settings()


def test_only_documents_without_fields_are_extracted_again(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    extractor = FakeExtractor()  # finds fields on the first document (the invoice) only
    worker.extract(engine_of, extractor, shipment_id)
    first = [d.doc_type for d in extractor.calls[0]]
    assert first[0] == "commercial_invoice"
    kept = {f.id for f in session.scalars(select(ExtractedField))}

    worker.extract(engine_of, extractor, shipment_id)
    # The invoice has its fields: only the documents still without any are asked about again.
    assert [d.doc_type for d in extractor.calls[1]] == first[1:]
    session.expire_all()
    assert {f.id for f in session.scalars(select(ExtractedField))} == kept


def test_nothing_new_to_read_asks_the_ai_nothing(
    session: Session, engine_of: Engine, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = processed_shipment(session, engine_of, storage, monkeypatch)
    # Only the invoice is left, so once its fields are read nothing is without fields.
    session.execute(delete(DocumentPart).where(DocumentPart.doc_type != "commercial_invoice"))
    session.commit()
    extractor = FakeExtractor()
    worker.extract(engine_of, extractor, shipment_id)
    worker.extract(engine_of, extractor, shipment_id)
    assert len(extractor.calls) == 1
    session.expire_all()
    shipment = session.get_one(Shipment, shipment_id)
    assert shipment.status == "EXTRACTED"
    run = session.scalars(select(Run).where(Run.shipment_id == shipment_id)).one()
    extracted = session.scalars(
        select(RunEvent.data).where(RunEvent.run_id == run.id, RunEvent.type == "fields_extracted")
    ).all()
    assert [e["documents"] for e in extracted] == [1, 0]
