"""Load fetched official reference data into the database.

    uv run python -m shipready.reference.fetch all     # download into ../data/reference
    uv run python -m shipready.db.load all             # validate and load (after the seed)

Each source replaces its tables in one transaction: it is validated in full first, so a bad file
changes nothing and the previous data stays.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from shipready.db.models import (
    RefCountry,
    RefCurrency,
    RefExchangeRate,
    RefExportPolicy,
    RefItcHs,
    RefLocation,
    RefPort,
)
from shipready.db.rows import replace
from shipready.db.session import make_engine
from shipready.reference.currencies import parse_currencies
from shipready.reference.exchange_rates import parse_exchange_rates
from shipready.reference.export_policy import load_overrides, parse_export_policy
from shipready.reference.fetch import FILES
from shipready.reference.itc_hs import parse_itc_hs
from shipready.reference.ports import parse_ports
from shipready.reference.unlocode import parse_unlocode


@dataclass
class LoadReport:
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def load_itc_hs(session: Session, directory: Path, report: LoadReport) -> None:
    """ITC(HS) codes and export policy load together: policy rows refer to the codes."""
    codes = parse_itc_hs(FILES["itc-hs"], _read(directory, "itc-hs"))
    eight_digit = {row["code"] for row in codes if row["level"] == 8}
    policy = parse_export_policy(
        FILES["export-policy"], _read(directory, "export-policy"), eight_digit, load_overrides()
    )
    session.execute(delete(RefExportPolicy))
    replace(session, RefItcHs, codes)
    replace(session, RefExportPolicy, policy.rows)
    report.counts.update({"ref_itc_hs": len(codes), "ref_export_policy": len(policy.rows)})
    for name, count in sorted(policy.dropped.items()):
        report.notes.append(f"dropped {count} {name} entries for codes no longer in ITC(HS)")


def load_ports(session: Session, directory: Path, report: LoadReport) -> None:
    ports = parse_ports(FILES["ports"], _read(directory, "ports"))
    replace(session, RefPort, ports.rows)
    report.counts["ref_ports"] = len(ports.rows)
    if ports.skipped:
        report.notes.append(f"skipped administrative entries: {', '.join(sorted(ports.skipped))}")


def load_currencies(session: Session, directory: Path, report: LoadReport) -> None:
    currencies = parse_currencies(FILES["currencies"], _read(directory, "currencies"))
    replace(session, RefCurrency, currencies)
    report.counts["ref_currencies"] = len(currencies)


def load_exchange_rates(session: Session, directory: Path, report: LoadReport) -> None:
    currencies = set(session.scalars(select(RefCurrency.code)))
    if not currencies:
        raise RuntimeError("ref_currencies is empty; load currencies first")
    rates = parse_exchange_rates(
        FILES["exchange-rates"], _read(directory, "exchange-rates"), currencies
    )
    replace(session, RefExchangeRate, rates)
    report.counts["ref_exchange_rates"] = len(rates)


def load_unlocode(session: Session, directory: Path, report: LoadReport) -> None:
    countries = set(session.scalars(select(RefCountry.code)))
    if not countries:
        raise RuntimeError("ref_countries is empty; run `python -m shipready.db.seed` first")
    path = directory / FILES["unlocode"]
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found; run `python -m shipready.reference.fetch unlocode`"
        )
    locations = parse_unlocode(path, countries)
    replace(session, RefLocation, locations.rows)
    report.counts["ref_locations"] = len(locations.rows)
    for country, count in sorted(locations.skipped_countries.items()):
        report.notes.append(f"skipped {count} UN/LOCODE entries for {country} (not ISO 3166)")


# In dependency order: exchange rates need currencies.
LOADERS: dict[str, Callable[[Session, Path, LoadReport], None]] = {
    "itc-hs": load_itc_hs,
    "ports": load_ports,
    "currencies": load_currencies,
    "exchange-rates": load_exchange_rates,
    "unlocode": load_unlocode,
}


def _read(directory: Path, source: str) -> bytes:
    path = directory / FILES[source]
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found; run `python -m shipready.reference.fetch {source}`"
        )
    return path.read_bytes()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load fetched reference data into the database.")
    parser.add_argument("source", choices=[*LOADERS, "all"])
    parser.add_argument("--dir", type=Path, default=Path("../data/reference"))
    args = parser.parse_args(argv)

    report = LoadReport()
    engine = make_engine()
    try:
        for source in LOADERS if args.source == "all" else [args.source]:
            with Session(engine) as session, session.begin():
                LOADERS[source](session, args.dir, report)
    finally:
        engine.dispose()
    for table, count in report.counts.items():
        print(f"{table}: {count} rows")
    for note in report.notes:
        print(note)


if __name__ == "__main__":
    main()
