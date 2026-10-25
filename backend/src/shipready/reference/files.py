"""Read reference data files, reporting problems with the file name and line number."""

import csv
import io
import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Any


class ReferenceDataError(ValueError):
    """A reference file is malformed; the message starts with '<file>:<line>:'."""

    def __init__(self, source: str, line: int | None, message: str) -> None:
        location = source if line is None else f"{source}:{line}"
        super().__init__(f"{location}: {message}")


def read_text(name: str, package: str = "shipready.reference") -> str:
    """Text of the packaged file <package>/data/<name>."""
    return files(package).joinpath("data", name).read_text(encoding="utf-8")


def read_csv(name: str) -> list[dict[str, str]]:
    """Rows of the packaged CSV reference/data/<name> as dicts keyed by the header row."""
    return list(csv.DictReader(read_text(name).splitlines()))


def numbered_rows(
    source: str, text: str, columns: tuple[str, ...]
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (line number, row) from CSV text whose header must be exactly `columns`."""
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != columns:
        raise ReferenceDataError(source, 1, f"expected columns {columns}, got {reader.fieldnames}")
    for row in reader:
        if None in row or None in row.values():
            raise ReferenceDataError(source, reader.line_num, f"expected {len(columns)} fields")
        yield reader.line_num, {key: value.strip() for key, value in row.items()}


def positive_decimal(source: str, line: int, name: str, value: str) -> Decimal:
    """Parse a positive, finite decimal field or raise ReferenceDataError."""
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ReferenceDataError(source, line, f"{name} is not a number: {value!r}") from None
    if not number.is_finite() or number <= 0:
        raise ReferenceDataError(source, line, f"{name} must be positive: {value!r}")
    return number


def json_value(source: str, data: bytes) -> Any:
    """Decode JSON, keeping decimal numbers exact (rates must not pass through float)."""
    try:
        return json.loads(data, parse_float=Decimal)
    except ValueError as error:
        raise ReferenceDataError(source, None, f"not valid JSON ({error})") from None


def json_list(source: str, data: bytes) -> list[Any]:
    value = json_value(source, data)
    if not isinstance(value, list):
        raise ReferenceDataError(source, None, "expected a JSON list")
    return value


def indian_date(source: str, position: int | None, value: object) -> date:
    """Parse a day-month-year date as DGFT and ICEGATE print them: 17-06-2025, 17/06/2025 or
    17.06.2025."""
    text = value.strip() if isinstance(value, str) else ""
    for layout in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, layout).date()
        except ValueError:
            continue
    raise ReferenceDataError(source, position, f"expected a DD-MM-YYYY date, got {value!r}")
