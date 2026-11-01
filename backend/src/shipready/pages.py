"""Read an uploaded file as pages: an image of each page, its text and every word's box.

A PDF's own text layer is used when it has one; a scanned page, a photo or a page with almost no
text is read with OCR (RapidOCR). An Excel workbook gives one page per sheet, text only. Word
boxes are fractions of the page (0..1 from the top left), so they fit the image at any size.
"""

import io
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

import numpy as np
import pypdfium2 as pdfium
from openpyxl import load_workbook
from PIL import Image, ImageOps, ImageSequence
from rapidocr import RapidOCR
from rapidocr.ch_ppocr_cls import TextClsOutput
from rapidocr.utils.output import RapidOCROutput

from shipready.api.uploads import XLSX

TextSource = Literal["pdf_text", "ocr", "cells"]
RENDER_DPI = 150
# A page with fewer characters than this in its text layer is treated as a scan.
MIN_TEXT_CHARS = 30
# Text lines whose direction decides whether a scanned page is upside down.
ORIENTATION_SAMPLE_LINES = 9


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Page:
    number: int  # from 1
    text: str  # lines in reading order, separated by newlines
    words: tuple[Word, ...]
    source: TextSource
    image: Image.Image | None  # none for a workbook sheet


def read_pages(data: bytes, media_type: str) -> list[Page]:
    if media_type == "application/pdf":
        return _pdf_pages(data)
    if media_type == XLSX:
        return _sheet_pages(data)
    if media_type.startswith("image/"):
        return _image_pages(data)
    raise ValueError(f"cannot read pages of {media_type}")


def _pdf_pages(data: bytes) -> list[Page]:
    document = pdfium.PdfDocument(data)
    try:
        pages = []
        for number, page in enumerate(document, start=1):
            image = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
            textpage = page.get_textpage()
            text = textpage.get_text_range().replace("\r\n", "\n").strip()
            if len(text) >= MIN_TEXT_CHARS:
                words = _pdf_words(textpage, *page.get_size())
                pages.append(Page(number, text, words, "pdf_text", image))
            else:
                pages.append(_ocr_page(number, image))
        return pages
    finally:
        document.close()


def _pdf_words(textpage: pdfium.PdfTextPage, width: float, height: float) -> tuple[Word, ...]:
    """Group the text layer's characters into words, with each word's box."""
    words: list[Word] = []
    chars: list[str] = []
    box: list[float] = []

    def flush() -> None:
        if chars:
            left, bottom, right, top = box
            words.append(
                Word(
                    "".join(chars),
                    left / width,
                    1 - top / height,
                    right / width,
                    1 - bottom / height,
                )
            )
            chars.clear()

    for index in range(textpage.count_chars()):
        char = textpage.get_text_range(index, 1)
        if not char or char.isspace():
            flush()
            continue
        left, bottom, right, top = textpage.get_charbox(index)
        if chars:
            box = [min(box[0], left), min(box[1], bottom), max(box[2], right), max(box[3], top)]
        else:
            box = [left, bottom, right, top]
        chars.append(char)
    flush()
    return tuple(words)


def _image_pages(data: bytes) -> list[Page]:
    with Image.open(io.BytesIO(data)) as picture:
        frames = [
            ImageOps.exif_transpose(frame.convert("RGB"))
            for frame in ImageSequence.Iterator(picture)
        ]
    return [_ocr_page(number, frame) for number, frame in enumerate(frames, start=1)]


def _ocr_page(number: int, image: Image.Image) -> Page:
    result = _read_text(image)
    if _maybe_upside_down(image, result):
        # The direction model can be wrong on an upright page, so the page is also read
        # turned, and the reading the OCR is more confident in wins. A turned page is kept
        # turned, so the word boxes match the stored image.
        turned = image.rotate(180)
        turned_result = _read_text(turned)
        if _confidence(turned_result) > _confidence(result):
            image, result = turned, turned_result
    lines = list(result.txts or ())
    words = tuple(word for line in _word_lines(result) for word in _ocr_words(line, *image.size))
    return Page(number, "\n".join(lines), words, "ocr", image)


def _read_text(image: Image.Image) -> RapidOCROutput:
    # Every option is passed on each call: RapidOCR keeps options from one call to the next.
    result = _ocr_engine()(image, use_det=True, use_cls=True, use_rec=True, return_word_box=True)
    if not isinstance(result, RapidOCROutput):
        raise TypeError(f"unexpected OCR result {type(result).__name__}")
    return result


def _confidence(result: RapidOCROutput) -> float:
    """The OCR's mean confidence over the page's lines (0 for a page without text)."""
    scores = list(result.scores or ())
    return sum(scores) / len(scores) if scores else 0.0


def _maybe_upside_down(image: Image.Image, result: RapidOCROutput) -> bool:
    """Whether most of the widest text lines read upside down, by RapidOCR's text direction
    model on each line's crop. Reading a whole upside-down page gives lines in reverse order,
    so a title would appear at the bottom."""
    if result.boxes is None or len(result.boxes) == 0:
        return False
    widest = sorted(result.boxes, key=lambda box: box[:, 0].min() - box[:, 0].max())
    votes = []
    for box in widest[:ORIENTATION_SAMPLE_LINES]:
        crop = image.crop(
            (int(box[:, 0].min()), int(box[:, 1].min()), int(box[:, 0].max()), int(box[:, 1].max()))
        )
        direction = _ocr_engine()(np.asarray(crop), use_det=False, use_cls=True, use_rec=False)
        if isinstance(direction, TextClsOutput) and direction.cls_res:
            votes.append(direction.cls_res[0][0] == "180")
    return sum(votes) > len(votes) / 2


def _word_lines(result: RapidOCROutput) -> Iterable[Any]:
    # RapidOCR annotates word_results as one flat tuple, but returns a tuple per text line of
    # (word, score, corner points) tuples.
    lines: Iterable[Any] = result.word_results if result.txts else ()
    return lines


def _ocr_words(line: Iterable[Any], width: int, height: int) -> list[Word]:
    words = []
    for text, _score, corners in line:
        if not str(text).strip() or not corners:
            continue
        xs, ys = [float(x) for x, _ in corners], [float(y) for _, y in corners]
        words.append(
            Word(str(text), min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height)
        )
    return words


@cache
def _ocr_engine() -> RapidOCR:
    # Loading the models takes a second or two, so one engine serves every page.
    return RapidOCR()


def _sheet_pages(data: bytes) -> list[Page]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        pages = []
        for number, sheet in enumerate(workbook.worksheets, start=1):
            lines = [
                "  ".join(str(value) for value in row if value is not None)
                for row in sheet.iter_rows(values_only=True)
            ]
            text = "\n".join(line for line in lines if line)
            pages.append(Page(number, text, (), "cells", None))
        return pages
    finally:
        workbook.close()
