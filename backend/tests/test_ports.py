import json
from collections.abc import Callable

import pytest

from shipready.reference.files import ReferenceDataError
from shipready.reference.ports import parse_ports


def values(*texts: str) -> bytes:
    return json.dumps([{"key": n, "value": text} for n, text in enumerate(texts)]).encode()


@pytest.mark.usefixtures("small_minimums")
def test_parses_icegate_locations_by_kind(reference_file: Callable[[str], bytes]) -> None:
    result = parse_ports("ports", reference_file("dgft-ports.json"))
    rows = {row["code"]: row for row in result.rows}
    assert {code: row["kind"] for code, row in rows.items()} == {
        "INNSA1": "sea",
        "INMUN1": "sea",
        "INALF1": "sea",
        "INBOM4": "air",
        "INDEL4": "air",
        "INTKD6": "inland",
        "INNTLB": "land",
        "INMAA5": "post",
        "INASR2": "rail",
    }
    assert rows["INNSA1"]["name"] == "JNCH, NHAVA SHEVA, TAL:URAN, DIST-RAIGAD-400707"
    assert rows["INNSA1"]["edi"] is True
    assert rows["INNTLB"]["edi"] is False  # "Non EDI"
    assert rows["INALF1"]["name"] == "SEA-PORT , ALLEPEY"


@pytest.mark.usefixtures("small_minimums")
def test_administrative_entries_are_skipped(reference_file: Callable[[str], bytes]) -> None:
    result = parse_ports("ports", reference_file("dgft-ports.json"))
    assert result.skipped == {"INICED": 1, "INXXX0": 1, "DEEMED": 1}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b'{"a": 1}', "ports: expected a JSON list"),
        (b'["INNSA1-X-EDI"]', "ports:1: expected an object with a value"),
        (values("Nhava Sheva"), "ports:1: unrecognised port entry"),
        (values("INNSA9-SOMEWHERE-EDI"), "ports:1: unknown location kind in code INNSA9"),
        (values("INNSA1-A-EDI", "INNSA1-B-EDI"), "ports:2: duplicate port code INNSA1"),
    ],
)
def test_malformed_entries_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_ports("ports", data)


def test_a_truncated_list_is_rejected() -> None:
    with pytest.raises(ReferenceDataError, match="only 1 ports"):
        parse_ports("ports", values("INNSA1-JNCH, NHAVA SHEVA-EDI"))
