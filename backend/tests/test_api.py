import io
import json
import threading
import time
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import httpx
import jwt
import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from moto import mock_aws
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shipready import passwords, users
from shipready.api import auth, documents, login, review, shipments, uploads
from shipready.api.app import create_app
from shipready.api.deps import (
    get_drive_client,
    get_enqueue,
    get_recheck,
    get_session,
    get_storage,
)
from shipready.db.models import (
    CheckResult,
    Document,
    DocumentPage,
    DocumentPart,
    ExtractedField,
    Message,
    Organization,
    Run,
    RunEvent,
    Shipment,
    User,
)
from shipready.db.seed import DEMO_ORG, DEMO_ORG_ID
from shipready.runs import await_review, current_run, finish, record
from shipready.storage import Storage, settings_from_env

SECRET = "test-secret-that-is-long-enough-for-hs256"
BUCKET = "shipready-test"
OTHER_ORG_ID = uuid.UUID("0ac00000-0000-4000-8000-000000000002")
PDF = b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def workbook() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # A fixed date: by default a zip entry carries the current time, so two calls a moment
        # apart could give different bytes.
        entry = zipfile.ZipInfo("xl/workbook.xml", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(entry, "<workbook/>")
    return buffer.getvalue()


def word_document() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entry = zipfile.ZipInfo("word/document.xml", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(entry, "<w:document/>")
    return buffer.getvalue()


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield Storage(client, BUCKET)


@pytest.fixture
def queued() -> list[uuid.UUID]:
    """Documents the API handed to the worker queue (a list instead of Redis)."""
    return []


@pytest.fixture
def rechecked() -> list[uuid.UUID]:
    """Shipments the API queued to be checked again."""
    return []


@pytest.fixture
def client(
    session: Session,
    storage: Storage,
    queued: list[uuid.UUID],
    rechecked: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv(auth.SECRET_VARIABLE, SECRET)
    session.add_all(
        [
            Organization(**DEMO_ORG),
            Organization(id=OTHER_ORG_ID, name="Other Exports", type="exporter"),
        ]
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_enqueue] = lambda: queued.append
    app.dependency_overrides[get_recheck] = lambda: rechecked.append
    yield TestClient(app)


def headers(org: uuid.UUID = DEMO_ORG_ID, **overrides: Any) -> dict[str, str]:
    lifetime = overrides.pop("lifetime", timedelta(hours=1))
    key = overrides.pop("key", SECRET)
    return {"Authorization": f"Bearer {auth.issue('tester', org, lifetime, key)}"}


def new_shipment(client: TestClient, reference: str = "JOB-001", **body: Any) -> str:
    response = client.post(
        "/api/v1/shipments", json={"reference": reference, **body}, headers=headers()
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def upload(client: TestClient, shipment_id: str, *files: tuple[str, bytes]) -> Any:
    return client.post(
        f"/api/v1/shipments/{shipment_id}/documents",
        files=[("files", (name, data)) for name, data in files],
        headers=headers(),
    )


def stored_keys(storage: Storage) -> list[str]:
    listing = storage.client.list_objects_v2(Bucket=BUCKET)
    return [item["Key"] for item in listing.get("Contents", [])]


# --- auth ---


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "auth_header",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        headers(lifetime=timedelta(seconds=-1)),
        headers(key="another-secret-that-is-long-enough-too"),
        {
            "Authorization": "Bearer "
            + jwt.encode({"sub": "x", "org": str(DEMO_ORG_ID), "exp": 9999999999}, SECRET)
        },  # no audience
    ],
)
def test_requests_without_a_valid_token_are_refused(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    response = client.get("/api/v1/shipments", headers=auth_header)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_short_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.SECRET_VARIABLE, "short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        auth.secret()


# --- shipments ---


def test_create_and_read_a_shipment(client: TestClient) -> None:
    shipment_id = new_shipment(client, "  JOB-001  ", mode="sea")
    body = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert (body["reference"], body["mode"], body["status"]) == ("JOB-001", "sea", "RECEIVED")
    assert (body["readiness"], body["readiness_score"]) == (None, None)  # not checked yet
    assert body["documents"] == []


@pytest.mark.parametrize(
    "body",
    [{"reference": ""}, {"reference": "x" * 65}, {"reference": "A", "mode": "ship"}, {"x": 1}],
)
def test_invalid_shipment_is_refused(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/api/v1/shipments", json=body, headers=headers()).status_code == 422


def test_duplicate_reference_is_refused_within_an_organisation(client: TestClient) -> None:
    new_shipment(client, "JOB-001")
    response = client.post("/api/v1/shipments", json={"reference": "JOB-001"}, headers=headers())
    assert response.status_code == 409
    # Another organisation may use the same reference.
    other = client.post(
        "/api/v1/shipments", json={"reference": "JOB-001"}, headers=headers(OTHER_ORG_ID)
    )
    assert other.status_code == 201


def test_list_shows_only_the_callers_shipments(client: TestClient) -> None:
    for reference in ("JOB-001", "JOB-002", "EXP-100"):
        new_shipment(client, reference)
    client.post("/api/v1/shipments", json={"reference": "THEIRS"}, headers=headers(OTHER_ORG_ID))

    listed = client.get("/api/v1/shipments", headers=headers()).json()
    assert sorted(s["reference"] for s in listed) == ["EXP-100", "JOB-001", "JOB-002"]
    found = client.get("/api/v1/shipments?q=job", headers=headers()).json()
    assert sorted(s["reference"] for s in found) == ["JOB-001", "JOB-002"]
    page = client.get("/api/v1/shipments?limit=2&offset=2", headers=headers()).json()
    assert len(page) == 1
    assert client.get("/api/v1/shipments?limit=0", headers=headers()).status_code == 422


def test_the_list_summarises_each_shipment(client: TestClient, session: Session) -> None:
    read = new_shipment(client, "JOB-READ")
    upload(client, read, ("invoice.pdf", PDF))
    extracted(session, read)
    part = session.scalars(select(DocumentPart)).one()
    session.add_all(
        ExtractedField(
            shipment_id=uuid.UUID(read),
            part_id=part.id,
            path=path,
            value=value,
            quote=value,
            page_no=1,
            box=None,
            model="test-model",
        )
        for path, value in [
            ("commercial_invoice.exporter.name", "Kulkarni Textiles Pvt Ltd"),
            ("shipping_bill.exporter_name", "KULKARNI TEXTILES"),  # the invoice comes first
            ("bill_of_lading.consignee.name", "Van Dijk Retail BV"),
            ("commercial_invoice.destination_country", "NL"),
            ("commercial_invoice.port_of_loading.code", "INNSA1"),
            ("bill_of_lading.port_of_discharge.code", "NLRTM"),
        ]
    )
    session.commit()
    untouched = new_shipment(client, "JOB-NEW")

    listed = {s["reference"]: s for s in client.get("/api/v1/shipments", headers=headers()).json()}
    summary = listed["JOB-READ"]
    assert {key: summary[key] for key in shipments.SUMMARY_FIELDS} == {
        "exporter": "Kulkarni Textiles Pvt Ltd",
        "consignee": "Van Dijk Retail BV",
        "destination_country": "NL",
        "port_of_loading": "INNSA1",
        "port_of_discharge": "NLRTM",
    }
    assert summary["files"] == 1
    assert summary["run"] == {"status": "running", "stage": "reading", "error": None}
    assert summary["updated_at"] >= summary["created_at"]
    empty = listed["JOB-NEW"]
    assert [empty[key] for key in shipments.SUMMARY_FIELDS] == [None] * 5
    assert (empty["files"], empty["run"]) == (0, None)
    assert empty["updated_at"] == empty["created_at"]
    del untouched


def test_another_organisations_shipment_is_not_found(client: TestClient) -> None:
    shipment_id = new_shipment(client)
    response = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers(OTHER_ORG_ID))
    assert response.status_code == 404
    assert client.get(f"/api/v1/shipments/{uuid.uuid4()}", headers=headers()).status_code == 404


# --- documents ---


def test_upload_stores_files_and_lists_them(
    client: TestClient, storage: Storage, session: Session
) -> None:
    shipment_id = new_shipment(client)
    response = upload(
        client,
        shipment_id,
        ("C:\\exports\\invoice.pdf", PDF),
        ("packing list.xlsx", workbook()),
        ("bl.png", PNG),
        ("purchase order.docx", word_document()),
    )
    assert response.status_code == 201, response.text
    assert response.json()["duplicates"] == []
    uploaded = response.json()["documents"]
    assert [d["filename"] for d in uploaded] == [
        "invoice.pdf",
        "packing list.xlsx",
        "bl.png",
        "purchase order.docx",
    ]
    assert [d["media_type"] for d in uploaded] == [
        "application/pdf",
        uploads.XLSX,
        "image/png",
        uploads.DOCX,
    ]

    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert {d["id"] for d in detail["documents"]} == {d["id"] for d in uploaded}
    for document in session.scalars(select(Document)):
        assert storage.get(document.storage_key) in (PDF, PNG, workbook(), word_document())
        assert document.storage_key.startswith(f"orgs/{DEMO_ORG_ID}/shipments/{shipment_id}/")
    one = client.get(f"/api/v1/documents/{uploaded[0]['id']}", headers=headers()).json()
    assert one == uploaded[0]


def test_stored_files_are_queued_for_the_worker(
    client: TestClient, queued: list[uuid.UUID]
) -> None:
    shipment_id = new_shipment(client)
    uploaded = upload(client, shipment_id, ("invoice.pdf", PDF), ("bl.png", PNG)).json()[
        "documents"
    ]
    assert queued == [uuid.UUID(d["id"]) for d in uploaded]
    assert [(d["status"], d["parts"], d["page_count"]) for d in uploaded] == [
        ("uploaded", [], None),
        ("uploaded", [], None),
    ]


def test_upload_succeeds_when_the_queue_is_down(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_queue(document_id: uuid.UUID) -> None:
        raise OperationalError("Error 10061 connecting to localhost:6379")

    client.app.dependency_overrides[get_enqueue] = lambda: broken_queue  # type: ignore[attr-defined]
    response = upload(client, new_shipment(client), ("invoice.pdf", PDF))
    assert response.status_code == 201
    assert response.json()["documents"][0]["status"] == "uploaded"
    assert "python -m shipready.worker requeue" in caplog.text


def test_type_comes_from_the_bytes_not_the_name(
    client: TestClient, storage: Storage, session: Session
) -> None:
    shipment_id = new_shipment(client)
    response = upload(client, shipment_id, ("invoice.pdf", PDF), ("notes.pdf", b"just text"))
    assert response.status_code == 415
    assert "notes.pdf" in response.json()["detail"]
    # Nothing of the rejected upload is kept, not even the valid file.
    assert stored_keys(storage) == []
    assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_an_empty_file_is_refused(client: TestClient) -> None:
    assert upload(client, new_shipment(client), ("empty.pdf", b"")).status_code == 422


def test_the_same_file_twice_in_one_upload_is_stored_once(
    client: TestClient, storage: Storage, queued: list[uuid.UUID]
) -> None:
    response = upload(client, new_shipment(client), ("a.pdf", PDF), ("bl.png", PNG), ("b.pdf", PDF))
    assert response.status_code == 201
    body = response.json()
    assert [d["filename"] for d in body["documents"]] == ["a.pdf", "bl.png"]
    assert body["duplicates"] == [{"filename": "b.pdf", "same_as": "a.pdf"}]
    assert len(stored_keys(storage)) == 2
    assert len(queued) == 2


def test_size_and_count_limits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    shipment_id = new_shipment(client)
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 10)
    assert upload(client, shipment_id, ("big.pdf", PDF)).status_code == 413
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 1_000_000)
    monkeypatch.setattr(documents, "MAX_FILES_PER_UPLOAD", 1)
    response = upload(client, shipment_id, ("a.pdf", PDF), ("b.png", PNG))
    assert response.status_code == 413


def test_a_file_already_in_the_shipment_is_reported_not_stored(
    client: TestClient, storage: Storage, session: Session, queued: list[uuid.UUID]
) -> None:
    shipment_id = new_shipment(client)
    assert upload(client, shipment_id, ("invoice.pdf", PDF)).status_code == 201
    events = session.scalar(select(func.count()).select_from(RunEvent))
    response = upload(client, shipment_id, ("invoice-copy.pdf", PDF))
    # Nothing new: 200, nothing stored or queued, the run left as it was.
    assert response.status_code == 200
    assert response.json() == {
        "documents": [],
        "duplicates": [{"filename": "invoice-copy.pdf", "same_as": "invoice.pdf"}],
    }
    assert len(stored_keys(storage)) == 1
    assert len(queued) == 1
    assert session.scalar(select(func.count()).select_from(RunEvent)) == events
    # The same file may belong to another shipment.
    assert upload(client, new_shipment(client, "JOB-002"), ("invoice.pdf", PDF)).status_code == 201


def failing_put(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """Storage that accepts the first file and is unreachable for the second."""
    real_put, calls = storage.put, []

    def put(key: str, data: bytes, media_type: str) -> None:
        calls.append(key)
        if len(calls) == 2:
            raise EndpointConnectionError(endpoint_url="http://storage:8333")
        real_put(key, data, media_type)

    monkeypatch.setattr(storage, "put", put)


def test_storage_outage_answers_503_and_leaves_nothing_behind(
    client: TestClient, storage: Storage, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment_id = new_shipment(client)
    failing_put(storage, monkeypatch)
    response = upload(client, shipment_id, ("a.pdf", PDF), ("b.png", PNG))
    assert response.status_code == 503
    assert response.json()["detail"] == "file storage is unavailable; try again"
    assert stored_keys(storage) == []
    assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_failed_clean_up_is_logged_not_hidden(
    client: TestClient,
    storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    shipment_id = new_shipment(client)
    failing_put(storage, monkeypatch)

    def delete(key: str) -> None:
        raise EndpointConnectionError(endpoint_url="http://storage:8333")

    monkeypatch.setattr(storage, "delete", delete)
    response = upload(client, shipment_id, ("a.pdf", PDF), ("b.png", PNG))
    assert response.status_code == 503  # the upload's own error, not the clean-up's
    (orphan,) = stored_keys(storage)
    assert f"could not remove {orphan}" in caplog.text


def test_documents_of_another_organisation_are_hidden(client: TestClient) -> None:
    shipment_id = new_shipment(client)
    (document,) = upload(client, shipment_id, ("invoice.pdf", PDF)).json()["documents"]
    other = headers(OTHER_ORG_ID)
    assert client.get(f"/api/v1/documents/{document['id']}", headers=other).status_code == 404
    response = client.post(
        f"/api/v1/shipments/{shipment_id}/documents",
        files=[("files", ("x.pdf", PDF))],
        headers=other,
    )
    assert response.status_code == 404


def test_deleting_a_shipment_deletes_its_document_rows(
    client: TestClient, session: Session
) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    session.delete(session.get(Shipment, uuid.UUID(shipment_id)))
    session.commit()
    assert session.scalar(select(func.count()).select_from(Document)) == 0


# --- helpers ---


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PDF, "application/pdf"),
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (PNG, "image/png"),
        (b"II*\x00rest", "image/tiff"),
        (workbook(), uploads.XLSX),
        (word_document(), uploads.DOCX),
        (b"PK\x03\x04not a zip", None),  # a zip header that is not a workbook
        (b"<html>", None),
    ],
)
def test_media_type(data: bytes, expected: str | None) -> None:
    assert uploads.media_type(data) == expected


def test_a_zip_that_is_neither_workbook_nor_document_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/presentation.xml", "<p/>")
    assert uploads.media_type(buffer.getvalue()) is None


def test_names_and_keys_cannot_escape() -> None:
    assert uploads.display_name("../../etc/passwd") == "passwd"
    assert uploads.display_name(None) == "unnamed"
    ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    key = uploads.storage_key(*ids, "../..\\..\\.hidden invoice?.pdf")
    assert key.endswith("/hidden_invoice_.pdf")
    assert ".." not in key


def test_storage_settings_must_be_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL, S3_BUCKET"):
        settings_from_env()


def test_app_refuses_to_start_without_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(auth.SECRET_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match="SHIPREADY_JWT_SECRET"), TestClient(create_app()):
        pass


def test_app_refuses_to_start_with_two_keys_and_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(auth.SECRET_VARIABLE, SECRET)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="set AI_PROVIDER"), TestClient(create_app()):
        pass


# --- extracted fields ---


def extracted(session: Session, shipment_id: str) -> uuid.UUID:
    """The shipment's one uploaded file read as an invoice with one field, as the worker does."""
    document = session.scalars(select(Document)).one()
    part = DocumentPart(
        document_id=document.id,
        first_page=1,
        last_page=1,
        doc_type="commercial_invoice",
        decided_by="title",
    )
    session.add(part)
    session.flush()
    session.add_all(
        [
            ExtractedField(
                shipment_id=uuid.UUID(shipment_id),
                part_id=part.id,
                path="commercial_invoice.invoice_number",
                value="EXP/1",
                quote="EXP/1",
                page_no=1,
                box={"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.25},
                model="test-model",
            ),
            ExtractedField(
                shipment_id=uuid.UUID(shipment_id),
                part_id=part.id,
                path="commercial_invoice.iec",
                value="0123456789",
                quote="0123 456 789",
                page_no=1,
                box=None,
                model="test-model",
            ),
        ]
    )
    session.get_one(Shipment, uuid.UUID(shipment_id)).status = "EXTRACTED"
    session.commit()
    return document.id


def test_fields_are_listed_with_their_evidence(client: TestClient, session: Session) -> None:
    shipment_id = new_shipment(client)
    assert client.get(f"/api/v1/shipments/{shipment_id}/fields", headers=headers()).json() == []
    upload(client, shipment_id, ("invoice.pdf", PDF))
    document_id = extracted(session, shipment_id)

    fields = client.get(f"/api/v1/shipments/{shipment_id}/fields", headers=headers()).json()
    assert [f["path"] for f in fields] == [
        "commercial_invoice.iec",
        "commercial_invoice.invoice_number",
    ]
    assert fields[1] == {
        "path": "commercial_invoice.invoice_number",
        "value": "EXP/1",
        "quote": "EXP/1",
        "document_id": str(document_id),
        "page_no": 1,
        "box": {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.25},
        "model": "test-model",
    }
    assert fields[0]["box"] is None
    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert (detail["status"], detail["error"]) == ("EXTRACTED", None)


def test_another_organisations_fields_are_not_found(client: TestClient) -> None:
    shipment_id = new_shipment(client)
    response = client.get(f"/api/v1/shipments/{shipment_id}/fields", headers=headers(OTHER_ORG_ID))
    assert response.status_code == 404


def test_new_files_make_an_extracted_shipment_wait_again(
    client: TestClient, session: Session
) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    extracted(session, shipment_id)
    assert upload(client, shipment_id, ("bl.png", PNG)).status_code == 201
    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert detail["status"] == "RECEIVED"


def test_checks_are_listed_failures_first_with_their_evidence(
    client: TestClient, session: Session
) -> None:
    shipment_id = new_shipment(client)
    assert client.get(f"/api/v1/shipments/{shipment_id}/checks", headers=headers()).json() == []
    upload(client, shipment_id, ("invoice.pdf", PDF))
    extracted(session, shipment_id)
    session.add_all(
        [
            CheckResult(
                shipment_id=uuid.UUID(shipment_id),
                rule_id="ID-01",
                outcome="pass",
                message="",
                evidence=["commercial_invoice.iec"],
            ),
            CheckResult(
                shipment_id=uuid.UUID(shipment_id),
                rule_id="INV-01",
                outcome="fail",
                message="invoice number EXP/1, shipping bill EXP/2",
                evidence=["commercial_invoice.invoice_number", "shipping_bill.invoice_number"],
                verification="kept",
                critic_reason="the shipping bill shows EXP/2",
            ),
            CheckResult(
                shipment_id=uuid.UUID(shipment_id),
                rule_id="DOC-01",
                outcome="fail",
                message="missing: shipping bill",
                evidence=[],
                citations=[{"source_id": "ftp-2023", "page": 26, "text": "Shipping Bill"}],
            ),
            CheckResult(
                shipment_id=uuid.UUID(shipment_id),
                rule_id="FX-01",
                outcome="not_verified",
                message="no customs export rate for USD on 2026-10-29 in our data",
                evidence=[],
            ),
        ]
    )
    session.commit()

    checks = client.get(f"/api/v1/shipments/{shipment_id}/checks", headers=headers()).json()
    assert [(c["rule_id"], c["outcome"]) for c in checks] == [
        ("DOC-01", "fail"),
        ("INV-01", "fail"),
        ("FX-01", "not_verified"),
        ("ID-01", "pass"),
    ]
    (citation,) = checks[0]["citations"]
    assert (citation["title"], citation["page"]) == ("Foreign Trade Policy 2023", 26)
    assert citation["url"].startswith("https://content.dgft.gov.in/")
    failed = checks[1]
    assert failed["citations"] == []
    assert (failed["verification"], failed["critic_reason"]) == (
        "kept",
        "the shipping bill shows EXP/2",
    )
    assert (checks[0]["verification"], checks[0]["critic_reason"]) == (None, "")
    assert (failed["title"], failed["severity"]) == (
        "Invoice number and date match the shipping bill",
        "blocker",
    )
    # Evidence is the fields themselves; a path with no stored field (the shipping bill's
    # number was not extracted here) has nothing to show.
    assert [f["path"] for f in failed["evidence"]] == ["commercial_invoice.invoice_number"]
    assert failed["evidence"][0]["box"] == {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.25}
    other = client.get(f"/api/v1/shipments/{shipment_id}/checks", headers=headers(OTHER_ORG_ID))
    assert other.status_code == 404


# --- runs and review ---


def under_review(session: Session, shipment_id: str) -> Run:
    """The shipment's run, its files read and checked, now awaiting review."""
    shipment = session.get_one(Shipment, uuid.UUID(shipment_id))
    run = current_run(session, shipment)
    await_review(session, run, shipment)
    session.commit()
    return run


def drafted(session: Session, shipment_id: str, run: Run, *recipients: str) -> list[str]:
    messages = [
        Message(
            shipment_id=uuid.UUID(shipment_id),
            run_id=run.id,
            recipient=recipient,
            subject=f"JOB-001: for the {recipient}",
            body="Please correct the document.",
            rule_ids=["WT-01"],
        )
        for recipient in recipients
    ]
    session.add_all(messages)
    session.commit()
    return [str(m.id) for m in messages]


def event_names(stream: str) -> list[str]:
    blocks = [block for block in stream.split("\n\n") if block]
    return [
        line.removeprefix("event: ")
        for b in blocks
        for line in b.split("\n")
        if line.startswith("event: ")
    ]


def test_an_upload_starts_a_run(client: TestClient) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    (run,) = client.get(f"/api/v1/shipments/{shipment_id}/runs", headers=headers()).json()
    assert (run["trigger"], run["status"], run["stage"]) == ("upload", "running", "reading")
    same = client.get(f"/api/v1/runs/{run['id']}", headers=headers()).json()
    assert same == run
    upload(client, shipment_id, ("bl.png", PNG))  # joins the run in progress
    assert len(client.get(f"/api/v1/shipments/{shipment_id}/runs", headers=headers()).json()) == 1
    other = client.get(f"/api/v1/runs/{run['id']}", headers=headers(OTHER_ORG_ID))
    assert other.status_code == 404


def test_a_recheck_waits_for_the_run_in_progress_and_read_files(
    client: TestClient, session: Session, rechecked: list[uuid.UUID]
) -> None:
    shipment_id = new_shipment(client)
    recheck = f"/api/v1/shipments/{shipment_id}/runs"
    not_read = client.post(recheck, headers=headers())
    assert (not_read.status_code, not_read.json()["detail"]) == (
        409,
        "the shipment's files are not all read",
    )
    upload(client, shipment_id, ("invoice.pdf", PDF))
    busy = client.post(recheck, headers=headers())
    assert (busy.status_code, busy.json()["detail"]) == (
        409,
        "a run of this shipment is in progress",
    )
    run = session.scalars(select(Run)).one()
    finish(session, run)
    for document in session.scalars(select(Document)):
        document.status = "processed"
    session.commit()

    response = client.post(recheck, headers=headers())
    assert response.status_code == 201, response.text
    assert (response.json()["trigger"], response.json()["stage"]) == ("recheck", "extracting")
    assert rechecked == [uuid.UUID(shipment_id)]


def test_run_events_stream_and_resume(client: TestClient, session: Session) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    run = session.scalars(select(Run)).one()
    finish(session, run, "extracting failed: ValueError")
    session.commit()
    path = f"/api/v1/runs/{run.id}/events"

    response = client.get(path, headers=headers())
    assert response.headers["content-type"].startswith("text/event-stream")
    assert event_names(response.text) == [
        "run_started",
        "files_uploaded",
        "stage_started",
        "run_failed",
    ]
    blocks = [block.split("\n") for block in response.text.split("\n\n") if block]
    assert json.loads(blocks[-1][2].removeprefix("data: "))["error"] == (
        "extracting failed: ValueError"
    )
    second = blocks[1][0].removeprefix("id: ")

    resumed = client.get(path, headers={**headers(), "Last-Event-ID": second}).text
    assert event_names(resumed) == ["stage_started", "run_failed"]
    assert client.get(path, headers=headers(OTHER_ORG_ID)).status_code == 404


def test_drafted_messages_are_edited_approved_or_discarded(
    client: TestClient, session: Session
) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    run = under_review(session, shipment_id)
    forwarder, buyer = drafted(session, shipment_id, run, "forwarder", "buyer")

    listed = client.get(f"/api/v1/shipments/{shipment_id}/messages", headers=headers()).json()
    assert {m["recipient"] for m in listed} == {"forwarder", "buyer"}
    edited = client.patch(
        f"/api/v1/messages/{forwarder}",
        json={"body": "  Please send a corrected copy.  "},
        headers=headers(),
    ).json()
    assert (edited["body"], edited["subject"]) == (
        "Please send a corrected copy.",
        "JOB-001: for the forwarder",
    )
    blank = client.patch(f"/api/v1/messages/{forwarder}", json={"body": ""}, headers=headers())
    assert blank.status_code == 422
    approved = client.post(f"/api/v1/messages/{forwarder}/approve", headers=headers()).json()
    assert approved["status"] == "approved"
    again = client.post(f"/api/v1/messages/{forwarder}/discard", headers=headers())
    assert (again.status_code, again.json()["detail"]) == (409, "the message is already approved")
    discarded = client.post(f"/api/v1/messages/{buyer}/discard", headers=headers()).json()
    assert discarded["status"] == "discarded"
    foreign = client.post(f"/api/v1/messages/{buyer}/approve", headers=headers(OTHER_ORG_ID))
    assert foreign.status_code == 404

    decisions = client.get(f"/api/v1/shipments/{shipment_id}/approvals", headers=headers()).json()
    assert [(d["action"], d["target_id"], d["decided_by"]) for d in decisions] == [
        ("approve_message", forwarder, "tester"),
        ("discard_message", buyer, "tester"),
    ]


def test_marking_ready_with_a_failed_blocker_needs_a_reason(
    client: TestClient, session: Session
) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    ready = f"/api/v1/shipments/{shipment_id}/mark-ready"
    early = client.post(ready, json={}, headers=headers())
    assert (early.status_code, early.json()["detail"]) == (
        409,
        "the shipment is not awaiting review",
    )
    run = under_review(session, shipment_id)
    session.add(
        CheckResult(
            shipment_id=uuid.UUID(shipment_id),
            rule_id="QTY-01",
            outcome="fail",
            message="line 1 differs",
            evidence=[],
        )
    )
    session.commit()

    refused = client.post(ready, json={}, headers=headers())
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "blocker checks fail (QTY-01); give a reason to mark it ready anyway",
    )
    decided = client.post(
        ready, json={"reason": "buyer accepted the short shipment"}, headers=headers()
    ).json()
    assert (decided["action"], decided["reason"], decided["run_id"]) == (
        "mark_ready",
        "buyer accepted the short shipment",
        str(run.id),
    )
    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert detail["status"] == "READY"
    (finished,) = client.get(f"/api/v1/shipments/{shipment_id}/runs", headers=headers()).json()
    assert finished["status"] == "done" and finished["finished_at"] is not None
    assert client.post(ready, json={}, headers=headers()).status_code == 409  # decided already


def test_a_shipment_sent_back_for_fixes(client: TestClient, session: Session) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    under_review(session, shipment_id)
    decided = client.post(
        f"/api/v1/shipments/{shipment_id}/mark-needs-fix", json={}, headers=headers()
    ).json()
    assert (decided["action"], decided["reason"]) == ("mark_needs_fix", None)
    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert detail["status"] == "NEEDS_FIX"
    # Corrected files start a new run.
    upload(client, shipment_id, ("bl.png", PNG))
    runs = client.get(f"/api/v1/shipments/{shipment_id}/runs", headers=headers()).json()
    assert [r["status"] for r in runs] == ["running", "done"]


def test_events_arrive_on_an_open_stream(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review, "POLL_S", 0.05)
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    run_id = session.scalars(select(Run.id)).one()
    engine = session.get_bind()

    def worker_steps() -> None:
        time.sleep(0.5)  # the stream is open and quiet by now
        with Session(engine) as other:
            run = other.get_one(Run, run_id)
            record(other, run, "document_read", file="invoice.pdf")
            finish(other, run, "extracting failed: ValueError")
            other.commit()

    thread = threading.Thread(target=worker_steps)
    thread.start()
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=headers()) as response:
        streamed = response.read().decode()
    thread.join()
    assert event_names(streamed) == [
        "run_started",
        "files_uploaded",
        "stage_started",
        "document_read",
        "run_failed",
    ]


