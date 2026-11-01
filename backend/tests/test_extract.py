import pytest

from shipready.extract import (
    Box,
    DocumentText,
    FieldWithEvidence,
    RawField,
    extract_fields,
    field_guide,
    field_templates,
    locate,
)
from shipready.pages import Page, Word


def words(*texts: str) -> tuple[Word, ...]:
    """Words left to right on one line, each 0.1 wide."""
    return tuple(Word(t, 0.1 * i, 0.5, 0.1 * i + 0.09, 0.52) for i, t in enumerate(texts))


def test_locate_finds_the_words_of_a_quote() -> None:
    line = words("Invoice", "No.", "EXP/26-27/0663", "Dated", "22-10-2026")
    assert locate("EXP/26-27/0663", line) == pytest.approx((0.2, 0.5, 0.29, 0.52))
    assert locate("Invoice No.", line) == pytest.approx((0.0, 0.5, 0.19, 0.52))


def test_locate_ignores_how_ocr_joined_or_split_words() -> None:
    assert locate("COMMERCIAL INVOICE", words("COMMERCIALINVOICE")) is not None
    assert locate("AIRWAYBILL", words("AIR", "W", "AYBILL")) is not None
    assert locate("14,200", words("Qty", "14,200", "KGS")) is not None


def test_locate_prefers_whole_words() -> None:
    # The IEC is part of the GSTIN, which comes first on the page.
    line = words("GSTIN", "09CDOFS2603T1Z6", "IEC", "CDOFS2603T")
    assert locate("CDOFS2603T", line) == pytest.approx((0.3, 0.5, 0.39, 0.52))
    # Only inside another word: that is still the best evidence there is.
    assert locate("CDOFS", line) == pytest.approx((0.1, 0.5, 0.19, 0.52))


def test_quote_wrapped_in_a_table_cell_is_found_line_by_line() -> None:
    # The description wraps in its cell; OCR reads the row's quantity between its two lines.
    row = (
        Word("Granite", 0.1, 0.5, 0.2, 0.52),
        Word("slabs,", 0.21, 0.5, 0.3, 0.52),
        Word("120", 0.8, 0.5, 0.85, 0.52),
        Word("polished", 0.1, 0.53, 0.25, 0.55),
    )
    assert locate("Granite slabs,\npolished", row) == pytest.approx((0.1, 0.5, 0.3, 0.55))
    assert locate("Granite slabs,\nunpolished", row) is None


def test_locate_returns_none_when_the_quote_is_not_there() -> None:
    assert locate("PO-99999", words("PO-59375")) is None
    assert locate("   ", words("anything")) is None


def test_field_templates_follow_the_document_models() -> None:
    invoice = field_templates("commercial_invoice")
    assert invoice["invoice_date"] == "date, YYYY-MM-DD"
    assert invoice["lines[].quantity"] == "number, digits and a decimal point only"
    assert invoice["consignee.address.country"] == "ISO 3166 two-letter country code"
    assert invoice["consignee.address.lines[]"].startswith("text as printed; every address line")
    bill = field_templates("bill_of_lading")
    assert bill["freight_terms"] == "one of prepaid, collect"
    assert bill["containers[].size"] == "one of 20GP, 40GP"
    assert bill["to_order"].startswith("true or false; true only if")
    assert field_templates("other") == {}


def test_field_guide_lists_each_type() -> None:
    guide = field_guide(["lut", "packing_list"])
    assert guide.startswith("lut:\n  arn (text as printed)")
    assert "\npacking_list:\n" in guide


def document(part: int = 1, doc_type: str = "commercial_invoice") -> DocumentText:
    page = Page(1, "", words("Invoice", "No.", "EXP/26-27/0663"), "pdf_text", None)
    return DocumentText(part, doc_type, "invoice.pdf", (page,))


class FakeExtractor:
    model = "fake-model"

    def __init__(self, *fields: RawField) -> None:
        self.fields = list(fields)
        self.guides: list[str] = []

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        self.guides.append(guide)
        return self.fields


def test_extract_fields_keeps_known_paths_with_evidence() -> None:
    extractor = FakeExtractor(
        RawField(1, "invoice_number", "EXP/26-27/0663", "EXP/26-27/0663", 1),
        RawField(1, "lines[3].quantity", "120", "120", 1),  # on the page? no: no box
        RawField(1, "colour", "red", "red", 1),  # not a field of an invoice
        RawField(9, "invoice_number", "X", "X", 1),  # no such document
        RawField(1, "invoice_number", "OTHER", "OTHER", 1),  # a second answer for one path
        RawField(1, "iec", "  ", "", 1),  # empty
    )
    fields = extract_fields([document()], extractor)
    assert fields == [
        FieldWithEvidence(
            "commercial_invoice.invoice_number",
            "EXP/26-27/0663",
            "EXP/26-27/0663",
            1,
            1,
            Box(*locate("EXP/26-27/0663", document().pages[0].words) or (0, 0, 0, 0)),
        ),
        FieldWithEvidence("commercial_invoice.lines[3].quantity", "120", "120", 1, 1, None),
    ]
    assert extractor.guides[0].startswith("commercial_invoice:")


def test_quote_on_another_page_has_no_box() -> None:
    extractor = FakeExtractor(RawField(1, "invoice_number", "EXP/26-27/0663", "EXP/26-27/0663", 2))
    (field,) = extract_fields([document()], extractor)
    assert field.box is None


def test_nothing_to_read_asks_nothing() -> None:
    extractor = FakeExtractor()
    assert extract_fields([], extractor) == []
    assert extractor.guides == []
