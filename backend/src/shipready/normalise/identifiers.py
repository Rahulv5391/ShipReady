"""Format and checksum validation for Indian exporter identifiers: GSTIN, PAN, IEC and AD code."""

import re

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# The 4th PAN character is the holder type (P person, C company, F firm, ...).
_PAN_PATTERN = r"[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]"
_PAN_RE = re.compile(rf"^{_PAN_PATTERN}$")
# State code + PAN + entity number + 'Z' + checksum character.
_GSTIN_RE = re.compile(rf"^[0-9]{{2}}{_PAN_PATTERN}[1-9A-Z]Z[0-9A-Z]$")
# Since 2017 the IEC is the exporter's PAN; IECs issued earlier are 10 digits.
_LEGACY_IEC_RE = re.compile(r"^[0-9]{10}$")
_AD_CODE_RE = re.compile(r"^[0-9]{14}$")

# GST state codes 01-38, plus 97 (other territory) and 99 (centre jurisdiction).
_GST_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}


def clean(value: str) -> str:
    """Upper-case and drop spaces, dashes and dots, which documents often print inside codes."""
    return re.sub(r"[\s\-.]", "", value).upper()


def gstin_check_char(first14: str) -> str:
    """Return the GSTIN checksum character for its first 14 characters (GSTN mod-36 scheme)."""
    if len(first14) != 14 or any(c not in _GSTIN_CHARS for c in first14):
        raise ValueError(f"expected 14 characters from 0-9 and A-Z, got {first14!r}")
    total = 0
    for position, char in enumerate(first14):
        product = _GSTIN_CHARS.index(char) * (1 if position % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def is_valid_pan(value: str) -> bool:
    return bool(_PAN_RE.match(clean(value)))


def is_valid_gstin(value: str) -> bool:
    gstin = clean(value)
    return (
        bool(_GSTIN_RE.match(gstin))
        and gstin[:2] in _GST_STATE_CODES
        and gstin_check_char(gstin[:14]) == gstin[14]
    )


def pan_from_gstin(gstin: str) -> str:
    """Return the PAN embedded in a valid GSTIN (characters 3 to 12)."""
    if not is_valid_gstin(gstin):
        raise ValueError(f"not a valid GSTIN: {gstin!r}")
    return clean(gstin)[2:12]


def is_valid_iec(value: str) -> bool:
    iec = clean(value)
    return is_valid_pan(iec) or bool(_LEGACY_IEC_RE.match(iec))


def is_valid_ad_code(value: str) -> bool:
    return bool(_AD_CODE_RE.match(clean(value)))
