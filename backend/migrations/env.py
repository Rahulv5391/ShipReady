import logging

from alembic import context
from sqlalchemy import Connection

from shipready.db.models import Base
from shipready.db.session import make_engine

config = context.config

# Only the command line gets console logging; tests run migrations quietly.
if config.cmd_opts is not None:
    logging.basicConfig(format="%(levelname)-5.5s [%(name)s] %(message)s")
    logging.getLogger("alembic").setLevel(logging.INFO)


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline (--sql) migrations are not supported; run against a database")

# Tests pass an open connection in; otherwise connect using DATABASE_URL.
connection = config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    with make_engine().connect() as new_connection:
        run_migrations(new_connection)
