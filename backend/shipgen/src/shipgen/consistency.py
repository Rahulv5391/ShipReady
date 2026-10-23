"""Invariants every golden shipment must satisfy. Returns problems instead of raising, so a test
can report all of them at once."""

import re
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from shipgen import profiles
from shipgen.generator import container_plan, financial_year, rate_on
from shipgen.models import Shipment
from shipready.normalise.containers import is_valid_container
from shipready.normalise.identifiers import (
    is_valid_ad_code,
    is_valid_gstin,
    is_valid_iec,
    pan_from_gstin,
)
from shipready.reference.itc_hs import load_itc_hs
from shipready.reference.uqc import UQC

CENTS = Decimal("0.01")
_LUT_ARN_RE = re.compile(r"^AD([0-9]{2})(0[1-9]|1[0-2])([0-9]{2})[0-9]{6}[0-9A-Z]$")
# Airline prefix, 7-digit serial, check digit (the serial modulo 7).
_AWB_RE = re.compile(r"^[0-9]{3}-([0-9]{7})([0-6])$")
# GST Rule 46: an invoice number has at most 16 characters.
_INVOICE_NUMBER_MAX = 16


def check_shipment(s: Shipment) -> list[str]:
    return [
        *_check_identifiers(s),
        *_check_goods(s),
        *_check_values(s),
        *_check_packing(s),
        *_check_transport(s),
        *_check_dates(s),
    ]


def _check_identifiers(s: Shipment) -> list[str]:
    e = s.exporter
    problems = []
    if not is_valid_gstin(e.gstin):
        problems.append(f"invalid GSTIN {e.gstin}")
    elif pan_from_gstin(e.gstin) != e.pan:
        problems.append("PAN inside GSTIN differs from exporter PAN")
    if not is_valid_iec(e.iec) or e.iec != e.pan:
        problems.append(f"IEC {e.iec} is not the exporter PAN")
    if not is_valid_ad_code(e.ad_code):
        problems.append(f"invalid AD code {e.ad_code}")
    arn = _LUT_ARN_RE.match(s.lut.arn)
    if arn is None:
        problems.append(f"LUT ARN {s.lut.arn} not in GST ARN format")
    elif arn.group(1) != e.gstin[:2]:
        problems.append("LUT ARN state differs from GSTIN state")
    if len(s.invoice_number) > _INVOICE_NUMBER_MAX:
        problems.append(f"invoice number longer than {_INVOICE_NUMBER_MAX} characters")
    return problems


def _check_goods(s: Shipment) -> list[str]:
    itc_hs = {row["code"]: row for row in load_itc_hs()}
    problems = []
    for line in s.lines:
        hs = itc_hs.get(line.hs_code)
        if hs is None or hs["export_policy"] != "Free":
            problems.append(f"line {line.line_no}: HS {line.hs_code} missing or not Free")
        elif hs["uqc"] != line.uqc:
            problems.append(f"line {line.line_no}: UQC {line.uqc} differs from ITC-HS")
        if line.uqc not in UQC:
            problems.append(f"line {line.line_no}: invalid UQC {line.uqc}")
    if [line.line_no for line in s.lines] != list(range(1, len(s.lines) + 1)):
        problems.append("line numbers are not 1..n")
    return problems


