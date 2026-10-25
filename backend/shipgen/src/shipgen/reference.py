"""ShipGen's frozen copy of the reference data its shipments are built from (shipgen/data).

The same seed must always give the same shipment, so ShipGen never reads the database or fetched
downloads, which change. These files are a snapshot checked against DGFT and ICEGATE on
2026-10-22/23: 21 ITC(HS) codes with their export policy and unit, 66 export rates from ICEGATE
notifications 27-29/2026, and 28 ports (12 Indian, 16 foreign by UN/LOCODE).
"""

import re
from datetime import date
from functools import cache
from typing import Any

from shipready.reference.export_policy import EXPORT_POLICIES
from shipready.reference.files import (
    ReferenceDataError,
    numbered_rows,
    positive_decimal,
    read_text,
)
from shipready.reference.uqc import UQC

ITC_HS_COLUMNS = ("code", "description", "chapter", "export_policy", "uqc", "source")
RATE_COLUMNS = ("currency", "unit", "rate_inr", "valid_from", "notification")
PORT_COLUMNS = ("code", "name", "country", "unlocode", "kind")
PORT_KINDS = ("sea", "air", "icd")
RATE_UNITS = ("1", "100")

_HS_CODE_RE = re.compile(r"^[0-9]{8}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PACKAGE = "shipgen"


def parse_itc_hs(source: str, text: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line, row in numbered_rows(source, text, ITC_HS_COLUMNS):
        if not _HS_CODE_RE.match(row["code"]):
            raise ReferenceDataError(source, line, f"code must be 8 digits, got {row['code']!r}")
        if row["code"] in rows:
            raise ReferenceDataError(source, line, f"duplicate code {row['code']}")
        if row["export_policy"] not in EXPORT_POLICIES:
            raise ReferenceDataError(
                source, line, f"export_policy must be one of {EXPORT_POLICIES}"
            )
        if row["uqc"] not in UQC:
            raise ReferenceDataError(source, line, f"not a UQC code: {row['uqc']!r}")
        if not all(row[column] for column in ("description", "chapter", "source")):
            raise ReferenceDataError(source, line, "description, chapter and source are required")
        rows[row["code"]] = row
    return rows


def parse_exchange_rates(source: str, text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    for line, row in numbered_rows(source, text, RATE_COLUMNS):
        if not _CURRENCY_RE.match(row["currency"]):
            raise ReferenceDataError(
                source, line, f"currency must be 3 letters: {row['currency']!r}"
            )
        if row["unit"] not in RATE_UNITS:
            raise ReferenceDataError(source, line, f"unit must be one of {RATE_UNITS}")
        try:
            valid_from = date.fromisoformat(row["valid_from"])
        except ValueError:
            raise ReferenceDataError(source, line, "valid_from must be YYYY-MM-DD") from None
        if not row["notification"]:
            raise ReferenceDataError(source, line, "notification is empty")
        if (row["currency"], valid_from) in seen:
            raise ReferenceDataError(source, line, f"duplicate rate for {row['currency']}")
        seen.add((row["currency"], valid_from))
        rows.append(
            {
                **row,
                "unit": int(row["unit"]),
                "rate_inr": positive_decimal(source, line, "rate_inr", row["rate_inr"]),
                "valid_from": valid_from,
            }
        )
    return rows


def parse_ports(source: str, text: str) -> list[dict[str, str]]:
    rows = []
    for line, row in numbered_rows(source, text, PORT_COLUMNS):
        if row["kind"] not in PORT_KINDS:
            raise ReferenceDataError(source, line, f"kind must be one of {PORT_KINDS}")
        rows.append(row)
    return rows


@cache
def load_itc_hs() -> dict[str, dict[str, Any]]:
    return parse_itc_hs("itc_hs.csv", read_text("itc_hs.csv", _PACKAGE))


@cache
def load_exchange_rates() -> tuple[dict[str, Any], ...]:
    return tuple(
        parse_exchange_rates("exchange_rates.csv", read_text("exchange_rates.csv", _PACKAGE))
    )


@cache
def load_ports() -> tuple[dict[str, str], ...]:
    return tuple(parse_ports("ports.csv", read_text("ports.csv", _PACKAGE)))
