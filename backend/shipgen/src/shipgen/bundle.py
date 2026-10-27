"""Write a case's documents as the files an exporter would receive: digital PDFs, scans, phone
photos and Excel packing lists, sometimes several documents scanned into one PDF.

The files are drawn from the case's documents, which already carry its errors and look-alikes,
so they match its labels. A document a DOC-01 label marks missing is left out.
"""

import random
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium

from shipgen.mutations import Label, missing_documents
from shipgen.render.common import LAYOUTS, Layout
from shipgen.render.degrade import pages, photo, scan, to_jpeg, to_pdf
from shipgen.render.sheets import render_pdf
from shipgen.render.workbook import packing_list_xlsx
from shipready.documents.models import Model, ShipmentDocuments

Format = Literal["pdf", "scan", "photo", "xlsx"]
# PLAN.md Section 15.1: about 40% digital, 40% scanned, 20% photos or Excel.
DIGITAL_SHARE = 0.4
SCAN_SHARE = 0.4
MERGE_SHARE = 0.2  # cases where several documents arrive scanned or saved into one PDF
UPSIDE_DOWN_SHARE = 0.05  # scanned pages fed the wrong way round
DPI = 150
# Issued by the exporter's own software, so they share one layout.
EXPORTER_DOCUMENTS = ("commercial_invoice", "packing_list")


class BundleFile(Model):
    path: str  # relative to the case folder
    documents: tuple[str, ...]  # ShipmentDocuments fields, in page order
    format: Format
    layouts: tuple[Layout, ...]  # one per document; empty for an Excel file
    pages: int
    rotation: int = 0  # degrees a scanned page is turned


class Bundle(Model):
    files: tuple[BundleFile, ...]
    missing: tuple[str, ...]  # documents left out for a DOC-01 label


def write_bundle(
    shipment_id: str, documents: ShipmentDocuments, labels: tuple[Label, ...], folder: Path
) -> Bundle:
    rng = random.Random(f"{shipment_id}:bundle")
    missing = missing_documents(labels)
    names = [
        name
        for name in type(documents).model_fields
        if getattr(documents, name) is not None and name not in missing
    ]
    exporter_layout = rng.choice(LAYOUTS)
    layouts: dict[str, Layout] = {
        name: exporter_layout if name in EXPORTER_DOCUMENTS else rng.choice(LAYOUTS)
        for name in names
    }
    formats = {name: _format(name, rng) for name in names}

    groups = [[name] for name in names]
    if rng.random() < MERGE_SHARE:
        groups = _merge(groups, formats, rng)

    folder.mkdir(parents=True, exist_ok=True)
    files: list[BundleFile] = []

    def add(
        path: str, data: bytes, group: list[str], kind: Format, count: int, turn: int = 0
    ) -> None:
        (folder / path).write_bytes(data)
        # An Excel packing list has its own fixed layout.
        used = () if kind == "xlsx" else tuple(layouts[name] for name in group)
        files.append(
            BundleFile(
                path=path,
                documents=tuple(group),
                format=kind,
                layouts=used,
                pages=count,
                rotation=turn,
            )
        )

    for group in groups:
        first, kind = group[0], formats[group[0]]
        pdf = b""
        if kind != "xlsx":
            pdf = render_pdf(
                [(name, getattr(documents, name), layouts[name]) for name in group], rng
            )
        if kind == "xlsx":
            add(f"{first}.xlsx", packing_list_xlsx(documents.packing_list), group, kind, 1)
        elif kind == "pdf":
            stem = first if len(group) == 1 else "documents"
            add(f"{stem}.pdf", pdf, group, kind, len(pdfium.PdfDocument(pdf)))
        elif kind == "scan":
            turn = 180 if rng.random() < UPSIDE_DOWN_SHARE else 0
            images = [scan(page, rng, turn) for page in pages(pdf, DPI)]
            stem = f"{first}_scan" if len(group) == 1 else "scanned_documents"
            add(f"{stem}.pdf", to_pdf(images, DPI), group, kind, len(images), turn)
        else:
            for number, page in enumerate(pages(pdf, DPI), start=1):
                add(f"{first}_photo_{number}.jpg", to_jpeg(photo(page, rng), rng), group, kind, 1)
    bundle = Bundle(files=tuple(files), missing=tuple(sorted(missing)))
    (folder / "bundle.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle


def _format(name: str, rng: random.Random) -> Format:
    draw = rng.random()
    if draw < DIGITAL_SHARE:
        return "pdf"
    if draw < DIGITAL_SHARE + SCAN_SHARE:
        return "scan"
    return "xlsx" if name == "packing_list" and rng.random() < 0.5 else "photo"


def _merge(
    groups: list[list[str]], formats: dict[str, Format], rng: random.Random
) -> list[list[str]]:
    """Put 2-3 documents of the same kind (all scanned, or all digital PDFs) into one file."""
    for kind in rng.sample(["scan", "pdf"], 2):
        same = [group[0] for group in groups if formats[group[0]] == kind]
        if len(same) >= 2:
            chosen = rng.sample(same, min(len(same), rng.randint(2, 3)))
            rest = [group for group in groups if group[0] not in chosen]
            return [*rest, chosen]
    return groups
