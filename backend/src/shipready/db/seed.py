"""Load the check catalogue and built-in reference lists into the database.

Every row is upserted by its key, so running the seed again changes nothing unless the source
files changed. Rows added in other ways are left alone. UN/LOCODE locations have their own
loader (`shipready.db.load_unlocode`) because the file is downloaded, not packaged.

Run after `alembic upgrade head`:  uv run python -m shipready.db.seed
"""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db.models import RefCountry, RefExchangeRate, RefItcHs, RefPort, RefUqc, Rule
from shipready.db.session import make_engine
from shipready.db.upsert import upsert
from shipready.reference.exchange_rates import load_exchange_rates
from shipready.reference.files import read_csv
from shipready.reference.itc_hs import load_itc_hs
from shipready.rules.catalogue import load_catalogue


def seed(session: Session) -> dict[str, int]:
    """Upsert all seed data in dependency order; return the row count loaded per table."""
    loads: list[tuple[type[DeclarativeBase], Sequence[dict[str, Any]]]] = [
        (Rule, [asdict(rule) for rule in load_catalogue()]),
        (RefUqc, read_csv("uqc.csv")),
        (RefCountry, read_csv("countries.csv")),
        (RefPort, read_csv("ports.csv")),
        (RefItcHs, load_itc_hs()),
        (RefExchangeRate, load_exchange_rates()),
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
