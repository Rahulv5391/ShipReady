"""Write reference rows: upsert packaged seed data, or replace a table with a full download."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db.models import Base


def upsert(session: Session, model: type[DeclarativeBase], rows: Sequence[dict[str, Any]]) -> None:
    """Insert rows, updating any whose primary key already exists. Never deletes rows."""
    table = _table(model, rows)
    statement = insert(table)
    key_columns = [column.name for column in table.primary_key.columns]
    session.execute(
        statement.on_conflict_do_update(
            index_elements=key_columns,
            set_={name: statement.excluded[name] for name in rows[0] if name not in key_columns},
        ),
        rows,
    )


def replace(session: Session, model: type[DeclarativeBase], rows: Sequence[dict[str, Any]]) -> None:
    """Make the table hold exactly `rows`: for complete official lists, where a code that is no
    longer published must disappear too. The caller's transaction makes it all-or-nothing."""
    table = _table(model, rows)
    session.execute(delete(table))
    session.execute(insert(table), rows)


def _table(model: type[DeclarativeBase], rows: Sequence[dict[str, Any]]) -> Table:
    table = Base.metadata.tables[model.__tablename__]
    if not rows:
        raise ValueError(f"no rows for {table.name}; is its source file empty?")
    return table
