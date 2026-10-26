"""Plain reference versions of the checks, used only to prove ShipGen's labels are right: on every
case, the rules the oracle finds broken must be exactly the rules its labels name.

It is not ShipReady's rule engine (Phases 13-15). It covers the rules a mutation targets, reads
ShipGen's own snapshot, and compares judgement-based fields (descriptions, parties) after simple
normalisation, which is enough to tell ShipGen's mutations from its look-alikes. HS-03
(plausibility) needs judgement and is not covered.
"""

from collections.abc import Callable, Iterator
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from typing import Any

from pydantic import BaseModel

from shipgen import profiles
from shipgen.generator import financial_year, rate_on
from shipgen.reference import load_itc_hs, load_ports
from shipready.documents.models import (
    AirWaybill,
    BillOfLading,
    InvoiceLine,
    PackingLine,
    Party,
    ShipmentDocuments,
)
from shipready.normalise.containers import is_valid_container
from shipready.normalise.identifiers import (
    clean,
    is_valid_ad_code,
    is_valid_gstin,
    is_valid_iec,
    pan_from_gstin,
)
from shipready.normalise.units import same_quantity
from shipready.reference.uqc import UQC
from shipready.rules.catalogue import load_catalogue

CENTS = Decimal("0.01")
Check = Callable[[ShipmentDocuments], bool]  # True when the rule is broken


def violations(documents: ShipmentDocuments) -> set[str]:
    return {rule for rule, broken in CHECKS.items() if broken(documents)}


def _transport(d: ShipmentDocuments) -> BillOfLading | AirWaybill:
    transport = d.bill_of_lading or d.air_waybill
    if transport is None:
        raise ValueError("a shipment needs a bill of lading or an airway bill")
    return transport


def _text(value: str) -> str:
    """Case, spacing and the company suffix's spelling do not change what a text says."""
    return " ".join(value.casefold().replace("private limited", "pvt ltd").split())


def _party(party: Party) -> tuple[str, ...]:
    address = party.address
    return (
        _text(party.name),
        *(_text(line) for line in address.lines),
        _text(address.city),
        address.country,
    )


def _lines(d: ShipmentDocuments) -> Iterator[tuple[Any, Any, Any, Any]]:
    return zip(
        d.commercial_invoice.lines,
        d.packing_list.lines,
        d.shipping_bill.lines,
        d.certificate_of_origin.lines,
        strict=True,
    )


def _quantities_differ(a: InvoiceLine, b: InvoiceLine | PackingLine) -> bool:
    return same_quantity(a.quantity, a.uqc, b.quantity, b.uqc) is False


def _arithmetic(d: ShipmentDocuments) -> bool:
    invoice = d.commercial_invoice
    lines = invoice.lines
    wrong_line = any(
        line.amount != (line.quantity * line.unit_price).quantize(CENTS, ROUND_HALF_UP)
        for line in lines
    )
    return (
        wrong_line
        or sum(line.amount for line in lines) != invoice.goods_value
        or invoice.goods_value + invoice.freight + invoice.insurance != invoice.total
    )


def _exchange_rate(d: ShipmentDocuments) -> bool:
    bill = d.shipping_bill
    rate: Decimal = rate_on(d.commercial_invoice.currency, bill.shipping_bill_date)["rate_inr"]
    return d.commercial_invoice.exchange_rate != rate or bill.exchange_rate != rate


def _incoterm(d: ShipmentDocuments) -> bool:
    term = d.commercial_invoice.incoterm.split()[0]
    expected = "prepaid" if term in profiles.PREPAID_INCOTERMS else "collect"
    return (
        d.purchase_order.incoterm != d.commercial_invoice.incoterm
        or _transport(d).freight_terms != expected
    )


def _package_count(d: ShipmentDocuments) -> bool:
    counts = {d.packing_list.total_packages, d.shipping_bill.total_packages}
    return len(counts | {_transport(d).total_packages}) > 1


@cache
def weight_tolerance_pct() -> Decimal:
    """WT-01's gross weight tolerance, as the catalogue sets it."""
    rule = next(rule for rule in load_catalogue() if rule.id == "WT-01")
    return Decimal(str(rule.params["gross_weight_tolerance_pct"]))


def _gross_weight(d: ShipmentDocuments) -> bool:
    packing = d.packing_list.gross_weight_kg
    difference = abs(packing - _transport(d).gross_weight_kg)
    return difference * 100 > packing * weight_tolerance_pct()


