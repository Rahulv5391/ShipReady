"""Identifiers, references between documents, the LUT and mandatory fields (ID, PTY-03, INV-01,
GST-02, DOC-02)."""

import re
from datetime import date
from functools import partial
from typing import Any

from shipready.checks.fields import Fields, first_problem, transport_document
from shipready.checks.reference import Reference
from shipready.extract import field_templates
from shipready.normalise.identifiers import (
    clean,
    is_valid_ad_code,
    is_valid_gstin,
    is_valid_iec,
    pan_from_gstin,
)

GSTIN_DOCUMENTS = ("commercial_invoice", "shipping_bill", "lut")
# Fields that may rightly be absent: a bill of lading made out "to order" names no consignee, a
# notify party is optional, and the LUT statement is GST-01's to check. Address lines vary in
# number, so how many there should be is unknown. A port's country is rarely printed: its code
# gives it (shipping.port_country).
OPTIONAL_FIELDS = re.compile(
    r"^(bill_of_lading\.(consignee|notify_party)\..*|commercial_invoice\.gst_declaration"
    r"|.*\.address\.lines\[\]"
    r"|.*\.(port_of_loading|port_of_discharge|airport_of_departure|airport_of_destination)\.country)$"
)


def _identifiers(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    iec = clean(fields.text("commercial_invoice.iec"))

    def valid_iec() -> str | None:
        return f"IEC {iec} is not valid" if not is_valid_iec(iec) else None

    def gstin(document: str) -> str | None:
        value = clean(fields.text(f"{document}.gstin"))
        if not is_valid_gstin(value):
            return f"{document} GSTIN {value} is not valid"
        if pan_from_gstin(value) != iec:
            return f"{document} GSTIN {value} does not contain the IEC {iec}"
        return None

    return first_problem([valid_iec, *(partial(gstin, d) for d in GSTIN_DOCUMENTS)])


def _same_gstin(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    invoice = clean(fields.text("commercial_invoice.gstin"))
    bill = clean(fields.text("shipping_bill.gstin"))
    return f"invoice {invoice}, shipping bill {bill}" if invoice != bill else None


def _ad_code(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    codes = {d: clean(fields.text(f"{d}.ad_code")) for d in ("commercial_invoice", "shipping_bill")}
    invalid = [f"{d} {c}" for d, c in codes.items() if not is_valid_ad_code(c)]
    if invalid:
        return f"not a valid AD code: {', '.join(invalid)}"
    if len(set(codes.values())) > 1:
        return ", ".join(f"{d} {c}" for d, c in codes.items())
    return None


def _notify_party(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    if transport_document(fields) != "bill_of_lading" or not fields.flag("bill_of_lading.to_order"):
        return None
    if fields.optional("bill_of_lading.notify_party.name") is None:
        return "the bill of lading is made out to order but names no notify party"
    return None


def _invoice_reference(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    def number() -> str | None:
        invoice = fields.text("commercial_invoice.invoice_number")
        bill = fields.text("shipping_bill.invoice_number")
        return (
            f"invoice number {invoice}, shipping bill {bill}"
            if clean(invoice) != clean(bill)
            else None
        )

    def day() -> str | None:
        invoice = fields.day("commercial_invoice.invoice_date")
        bill = fields.day("shipping_bill.invoice_date")
        return f"invoice date {invoice}, shipping bill {bill}" if invoice != bill else None

    return first_problem([number, day])


def financial_year(day: date) -> str:
    """The Indian financial year (April to March) containing `day`, e.g. '2026-27'."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _lut(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    arn = clean(fields.text("lut.arn"))

    def quoted(document: str) -> str | None:
        value = clean(fields.text(f"{document}.lut_arn"))
        return f"{document} quotes LUT {value}, the LUT is {arn}" if value != arn else None

    def year() -> str | None:
        expected = financial_year(fields.day("commercial_invoice.invoice_date"))
        stated = fields.text("lut.financial_year")
        return (
            f"the LUT is for {stated}, the invoice falls in {expected}"
            if stated != expected
            else None
        )

    return first_problem(
        [lambda: quoted("commercial_invoice"), lambda: quoted("shipping_bill"), year]
    )


def _mandatory_fields(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    missing = []
    for document in sorted({path.split(".")[0] for path in fields.values}):
        for template in field_templates(document):
            full = f"{document}.{template}"
            if OPTIONAL_FIELDS.match(full):
                continue
            missing += [path for path in _paths(fields, full) if not fields.present(path)]
    if missing:
        return f"missing: {', '.join(missing)}"
    return None


def _paths(fields: Fields, template: str) -> list[str]:
    """The paths a template stands for: one per item of each list it goes through."""
    if "[]" not in template:
        return [template]
    head, tail = template.split("[]", 1)
    return [
        path for i in range(fields.count(head)) for path in _paths(fields, f"{head}[{i}]{tail}")
    ]


CHECKS = {
    "ID-01": _identifiers,
    "ID-02": _same_gstin,
    "ID-03": _ad_code,
    "PTY-03": _notify_party,
    "INV-01": _invoice_reference,
    "GST-02": _lut,
    "DOC-02": _mandatory_fields,
}
