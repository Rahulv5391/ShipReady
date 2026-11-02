"""Packages, weights, containers, marks, ports, destination and dates (PKG, WT, CNT, MRK, PORT,
DST, DATE)."""

import re
from decimal import Decimal
from typing import Any

from shipready.checks.fields import (
    Fields,
    NotVerified,
    first_problem,
    same_text,
    transport_document,
)
from shipready.checks.reference import Reference
from shipready.normalise.containers import is_valid_container
from shipready.normalise.identifiers import clean

# Documents that list the containers of a sea shipment.
CONTAINER_DOCUMENTS = ("packing_list", "bill_of_lading", "shipping_bill")


def _differ(values: dict[str, object]) -> str | None:
    """A problem naming each document's value, when they are not all equal."""
    if len(set(values.values())) > 1:
        return ", ".join(f"{document} {value}" for document, value in values.items())
    return None


def _packages(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    documents = ("packing_list", "shipping_bill", transport_document(fields))
    return _differ({d: fields.number(f"{d}.total_packages") for d in documents})


def _gross_weight(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    tolerance = Decimal(str(params["gross_weight_tolerance_pct"]))
    document = transport_document(fields)
    packing = fields.number("packing_list.gross_weight_kg")
    carried = fields.number(f"{document}.gross_weight_kg")
    if abs(packing - carried) * 100 > packing * tolerance:
        return f"packing list {packing} kg, {document} {carried} kg (more than {tolerance}% apart)"
    return None


def _weights_add_up(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    count = fields.count("packing_list.lines")
    if count == 0:
        raise NotVerified("no packing list lines found")

    def net_within_gross() -> str | None:
        net = fields.number("packing_list.net_weight_kg")
        gross = fields.number("packing_list.gross_weight_kg")
        return f"net weight {net} kg exceeds gross weight {gross} kg" if net > gross else None

    def total(kind: str) -> str | None:
        lines = sum(fields.number(f"packing_list.lines[{i}].{kind}") for i in range(count))
        stated = fields.number(f"packing_list.{kind}")
        name = kind.removesuffix("_kg").replace("_", " ")
        return f"lines' {name} add up to {lines} kg, not {stated} kg" if lines != stated else None

    return first_problem(
        [net_within_gross, lambda: total("net_weight_kg"), lambda: total("gross_weight_kg")]
    )


def _container_lists(
    fields: Fields, field: str, documents: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    """Each document's containers' `field` (number or seal), cleaned and sorted. An airway bill
    shipment has none; a sea document that shows none cannot be checked."""
    if transport_document(fields) != "bill_of_lading":
        return {}
    lists = {}
    for document in documents:
        count = fields.count(f"{document}.containers")
        if count == 0:
            raise NotVerified(f"no containers found on {document}")
        lists[document] = tuple(
            sorted(clean(fields.text(f"{document}.containers[{i}].{field}")) for i in range(count))
        )
    return lists


def _container_numbers(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    lists = _container_lists(fields, "number", CONTAINER_DOCUMENTS)
    invalid = sorted(
        {n for numbers in lists.values() for n in numbers if not is_valid_container(n)}
    )
    if invalid:
        return f"not valid container numbers: {', '.join(invalid)}"
    return _differ({d: ", ".join(numbers) for d, numbers in lists.items()})


def _container_count(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    lists = _container_lists(fields, "number", CONTAINER_DOCUMENTS)
    return _differ({d: len(numbers) for d, numbers in lists.items()})


def _seals(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    lists = _container_lists(fields, "seal", ("packing_list", "bill_of_lading"))
    return _differ({d: ", ".join(seals) for d, seals in lists.items()})


def _marks(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    if transport_document(fields) != "bill_of_lading":
        return None  # an airway bill carries no marks
    packing, bill = fields.text("packing_list.marks"), fields.text("bill_of_lading.marks")
    return (
        f"packing list {packing!r}, bill of lading {bill!r}"
        if not same_text(packing, bill)
        else None
    )


def _departure(fields: Fields) -> str:
    document = transport_document(fields)
    port = "port_of_loading" if document == "bill_of_lading" else "airport_of_departure"
    return f"{document}.{port}"


def _destination(fields: Fields) -> str:
    document = transport_document(fields)
    port = "port_of_discharge" if document == "bill_of_lading" else "airport_of_destination"
    return f"{document}.{port}"


def _port_of_loading(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    code = clean(fields.text("commercial_invoice.port_of_loading.code"))

    def indian() -> str | None:
        known = reference.indian_port(code)
        if known is None:
            raise NotVerified("no list of Indian ports in our data")
        if not known:
            raise NotVerified(f"{code} is not in our list of Indian customs ports")
        return None

    def same() -> str | None:
        return _differ(
            {
                "commercial_invoice": code,
                "shipping_bill": clean(fields.text("shipping_bill.port_code")),
                _departure(fields).split(".")[0]: clean(fields.text(f"{_departure(fields)}.code")),
            }
        )

    return first_problem([indian, same])


def port_country(fields: Fields, port: str) -> str:
    """The port's country as printed, or else from its code: a UN/LOCODE, and an Indian
    customs code, starts with the country's ISO code (NLRTM, INNSA1)."""
    printed = fields.optional(f"{port}.country")
    if printed is not None:
        return printed.upper()
    code = clean(fields.text(f"{port}.code"))
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3,4}", code):
        raise NotVerified(f"{port} has no country, and its code {code!r} does not give one")
    return code[:2]


def _destination_country(
    fields: Fields, reference: Reference, params: dict[str, Any]
) -> str | None:
    return _differ(
        {
            "commercial_invoice": fields.text("commercial_invoice.destination_country").upper(),
            "certificate_of_origin": fields.text(
                "certificate_of_origin.destination_country"
            ).upper(),
            _destination(fields).split(".")[0]: port_country(fields, _destination(fields)),
        }
    )


def _dates(fields: Fields, reference: Reference, params: dict[str, Any]) -> str | None:
    document = transport_document(fields)
    shipped_on = "shipped_on_board" if document == "bill_of_lading" else "flight_date"
    shipped = fields.day(f"{document}.{shipped_on}")
    invoiced = fields.day("commercial_invoice.invoice_date")

    def order_first() -> str | None:
        ordered = fields.day("purchase_order.po_date")
        return (
            f"invoice dated {invoiced}, before the order ({ordered})"
            if invoiced < ordered
            else None
        )

    def invoice_before_shipping() -> str | None:
        return f"shipped {shipped}, before the invoice ({invoiced})" if shipped < invoiced else None

    def certificate_before_shipping() -> str | None:
        certified = fields.day("certificate_of_origin.certificate_date")
        return (
            f"certificate dated {certified}, after shipping ({shipped})"
            if certified > shipped
            else None
        )

    return first_problem([order_first, invoice_before_shipping, certificate_before_shipping])


CHECKS = {
    "PKG-01": _packages,
    "WT-01": _gross_weight,
    "WT-02": _weights_add_up,
    "CNT-01": _container_numbers,
    "CNT-02": _container_count,
    "CNT-03": _seals,
    "MRK-01": _marks,
    "PORT-01": _port_of_loading,
    "DST-01": _destination_country,
    "DATE-01": _dates,
}
