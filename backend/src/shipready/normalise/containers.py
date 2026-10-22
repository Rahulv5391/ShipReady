"""ISO 6346 container number validation: owner code, category, serial number, check digit."""

import re

from shipready.normalise.identifiers import clean

_CONTAINER_RE = re.compile(r"^[A-Z]{3}[UJZ][0-9]{7}$")
_FIRST10_RE = re.compile(r"^[A-Z]{3}[UJZ][0-9]{6}$")


def _letter_values() -> dict[str, int]:
    # Letters count from 10 upwards but skip multiples of 11 (11, 22, 33).
    values, value = {}, 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if value % 11 == 0:
            value += 1
        values[letter] = value
        value += 1
    return values


_LETTER_VALUES = _letter_values()


def check_digit(first10: str) -> int:
    """Return the check digit for the first 10 characters, e.g. 'CSQU305438' -> 3."""
    if not _FIRST10_RE.match(first10):
        raise ValueError(f"expected owner code, category and 6-digit serial, got {first10!r}")
    # Each position's weight is 2**position.
    total = sum(
        (int(char) if char.isdigit() else _LETTER_VALUES[char]) << position
        for position, char in enumerate(first10)
    )
    # A remainder of 10 is written as 0.
    return total % 11 % 10


def is_valid_container(value: str) -> bool:
    number = clean(value)
    return bool(_CONTAINER_RE.match(number)) and check_digit(number[:10]) == int(number[10])
