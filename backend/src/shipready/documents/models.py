"""What each export document contains: the fields ShipReady extracts and checks.

ShipGen fills these from its golden shipments; extraction (Phase 11) fills them from real
documents.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Address(Model):
    lines: tuple[str, ...]
    city: str
    country: str  # ISO 3166 alpha-2


class Party(Model):
    name: str
    address: Address


class Container(Model):
    number: str
    seal: str
    size: Literal["20GP", "40GP"]


class Port(Model):
    code: str  # ICEGATE code for Indian ports, UN/LOCODE otherwise
    name: str
    country: str


class InvoiceLine(Model):
    description: str
    hs_code: str
    quantity: Decimal
    uqc: str
    unit_price: Decimal
    amount: Decimal


class PackingLine(Model):
    description: str
    quantity: Decimal
    uqc: str
    packages: int
    package_type: str
    net_weight_kg: Decimal
    gross_weight_kg: Decimal


class GoodsLine(Model):
    description: str
    hs_code: str
    quantity: Decimal
    uqc: str


class CommercialInvoice(Model):
    invoice_number: str
    invoice_date: date
    exporter: Party
    gstin: str
    iec: str
    consignee: Party
    buyer_po_number: str
    buyer_po_date: date
    lines: tuple[InvoiceLine, ...]
    currency: str
    goods_value: Decimal
    freight: Decimal
    insurance: Decimal
    total: Decimal
    exchange_rate: Decimal
    exchange_rate_unit: int
    total_inr: Decimal
    incoterm: str  # e.g. "CIF Rotterdam"
    payment_terms: str
    port_of_loading: Port
    port_of_discharge: Port
    destination_country: str
    gst_declaration: str
    lut_arn: str
    bank_name: str
    ad_code: str


class PackingList(Model):
    invoice_number: str
    invoice_date: date
    exporter: Party
    consignee: Party
    lines: tuple[PackingLine, ...]
    total_packages: int
    net_weight_kg: Decimal
    gross_weight_kg: Decimal
    volume_cbm: Decimal
    marks: str
    containers: tuple[Container, ...]


class PurchaseOrder(Model):
    po_number: str
    po_date: date
    buyer: Party
    seller: Party
    lines: tuple[InvoiceLine, ...]
    currency: str
    total: Decimal
    incoterm: str
    payment_terms: str


class ShippingBill(Model):
    shipping_bill_number: str
    shipping_bill_date: date
    port_code: str
    exporter_name: str
    iec: str
    gstin: str
    ad_code: str
    consignee_name: str
    consignee_country: str
    invoice_number: str
    invoice_date: date
    lines: tuple[InvoiceLine, ...]
    currency: str
    invoice_value: Decimal
    fob_value: Decimal
    exchange_rate: Decimal
    exchange_rate_unit: int
    fob_inr: Decimal
    total_packages: int
    gross_weight_kg: Decimal
    containers: tuple[Container, ...]
    igst_payment_status: str  # "LUT": exported under a Letter of Undertaking
    lut_arn: str


class BillOfLading(Model):
    bl_number: str
    shipper: Party
    consignee: Party | None  # None when consigned "to order"
    to_order: bool
    notify_party: Party | None
    vessel: str
    voyage: str
    port_of_loading: Port
    port_of_discharge: Port
    containers: tuple[Container, ...]
    total_packages: int
    goods_description: str
    gross_weight_kg: Decimal
    volume_cbm: Decimal
    marks: str
    freight_terms: str
    shipped_on_board: date


class AirWaybill(Model):
    awb_number: str
    shipper: Party
    consignee: Party
    airport_of_departure: Port
    airport_of_destination: Port
    flight: str
    flight_date: date
    total_packages: int
    gross_weight_kg: Decimal
    chargeable_weight_kg: Decimal
    goods_description: str
    freight_terms: str


class CertificateOfOrigin(Model):
    certificate_number: str
    certificate_date: date
    issuing_body: str
    exporter: Party
    consignee: Party
    country_of_origin: str
    destination_country: str
    transport: str  # e.g. "By sea, MV Evans Star, Nhava Sheva to Rotterdam"
    invoice_number: str
    invoice_date: date
    lines: tuple[GoodsLine, ...]


class LutAcknowledgement(Model):
    arn: str
    gstin: str
    legal_name: str
    financial_year: str
    filed_on: date


class ShipmentDocuments(Model):
    commercial_invoice: CommercialInvoice
    packing_list: PackingList
    purchase_order: PurchaseOrder
    shipping_bill: ShippingBill
    bill_of_lading: BillOfLading | None
    air_waybill: AirWaybill | None
    certificate_of_origin: CertificateOfOrigin
    lut: LutAcknowledgement
