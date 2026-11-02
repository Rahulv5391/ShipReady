"""Index the fetched regulatory texts for search: split each into passages, embed them and store
them in Postgres (pgvector), so the compliance checks can cite the rule they rely on.

    uv run --env-file .env python -m shipready.knowledge.index --dir ../data/knowledge

A source whose file is unchanged since it was indexed (same SHA-256 in manifest.json) is skipped,
so running again costs nothing; a changed source has its passages replaced.
"""

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from shipready.ai import EMBED_BATCH, Embedder, RateLimited, embedder_from_env
from shipready.db.models import KnowledgeChunk
from shipready.db.session import make_engine

logger = logging.getLogger(__name__)
# About a page's paragraph: enough context to stand alone as a citation, small enough that a
# search hit is about one thing.
CHUNK_CHARS = 1500
# Carried over from the previous passage, so a rule split across two passages is whole in one.
OVERLAP_CHARS = 200
# The free tier limits tokens per minute; waits longer than this mean a spent daily quota.
MAX_WAITS = 10
MAX_WAIT_S = 120


@dataclass(frozen=True)
class Passage:
    source_id: str
    page: int | None
    text: str


def read_pages(path: Path) -> list[tuple[int | None, str]]:
    """The text of each page of a PDF, or of a web page as a whole (page None)."""
    if path.suffix == ".pdf":
        document = pdfium.PdfDocument(path)
        try:
            return [
                (number, page.get_textpage().get_text_range())
                for number, page in enumerate(document, start=1)
            ]
        finally:
            document.close()
    if path.suffix == ".html":
        return [(None, _html_text(path.read_text(encoding="utf-8", errors="replace")))]
    raise ValueError(f"cannot index {path.name}: only PDF and HTML sources are indexed")


_HIDDEN_TAGS = ("script", "style")


class _TextOnly(HTMLParser):
    """The visible text of a page, without scripts and styles."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _html_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    return "\n".join(parser.parts)


def split_passages(source_id: str, pages: list[tuple[int | None, str]]) -> list[Passage]:
    """Each page's text in passages of about CHUNK_CHARS, broken at sentence ends where one is
    near, each starting with the end of the one before."""
    passages = []
    for page, raw in pages:
        text = re.sub(r"\s+", " ", raw).strip()
        start = 0
        while start < len(text):
            end = min(start + CHUNK_CHARS, len(text))
            if end < len(text):
                stop = text.rfind(". ", start + CHUNK_CHARS // 2, end)
                end = stop + 1 if stop > 0 else end
            passages.append(Passage(source_id, page, text[start:end].strip()))
            if end == len(text):
                break
            start = max(end - OVERLAP_CHARS, start + 1)
    return [p for p in passages if p.text]


def index_sources(session: Session, embedder: Embedder, folder: Path) -> dict[str, int]:
    """Index every source in the folder's manifest.json whose file changed; the number of
    passages stored per source indexed now."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["sources"]
    indexed = {}
    for source in manifest:
        stored = session.scalar(
            select(KnowledgeChunk.source_sha256)
            .where(KnowledgeChunk.source_id == source["id"])
            .limit(1)
        )
        if stored == source["sha256"]:
            continue
        passages = split_passages(source["id"], read_pages(folder / source["file"]))
        texts = [p.text for p in passages]
        vectors = [
            vector
            for start in range(0, len(texts), EMBED_BATCH)
            for vector in _patiently(embedder, texts[start : start + EMBED_BATCH])
        ]
        session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source["id"]))
        session.add_all(
            KnowledgeChunk(
                source_id=passage.source_id,
                source_sha256=source["sha256"],
                chunk_no=number,
                page=passage.page,
                text=passage.text,
                embedding=vector,
                model=embedder.model,
            )
            for number, (passage, vector) in enumerate(zip(passages, vectors, strict=True))
        )
        session.commit()
        indexed[source["id"]] = len(passages)
        logger.info("%s: %d passages", source["id"], len(passages))
    return indexed


def _patiently(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    """Embed `texts`, waiting out per-minute limits; a longer wait means the day's quota is
    spent, and the sources indexed so far are kept."""
    for _ in range(MAX_WAITS):
        try:
            return embedder.embed(texts, query=False)
        except RateLimited as error:
            if error.retry_after > MAX_WAIT_S:
                raise
            time.sleep(error.retry_after)
    return embedder.embed(texts, query=False)


def search(
    session: Session,
    embedder: Embedder,
    question: str,
    limit: int = 5,
    sources: tuple[str, ...] = (),
) -> list[tuple[KnowledgeChunk, float]]:
    """The passages nearest to `question`, with their cosine distance (0 is identical), from
    `sources` only when given. Empty when nothing is indexed."""
    (vector,) = embedder.embed([question], query=True)
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    query = select(KnowledgeChunk, distance).order_by(distance).limit(limit)
    if sources:
        query = query.where(KnowledgeChunk.source_id.in_(sources))
    return [(chunk, float(d)) for chunk, d in session.execute(query)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Index the fetched regulatory texts.")
    parser.add_argument("--dir", type=Path, default=Path("../data/knowledge"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = make_engine()
    try:
        with Session(engine) as session:
            indexed = index_sources(session, embedder_from_env(), args.dir)
    finally:
        engine.dispose()
    print(f"{len(indexed)} sources indexed")


if __name__ == "__main__":
    main()
