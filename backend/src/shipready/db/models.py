"""Tables for the check catalogue and the built-in reference lists (PLAN.md Section 12)."""

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shipready.rules.catalogue import CHECK_TYPES, SEVERITIES

PORT_KINDS = ("sea", "air", "icd")


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
    __tablename__ = "ref_ports"
    __table_args__ = (CheckConstraint(_one_of("kind", PORT_KINDS), name="kind_valid"),)

    # ICEGATE port code for Indian ports (e.g. INNSA1), UN/LOCODE for foreign ones.
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(ForeignKey("ref_countries.code"))
    unlocode: Mapped[str] = mapped_column(String(5))
    kind: Mapped[str] = mapped_column(String(3))
