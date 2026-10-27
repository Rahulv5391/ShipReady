"""Download the knowledge base's regulatory texts and record what was fetched.

    uv run python -m shipready.knowledge.fetch --dir ../data/knowledge

Each document is saved as <id>.pdf or <id>.html, and manifest.json records its source, version,
size, SHA-256 and fetch time, so a later index can tell whether a text changed. A response that is
not the expected format (an error page instead of a PDF) fails the fetch and is never saved.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from shipready.knowledge.sources import Source, load_sources
from shipready.reference.fetch import FetchError, request, save


def fetch_source(source: Source) -> bytes:
    body = request(source.url)
    if source.format == "pdf" and not body.startswith(b"%PDF"):
        raise FetchError(f"{source.id}: expected a PDF, got {body[:60]!r}")
    if source.format == "html" and b"<html" not in body[:2000].lower():
        raise FetchError(f"{source.id}: expected an HTML page, got {body[:60]!r}")
    return body


def fetch_all(directory: Path, sources: list[Source]) -> list[dict[str, object]]:
    """Fetch every source, then write the manifest. One failure stops the run before the
    manifest changes, so the manifest never describes files that were not fetched."""
    entries = []
    for source in sources:
        body = fetch_source(source)
        name = f"{source.id}.{source.format}"
        save(directory, name, body)
        entries.append(
            {
                "id": source.id,
                "file": name,
                "title": source.title,
                "issuer": source.issuer,
                "version": source.version,
                "url": source.url,
                "used_by": list(source.used_by),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
    manifest = json.dumps({"sources": entries}, indent=2) + "\n"
    save(directory, "manifest.json", manifest.encode())
    return entries


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download the regulatory knowledge base.")
    parser.add_argument("--dir", type=Path, default=Path("../data/knowledge"))
    args = parser.parse_args(argv)
    for entry in fetch_all(args.dir, load_sources()):
        print(f"{entry['file']}: {entry['bytes']} bytes")


if __name__ == "__main__":
    main()
