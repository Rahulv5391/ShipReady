import pytest
from hypothesis import given
from hypothesis import strategies as st

from shipready.normalise.containers import check_digit, is_valid_container

first10s = st.from_regex(r"[A-Z]{3}[UJZ][0-9]{6}", fullmatch=True)


def test_iso_6346_reference_example() -> None:
    assert check_digit("CSQU305438") == 3
    assert is_valid_container("CSQU3054383")


def test_remainder_ten_is_written_as_zero() -> None:
    assert check_digit("CSQU000007") == 0
    assert is_valid_container("CSQU0000070")


def test_separators_and_case_are_ignored() -> None:
    assert is_valid_container("csqu 305438-3")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "CSQU3054384",  # wrong check digit
        "CSQU305438",  # check digit missing
        "CSQU30543831",  # too long
        "CSQX3054383",  # category must be U, J or Z
        "CS1U3054383",  # owner code must be letters
    ],
)
def test_invalid_containers(value: str) -> None:
    assert not is_valid_container(value)


@pytest.mark.parametrize("value", ["CSQU30543", "CSQX305438", "csqu305438", ""])
def test_check_digit_rejects_malformed_input(value: str) -> None:
    with pytest.raises(ValueError, match="owner code"):
        check_digit(value)


@given(first10s)
def test_computed_check_digit_validates(first10: str) -> None:
    digit = check_digit(first10)
    assert 0 <= digit <= 9
    assert is_valid_container(f"{first10}{digit}")
    assert not is_valid_container(f"{first10}{(digit + 1) % 10}")
