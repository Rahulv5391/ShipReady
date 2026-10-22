"""ITC(HS) codes with their export policy, curated from DGFT (see Decision.md D-12)."""

import re
from typing import Any

from shipready.reference.files import ReferenceDataError, numbered_rows, read_text
from shipready.reference.uqc import UQC

EXPORT_POLICIES = ("Free", "Restricted", "Prohibited", "STE")
COLUMNS = ("code", "description", "chapter", "export_policy", "uqc", "source")

_CODE_RE = re.compile(r"^[0-9]{8}$")


def parse_itc_hs(source: str, text: str) -> list[dict[str, Any]]:
    """Validate ITC(HS) CSV text; raise ReferenceDataError naming the file and line."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line, row in numbered_rows(source, text, COLUMNS):
        if not _CODE_RE.match(row["code"]):
            raise ReferenceDataError(source, line, f"code must be 8 digits, got {row['code']!r}")
        if row["code"] in seen:
            raise ReferenceDataError(source, line, f"duplicate code {row['code']}")
        if row["export_policy"] not in EXPORT_POLICIES:
            raise ReferenceDataError(
                source, line, f"export_policy must be one of {EXPORT_POLICIES}"
            )
        if row["uqc"] not in UQC:
            raise ReferenceDataError(source, line, f"not a UQC code: {row['uqc']!r}")
        for column in ("description", "chapter", "source"):
            if not row[column]:
                raise ReferenceDataError(source, line, f"{column} is empty")
        seen.add(row["code"])
        rows.append(row)
    return rows


def load_itc_hs() -> list[dict[str, Any]]:
    return parse_itc_hs("itc_hs.csv", read_text("itc_hs.csv"))
