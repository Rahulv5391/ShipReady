"""Documents: upload a shipment's files or import them from Google Drive, and read their
metadata."""

import hashlib
import logging
import uuid
from collections.abc import Callable
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from kombu.exceptions import OperationalError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.api import drive
from shipready.api.deps import (
    CheckDep,
    DriveClientDep,
    EnqueueDep,
    PrincipalDep,
    SessionDep,
    StorageDep,
)
from shipready.api.schemas import DocumentOut, DriveImportIn, DuplicateOut, PageOut, UploadOut
from shipready.api.shipments import shipment_of
from shipready.api.uploads import (
    MAX_FILE_BYTES,
    MAX_FILES_PER_UPLOAD,
    display_name,
    media_type,
    storage_key,
)
from shipready.db.models import Document, DocumentPage, Shipment
from shipready.runs import active_run, current_run, enter_stage, record
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
    enqueue: EnqueueDep,
    response: Response,
) -> UploadOut:
    """Store every file, or none: a bad file rejects the whole upload. Stored files are then
    queued for the worker, which reads their pages and splits them into documents.

    A file whose bytes are already in the shipment, or earlier in the same upload, is stored
    once and listed in `duplicates`, for the web app's soft notice (Decision.md D-34). When
    every file was a duplicate nothing changes, and the answer is 200 instead of 201."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    _check_count(len(files))
    received = [
        (display_name(upload.filename), upload.file.read(MAX_FILE_BYTES + 1)) for upload in files
    ]
    return _store(received, principal.org_id, shipment, session, storage, enqueue, response)


@router.post("/shipments/{shipment_id}/documents:import-drive", status_code=status.HTTP_201_CREATED)
def import_from_drive(
    shipment_id: uuid.UUID,
    body: DriveImportIn,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    enqueue: EnqueueDep,
    drive_client: DriveClientDep,
    response: Response,
) -> UploadOut:
    """Fetch the files picked in Google Drive with the browser's short-lived token, then store
    them exactly as an upload: the same checks, all or none, duplicates stored once. The token
    is used for this request only (Decision.md D-37)."""
    shipment = shipment_of(session, principal.org_id, shipment_id)
    _check_count(len(body.files))
    try:
        received = [drive.fetch(drive_client, body.access_token, f.id) for f in body.files]
    except drive.DriveError as error:
        raise HTTPException(error.status, str(error)) from None
    return _store(received, principal.org_id, shipment, session, storage, enqueue, response)


@router.post("/documents/{document_id}:replace", status_code=status.HTTP_201_CREATED)
def replace_document(
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="the corrected document")],
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    enqueue: EnqueueDep,
    response: Response,
) -> UploadOut:
    """Put a corrected file in place of a document: the old one, its pages and fields go, and
    only the new one is read and extracted before the checks run again. The same bytes as a
    file already in the shipment (the old one included) are reported as a duplicate and nothing
    changes. Refused while the shipment is being read or checked."""
    document = document_of(session, principal.org_id, document_id)
    shipment = session.get_one(Shipment, document.shipment_id)
    _check_idle(session, shipment)
    received = [(display_name(file.filename), file.file.read(MAX_FILE_BYTES + 1))]
    return _store(
        received, principal.org_id, shipment, session, storage, enqueue, response, document
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    check: CheckDep,
) -> None:
    """Take a document out of its shipment, with its pages and fields, and check the rest
    again. A shipment keeps at least one file (replace it instead), and nothing is removed while
    the shipment is being read or checked."""
    document = document_of(session, principal.org_id, document_id)
    shipment = session.get_one(Shipment, document.shipment_id)
    _check_idle(session, shipment)
    files = session.scalar(
        select(func.count()).select_from(Document).where(Document.shipment_id == shipment.id)
    )
    if files == 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a shipment keeps at least one file; replace it instead"
        )
    keys = _keys_of(session, document)
    filename = document.filename
    session.execute(delete(Document).where(Document.id == document.id))
    run = current_run(session, shipment)
    record(session, run, "document_removed", file=filename)
    enter_stage(session, run, "checking")
    session.commit()
    _remove(storage, keys, "a removed document")
    try:
        check(shipment.id)
    except OperationalError as error:
        logger.error("could not queue the checks of shipment %s (%s)", shipment.id, error)


def _check_idle(session: Session, shipment: Shipment) -> None:
    """Files change only between runs or while one awaits review, so results never mix them."""
    run = active_run(session, shipment.id)
    if run is not None and run.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the shipment is being read and checked; try again when it is waiting for review",
        )


def _keys_of(session: Session, document: Document) -> list[str]:
    """The stored file and its page images."""
    images = session.scalars(
        select(DocumentPage.image_key).where(
            DocumentPage.document_id == document.id, DocumentPage.image_key.is_not(None)
        )
    )
    return [document.storage_key, *(key for key in images if key)]


def _check_count(count: int) -> None:
    if count > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"at most {MAX_FILES_PER_UPLOAD} files per upload"
        )


def _store(
    received: list[tuple[str, bytes]],
    org_id: uuid.UUID,
    shipment: Shipment,
    session: Session,
    storage: Storage,
    enqueue: Callable[[uuid.UUID], None],
    response: Response,
    replacing: Document | None = None,
) -> UploadOut:
    """Check, store and queue received files, however they arrived (`upload_documents`), in
    place of `replacing` when given (`replace_document`)."""
    stored_as = {
        digest: filename
        for digest, filename in session.execute(
            select(Document.sha256, Document.filename).where(Document.shipment_id == shipment.id)
        )
    }
    documents: list[tuple[Document, bytes]] = []
    duplicates: list[DuplicateOut] = []
    for name, data in received:
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
                f"{name} is not a PDF, Word document, Excel workbook, JPEG, PNG or TIFF",
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest in stored_as:
            duplicates.append(DuplicateOut(filename=name, same_as=stored_as[digest]))
            continue
        stored_as[digest] = name
        document_id = uuid.uuid4()
        document = Document(
            id=document_id,
            org_id=org_id,
            shipment_id=shipment.id,
            filename=name,
            media_type=kind,
            size_bytes=len(data),
            sha256=digest,
            storage_key=storage_key(org_id, shipment.id, document_id, name),
        )
        documents.append((document, data))
    if not documents:
        response.status_code = status.HTTP_200_OK
        return UploadOut(documents=[], duplicates=duplicates)

    stored: list[str] = []
    replaced = _keys_of(session, replacing) if replacing else []
    try:
        for document, data in documents:
            storage.put(document.storage_key, data, document.media_type)
            stored.append(document.storage_key)
        if replacing:
            run = current_run(session, shipment)
            record(session, run, "document_removed", file=replacing.filename)
            session.execute(delete(Document).where(Document.id == replacing.id))
        session.add_all(document for document, _ in documents)
        # New files make earlier fields incomplete; extraction runs again once they are read.
        shipment.status = "RECEIVED"
        run = current_run(session, shipment)
        record(session, run, "files_uploaded", files=[d.filename for d, _ in documents])
        enter_stage(session, run, "reading")
        session.commit()
    except Exception as error:
        session.rollback()
        _remove(storage, stored, "a failed upload")
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
    _remove(storage, replaced, "a replaced document")
    for document, _ in documents:
        try:
            enqueue(document.id)
        except OperationalError as error:
            # The file is safely stored; it waits as "uploaded" until the queue is back.
            logger.error(
                "could not queue document %s (%s); run `python -m shipready.worker requeue`",
                document.id,
                error,
            )
    return UploadOut(
        documents=[DocumentOut.model_validate(document) for document, _ in documents],
        duplicates=duplicates,
    )


def _remove(storage: Storage, keys: list[str], why: str) -> None:
    """Delete stored files the database no longer lists (`why`: after a failed upload, or of a
    replaced or removed document). Storage may be failing, so a file that cannot be deleted is
    logged for clean-up instead of hiding the original error or undoing the change."""
    for key in keys:
        try:
            storage.delete(key)
        except (BotoCoreError, ClientError) as error:
            logger.error("could not remove %s after %s: %s", key, why, error)


@router.get("/documents/{document_id}")
def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentOut:
    return DocumentOut.model_validate(document_of(session, principal.org_id, document_id))


@router.get("/documents/{document_id}/pages")
def list_pages(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[PageOut]:
    """The file's pages as read, in order; empty until the worker has read it."""
    document = document_of(session, principal.org_id, document_id)
    pages = session.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_no)
    )
    return [
        PageOut(
            page_no=page.page_no,
            width_px=page.width_px,
            height_px=page.height_px,
            text_source=page.text_source,
            has_image=page.image_key is not None,
        )
        for page in pages
    ]


@router.get(
    "/documents/{document_id}/pages/{page_no}/image",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def page_image(
    document_id: uuid.UUID,
    page_no: int,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> Response:
    """The page as rendered when it was read (PNG), on which evidence boxes are drawn. Kept by
    the browser for an hour only, and for this person only: a page is read again when its file
    is replaced, and pages are private to the organisation."""
    document = document_of(session, principal.org_id, document_id)
    page = session.get(DocumentPage, (document.id, page_no))
    if page is None or page.image_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "page image not found")
    try:
        png = storage.get(page.image_key)
    except (BotoCoreError, ClientError) as error:
        logger.error("could not read page image %s: %s", page.image_key, error)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "file storage is unavailable; try again"
        ) from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


def document_of(session: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """The document if it belongs to `org_id`; another organisation's is not found."""
    document = session.get(Document, document_id)
    if document is None or document.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return document
