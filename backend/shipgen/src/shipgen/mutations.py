"""Labelled errors injected into a golden shipment's documents, each mapped to the rules that must
catch it.

A mutation changes what one or more documents show, the way a typo, a stale copy or a wrong
lookup would, and returns a label with the rules and every changed field. Each mutation is
designed so that only its labelled rules are broken; where one error unavoidably breaks two rules
(a container missing from the shipping bill also changes its container numbers), both are named.
The golden shipment itself never changes: it stays the truth the documents are compared against.
"""

import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from typing import Any

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from shipgen import profiles
from shipgen.generator import rate_on
from shipgen.products import load_products
from shipgen.reference import load_exchange_rates, load_itc_hs, load_ports
from shipready.documents.models import Model, ShipmentDocuments
from shipready.normalise.identifiers import gstin_check_char

CENTS = Decimal("0.01")
FieldPath = tuple[str | int, ...]  # e.g. ("packing_list", "lines", 0, "quantity")
Edit = tuple[FieldPath, Any]  # a field to change and its new value
# Returns the edits, or None when the mutation does not apply (e.g. seals on an air shipment).
Choose = Callable[[ShipmentDocuments, random.Random], list[Edit] | None]


class Change(Model):
    document: str  # a ShipmentDocuments field, e.g. "packing_list"
    field: str  # path inside the document, e.g. "lines[0].quantity"; "" for the whole document
    original: JsonValue
    mutated: JsonValue


class Label(Model):
    mutation: str
    rule_ids: tuple[str, ...]  # empty for a look-alike: no rule may fire
    changes: tuple[Change, ...]


@dataclass(frozen=True)
class Mutation:
    name: str
    rule_ids: tuple[str, ...]
    choose: Choose


def apply(
    mutation: Mutation, documents: ShipmentDocuments, rng: random.Random
) -> tuple[ShipmentDocuments, Label] | None:
    """The mutated documents and their label, or None if the mutation does not apply."""
    edits = mutation.choose(documents, rng)
    if edits is None:
        return None
    changes = []
    for path, value in edits:
        original = get_at(documents, path)
        if value == original:
            raise ValueError(f"{mutation.name} left {format_path(path)} unchanged")
        changes.append(
            Change(
                document=str(path[0]),
                field=format_path(path[1:]),
                original=to_jsonable_python(original),
                mutated=to_jsonable_python(value),
            )
        )
        documents = replace_at(documents, path, value)
    label = Label(mutation=mutation.name, rule_ids=mutation.rule_ids, changes=tuple(changes))
    return documents, label


def get_at(node: Any, path: FieldPath) -> Any:
    for step in path:
        node = node[step] if isinstance(step, int) else getattr(node, step)
    return node


def replace_at(node: Any, path: FieldPath, value: Any) -> Any:
    """A copy of `node` with the field at `path` set to `value`; the models are frozen."""
    if not path:
        return value
    step, rest = path[0], path[1:]
    if isinstance(step, int):
        return (*node[:step], replace_at(node[step], rest, value), *node[step + 1 :])
    return node.model_copy(update={step: replace_at(getattr(node, step), rest, value)})


def format_path(path: FieldPath) -> str:
    text = ""
    for step in path:
        text += f"[{step}]" if isinstance(step, int) else f".{step}"
    return text.lstrip(".")


