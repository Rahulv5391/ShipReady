import zipfile
from pathlib import Path

import pytest

from shipready.reference.files import ReferenceDataError
from shipready.reference.unlocode import parse_unlocode

COUNTRIES = {"IN", "NL"}
PART1 = (
    ",IN,,.INDIA,,,,,,,,\n"
    ",IN,NSA,Nhava Sheva (Jawaharlal Nehru),Nhava Sheva,MH,1-------,AA,0002,,,\n"
    "#,IN,NSA,Jawaharlal Nehru (Nhava Sheva),Jawaharlal Nehru,MH,1-------,AA,2501,,,\n"
    "X,IN,OLD,Closed Place,Closed Place,,--3-----,AS,2501,,,\n"
    ",XZ,ABC,International Waters,International Waters,,1-------,RL,0101,,,\n"
)
PART2 = ',NL,RTM,Rotterdam,Rotterdam,ZH,12345---,AF,0501,,"5155N 00430E",\n'


def make_zip(tmp_path: Path, parts: dict[str, bytes]) -> Path:
    path = tmp_path / "unlocode-latest.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(f"release/csv/{name}", data)
    return path


def valid_zip(tmp_path: Path) -> Path:
    return make_zip(
        tmp_path,
        {
            "UNLOCODE CodeListPart1.csv": PART1.encode(),
            "UNLOCODE CodeListPart2.csv": PART2.encode(),
            "SubdivisionCodes.csv": b"not,a,code,list\n",
        },
    )


def test_parses_locations_across_parts(tmp_path: Path) -> None:
    parsed = parse_unlocode(valid_zip(tmp_path), COUNTRIES)
    rows = {row["code"]: row for row in parsed.rows}
    assert set(rows) == {"INNSA", "NLRTM"}
    assert rows["NLRTM"] == {
        "code": "NLRTM",
        "country": "NL",
        "name": "Rotterdam",
        "subdivision": "ZH",
        "functions": "12345---",
        "status": "AF",
    }


def test_entry_changed_in_this_release_wins_over_the_old_one(tmp_path: Path) -> None:
    rows = {row["code"]: row for row in parse_unlocode(valid_zip(tmp_path), COUNTRIES).rows}
    assert rows["INNSA"]["name"] == "Jawaharlal Nehru (Nhava Sheva)"


def test_deleted_and_non_iso_entries_are_skipped(tmp_path: Path) -> None:
    parsed = parse_unlocode(valid_zip(tmp_path), COUNTRIES)
    assert "INOLD" not in {row["code"] for row in parsed.rows}
    assert parsed.skipped_countries == {"XZ": 1}


def test_empty_subdivision_and_status_become_none(tmp_path: Path) -> None:
    path = make_zip(
        tmp_path, {"CodeListPart1.csv": b",IN,AMD,Ahmedabad,Ahmedabad,,1--4----,,,,,\n"}
    )
    (row,) = parse_unlocode(path, COUNTRIES).rows
    assert row["subdivision"] is None
    assert row["status"] is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b",IN,NSA,Nhava Sheva\n", r"CodeListPart1\.csv:1: expected 12 fields, got 4"),
        (b",IN,AMD,Ahmedabad,Ahmedabad,GJ,1--4----,AI,,,,\n,IN,ns,X,X,,1-------,,,,,\n",
         r"CodeListPart1\.csv:2: invalid code 'IN' 'ns'"),
        (b",IN,AMD,Ahmedabad,Ahmedabad,GJ,port,AI,,,,\n", r":1: function must be 8 characters"),
        (b",IN,AMD,,,GJ,1--4----,AI,,,,\n", r":1: name is empty"),
        (",IN,AMD,Ahmedābād,Ahmedabad,GJ,1--4----,AI,,,,\n".encode("latin-1", "replace")
         + b"\xff\n", r"CodeListPart1\.csv: not UTF-8"),
    ],
)  # fmt: skip
def test_malformed_files_name_the_file_and_line(tmp_path: Path, data: bytes, message: str) -> None:
    path = make_zip(tmp_path, {"CodeListPart1.csv": data})
    with pytest.raises(ReferenceDataError, match=message):
        parse_unlocode(path, COUNTRIES)


def test_zip_without_code_list_is_rejected(tmp_path: Path) -> None:
    path = make_zip(tmp_path, {"SubdivisionCodes.csv": b""})
    with pytest.raises(ReferenceDataError, match="no CodeListPart"):
        parse_unlocode(path, COUNTRIES)
