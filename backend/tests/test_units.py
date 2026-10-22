from decimal import Decimal

import pytest

from shipready.normalise.units import same_quantity, to_uqc
from shipready.reference.uqc import UQC


def test_uqc_list_is_loaded() -> None:
    assert len(UQC) == 45
    assert UQC["KGS"] == "KILOGRAMS"
    assert {"PCS", "NOS", "MTS", "TON", "SET", "PRS", "CTN"} <= UQC.keys()


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("PCS", "PCS"),
        ("Pcs.", "PCS"),
        ("pieces", "PCS"),
        ("Nos", "NOS"),
        ("kg", "KGS"),
        ("K G S", "KGS"),
        ("M.T.", "MTS"),
        ("tonnes", "TON"),
        ("litres", "LTR"),
        ("Sq M", "SQM"),
        ("furlongs", None),
        ("", None),
    ],
)
def test_to_uqc(printed: str, expected: str | None) -> None:
    assert to_uqc(printed) == expected


@pytest.mark.parametrize(
    ("a", "a_uqc", "b", "b_uqc", "expected"),
    [
        ("500", "PCS", "500", "PCS", True),
        ("500", "PCS", "480", "PCS", False),
        ("1000", "KGS", "1", "MTS", True),
        ("2.5", "TON", "2500", "KGS", True),
        ("1001", "KGS", "1", "MTS", False),
        ("12", "PCS", "1", "DOZ", True),
        ("144", "NOS", "1", "GRS", True),
        ("250", "MLT", "0.25", "LTR", True),
        ("5", "KGS", "5", "PCS", None),  # mass vs count
        ("10", "SET", "10", "PCS", None),  # no fixed conversion
        ("0", "KGS", "0", "MTS", True),
    ],
)
def test_same_quantity(a: str, a_uqc: str, b: str, b_uqc: str, expected: bool | None) -> None:
    assert same_quantity(Decimal(a), a_uqc, Decimal(b), b_uqc) is expected


def test_same_quantity_rejects_codes_outside_the_uqc_list() -> None:
    with pytest.raises(ValueError, match="not a UQC code: 'KG'"):
        same_quantity(Decimal(1), "KG", Decimal(1), "KGS")
