"""Parse customs exchange rates from ICEGATE's notifications (icegate-exchange-rates.json).

Since 4 July 2024 (CBIC Circular 07/2024-Customs) rates are no longer gazette notifications: the
Exchange Rate Automation Module publishes them on ICEGATE, usually on the 1st and 3rd Thursday of
the month and sometimes in between, each in force from the date the notification states. Only
export rates are kept, since ShipReady checks exports.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from shipready.reference.files import ReferenceDataError, indian_date, json_value

# ICEGATE quotes most currencies per 1 unit and a few (e.g. JPY, KRW) per 100 units.
UNITS = (1, 100)
# Each notification covers about 22 currencies; far fewer means a truncated response.
MIN_CURRENCIES_PER_NOTIFICATION = 15


def parse_exchange_rates(
    source: str,
    data: bytes,
    currencies: set[str],
) -> list[dict[str, Any]]:
    """Rows of currency, valid_from, unit, rate_inr (export), notification and published_on.

    `currencies` are the ISO 4217 codes a rate may be given for.
    """
    payload = json_value(source, data)
    if not isinstance(payload, dict) or not isinstance(payload.get("notifications"), list):
        raise ReferenceDataError(source, None, "expected 'notifications' and 'details'")
    details = payload.get("details")
    if not isinstance(details, dict):
        raise ReferenceDataError(source, None, "missing notification details")

    rows: dict[tuple[str, date], dict[str, Any]] = {}
    for position, entry in enumerate(payload["notifications"], start=1):
        number = str(entry.get("notificationNumber", "")).strip()
        detail = details.get(number)
        if not number or not isinstance(detail, dict):
            raise ReferenceDataError(source, position, f"no details for notification {number!r}")
        published_on = indian_date(source, position, entry.get("notPublishDate"))
        valid_from = indian_date(source, position, detail.get("notPublishDate"))
        if valid_from < published_on:
            raise ReferenceDataError(
                source, position, f"{number} is in force before it was published"
            )
        rates = detail.get("currencyDetail")
        if not isinstance(rates, list) or len(rates) < MIN_CURRENCIES_PER_NOTIFICATION:
            raise ReferenceDataError(source, position, f"{number} has too few rates")
        for rate in rates:
            row = _rate(source, position, number, rate, currencies)
            key = (row["currency"], valid_from)
            if key in rows:
                raise ReferenceDataError(
                    source,
                    position,
                    f"{number} and {rows[key]['notification']} both set "
                    f"{row['currency']} from {valid_from}",
                )
            rows[key] = {**row, "valid_from": valid_from, "published_on": published_on}
    return list(rows.values())


def _rate(
    source: str, position: int, number: str, rate: Any, currencies: set[str]
) -> dict[str, Any]:
    currency = str(rate.get("currencyCode", "")).strip() if isinstance(rate, dict) else ""
    if currency not in currencies:
        raise ReferenceDataError(
            source, position, f"{number}: {currency!r} is not an ISO 4217 code"
        )
    export_rate, units = rate.get("cbicExport"), rate.get("units")
    if not isinstance(export_rate, (Decimal, int)) or export_rate <= 0:
        raise ReferenceDataError(source, position, f"{number}: bad export rate for {currency}")
    try:
        unit = Decimal(str(units))
    except ArithmeticError:
        unit = Decimal(0)
    if unit not in UNITS:
        raise ReferenceDataError(source, position, f"{number}: unit {units!r} for {currency}")
    return {
        "currency": currency,
        "unit": int(unit),
        "rate_inr": Decimal(export_rate),
        "notification": number,
    }