def _weights(d: ShipmentDocuments) -> bool:
    packing = d.packing_list
    return (
        packing.net_weight_kg > packing.gross_weight_kg
        or sum(line.net_weight_kg for line in packing.lines) != packing.net_weight_kg
        or sum(line.gross_weight_kg for line in packing.lines) != packing.gross_weight_kg
    )


def _containers(d: ShipmentDocuments, field: str, documents: tuple[str, ...]) -> list[list[str]]:
    lists = []
    for name in documents:
        document = getattr(d, name)
        if document is not None and not isinstance(document, AirWaybill):
            lists.append(sorted(clean(getattr(c, field)) for c in document.containers))
    return lists


def _container_numbers(d: ShipmentDocuments) -> bool:
    lists = _containers(d, "number", ("packing_list", "bill_of_lading", "shipping_bill"))
    return any(numbers != lists[0] for numbers in lists) or not all(
        is_valid_container(number) for numbers in lists for number in numbers
    )


def _container_count(d: ShipmentDocuments) -> bool:
    lists = _containers(d, "number", ("packing_list", "bill_of_lading", "shipping_bill"))
    return len({len(numbers) for numbers in lists}) > 1


def _seals(d: ShipmentDocuments) -> bool:
    lists = _containers(d, "seal", ("packing_list", "bill_of_lading"))
    return len(lists) == 2 and lists[0] != lists[1]


def _marks(d: ShipmentDocuments) -> bool:
    bill = d.bill_of_lading
    return bill is not None and bill.marks != d.packing_list.marks


def _hs_valid(d: ShipmentDocuments) -> bool:
    known = load_itc_hs()
    return any(line.hs_code not in known for line in d.commercial_invoice.lines)


def _hs_same(d: ShipmentDocuments) -> bool:
    return any(len({ci.hs_code, sb.hs_code, coo.hs_code}) > 1 for ci, _, sb, coo in _lines(d))


def _policy(d: ShipmentDocuments) -> bool:
    known = load_itc_hs()
    return any(
        line.hs_code in known and known[line.hs_code]["export_policy"] != "Free"
        for line in d.commercial_invoice.lines
    )


def _descriptions(d: ShipmentDocuments) -> bool:
    expected = "; ".join(
        sorted({line.description.split(" - ")[0] for line in d.commercial_invoice.lines})
    )
    return _text(_transport(d).goods_description) != _text(expected) or any(
        len({_text(line.description) for line in lines}) > 1 for lines in _lines(d)
    )


def _units(d: ShipmentDocuments) -> bool:
    return any(
        len({line.uqc for line in lines}) > 1 or lines[0].uqc not in UQC for lines in _lines(d)
    )


def _identifiers(d: ShipmentDocuments) -> bool:
    iec = clean(d.commercial_invoice.iec)
    gstins = (d.commercial_invoice.gstin, d.shipping_bill.gstin, d.lut.gstin)
    return not is_valid_iec(iec) or any(
        not is_valid_gstin(gstin) or pan_from_gstin(gstin) != iec for gstin in gstins
    )


def _gstin_same(d: ShipmentDocuments) -> bool:
    return clean(d.commercial_invoice.gstin) != clean(d.shipping_bill.gstin)


def _ad_code(d: ShipmentDocuments) -> bool:
    codes = {d.commercial_invoice.ad_code, d.shipping_bill.ad_code}
    return len(codes) > 1 or not all(is_valid_ad_code(code) for code in codes)


def _exporter(d: ShipmentDocuments) -> bool:
    parties = (
        d.commercial_invoice.exporter,
        d.packing_list.exporter,
        d.purchase_order.seller,
        d.certificate_of_origin.exporter,
        _transport(d).shipper,
    )
    names = {_text(d.shipping_bill.exporter_name), _text(d.lut.legal_name)}
    return len({_party(p) for p in parties}) > 1 or names != {_text(parties[0].name)}


def _consignee(d: ShipmentDocuments) -> bool:
    parties = [
        d.commercial_invoice.consignee,
        d.packing_list.consignee,
        d.purchase_order.buyer,
        d.certificate_of_origin.consignee,
    ]
    transport_consignee = _transport(d).consignee
    if transport_consignee is not None:  # None on a bill of lading made out "to order"
        parties.append(transport_consignee)
    bill = d.shipping_bill
    return len({_party(p) for p in parties}) > 1 or (
        _text(bill.consignee_name),
        bill.consignee_country,
    ) != (_text(parties[0].name), parties[0].address.country)


