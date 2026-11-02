"""Reading a file's pages (OCR) takes seconds a page, and evaluations read the same files on every
run. So pages are kept on disk, keyed by the file's checksum and a fingerprint of the reading code
and OCR engine: a change to either reads the files afresh, so a cached page is never stale.

Pages are kept as text and word boxes; their images, which the critic looks at, as JPEG files
beside them.
"""

import hashlib
import json
from dataclasses import asdict, replace
from functools import cache
from importlib import metadata, resources
from pathlib import Path

from PIL import Image

from shipready.pages import Page, Word, read_pages, text_source


@cache
def reader_fingerprint() -> str:
    """Changes whenever the page reader's code or the OCR and PDF libraries change."""
    digest = hashlib.sha256(resources.files("shipready").joinpath("pages.py").read_bytes())
    for package in ("rapidocr", "onnxruntime", "pypdfium2"):
        digest.update(f"{package}=={metadata.version(package)}".encode())
    return digest.hexdigest()[:16]


def cached_pages(data: bytes, media_type: str, directory: Path) -> list[Page]:
    path = _stem(data, directory).with_suffix(".json")
    if path.is_file():
        return [_page(entry) for entry in json.loads(path.read_text(encoding="utf-8"))]
    return _read_and_keep(data, media_type, directory)


def page_image(data: bytes, media_type: str, number: int, directory: Path) -> Image.Image | None:
    """Page `number`'s image, turned as it was read, so word boxes match it; None for a sheet.
    Pages cached before images were kept are read again once."""
    image = _stem(data, directory).with_name(f"{_stem(data, directory).name}-p{number}.jpg")
    if not image.is_file():
        pages = {page.number: page for page in cached_pages(data, media_type, directory)}
        if pages[number].source == "cells":
            return None
        _read_and_keep(data, media_type, directory)
    return Image.open(image)


def _stem(data: bytes, directory: Path) -> Path:
    return directory / f"{hashlib.sha256(data).hexdigest()}-{reader_fingerprint()}"


def _read_and_keep(data: bytes, media_type: str, directory: Path) -> list[Page]:
    read = read_pages(data, media_type)
    stem = _stem(data, directory)
    directory.mkdir(parents=True, exist_ok=True)
    for page in read:
        if page.image is not None:
            page.image.save(stem.with_name(f"{stem.name}-p{page.number}.jpg"), quality=90)
    pages = [replace(page, image=None) for page in read]
    # Written beside and then moved, so a run stopped mid-write leaves no half file to read.
    partial = stem.with_suffix(".part")
    partial.write_text(json.dumps([asdict(page) for page in pages]), encoding="utf-8")
    partial.replace(stem.with_suffix(".json"))
    return pages


def _page(entry: dict[str, object]) -> Page:
    words = entry["words"]
    if not isinstance(words, list):
        raise ValueError(f"unreadable cached page {str(entry)[:80]}")
    return Page(
        number=int(str(entry["number"])),
        text=str(entry["text"]),
        words=tuple(Word(**word) for word in words),
        source=text_source(entry["source"]),
        image=None,
    )
