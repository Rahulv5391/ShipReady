from collections.abc import Callable

import pytest

from shipready.reference.currencies import parse_currencies
from shipready.reference.files import ReferenceDataError


def document(*entries: str) -> bytes:
    body = "".join(f"<CcyNtry>{entry}</CcyNtry>" for entry in entries)
    return f'<ISO_4217 Pblshd="2026-09-17"><CcyTbl>{body}</CcyTbl></ISO_4217>'.encode()


def entry(country: str, code: str, name: str, minor: str) -> str:
    return (
        f"<CtryNm>{country}</CtryNm><CcyNm>{name}</CcyNm><Ccy>{code}</Ccy>"
        f"<CcyMnrUnts>{minor}</CcyMnrUnts>"
    )


@pytest.mark.usefixtures("small_minimums")
def test_parses_the_six_list(reference_file: Callable[[str], bytes]) -> None:
    rows = {
        row["code"]: row for row in parse_currencies("iso", reference_file("iso4217-list-one.xml"))
    }
    assert rows["INR"] == {"code": "INR", "name": "Indian Rupee", "minor_units": 2}
    assert rows["JPY"]["minor_units"] == 0
    assert rows["KWD"]["minor_units"] == 3
    assert rows["XAU"]["minor_units"] is None  # gold has no minor unit
    # USD is listed for the USA and Ecuador; Antarctica has no currency.
    assert sorted(rows) == ["AED", "EUR", "GBP", "INR", "JPY", "KWD", "USD", "USN", "XAU"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not xml", "iso: not valid XML"),
        (b"<html/>", "expected an ISO_4217 document"),
        (document(entry("X", "US", "Dollar", "2")), "iso:1: invalid currency code 'US'"),
        (document(entry("X", "USD", "", "2")), "iso:1: incomplete entry for USD"),
        (document(entry("X", "USD", "US Dollar", "two")), "iso:1: incomplete entry for USD"),
        (
            document(entry("A", "USD", "US Dollar", "2"), entry("B", "USD", "US Dollar", "3")),
            "iso:2: conflicting entries for USD",
        ),
    ],
)
def test_malformed_lists_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_currencies("iso", data)


def test_a_truncated_list_is_rejected() -> None:
    with pytest.raises(ReferenceDataError, match="only 1 currencies"):
        parse_currencies("iso", document(entry("INDIA", "INR", "Indian Rupee", "2")))
