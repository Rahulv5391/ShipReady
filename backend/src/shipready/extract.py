"""Read the fields of a shipment's documents, each with the exact text it came from, and find
that text on its page: the evidence a finding will point to.

The fields asked for are generated from the document models (shipready.documents.models), so the
guide the AI receives always matches what the checks expect. Paths are those of the models, with
line numbers: "lines[2].quantity" of a commercial invoice is that invoice's third line's quantity.
"""

import re
import types
import typing
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Protocol

from pydantic import BaseModel

from shipready.documents.models import ShipmentDocuments
from shipready.pages import Page, Word

_INDEX = re.compile(r"\[\d+\]")
# Where a document's layout alone would mislead: printed addresses put the city between the
# street and the state, and a bill of lading prints nothing when it is not "to order".
_HINTS = {
    "address.lines[]": (
        "every address line except the city and the country, including a state and postcode line"
    ),
    "to_order": "true only if the consignee is shown as TO ORDER, otherwise false",
}


@dataclass(frozen=True)
class DocumentText:
    """One document of the shipment, as the worker split it: its type and its pages."""

    part: int  # numbers the documents in a request; the AI answers with it
    doc_type: str
    filename: str
    pages: tuple[Page, ...]


@dataclass(frozen=True)
class RawField:
    """A field as the AI gives it, before it is checked."""

    part: int
    path: str  # inside the document, e.g. "lines[0].quantity"
    value: str
    quote: str  # the text exactly as printed
    page: int


@dataclass(frozen=True)
class Box:
    """Where a quote is on its page, as fractions of the page from the top left."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class FieldWithEvidence:
    path: str  # with its document, e.g. "commercial_invoice.lines[0].quantity"
    value: str
    quote: str
    part: int
    page: int  # page of the file
    box: Box | None  # None when the quote could not be found on the page


class FieldExtractor(Protocol):
    model: str  # recorded with each field

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]: ...


def extract_fields(
    documents: list[DocumentText], extractor: FieldExtractor
) -> list[FieldWithEvidence]:
    """Every field the AI found, kept only if its path is one the document type has, once per
    path (the first answer wins), with its evidence box when the quote is on the stated page."""
    known = {document.part: document for document in documents}
    if not known:
        return []
    guide = field_guide(sorted({document.doc_type for document in documents}))
    fields: dict[str, FieldWithEvidence] = {}
    for raw in extractor.extract(documents, guide):
        document = known.get(raw.part)
        if document is None or not raw.value.strip():
            continue
        if _INDEX.sub("[]", raw.path) not in field_templates(document.doc_type):
            continue
        path = f"{document.doc_type}.{raw.path}"
        if path not in fields:
            fields[path] = FieldWithEvidence(
                path, raw.value.strip(), raw.quote, raw.part, raw.page, _find(document, raw)
            )
    return list(fields.values())


def _find(document: DocumentText, raw: RawField) -> Box | None:
    page = next((p for p in document.pages if p.number == raw.page), None)
    located = locate(raw.quote, page.words) if page is not None else None
    return Box(*located) if located is not None else None


def locate(quote: str, words: tuple[Word, ...]) -> tuple[float, float, float, float] | None:
    """The box around the words that spell `quote`, ignoring spaces and case, since OCR joins
    and splits words. A match of whole words is preferred, so an IEC is not found inside the
    GSTIN that contains it. A quote over several lines that is not found in one piece (text
    wrapped in a table cell is read between the row's other cells) is found line by line.
    None when the quote is not on the page."""
    found = _locate_span(quote, words)
    lines = [line for line in quote.splitlines() if line.strip()]
    if found is not None or len(lines) < 2:
        return found
    boxes = [box for box in (_locate_span(line, words) for line in lines) if box is not None]
    if len(boxes) < len(lines):
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _locate_span(quote: str, words: tuple[Word, ...]) -> tuple[float, float, float, float] | None:
    target = _squash(quote)
    if not target:
        return None
    joined, owners, word_starts = "", [], set()
    for index, word in enumerate(words):
        text = _squash(word.text)
        word_starts.add(len(joined))
        joined += text
        owners += [index] * len(text)
    word_starts.add(len(joined))
    starts = [m.start() for m in re.finditer(f"(?={re.escape(target)})", joined)]
    if not starts:
        return None
    whole = [s for s in starts if s in word_starts and s + len(target) in word_starts]
    start = (whole or starts)[0]
    hit = [words[i] for i in sorted(set(owners[start : start + len(target)]))]
    return (
        min(w.x0 for w in hit),
        min(w.y0 for w in hit),
        max(w.x1 for w in hit),
        max(w.y1 for w in hit),
    )


def _squash(text: str) -> str:
    return "".join(text.split()).casefold()


def field_guide(doc_types: list[str]) -> str:
    """The fields of each document type, one per line, for the AI to fill."""
    lines = []
    for doc_type in doc_types:
        lines.append(f"{doc_type}:")
        lines += [f"  {path} ({kind})" for path, kind in field_templates(doc_type).items()]
    return "\n".join(lines)


@cache
def field_templates(doc_type: str) -> dict[str, str]:
    """Field paths of a document type ("lines[].quantity") with the kind of value expected.
    "other" documents have no fields."""
    model = ShipmentDocuments.model_fields.get(doc_type)
    if model is None:
        return {}
    return dict(_templates(_model_of(model.annotation), ""))


def _templates(model: type[BaseModel], prefix: str) -> list[tuple[str, str]]:
    found = []
    for name, info in model.model_fields.items():
        kind = _without_none(info.annotation)
        path = f"{prefix}{name}"
        if typing.get_origin(kind) is tuple:
            kind, path = typing.get_args(kind)[0], f"{path}[]"
        if isinstance(kind, type) and issubclass(kind, BaseModel):
            found += _templates(kind, f"{path}.")
        else:
            hint = next((h for end, h in _HINTS.items() if path.endswith(end)), None)
            found.append((path, f"{_kind(kind, name)}; {hint}" if hint else _kind(kind, name)))
    return found


def _model_of(annotation: object) -> type[BaseModel]:
    model = _without_none(annotation)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise TypeError(f"not a document model: {annotation!r}")
    return model


def _without_none(annotation: object) -> object:
    """X for "X | None"."""
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        (inner,) = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return inner
    return annotation


def _kind(annotation: object, name: str) -> str:
    """How the AI should write the value, so it can be compared without guessing formats."""
    if annotation is date:
        return "date, YYYY-MM-DD"
    if annotation is Decimal:
        return "number, digits and a decimal point only"
    if annotation is bool:
        return "true or false"
    if annotation is int:
        return "whole number"
    if typing.get_origin(annotation) is typing.Literal:
        return "one of " + ", ".join(str(a) for a in typing.get_args(annotation))
    if name == "country" or name.endswith("_country") or name == "country_of_origin":
        return "ISO 3166 two-letter country code"
    return "text as printed"
