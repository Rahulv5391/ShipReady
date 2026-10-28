import io
import uuid
import zipfile
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import boto3
import jwt
import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shipready.api import auth, documents, token, uploads
from shipready.api.app import create_app
from shipready.api.deps import get_session, get_storage
from shipready.db.models import Document, Organization, Shipment
from shipready.db.seed import DEMO_ORG, DEMO_ORG_ID
from shipready.storage import Storage, settings_from_env

SECRET = "test-secret-that-is-long-enough-for-hs256"
BUCKET = "shipready-test"
OTHER_ORG_ID = uuid.UUID("0ac00000-0000-4000-8000-000000000002")
PDF = b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def workbook() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield Storage(client, BUCKET)


@pytest.fixture
def client(
    session: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
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


def test_token_command_issues_a_valid_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(auth.SECRET_VARIABLE, SECRET)
    token.main(["--user", "rahul", "--hours", "2"])
    principal = auth.verify(capsys.readouterr().out.strip(), SECRET)
    assert principal == auth.Principal(user="rahul", org_id=DEMO_ORG_ID)
    with pytest.raises(SystemExit):
        token.main(["--hours", "0"])


# --- shipments ---


def test_create_and_read_a_shipment(client: TestClient) -> None:
    shipment_id = new_shipment(client, "  JOB-001  ", mode="sea")
    body = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert (body["reference"], body["mode"], body["status"]) == ("JOB-001", "sea", "RECEIVED")
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
    )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    assert [d["filename"] for d in uploaded] == ["invoice.pdf", "packing list.xlsx", "bl.png"]
    assert [d["media_type"] for d in uploaded] == [
        "application/pdf",
        uploads.XLSX,
        "image/png",
    ]

    detail = client.get(f"/api/v1/shipments/{shipment_id}", headers=headers()).json()
    assert {d["id"] for d in detail["documents"]} == {d["id"] for d in uploaded}
    for document in session.scalars(select(Document)):
        assert storage.get(document.storage_key) in (PDF, PNG, workbook())
        assert document.storage_key.startswith(f"orgs/{DEMO_ORG_ID}/shipments/{shipment_id}/")
    one = client.get(f"/api/v1/documents/{uploaded[0]['id']}", headers=headers()).json()
    assert one == uploaded[0]


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


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ([("empty.pdf", b"")], 422),
        ([("a.pdf", PDF), ("b.pdf", PDF)], 409),  # the same file twice
    ],
)
def test_bad_uploads_are_refused(
    client: TestClient, files: list[tuple[str, bytes]], status: int
) -> None:
    assert upload(client, new_shipment(client), *files).status_code == status


def test_size_and_count_limits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    shipment_id = new_shipment(client)
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 10)
    assert upload(client, shipment_id, ("big.pdf", PDF)).status_code == 413
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 1_000_000)
    monkeypatch.setattr(documents, "MAX_FILES_PER_UPLOAD", 1)
    response = upload(client, shipment_id, ("a.pdf", PDF), ("b.png", PNG))
    assert response.status_code == 413


def test_a_file_already_in_the_shipment_is_refused(client: TestClient) -> None:
    shipment_id = new_shipment(client)
    assert upload(client, shipment_id, ("invoice.pdf", PDF)).status_code == 201
    response = upload(client, shipment_id, ("invoice-copy.pdf", PDF))
    assert response.status_code == 409
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
    (document,) = upload(client, shipment_id, ("invoice.pdf", PDF)).json()
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
        (b"PK\x03\x04not a zip", None),  # a zip header that is not a workbook
        (b"<html>", None),
    ],
)
def test_media_type(data: bytes, expected: str | None) -> None:
    assert uploads.media_type(data) == expected


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
