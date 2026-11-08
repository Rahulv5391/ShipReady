"""Draw a document as a Word file (.docx), the way an exporter or buyer types one up by hand.

It follows the "word" house style of `common`: parties as paragraphs, one "Label: value" line per
field, tables with rules between rows, then totals, notes and the signatory. LibreOffice turns it
into a PDF when ShipReady reads it, so it tests the path real Word files take (Decision.md D-34).
"""

import io
import zipfile
from datetime import datetime
from decimal import Decimal

from docx import Document
from docx.document import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from shipgen.render.common import SPECIMEN_NOTE, Grid, Layout, Sheet, label, text

LAYOUT: Layout = "word"
# Every part of the file gets this date, so the same seed gives the same bytes.
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def sheet_docx(sheet: Sheet) -> bytes:
    document = Document()
    _page(document)
    title = document.add_paragraph()
    run = title.add_run(label(sheet.title, LAYOUT))
    run.bold, run.font.size = True, Pt(16)
    for key, lines in sheet.parties:
        block = document.add_paragraph()
        block.add_run(f"{label(key, LAYOUT)}:").bold = True
        for line in lines:
            block.add_run().add_break()
            block.add_run(line)
    for key, value in sheet.fields:
        document.add_paragraph(f"{label(key, LAYOUT)}: {text(value, LAYOUT)}")
    for grid in sheet.grids:
        _table(document, grid)
    for key, value in sheet.totals:
        total = document.add_paragraph(f"{label(key, LAYOUT)}: {text(value, LAYOUT)}")
        total.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for note in sheet.notes:
        document.add_paragraph(note)
    if sheet.signatory is not None:
        signature = document.add_paragraph()
        signature.add_run(sheet.signatory).bold = True
        signature.add_run().add_break()
        signature.add_run().add_break()
        signature.add_run("Authorised Signatory")
    _properties(document, label(sheet.title, LAYOUT))
    buffer = io.BytesIO()
    document.save(buffer)
    return _fixed_zip(buffer.getvalue())


def _page(document: WordDocument) -> None:
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Mm(15))
    normal = document.styles["Normal"].font
    normal.name, normal.size = "Times New Roman", Pt(10)
    footer = section.footer.paragraphs[0]
    footer.add_run(SPECIMEN_NOTE).font.size = Pt(7)


def _table(document: WordDocument, grid: Grid) -> None:
    table = document.add_table(rows=1, cols=len(grid.columns))
    for cell, key in zip(table.rows[0].cells, grid.columns, strict=True):
        cell.paragraphs[0].add_run(label(key, LAYOUT)).bold = True
    for row in grid.rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.text = text(value, LAYOUT)
            if isinstance(value, Decimal | int):
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _properties(document: WordDocument, title: str) -> None:
    properties = document.core_properties
    properties.title, properties.author = title, "ShipGen"
    properties.comments = SPECIMEN_NOTE
    properties.created = properties.modified = datetime(*FIXED_TIME)
    properties.last_modified_by, properties.revision = "ShipGen", 1


def _fixed_zip(data: bytes) -> bytes:
    """The file with every part dated FIXED_TIME: python-docx stamps parts with the time of
    saving, which would make each run's file differ."""
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(item))
    return output.getvalue()
