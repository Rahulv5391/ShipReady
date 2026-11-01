"""Decide which document each page belongs to, and split a file into documents (parts).

A page whose top carries an unambiguous title ("BILL OF LADING") is decided by the title. A page
without one continues the document before it, as page 2 of an invoice does. The AI is asked
only as configured (CLASSIFY_WITH_AI):
- never: an untitled first page is "other";
- fallback: the AI decides pages the rules cannot (an untitled first page, conflicting titles);
- always: the AI decides every page, and titles are ignored.
"""

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from shipready.ai import AiMode, PageClassifier
from shipready.pages import Page, Word

# A title is in the top part of the page...
TITLE_ZONE = 0.3
# ...on a short line with no figures or colon, so a field such as "Purchase Order No.: PO-1"
# or a sentence that mentions a "letter of undertaking" is not taken for a title. Titles are
# compared with every space removed, because OCR joins words ("COMMERCIALINVOICE") and splits
# them ("AIR W AYBILL").
TITLE_MAX_WORDS = 8
_TITLES: dict[str, re.Pattern[str]] = {
    "commercial_invoice": re.compile(r"(commercial|export)invoice"),
    "packing_list": re.compile(r"packinglist"),
    "purchase_order": re.compile(r"purchaseorder"),
    "shipping_bill": re.compile(r"shippingbill"),
    "bill_of_lading": re.compile(r"billoflading"),
    "air_waybill": re.compile(r"airwaybill"),
    "certificate_of_origin": re.compile(r"certificateoforigin"),
    "lut": re.compile(r"letterofundertaking|lutacknowledgement"),
}
# Words on one line differ in height by a little; tops within this distance share a line.
_LINE_TOLERANCE = 0.008


@dataclass(frozen=True)
class Part:
    first_page: int
    last_page: int
    doc_type: str
    decided_by: str  # title, follows, ai or none (PART_DECISIONS)
    confidence: Decimal | None  # the AI's, when it decided


def split_into_parts(pages: list[Page], mode: AiMode, ai: PageClassifier | None) -> list[Part]:
    if mode != "never" and ai is None:
        raise ValueError(f"CLASSIFY_WITH_AI={mode} needs an AI classifier")
    parts: list[Part] = []
    for page in pages:
        doc_type, decided_by, confidence = _decide(page, mode, ai, parts)
        previous = parts[-1] if parts else None
        continues = decided_by == "follows" or (
            # Under "always", consecutive pages the AI gives one type are one document.
            mode == "always" and previous is not None and previous.doc_type == doc_type
        )
        if previous is not None and continues:
            lowest = min(
                (c for c in (previous.confidence, confidence) if c is not None), default=None
            )
            parts[-1] = replace(previous, last_page=page.number, confidence=lowest)
        else:
            parts.append(Part(page.number, page.number, doc_type, decided_by, confidence))
    return parts


def _decide(
    page: Page, mode: AiMode, ai: PageClassifier | None, parts: list[Part]
) -> tuple[str, str, Decimal | None]:
    if mode == "always" and ai is not None:
        return _ask(ai, page)
    titles = page_titles(page)
    if len(titles) == 1:
        (title,) = titles
        return title, "title", None
    if not titles and parts:
        return parts[-1].doc_type, "follows", None
    if mode == "fallback" and ai is not None:
        return _ask(ai, page)
    return "other", "none", None


def _ask(ai: PageClassifier, page: Page) -> tuple[str, str, Decimal | None]:
    answer = ai.classify(page.text)
    return answer.doc_type, "ai", Decimal(str(round(answer.confidence, 3)))


def page_titles(page: Page) -> set[str]:
    """Document types whose title appears on a title-like line at the top of the page."""
    found = set()
    for line in top_lines(page):
        text = line.casefold()
        if len(text.split()) > TITLE_MAX_WORDS or ":" in text or re.search(r"\d", text):
            continue
        squashed = "".join(text.split())
        found |= {doc_type for doc_type, title in _TITLES.items() if title.search(squashed)}
    return found


def top_lines(page: Page) -> list[str]:
    """The page's lines in the title zone, top to bottom, rebuilt from word positions (a PDF's
    text layer is in drawing order, which can put a footer first). A sheet has no positions:
    its first rows stand in."""
    if not page.words:
        return page.text.splitlines()[:5]
    words = sorted((w for w in page.words if w.y0 < TITLE_ZONE), key=lambda w: w.y0)
    lines: list[list[Word]] = []
    for word in words:
        if lines and abs(word.y0 - lines[-1][0].y0) <= _LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [" ".join(w.text for w in sorted(line, key=lambda w: w.x0)) for line in lines]
