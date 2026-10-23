from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from shipgen.consistency import check_shipment
from shipgen.generator import generate_shipment
from shipgen.models import Shipment


def sea_cif() -> Shipment:
    for index in range(500):
        shipment = generate_shipment(5, index)
        if shipment.transport.mode == "sea" and shipment.incoterm == "CIF":
            return shipment
    raise AssertionError("no sea CIF shipment generated")


def air() -> Shipment:
    for index in range(500):
        shipment = generate_shipment(5, index)
        if shipment.transport.mode == "air":
            return shipment
    raise AssertionError("no air shipment generated")


def change(shipment: Shipment, **fields: Any) -> Shipment:
    return shipment.model_copy(update=fields)


def change_line(shipment: Shipment, **fields: Any) -> Shipment:
    lines = (shipment.lines[0].model_copy(update=fields), *shipment.lines[1:])
    return change(shipment, lines=lines)


def change_exporter(shipment: Shipment, **fields: Any) -> Shipment:
    return change(shipment, exporter=shipment.exporter.model_copy(update=fields))


def change_transport(shipment: Shipment, **fields: Any) -> Shipment:
    return change(shipment, transport=shipment.transport.model_copy(update=fields))


Mutation = Callable[[Shipment], Shipment]

MUTATIONS: list[tuple[Mutation, str]] = [
    (lambda s: change_exporter(s, gstin=s.exporter.gstin[:-1] + "0"), "invalid GSTIN"),
    (lambda s: change_exporter(s, pan="ZZZPZ9999Z", iec="ZZZPZ9999Z"), "PAN inside GSTIN"),
    (lambda s: change_exporter(s, iec="0123456789"), "is not the exporter PAN"),
    (lambda s: change_exporter(s, ad_code="123"), "invalid AD code"),
    (lambda s: change(s, lut=s.lut.model_copy(update={"arn": "LUT123"})), "not in GST ARN format"),
    (lambda s: change(s, invoice_number="EXPORT/2026-27/000123"), "longer than 16"),
    (lambda s: change_line(s, hs_code="17019990"), "missing or not Free"),
    (lambda s: change_line(s, uqc="SET"), "differs from ITC-HS"),
    (lambda s: change_line(s, amount=s.lines[0].amount + 1), "amount is not quantity x unit price"),
    (lambda s: change(s, goods_value=s.goods_value + 1), "do not sum to goods value"),
    (lambda s: change(s, invoice_total=s.invoice_total + 1), "not goods + freight + insurance"),
    (
        lambda s: change(s, freight=Decimal(0), invoice_total=s.invoice_total - s.freight),
        "freight charged",
    ),
    (lambda s: change(s, exchange_rate=s.exchange_rate + 1), "not the CBIC rate"),
    (lambda s: change(s, fob_inr=s.fob_inr + 1), "FOB in INR"),
    (lambda s: change_line(s, net_weight_kg=s.lines[0].gross_weight_kg + 1), "net weight exceeds"),
    (lambda s: change(s, total_packages=s.total_packages + 1), "line packages do not sum"),
    (lambda s: change(s, marks="NO MARKS"), "marks do not number"),
    (lambda s: change(s, destination_country="ZA"), "country differ"),
    (lambda s: change(s, freight_terms="collect"), "freight terms collect"),
    (lambda s: change(s, to_order=True, notify_party=None), "without a notify party"),
    (
        lambda s: change_transport(
            s,
            containers=(
                s.transport.containers[0].model_copy(update={"number": "CSQU3054384"}),
                *s.transport.containers[1:],
            ),
        ),
        "invalid container number",
    ),
    (lambda s: change(s, po_date=s.invoice_date + timedelta(1)), "PO date is after invoice date"),
    (lambda s: change(s, coo_date=s.invoice_date - timedelta(1)), "certificate of origin"),
    (
        lambda s: change(s, lut=s.lut.model_copy(update={"financial_year": "2025-26"})),
        "LUT does not cover",
    ),
]


def test_golden_shipment_has_no_problems() -> None:
    assert check_shipment(sea_cif()) == []
    assert check_shipment(air()) == []


@pytest.mark.parametrize(("mutate", "message"), MUTATIONS)
def test_each_broken_invariant_is_reported(mutate: Mutation, message: str) -> None:
    problems = check_shipment(mutate(sea_cif()))
    assert any(message in problem for problem in problems), problems


def test_air_specific_invariants() -> None:
    shipment = air()
    reference = shipment.transport.carrier_reference
    wrong_digit = reference[:-1] + str((int(reference[-1]) + 1) % 7)
    assert "airway bill check digit is wrong" in check_shipment(
        change_transport(shipment, carrier_reference=wrong_digit)
    )
    assert any(
        "not in 123-12345678 format" in problem
        for problem in check_shipment(change_transport(shipment, carrier_reference="SGL123"))
    )
    assert any(
        "to-order" in problem
        for problem in check_shipment(
            change(shipment, to_order=True, notify_party=shipment.consignee)
        )
    )
