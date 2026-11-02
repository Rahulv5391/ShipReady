"""A shipment's fields as the checks read them.

Fields are flat, by path ("commercial_invoice.lines[0].quantity"), as extraction stores them
(text) or as the labelled dataset holds them (Python values); both read the same here. A value a
check needs but cannot read raises `NotVerified`, so the check reports "not verified" rather than
guessing. Every path a check reads is remembered: those are its evidence.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

_INDEX = re.compile(r"\[(\d+)\]")


class NotVerified(Exception):
    """A check could not be decided: a value is missing or unreadable, or reference data does
    not cover it."""


class Fields:
    def __init__(self, values: Mapping[str, object]) -> None:
        self.values = values
        self.read: list[str] = []

    def has(self, document: str) -> bool:
        """Whether any field of `document` was found."""
        return any(path.startswith(f"{document}.") for path in self.values)

    def present(self, path: str) -> bool:
        """Whether the field has a value. Not recorded as read: knowing a field is absent
        cites nothing as evidence."""
        value = self.values.get(path)
        return value is not None and not (isinstance(value, str) and not value.strip())

    def optional(self, path: str) -> str | None:
        """The value as text, or None when it is missing or blank."""
        self.read.append(path)
        value = self.values.get(path)
        if not self.present(path):
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip()

    def text(self, path: str) -> str:
        value = self.optional(path)
        if value is None:
            raise NotVerified(f"{path} is missing")
        return value

    def number(self, path: str) -> Decimal:
        text = self.text(path)
        try:
            # Thousands separators are printed; extraction is asked for plain digits but the
            # labelled values and some answers keep them.
            return Decimal(text.replace(",", ""))
        except InvalidOperation:
            raise NotVerified(f"{path} is not a number: {text!r}") from None

    def day(self, path: str) -> date:
        value = self.values.get(path)
        if isinstance(value, date):
            self.read.append(path)
            return value
        text = self.text(path)
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise NotVerified(f"{path} is not a date: {text!r}") from None

    def flag(self, path: str) -> bool:
        text = self.text(path).casefold()
        if text not in ("true", "false"):
            raise NotVerified(f"{path} is not true or false: {text!r}")
        return text == "true"

    def count(self, prefix: str) -> int:
        """How many items the list at `prefix` has ("packing_list.lines" -> 3): one more than
        the highest item number found."""
        numbers = [
            int(match.group(1))
            for path in self.values
            if path.startswith(f"{prefix}[")
            and (match := _INDEX.match(path, len(prefix))) is not None
        ]
        return max(numbers) + 1 if numbers else 0


def transport_document(fields: Fields) -> str:
    """The shipment's transport document: a bill of lading by sea, an airway bill by air."""
    for document in ("bill_of_lading", "air_waybill"):
        if fields.has(document):
            return document
    raise NotVerified("no bill of lading or airway bill was found")


def same_text(a: str, b: str) -> bool:
    """Case and spacing do not change what a text says."""
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


def first_problem(checks: Iterable[Callable[[], str | None]]) -> str | None:
    """The problems `checks` find, joined; a check that cannot be decided does not hide one that
    fails, but with no failure the whole is not verified."""
    problems, undecided = [], None
    for check in checks:
        try:
            problem = check()
        except NotVerified as error:
            undecided = undecided or error
            continue
        if problem:
            problems.append(problem)
    if problems:
        return "; ".join(problems)
    if undecided is not None:
        raise undecided
    return None


class LineCountDiffers(Exception):
    """Documents that should list the same goods have a different number of lines."""


def line_count(fields: Fields, *documents: str) -> int:
    """The number of lines the documents share. Raises NotVerified when a document shows no
    lines, and LineCountDiffers when they list different numbers of lines."""
    counts = {document: fields.count(f"{document}.lines") for document in documents}
    missing = [document for document, count in counts.items() if count == 0]
    if missing:
        raise NotVerified(f"no lines found on {', '.join(missing)}")
    if len(set(counts.values())) > 1:
        raise LineCountDiffers(", ".join(f"{d} has {n} lines" for d, n in counts.items()))
    return next(iter(counts.values()))
