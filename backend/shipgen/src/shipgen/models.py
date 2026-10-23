"""The golden shipment: the ground truth every generated document is derived from."""

from datetime import date
from decimal import Decimal
from typing import Literal

from shipready.documents.models import Container, Model, Party, Port

Mode = Literal["sea", "air"]
FreightTerms = Literal["prepaid", "collect"]


class Exporter(Party):
    gstin: str
    pan: str
    iec: str
    bank_name: str
    ad_code: str


class Lut(Model):
    """GST Letter of Undertaking that lets the exporter ship without paying IGST."""

    arn: str
    financial_year: str  # e.g. "2026-27"
    filed_on: date


class LineItem(Model):
    line_no: int
    sku: str
    description: str
    hs_code: str
    quantity: Decimal
    uqc: str
    unit_price: Decimal
    amount: Decimal
    packages: int
    package_type: str
    net_weight_kg: Decimal
    gross_weight_kg: Decimal
    volume_cbm: Decimal


class Transport(Model):
    mode: Mode
    port_of_loading: Port
    port_of_discharge: Port
    carrier_reference: str  # bill of lading number (sea) or airway bill number (air)
    vessel_or_flight: str
    voyage: str | None  # sea only
    containers: tuple[Container, ...]  # empty for air
    departure_date: date  # shipped on board / flight date


class Shipment(Model):
    shipment_id: str
    exporter: Exporter
    lut: Lut
    consignee: Party
    notify_party: Party | None
    to_order: bool  # bill of lading consigned "to order" (bank-controlled title)
    destination_country: str

    po_number: str
    po_date: date
    invoice_number: str
    invoice_date: date
    shipping_bill_number: str
    shipping_bill_date: date
    coo_number: str
    coo_date: date

    incoterm: str
    incoterm_place: str
    freight_terms: FreightTerms
    payment_terms: str

    currency: str
    exchange_rate: Decimal  # INR per `exchange_rate_unit` units, CBIC export rate
    exchange_rate_unit: int
    exchange_notification: str

    lines: tuple[LineItem, ...]
    goods_value: Decimal  # sum of line amounts; equals the FOB value
    freight: Decimal
    insurance: Decimal
    invoice_total: Decimal
    fob_inr: Decimal
    invoice_total_inr: Decimal

    total_packages: int
    net_weight_kg: Decimal
    gross_weight_kg: Decimal
    volume_cbm: Decimal
    marks: str

    transport: Transport

    @property
    def exporter_party(self) -> Party:
        """The exporter as documents print it: name and address only."""
        return Party(name=self.exporter.name, address=self.exporter.address)
