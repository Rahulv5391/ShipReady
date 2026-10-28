"""What a request handler receives: a database session, the storage client and the caller.

Created once at startup (app.lifespan) and replaced in tests through dependency overrides.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from shipready.api.auth import Principal, current_principal
from shipready.storage import Storage


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


SessionDep = Annotated[Session, Depends(get_session)]
StorageDep = Annotated[Storage, Depends(get_storage)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]
