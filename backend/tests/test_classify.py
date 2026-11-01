from decimal import Decimal

import pytest

from shipready.ai import AiAnswer
from shipready.classify import Part, page_titles, split_into_parts, top_lines
from shipready.pages import Page, Word


def line(text: str, top: float, left: float = 0.1) -> list[Word]:
    """Words of one line at height `top`, laid out left to right."""
    words, x = [], left
    for word in text.split():
        words.append(Word(word, x, top, x + 0.01 * len(word), top + 0.015))
        x += 0.01 * len(word) + 0.01
    return words


def page(number: int, *lines: tuple[str, float]) -> Page:
    words = tuple(w for text, top in lines for w in line(text, top))
    text = "\n".join(text for text, _ in lines)
    return Page(number, text, words, "pdf_text", None)


class FakeAi:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def classify(self, page_text: str) -> AiAnswer:
        self.asked.append(page_text)
        return AiAnswer(self.answers.pop(0), 0.9)


def test_title_at_the_top_decides() -> None:
    invoice = page(1, ("COMMERCIAL INVOICE", 0.05), ("Exporter: Som Overseas", 0.1))
    assert page_titles(invoice) == {"commercial_invoice"}
    assert page_titles(page(1, ("Export Invoice", 0.04))) == {"commercial_invoice"}


@pytest.mark.parametrize(
    ("text", "top"),
    [
        ("Purchase Order No.: PO-59375", 0.1),  # a field, not a title
        ("Bill of Lading Number SGL695836043", 0.1),  # has figures
        ("Supply meant for export under bond or letter of undertaking without IGST", 0.1),
        ("PACKING LIST", 0.8),  # too low on the page
        ("PROFORMA INVOICE", 0.05),  # not a commercial invoice
    ],
)
def test_lines_that_are_not_titles(text: str, top: float) -> None:
    assert page_titles(page(1, (text, top))) == set()


def test_two_different_titles_are_not_decided_by_rules() -> None:
    both = page(1, ("COMMERCIAL INVOICE", 0.05), ("PACKING LIST", 0.08))
    assert page_titles(both) == {"commercial_invoice", "packing_list"}
    (part,) = split_into_parts([both], "never", None)
    assert (part.doc_type, part.decided_by) == ("other", "none")


def test_lines_are_rebuilt_from_word_positions() -> None:
    # A text layer in drawing order: footer first, and a title's words out of order.
    words = (
        Word("Specimen", 0.1, 0.96, 0.2, 0.97),
        Word("LADING", 0.5, 0.051, 0.6, 0.06),
        Word("BILL", 0.3, 0.05, 0.35, 0.06),
        Word("OF", 0.4, 0.052, 0.45, 0.06),
        Word("Shipper:", 0.1, 0.1, 0.2, 0.11),
    )
    lines = top_lines(Page(1, "", words, "pdf_text", None))
    assert lines == ["BILL OF LADING", "Shipper:"]


def test_sheet_without_word_boxes_uses_its_first_rows() -> None:
    sheet = Page(1, "PACKING LIST\nExporter\nKata Impex", (), "cells", None)
    assert page_titles(sheet) == {"packing_list"}


def test_untitled_page_continues_the_document_before_it() -> None:
    pages = [
        page(1, ("PACKING LIST", 0.05)),
        page(2, ("Line items continued", 0.05)),
        page(3, ("BILL OF LADING", 0.05)),
    ]
    assert split_into_parts(pages, "never", None) == [
        Part(1, 2, "packing_list", "title", None),
        Part(3, 3, "bill_of_lading", "title", None),
    ]


def test_ai_is_asked_only_for_what_rules_cannot_decide() -> None:
    ai = FakeAi("certificate_of_origin")
    pages = [page(1, ("Certificado", 0.05)), page(2, ("continued", 0.05))]
    parts = split_into_parts(pages, "fallback", ai)
    assert parts == [Part(1, 2, "certificate_of_origin", "ai", Decimal("0.9"))]
    assert len(ai.asked) == 1
    titled = FakeAi()
    split_into_parts([page(1, ("SHIPPING BILL", 0.05))], "fallback", titled)
    assert titled.asked == []


def test_without_ai_an_untitled_first_page_is_other() -> None:
    (part,) = split_into_parts([page(1, ("Certificado", 0.05))], "never", None)
    assert part == Part(1, 1, "other", "none", None)


def test_always_asks_the_ai_for_every_page_and_merges_runs() -> None:
    ai = FakeAi("packing_list", "packing_list", "lut")
    pages = [page(n, ("PACKING LIST", 0.05)) for n in (1, 2, 3)]
    assert split_into_parts(pages, "always", ai) == [
        Part(1, 2, "packing_list", "ai", Decimal("0.9")),
        Part(3, 3, "lut", "ai", Decimal("0.9")),
    ]
    assert len(ai.asked) == 3


def test_ai_modes_need_a_classifier() -> None:
    with pytest.raises(ValueError, match="needs an AI classifier"):
        split_into_parts([page(1, ("x", 0.05))], "fallback", None)


def test_title_joined_by_ocr_still_counts() -> None:
    assert page_titles(page(1, ("COMMERCIALINVOICE", 0.06))) == {"commercial_invoice"}
    assert page_titles(page(1, ("BILLOFLADING", 0.06))) == {"bill_of_lading"}


def test_title_split_by_ocr_still_counts() -> None:
    assert page_titles(page(1, ("AIR W AYBILL", 0.06))) == {"air_waybill"}
