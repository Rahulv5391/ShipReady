import io
import random
from functools import cache

import pypdfium2 as pdfium
from PIL import Image

from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.render.degrade import pages, photo, scan, to_jpeg, to_pdf
from shipgen.render.sheets import render_pdf

DPI = 100


@cache
def page() -> Image.Image:
    invoice = build_documents(generate_shipment(11, 0)).commercial_invoice
    pdf = render_pdf([("commercial_invoice", invoice, "erp")], random.Random(0))
    (first,) = pages(pdf, DPI)
    return first


def test_pages_renders_each_page_at_the_resolution() -> None:
    width, height = page().size
    # A4 is 210 x 297 mm.
    assert abs(width - 210 / 25.4 * DPI) <= 1
    assert abs(height - 297 / 25.4 * DPI) <= 1
    assert page().mode == "RGB"


def test_scan_is_grey_skewed_and_reproducible() -> None:
    scanned = scan(page(), random.Random(1))
    assert scanned.mode == "L"
    assert scanned.size != page().size  # the skew grows the canvas
    assert scanned.tobytes() == scan(page(), random.Random(1)).tobytes()
    assert scanned.tobytes() != scan(page(), random.Random(2)).tobytes()


def test_scan_can_turn_the_page_upside_down() -> None:
    upright = scan(page(), random.Random(1))
    turned = scan(page(), random.Random(1), rotation=180)
    assert turned.size == upright.size
    # The title is at the top of an upright page and at the bottom of a turned one.
    top = (0, 0, upright.width, upright.height // 8)
    bottom = (0, upright.height * 7 // 8, upright.width, upright.height)
    assert _ink(upright.crop(top)) > _ink(upright.crop(bottom))
    assert _ink(turned.crop(bottom)) > _ink(turned.crop(top))


def test_photo_is_colour_with_a_desk_around_the_page() -> None:
    taken = photo(page(), random.Random(3))
    assert taken.mode == "RGB"
    assert taken.width > page().width and taken.height > page().height
    corner = taken.getpixel((2, 2))
    assert isinstance(corner, tuple) and max(corner) < 200  # desk, not paper
    assert taken.tobytes() == photo(page(), random.Random(3)).tobytes()


def test_scanned_pdf_has_pages_but_no_text() -> None:
    images = [scan(page(), random.Random(seed)) for seed in range(2)]
    document = pdfium.PdfDocument(to_pdf(images, DPI))
    assert len(document) == 2
    assert all(p.get_textpage().get_text_range().strip() == "" for p in document)
    assert to_pdf(images, DPI) == to_pdf(images, DPI)


def test_jpeg_decodes() -> None:
    data = to_jpeg(photo(page(), random.Random(4)), random.Random(4))
    assert Image.open(io.BytesIO(data)).format == "JPEG"


def _ink(image: Image.Image) -> int:
    """Number of dark pixels."""
    return sum(image.convert("L").histogram()[:100])
