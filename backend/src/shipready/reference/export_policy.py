"""Build the export policy table from DGFT's Restricted, Prohibited and STE lists
(dgft-export-policy.json) and the curated overrides (reference/data/export_policy_overrides.csv).

Any 8-digit code that is on no list is Free. DGFT's lists keep some stale entries (a lapsed
prohibition, codes since split), so each listed code is checked against the policy DGFT's code page
shows today:
- a code no longer in the ITC(HS) list is dropped (its successor codes carry the policy);
- a code on several lists, or whose list policy differs from today's, must have its dated history
  in the overrides file, whose open-ended period must match today's policy.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from shipready.reference.files import (
    ReferenceDataError,
    indian_date,
    json_value,
    numbered_rows,
    read_text,
)

EXPORT_POLICIES = ("Free", "Restricted", "Prohibited", "STE")
LISTED_POLICIES = ("Restricted", "Prohibited", "STE")
OVERRIDE_COLUMNS = ("code", "policy", "effective_from", "effective_to", "notification", "note")
OVERRIDES_FILE = "export_policy_overrides.csv"
# A DGFT notification number: 23/2015-20, 104(RE-2013)/2009-2014 or 13/2023.
_NOTIFICATION_RE = re.compile(r"^\d+(?:\(RE-\d{4}\))?/\d{4}(?:-\d{2,4})?$")
# Words DGFT sometimes writes around a number ("Notification No. 110/2009-14").
_NOTIFICATION_WORDS = {"Notification", "No."}


@dataclass
class ParsedPolicy:
    rows: list[dict[str, Any]] = field(default_factory=list)
    dropped: Counter[str] = field(default_factory=Counter)  # listed codes not in ITC(HS), by list


def parse_export_policy(
    source: str, data: bytes, codes: set[str], overrides: list[dict[str, Any]]
) -> ParsedPolicy:
    """Policy rows (code, policy, effective_from, effective_to, notification, source).

    `codes` are the current 8-digit ITC(HS) codes; `overrides` come from `parse_overrides`.
    """
    payload = json_value(source, data)
    lists, current = _lists_and_current(source, payload)
    overridden = {row["code"] for row in overrides}
    result = ParsedPolicy()

    entries: dict[str, list[dict[str, Any]]] = {}
    for policy, items in lists.items():
        for position, item in enumerate(items, start=1):
            code = str(item.get("itcCode", "")).strip() if isinstance(item, dict) else ""
            if len(code) != 8 or not code.isdigit():
                raise ReferenceDataError(f"{source} {policy} list", position, f"bad code {code!r}")
            if code not in codes:
                result.dropped[policy] += 1
                continue
            numbers, dates = _notifications(f"{source} {policy} list", position, item)
            entries.setdefault(code, []).append(
                {
                    "policy": policy,
                    "notification": "; ".join(numbers) or None,
                    # With several notifications, the latest is the only date from which the
                    # listed policy is certain to apply (an earlier one may have set another).
                    "effective_from": max(dates) if dates else None,
                }
            )

    for code, found in sorted(entries.items()):
        if code in overridden:
            continue
        policies = {entry["policy"] for entry in found}
        if len(policies) > 1:
            raise ReferenceDataError(
                source,
                None,
                f"{code} is on the {', '.join(sorted(policies))} lists; record its dated history "
                f"in {OVERRIDES_FILE}",
            )
        (policy,) = policies
        if len(found) > 1:
            raise ReferenceDataError(
                source,
                None,
                f"{code} is on the {policy} list {len(found)} times; record its dated history "
                f"in {OVERRIDES_FILE}",
            )
        if current.get(code) != policy:
            raise ReferenceDataError(
                source,
                None,
                f"{code}: DGFT lists it as {policy} but its code page shows "
                f"{current.get(code, 'nothing')}; record its history in {OVERRIDES_FILE}",
            )
        result.rows.append({"code": code, **found[0], "effective_to": None, "source": "dgft"})

    for row in overrides:
        if row["code"] not in codes:
            raise ReferenceDataError(OVERRIDES_FILE, None, f"{row['code']} is not an ITC(HS) code")
        if row["effective_to"] is None and row["policy"] != current.get(row["code"], "Free"):
            raise ReferenceDataError(
                OVERRIDES_FILE,
                None,
                f"{row['code']}: open-ended override says {row['policy']} but DGFT now shows "
                f"{current.get(row['code'], 'Free')}; update the override",
            )
        result.rows.append(
            {**{k: row[k] for k in OVERRIDE_COLUMNS if k != "note"}, "source": "override"}
        )
    return result


def parse_overrides(source: str, text: str) -> list[dict[str, Any]]:
    """Dated policy periods per code; a code's periods must be in order and must not overlap."""
    rows: list[dict[str, Any]] = []
    for line, row in numbered_rows(source, text, OVERRIDE_COLUMNS):
        code = row["code"]
        if len(code) != 8 or not code.isdigit():
            raise ReferenceDataError(source, line, f"code must be 8 digits, got {code!r}")
        if row["policy"] not in EXPORT_POLICIES:
            raise ReferenceDataError(source, line, f"policy must be one of {EXPORT_POLICIES}")
        start = _iso_date(source, line, row["effective_from"])
        end = _iso_date(source, line, row["effective_to"]) if row["effective_to"] else None
        if end is not None and end < start:
            raise ReferenceDataError(source, line, "effective_to is before effective_from")
        if not row["notification"] or not row["note"]:
            raise ReferenceDataError(source, line, "notification and note are required")
        previous = next((r for r in reversed(rows) if r["code"] == code), None)
        if previous is not None and (
            previous["effective_to"] is None or start <= previous["effective_to"]
        ):
            raise ReferenceDataError(source, line, f"period overlaps the previous one for {code}")
        rows.append({**row, "effective_from": start, "effective_to": end})
    return rows


