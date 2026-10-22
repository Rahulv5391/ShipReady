"""Units of quantity: map printed units to UQC codes and compare quantities across units."""

from decimal import Decimal

from shipready.reference.uqc import UQC

# Printed spellings that differ from the UQC code itself. Keys are upper-case without dots
# or spaces; codes already in the UQC list (e.g. "KGS", "PCS") need no alias.
_ALIASES = {
    "PC": "PCS", "PIECE": "PCS", "PIECES": "PCS",
    "NO": "NOS", "NUMBER": "NOS",
    "UNIT": "UNT", "UNITS": "UNT",
    "SETS": "SET",
    "PAIR": "PRS", "PAIRS": "PRS",
    "DOZEN": "DOZ", "DOZENS": "DOZ",
    "KG": "KGS", "KILO": "KGS", "KILOS": "KGS", "KILOGRAM": "KGS", "KILOGRAMS": "KGS",
    "G": "GMS", "GM": "GMS", "GRAM": "GMS", "GRAMS": "GMS",
    "MT": "MTS", "TONS": "TON", "TONNE": "TON", "TONNES": "TON",
    "QUINTAL": "QTL",
    "L": "LTR", "LITRE": "LTR", "LITRES": "LTR", "LITER": "LTR", "LITERS": "LTR",
    "ML": "MLT",
    "M": "MTR", "METER": "MTR", "METERS": "MTR", "METRE": "MTR", "METRES": "MTR",
    "CM": "CMS",
    "M2": "SQM", "M3": "CBM",
    "CARTON": "CTN", "CARTONS": "CTN",
    "BAGS": "BAG", "BOXES": "BOX", "ROLL": "ROL", "ROLLS": "ROL",
}  # fmt: skip

# Units convertible to a common base unit: code -> (base code, factor to base).
# MTS and TON are both metric tonnes in the UQC list.
_TO_BASE = {
    "KGS": ("KGS", Decimal(1)),
    "GMS": ("KGS", Decimal("0.001")),
    "QTL": ("KGS", Decimal(100)),
    "MTS": ("KGS", Decimal(1000)),
    "TON": ("KGS", Decimal(1000)),
    "LTR": ("LTR", Decimal(1)),
    "MLT": ("LTR", Decimal("0.001")),
    "KLR": ("LTR", Decimal(1000)),
    "MTR": ("MTR", Decimal(1)),
    "CMS": ("MTR", Decimal("0.01")),
    "KME": ("MTR", Decimal(1000)),
    "PCS": ("PCS", Decimal(1)),
    "NOS": ("PCS", Decimal(1)),
    "UNT": ("PCS", Decimal(1)),
    "DOZ": ("PCS", Decimal(12)),
    "GRS": ("PCS", Decimal(144)),
}


def to_uqc(printed: str) -> str | None:
    """Map a printed unit such as 'Pcs.' or 'kgs' to its UQC code; None if not recognised."""
    key = printed.upper().replace(".", "").replace(" ", "")
    code = _ALIASES.get(key, key)
    return code if code in UQC else None


def same_quantity(a: Decimal, a_uqc: str, b: Decimal, b_uqc: str) -> bool | None:
    """Compare two quantities given in UQC codes, converting units where possible.

    Returns None when the units cannot be compared (e.g. KGS against PCS), so the caller
    can report "not comparable" instead of a false mismatch.
    """
    for code in (a_uqc, b_uqc):
        if code not in UQC:
            raise ValueError(f"not a UQC code: {code!r}")
    if a_uqc == b_uqc:
        return a == b
    if a_uqc not in _TO_BASE or b_uqc not in _TO_BASE:
        return None
    a_base, a_factor = _TO_BASE[a_uqc]
    b_base, b_factor = _TO_BASE[b_uqc]
    if a_base != b_base:
        return None
    return a * a_factor == b * b_factor
