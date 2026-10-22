import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Start Postgres with `docker compose up -d` and run "
            "`uv run --env-file .env pytest` (see backend/.env.example)."
        )
    return url


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


def migrate(connection: Connection, revision: str) -> None:
    """Run the real Alembic migrations on an open connection, upgrading or downgrading."""
    config = Config(toml_file=PYPROJECT, attributes={"connection": connection})
    if revision == "base":
        command.downgrade(config, "base")
    else:
        command.upgrade(config, revision)


@pytest.fixture
def run_migration() -> Callable[[Connection, str], None]:
    return migrate


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session on a freshly migrated, empty schema."""
    with engine.begin() as connection:
        migrate(connection, "base")
        migrate(connection, "head")
    with Session(engine) as session:
        yield session
