"""Parse the ISO 4217 currency list published by SIX, the maintenance agency (list-one.xml)."""

import re
from typing import Any
from xml.etree import ElementTree

from shipready.reference.files import ReferenceDataError

# The list has about 180 currencies; far fewer means a truncated download.
MIN_CURRENCIES = 150

_CODE_RE = re.compile(r"^[A-Z]{3}$")
# Funds, precious metals and testing codes have no minor unit.
_NO_MINOR_UNIT = "N.A."


def parse_currencies(source: str, data: bytes) -> list[dict[str, Any]]:
    """One row per currency code: code, name and the number of decimal places (or None).

    The list has one entry per country using a currency, so a code repeats; repeats must agree.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ReferenceDataError(source, None, f"not valid XML ({error})") from None
    if root.tag != "ISO_4217":
        raise ReferenceDataError(source, None, f"expected an ISO_4217 document, got <{root.tag}>")

    rows: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(root.iter("CcyNtry"), start=1):
        code = (entry.findtext("Ccy") or "").strip()
        if not code:
            continue  # territories without a universal currency (e.g. Antarctica)
        if not _CODE_RE.match(code):
            raise ReferenceDataError(source, position, f"invalid currency code {code!r}")
        name = (entry.findtext("CcyNm") or "").strip()
        minor = (entry.findtext("CcyMnrUnts") or "").strip()
        if not name or not (minor.isdigit() or minor == _NO_MINOR_UNIT):
            raise ReferenceDataError(source, position, f"incomplete entry for {code}")
        row = {"code": code, "name": name, "minor_units": int(minor) if minor.isdigit() else None}
        if rows.setdefault(code, row) != row:
            raise ReferenceDataError(source, position, f"conflicting entries for {code}")
    if len(rows) < MIN_CURRENCIES:
        raise ReferenceDataError(
            source, None, f"only {len(rows)} currencies (expected at least {MIN_CURRENCIES})"
        )
    return list(rows.values())
