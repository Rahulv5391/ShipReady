"""The reference data the checks consult, behind a small interface so tests need no database.

Each lookup answers None when our data cannot say (a table not loaded, a code or a date it does
not cover): the check then reports "not verified", never a failure (PLAN.md Phase 13).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from shipready.db.models import RefExchangeRate, RefExportPolicy, RefItcHs, RefPort

# ICEGATE notifies export rates every two weeks; past this many days after the newest
# notification we hold, a newer rate may be in force that we do not know.
RATE_NOTICE_DAYS = 15


class Reference(Protocol):
    def hs_code_known(self, code: str) -> bool | None:
        """Whether `code` is an 8-digit ITC(HS) tariff item; None without the schedule."""

    def export_policy(self, code: str, on: date) -> str | None:
        """Free, Restricted, Prohibited or STE on `on`; None for a code not in the schedule."""

    def exchange_rate(self, currency: str, on: date) -> tuple[Decimal, int] | None:
        """The customs export rate in force on `on`: INR per `unit` units of `currency`."""

    def indian_port(self, code: str) -> bool | None:
        """Whether `code` is an Indian customs location; None without the port list."""

    def hs_description(self, code: str) -> str | None:
        """What the 8-digit `code` covers, from its chapter down; None for an unknown code."""


class DbReference:
    """The reference tables loaded by `shipready.db.load`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def hs_code_known(self, code: str) -> bool | None:
        if not self.session.scalar(select(exists().where(RefItcHs.level == 8))):
            return None
        return self.session.get(RefItcHs, code) is not None and len(code) == 8

    def export_policy(self, code: str, on: date) -> str | None:
        if self.session.get(RefItcHs, code) is None:
            return None
        policy = self.session.scalar(
            select(RefExportPolicy.policy).where(
                RefExportPolicy.code == code,
                (RefExportPolicy.effective_from.is_(None)) | (RefExportPolicy.effective_from <= on),
                (RefExportPolicy.effective_to.is_(None)) | (RefExportPolicy.effective_to >= on),
            )
        )
        # A code with no restriction in force is Free (RefExportPolicy lists exceptions only).
        return policy or "Free"

    def exchange_rate(self, currency: str, on: date) -> tuple[Decimal, int] | None:
        newest = self.session.scalar(select(func.max(RefExchangeRate.valid_from)))
        if newest is None or on > newest + timedelta(days=RATE_NOTICE_DAYS):
            return None
        row = self.session.scalars(
            select(RefExchangeRate)
            .where(RefExchangeRate.currency == currency, RefExchangeRate.valid_from <= on)
            .order_by(RefExchangeRate.valid_from.desc())
            .limit(1)
        ).first()
        return (row.rate_inr, row.unit) if row else None

    def hs_description(self, code: str) -> str | None:
        if self.session.get(RefItcHs, code) is None:
            return None
        # A tariff item often reads only "Other": its chapter, heading and subheading say what.
        levels = [code[:2], code[:4], code[:6], code]
        rows = self.session.scalars(select(RefItcHs).where(RefItcHs.code.in_(levels)))
        found = {row.code: row.description for row in rows}
        return "; ".join(found[level] for level in levels if level in found)

    def indian_port(self, code: str) -> bool | None:
        if not self.session.scalar(select(exists().where(RefPort.code.is_not(None)))):
            return None
        return self.session.get(RefPort, code) is not None
