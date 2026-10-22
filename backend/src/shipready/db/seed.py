"""Load the check catalogue and built-in reference lists into the database.

Every row is upserted by its key, so running the seed again changes nothing unless the source
files changed. Rows added by other loaders (e.g. UN/LOCODE ports in Phase 3) are left alone.

Run after `alembic upgrade head`:  uv run python -m shipready.db.seed
"""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db.models import Base, RefCountry, RefPort, RefUqc, Rule
from shipready.db.session import make_engine
from shipready.reference.files import read_csv
from shipready.rules.catalogue import load_catalogue


def seed(session: Session) -> dict[str, int]:
    """Upsert all seed data in dependency order; return the row count loaded per table."""
    loads: list[tuple[type[DeclarativeBase], Sequence[dict[str, Any]]]] = [
        (Rule, [asdict(rule) for rule in load_catalogue()]),
        (RefUqc, read_csv("uqc.csv")),
        (RefCountry, read_csv("countries.csv")),
        (RefPort, read_csv("ports.csv")),
    ]
    for model, rows in loads:
        _upsert(session, model, rows)
    return {model.__tablename__: len(rows) for model, rows in loads}


def _upsert(session: Session, model: type[DeclarativeBase], rows: Sequence[dict[str, Any]]) -> None:
    table = Base.metadata.tables[model.__tablename__]
    if not rows:
        raise ValueError(f"no seed rows for {table.name}; is its source file empty?")
    statement = insert(table)
    key_columns = [column.name for column in table.primary_key.columns]
    session.execute(
        statement.on_conflict_do_update(
            index_elements=key_columns,
            set_={name: statement.excluded[name] for name in rows[0] if name not in key_columns},
        ),
        rows,
    )


def main() -> None:
    with Session(make_engine()) as session, session.begin():
        counts = seed(session)
    for table, count in counts.items():
        print(f"{table}: {count} rows")


if __name__ == "__main__":
    main()
