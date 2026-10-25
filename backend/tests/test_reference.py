from datetime import date

import pytest

from shipready.reference.files import ReferenceDataError, indian_date, read_csv

COUNTRIES = {row["code"]: row["name"] for row in read_csv("countries.csv")}


def test_countries_are_the_iso_3166_list() -> None:
    assert len(COUNTRIES) == 249
    assert COUNTRIES["IN"] == "India"
    assert COUNTRIES["CI"] == "Côte d'Ivoire"
    assert COUNTRIES["BQ"] == "Bonaire, Sint Eustatius and Saba"


@pytest.mark.parametrize("text", ["17-06-2025", "17/06/2025", "17.06.2025", " 17-06-2025 "])
def test_indian_dates_in_every_layout_dgft_and_icegate_use(text: str) -> None:
    assert indian_date("f", 1, text) == date(2025, 6, 17)


@pytest.mark.parametrize("value", ["2025-06-17", "31-02-2025", "", None, 20250617])
def test_other_dates_are_rejected(value: object) -> None:
    with pytest.raises(ReferenceDataError, match="f:3: expected a DD-MM-YYYY date"):
        indian_date("f", 3, value)
