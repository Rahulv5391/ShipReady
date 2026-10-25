"""Tables for the check catalogue and reference data (PLAN.md Section 12).

The catalogue, UQC codes and countries are seeded from packaged files; the other reference tables
are loaded from official downloads by `shipready.reference.load`.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shipready.reference.export_policy import EXPORT_POLICIES
from shipready.reference.ports import KINDS
from shipready.rules.catalogue import CHECK_TYPES, SEVERITIES

POLICY_SOURCES = ("dgft", "override")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(_one_of("check_type", CHECK_TYPES), name="check_type_valid"),
        CheckConstraint(_one_of("severity", SEVERITIES), name="severity_valid"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(String(8))
    severity: Mapped[str] = mapped_column(String(8))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prevents: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool]


class RefUqc(Base):
    __tablename__ = "ref_uqc"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    description: Mapped[str] = mapped_column(Text)


class RefCountry(Base):
    __tablename__ = "ref_countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class RefPort(Base):
    """An Indian customs location (ICEGATE code), e.g. INNSA1 Nhava Sheva seaport."""

    __tablename__ = "ref_ports"
    __table_args__ = (CheckConstraint(_one_of("kind", tuple(KINDS.values())), name="kind_valid"),)

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(6))
    edi: Mapped[bool]  # connected to ICEGATE's electronic filing


class RefItcHs(Base):
    """An ITC(HS) code: chapter (2 digits), heading (4), subheading (6) or tariff item (8)."""

    __tablename__ = "ref_itc_hs"
    __table_args__ = (CheckConstraint("level IN (2, 4, 6, 8)", name="level_valid"),)

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)
    description: Mapped[str] = mapped_column(Text)


class RefExportPolicy(Base):
    """A period during which an 8-digit code is not Free to export. Codes without a row are Free.

    `effective_from` is the date of the notification DGFT cites (earlier history is not recorded)
    and is empty when DGFT cites none; `effective_to` is empty while the policy is in force.
    """

    __tablename__ = "ref_export_policy"
    __table_args__ = (
        CheckConstraint(_one_of("policy", EXPORT_POLICIES), name="policy_valid"),
        CheckConstraint(_one_of("source", POLICY_SOURCES), name="source_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("ref_itc_hs.code"), index=True)
    policy: Mapped[str] = mapped_column(String(10))
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    notification: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8))


class RefCurrency(Base):
    """An ISO 4217 currency; `minor_units` is empty for funds and metals."""

    __tablename__ = "ref_currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    minor_units: Mapped[int | None] = mapped_column(SmallInteger)


class RefExchangeRate(Base):
    """Customs export rate: INR per `unit` units of `currency`, in force from `valid_from` until
    the next notification for that currency."""

    __tablename__ = "ref_exchange_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    valid_from: Mapped[date] = mapped_column(primary_key=True)
    unit: Mapped[int]
    rate_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    notification: Mapped[str] = mapped_column(Text)  # ICEGATE notification number, e.g. 29/2026
    published_on: Mapped[date]


class RefLocation(Base):
    """UN/LOCODE location (city, port, airport, inland depot)."""

    __tablename__ = "ref_locations"

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    country: Mapped[str] = mapped_column(ForeignKey("ref_countries.code"))
    name: Mapped[str] = mapped_column(Text)
    subdivision: Mapped[str | None] = mapped_column(String(3))
    # Eight positions: 1 port, 2 rail, 3 road, 4 airport, 5 postal, 6 multimodal (e.g. ICD),
    # 7 fixed transport, B border crossing; "-" where the function does not apply.
    functions: Mapped[str] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(2))
