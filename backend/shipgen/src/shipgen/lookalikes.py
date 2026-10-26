"""Look-alike non-errors: differences real documents show that no rule may report.

Each changes how a value is written, never what it means: a spaced GSTIN, a description in
capitals, a weight rounded within tolerance. Their labels name no rule, so any finding on them is
a false positive.
"""

import random
from decimal import ROUND_HALF_UP, Decimal

from shipgen.mutations import Edit, FieldPath, Mutation, get_at, transport_document
from shipgen.oracle import weight_tolerance_pct
from shipready.documents.models import ShipmentDocuments


def _description_capitals(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    i = rng.randrange(len(documents.packing_list.lines))
    description = documents.packing_list.lines[i].description
    if description.upper() == description:
        return None
    return [(("packing_list", "lines", i, "description"), description.upper())]


def _company_suffix_expanded(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    name = documents.certificate_of_origin.exporter.name
    if "Pvt Ltd" not in name:
        return None
    expanded = name.replace("Pvt Ltd", "Private Limited")
    return [(("certificate_of_origin", "exporter", "name"), expanded)]


def _address_capitals(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    path: FieldPath = ("certificate_of_origin", "consignee", "address", "lines")
    lines = get_at(documents, path)
    upper = tuple(line.upper() for line in lines)
    return None if upper == lines else [(path, upper)]


def _gross_weight_rounded(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    """The carrier's document rounds the gross weight to whole kilograms, within WT-01's
    tolerance."""
    path: FieldPath = (transport_document(documents), "gross_weight_kg")
    weight: Decimal = get_at(documents, path)
    rounded = weight.quantize(Decimal(1), ROUND_HALF_UP)
    if rounded == weight or abs(rounded - weight) * 100 > weight * weight_tolerance_pct():
        return None
    return [(path, rounded)]


def _gstin_spaced(documents: ShipmentDocuments, rng: random.Random) -> list[Edit]:
    gstin = documents.shipping_bill.gstin
    return [(("shipping_bill", "gstin"), f"{gstin[:2]} {gstin[2:12]} {gstin[12:]}")]


def _container_spaced(documents: ShipmentDocuments, rng: random.Random) -> list[Edit] | None:
    bill = documents.bill_of_lading
    if bill is None or not bill.containers:
        return None
    k = rng.randrange(len(bill.containers))
    number = bill.containers[k].number
    spaced = f"{number[:4]} {number[4:10]} {number[10]}"
    return [(("bill_of_lading", "containers", k, "number"), spaced)]


LOOKALIKES = (
    Mutation("description_in_capitals", (), _description_capitals),
    Mutation("company_suffix_expanded", (), _company_suffix_expanded),
    Mutation("address_in_capitals", (), _address_capitals),
    Mutation("gross_weight_rounded", (), _gross_weight_rounded),
    Mutation("gstin_spaced", (), _gstin_spaced),
    Mutation("container_number_spaced", (), _container_spaced),
)
