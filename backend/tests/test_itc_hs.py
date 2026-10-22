import pytest

from shipready.reference.files import ReferenceDataError
from shipready.reference.itc_hs import load_itc_hs, parse_itc_hs

HEADER = "code,description,chapter,export_policy,uqc,source\n"
VALID = "61091000,Of cotton,Apparel,Free,NOS,DGFT\n"


def test_packaged_codes_load() -> None:
    rows = {row["code"]: row for row in load_itc_hs()}
    assert len(rows) == 21
    assert rows["61091000"]["description"] == "Of cotton"
    assert rows["17019990"]["export_policy"] == "Restricted"
    assert {row["export_policy"] for row in rows.values()} == {"Free", "Restricted"}


def test_valid_row_is_returned_stripped() -> None:
    (row,) = parse_itc_hs("x.csv", HEADER + "61091000, Of cotton ,Apparel,Free,NOS,DGFT\n")
    assert row == {
        "code": "61091000",
        "description": "Of cotton",
        "chapter": "Apparel",
        "export_policy": "Free",
        "uqc": "NOS",
        "source": "DGFT",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("code,description\n" + VALID, r"x\.csv:1: expected columns"),
        (HEADER + "61091000,Of cotton,Apparel,Free\n", r"x\.csv:2: expected 6 fields"),
        (HEADER + VALID + "6109100,Of cotton,Apparel,Free,NOS,DGFT\n", r"x\.csv:3: code must be 8"),
        (HEADER + VALID + VALID, r"x\.csv:3: duplicate code 61091000"),
        (HEADER + VALID.replace("Free", "Open"), r"x\.csv:2: export_policy must be"),
        (HEADER + VALID.replace("NOS", "KG"), r"x\.csv:2: not a UQC code: 'KG'"),
        (HEADER + VALID.replace("Of cotton", " "), r"x\.csv:2: description is empty"),
        (HEADER + VALID.replace("DGFT", ""), r"x\.csv:2: source is empty"),
    ],
)
def test_malformed_rows_name_the_file_and_line(text: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_itc_hs("x.csv", text)
