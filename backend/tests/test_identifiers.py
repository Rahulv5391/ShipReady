import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from shipready.normalise.identifiers import (
    clean,
    gstin_check_char,
    is_valid_ad_code,
    is_valid_gstin,
    is_valid_iec,
    is_valid_pan,
    pan_from_gstin,
)

# Example GSTIN published in GST documentation; validates the checksum independently.
PUBLISHED_GSTIN = "27AAPFU0939F1ZV"

pans = st.from_regex(r"[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]", fullmatch=True)
state_codes = st.sampled_from([f"{n:02d}" for n in range(1, 39)] + ["97", "99"])


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    first14 = f"{state_code}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


def test_clean_removes_separators_and_uppercases() -> None:
    assert clean(" 27aapfu-0939.f1zv ") == PUBLISHED_GSTIN
    assert clean("") == ""


def test_published_gstin_is_valid() -> None:
    assert is_valid_gstin(PUBLISHED_GSTIN)
    assert is_valid_gstin("27 aapfu 0939 f1zv")
    assert pan_from_gstin(PUBLISHED_GSTIN) == "AAPFU0939F"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "27AAPFU0939F1Z",  # too short
        "27AAPFU0939F1ZVX",  # too long
        "27AAPFU0939F1ZW",  # wrong checksum
        "27AAPFU0939F1AV",  # 14th character must be Z
        "27AAPFU0939F0ZV",  # entity number cannot be 0
        "40AAPFU0939F1ZV",  # no such state code
        "27AAPXU0939F1ZV",  # X is not a PAN holder type
    ],
)
def test_invalid_gstins(value: str) -> None:
    assert not is_valid_gstin(value)


@given(state_codes, pans)
def test_constructed_gstins_validate_and_embed_the_pan(state_code: str, pan: str) -> None:
    gstin = make_gstin(state_code, pan)
    assert is_valid_gstin(gstin)
    assert pan_from_gstin(gstin) == pan


@given(state_codes, pans, st.integers(min_value=0, max_value=14), st.sampled_from("0123456789"))
def test_changing_one_digit_breaks_the_checksum(
    state_code: str, pan: str, position: int, digit: str
) -> None:
    gstin = make_gstin(state_code, pan)
    assume(gstin[position].isdigit() and gstin[position] != digit)
    tampered = gstin[:position] + digit + gstin[position + 1 :]
    assert not is_valid_gstin(tampered)


def test_gstin_check_char_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="14 characters"):
        gstin_check_char("27AAPFU0939F1")
    with pytest.raises(ValueError, match="14 characters"):
        gstin_check_char("27aapfu0939f1z")


def test_pan_from_gstin_rejects_invalid_gstin() -> None:
    with pytest.raises(ValueError, match="not a valid GSTIN"):
        pan_from_gstin("27AAPFU0939F1ZW")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AAPFU0939F", True),
        ("aapfu 0939 f", True),
        ("AAPXU0939F", False),  # X is not a holder type
        ("AAPFU0939", False),
        ("1APFU0939F", False),
        ("", False),
    ],
)
def test_pan(value: str, expected: bool) -> None:
    assert is_valid_pan(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AAPFU0939F", True),  # PAN-based IEC (since 2017)
        ("0388012345", True),  # legacy numeric IEC
        ("038801234", False),
        ("ABCDE12345", False),
        ("", False),
    ],
)
def test_iec(value: str, expected: bool) -> None:
    assert is_valid_iec(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("01234567890123", True),
        ("0123456 7890123", True),
        ("0123456789012", False),
        ("012345678901234", False),
        ("0123456789012A", False),
        ("", False),
    ],
)
def test_ad_code(value: str, expected: bool) -> None:
    assert is_valid_ad_code(value) is expected
