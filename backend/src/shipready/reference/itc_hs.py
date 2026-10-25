"""Parse DGFT's ITC(HS) code list (dgft-itc-hs.json): chapters, headings, subheadings and the
8-digit codes goods are declared under."""

import re
from typing import Any

from shipready.reference.files import ReferenceDataError, json_list

# The full list has about 12,500 eight-digit codes; far fewer means a truncated download.
MIN_EIGHT_DIGIT_CODES = 10_000

_CODE_RE = re.compile(r"^[0-9]{2}(?:[0-9]{2}(?:[0-9]{2}(?:[0-9]{2})?)?)?$")


def parse_itc_hs(source: str, data: bytes) -> list[dict[str, Any]]:
    """One row per code: code, level (2, 4, 6 or 8 digits) and description.

    DGFT's list pads some codes and descriptions with whitespace and repeats a few codes; the
    first entry for a code is kept. Errors name the entry by its position in the list.
    """
    entries = json_list(source, data)
    rows: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ReferenceDataError(source, position, f"expected an object, got {entry!r}")
        code = _clean(entry.get("itcCode"))
        description = _clean(entry.get("itcDescription"))
        if not _CODE_RE.match(code):
            raise ReferenceDataError(source, position, f"invalid ITC(HS) code {code!r}")
        if not description:
            raise ReferenceDataError(source, position, f"code {code} has no description")
        rows.setdefault(code, {"code": code, "level": len(code), "description": description})
    eight_digit = sum(1 for row in rows.values() if row["level"] == 8)
    if eight_digit < MIN_EIGHT_DIGIT_CODES:
        raise ReferenceDataError(
            source,
            None,
            f"only {eight_digit} eight-digit codes (expected at least {MIN_EIGHT_DIGIT_CODES})",
        )
    return list(rows.values())


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""
