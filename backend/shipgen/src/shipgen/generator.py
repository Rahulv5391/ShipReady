"""Generate golden shipments. The same (seed, index) always gives the same shipment."""

import math
import random
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from typing import Any, Literal

from faker import Faker

from shipgen import profiles
from shipgen.documents import chargeable_weight
from shipgen.models import Exporter, LineItem, Lut, Mode, Shipment, Transport
from shipgen.products import Product, load_products
from shipready.documents.models import Address, Container, Party, Port
from shipready.normalise.containers import check_digit
from shipready.normalise.identifiers import gstin_check_char
from shipready.reference.exchange_rates import load_exchange_rates
from shipready.reference.files import read_csv

CENTS = Decimal("0.01")
GRAMS = Decimal("0.001")
MAX_LINES = 15
# Usable volume (cbm) and payload (kg) per container size.
ContainerSize = Literal["20GP", "40GP"]
CONTAINER_CAPACITY: dict[ContainerSize, tuple[Decimal, Decimal]] = {
    "20GP": (Decimal(28), Decimal(21000)),
    "40GP": (Decimal(58), Decimal(26000)),
}
# Air India's IATA airline prefix; ShipGen airway bills use it so numbers look real.
AWB_PREFIX = "098"
# CBIC notifications are fortnightly, so the latest rate is assumed to hold for 13 more days.
RATE_VALIDITY_DAYS = 13


@dataclass(frozen=True)
class _Reference:
    products_by_category: dict[str, tuple[Product, ...]]
    ports: tuple[Port, ...]
    port_kinds: dict[str, str]
    rates: tuple[dict[str, Any], ...]
    first_day: date
    last_day: date


@cache
def _reference() -> _Reference:
    products: dict[str, list[Product]] = {}
    for product in load_products():
        products.setdefault(product.category, []).append(product)
    port_rows = read_csv("ports.csv")
    rates = tuple(load_exchange_rates())
    valid_from = [rate["valid_from"] for rate in rates]
    return _Reference(
        products_by_category={key: tuple(value) for key, value in sorted(products.items())},
        ports=tuple(Port(code=r["code"], name=r["name"], country=r["country"]) for r in port_rows),
        port_kinds={row["code"]: row["kind"] for row in port_rows},
        rates=rates,
        first_day=min(valid_from),
        last_day=max(valid_from) + timedelta(days=RATE_VALIDITY_DAYS),
    )


def rate_on(currency: str, day: date) -> dict[str, Any]:
    """The CBIC export rate for `currency` in force on `day`."""
    candidates = [
        rate
        for rate in _reference().rates
        if rate["currency"] == currency and rate["valid_from"] <= day
    ]
    if not candidates:
        raise ValueError(f"no CBIC exchange rate for {currency} on {day}")
    return max(candidates, key=lambda rate: rate["valid_from"])


