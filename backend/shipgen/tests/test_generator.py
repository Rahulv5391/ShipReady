from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shipgen.consistency import check_shipment
from shipgen.documents import build_documents
from shipgen.generator import (
    container_plan,
    financial_year,
    generate_shipment,
    rate_on,
)
from shipgen.models import Shipment


def find_shipment(predicate: Callable[[Shipment], bool]) -> Shipment:
    for index in range(500):
        shipment = generate_shipment(1, index)
        if predicate(shipment):
            return shipment
    raise AssertionError("no generated shipment matched")


def test_same_seed_and_index_give_the_same_shipment() -> None:
    assert generate_shipment(42, 7) == generate_shipment(42, 7)
    assert generate_shipment(42, 7).model_dump_json() == generate_shipment(42, 7).model_dump_json()


def test_different_index_or_seed_gives_a_different_shipment() -> None:
    assert generate_shipment(42, 7) != generate_shipment(42, 8)
    assert generate_shipment(42, 7) != generate_shipment(43, 7)
    assert generate_shipment(42, 7).shipment_id == "SG42-0007"


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=10**6), st.integers(min_value=0, max_value=9999))
def test_every_generated_shipment_is_consistent(seed: int, index: int) -> None:
    shipment = generate_shipment(seed, index)
    assert check_shipment(shipment) == []
    build_documents(shipment)


def test_generator_covers_sea_air_and_to_order() -> None:
    air = find_shipment(lambda s: s.transport.mode == "air")
    assert air.transport.containers == ()
    assert air.lines[0].hs_code.startswith("3004")  # only pharma goes by air
    to_order = find_shipment(lambda s: s.to_order)
    assert to_order.notify_party == to_order.consignee
    multi = find_shipment(lambda s: len(s.transport.containers) > 1)
    assert {container.size for container in multi.transport.containers} == {"40GP"}


def test_non_usd_shipments_are_converted_through_inr() -> None:
    shipment = find_shipment(lambda s: s.currency == "EUR")
    assert shipment.exchange_rate == rate_on("EUR", shipment.shipping_bill_date)["rate_inr"]


@pytest.mark.parametrize(
    ("day", "notification"),
    [
        (date(2026, 9, 18), "27/2026"),
        (date(2026, 10, 1), "27/2026"),
        (date(2026, 10, 2), "28/2026"),
        (date(2026, 12, 31), "29/2026"),
    ],
)
def test_rate_on_picks_the_notification_in_force(day: date, notification: str) -> None:
    assert rate_on("USD", day)["notification"] == notification


def test_rate_on_fails_before_the_first_notification() -> None:
    with pytest.raises(ValueError, match="no CBIC exchange rate for USD on 2026-09-17"):
        rate_on("USD", date(2026, 9, 17))


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 4, 1), "2026-27"), (date(2027, 3, 31), "2026-27"), (date(2026, 3, 31), "2025-26")],
)
def test_financial_year_runs_april_to_march(day: date, expected: str) -> None:
    assert financial_year(day) == expected


@pytest.mark.parametrize(
    ("volume", "weight", "plan"),
    [
        ("10", "5000", ["20GP"]),
        ("28", "21000", ["20GP"]),
        ("29", "5000", ["40GP"]),
        ("120", "5000", ["40GP", "40GP", "40GP"]),
        ("10", "60000", ["40GP", "40GP", "40GP"]),  # heavy cargo such as granite
    ],
)
def test_container_plan_fits_volume_and_weight(volume: str, weight: str, plan: list[str]) -> None:
    assert container_plan(Decimal(volume), Decimal(weight)) == plan
