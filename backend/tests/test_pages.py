import io
import random
from functools import cache

import pytest
from openpyxl import Workbook
from PIL import Image

from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.render.degrade import pages as render_pages
from shipgen.render.degrade import scan, to_jpeg, to_pdf
from shipgen.render.sheets import render_pdf
from shipready import pages
from shipready.api.uploads import XLSX
from shipready.documents.models import CommercialInvoice
from shipready.pages import Page, read_pages


@cache
def invoice() -> CommercialInvoice:
    return build_documents(generate_shipment(11, 0)).commercial_invoice


@cache
def invoice_pdf() -> bytes:
    return render_pdf([("commercial_invoice", invoice(), "erp")], random.Random(0))


def test_pdf_text_layer_with_word_boxes() -> None:
    (page,) = read_pages(invoice_pdf(), "application/pdf")
    assert page.source == "pdf_text"
    assert invoice().invoice_number in page.text
    title = [w for w in page.words if w.text == "COMMERCIAL"]
    assert title and title[0].y0 < 0.1  # the title is at the top
    assert all(0 <= w.x0 < w.x1 <= 1 and 0 <= w.y0 < w.y1 <= 1 for w in page.words)
    assert page.image is not None and page.image.width > 1000


@cache
def scanned_page() -> Page:
    image = scan(render_pages(invoice_pdf(), 150)[0], random.Random(1))
    (page,) = read_pages(to_pdf([image], 150), "application/pdf")
    return page


def test_scanned_pdf_is_read_with_ocr() -> None:
    page = scanned_page()
    assert page.source == "ocr"
    assert invoice().invoice_number in page.text
    assert any(w.text.upper().startswith("COMMERCIAL") and w.y0 < 0.15 for w in page.words)


def test_photo_is_read_with_ocr() -> None:
    photo = render_pages(invoice_pdf(), 150)[0]
    (page,) = read_pages(to_jpeg(photo, random.Random(0)), "image/jpeg")
    assert page.source == "ocr"
    assert "COMMERCIAL INVOICE" in page.text.upper()


def test_every_tiff_frame_is_a_page() -> None:
    frames = [Image.new("RGB", (400, 300), "white") for _ in range(2)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])
    pages = read_pages(buffer.getvalue(), "image/tiff")
    assert [p.number for p in pages] == [1, 2]
    assert all(p.text == "" and p.words == () for p in pages)  # blank pages: no text


def test_workbook_sheets_are_pages_of_text() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["PACKING LIST"])
    sheet.append(["Invoice No.", "EXP/26-27/0001"])
    workbook.create_sheet("Containers").append(["MSKU1234565"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    pages = read_pages(buffer.getvalue(), XLSX)
    assert [(p.source, p.image) for p in pages] == [("cells", None), ("cells", None)]
    assert pages[0].text == "PACKING LIST\nInvoice No.  EXP/26-27/0001"
    assert pages[1].text == "MSKU1234565"


def test_unknown_media_type_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot read pages"):
        read_pages(b"x", "text/plain")


def test_upside_down_scan_is_turned_and_read() -> None:
    upright = render_pages(invoice_pdf(), 150)[0]
    image = scan(upright, random.Random(1), rotation=180)
    (page,) = read_pages(to_pdf([image], 150), "application/pdf")
    assert invoice().invoice_number in page.text
    # Turned the right way: the title is at the top again, and the stored image matches.
    assert any(w.text.upper().startswith("COMMERCIAL") and w.y0 < 0.15 for w in page.words)
    # The scan is re-rendered from the PDF, so its size may differ by a pixel of rounding.
    assert page.image is not None
    assert all(abs(a - b) <= 2 for a, b in zip(page.image.size, image.size, strict=True))


def test_upright_page_wrongly_voted_upside_down_stays_upright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The direction model can vote "upside down" on an upright page; the page is then read both
    # ways and the more confident reading kept.
    monkeypatch.setattr(pages, "_maybe_upside_down", lambda image, result: True)
    page = scanned_page.__wrapped__()
    assert any(w.text.upper().startswith("COMMERCIAL") and w.y0 < 0.15 for w in page.words)
