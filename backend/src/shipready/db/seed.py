"""Load the packaged, hand-maintained data: the check catalogue, UQC codes, countries and the
demo organisation.

Every row is upserted by its key, so running the seed again changes nothing unless the source
files changed. Official downloads (ITC(HS), ports, currencies, rates, UN/LOCODE) are loaded by
`shipready.db.load` instead.

Run after `alembic upgrade head`:  uv run python -m shipready.db.seed
"""

import uuid
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db.models import Organization, RefCountry, RefUqc, Rule
from shipready.db.rows import upsert
from shipready.db.session import make_engine
from shipready.reference.files import read_csv
from shipready.rules.catalogue import load_catalogue

# The showcase has one organisation; dev tokens are issued for it.
DEMO_ORG_ID = uuid.UUID("5a1e0000-0000-4000-8000-000000000001")
DEMO_ORG = {"id": DEMO_ORG_ID, "name": "ShipReady Demo Exports", "type": "exporter"}


def seed(session: Session) -> dict[str, int]:
    """Upsert all seed data in dependency order; return the row count loaded per table."""
    loads: list[tuple[type[DeclarativeBase], Sequence[dict[str, Any]]]] = [
        (Rule, [asdict(rule) for rule in load_catalogue()]),
        (RefUqc, read_csv("uqc.csv")),
        (RefCountry, read_csv("countries.csv")),
        (Organization, [DEMO_ORG]),
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
