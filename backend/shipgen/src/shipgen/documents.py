"""Fill the document models (shipready.documents) from a golden shipment: the ground truth
for extraction."""

from decimal import Decimal

from shipgen.models import Shipment
from shipgen.profiles import COO_ISSUER
from shipready.documents.models import (
    AirWaybill,
    BillOfLading,
    CertificateOfOrigin,
    CommercialInvoice,
    GoodsLine,
    InvoiceLine,
    LutAcknowledgement,
    PackingLine,
    PackingList,
    PurchaseOrder,
    ShipmentDocuments,
    ShippingBill,
)

LUT_DECLARATION = (
    "Supply meant for export under bond or letter of undertaking without payment of IGST"
)


def chargeable_weight(gross_weight_kg: Decimal, volume_cbm: Decimal) -> Decimal:
    # IATA volumetric weight: 6,000 cm3 per kg, i.e. 167 kg per cbm.
    return max(gross_weight_kg, (volume_cbm * 167).quantize(Decimal("0.001")))


def build_documents(shipment: Shipment) -> ShipmentDocuments:
    s = shipment
    t = s.transport
    invoice_lines = tuple(
        InvoiceLine(
            description=line.description,
            hs_code=line.hs_code,
            quantity=line.quantity,
            uqc=line.uqc,
            unit_price=line.unit_price,
            amount=line.amount,
        )
        for line in s.lines
    )
    goods_description = "; ".join(sorted({line.description.split(" - ")[0] for line in s.lines}))
    incoterm = f"{s.incoterm} {s.incoterm_place}"

    bill_of_lading = None
    air_waybill = None
    if t.mode == "sea":
        if t.voyage is None:
            raise ValueError(f"{s.shipment_id}: sea shipment without a voyage")
        bill_of_lading = BillOfLading(
            bl_number=t.carrier_reference,
            shipper=s.exporter_party,
            consignee=None if s.to_order else s.consignee,
            to_order=s.to_order,
            notify_party=s.notify_party,
            vessel=t.vessel_or_flight,
            voyage=t.voyage,
            port_of_loading=t.port_of_loading,
            port_of_discharge=t.port_of_discharge,
            containers=t.containers,
            total_packages=s.total_packages,
            goods_description=goods_description,
            gross_weight_kg=s.gross_weight_kg,
            volume_cbm=s.volume_cbm,
            marks=s.marks,
            freight_terms=s.freight_terms,
            shipped_on_board=t.departure_date,
        )
    else:
        air_waybill = AirWaybill(
            awb_number=t.carrier_reference,
            shipper=s.exporter_party,
            consignee=s.consignee,
            airport_of_departure=t.port_of_loading,
            airport_of_destination=t.port_of_discharge,
            flight=t.vessel_or_flight,
            flight_date=t.departure_date,
            total_packages=s.total_packages,
            gross_weight_kg=s.gross_weight_kg,
            chargeable_weight_kg=chargeable_weight(s.gross_weight_kg, s.volume_cbm),
            goods_description=goods_description,
            freight_terms=s.freight_terms,
        )

    return ShipmentDocuments(
        commercial_invoice=CommercialInvoice(
            invoice_number=s.invoice_number,
            invoice_date=s.invoice_date,
            exporter=s.exporter_party,
            gstin=s.exporter.gstin,
            iec=s.exporter.iec,
            consignee=s.consignee,
            buyer_po_number=s.po_number,
            buyer_po_date=s.po_date,
            lines=invoice_lines,
            currency=s.currency,
            goods_value=s.goods_value,
            freight=s.freight,
            insurance=s.insurance,
            total=s.invoice_total,
            exchange_rate=s.exchange_rate,
            exchange_rate_unit=s.exchange_rate_unit,
            total_inr=s.invoice_total_inr,
            incoterm=incoterm,
            payment_terms=s.payment_terms,
            port_of_loading=t.port_of_loading,
            port_of_discharge=t.port_of_discharge,
            destination_country=s.destination_country,
            gst_declaration=LUT_DECLARATION,
            lut_arn=s.lut.arn,
            bank_name=s.exporter.bank_name,
            ad_code=s.exporter.ad_code,
        ),
        packing_list=PackingList(
            invoice_number=s.invoice_number,
            invoice_date=s.invoice_date,
            exporter=s.exporter_party,
            consignee=s.consignee,
            lines=tuple(
                PackingLine(
                    description=line.description,
                    quantity=line.quantity,
                    uqc=line.uqc,
                    packages=line.packages,
                    package_type=line.package_type,
                    net_weight_kg=line.net_weight_kg,
                    gross_weight_kg=line.gross_weight_kg,
                )
                for line in s.lines
            ),
            total_packages=s.total_packages,
            net_weight_kg=s.net_weight_kg,
            gross_weight_kg=s.gross_weight_kg,
            volume_cbm=s.volume_cbm,
            marks=s.marks,
            containers=t.containers,
        ),
        purchase_order=PurchaseOrder(
            po_number=s.po_number,
            po_date=s.po_date,
            buyer=s.consignee,
            seller=s.exporter_party,
            lines=invoice_lines,
            currency=s.currency,
            total=s.goods_value,
            incoterm=incoterm,
            payment_terms=s.payment_terms,
        ),
        shipping_bill=ShippingBill(
            shipping_bill_number=s.shipping_bill_number,
            shipping_bill_date=s.shipping_bill_date,
            port_code=t.port_of_loading.code,
            exporter_name=s.exporter.name,
            iec=s.exporter.iec,
            gstin=s.exporter.gstin,
            ad_code=s.exporter.ad_code,
            consignee_name=s.consignee.name,
            consignee_country=s.consignee.address.country,
            invoice_number=s.invoice_number,
            invoice_date=s.invoice_date,
            lines=invoice_lines,
            currency=s.currency,
            invoice_value=s.invoice_total,
            fob_value=s.goods_value,
            exchange_rate=s.exchange_rate,
            exchange_rate_unit=s.exchange_rate_unit,
            fob_inr=s.fob_inr,
            total_packages=s.total_packages,
            gross_weight_kg=s.gross_weight_kg,
            containers=t.containers,
            igst_payment_status="LUT",
            lut_arn=s.lut.arn,
        ),
        bill_of_lading=bill_of_lading,
        air_waybill=air_waybill,
        certificate_of_origin=CertificateOfOrigin(
            certificate_number=s.coo_number,
            certificate_date=s.coo_date,
            issuing_body=COO_ISSUER,
            exporter=s.exporter_party,
            consignee=s.consignee,
            country_of_origin="IN",
            destination_country=s.destination_country,
            transport=(
                f"By {t.mode}, {t.vessel_or_flight}, "
                f"{t.port_of_loading.name} to {t.port_of_discharge.name}"
            ),
            invoice_number=s.invoice_number,
            invoice_date=s.invoice_date,
            lines=tuple(
                GoodsLine(
                    description=line.description,
                    hs_code=line.hs_code,
                    quantity=line.quantity,
                    uqc=line.uqc,
                )
                for line in s.lines
            ),
        ),
        lut=LutAcknowledgement(
            arn=s.lut.arn,
            gstin=s.exporter.gstin,
            legal_name=s.exporter.name,
            financial_year=s.lut.financial_year,
            filed_on=s.lut.filed_on,
        ),
    )