LOGIN_PASSWORD = "correct horse battery staple"


@pytest.fixture
def account(client: TestClient, session: Session) -> User:
    """A user of the demo organisation (the client fixture creates the organisations)."""
    return users.add_user(
        session, DEMO_ORG_ID, " Rahul@DemoExports.in ", "Rahul Verma", LOGIN_PASSWORD
    )


def sign_in(client: TestClient, email: str, password: str, **extra: object) -> Any:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})


# --- users and sign-in ---


def test_users_are_stored_lowercase_with_a_hash(account: User, session: Session) -> None:
    stored = session.scalars(select(User)).one()
    assert (stored.email, stored.name, stored.org_id) == (
        "rahul@demoexports.in",
        "Rahul Verma",
        DEMO_ORG_ID,
    )
    assert passwords.check_password(LOGIN_PASSWORD, stored.password_hash)


@pytest.mark.parametrize(
    ("email", "name", "org", "password", "message"),
    [
        ("RAHUL@demoexports.in", "Rahul", DEMO_ORG_ID, LOGIN_PASSWORD, "already has an account"),
        ("not-an-email", "Rahul", DEMO_ORG_ID, LOGIN_PASSWORD, "is not an email address"),
        ("a@b", "Rahul", DEMO_ORG_ID, LOGIN_PASSWORD, "is not an email address"),
        ("new@demoexports.in", " ", DEMO_ORG_ID, LOGIN_PASSWORD, "needs a name"),
        ("new@demoexports.in", "New", DEMO_ORG_ID, "abc", "at least 4"),
    ],
)
def test_bad_users_are_refused(
    account: User,
    session: Session,
    email: str,
    name: str,
    org: uuid.UUID,
    password: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        users.add_user(session, org, email, name, password)


def test_a_user_needs_a_known_organisation(client: TestClient, session: Session) -> None:
    with pytest.raises(ValueError, match="no organisation"):
        users.add_user(session, uuid.uuid4(), "x@y.in", "X", LOGIN_PASSWORD)


def test_the_command_reads_the_password_from_stdin(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(users, "make_engine", lambda: session.get_bind())
    monkeypatch.setattr("sys.stdin", io.StringIO(LOGIN_PASSWORD + "\n"))
    users.main(["add", "--email", "ops@demoexports.in", "--name", "Ops", "--password-stdin"])
    assert "added ops@demoexports.in" in capsys.readouterr().out
    stored = users.find_user(session, "OPS@demoexports.in")
    assert stored is not None and passwords.check_password(LOGIN_PASSWORD, stored.password_hash)


# --- sign-in ---


def test_sign_in_gives_a_token_the_api_accepts(client: TestClient, account: User) -> None:
    response = sign_in(client, "RAHUL@demoexports.in", LOGIN_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {
        "email": "rahul@demoexports.in",
        "name": "Rahul Verma",
        "org_id": str(DEMO_ORG_ID),
    }
    assert body["token_type"] == "bearer"
    principal = auth.verify(body["access_token"], SECRET)
    assert principal == auth.Principal(user="rahul@demoexports.in", org_id=DEMO_ORG_ID)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/v1/shipments", headers=headers).status_code == 200


@pytest.mark.parametrize(
    ("remember", "lifetime"),
    [(False, login.SESSION_LIFETIME), (True, login.REMEMBERED_LIFETIME)],
)
def test_keep_me_signed_in_sets_how_long_the_token_lasts(
    client: TestClient, account: User, remember: bool, lifetime: timedelta
) -> None:
    body = sign_in(client, account.email, LOGIN_PASSWORD, remember=remember).json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert abs(expires - (datetime.now(UTC) + lifetime)) < timedelta(minutes=1)


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("rahul@demoexports.in", "wrong password entirely"),
        ("nobody@demoexports.in", LOGIN_PASSWORD),
    ],
)
def test_wrong_credentials_all_get_the_same_answer(
    client: TestClient, account: User, email: str, password: str
) -> None:
    response = sign_in(client, email, password)
    assert response.status_code == 401
    assert response.json() == {"detail": login.WRONG_CREDENTIALS}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "rahul@demoexports.in"},
        {"email": "rahul@demoexports.in", "password": ""},
        {"email": "rahul@demoexports.in", "password": "x" * 1025},
        {"email": "rahul@demoexports.in", "password": LOGIN_PASSWORD, "admin": True},
    ],
)
def test_malformed_sign_ins_are_refused(
    client: TestClient, account: User, body: dict[str, object]
) -> None:
    assert client.post("/api/v1/auth/login", json=body).status_code == 422


