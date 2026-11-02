import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shipready.ai import RateLimited
from shipready.db.models import EMBEDDING_DIMENSIONS, KnowledgeChunk
from shipready.knowledge import index
from shipready.knowledge.index import (
    CHUNK_CHARS,
    OVERLAP_CHARS,
    index_sources,
    read_pages,
    search,
    split_passages,
)

LUT_RULE = (
    "Every export invoice shall carry the endorsement supply meant for export under bond or "
    "letter of undertaking without payment of integrated tax."
)


class WordEmbedder:
    """Places a text by which of a few words it contains, so related texts are near."""

    model = "word-embedder"
    WORDS = ("export", "invoice", "phytosanitary", "plant", "letter", "undertaking")

    def __init__(self) -> None:
        self.requests: list[int] = []

    def embed(self, texts: list[str], query: bool) -> list[list[float]]:
        self.requests.append(len(texts))
        return [self._vector(text.casefold()) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [float(word in text) for word in self.WORDS]
        vector += [0.01] * (EMBEDDING_DIMENSIONS - len(vector))  # never all zero
        return vector


def test_passages_are_split_at_sentences_with_overlap() -> None:
    sentence = "A rule about exports applies here. "
    text = sentence * 120
    passages = split_passages("ftp-2023", [(3, text), (4, "Short page.")])
    assert all(len(p.text) <= CHUNK_CHARS for p in passages)
    assert all(p.text.endswith(".") for p in passages[:-1])
    assert [p.page for p in passages][-1] == 4
    first, second = passages[0].text, passages[1].text
    assert first[-OVERLAP_CHARS // 2 :] in second  # the end of one starts the next
    assert all(p.source_id == "ftp-2023" for p in passages)


def test_blank_pages_give_no_passages() -> None:
    assert split_passages("x", [(1, "   \n  "), (2, "")]) == []


def test_html_sources_are_read_without_scripts(tmp_path: Path) -> None:
    page = tmp_path / "rule.html"
    page.write_text(
        "<html><head><style>p {}</style><script>var x = 1;</script></head>"
        f"<body><h1>Rule 96A</h1><p>{LUT_RULE}</p></body></html>",
        encoding="utf-8",
    )
    ((number, text),) = read_pages(page)
    assert number is None
    assert "Rule 96A" in text and LUT_RULE in text
    assert "var x" not in text and "p {}" not in text


def test_other_formats_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only PDF and HTML"):
        read_pages(tmp_path / "notes.docx")


def knowledge(tmp_path: Path, texts: dict[str, str]) -> Path:
    """A fetched knowledge folder of HTML sources and its manifest."""
    sources = []
    for source_id, text in texts.items():
        body = f"<html><body><p>{text}</p></body></html>".encode()
        (tmp_path / f"{source_id}.html").write_bytes(body)
        sources.append(
            {
                "id": source_id,
                "file": f"{source_id}.html",
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    (tmp_path / "manifest.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return tmp_path


def test_index_stores_passages_and_skips_unchanged_sources(
    session: Session, tmp_path: Path
) -> None:
    folder = knowledge(
        tmp_path,
        {
            "gst-rule": LUT_RULE,
            "plant-rule": "A phytosanitary certificate is needed for plant exports.",
        },
    )
    embedder = WordEmbedder()
    assert index_sources(session, embedder, folder) == {"gst-rule": 1, "plant-rule": 1}
    assert index_sources(session, embedder, folder) == {}  # nothing changed: nothing asked
    assert embedder.requests == [1, 1]

    (folder / "manifest.json").write_text(
        json.dumps({"sources": [{"id": "gst-rule", "file": "gst-rule.html", "sha256": "changed"}]}),
        encoding="utf-8",
    )
    assert index_sources(session, embedder, folder) == {"gst-rule": 1}
    rows = session.execute(
        select(KnowledgeChunk.source_id, func.count()).group_by(KnowledgeChunk.source_id)
    )
    counts = {source_id: count for source_id, count in rows}
    assert counts == {"gst-rule": 1, "plant-rule": 1}  # replaced, not added to


def test_search_finds_the_nearest_passages(session: Session, tmp_path: Path) -> None:
    embedder = WordEmbedder()
    assert search(session, embedder, "anything") == []  # nothing indexed
    folder = knowledge(
        tmp_path,
        {
            "gst-rule": LUT_RULE,
            "plant-rule": "A phytosanitary certificate is needed for plant exports.",
        },
    )
    index_sources(session, embedder, folder)

    (best, distance), _ = search(
        session, embedder, "Is a phytosanitary certificate needed for plants?"
    )
    assert (best.source_id, best.page) == ("plant-rule", None)
    assert 0 <= distance < 0.5
    only_gst = search(session, embedder, "phytosanitary", sources=("gst-rule",))
    assert [chunk.source_id for chunk, _ in only_gst] == ["gst-rule"]


def test_minute_limits_are_waited_out(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("shipready.knowledge.index.time.sleep", waits.append)
    vectors = [[0.5] * EMBEDDING_DIMENSIONS]
    answers: list[RateLimited | list[list[float]]] = [RateLimited(20), vectors]

    class Flaky(WordEmbedder):
        def embed(self, texts: list[str], query: bool) -> list[list[float]]:
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    assert index._patiently(Flaky(), ["text"]) == [[0.5] * EMBEDDING_DIMENSIONS]
    assert waits == [20]
    answers.append(RateLimited(6000))
    with pytest.raises(RateLimited):
        index._patiently(Flaky(), ["text"])  # a spent daily quota is not waited for
