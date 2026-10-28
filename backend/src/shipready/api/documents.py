"""Documents: upload a shipment's files and read their metadata."""

import hashlib
import logging
import uuid
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shipready.api.deps import PrincipalDep, SessionDep, StorageDep
from shipready.api.schemas import DocumentOut
from shipready.api.shipments import shipment_of
from shipready.api.uploads import (
    MAX_FILE_BYTES,
    MAX_FILES_PER_UPLOAD,
    display_name,
    media_type,
    storage_key,
)
from shipready.db.models import Document
from shipready.storage import Storage

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


@router.post("/shipments/{shipment_id}/documents", status_code=status.HTTP_201_CREATED)
def upload_documents(
    shipment_id: uuid.UUID,
    files: Annotated[list[UploadFile], File(description="the shipment's documents")],
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> list[DocumentOut]:
    """Store every file, or none: a bad file rejects the whole upload."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"at most {MAX_FILES_PER_UPLOAD} files per upload"
        )
    existing = set(
        session.scalars(select(Document.sha256).where(Document.shipment_id == shipment.id))
    )
    documents: list[tuple[Document, bytes]] = []
    for upload in files:
        name = display_name(upload.filename)
        data = upload.file.read(MAX_FILE_BYTES + 1)
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} is empty")
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB",
            )
        kind = media_type(data)
        if kind is None:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"{name} is not a PDF, JPEG, PNG, TIFF or Excel workbook",
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest in existing:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{name} is already in this shipment")
        existing.add(digest)
        document_id = uuid.uuid4()
        document = Document(
            id=document_id,
            org_id=principal.org_id,
            shipment_id=shipment.id,
            filename=name,
            media_type=kind,
            size_bytes=len(data),
            sha256=digest,
            storage_key=storage_key(principal.org_id, shipment.id, document_id, name),
        )
        documents.append((document, data))

    stored: list[str] = []
    try:
        for document, data in documents:
            storage.put(document.storage_key, data, document.media_type)
            stored.append(document.storage_key)
        session.add_all(document for document, _ in documents)
        session.commit()
    except Exception as error:
        session.rollback()
        _remove(storage, stored)
        if isinstance(error, IntegrityError):  # the same file uploaded at the same moment
            raise HTTPException(
                status.HTTP_409_CONFLICT, "a file is already in this shipment"
            ) from None
        if isinstance(error, BotoCoreError | ClientError):
            logger.error("upload to storage failed: %s", error)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "file storage is unavailable; try again"
            ) from None
        raise
    return [DocumentOut.model_validate(document) for document, _ in documents]


def _remove(storage: Storage, keys: list[str]) -> None:
    """Delete files stored before the upload failed, so storage holds nothing the database does
    not list. Storage may be the reason it failed, so a file that cannot be deleted is logged
    for clean-up instead of hiding the original error."""
    for key in keys:
        try:
            storage.delete(key)
        except (BotoCoreError, ClientError) as error:
            logger.error("could not remove %s after a failed upload: %s", key, error)


@router.get("/documents/{document_id}")
def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentOut:
    document = session.get(Document, document_id)
    if document is None or document.org_id != principal.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return DocumentOut.model_validate(document)