def test_approvals_record_the_signed_in_person(
    client: TestClient, session: Session, account: User
) -> None:
    token = sign_in(client, account.email, LOGIN_PASSWORD).json()["access_token"]
    signed_in = {"Authorization": f"Bearer {token}"}
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    run = under_review(session, shipment_id)
    (message,) = drafted(session, shipment_id, run, "forwarder")
    assert client.post(f"/api/v1/messages/{message}/approve", headers=signed_in).status_code == 200
    decisions = client.get(f"/api/v1/shipments/{shipment_id}/approvals", headers=signed_in).json()
    assert [d["decided_by"] for d in decisions] == ["rahul@demoexports.in"]


# --- Google Drive import ---

DRIVE_TOKEN = "ya29.picker-token-never-logged"


def drive_returning(files: dict[str, tuple[str, str, bytes]]) -> httpx.Client:
    """A Google Drive holding `files`: ID -> (name, Drive type, bytes); a Google Doc's bytes are
    what its PDF export gives."""

    def answer(request: httpx.Request) -> httpx.Response:
        file_id, *export = request.url.path.removeprefix("/drive/v3/files/").split("/")
        if file_id not in files:
            return httpx.Response(404)
        name, kind, data = files[file_id]
        if export or request.url.params.get("alt") == "media":
            return httpx.Response(200, content=data)
        info = {"name": name, "mimeType": kind, "size": str(len(data))}
        return httpx.Response(200, json={**info, "capabilities": {"canDownload": True}})

    return httpx.Client(transport=httpx.MockTransport(answer))


