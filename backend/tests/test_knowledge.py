import json
from pathlib import Path

import pytest

from shipready.knowledge import fetch
from shipready.knowledge.sources import Source, SourcesError, load_sources, parse_sources
from shipready.reference.fetch import FetchError

VALID = """
- id: hbp
  title: Handbook of Procedures 2023
  issuer: DGFT
  version: As issued
  url: https://content.dgft.gov.in/Website/HBP_2023.pdf
  format: pdf
  used_by: [POL-02]
"""


def test_packaged_sources_are_valid() -> None:
    sources = load_sources()
    assert len(sources) >= 10
    assert {"ftp-2023", "hbp-2023", "cgst-rule-96a"} <= {source.id for source in sources}


def test_parse_valid_source() -> None:
    (source,) = parse_sources(VALID)
    assert source == Source(
        id="hbp",
        title="Handbook of Procedures 2023",
        issuer="DGFT",
        version="As issued",
        url="https://content.dgft.gov.in/Website/HBP_2023.pdf",
        format="pdf",
        used_by=("POL-02",),
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("https://content.dgft.gov.in", "https://taxguru.in"), "official host"),
        (("https://", "http://"), "official host"),
        (("format: pdf", "format: docx"), "format must be"),
        (("[POL-02]", "[XYZ-99]"), "check IDs"),
        (("version: As issued", "version: ''"), "non-empty text"),
        (("  used_by: [POL-02]\n", ""), "fields must be exactly"),
    ],
)
def test_invalid_source_is_rejected(change: tuple[str, str], message: str) -> None:
    with pytest.raises(SourcesError, match=message):
        parse_sources(VALID.replace(*change))


def test_duplicate_and_empty_lists_are_rejected() -> None:
    with pytest.raises(SourcesError, match="duplicate"):
        parse_sources(VALID + VALID)
    with pytest.raises(SourcesError, match="non-empty list"):
        parse_sources("[]")


def test_fetch_all_saves_files_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [
        *parse_sources(VALID),
        *parse_sources(VALID.replace("id: hbp", "id: rule").replace("format: pdf", "format: html")),
    ]
    bodies = {"pdf": b"%PDF-1.7 handbook", "html": b"<!DOCTYPE html><html>rule</html>"}
    replies = iter([bodies["pdf"], bodies["html"]])
    monkeypatch.setattr(fetch, "request", lambda url: next(replies))

    entries = fetch.fetch_all(tmp_path, sources)
    assert (tmp_path / "hbp.pdf").read_bytes() == bodies["pdf"]
    assert (tmp_path / "rule.html").read_bytes() == bodies["html"]
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["sources"] == entries
    assert entries[0]["bytes"] == len(bodies["pdf"])
    assert len(str(entries[0]["sha256"])) == 64


def test_error_page_instead_of_pdf_fails_and_keeps_old_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "manifest.json").write_text('{"sources": []}', encoding="utf-8")
    monkeypatch.setattr(fetch, "request", lambda url: b"<html>Service unavailable</html>")
    with pytest.raises(FetchError, match="expected a PDF"):
        fetch.fetch_all(tmp_path, parse_sources(VALID))
    assert (tmp_path / "manifest.json").read_text("utf-8") == '{"sources": []}'
    assert not (tmp_path / "hbp.pdf").exists()
