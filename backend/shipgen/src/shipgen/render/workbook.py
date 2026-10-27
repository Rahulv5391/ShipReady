"""A packing list as an Excel workbook, the way exporters often send it: numbers and dates as
real cells, not text."""

import io
import zipfile
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Font

from shipgen.render.common import SPECIMEN_NOTE, Layout, label, party_lines
from shipready.documents.models import PackingList

_LAYOUT: Layout = "erp"
_DATE_FORMAT = "DD-MM-YYYY"
_FIXED_TIME = datetime(2026, 1, 1)
# openpyxl stamps the time of saving into the document properties, so they are replaced.
_PROPERTIES = (
    b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
    b'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    b'xmlns:dcterms="http://purl.org/dc/terms/" '
    b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>ShipGen</dc:creator>'
    b'<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
    b'<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
    b"</cp:coreProperties>"
)


def packing_list_xlsx(d: PackingList) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("openpyxl created a workbook without a sheet")
    sheet.title = "Packing List"
    bold = Font(bold=True)

    def row(*values: object, strong: bool = False) -> None:
        sheet.append(list(values))
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, date):
                cell.number_format = _DATE_FORMAT
            if strong:
                cell.font = bold

    row(label("packing_list", _LAYOUT), strong=True)
    for key, party in (("exporter", d.exporter), ("consignee", d.consignee)):
        row(label(key, _LAYOUT), strong=True)
        for party_line in party_lines(party):
            row(party_line)
    row()
    row(label("invoice_number", _LAYOUT), d.invoice_number)
    row(label("invoice_date", _LAYOUT), d.invoice_date)
    row(label("marks", _LAYOUT), d.marks)
    row()
    columns = (
        "sr",
        "description",
        "quantity",
        "uqc",
        "packages",
        "package_type",
        "net_weight_kg",
        "gross_weight_kg",
    )
    row(*(label(key, _LAYOUT) for key in columns), strong=True)
    for i, line in enumerate(d.lines, start=1):
        row(
            i,
            line.description,
            line.quantity,
            line.uqc,
            line.packages,
            line.package_type,
            line.net_weight_kg,
            line.gross_weight_kg,
        )
    row()
    for key, value in (
        ("total_packages", d.total_packages),
        ("net_weight_kg", d.net_weight_kg),
        ("gross_weight_kg", d.gross_weight_kg),
        ("volume_cbm", d.volume_cbm),
    ):
        row(label(key, _LAYOUT), value)
    if d.containers:
        row()
        row(*(label(key, _LAYOUT) for key in ("sr", "container", "seal", "size")), strong=True)
        for i, container in enumerate(d.containers, start=1):
            row(i, container.number, container.seal, container.size)
    row()
    row(SPECIMEN_NOTE)
    sheet.column_dimensions["B"].width = 45

    buffer = io.BytesIO()
    workbook.save(buffer)
    return _fixed_zip_times(buffer.getvalue())


def _fixed_zip_times(data: bytes) -> bytes:
    """The workbook with fixed times in its properties and zip entries instead of the time of
    saving, so the same seed gives the same bytes."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            fixed = zipfile.ZipInfo(entry.filename, date_time=_FIXED_TIME.timetuple()[:6])
            fixed.compress_type = zipfile.ZIP_DEFLATED
            content = source.read(entry)
            if entry.filename == "docProps/core.xml":
                content = _PROPERTIES
            target.writestr(fixed, content)
    return buffer.getvalue()
