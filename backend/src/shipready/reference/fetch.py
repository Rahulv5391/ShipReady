"""Download official reference data into a directory (default ../data/reference) for loading.

    uv run python -m shipready.reference.fetch all
    uv run python -m shipready.reference.fetch exchange-rates

The DGFT and ICEGATE endpoints are the ones their public websites use; they are not documented
APIs and may change. Every response is checked for the expected shape before it is saved, so a
changed or failing endpoint stops the fetch instead of writing bad data (Decision.md D-18).
"""

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from itertools import chain
from pathlib import Path
from typing import Any

DGFT = "https://www.dgft.gov.in/CP/webHP?requestType=ApplicationRH"
ICEGATE = "https://foservices.icegate.gov.in/cbu/icegateapi"
SIX_ISO_4217 = (
    "https://www.six-group.com/dam/download/financial-information/data-center/"
    "iso-currrency/lists/list-one.xml"
)
UNECE_UNLOCODE = "https://unlocode.unece.org/downloads/unlocode-latest.zip"

EXPORT_POLICY_LISTS = ("Restricted", "Prohibited", "STE")
# DGFT's policy list endpoint takes itcType 1 for import and 2 for export.
_EXPORT = "2"
# Pause between per-item requests so government servers are not hammered.
REQUEST_INTERVAL_SECONDS = 0.6
_TIMEOUT_SECONDS = 120
_ATTEMPTS = 3
_USER_AGENT = "Mozilla/5.0 (compatible; ShipReady reference data fetch)"
_POLICY_RE = re.compile(r"Export Policy (Free|Restricted|Prohibited|STE|NA)\b")

FILES = {
    "itc-hs": "dgft-itc-hs.json",
    "export-policy": "dgft-export-policy.json",
    "ports": "dgft-ports.json",
    "currencies": "iso4217-list-one.xml",
    "exchange-rates": "icegate-exchange-rates.json",
    "unlocode": "unlocode-latest.zip",
}


class FetchError(RuntimeError):
    pass


def request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    """GET (or POST when `data` is given), retrying transient failures."""
    method = "GET" if data is None else "POST"
    last_error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        req = urllib.request.Request(
            url, data=data, method=method, headers={"User-Agent": _USER_AGENT, **(headers or {})}
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
                body: bytes = response.read()
                return body
        except OSError as error:  # URLError, HTTPError and timeouts are all OSError
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"{method} {url} failed after {_ATTEMPTS} attempts: {last_error}")


def json_list(body: bytes, what: str) -> list[Any]:
    """Decode a JSON list, failing clearly when an endpoint returns an error page instead."""
    try:
        value = json.loads(body)
    except ValueError:
        raise FetchError(f"{what}: expected JSON, got {body[:120]!r}") from None
    if not isinstance(value, list):
        raise FetchError(f"{what}: expected a JSON list, got {type(value).__name__}")
    return value


def fetch_itc_hs() -> bytes:
    # An empty search returns DGFT's whole ITC(HS) tree (chapters down to 8-digit codes).
    body = request(f"{DGFT}&actionVal=preview&screenId=90000802&itc-code=", data=b"")
    json_list(body, "ITC(HS) codes")
    return body


def fetch_export_policy() -> bytes:
    """DGFT's Restricted, Prohibited and STE export lists, plus the current policy DGFT shows
    for each listed code, so the loader can detect stale list entries."""
    lists: dict[str, list[Any]] = {}
    for policy in EXPORT_POLICY_LISTS:
        form = urllib.parse.urlencode({"itchsPolicy": policy, "itcType": _EXPORT}).encode()
        body = request(f"{DGFT}&screenId=90000802&actionVal=getItcDtlsByImportPolicy", form)
        try:
            response = json.loads(body)
            lists[policy] = response["itcCodeClassifications"]
        except (ValueError, KeyError, TypeError):
            raise FetchError(f"{policy} export list: unexpected response {body[:120]!r}") from None
    codes = sorted({entry["itcCode"].strip() for entry in chain(*lists.values())})
    current = {}
    for code in codes:
        current[code] = current_export_policy(code)
        time.sleep(REQUEST_INTERVAL_SECONDS)
    return json.dumps({"lists": lists, "current": current}, ensure_ascii=False).encode()


def current_export_policy(code: str) -> str:
    """The export policy DGFT's ITC(HS) page shows today for one code ('NA' if none)."""
    form = urllib.parse.urlencode({"itcCode": code, "importer": "Exporter", "impExpType": "2"})
    html = request(f"{DGFT}&screenId=90000802&actionVal=importerExporter", form.encode())
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.decode("utf-8", "replace")))
    match = _POLICY_RE.search(text)
    if match is None:
        raise FetchError(f"export policy page for {code} has no 'Export Policy' value")
    return match.group(1)


def fetch_ports() -> bytes:
    # An empty port search returns every Indian customs location DGFT holds from ICEGATE.
    body = request(f"{DGFT}&actionVal=preview&screenId=9000012351", data=b"portOfReg=")
    json_list(body, "ports")
    return body


def fetch_currencies() -> bytes:
    body = request(SIX_ISO_4217)
    if b"<ISO_4217" not in body[:500]:
        raise FetchError(f"ISO 4217 list: unexpected response {body[:120]!r}")
    return body


def fetch_exchange_rates() -> bytes:
    """Every exchange rate notification ICEGATE lists (published there since 4 July 2024)."""
    headers = {"Content-Type": "application/json", "channel": "browser"}
    notifications = json_list(
        request(f"{ICEGATE}/getnotdetails", b"{}", headers), "notification list"
    )
    details = {}
    for entry in notifications:
        number = entry["notificationNumber"]
        body = request(
            f"{ICEGATE}/igexratepublishnot", json.dumps({"notNum": number}).encode(), headers
        )
        try:
            detail = json.loads(body)
        except ValueError:
            raise FetchError(f"notification {number}: expected JSON, got {body[:120]!r}") from None
        if detail.get("status") != 1 or not detail.get("currencyDetail"):
            raise FetchError(f"notification {number}: no rates in response {body[:120]!r}")
        details[number] = detail
        time.sleep(REQUEST_INTERVAL_SECONDS)
    payload = {"notifications": notifications, "details": details}
    return json.dumps(payload, ensure_ascii=False).encode()


def fetch_unlocode() -> bytes:
    body = request(UNECE_UNLOCODE)
    if not body.startswith(b"PK"):
        raise FetchError(f"UN/LOCODE: expected a zip file, got {body[:60]!r}")
    return body


FETCHERS: dict[str, Callable[[], bytes]] = {
    "itc-hs": fetch_itc_hs,
    "export-policy": fetch_export_policy,
    "ports": fetch_ports,
    "currencies": fetch_currencies,
    "exchange-rates": fetch_exchange_rates,
    "unlocode": fetch_unlocode,
}


def save(directory: Path, name: str, content: bytes) -> Path:
    """Write via a temporary file so an interrupted fetch never leaves a half-written file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download official reference data.")
    parser.add_argument("source", choices=[*FETCHERS, "all"])
    parser.add_argument("--dir", type=Path, default=Path("../data/reference"))
    args = parser.parse_args(argv)

    sources = list(FETCHERS) if args.source == "all" else [args.source]
    for source in sources:
        path = save(args.dir, FILES[source], FETCHERS[source]())
        print(f"{source}: {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
