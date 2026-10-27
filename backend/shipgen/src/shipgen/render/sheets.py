"""What each document prints: one Sheet per document type, drawn by `common.compose`."""

import random
from collections.abc import Callable
from typing import Any

from shipgen.render.common import (
    Grid,
    Layout,
    Sheet,
    compose,
    country_name,
    party_lines,
    port_text,
    text,
)
from shipready.documents.models import (
    AirWaybill,
    BillOfLading,
    CertificateOfOrigin,
    CommercialInvoice,
    Container,
    InvoiceLine,
    LutAcknowledgement,
    PackingList,
    PurchaseOrder,
    ShippingBill,
)

_ITEM_COLUMNS = ("sr", "description", "hs_code", "quantity", "uqc", "unit_price", "amount")
_ITEM_WIDTHS = (0.7, 5, 1.5, 1.4, 0.9, 1.4, 1.8)
COO_STATEMENT = "It is hereby certified that the goods described above originate in India."
LUT_STATEMENT = (
    "Acknowledgement of the Letter of Undertaking furnished for export of goods or services "
    "without payment of integrated tax."
)


def _items(lines: tuple[InvoiceLine, ...]) -> Grid:
    rows = tuple(
        (i, line.description, line.hs_code, line.quantity, line.uqc, line.unit_price, line.amount)
        for i, line in enumerate(lines, start=1)
    )
    return Grid(_ITEM_COLUMNS, rows, _ITEM_WIDTHS)


def _containers(containers: tuple[Container, ...]) -> tuple[Grid, ...]:
    if not containers:
        return ()
    rows = tuple((i, c.number, c.seal, c.size) for i, c in enumerate(containers, start=1))
    return (Grid(("sr", "container", "seal", "size"), rows, (0.7, 3, 3, 1.5)),)


def _rate(rate: object, unit: int, currency: str, layout: Layout) -> str:
    return f"{unit} {currency} = INR {text(rate, layout)}"


def commercial_invoice(d: CommercialInvoice, layout: Layout) -> Sheet:
    return Sheet(
        title="commercial_invoice",
        parties=(("exporter", party_lines(d.exporter)), ("consignee", party_lines(d.consignee))),
        fields=(
            ("invoice_number", d.invoice_number),
            ("invoice_date", d.invoice_date),
            ("po_number", d.buyer_po_number),
            ("po_date", d.buyer_po_date),
            ("gstin", d.gstin),
            ("iec", d.iec),
            ("port_of_loading", port_text(d.port_of_loading)),
            ("port_of_discharge", port_text(d.port_of_discharge)),
            ("destination_country", country_name(d.destination_country)),
            ("incoterm", d.incoterm),
            ("payment_terms", d.payment_terms),
            ("currency", d.currency),
        ),
        grids=(_items(d.lines),),
        totals=(
            ("goods_value", d.goods_value),
            ("freight", d.freight),
            ("insurance", d.insurance),
            ("total", d.total),
            ("exchange_rate", _rate(d.exchange_rate, d.exchange_rate_unit, d.currency, layout)),
            ("total_inr", d.total_inr),
            ("lut_arn", d.lut_arn),
            ("bank_name", d.bank_name),
            ("ad_code", d.ad_code),
        ),
        notes=(d.gst_declaration,),
        signatory=f"For {d.exporter.name}",
    )


def packing_list(d: PackingList, layout: Layout) -> Sheet:
    rows = tuple(
        (
            i,
            line.description,
            line.quantity,
            line.uqc,
            line.packages,
            line.package_type,
            line.net_weight_kg,
            line.gross_weight_kg,
        )
        for i, line in enumerate(d.lines, start=1)
    )
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
    return Sheet(
        title="packing_list",
        parties=(("exporter", party_lines(d.exporter)), ("consignee", party_lines(d.consignee))),
        fields=(
            ("invoice_number", d.invoice_number),
            ("invoice_date", d.invoice_date),
            ("marks", d.marks),
        ),
        grids=(
            Grid(columns, rows, (0.7, 5, 1.3, 0.9, 1, 1, 1.5, 1.5)),
            *_containers(d.containers),
        ),
        totals=(
            ("total_packages", d.total_packages),
            ("net_weight_kg", d.net_weight_kg),
            ("gross_weight_kg", d.gross_weight_kg),
            ("volume_cbm", d.volume_cbm),
        ),
        signatory=f"For {d.exporter.name}",
    )


def purchase_order(d: PurchaseOrder, layout: Layout) -> Sheet:
    return Sheet(
        title="purchase_order",
        parties=(("buyer", party_lines(d.buyer)), ("seller", party_lines(d.seller))),
        fields=(
            ("po_number", d.po_number),
            ("po_date", d.po_date),
            ("currency", d.currency),
            ("incoterm", d.incoterm),
            ("payment_terms", d.payment_terms),
        ),
        grids=(_items(d.lines),),
        totals=(("total", d.total),),
        signatory=f"For {d.buyer.name}",
    )


