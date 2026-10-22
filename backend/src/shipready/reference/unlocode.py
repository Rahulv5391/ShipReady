"""Parse the UN/LOCODE code list from the UNECE release zip (unlocode-latest.zip).

The release has the list split over `CodeListPart<n>.csv` files with no header row and 12 columns:
change, country, location, name, name without diacritics, subdivision, function, status, date,
IATA, coordinates, remarks.
"""

import csv
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shipready.reference.files import ReferenceDataError

_PART_RE = re.compile(r"CodeListPart\d+\.csv$")
_FIELD_COUNT = 12
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_LOCATION_RE = re.compile(r"^[A-Z0-9]{3}$")
_FUNCTION_RE = re.compile(r"^[0-9B-]{8}$")
# Change marker "X": the entry is marked for deletion in this release.
_DELETED = "X"


@dataclass
class ParsedLocations:
    rows: list[dict[str, Any]] = field(default_factory=list)
    # Entries skipped because their country is not in ISO 3166 (e.g. XZ, international waters).
    skipped_countries: Counter[str] = field(default_factory=Counter)


def parse_unlocode(zip_path: Path, countries: set[str]) -> ParsedLocations:
    """Locations from the release zip, one row per code, for countries in `countries`."""
    with zipfile.ZipFile(zip_path) as archive:
        parts = sorted(name for name in archive.namelist() if _PART_RE.search(name))
        if not parts:
            raise ReferenceDataError(zip_path.name, None, "no CodeListPart*.csv files in the zip")
        result = ParsedLocations()
        # code -> (changed in this release, row)
        chosen: dict[str, tuple[bool, dict[str, Any]]] = {}
        for part in parts:
            source = f"{zip_path.name}/{Path(part).name}"
            for line, fields in _read_part(source, archive.read(part)):
                change, country, location = fields[0], fields[1], fields[2]
                if not location or change == _DELETED:
                    continue  # country header rows have no location code
                if country not in countries:
                    result.skipped_countries[country] += 1
                    continue
                row = _location(source, line, fields)
                changed = bool(change)
                # A code listed twice (renamed or bilingual places) keeps the entry changed in
                # this release; otherwise the first one.
                if row["code"] not in chosen or (changed and not chosen[row["code"]][0]):
                    chosen[row["code"]] = (changed, row)
    result.rows = [row for _, row in chosen.values()]
    return result


def _read_part(source: str, data: bytes) -> list[tuple[int, list[str]]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReferenceDataError(source, None, f"not UTF-8 ({error.reason})") from None
    rows = []
    for line, fields in enumerate(csv.reader(io.StringIO(text)), start=1):
        if len(fields) != _FIELD_COUNT:
            raise ReferenceDataError(
                source, line, f"expected {_FIELD_COUNT} fields, got {len(fields)}"
            )
        rows.append((line, fields))
    return rows


def _location(source: str, line: int, fields: list[str]) -> dict[str, Any]:
    _, country, location, name, _, subdivision, function, status, *_ = fields
    if not _COUNTRY_RE.match(country) or not _LOCATION_RE.match(location):
        raise ReferenceDataError(source, line, f"invalid code {country!r} {location!r}")
    if not _FUNCTION_RE.match(function):
        raise ReferenceDataError(source, line, f"function must be 8 characters, got {function!r}")
    if not name:
        raise ReferenceDataError(source, line, "name is empty")
    return {
        "code": country + location,
        "country": country,
        "name": name,
        "subdivision": subdivision or None,
        "functions": function,
        "status": status or None,
    }
