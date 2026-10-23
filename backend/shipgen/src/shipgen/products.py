"""The product catalogue ShipGen draws line items from (shipgen/data/products.csv)."""

from dataclasses import dataclass
from decimal import Decimal

from shipready.reference.files import (
    ReferenceDataError,
    numbered_rows,
    positive_decimal,
    read_text,
)
from shipready.reference.itc_hs import load_itc_hs

COLUMNS = (
    "sku",
    "category",
    "hs_code",
    "description",
    "variants",
    "uqc",
    "price_usd_min",
    "price_usd_max",
    "net_kg_per_unit",
    "units_per_package",
    "package_type",
    "package_tare_kg",
    "package_cbm",
    "packages_min",
    "packages_max",
)
_NUMBERS = (
    "price_usd_min",
    "price_usd_max",
    "net_kg_per_unit",
    "units_per_package",
    "package_tare_kg",
    "package_cbm",
    "packages_min",
    "packages_max",
)


@dataclass(frozen=True)
class Product:
    sku: str
    category: str
    hs_code: str
    description: str
    variants: tuple[str, ...]
    uqc: str
    price_usd_min: Decimal
    price_usd_max: Decimal
    net_kg_per_unit: Decimal
    units_per_package: Decimal
    package_type: str
    package_tare_kg: Decimal
    package_cbm: Decimal
    packages_min: int
    packages_max: int


def parse_products(source: str, text: str) -> list[Product]:
    """Validate the catalogue: every HS code must be Free in ITC-HS, with the same unit."""
    itc_hs = {row["code"]: row for row in load_itc_hs()}
    products = []
    for line, row in numbered_rows(source, text, COLUMNS):
        hs = itc_hs.get(row["hs_code"])
        if hs is None:
            raise ReferenceDataError(source, line, f"HS code {row['hs_code']} not in itc_hs.csv")
        # Golden shipments must be clean, so restricted goods are left to error injection.
        if hs["export_policy"] != "Free":
            raise ReferenceDataError(source, line, f"HS code {row['hs_code']} is not Free")
        if row["uqc"] != hs["uqc"]:
            raise ReferenceDataError(source, line, f"uqc {row['uqc']} differs from ITC-HS")
        number = {name: positive_decimal(source, line, name, row[name]) for name in _NUMBERS}
        if number["packages_min"] % 1 or number["packages_max"] % 1:
            raise ReferenceDataError(source, line, "package counts must be whole numbers")
        product = Product(
            sku=row["sku"],
            category=row["category"],
            hs_code=row["hs_code"],
            description=row["description"],
            variants=tuple(row["variants"].split(";")),
            uqc=row["uqc"],
            price_usd_min=number["price_usd_min"],
            price_usd_max=number["price_usd_max"],
            net_kg_per_unit=number["net_kg_per_unit"],
            units_per_package=number["units_per_package"],
            package_type=row["package_type"],
            package_tare_kg=number["package_tare_kg"],
            package_cbm=number["package_cbm"],
            packages_min=int(number["packages_min"]),
            packages_max=int(number["packages_max"]),
        )
        if (
            product.price_usd_min > product.price_usd_max
            or product.packages_min > product.packages_max
        ):
            raise ReferenceDataError(source, line, "minimum exceeds maximum")
        products.append(product)
    return products


def load_products() -> list[Product]:
    return parse_products("products.csv", read_text("products.csv", "shipgen"))