def load_overrides() -> list[dict[str, Any]]:
    return parse_overrides(OVERRIDES_FILE, read_text(OVERRIDES_FILE))


def _lists_and_current(source: str, payload: Any) -> tuple[dict[str, list[Any]], dict[str, str]]:
    if not isinstance(payload, dict):
        raise ReferenceDataError(source, None, "expected an object with 'lists' and 'current'")
    lists, current = payload.get("lists"), payload.get("current")
    if not isinstance(lists, dict) or set(lists) != set(LISTED_POLICIES):
        raise ReferenceDataError(source, None, f"expected lists {LISTED_POLICIES}")
    if not all(isinstance(items, list) and items for items in lists.values()):
        raise ReferenceDataError(source, None, "an export policy list is empty")
    if not isinstance(current, dict):
        raise ReferenceDataError(source, None, "missing the current policy per code")
    return lists, current


def _notifications(
    source: str, position: int, item: dict[str, Any]
) -> tuple[list[str], list[date]]:
    """Notification numbers and dates DGFT cites for an entry.

    The fields are free text: some entries cite several notifications (one per line, or separated
    by spaces), some write "Notification No. 110/2009-14", and a few give a number but no date.
    Numbers are found by their shape; dates, when given, must match the numbers one for one.
    """
    number_text = str(item.get("notificationNo") or "")
    words = number_text.split()
    numbers = [word for word in words if _NOTIFICATION_RE.match(word)]
    if any(word not in _NOTIFICATION_WORDS for word in words if word not in numbers):
        raise ReferenceDataError(source, position, f"unrecognised notification {number_text!r}")
    texts = str(item.get("notificationDate") or "").split()
    if texts and len(texts) != len(numbers):
        raise ReferenceDataError(
            source, position, f"{len(numbers)} notification numbers but {len(texts)} dates"
        )
    return numbers, [indian_date(source, position, text) for text in texts]


def _iso_date(source: str, line: int, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ReferenceDataError(source, line, f"expected YYYY-MM-DD, got {value!r}") from None
