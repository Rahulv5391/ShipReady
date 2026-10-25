"""Parse the Indian customs locations DGFT publishes from ICEGATE (dgft-ports.json).

Each entry reads "<code>-<name and address>-<EDI | Non EDI>", e.g.
"INNSA1-JNCH, NHAVA SHEVA, TAL:URAN, DIST-RAIGAD-400707-EDI".
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from shipready.reference.files import ReferenceDataError, json_list

# The last character of an ICEGATE location code gives its kind.
KINDS = {
    "1": "sea",  # seaport
    "2": "rail",  # rail cargo station
    "4": "air",  # air cargo complex
    "5": "post",  # foreign post office
    "6": "inland",  # inland container depot, container freight station or SEZ
    "B": "land",  # land customs station on a border
}
# The full list has about 640 locations; far fewer means a truncated download.
MIN_PORTS = 500

_ENTRY_RE = re.compile(r"^(IN[A-Z0-9]{3}[0-9A-Z])-(.+)-(EDI|Non EDI)$")
# Administrative entries in the list that are not places goods are cleared at: directorates
# (suffix D), the SOFTEX code (suffix 0) and the "DEEMED" placeholder.
_ADMINISTRATIVE_SUFFIXES = {"D", "0"}
_DEEMED = "DEEMED-"


@dataclass
class ParsedPorts:
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)  # administrative entries by code


def parse_ports(source: str, data: bytes) -> ParsedPorts:
    result = ParsedPorts()
    seen: set[str] = set()
    for position, entry in enumerate(json_list(source, data), start=1):
        value = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(value, str):
            raise ReferenceDataError(
                source, position, f"expected an object with a value: {entry!r}"
            )
        value = value.strip()
        if value.startswith(_DEEMED):
            result.skipped[value.split("-")[0]] += 1
            continue
        match = _ENTRY_RE.match(value)
        if match is None:
            raise ReferenceDataError(source, position, f"unrecognised port entry {value!r}")
        code, name, edi = match.groups()
        if code[-1] in _ADMINISTRATIVE_SUFFIXES:
            result.skipped[code] += 1
            continue
        if code[-1] not in KINDS:
            raise ReferenceDataError(source, position, f"unknown location kind in code {code}")
        if code in seen:
            raise ReferenceDataError(source, position, f"duplicate port code {code}")
        seen.add(code)
        result.rows.append(
            {
                "code": code,
                "name": re.sub(r"\s+", " ", name).strip(),
                "kind": KINDS[code[-1]],
                "edi": edi == "EDI",
            }
        )
    if len(result.rows) < MIN_PORTS:
        raise ReferenceDataError(
            source, None, f"only {len(result.rows)} ports (expected at least {MIN_PORTS})"
        )
    return result
