"""Reading a file's pages (OCR) takes seconds a page, and evaluations read the same files on every
run. So pages are kept on disk, keyed by the file's checksum and a fingerprint of the reading code
and OCR engine: a change to either reads the files afresh, so a cached page is never stale.

Cached pages carry no image; the evaluation pipelines use the text and word boxes only.
"""

import hashlib
import json
from dataclasses import asdict, replace
from functools import cache
from importlib import metadata, resources
from pathlib import Path

from shipready.pages import Page, Word, read_pages, text_source


@cache
def reader_fingerprint() -> str:
    """Changes whenever the page reader's code or the OCR and PDF libraries change."""
    digest = hashlib.sha256(resources.files("shipready").joinpath("pages.py").read_bytes())
    for package in ("rapidocr", "onnxruntime", "pypdfium2"):
        digest.update(f"{package}=={metadata.version(package)}".encode())
    return digest.hexdigest()[:16]


def cached_pages(data: bytes, media_type: str, directory: Path) -> list[Page]:
    path = directory / f"{hashlib.sha256(data).hexdigest()}-{reader_fingerprint()}.json"
    if path.is_file():
        return [_page(entry) for entry in json.loads(path.read_text(encoding="utf-8"))]
    pages = [replace(page, image=None) for page in read_pages(data, media_type)]
    directory.mkdir(parents=True, exist_ok=True)
    # Written beside and then moved, so a run stopped mid-write leaves no half file to read.
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps([asdict(page) for page in pages]), encoding="utf-8")
    partial.replace(path)
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