def shipping_bill(d: ShippingBill, layout: Layout) -> Sheet:
    return Sheet(
        title="shipping_bill",
        fields=(
            ("shipping_bill_number", d.shipping_bill_number),
            ("shipping_bill_date", d.shipping_bill_date),
            ("port_code", d.port_code),
            ("exporter_name", d.exporter_name),
            ("iec", d.iec),
            ("gstin", d.gstin),
            ("ad_code", d.ad_code),
            ("consignee_name", d.consignee_name),
            ("consignee_country", country_name(d.consignee_country)),
            ("invoice_number", d.invoice_number),
            ("invoice_date", d.invoice_date),
            ("currency", d.currency),
            ("igst_payment_status", d.igst_payment_status),
            ("lut_arn", d.lut_arn),
        ),
        grids=(_items(d.lines), *_containers(d.containers)),
        totals=(
            ("invoice_value", d.invoice_value),
            ("fob_value", d.fob_value),
            ("exchange_rate", _rate(d.exchange_rate, d.exchange_rate_unit, d.currency, layout)),
            ("fob_inr", d.fob_inr),
            ("total_packages", d.total_packages),
            ("gross_weight_kg", d.gross_weight_kg),
        ),
    )


def bill_of_lading(d: BillOfLading, layout: Layout) -> Sheet:
    consignee = ("TO ORDER",) if d.to_order or d.consignee is None else party_lines(d.consignee)
    parties = [("shipper", party_lines(d.shipper)), ("consignee", consignee)]
    if d.notify_party is not None:
        parties.append(("notify_party", party_lines(d.notify_party)))
    goods = Grid(
        ("marks", "packages", "description", "gross_weight_kg", "volume_cbm"),
        ((d.marks, d.total_packages, d.goods_description, d.gross_weight_kg, d.volume_cbm),),
        (2, 1, 4, 1.5, 1.3),
    )
    return Sheet(
        title="bill_of_lading",
        parties=tuple(parties),
        fields=(
            ("bl_number", d.bl_number),
            ("vessel", d.vessel),
            ("voyage", d.voyage),
            ("port_of_loading", port_text(d.port_of_loading)),
            ("port_of_discharge", port_text(d.port_of_discharge)),
            ("freight_terms", f"Freight {d.freight_terms}"),
            ("shipped_on_board", d.shipped_on_board),
        ),
        grids=(goods, *_containers(d.containers)),
        signatory="For the Carrier",
    )


def air_waybill(d: AirWaybill, layout: Layout) -> Sheet:
    goods = Grid(
        ("packages", "gross_weight_kg", "chargeable_weight_kg", "description"),
        ((d.total_packages, d.gross_weight_kg, d.chargeable_weight_kg, d.goods_description),),
        (1, 1.5, 1.5, 5),
    )
    return Sheet(
        title="air_waybill",
        parties=(("shipper", party_lines(d.shipper)), ("consignee", party_lines(d.consignee))),
        fields=(
            ("awb_number", d.awb_number),
            ("airport_of_departure", port_text(d.airport_of_departure)),
            ("airport_of_destination", port_text(d.airport_of_destination)),
            ("flight", d.flight),
            ("flight_date", d.flight_date),
            ("freight_terms", f"Freight {d.freight_terms}"),
        ),
        grids=(goods,),
        signatory="For the Carrier",
    )


def certificate_of_origin(d: CertificateOfOrigin, layout: Layout) -> Sheet:
    rows = tuple(
        (i, line.description, line.hs_code, line.quantity, line.uqc)
        for i, line in enumerate(d.lines, start=1)
    )
    return Sheet(
        title="certificate_of_origin",
        parties=(("exporter", party_lines(d.exporter)), ("consignee", party_lines(d.consignee))),
        fields=(
            ("certificate_number", d.certificate_number),
            ("certificate_date", d.certificate_date),
            ("issuing_body", d.issuing_body),
            ("country_of_origin", country_name(d.country_of_origin)),
            ("destination_country", country_name(d.destination_country)),
            ("transport", d.transport),
            ("invoice_number", d.invoice_number),
            ("invoice_date", d.invoice_date),
        ),
        grids=(
            Grid(("sr", "description", "hs_code", "quantity", "uqc"), rows, (0.7, 6, 1.5, 1.5, 1)),
        ),
        notes=(COO_STATEMENT,),
        signatory=f"For {d.issuing_body}",
    )


def lut(d: LutAcknowledgement, layout: Layout) -> Sheet:
    return Sheet(
        title="lut",
        fields=(
            ("arn", d.arn),
            ("gstin", d.gstin),
            ("legal_name", d.legal_name),
            ("financial_year", d.financial_year),
            ("filed_on", d.filed_on),
        ),
        notes=(LUT_STATEMENT,),
    )


# Keyed by the ShipmentDocuments field each document comes from.
SHEETS: dict[str, Callable[[Any, Layout], Sheet]] = {
    "commercial_invoice": commercial_invoice,
    "packing_list": packing_list,
    "purchase_order": purchase_order,
    "shipping_bill": shipping_bill,
    "bill_of_lading": bill_of_lading,
    "air_waybill": air_waybill,
    "certificate_of_origin": certificate_of_origin,
    "lut": lut,
}


def render_pdf(parts: list[tuple[str, Any, Layout]], rng: random.Random) -> bytes:
    """One PDF of the documents given as (ShipmentDocuments field, document, layout)."""
    return compose(
        [(SHEETS[name](document, layout), layout) for name, document, layout in parts], rng
    )
