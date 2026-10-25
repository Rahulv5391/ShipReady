"""Load the packaged, hand-maintained data: the check catalogue, UQC codes and countries.

Every row is upserted by its key, so running the seed again changes nothing unless the source
files changed. Official downloads (ITC(HS), ports, currencies, rates, UN/LOCODE) are loaded by
`shipready.db.load` instead.

Run after `alembic upgrade head`:  uv run python -m shipready.db.seed
"""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db.models import RefCountry, RefUqc, Rule
from shipready.db.rows import upsert
from shipready.db.session import make_engine
from shipready.reference.files import read_csv
from shipready.rules.catalogue import load_catalogue


def seed(session: Session) -> dict[str, int]:
    """Upsert all seed data in dependency order; return the row count loaded per table."""
    loads: list[tuple[type[DeclarativeBase], Sequence[dict[str, Any]]]] = [
        (Rule, [asdict(rule) for rule in load_catalogue()]),
        (RefUqc, read_csv("uqc.csv")),
        (RefCountry, read_csv("countries.csv")),
    ]
    for model, rows in loads:
        upsert(session, model, rows)
    return {model.__tablename__: len(rows) for model, rows in loads}


def main() -> None:
    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            counts = seed(session)
    finally:
        engine.dispose()
    for table, count in counts.items():
        print(f"{table}: {count} rows")


if __name__ == "__main__":
    main()
