import json

import httpx
import pytest

from shipready.api import drive
from shipready.api.uploads import MAX_FILE_BYTES, XLSX

TOKEN = "ya29.short-lived-picker-token"
PDF = b"%PDF-1.7 from drive"


def fake_drive(
    files: dict[str, dict[str, object]],
    content: dict[str, bytes],
    seen: list[httpx.Request] | None = None,
) -> httpx.Client:
    """Google Drive answering from `files` (metadata by ID) and `content` (bytes by ID, or by
    "ID:mimeType" for an export)."""

    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        parts = request.url.path.removeprefix("/drive/v3/files/").split("/")
        file_id = parts[0]
        if file_id not in files:
            return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
        if len(parts) == 2:  # /export
            key = f"{file_id}:{request.url.params['mimeType']}"
            if key not in content:
                reason = {"error": {"errors": [{"reason": "exportSizeLimitExceeded"}]}}
                return httpx.Response(403, json=reason)
            return httpx.Response(200, content=content[key])
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=content[file_id])
        return httpx.Response(200, json=files[file_id])

    return httpx.Client(transport=httpx.MockTransport(answer))


def meta(name: str, kind: str, size: int = 100, download: bool = True) -> dict[str, object]:
    return {
        "name": name,
        "mimeType": kind,
        "size": str(size),
        "capabilities": {"canDownload": download},
    }


def test_a_file_is_downloaded_with_the_token() -> None:
    seen: list[httpx.Request] = []
    client = fake_drive(
        {"pdf-file-id-1": meta("invoice.pdf", "application/pdf")}, {"pdf-file-id-1": PDF}, seen
    )
    assert drive.fetch(client, TOKEN, "pdf-file-id-1") == ("invoice.pdf", PDF)
    metadata, download = seen
    assert metadata.url.params["fields"] == "name,mimeType,size,capabilities/canDownload"
    assert download.url.params["alt"] == "media"
    assert download.url.params["supportsAllDrives"] == "true"


@pytest.mark.parametrize(
    ("name", "kind", "export", "expected"),
    [
        (
            "Purchase order",
            "application/vnd.google-apps.document",
            "application/pdf",
            "Purchase order.pdf",
        ),
        ("Packing list.xlsx", "application/vnd.google-apps.spreadsheet", XLSX, "Packing list.xlsx"),
    ],
)
def test_google_docs_and_sheets_are_exported(
    name: str, kind: str, export: str, expected: str
) -> None:
    client = fake_drive(
        {"google-file-1": meta(name, kind)}, {f"google-file-1:{export}": b"exported"}
    )
    assert drive.fetch(client, TOKEN, "google-file-1") == (expected, b"exported")


GOOGLE = "application/vnd.google-apps."


@pytest.mark.parametrize(
    ("files", "status", "message"),
    [
        ({}, 422, "a picked file could not be opened in Google Drive"),
        (
            {"file-id-0001": meta("Deck", f"{GOOGLE}presentation")},
            415,
            "Deck is a Google presentation",
        ),
        (
            {"file-id-0001": meta("bl.pdf", "application/pdf", download=False)},
            422,
            "bl.pdf cannot be",
        ),
        (
            {"file-id-0001": meta("scan.pdf", "application/pdf", size=MAX_FILE_BYTES + 1)},
            413,
            "scan.pdf is larger than 25 MB",
        ),
        ({"file-id-0001": meta("Lines", f"{GOOGLE}spreadsheet")}, 413, "the 10 MB Google allows"),
    ],
)
def test_files_that_cannot_be_fetched_say_why(
    files: dict[str, dict[str, object]], status: int, message: str
) -> None:
    with pytest.raises(drive.DriveError) as raised:
        drive.fetch(fake_drive(files, {}), TOKEN, "file-id-0001")
    assert raised.value.status == status
    assert message in str(raised.value)


def test_a_download_larger_than_its_stated_size_is_cut_off() -> None:
    client = fake_drive(
        {"liar-file-01": meta("small.pdf", "application/pdf", size=10)},
        {"liar-file-01": b"%PDF" + b"x" * MAX_FILE_BYTES},
    )
    with pytest.raises(drive.DriveError, match="larger than 25 MB") as raised:
        drive.fetch(client, TOKEN, "liar-file-01")
    assert raised.value.status == 413


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {}, 400),  # Google's permission, not ShipReady's sign-in
        (429, {}, 503),
        (500, {}, 503),
        (418, {}, 502),
    ],
)
def test_googles_refusals_become_answers_the_app_can_show(
    status: int, body: dict[str, object], expected: int
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, content=json.dumps(body))
        )
    )
    with pytest.raises(drive.DriveError) as raised:
        drive.fetch(client, TOKEN, "any-file-id-1")
    assert raised.value.status == expected


def test_an_unreachable_drive_is_a_503() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(drive.DriveError, match="could not be reached") as raised:
        drive.fetch(httpx.Client(transport=httpx.MockTransport(fail)), TOKEN, "any-file-id-1")
    assert raised.value.status == 503
