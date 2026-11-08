"""Word documents to PDF with headless LibreOffice, so they are read, highlighted and reviewed
like any PDF (Decision.md D-34).

LibreOffice runs as a separate process with a profile of its own in a temporary folder, so
conversions in parallel worker processes cannot lock each other's profile. The worker's Docker
image installs it; elsewhere SOFFICE_PATH names the `soffice` program.
"""

import os
import subprocess
import tempfile
from pathlib import Path

# A page or two of trade paperwork converts in a few seconds; much longer means LibreOffice hung.
TIMEOUT_S = 60


class ConversionError(Exception):
    """The Word document could not be turned into a PDF."""


def docx_to_pdf(data: bytes) -> bytes:
    """The PDF LibreOffice makes of a Word document's bytes."""
    soffice = os.environ.get("SOFFICE_PATH", "soffice")
    with tempfile.TemporaryDirectory(prefix="shipready-docx-") as folder:
        work = Path(folder)
        source = work / "document.docx"
        source.write_bytes(data)
        command = [
            soffice,
            f"-env:UserInstallation={(work / 'profile').as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(source),
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=TIMEOUT_S, check=False)
        except FileNotFoundError as error:
            raise ConversionError(
                f"LibreOffice ({soffice}) is not installed; set SOFFICE_PATH or run the worker's "
                "Docker image"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ConversionError(f"LibreOffice took longer than {TIMEOUT_S} s") from error
        output = work / "document.pdf"
        if result.returncode != 0 or not output.is_file():
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()
            raise ConversionError(f"LibreOffice could not convert the file: {detail[:300]}")
        return output.read_bytes()
