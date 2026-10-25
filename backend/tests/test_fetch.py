"""The fetch module, with HTTP stubbed: tests never call government servers."""

import io
import json
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shipready.reference import fetch
from shipready.reference.fetch import FetchError


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def respond(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[str, bytes | None], bytes]
) -> list[str]:
    """Route `fetch.request` to `handler(url, data)` and record the URLs requested."""
    calls: list[str] = []

    def request(
        url: str, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> bytes:
        calls.append(url)
        return handler(url, data)

    monkeypatch.setattr(fetch, "request", request)
    return calls


def test_request_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def urlopen(req: Any, timeout: int) -> io.BytesIO:
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.URLError("connection reset")
        return io.BytesIO(b"ok")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert fetch.request("https://example.test/a") == b"ok"
    assert len(attempts) == 3


def test_request_gives_up_with_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(req: Any, timeout: int) -> io.BytesIO:
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(FetchError, match=r"POST https://example\.test/a failed after 3 attempts"):
        fetch.request("https://example.test/a", b"x")


def test_an_error_page_is_not_saved_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, lambda url, data: b"<html><title>Error Page</title></html>")
    with pytest.raises(FetchError, match="ITC\\(HS\\) codes: expected JSON"):
        fetch.fetch_itc_hs()
    with pytest.raises(FetchError, match="ports: expected JSON"):
        fetch.fetch_ports()
    with pytest.raises(FetchError, match="ISO 4217 list: unexpected response"):
        fetch.fetch_currencies()
    with pytest.raises(FetchError, match="UN/LOCODE: expected a zip file"):
        fetch.fetch_unlocode()


def test_export_policy_collects_lists_and_todays_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(url: str, data: bytes | None) -> bytes:
        if "getItcDtlsByImportPolicy" in url:
            policy = dict(pair.split("=") for pair in (data or b"").decode().split("&"))[
                "itchsPolicy"
            ]
            code = {"Restricted": "17019990", "Prohibited": "17019990", "STE": "25085031"}[policy]
            return json.dumps({"itcCodeClassifications": [{"itcCode": f" {code} "}]}).encode()
        code = "17019990" if b"17019990" in (data or b"") else "25085031"
        policy = "Restricted" if code == "17019990" else "STE"
        return f"<td>Export Policy</td> <td>{policy}</td> Policy specified at 8-digit".encode()

    calls = respond(monkeypatch, handler)
    payload = json.loads(fetch.fetch_export_policy())
    assert set(payload["lists"]) == {"Restricted", "Prohibited", "STE"}
    assert payload["current"] == {"17019990": "Restricted", "25085031": "STE"}
    assert sum("importerExporter" in url for url in calls) == 2  # each code checked once


def test_a_policy_page_without_a_policy_stops_the_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, lambda url, data: b"<html>maintenance</html>")
    with pytest.raises(FetchError, match="export policy page for 17019990 has no 'Export Policy'"):
        fetch.current_export_policy("17019990")


def test_a_broken_policy_list_stops_the_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, lambda url, data: b'{"responseCode": 500}')
    with pytest.raises(FetchError, match="Restricted export list: unexpected response"):
        fetch.fetch_export_policy()


def test_exchange_rates_fetch_every_listed_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(url: str, data: bytes | None) -> bytes:
        if url.endswith("getnotdetails"):
            return b'[{"notificationNumber": "29/2026"}, {"notificationNumber": "28/2026"}]'
        number = json.loads(data or b"{}")["notNum"]
        return json.dumps(
            {"status": 1, "notificationNumber": number, "currencyDetail": [{}]}
        ).encode()

    respond(monkeypatch, handler)
    payload = json.loads(fetch.fetch_exchange_rates())
    assert set(payload["details"]) == {"29/2026", "28/2026"}


def test_an_empty_notification_stops_the_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(url: str, data: bytes | None) -> bytes:
        if url.endswith("getnotdetails"):
            return b'[{"notificationNumber": "29/2026"}]'
        return b'{"status": 0, "error": "not found"}'

    respond(monkeypatch, handler)
    with pytest.raises(FetchError, match="notification 29/2026: no rates in response"):
        fetch.fetch_exchange_rates()


def test_save_replaces_the_file_atomically(tmp_path: Path) -> None:
    path = fetch.save(tmp_path / "reference", "data.json", b"new")
    assert path.read_bytes() == b"new"
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]  # no .part left behind


def test_main_fetches_the_chosen_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(fetch.FETCHERS, "ports", lambda: b"[]")
    fetch.main(["ports", "--dir", str(tmp_path)])
    assert (tmp_path / "dgft-ports.json").read_bytes() == b"[]"
    assert "ports:" in capsys.readouterr().out
