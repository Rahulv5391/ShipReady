"""Read reference data files, reporting problems with the file name and line number."""

import csv
import io
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from importlib.resources import files


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
