"""Load UN/LOCODE locations from the UNECE release zip into `ref_locations`.

Download https://unlocode.unece.org/downloads/unlocode-latest.zip to data/reference/, then run
after the seed (locations reference `ref_countries`):

    uv run python -m shipready.db.load_unlocode ../data/reference/unlocode-latest.zip
"""

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from shipready.db.models import RefCountry, RefLocation
from shipready.db.session import make_engine
from shipready.db.upsert import upsert
from shipready.reference.unlocode import ParsedLocations, parse_unlocode


def load_unlocode(session: Session, zip_path: Path) -> ParsedLocations:
    countries = set(session.scalars(select(RefCountry.code)))
    if not countries:
        raise RuntimeError("ref_countries is empty; run `python -m shipready.db.seed` first")
    parsed = parse_unlocode(zip_path, countries)
    upsert(session, RefLocation, parsed.rows)
    return parsed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load UN/LOCODE locations into the database.")
    parser.add_argument("zip_path", type=Path, help="path to unlocode-latest.zip from UNECE")
    zip_path: Path = parser.parse_args(argv).zip_path
    if not zip_path.is_file():
        parser.error(f"file not found: {zip_path}")

    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            parsed = load_unlocode(session, zip_path)
    finally:
        engine.dispose()
    print(f"ref_locations: {len(parsed.rows)} rows")
    for country, count in sorted(parsed.skipped_countries.items()):
        print(f"skipped {count} entries for {country} (not an ISO 3166 country)")


if __name__ == "__main__":
    main()
