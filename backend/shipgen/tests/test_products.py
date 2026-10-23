import pytest

from shipgen.products import COLUMNS, load_products, parse_products
from shipready.reference.files import ReferenceDataError

HEADER = ",".join(COLUMNS) + "\n"
VALID = "TSH-C,textiles,61091000,T-shirts,S;M,NOS,2.50,5.00,0.18,50,CTN,1.2,0.080,10,200\n"


def test_catalogue_uses_free_itc_hs_codes() -> None:
    products = load_products()
    assert len(products) == 20
    assert len({product.sku for product in products}) == 20
    # Sugar is Restricted, so it is kept out of clean shipments (left for error injection).
    assert "17019990" not in {product.hs_code for product in products}


def test_valid_row_is_parsed() -> None:
    (product,) = parse_products("p.csv", HEADER + VALID)
    assert product.variants == ("S", "M")
    assert product.packages_max == 200
    assert str(product.price_usd_min) == "2.50"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (VALID.replace("61091000", "61091099"), r"p\.csv:2: HS code 61091099 not in itc_hs\.csv"),
        (
            VALID.replace("61091000", "17019990").replace("NOS", "KGS"),
            r":2: HS code .* is not Free",
        ),
        (VALID.replace("NOS", "KGS"), r":2: uqc KGS differs from ITC-HS"),
        (VALID.replace("2.50", "abc"), r":2: price_usd_min is not a number"),
        (VALID.replace("0.18", "0"), r":2: net_kg_per_unit must be positive"),
        (VALID.replace(",10,200", ",10.5,200"), r":2: package counts must be whole numbers"),
        (VALID.replace(",10,200", ",300,200"), r":2: minimum exceeds maximum"),
    ],
)
def test_malformed_rows_name_the_file_and_line(row: str, message: str) -> None:
    with pytest.raises(ReferenceDataError, match=message):
        parse_products("p.csv", HEADER + row)
