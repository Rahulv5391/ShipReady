"""CBIC customs exchange rates for exports, transcribed from notifications (Decision.md D-12)."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from shipready.reference.files import ReferenceDataError, numbered_rows, read_text

COLUMNS = ("currency", "unit", "rate_inr", "valid_from", "notification")

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
# CBIC quotes most currencies per 1 unit and a few (e.g. JPY) per 100 units.
_UNITS = (1, 100)


def parse_exchange_rates(source: str, text: str) -> list[dict[str, Any]]:
    """Validate exchange-rate CSV text; raise ReferenceDataError naming the file and line."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    for line, row in numbered_rows(source, text, COLUMNS):
        if not _CURRENCY_RE.match(row["currency"]):
            raise ReferenceDataError(
                source, line, f"currency must be 3 letters: {row['currency']!r}"
            )
        if row["unit"] not in {str(unit) for unit in _UNITS}:
            raise ReferenceDataError(source, line, f"unit must be one of {_UNITS}")
        rate = _positive_decimal(source, line, row["rate_inr"])
        valid_from = _iso_date(source, line, row["valid_from"])
        if not row["notification"]:
            raise ReferenceDataError(source, line, "notification is empty")
        key = (row["currency"], valid_from)
        if key in seen:
            raise ReferenceDataError(
                source, line, f"duplicate rate for {row['currency']} on {valid_from}"
            )
        seen.add(key)
        rows.append({**row, "unit": int(row["unit"]), "rate_inr": rate, "valid_from": valid_from})
    return rows


def load_exchange_rates() -> list[dict[str, Any]]:
    return parse_exchange_rates("exchange_rates.csv", read_text("exchange_rates.csv"))


def _positive_decimal(source: str, line: int, value: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ReferenceDataError(source, line, f"rate_inr is not a number: {value!r}") from None
    if not number.is_finite() or number <= 0:
        raise ReferenceDataError(source, line, f"rate_inr must be positive: {value!r}")
    return number


def _iso_date(source: str, line: int, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ReferenceDataError(
            source, line, f"valid_from must be YYYY-MM-DD: {value!r}"
        ) from None