def financial_year(day: date) -> str:
    """Indian financial year (April to March) containing `day`, e.g. '2026-27'."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def generate_shipment(seed: int, index: int) -> Shipment:
    rng = random.Random(f"{seed}:{index}")
    ref = _reference()

    category = rng.choice(sorted(ref.products_by_category))
    mode: Mode = "air" if category == "pharma" and rng.random() < 0.5 else "sea"
    loading = rng.choice(_ports(mode, indian=True))
    discharge = rng.choice(_ports(mode, indian=False))
    country = discharge.country
    destination = profiles.DESTINATIONS[country]

    shipping_bill_date = ref.first_day + timedelta(
        rng.randint(0, (ref.last_day - ref.first_day).days)
    )
    invoice_date = shipping_bill_date - timedelta(rng.randint(0, 3))
    departure_date = shipping_bill_date + timedelta(rng.randint(1, 6))
    fy = financial_year(invoice_date)

    state = rng.choice(profiles.EXPORTER_STATES)
    indian_faker = _faker("en_IN", rng)
    exporter = _exporter(rng, indian_faker, state)
    lut_filed_on = date(int(fy[:4]), 4, 1) + timedelta(rng.randint(0, 29))
    lut = Lut(
        arn=_lut_arn(rng, state.gst_code, lut_filed_on),
        financial_year=fy,
        filed_on=lut_filed_on,
    )

    foreign_faker = _faker(destination.faker_locale, rng)
    consignee = Party(
        name=foreign_faker.company(),
        address=Address(
            lines=(foreign_faker.street_address().replace("\n", ", "),),
            city=rng.choice(destination.cities),
            country=country,
        ),
    )
    # Airway bills are not documents of title, so only sea shipments can be "to order".
    payment_options = [p for p in profiles.PAYMENT_TERMS if mode == "sea" or not p[1]]
    payment_terms, to_order = rng.choice(payment_options)

    incoterm = rng.choice(profiles.SEA_INCOTERMS if mode == "sea" else profiles.AIR_INCOTERMS)
    rate = rate_on(destination.currency, shipping_bill_date)
    usd_rate = rate_on("USD", shipping_bill_date)

    def from_usd(amount: Decimal) -> Decimal:
        inr: Decimal = amount * usd_rate["rate_inr"] / usd_rate["unit"]
        converted: Decimal = inr * rate["unit"] / rate["rate_inr"]
        return converted.quantize(CENTS, ROUND_HALF_UP)

    lines = _lines(rng, ref.products_by_category[category], from_usd)
    goods_value = sum((line.amount for line in lines), Decimal(0))
    net_weight = sum((line.net_weight_kg for line in lines), Decimal(0))
    gross_weight = sum((line.gross_weight_kg for line in lines), Decimal(0))
    volume = sum((line.volume_cbm for line in lines), Decimal(0))
    total_packages = sum(line.packages for line in lines)

    containers = _containers(rng, volume, gross_weight) if mode == "sea" else ()
    freight = Decimal(0)
    if incoterm in profiles.PREPAID_INCOTERMS:
        if mode == "sea":
            per_container = Decimal(str(round(rng.uniform(600, 2200), 2)))
            freight = from_usd(per_container * len(containers))
        else:
            chargeable = chargeable_weight(gross_weight, volume)
            freight = from_usd(chargeable * Decimal(str(round(rng.uniform(2.5, 4.5), 2))))
    insurance = Decimal(0)
    if incoterm in profiles.INSURED_INCOTERMS:
        insurance = (goods_value * Decimal(str(round(rng.uniform(0.001, 0.003), 4)))).quantize(
            CENTS, ROUND_HALF_UP
        )
    invoice_total = goods_value + freight + insurance
    invoice_sequence = rng.randint(1, 9999)

    return Shipment(
        shipment_id=f"SG{seed}-{index:04d}",
        exporter=exporter,
        lut=lut,
        consignee=consignee,
        notify_party=consignee if to_order else None,
        to_order=to_order,
        destination_country=country,
        po_number=f"PO-{rng.randint(10000, 99999)}",
        po_date=invoice_date - timedelta(rng.randint(7, 45)),
        invoice_number=f"EXP/{fy[2:]}/{invoice_sequence:04d}",
        invoice_date=invoice_date,
        shipping_bill_number=str(rng.randint(1_000_000, 9_999_999)),
        shipping_bill_date=shipping_bill_date,
        coo_number=f"COO/{invoice_date.year}/{rng.randint(1, 999_999):06d}",
        coo_date=invoice_date + timedelta(rng.randint(0, (departure_date - invoice_date).days)),
        incoterm=incoterm,
        incoterm_place=(discharge if incoterm in profiles.PREPAID_INCOTERMS else loading).name,
        freight_terms="prepaid" if incoterm in profiles.PREPAID_INCOTERMS else "collect",
        payment_terms=payment_terms,
        currency=destination.currency,
        exchange_rate=rate["rate_inr"],
        exchange_rate_unit=rate["unit"],
        exchange_notification=rate["notification"],
        lines=lines,
        goods_value=goods_value,
        freight=freight,
        insurance=insurance,
        invoice_total=invoice_total,
        fob_inr=_to_inr(goods_value, rate),
        invoice_total_inr=_to_inr(invoice_total, rate),
        total_packages=total_packages,
        net_weight_kg=net_weight,
        gross_weight_kg=gross_weight,
        volume_cbm=volume,
        marks=f"{_initials(consignee.name)}/{invoice_sequence:04d}/1-{total_packages}",
        transport=_transport(
            rng, foreign_faker, mode, loading, discharge, containers, departure_date
        ),
    )


def _ports(mode: Mode, *, indian: bool) -> list[Port]:
    ref = _reference()
    # Inland depots are left out: FOB and CFR/CIF only apply at a seaport.
    return [
        port
        for port in ref.ports
        if (port.country == "IN") == indian
        and ref.port_kinds[port.code] == mode
        and (indian or port.country in profiles.DESTINATIONS)
    ]


def _faker(locale: str, rng: random.Random) -> Faker:
    faker = Faker(locale)
    faker.seed_instance(rng.getrandbits(32))
    return faker


def _exporter(rng: random.Random, faker: Faker, state: profiles.IndianState) -> Exporter:
    suffix = rng.choice(profiles.COMPANY_SUFFIXES)
    name = f"{faker.last_name()} {suffix}"
    # PAN: 3 letters, holder type (C company, F firm), first letter of the name, 4 digits, letter.
    holder = "C" if "Pvt Ltd" in suffix else "F"
    pan = (
        "".join(rng.choices(string.ascii_uppercase, k=3))
        + holder
        + name[0].upper()
        + f"{rng.randint(0, 9999):04d}"
        + rng.choice(string.ascii_uppercase)
    )
    first14 = f"{state.gst_code}{pan}1Z"
    city = rng.choice(state.cities)
    pin = state.pin_prefix + f"{rng.randint(0, 99999):05d}"
    return Exporter(
        name=name,
        address=Address(
            lines=(f"{rng.randint(1, 250)}, {faker.street_name()}", f"{state.name} {pin}"),
            city=city,
            country="IN",
        ),
        gstin=first14 + gstin_check_char(first14),
        pan=pan,
        iec=pan,
        bank_name=rng.choice(profiles.BANKS),
        ad_code=f"{rng.randint(0, 10**14 - 1):014d}",
    )


def _lut_arn(rng: random.Random, state_code: str, filed_on: date) -> str:
    """GST ARN layout: 'AD' (refund-type application), state code, MMYY, 6-digit sequence and a
    check character. GSTN does not publish the check character's algorithm, so it is random."""
    check = rng.choice(string.ascii_uppercase + string.digits)
    return f"AD{state_code}{filed_on:%m%y}{rng.randint(0, 999_999):06d}{check}"