def _notify_party(d: ShipmentDocuments) -> bool:
    bill = d.bill_of_lading
    return bill is not None and bill.to_order and bill.notify_party is None


def _invoice_reference(d: ShipmentDocuments) -> bool:
    invoice, bill = d.commercial_invoice, d.shipping_bill
    return (bill.invoice_number, bill.invoice_date) != (
        invoice.invoice_number,
        invoice.invoice_date,
    )


def _lut_statement(d: ShipmentDocuments) -> bool:
    return not d.commercial_invoice.gst_declaration.strip()


def _lut(d: ShipmentDocuments) -> bool:
    lut = d.lut
    return (
        d.commercial_invoice.lut_arn != lut.arn
        or d.shipping_bill.lut_arn != lut.arn
        or lut.financial_year != financial_year(d.commercial_invoice.invoice_date)
    )


def _port(d: ShipmentDocuments) -> bool:
    indian = {port["code"] for port in load_ports() if port["country"] == "IN"}
    code = d.commercial_invoice.port_of_loading.code
    transport = _transport(d)
    departure = (
        transport.airport_of_departure
        if isinstance(transport, AirWaybill)
        else transport.port_of_loading
    )
    return code not in indian or {d.shipping_bill.port_code, departure.code} != {code}


def _destination(d: ShipmentDocuments) -> bool:
    transport = _transport(d)
    discharge = (
        transport.airport_of_destination
        if isinstance(transport, AirWaybill)
        else transport.port_of_discharge
    )
    countries = {
        d.commercial_invoice.destination_country,
        d.certificate_of_origin.destination_country,
        discharge.country,
    }
    return len(countries) > 1


def _dates(d: ShipmentDocuments) -> bool:
    transport = _transport(d)
    shipped = (
        transport.flight_date if isinstance(transport, AirWaybill) else transport.shipped_on_board
    )
    invoice_date = d.commercial_invoice.invoice_date
    return not (
        d.purchase_order.po_date <= invoice_date <= shipped
        and d.certificate_of_origin.certificate_date <= shipped
    )


def _blank_fields(d: ShipmentDocuments) -> bool:
    # The LUT statement belongs to GST-01, so it is not counted here.
    return any(path != "commercial_invoice.gst_declaration" for path in _empty_text(d, ""))


def _empty_text(node: Any, path: str) -> Iterator[str]:
    if isinstance(node, str):
        if not node.strip():
            yield path
    elif isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from _empty_text(getattr(node, name), f"{path}.{name}".lstrip("."))
    elif isinstance(node, tuple):
        for i, item in enumerate(node):
            yield from _empty_text(item, f"{path}[{i}]")


CHECKS: dict[str, Check] = {
    "QTY-01": lambda d: any(_quantities_differ(ci, pl) for ci, pl, _, _ in _lines(d)),
    "QTY-02": lambda d: any(_quantities_differ(ci, sb) for ci, _, sb, _ in _lines(d)),
    "QTY-03": lambda d: any(
        _quantities_differ(ci, po)
        for ci, po in zip(d.commercial_invoice.lines, d.purchase_order.lines, strict=True)
    ),
    "VAL-01": _arithmetic,
    "VAL-02": lambda d: (
        (d.shipping_bill.invoice_value, d.shipping_bill.currency)
        != (d.commercial_invoice.total, d.commercial_invoice.currency)
    ),
    "VAL-03": lambda d: any(
        ci.unit_price != po.unit_price
        for ci, po in zip(d.commercial_invoice.lines, d.purchase_order.lines, strict=True)
    ),
    "FX-01": _exchange_rate,
    "INC-01": _incoterm,
    "PKG-01": _package_count,
    "WT-01": _gross_weight,
    "WT-02": _weights,
    "CNT-01": _container_numbers,
    "CNT-02": _container_count,
    "CNT-03": _seals,
    "MRK-01": _marks,
    "HS-01": _hs_valid,
    "HS-02": _hs_same,
    "POL-01": _policy,
    "DESC-01": _descriptions,
    "UQC-01": _units,
    "ID-01": _identifiers,
    "ID-02": _gstin_same,
    "ID-03": _ad_code,
    "PTY-01": _exporter,
    "PTY-02": _consignee,
    "PTY-03": _notify_party,
    "INV-01": _invoice_reference,
    "GST-01": _lut_statement,
    "GST-02": _lut,
    "PORT-01": _port,
    "DST-01": _destination,
    "DATE-01": _dates,
    "DOC-02": _blank_fields,
}