def import_drive(
    client: TestClient, shipment_id: str, *ids: str, org: uuid.UUID = DEMO_ORG_ID
) -> Any:
    return client.post(
        f"/api/v1/shipments/{shipment_id}/documents:import-drive",
        json={"access_token": DRIVE_TOKEN, "files": [{"id": i} for i in ids]},
        headers=headers(org),
    )


@pytest.fixture
def drive_files(client: TestClient) -> dict[str, tuple[str, str, bytes]]:
    """What the fake Drive holds; tests add to it."""
    files: dict[str, tuple[str, str, bytes]] = {}
    client.app.dependency_overrides[get_drive_client] = lambda: drive_returning(files)  # type: ignore[attr-defined]
    return files


def test_drive_files_are_stored_like_uploads(
    client: TestClient,
    storage: Storage,
    queued: list[uuid.UUID],
    drive_files: dict[str, tuple[str, str, bytes]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    drive_files["invoice-id-0001"] = ("invoice.pdf", "application/pdf", PDF)
    drive_files["po-doc-id-0001"] = (
        "Purchase order",
        "application/vnd.google-apps.document",
        PDF + b"po",
    )
    shipment_id = new_shipment(client)
    response = import_drive(client, shipment_id, "invoice-id-0001", "po-doc-id-0001")
    assert response.status_code == 201, response.text
    documents = response.json()["documents"]
    assert [(d["filename"], d["media_type"]) for d in documents] == [
        ("invoice.pdf", "application/pdf"),
        ("Purchase order.pdf", "application/pdf"),
    ]
    assert len(stored_keys(storage)) == 2
    assert queued == [uuid.UUID(d["id"]) for d in documents]
    assert DRIVE_TOKEN not in caplog.text


def test_a_drive_file_already_uploaded_is_a_duplicate(
    client: TestClient, drive_files: dict[str, tuple[str, str, bytes]]
) -> None:
    shipment_id = new_shipment(client)
    upload(client, shipment_id, ("invoice.pdf", PDF))
    drive_files["invoice-id-0001"] = ("Invoice from Drive.pdf", "application/pdf", PDF)
    response = import_drive(client, shipment_id, "invoice-id-0001")
    assert response.status_code == 200
    assert response.json()["duplicates"] == [
        {"filename": "Invoice from Drive.pdf", "same_as": "invoice.pdf"}
    ]


def test_one_drive_file_that_fails_stores_none(
    client: TestClient, storage: Storage, drive_files: dict[str, tuple[str, str, bytes]]
) -> None:
    drive_files["invoice-id-0001"] = ("invoice.pdf", "application/pdf", PDF)
    drive_files["notes-id-00001"] = ("notes.pdf", "application/pdf", b"just text")
    shipment_id = new_shipment(client)
    missing = import_drive(client, shipment_id, "invoice-id-0001", "gone-file-0001")
    assert (missing.status_code, missing.json()["detail"]) == (
        422,
        "a picked file could not be opened in Google Drive",
    )
    wrong_type = import_drive(client, shipment_id, "invoice-id-0001", "notes-id-00001")
    assert wrong_type.status_code == 415
    assert stored_keys(storage) == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"access_token": "t", "files": []}, 422),
        ({"access_token": "t", "files": [{"id": "../../etc/passwd"}]}, 422),
        ({"access_token": "", "files": [{"id": "invoice-id-0001"}]}, 422),
        ({"access_token": "t", "files": [{"id": f"file-id-{n:05d}"} for n in range(31)]}, 413),
    ],
)
def test_bad_drive_imports_are_refused(
    client: TestClient,
    drive_files: dict[str, tuple[str, str, bytes]],
    body: dict[str, object],
    status: int,
) -> None:
    path = f"/api/v1/shipments/{new_shipment(client)}/documents:import-drive"
    assert client.post(path, json=body, headers=headers()).status_code == status


