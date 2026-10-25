import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from shipready.reference.export_policy import (
    OVERRIDE_COLUMNS,
    load_overrides,
    parse_export_policy,
    parse_overrides,
)
from shipready.reference.files import ReferenceDataError

CODES = {
    "17011490",
    "17019990",
    "25085031",
    "29031921",
    "29031929",
    "47020010",
    "47020090",
    "61091000",
}
HEADER = ",".join(OVERRIDE_COLUMNS) + "\n"


# A real obsolete code: every list starts with it so no list is empty, and the parser drops it.
OBSOLETE = "29031920"


def payload(lists: dict[str, list[dict[str, str]]], current: dict[str, str]) -> bytes:
    full = {p: [item(OBSOLETE), *lists.get(p, [])] for p in ("Restricted", "Prohibited", "STE")}
    return json.dumps({"lists": full, "current": current}).encode()


def item(code: str, number: str = "", day: str = "") -> dict[str, str]:
    return {"itcCode": code, "notificationNo": number, "notificationDate": day}


def by_code(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["code"], []).append(row)
    return grouped


def test_real_lists_with_the_sugar_overrides(reference_file: Callable[[str], bytes]) -> None:
    result = parse_export_policy(
        "policy", reference_file("dgft-export-policy.json"), CODES, load_overrides()
    )
    rows = by_code(result.rows)
    assert [(r["policy"], r["effective_from"], r["effective_to"]) for r in rows["17019990"]] == [
        ("Restricted", date(2025, 6, 17), date(2026, 5, 12)),
        ("Prohibited", date(2026, 5, 13), date(2026, 9, 30)),
        ("Restricted", date(2026, 10, 1), None),
    ]
    assert {r["source"] for r in rows["17019990"]} == {"override"}
    assert rows["47020010"] == [
        {
            "code": "47020010",
            "policy": "Prohibited",
            "notification": None,
            "effective_from": None,
            "effective_to": None,
            "source": "dgft",
        }
    ]
    assert rows["25085031"][0]["policy"] == "STE"
    assert "61091000" not in rows  # not listed, so Free
    # 29031920 and 47020000 were split into new codes and are no longer in ITC(HS).
    assert result.dropped == {"Restricted": 1, "Prohibited": 1}


@pytest.mark.parametrize(
    ("number", "day", "notification", "effective_from"),
    [
        ("23/2015-20", "07.10.2015", "23/2015-20", date(2015, 10, 7)),
        ("12/2026-27", "17/04/2026", "12/2026-27", date(2026, 4, 17)),
        ("13/2023", "22-06-2023", "13/2023", date(2023, 6, 22)),
        ("104(RE-2013)/2009-2014", "31.12.2014", "104(RE-2013)/2009-2014", date(2014, 12, 31)),
        # Several notifications: the latest date is the one the policy surely applies from.
        (
            "37/2015-20\n15/2015-20",
            "27.01.2017\n05.07.2017",
            "37/2015-20; 15/2015-20",
            date(2017, 7, 5),
        ),
        (
            "11/2015-20 08/2015-20",
            "23.06.2017\n19.05.2022",
            "11/2015-20; 08/2015-20",
            date(2022, 5, 19),
        ),
        ("Notification No. 110/2009-14", "", "110/2009-14", None),
        ("", "", None, None),
    ],
)
def test_dgft_notification_formats(
    number: str, day: str, notification: str | None, effective_from: date | None
) -> None:
    data = payload({"STE": [item("25085031", number, day)]}, {"25085031": "STE"})
    (row,) = parse_export_policy("policy", data, CODES, []).rows
    assert (row["notification"], row["effective_from"]) == (notification, effective_from)


@pytest.mark.parametrize(
    ("number", "day", "message"),
    [
        ("see circular", "", "unrecognised notification 'see circular'"),
        ("23/2015-20 extended", "07.10.2015", "unrecognised notification"),
        ("23/2015-20", "07.10.2015\n08.10.2015", "1 notification numbers but 2 dates"),
        ("23/2015-20", "2015-10-07", "expected a DD-MM-YYYY date"),
    ],
)
def test_unrecognised_notifications_are_rejected(number: str, day: str, message: str) -> None:
    data = payload({"STE": [item("25085031", number, day)]}, {"25085031": "STE"})
    with pytest.raises(ReferenceDataError, match=f"STE list:2: {message}"):
        parse_export_policy("policy", data, CODES, [])


