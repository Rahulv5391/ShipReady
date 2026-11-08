"""What a request handler receives: a database session, the storage client, the work queue, a
client for Google Drive and the caller.

Created once at startup (app.lifespan) and replaced in tests through dependency overrides.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from shipready.api.auth import Principal, current_principal
from shipready.api.drive import TIMEOUT_S
from shipready.storage import Storage


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_enqueue() -> Callable[[uuid.UUID], None]:
    """Queue a document for the worker. Imported here so the API starts without the worker's
    heavier modules until a file is uploaded."""
    from shipready.worker import process_document

    return lambda document_id: process_document.delay(str(document_id))


def get_recheck() -> Callable[[uuid.UUID], None]:
    """Queue a shipment's extraction and checks again, its files already read."""
    from shipready.worker import extract_shipment

    return lambda shipment_id: extract_shipment.delay(str(shipment_id))


def get_drive_client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=TIMEOUT_S) as client:
        yield client


SessionDep = Annotated[Session, Depends(get_session)]
EnqueueDep = Annotated[Callable[[uuid.UUID], None], Depends(get_enqueue)]
RecheckDep = Annotated[Callable[[uuid.UUID], None], Depends(get_recheck)]
StorageDep = Annotated[Storage, Depends(get_storage)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]
DriveClientDep = Annotated[httpx.Client, Depends(get_drive_client)]
