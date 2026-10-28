"""The ShipReady API (PLAN.md Section 13), versioned under /api/v1.

    uv run --env-file .env uvicorn shipready.api.app:app --reload

The database engine and storage client are created once at startup from the environment.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from shipready.api import documents, shipments
from shipready.api.auth import secret
from shipready.db.session import make_engine
from shipready.storage import make_storage, settings_from_env


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    secret()  # refuse to start without a signing key, rather than fail every request
    engine = make_engine()
    app.state.engine = engine
    app.state.storage = make_storage(settings_from_env())
    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="ShipReady API", version="0.1.0", lifespan=lifespan)
    api = APIRouter(prefix="/api/v1")

    @api.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(shipments.router)
    api.include_router(documents.router)
    app.include_router(api)
    return app


app = create_app()
