import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from shipready.reference.exchange_rates import parse_exchange_rates
from shipready.reference.files import ReferenceDataError

CURRENCIES = {"USD", "EUR", "JPY"}


def rate(code: str = "USD", export: Any = 94.2, units: str = "1.0") -> dict[str, Any]:
    return {"currencyCode": code, "cbicImport": 96.0, "cbicExport": export, "units": units}


PADDING = [
    {"currencyCode": "EUR", "cbicImport": 108.5, "cbicExport": 104.85, "units": "1.0"},
    {"currencyCode": "JPY", "cbicImport": 61.2, "cbicExport": 59.35, "units": "100.0"},
]


def payload(
    published: str = "15-10-2026", in_force: str = "16-10-2026", rates: list[Any] | None = None
) -> bytes:
    return json.dumps(
        {
            "notifications": [{"notificationNumber": "29/2026", "notPublishDate": published}],
            "details": {
                "29/2026": {
                    "notificationNumber": "29/2026",
                    "notPublishDate": in_force,
                    "status": 1,
                    # EUR and JPY pad every notification to the (lowered) minimum of three.
                    "currencyDetail": [*(rates if rates is not None else [rate()]), *PADDING],
                }
            },
        }
    ).encode()


@pytest.mark.usefixtures("small_minimums")
def test_parses_icegate_notifications(reference_file: Callable[[str], bytes]) -> None:
    rows = parse_exchange_rates("rates", reference_file("icegate-exchange-rates.json"), CURRENCIES)
    by_key = {(row["currency"], row["valid_from"]): row for row in rows}
    assert by_key[("USD", date(2026, 10, 16))] == {
        "currency": "USD",
        "unit": 1,
        "rate_inr": Decimal("94.2"),
        "notification": "29/2026",
        "valid_from": date(2026, 10, 16),
        "published_on": date(2026, 10, 15),
    }
    assert by_key[("JPY", date(2026, 10, 2))]["unit"] == 100
    assert by_key[("EUR", date(2026, 10, 2))]["rate_inr"] == Decimal("106.8")
    assert len(rows) == 6


@pytest.mark.usefixtures("small_minimums")
def test_rates_stay_exact_decimals() -> None:
    rows = parse_exchange_rates("rates", payload(rates=[rate(export=0.1)]), CURRENCIES)
    (row,) = [row for row in rows if row["currency"] == "USD"]
    # 0.1 would be 0.1000000000000000055... had it passed through float.
    assert row["rate_inr"] == Decimal("0.1")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"[]", "rates: expected 'notifications' and 'details'"),
        (json.dumps({"notifications": []}).encode(), "missing notification details"),
        (
            json.dumps(
                {"notifications": [{"notificationNumber": "1/2026"}], "details": {}}
            ).encode(),
            "rates:1: no details for notification '1/2026'",
        ),
        (payload(published="2026-10-15"), "expected a DD-MM-YYYY date"),
        (payload(in_force="14-10-2026"), "29/2026 is in force before it was published"),
        (payload(rates=[]), "29/2026 has too few rates"),
        (payload(rates=[rate(code="XYZ")]), "'XYZ' is not an ISO 4217 code"),
        (payload(rates=[rate(export=0)]), "bad export rate for USD"),
        (payload(rates=[rate(export="94.2")]), "bad export rate for USD"),
        (payload(rates=[rate(units="10.0")]), "unit '10.0' for USD"),
        (payload(rates=[rate(units="one")]), "unit 'one' for USD"),
        (payload(rates=[rate(), rate()]), "29/2026 and 29/2026 both set USD from 2026-10-16"),
    ],
)
@pytest.mark.usefixtures("small_minimums")
def test_malformed_notifications_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_exchange_rates("rates", data, CURRENCIES)