def _lines(
    rng: random.Random, products: tuple[Product, ...], from_usd: Callable[[Decimal], Decimal]
) -> tuple[LineItem, ...]:
    combos = [(product, variant) for product in products for variant in product.variants]
    chosen = rng.sample(combos, rng.randint(1, min(MAX_LINES, len(combos))))
    lines = []
    for line_no, (product, variant) in enumerate(chosen, start=1):
        packages = rng.randint(product.packages_min, product.packages_max)
        quantity = product.units_per_package * packages
        price_usd = Decimal(
            str(round(rng.uniform(float(product.price_usd_min), float(product.price_usd_max)), 2))
        )
        unit_price = from_usd(price_usd)
        net = (quantity * product.net_kg_per_unit).quantize(GRAMS)
        lines.append(
            LineItem(
                line_no=line_no,
                sku=product.sku,
                description=f"{product.description} - {variant}",
                hs_code=product.hs_code,
                quantity=quantity,
                uqc=product.uqc,
                unit_price=unit_price,
                amount=(quantity * unit_price).quantize(CENTS, ROUND_HALF_UP),
                packages=packages,
                package_type=product.package_type,
                net_weight_kg=net,
                gross_weight_kg=(net + product.package_tare_kg * packages).quantize(GRAMS),
                volume_cbm=(product.package_cbm * packages).quantize(GRAMS),
            )
        )
    return tuple(lines)


def container_plan(volume: Decimal, gross_weight: Decimal) -> list[ContainerSize]:
    """One 20GP if the cargo fits, otherwise as many 40GP as volume and weight need."""

    def needed(size: ContainerSize) -> int:
        cbm, kg = CONTAINER_CAPACITY[size]
        return max(math.ceil(volume / cbm), math.ceil(gross_weight / kg), 1)

    return ["20GP"] if needed("20GP") == 1 else ["40GP"] * needed("40GP")


def _containers(
    rng: random.Random, volume: Decimal, gross_weight: Decimal
) -> tuple[Container, ...]:
    containers: list[Container] = []
    numbers: set[str] = set()
    for size in container_plan(volume, gross_weight):
        while True:
            first10 = (
                "".join(rng.choices(string.ascii_uppercase, k=3))
                + "U"
                + f"{rng.randint(0, 999_999):06d}"
            )
            number = first10 + str(check_digit(first10))
            if number not in numbers:
                break
        numbers.add(number)
        seal = (
            "".join(rng.choices(string.ascii_uppercase, k=2)) + f"{rng.randint(0, 9_999_999):07d}"
        )
        containers.append(Container(number=number, seal=seal, size=size))
    return tuple(containers)


def _transport(
    rng: random.Random,
    faker: Faker,
    mode: Mode,
    loading: Port,
    discharge: Port,
    containers: tuple[Container, ...],
    departure_date: date,
) -> Transport:
    if mode == "sea":
        reference = f"SGL{rng.randint(10**8, 10**9 - 1)}"
        vessel = f"MV {faker.last_name()} {rng.choice(('Star', 'Spirit', 'Pride', 'Trader'))}"
        voyage: str | None = f"{rng.randint(100, 999)}{rng.choice('EW')}"
    else:
        # The 8th digit of an airway bill serial is the first seven digits modulo 7.
        serial = rng.randint(0, 9_999_999)
        reference = f"{AWB_PREFIX}-{serial:07d}{serial % 7}"
        vessel = f"SG {rng.randint(100, 9999)}"
        voyage = None
    return Transport(
        mode=mode,
        port_of_loading=loading,
        port_of_discharge=discharge,
        carrier_reference=reference,
        vessel_or_flight=vessel,
        voyage=voyage,
        containers=containers,
        departure_date=departure_date,
    )


def _to_inr(amount: Decimal, rate: dict[str, Any]) -> Decimal:
    inr: Decimal = amount * rate["rate_inr"] / rate["unit"]
    return inr.quantize(CENTS, ROUND_HALF_UP)


def _initials(name: str) -> str:
    letters = [word[0] for word in name.split() if word[0].isalpha()]
    return "".join(letters[:3]).upper() or "X"