def nudge(value: Decimal, rng: random.Random, low: float, high: float) -> Decimal:
    """`value` moved up or down by a fraction between `low` and `high`, keeping its decimal
    places. It always changes by at least one step in the last place and stays positive."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or value <= 0:
        raise ValueError(f"expected a positive finite decimal, got {value}")
    step = Decimal(1).scaleb(exponent)
    fraction = Decimal(str(round(rng.uniform(low, high), 4)))
    delta = max((value * fraction).quantize(step, ROUND_HALF_UP), step)
    down = rng.random() < 0.5 and delta < value
    return value - delta if down else value + delta


def change_digit(text: str, rng: random.Random) -> str:
    """`text` with one of its digits replaced by a different digit, as a mistyped copy."""
    positions = [i for i, char in enumerate(text) if char.isdigit()]
    if not positions:
        raise ValueError(f"no digit to change in {text!r}")
    i = rng.choice(positions)
    digit = rng.choice([d for d in "0123456789" if d != text[i]])
    return text[:i] + digit + text[i + 1 :]


def transport_document(documents: ShipmentDocuments) -> str:
    return "bill_of_lading" if documents.bill_of_lading is not None else "air_waybill"


def _line(documents: ShipmentDocuments, rng: random.Random) -> int:
    return rng.randrange(len(documents.commercial_invoice.lines))


def _number_in_address(document: str, party: str) -> Choose:
    """The street or flat number in a party's first address line, mistyped."""

    def choose(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
        path: FieldPath = (document, party, "address", "lines", 0)
        line = get_at(documents, path)
        return [(path, change_digit(line, rng))] if re.search(r"\d", line) else None

    return choose


# --- Quantities and values ---


def _packing_quantity(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    i = _line(documents, rng)
    quantity = documents.packing_list.lines[i].quantity
    return [(("packing_list", "lines", i, "quantity"), nudge(quantity, rng, 0.02, 0.10))]


def _shipping_bill_quantity(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    i = _line(documents, rng)
    quantity = documents.shipping_bill.lines[i].quantity
    return [(("shipping_bill", "lines", i, "quantity"), nudge(quantity, rng, 0.02, 0.10))]


def _purchase_order_line(
    documents: ShipmentDocuments, i: int, quantity: Decimal, unit_price: Decimal
) -> list[Edit]:
    """A changed purchase order line with its amount and total kept consistent, so only the
    comparison with the invoice is wrong."""
    order = documents.purchase_order
    line = order.lines[i]
    amount = (quantity * unit_price).quantize(CENTS, ROUND_HALF_UP)
    edits: list[Edit] = []
    if quantity != line.quantity:
        edits.append((("purchase_order", "lines", i, "quantity"), quantity))
    if unit_price != line.unit_price:
        edits.append((("purchase_order", "lines", i, "unit_price"), unit_price))
    if amount != line.amount:
        edits.append((("purchase_order", "lines", i, "amount"), amount))
        edits.append((("purchase_order", "total"), order.total - line.amount + amount))
    return edits


def _order_quantity(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    i = _line(documents, rng)
    line = documents.purchase_order.lines[i]
    quantity = nudge(line.quantity, rng, 0.05, 0.20)
    return _purchase_order_line(documents, i, quantity, line.unit_price)


def _order_unit_price(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    i = _line(documents, rng)
    line = documents.purchase_order.lines[i]
    unit_price = nudge(line.unit_price, rng, 0.03, 0.15)
    return _purchase_order_line(documents, i, line.quantity, unit_price)


def _invoice_line_amount(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    i = _line(documents, rng)
    amount = documents.commercial_invoice.lines[i].amount
    return [(("commercial_invoice", "lines", i, "amount"), nudge(amount, rng, 0.01, 0.10))]


def _shipping_bill_invoice_value(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    value = documents.shipping_bill.invoice_value
    return [(("shipping_bill", "invoice_value"), nudge(value, rng, 0.005, 0.05))]


def _stale_exchange_rate(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    """The rate of another notification, used on both the invoice and the shipping bill, with
    the INR values worked out from it: the exporter looked up the wrong fortnight."""
    invoice, bill = documents.commercial_invoice, documents.shipping_bill
    in_force = rate_on(invoice.currency, bill.shipping_bill_date)
    others = [
        rate
        for rate in load_exchange_rates()
        if rate["currency"] == invoice.currency
        and rate["unit"] == in_force["unit"]
        and rate["rate_inr"] != in_force["rate_inr"]
    ]
    if not others:
        return None
    rate = rng.choice(others)["rate_inr"]
    unit = in_force["unit"]
    return [
        (("commercial_invoice", "exchange_rate"), rate),
        (("commercial_invoice", "total_inr"), _to_inr(invoice.total, rate, unit)),
        (("shipping_bill", "exchange_rate"), rate),
        (("shipping_bill", "fob_inr"), _to_inr(bill.fob_value, rate, unit)),
    ]


def _to_inr(value: Decimal, rate: Decimal, unit: int) -> Decimal:
    return (value * rate / unit).quantize(CENTS, ROUND_HALF_UP)


# --- Shipping and packing ---


def _freight_terms(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    document = transport_document(documents)
    terms = get_at(documents, (document, "freight_terms"))
    return [((document, "freight_terms"), "collect" if terms == "prepaid" else "prepaid")]


def _package_count(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    count = documents.shipping_bill.total_packages
    off = rng.choice((-1, 1)) if count > 1 else 1
    return [(("shipping_bill", "total_packages"), count + off)]


def _transport_gross_weight(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    # Well beyond WT-01's tolerance (0.5%).
    path: FieldPath = (transport_document(documents), "gross_weight_kg")
    return [(path, nudge(get_at(documents, path), rng, 0.015, 0.05))]


def _net_weight_total(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    net = documents.packing_list.net_weight_kg
    return [(("packing_list", "net_weight_kg"), nudge(net, rng, 0.02, 0.08))]


def _container(documents: ShipmentDocuments, rng: random.Random, field: str) -> list[Edit] | None:
    bill = documents.bill_of_lading
    if bill is None or not bill.containers:
        return None
    k = rng.randrange(len(bill.containers))
    path: FieldPath = ("bill_of_lading", "containers", k, field)
    value = get_at(documents, path)
    if field == "number":
        # Only the check digit changes, so the owner code and serial still match.
        return [(path, value[:10] + change_digit(value[10], rng))]
    return [(path, change_digit(value, rng))]


def _container_check_digit(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    return _container(documents, rng, "number")


def _seal(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    return _container(documents, rng, "seal")


def _container_dropped(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    containers = documents.shipping_bill.containers
    if len(containers) < 2:
        return None
    k = rng.randrange(len(containers))
    return [(("shipping_bill", "containers"), containers[:k] + containers[k + 1 :])]


def _marks(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    bill = documents.bill_of_lading
    if bill is None:
        return None
    return [(("bill_of_lading", "marks"), change_digit(bill.marks, rng))]


def _port_code(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    code = documents.shipping_bill.port_code
    ports = load_ports()
    kind = next(port["kind"] for port in ports if port["code"] == code)
    others = [p["code"] for p in ports if p["country"] == "IN" and p["kind"] == kind]
    return [(("shipping_bill", "port_code"), rng.choice([c for c in others if c != code]))]


def _destination(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    current = documents.certificate_of_origin.destination_country
    country = rng.choice([c for c in sorted(profiles.DESTINATIONS) if c != current])
    return [(("certificate_of_origin", "destination_country"), country)]


def _shipped_before_invoice(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    document = transport_document(documents)
    field = "shipped_on_board" if document == "bill_of_lading" else "flight_date"
    day = documents.commercial_invoice.invoice_date - timedelta(rng.randint(1, 5))
    return [((document, field), day)]


# --- Goods and policy ---


def _hs_truncated(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    """A 6-digit HS code, written the same on every document (so only HS-01 fails)."""
    i = _line(documents, rng)
    code = documents.commercial_invoice.lines[i].hs_code[:6]
    return [
        ((document, "lines", i, "hs_code"), code)
        for document in ("commercial_invoice", "shipping_bill", "certificate_of_origin")
    ]


def _hs_swapped(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    """The shipping bill gives a line the HS code of another line."""
    lines = documents.shipping_bill.lines
    pairs = [
        (i, j)
        for i in range(len(lines))
        for j in range(len(lines))
        if lines[i].hs_code != lines[j].hs_code
    ]
    if not pairs:
        return None
    i, j = rng.choice(pairs)
    return [(("shipping_bill", "lines", i, "hs_code"), lines[j].hs_code)]


def _restricted_goods(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    """A line classified under a code that is not Free, on every document. The description
    still names the original goods, so HS-03 (plausibility) is labelled too."""
    i = _line(documents, rng)
    code = rng.choice(_restricted_codes())
    return [
        ((document, "lines", i, "hs_code"), code)
        for document in ("commercial_invoice", "shipping_bill", "certificate_of_origin")
    ]


@cache
def _restricted_codes() -> tuple[str, ...]:
    codes = tuple(code for code, row in load_itc_hs().items() if row["export_policy"] != "Free")
    if not codes:
        raise ValueError("ShipGen's ITC(HS) snapshot has no code that is not Free")
    return codes


def _transport_description(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    document = transport_document(documents)
    current = get_at(documents, (document, "goods_description"))
    others = sorted({p.description for p in load_products()} - set(current.split("; ")))
    return [((document, "goods_description"), rng.choice(others))]


def _packing_unit(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    """A valid unit that cannot be converted to the invoice unit, so QTY-01 cannot compare
    the quantities and only UQC-01 fails."""
    i = _line(documents, rng)
    uqc = documents.packing_list.lines[i].uqc
    return [(("packing_list", "lines", i, "uqc"), "NOS" if uqc in _MASS_UNITS else "KGS")]


_MASS_UNITS = {"KGS", "GMS", "QTL", "MTS", "TON"}


# --- Parties and identifiers ---


def _gstin_checksum(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    """A GSTIN with the wrong check character, copied onto every document."""
    gstin = documents.commercial_invoice.gstin
    wrong = rng.choice([c for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c != gstin[14]])
    return [
        ((document, "gstin"), gstin[:14] + wrong)
        for document in ("commercial_invoice", "shipping_bill", "lut")
    ]


def _gstin_other_state(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    """The exporter's registration in another state on the shipping bill: a valid GSTIN with
    the same PAN, so only ID-02 fails."""
    gstin = documents.shipping_bill.gstin
    states = [s.gst_code for s in profiles.EXPORTER_STATES if s.gst_code != gstin[:2]]
    first14 = rng.choice(states) + gstin[2:14]
    return [(("shipping_bill", "gstin"), first14 + gstin_check_char(first14))]


def _ad_code(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    return [(("shipping_bill", "ad_code"), change_digit(documents.shipping_bill.ad_code, rng))]


def _notify_party_missing(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    bill = documents.bill_of_lading
    if bill is None or not bill.to_order:
        return None
    return [(("bill_of_lading", "notify_party"), None)]


def _invoice_number(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    number = documents.shipping_bill.invoice_number
    return [(("shipping_bill", "invoice_number"), change_digit(number, rng))]


def _invoice_date(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    day = documents.shipping_bill.invoice_date - timedelta(rng.randint(1, 3))
    return [(("shipping_bill", "invoice_date"), day)]


def _lut_declaration(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    return [(("commercial_invoice", "gst_declaration"), "")]


def _lut_arn(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    arn = documents.commercial_invoice.lut_arn
    return [(("commercial_invoice", "lut_arn"), change_digit(arn, rng))]


# Fields no other rule compares, so blanking one breaks only DOC-02.
_MANDATORY_FIELDS: tuple[FieldPath, ...] = (
    ("commercial_invoice", "payment_terms"),
    ("commercial_invoice", "bank_name"),
    ("shipping_bill", "shipping_bill_number"),
    ("certificate_of_origin", "certificate_number"),
)


def _blank_field(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    return [(rng.choice(_MANDATORY_FIELDS), "")]


# The documents every export shipment needs. Leaving one out is a DOC-01 finding; it is taken
# out of the bundle of files (shipgen.bundle), while the case keeps its values as the truth.
MISSING_DOCUMENT = "document_missing"


def missing_document(documents: ShipmentDocuments, rng: random.Random) -> Label:
    required = (
        "commercial_invoice",
        "packing_list",
        "shipping_bill",
        transport_document(documents),
    )
    change = Change(document=rng.choice(required), field="", original="present", mutated="missing")
    return Label(mutation=MISSING_DOCUMENT, rule_ids=("DOC-01",), changes=(change,))


def missing_documents(labels: tuple[Label, ...]) -> set[str]:
    return {
        change.document
        for label in labels
        if label.mutation == MISSING_DOCUMENT
        for change in label.changes
    }


MUTATIONS = (
    Mutation("qty_mismatch_packing_list", ("QTY-01",), _packing_quantity),
    Mutation("qty_mismatch_shipping_bill", ("QTY-02",), _shipping_bill_quantity),
    Mutation("qty_differs_from_order", ("QTY-03",), _order_quantity),
    Mutation("invoice_line_arithmetic", ("VAL-01",), _invoice_line_amount),
    Mutation("invoice_value_mismatch_sb", ("VAL-02",), _shipping_bill_invoice_value),
    Mutation("unit_price_differs_from_order", ("VAL-03",), _order_unit_price),
    Mutation("fx_rate_wrong_notification", ("FX-01",), _stale_exchange_rate),
    Mutation("freight_terms_contradict_incoterm", ("INC-01",), _freight_terms),
    Mutation("pkg_count_off_by_one", ("PKG-01",), _package_count),
    Mutation("gross_weight_drift", ("WT-01",), _transport_gross_weight),
    Mutation("net_weight_total_wrong", ("WT-02",), _net_weight_total),
    Mutation("container_check_digit", ("CNT-01",), _container_check_digit),
    Mutation("container_missing_on_sb", ("CNT-02", "CNT-01"), _container_dropped),
    Mutation("seal_mismatch", ("CNT-03",), _seal),
    Mutation("marks_mismatch", ("MRK-01",), _marks),
    Mutation("hs_truncated_6", ("HS-01",), _hs_truncated),
    Mutation("hs_swap_between_docs", ("HS-02",), _hs_swapped),
    Mutation("restricted_item", ("POL-01", "HS-03"), _restricted_goods),
    Mutation("description_differs_on_transport_doc", ("DESC-01",), _transport_description),
    Mutation("unit_differs_on_packing_list", ("UQC-01",), _packing_unit),
    Mutation("gstin_checksum_typo", ("ID-01",), _gstin_checksum),
    Mutation("gstin_other_state_on_sb", ("ID-02",), _gstin_other_state),
    Mutation("ad_code_mismatch_sb", ("ID-03",), _ad_code),
    Mutation(
        "exporter_address_differs_pl", ("PTY-01",), _number_in_address("packing_list", "exporter")
    ),
    Mutation(
        "consignee_address_differs_coo",
        ("PTY-02",),
        _number_in_address("certificate_of_origin", "consignee"),
    ),
    Mutation("notify_party_missing", ("PTY-03",), _notify_party_missing),
    Mutation("invoice_no_series_diff", ("INV-01",), _invoice_number),
    Mutation("invoice_date_differs_sb", ("INV-01",), _invoice_date),
    Mutation("lut_statement_missing", ("GST-01",), _lut_declaration),
    Mutation("lut_arn_mismatch", ("GST-02",), _lut_arn),
    Mutation("port_code_mismatch_sb", ("PORT-01",), _port_code),
    Mutation("destination_differs_coo", ("DST-01",), _destination),
    Mutation("shipped_before_invoice", ("DATE-01",), _shipped_before_invoice),
    Mutation("mandatory_field_blank", ("DOC-02",), _blank_field),
)
