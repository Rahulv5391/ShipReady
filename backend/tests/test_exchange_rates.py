from datetime import date
from decimal import Decimal

import pytest

from shipready.reference.exchange_rates import load_exchange_rates, parse_exchange_rates
from shipready.reference.files import ReferenceDataError

HEADER = "currency,unit,rate_inr,valid_from,notification\n"
USD = "USD,1,90.00,2026-10-16,1/2026-Customs (N.T.)\n"


def test_packaged_rates_cover_three_notifications() -> None:
    rows = load_exchange_rates()
    assert len(rows) == 66
    assert {row["notification"] for row in rows} == {
        "27/2026-Customs (N.T.)",
        "28/2026-Customs (N.T.)",
        "29/2026-Customs (N.T.)",
    }
    jpy = [row for row in rows if row["currency"] == "JPY"]
    assert {row["unit"] for row in jpy} == {100}


def test_valid_rows_are_typed() -> None:
    rows = parse_exchange_rates("x.csv", HEADER + USD + "JPY,100,60.00,2026-10-16,1/2026\n")
    assert rows[0] == {
        "currency": "USD",
        "unit": 1,
        "rate_inr": Decimal("90.00"),
        "valid_from": date(2026, 10, 16),
        "notification": "1/2026-Customs (N.T.)",
    }
    assert rows[1]["unit"] == 100


def test_same_currency_on_different_dates_is_allowed() -> None:
    rows = parse_exchange_rates("x.csv", HEADER + USD + USD.replace("2026-10-16", "2026-11-01"))
    assert [row["valid_from"] for row in rows] == [date(2026, 10, 16), date(2026, 11, 1)]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("currency,rate\n", r"x\.csv:1: expected columns"),
        (HEADER + USD.replace("USD", "US"), r"x\.csv:2: currency must be 3 letters"),
        (HEADER + USD.replace(",1,", ",10,"), r"x\.csv:2: unit must be one of"),
        (HEADER + USD.replace("90.00", "n/a"), r"x\.csv:2: rate_inr is not a number"),
        (HEADER + USD.replace("90.00", "0"), r"x\.csv:2: rate_inr must be positive"),
        (HEADER + USD.replace("90.00", "NaN"), r"x\.csv:2: rate_inr must be positive"),
        (HEADER + USD.replace("2026-10-16", "16/10/2026"), r"x\.csv:2: valid_from must be"),
        (HEADER + USD.replace("1/2026-Customs (N.T.)", ""), r"x\.csv:2: notification is empty"),
        (HEADER + USD + USD, r"x\.csv:3: duplicate rate for USD on 2026-10-16"),
    ],
)
def test_malformed_rows_name_the_file_and_line(text: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_exchange_rates("x.csv", text)
