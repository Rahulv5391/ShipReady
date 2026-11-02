"""HS codes, export policy and units of quantity (HS-01, HS-02, POL-01, UQC-01)."""

import re
from functools import partial
from typing import Any

from shipready.checks.fields import (
    Fields,
    LineCountDiffers,
    NotVerified,
    first_problem,
    line_count,
)
from shipready.checks.reference import Reference
from shipready.normalise.units import to_uqc

# Documents whose lines carry an HS code, and those that state a unit for each line.
HS_DOCUMENTS = ("commercial_invoice", "shipping_bill", "certificate_of_origin")
UNIT_DOCUMENTS = ("commercial_invoice", "packing_list", "shipping_bill", "certificate_of_origin")


def _hs_code(fields: Fields, line: str) -> str:
    """The code without the dots and spaces it is often printed with (8471.30.10)."""
    return re.sub(r"[\s.]", "", fields.text(f"{line}.hs_code"))


def _valid_codes(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    def code(document: str, i: int) -> str | None:
        value = _hs_code(fields, f"{document}.lines[{i}]")
        if not re.fullmatch(r"[0-9]{8}", value):
            return f"{document} line {i + 1}: {value!r} is not an 8-digit ITC(HS) code"
        known = reference.hs_code_known(value)
        if not known:
            # Absent from our copy of the schedule, which may be out of date: not a failure.
            raise NotVerified(f"{value} is not in our copy of the ITC(HS) schedule")
        return None

    return first_problem(
        partial(code, document, i)
        for document in HS_DOCUMENTS
        for i in range(fields.count(f"{document}.lines"))
    )


def _same_codes(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    try:
        count = line_count(fields, *HS_DOCUMENTS)
    except LineCountDiffers as error:
        return str(error)

    def line(i: int) -> str | None:
        codes = {d: _hs_code(fields, f"{d}.lines[{i}]") for d in HS_DOCUMENTS}
        if len(set(codes.values())) > 1:
            return f"line {i + 1}: " + ", ".join(f"{d} {c}" for d, c in codes.items())
        return None

    return first_problem(partial(line, i) for i in range(count))


def _policy(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    on = fields.day("commercial_invoice.invoice_date")
    count = fields.count("commercial_invoice.lines")
    if count == 0:
        raise NotVerified("no invoice lines found")

    def line(i: int) -> str | None:
        code = _hs_code(fields, f"commercial_invoice.lines[{i}]")
        policy = reference.export_policy(code, on)
        if policy is None:
            raise NotVerified(f"{code} is not in our copy of the ITC(HS) schedule")
        return f"line {i + 1}: export of {code} is {policy}" if policy != "Free" else None

    return first_problem(partial(line, i) for i in range(count))


def _units(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    try:
        count = line_count(fields, *UNIT_DOCUMENTS)
    except LineCountDiffers as error:
        raise NotVerified(str(error)) from error  # a missing line is QTY's and HS's to report

    def line(i: int) -> str | None:
        printed = {d: fields.text(f"{d}.lines[{i}].uqc") for d in UNIT_DOCUMENTS}
        unknown = [f"{d} {u!r}" for d, u in printed.items() if to_uqc(u) is None]
        if unknown:
            return f"line {i + 1}: not a unit quantity code: {', '.join(unknown)}"
        if len({to_uqc(u) for u in printed.values()}) > 1:
            return f"line {i + 1}: " + ", ".join(f"{d} {u}" for d, u in printed.items())
        return None

    return first_problem(partial(line, i) for i in range(count))


CHECKS = {
    "HS-01": _valid_codes,
    "HS-02": _same_codes,
    "POL-01": _policy,
    "UQC-01": _units,
}