def _check_values(s: Shipment) -> list[str]:
    problems = []
    for line in s.lines:
        if (line.quantity * line.unit_price).quantize(CENTS, ROUND_HALF_UP) != line.amount:
            problems.append(f"line {line.line_no}: amount is not quantity x unit price")
    if sum(line.amount for line in s.lines) != s.goods_value:
        problems.append("line amounts do not sum to goods value")
    if s.goods_value + s.freight + s.insurance != s.invoice_total:
        problems.append("invoice total is not goods + freight + insurance")
    if (s.freight > 0) != (s.incoterm in profiles.PREPAID_INCOTERMS):
        problems.append(f"freight charged does not match {s.incoterm}")
    if (s.insurance > 0) != (s.incoterm in profiles.INSURED_INCOTERMS):
        problems.append(f"insurance charged does not match {s.incoterm}")
    rate = rate_on(s.currency, s.shipping_bill_date)
    if (rate["rate_inr"], rate["unit"], rate["notification"]) != (
        s.exchange_rate,
        s.exchange_rate_unit,
        s.exchange_notification,
    ):
        problems.append("exchange rate is not the CBIC rate on the shipping bill date")
    for value, inr, label in (
        (s.goods_value, s.fob_inr, "FOB"),
        (s.invoice_total, s.invoice_total_inr, "invoice total"),
    ):
        expected = (value * s.exchange_rate / s.exchange_rate_unit).quantize(CENTS, ROUND_HALF_UP)
        if inr != expected:
            problems.append(f"{label} in INR is not value x rate")
    return problems


def _check_packing(s: Shipment) -> list[str]:
    problems = []
    for line in s.lines:
        if line.net_weight_kg > line.gross_weight_kg:
            problems.append(f"line {line.line_no}: net weight exceeds gross weight")
    totals = (
        (sum(line.packages for line in s.lines), s.total_packages, "packages"),
        (sum(line.net_weight_kg for line in s.lines), s.net_weight_kg, "net weight"),
        (sum(line.gross_weight_kg for line in s.lines), s.gross_weight_kg, "gross weight"),
        (sum(line.volume_cbm for line in s.lines), s.volume_cbm, "volume"),
    )
    problems += [
        f"line {label} do not sum to the total" for total, value, label in totals if total != value
    ]
    if not s.marks.endswith(f"/1-{s.total_packages}"):
        problems.append("marks do not number every package")
    return problems


def _check_transport(s: Shipment) -> list[str]:
    t = s.transport
    problems = []
    if t.port_of_loading.country != "IN":
        problems.append("port of loading is not in India")
    if len({t.port_of_discharge.country, s.destination_country, s.consignee.address.country}) > 1:
        problems.append("destination, port of discharge and consignee country differ")
    if s.freight_terms != ("prepaid" if s.incoterm in profiles.PREPAID_INCOTERMS else "collect"):
        problems.append(f"freight terms {s.freight_terms} do not fit {s.incoterm}")
    if s.to_order and s.notify_party is None:
        problems.append("to-order bill of lading without a notify party")
    if t.mode == "sea":
        numbers = [container.number for container in t.containers]
        if not all(is_valid_container(number) for number in numbers):
            problems.append("invalid container number")
        if len(set(numbers)) != len(numbers):
            problems.append("duplicate container number")
        if [c.size for c in t.containers] != container_plan(s.volume_cbm, s.gross_weight_kg):
            problems.append("containers do not fit the cargo")
    else:
        if t.containers or s.to_order:
            problems.append("air shipment with containers or a to-order consignment")
        awb = _AWB_RE.match(t.carrier_reference)
        if awb is None:
            problems.append(f"airway bill {t.carrier_reference} not in 123-12345678 format")
        elif int(awb.group(1)) % 7 != int(awb.group(2)):
            problems.append("airway bill check digit is wrong")
    return problems


def _check_dates(s: Shipment) -> list[str]:
    problems = []
    order = (
        (s.po_date, "PO"),
        (s.invoice_date, "invoice"),
        (s.shipping_bill_date, "shipping bill"),
        (s.transport.departure_date, "departure"),
    )
    for (earlier, a), (later, b) in pairwise(order):
        if earlier > later:
            problems.append(f"{a} date is after {b} date")
    if not s.invoice_date <= s.coo_date <= s.transport.departure_date:
        problems.append("certificate of origin is not dated between invoice and departure")
    if s.lut.financial_year != financial_year(s.invoice_date) or s.lut.filed_on > s.invoice_date:
        problems.append("LUT does not cover the invoice date")
    return problems
