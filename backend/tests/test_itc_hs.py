import json
from collections.abc import Callable

import pytest

from shipready.reference.files import ReferenceDataError
from shipready.reference.itc_hs import parse_itc_hs


def entries(*pairs: tuple[str, str]) -> bytes:
    return json.dumps([{"itcCode": code, "itcDescription": text} for code, text in pairs]).encode()


@pytest.mark.usefixtures("small_minimums")
def test_parses_the_dgft_tree(reference_file: Callable[[str], bytes]) -> None:
    rows = {row["code"]: row for row in parse_itc_hs("itc", reference_file("dgft-itc-hs.json"))}
    assert rows["17"]["level"] == 2
    assert rows["1701"]["level"] == 4
    assert rows["61091000"] == {"code": "61091000", "level": 8, "description": "Of cotton"}
    assert sum(1 for row in rows.values() if row["level"] == 8) == 11


@pytest.mark.usefixtures("small_minimums")
def test_whitespace_is_cleaned_and_the_first_duplicate_kept(
    reference_file: Callable[[str], bytes],
) -> None:
    # DGFT lists heading 8901 twice, once as "8901\n\n" with a padded description.
    rows = {row["code"]: row for row in parse_itc_hs("itc", reference_file("dgft-itc-hs.json"))}
    assert rows["8901"]["description"].startswith("Cruise ships, excursion boats")
    assert "  " not in rows["8901"]["description"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"<html>error</html>", "itc: not valid JSON"),
        (b'{"a": 1}', "itc: expected a JSON list"),
        (b'["text"]', "itc:1: expected an object"),
        (entries(("6109100", "Of cotton")), "itc:1: invalid ITC\\(HS\\) code '6109100'"),
        (entries(("61091000", "  ")), "itc:1: code 61091000 has no description"),
    ],
)
def test_malformed_entries_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_itc_hs("itc", data)


def test_a_truncated_list_is_rejected() -> None:
    with pytest.raises(ReferenceDataError, match="only 1 eight-digit codes"):
        parse_itc_hs("itc", entries(("61091000", "Of cotton")))
