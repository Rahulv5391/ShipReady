"""Checks on uploaded files: size, type and a storage key that cannot escape its folder.

The type comes from the file's first bytes, never from its name or the client's Content-Type, so
a renamed file cannot pass as a PDF.
"""

import io
import re
import uuid
import zipfile

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 30
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Leading bytes of each accepted type (PLAN.md Section 5.1: PDFs, scans and photos, Excel;
# Word added by Decision.md D-34).
_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def media_type(data: bytes) -> str | None:
    """The file's type from its content, or None if it is not one ShipReady accepts."""
    for signature, kind in _SIGNATURES:
        if data.startswith(signature):
            return kind
    if data.startswith(b"PK\x03\x04"):
        return _office_type(data)
    return None


def _office_type(data: bytes) -> str | None:
    """Excel and Word files are both ZIP archives; the part inside tells them apart."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    if "xl/workbook.xml" in names:
        return XLSX
    if "word/document.xml" in names:
        return DOCX
    return None


def display_name(filename: str | None) -> str:
    """The file name as the user gave it, without any folder part a client may send."""
    name = re.split(r"[\\/]", filename or "")[-1].strip()
    return name or "unnamed"


def storage_key(
    org_id: uuid.UUID, shipment_id: uuid.UUID, document_id: uuid.UUID, name: str
) -> str:
    # Only safe characters, so a crafted name cannot add folders or hidden files.
    safe = _UNSAFE.sub("_", name).strip("._") or "file"
    return f"orgs/{org_id}/shipments/{shipment_id}/documents/{document_id}/{safe[:120]}"
