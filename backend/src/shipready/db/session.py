"""Database connection settings."""

import os

from sqlalchemy import Engine, create_engine

CONNECT_TIMEOUT_SECONDS = 10


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set; see backend/.env.example "
            "(e.g. postgresql+psycopg://user:password@localhost:5432/shipready)"
        )
    return url


def make_engine() -> Engine:
    # Without a timeout, an unreachable database hangs the caller instead of failing.
    return create_engine(database_url(), connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS})