def test_drive_imports_stay_in_the_organisation(
    client: TestClient, drive_files: dict[str, tuple[str, str, bytes]]
) -> None:
    drive_files["invoice-id-0001"] = ("invoice.pdf", "application/pdf", PDF)
    response = import_drive(client, new_shipment(client), "invoice-id-0001", org=OTHER_ORG_ID)
    assert response.status_code == 404


# --- pages and their images ---


def read_pages(session: Session, storage: Storage, document_id: str) -> None:
    """The document read as the worker does: page 1 with an image, page 2 a sheet without."""
    document = session.get_one(Document, uuid.UUID(document_id))
    key = f"{document.storage_key.rsplit('/', 1)[0]}/pages/1.png"
    storage.put(key, PNG, "image/png")
    session.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_no=2,
                image_key=None,
                width_px=None,
                height_px=None,
                text_source="cells",
                text="Sheet",
                words=[],
            ),
            DocumentPage(
                document_id=document.id,
                page_no=1,
                image_key=key,
                width_px=1275,
                height_px=1651,
                text_source="pdf_text",
                text="Invoice",
                words=[],
            ),
        ]
    )
    session.commit()


def test_pages_are_listed_and_their_images_served(
    client: TestClient, session: Session, storage: Storage
) -> None:
    shipment_id = new_shipment(client)
    (document,) = upload(client, shipment_id, ("invoice.pdf", PDF)).json()["documents"]
    base = f"/api/v1/documents/{document['id']}/pages"
    assert client.get(base, headers=headers()).json() == []  # not read yet
    read_pages(session, storage, document["id"])

    pages = client.get(base, headers=headers()).json()
    assert pages == [
        {
            "page_no": 1,
            "width_px": 1275,
            "height_px": 1651,
            "text_source": "pdf_text",
            "has_image": True,
        },
        {
            "page_no": 2,
            "width_px": None,
            "height_px": None,
            "text_source": "cells",
            "has_image": False,
        },
    ]
    image = client.get(f"{base}/1/image", headers=headers())
    assert (image.status_code, image.content) == (200, PNG)
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "private, max-age=3600"
    assert client.get(f"{base}/2/image", headers=headers()).status_code == 404  # a sheet
    assert client.get(f"{base}/3/image", headers=headers()).status_code == 404
    assert client.get(f"{base}/1/image", headers=headers(OTHER_ORG_ID)).status_code == 404
    assert client.get(base, headers=headers(OTHER_ORG_ID)).status_code == 404


def test_a_page_image_storage_cannot_give_is_a_503(
    client: TestClient, session: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    (document,) = upload(client, new_shipment(client), ("invoice.pdf", PDF)).json()["documents"]
    read_pages(session, storage, document["id"])

    def unreachable(key: str) -> bytes:
        raise EndpointConnectionError(endpoint_url="http://storage:8333")

    monkeypatch.setattr(storage, "get", unreachable)
    response = client.get(f"/api/v1/documents/{document['id']}/pages/1/image", headers=headers())
    assert (response.status_code, response.json()["detail"]) == (
        503,
        "file storage is unavailable; try again",
    )
