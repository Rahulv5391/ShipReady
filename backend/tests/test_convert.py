import subprocess
from pathlib import Path
from typing import Any

import pytest

from shipready import convert, pages
from shipready.api.uploads import DOCX
from shipready.convert import ConversionError, docx_to_pdf

PDF_BYTES = b"%PDF-1.7 converted"


def fake_soffice(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[list[str]]:
    """LibreOffice replaced: `outcome` is the PDF it writes, a return code, or an exception."""
    commands: list[list[str]] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        assert options["timeout"] == convert.TIMEOUT_S
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, bytes):
            folder = Path(command[command.index("--outdir") + 1])
            assert (folder / "document.docx").read_bytes() == b"docx bytes"
            (folder / "document.pdf").write_bytes(outcome)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        return subprocess.CompletedProcess(
            command, outcome, b"", b"Error: source file could not be loaded"
        )

    monkeypatch.setattr("shipready.convert.subprocess.run", run)
    return commands


def test_conversion_runs_headless_with_its_own_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOFFICE_PATH", "/opt/libreoffice/soffice")
    commands = fake_soffice(monkeypatch, PDF_BYTES)
    assert docx_to_pdf(b"docx bytes") == PDF_BYTES
    (command,) = commands
    assert command[0] == "/opt/libreoffice/soffice"
    assert command[1].startswith("-env:UserInstallation=file:")
    assert command[2:6] == ["--headless", "--norestore", "--convert-to", "pdf"]


def test_soffice_is_found_on_the_path_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOFFICE_PATH", raising=False)
    commands = fake_soffice(monkeypatch, PDF_BYTES)
    docx_to_pdf(b"docx bytes")
    assert commands[0][0] == "soffice"


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (FileNotFoundError("soffice"), "LibreOffice .* is not installed"),
        (subprocess.TimeoutExpired("soffice", 60), "took longer than 60 s"),
        (1, "could not convert the file: Error: source file could not be loaded"),
    ],
)
def test_failed_conversions_say_why(
    monkeypatch: pytest.MonkeyPatch, outcome: Any, message: str
) -> None:
    fake_soffice(monkeypatch, outcome)
    with pytest.raises(ConversionError, match=message):
        docx_to_pdf(b"docx bytes")


def test_word_documents_are_read_as_their_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bytes]] = []

    def convert_to_pdf(data: bytes) -> bytes:
        calls.append(("convert", data))
        return PDF_BYTES

    def pdf_pages(data: bytes) -> list[pages.Page]:
        calls.append(("read", data))
        return []

    monkeypatch.setattr(pages, "docx_to_pdf", convert_to_pdf)
    monkeypatch.setattr(pages, "_pdf_pages", pdf_pages)
    assert pages.read_pages(b"docx bytes", DOCX) == []
    assert calls == [("convert", b"docx bytes"), ("read", PDF_BYTES)]
