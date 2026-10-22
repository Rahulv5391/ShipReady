from shipready.reference.files import read_csv

COUNTRIES = {row["code"]: row["name"] for row in read_csv("countries.csv")}
PORTS = read_csv("ports.csv")

# Last character of an ICEGATE port code: 1 seaport, 4 air cargo complex, 6 inland container depot.
ICEGATE_SUFFIX = {"sea": "1", "air": "4", "icd": "6"}


def test_countries_are_the_iso_3166_list() -> None:
    assert len(COUNTRIES) == 249
    assert COUNTRIES["IN"] == "India"
    assert COUNTRIES["CI"] == "Côte d'Ivoire"
    assert COUNTRIES["BQ"] == "Bonaire, Sint Eustatius and Saba"


def test_ports_are_unique_and_in_known_countries() -> None:
    codes = [port["code"] for port in PORTS]
    assert len(codes) == len(set(codes))
    assert all(port["country"] in COUNTRIES for port in PORTS)
    assert all(port["kind"] in ICEGATE_SUFFIX for port in PORTS)
    assert all(port["unlocode"].startswith(port["country"]) for port in PORTS)


def test_indian_ports_use_icegate_codes() -> None:
    indian = [port for port in PORTS if port["country"] == "IN"]
    assert indian
    for port in indian:
        assert port["code"] == port["unlocode"] + ICEGATE_SUFFIX[port["kind"]], port


def test_foreign_ports_use_their_unlocode() -> None:
    foreign = [port for port in PORTS if port["country"] != "IN"]
    assert foreign
    assert all(port["code"] == port["unlocode"] for port in foreign)
