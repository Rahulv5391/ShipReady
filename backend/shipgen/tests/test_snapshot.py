import pytest

from shipgen.reference import (
    ITC_HS_COLUMNS,
    PORT_COLUMNS,
    RATE_COLUMNS,
    load_exchange_rates,
    load_itc_hs,
    load_ports,
    parse_exchange_rates,
    parse_itc_hs,
    parse_ports,
)
from shipready.reference.files import ReferenceDataError

# Last character of an ICEGATE port code: 1 seaport, 4 air cargo complex, 6 inland depot.
ICEGATE_SUFFIX = {"sea": "1", "air": "4", "icd": "6"}


def test_snapshot_itc_hs_codes() -> None:
    codes = load_itc_hs()
    assert len(codes) == 21
    assert codes["17019990"]["export_policy"] == "Restricted"
    assert codes["61091000"]["uqc"] == "NOS"


def test_snapshot_exchange_rates_are_icegate_notifications() -> None:
    rates = load_exchange_rates()
    assert len(rates) == 66
    assert {rate["notification"] for rate in rates} == {"27/2026", "28/2026", "29/2026"}
    assert {rate["unit"] for rate in rates if rate["currency"] == "JPY"} == {100}


def test_snapshot_ports() -> None:
    ports = load_ports()
    assert len({port["code"] for port in ports}) == len(ports) == 28
    for port in ports:
        if port["country"] == "IN":
            assert port["code"] == port["unlocode"] + ICEGATE_SUFFIX[port["kind"]], port
        else:
            assert port["code"] == port["unlocode"], port


ITC_HEADER = ",".join(ITC_HS_COLUMNS) + "\n"
ITC_ROW = "61091000,Of cotton,Apparel,Free,NOS,DGFT\n"
RATE_HEADER = ",".join(RATE_COLUMNS) + "\n"
RATE_ROW = "USD,1,90.00,2026-10-16,29/2026\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (ITC_HEADER + ITC_ROW.replace("61091000", "6109100"), r"i\.csv:2: code must be 8 digits"),
        (ITC_HEADER + ITC_ROW + ITC_ROW, r"i\.csv:3: duplicate code 61091000"),
        (ITC_HEADER + ITC_ROW.replace("Free", "Open"), r"i\.csv:2: export_policy must be"),
        (ITC_HEADER + ITC_ROW.replace("NOS", "KG"), r"i\.csv:2: not a UQC code: 'KG'"),
        (ITC_HEADER + ITC_ROW.replace("Apparel", ""), r"i\.csv:2: description, chapter and source"),
    ],
)
def test_malformed_itc_hs_rows(text: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_itc_hs("i.csv", text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (RATE_HEADER + RATE_ROW.replace("USD", "US"), r"r\.csv:2: currency must be 3 letters"),
        (RATE_HEADER + RATE_ROW.replace(",1,", ",10,"), r"r\.csv:2: unit must be one of"),
        (RATE_HEADER + RATE_ROW.replace("90.00", "0"), r"r\.csv:2: rate_inr must be positive"),
        (RATE_HEADER + RATE_ROW.replace("2026-10-16", "16/10/2026"), r"r\.csv:2: valid_from must"),
        (RATE_HEADER + RATE_ROW.replace("29/2026", ""), r"r\.csv:2: notification is empty"),
        (RATE_HEADER + RATE_ROW + RATE_ROW, r"r\.csv:3: duplicate rate for USD"),
    ],
)
def test_malformed_rate_rows(text: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_exchange_rates("r.csv", text)


def test_malformed_port_rows() -> None:
    text = ",".join(PORT_COLUMNS) + "\nINNSA1,Nhava Sheva,IN,INNSA,ship\n"
    with pytest.raises(ReferenceDataError, match=r"p\.csv:2: kind must be one of"):
        parse_ports("p.csv", text)