def test_a_code_on_two_lists_needs_an_override() -> None:
    data = payload(
        {"Restricted": [item("17019990")], "Prohibited": [item("17019990")]},
        {"17019990": "Restricted"},
    )
    with pytest.raises(ReferenceDataError, match="17019990 is on the Prohibited, Restricted lists"):
        parse_export_policy("policy", data, CODES, [])


def test_a_code_listed_twice_on_one_list_needs_an_override() -> None:
    data = payload(
        {"STE": [item("25085031"), item("25085031", "13/2023", "22.06.2023")]}, {"25085031": "STE"}
    )
    with pytest.raises(ReferenceDataError, match="25085031 is on the STE list 2 times"):
        parse_export_policy("policy", data, CODES, [])


def test_a_list_entry_that_disagrees_with_today_needs_an_override() -> None:
    data = payload({"Prohibited": [item("47020010")]}, {"47020010": "Free"})
    with pytest.raises(ReferenceDataError, match="47020010: DGFT lists it as Prohibited"):
        parse_export_policy("policy", data, CODES, [])


def test_an_open_override_must_match_today() -> None:
    override = parse_overrides("o.csv", HEADER + "47020010,Restricted,2026-01-01,,1/2026-27,why\n")
    data = payload({"Prohibited": [item("47020010")]}, {"47020010": "Prohibited"})
    with pytest.raises(ReferenceDataError, match="open-ended override says Restricted"):
        parse_export_policy("policy", data, CODES, override)


def test_an_override_for_an_unknown_code_is_rejected() -> None:
    override = parse_overrides("o.csv", HEADER + "99999999,Free,2026-01-01,,1/2026-27,why\n")
    data = payload({"STE": [item("25085031")]}, {"25085031": "STE"})
    with pytest.raises(ReferenceDataError, match="99999999 is not an ITC\\(HS\\) code"):
        parse_export_policy("policy", data, CODES, override)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"[]", "expected an object with 'lists' and 'current'"),
        (json.dumps({"lists": {"Restricted": []}, "current": {}}).encode(), "expected lists"),
        (
            json.dumps(
                {"lists": {"Restricted": [], "Prohibited": [], "STE": []}, "current": {}}
            ).encode(),
            "an export policy list is empty",
        ),
        (
            json.dumps(
                {"lists": {p: [item("25085031")] for p in ("Restricted", "Prohibited", "STE")}}
            ).encode(),
            "missing the current policy",
        ),
        (payload({"STE": [item("2508")]}, {}), "STE list:2: bad code '2508'"),
        (
            payload({"STE": [item("25085031", "1/2024", "2024-05-13")]}, {}),
            "expected a DD-MM-YYYY date",
        ),
    ],
)
def test_malformed_policy_files_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_export_policy("policy", data, CODES, [])


def test_packaged_overrides_cover_the_sugar_ban() -> None:
    rows = load_overrides()
    assert {row["code"] for row in rows} == {"17011490", "17019990"}
    assert all(row["note"] and row["notification"] for row in rows)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("1701999,Free,2026-01-01,,n,why\n", "o.csv:2: code must be 8 digits"),
        ("17019990,Banned,2026-01-01,,n,why\n", "o.csv:2: policy must be one of"),
        ("17019990,Free,01-01-2026,,n,why\n", "o.csv:2: expected YYYY-MM-DD"),
        ("17019990,Free,2026-02-01,2026-01-01,n,why\n", "effective_to is before effective_from"),
        ("17019990,Free,2026-01-01,,n,\n", "notification and note are required"),
        (
            "17019990,Free,2026-01-01,2026-03-01,n,why\n17019990,STE,2026-02-01,,n,why\n",
            "o.csv:3: period overlaps",
        ),
        (
            "17019990,Free,2026-01-01,,n,why\n17019990,STE,2026-02-01,,n,why\n",
            "o.csv:3: period overlaps",
        ),
    ],
)
def test_malformed_overrides_name_the_line(rows: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_overrides("o.csv", HEADER + rows)
