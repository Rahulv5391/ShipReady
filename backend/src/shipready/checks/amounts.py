"""Quantities, values, the exchange rate and the Incoterm (QTY, VAL, FX, INC)."""

from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from typing import Any

from shipready.checks.fields import (
    Fields,
    LineCountDiffers,
    NotVerified,
    first_problem,
    line_count,
    same_text,
    transport_document,
)
from shipready.checks.reference import Reference
from shipready.normalise.identifiers import clean
from shipready.normalise.units import same_quantity, to_uqc

CENTS = Decimal("0.01")
INVOICE = "commercial_invoice"
# Incoterms 2020 under which the seller pays the main carriage, so freight is prepaid: the C and
# D terms. Under E and F terms the buyer pays it on arrival (collect).
PREPAID_INCOTERMS = {"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}


def _quantity(fields: Fields, line: str) -> tuple[Decimal, str]:
    quantity = fields.number(f"{line}.quantity")
    printed = fields.text(f"{line}.uqc")
    unit = to_uqc(printed)
    if unit is None:
        raise NotVerified(f"{line}.uqc {printed!r} is not a known unit")
    return quantity, unit


def _quantities_match(fields: Fields, other: str) -> str | None:
    try:
        count = line_count(fields, INVOICE, other)
    except LineCountDiffers as error:
        return str(error)

    def line(i: int) -> str | None:
        a, a_unit = _quantity(fields, f"{INVOICE}.lines[{i}]")
        b, b_unit = _quantity(fields, f"{other}.lines[{i}]")
        if same_quantity(a, a_unit, b, b_unit) is False:
            return f"line {i + 1}: invoice {a} {a_unit}, {other} {b} {b_unit}"
        return None

    return first_problem(partial(line, i) for i in range(count))


def _arithmetic(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    count = fields.count(f"{INVOICE}.lines")
    if count == 0:
        raise NotVerified("no invoice lines found")

    def line(i: int) -> str | None:
        prefix = f"{INVOICE}.lines[{i}]"
        quantity, price = fields.number(f"{prefix}.quantity"), fields.number(f"{prefix}.unit_price")
        amount = fields.number(f"{prefix}.amount")
        expected = (quantity * price).quantize(CENTS, ROUND_HALF_UP)
        if amount != expected:
            return f"line {i + 1}: {quantity} x {price} is {expected}, not {amount}"
        return None

    def goods_value() -> str | None:
        total = sum(fields.number(f"{INVOICE}.lines[{i}].amount") for i in range(count))
        stated = fields.number(f"{INVOICE}.goods_value")
        return f"lines add up to {total}, not {stated}" if total != stated else None

    def invoice_total() -> str | None:
        parts = [
            fields.number(f"{INVOICE}.{name}") for name in ("goods_value", "freight", "insurance")
        ]
        stated = fields.number(f"{INVOICE}.total")
        expected = sum(parts, Decimal(0))
        return (
            f"goods, freight and insurance add up to {expected}, not {stated}"
            if expected != stated
            else None
        )

    return first_problem([*(partial(line, i) for i in range(count)), goods_value, invoice_total])


def _shipping_bill_value(
    fields: Fields, reference: Reference, params: dict[str, Any]
) -> str | None:
    invoice = (fields.number(f"{INVOICE}.total"), fields.text(f"{INVOICE}.currency").upper())
    bill = (
        fields.number("shipping_bill.invoice_value"),
        fields.text("shipping_bill.currency").upper(),
    )
    if invoice != bill:
        return f"invoice total {invoice[1]} {invoice[0]}, shipping bill {bill[1]} {bill[0]}"
    return None


def _order_prices(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    try:
        count = line_count(fields, INVOICE, "purchase_order")
    except LineCountDiffers as error:
        return str(error)

    def line(i: int) -> str | None:
        invoiced = fields.number(f"{INVOICE}.lines[{i}].unit_price")
        ordered = fields.number(f"purchase_order.lines[{i}].unit_price")
        if invoiced != ordered:
            return f"line {i + 1}: invoice price {invoiced}, order price {ordered}"
        return None

    return first_problem(partial(line, i) for i in range(count))


def _exchange_rate(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    currency = fields.text(f"{INVOICE}.currency").upper()
    on = fields.day("shipping_bill.shipping_bill_date")
    rate = reference.exchange_rate(currency, on)
    if rate is None:
        raise NotVerified(f"no customs export rate for {currency} on {on} in our data")
    customs, unit = rate

    def stated(document: str) -> str | None:
        printed = fields.number(f"{document}.exchange_rate")
        # A rate printed without its unit is read as given per the customs unit.
        printed_unit = fields.optional(f"{document}.exchange_rate_unit")
        per_unit = printed / Decimal(printed_unit) if printed_unit else printed / unit
        if per_unit != customs / unit:
            return f"{document} rate {printed}, customs rate {customs} per {unit} {currency}"
        return None

    return first_problem([lambda: stated(INVOICE), lambda: stated("shipping_bill")])


def _incoterm(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    incoterm = fields.text(f"{INVOICE}.incoterm")

    def order() -> str | None:
        ordered = fields.text("purchase_order.incoterm")
        return (
            f"invoice {incoterm!r}, order {ordered!r}" if not same_text(incoterm, ordered) else None
        )

    def freight() -> str | None:
        document = transport_document(fields)
        terms = fields.text(f"{document}.freight_terms").casefold()
        expected = "prepaid" if clean(incoterm)[:3] in PREPAID_INCOTERMS else "collect"
        if expected not in terms:
            return f"{incoterm} means freight {expected}; {document} says {terms!r}"
        return None

    return first_problem([order, freight])


CHECKS = {
    "QTY-01": lambda fields, reference, params: _quantities_match(fields, "packing_list"),
    "QTY-02": lambda fields, reference, params: _quantities_match(fields, "shipping_bill"),
    "QTY-03": lambda fields, reference, params: _quantities_match(fields, "purchase_order"),
    "VAL-01": _arithmetic,
    "VAL-02": _shipping_bill_value,
    "VAL-03": _order_prices,
    "FX-01": _exchange_rate,
    "INC-01": _incoterm,
}
