"""What the harness asks of a pipeline: given a shipment's files, say what each file is, what the
documents contain and which checks fail.

A pipeline sees only the files, never case.json or bundle.json, which hold the answers.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Protocol

from evals.answer_cache import CachedExtractor
from evals.page_cache import cached_pages
from shipready.ai import (
    AiAnswer,
    AiMode,
    GeminiClassifier,
    PageClassifier,
    RateLimited,
    extractor_from_env,
)
from shipready.api.uploads import media_type
from shipready.classify import split_into_parts
from shipready.extract import DocumentText, FieldExtractor, RawField, extract_fields

# Waits for a rate-limited or overloaded AI before the run gives up (a spent daily quota will
# not recover).
MAX_AI_WAITS = 10
# A longer wait than this means the day's quota is spent: the run stops, and answers already
# given are kept in the cache for the next run.
MAX_AI_WAIT_S = 300
# Where pages read by OCR, and the AI's extraction answers, are kept between runs.
PAGE_CACHE = Path(os.environ.get("EVALS_PAGE_CACHE", "../data/evals/page-cache"))
ANSWER_CACHE = Path(os.environ.get("EVALS_ANSWER_CACHE", "../data/evals/answer-cache"))


@dataclass(frozen=True)
class Prediction:
    files: dict[str, tuple[str, ...]] = field(default_factory=dict)  # file -> document types
    fields: dict[str, object] = field(default_factory=dict)  # same paths as EvalCase.fields
    located: frozenset[str] = frozenset()  # field paths whose evidence box was found
    findings: frozenset[str] = frozenset()  # rule IDs reported
    cost_usd: Decimal = Decimal(0)


class Pipeline(Protocol):
    name: str

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction: ...


class EmptyPipeline:
    """Reads nothing and reports nothing: the floor every real pipeline must beat."""

    name = "empty"

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        return Prediction()


class ClassifyPipeline:
    """Reads each file's pages and splits it into documents, as the worker does (Phase 10).
    It predicts document types only."""

    def __init__(self, mode: AiMode) -> None:
        self.mode = mode
        self.name = {"never": "rules", "fallback": "rules+ai", "always": "ai"}[mode]
        self.ai: PageClassifier | None = None
        if mode != "never":
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError(f"the {self.name} pipeline needs GEMINI_API_KEY")
            self.ai = _PatientClassifier(GeminiClassifier(key))

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        predicted, _ = read_documents(folder, files, self.mode, self.ai)
        return Prediction(files=predicted)


class ExtractPipeline:
    """Splits files into documents by their titles, then reads every field of the shipment in
    one AI request with its evidence (Phase 11). Answers are cached (evals.answer_cache)."""

    name = "extract"

    def __init__(self) -> None:
        try:
            extractor = extractor_from_env()
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        self.extractor = _PatientExtractor(CachedExtractor(extractor, ANSWER_CACHE))

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        predicted, documents = read_documents(folder, files, "never", None)
        fields = extract_fields(documents, self.extractor)
        return Prediction(
            files=predicted,
            fields={f.path: f.value for f in fields},
            located=frozenset(f.path for f in fields if f.box is not None),
        )


def read_documents(
    folder: Path, files: tuple[str, ...], mode: AiMode, ai: PageClassifier | None
) -> tuple[dict[str, tuple[str, ...]], list[DocumentText]]:
    """Each file's document types, and every document with its pages, numbered across files."""
    predicted: dict[str, tuple[str, ...]] = {}
    documents: list[DocumentText] = []
    for path in files:
        data = (folder / path).read_bytes()
        kind = media_type(data)
        if kind is None:
            raise ValueError(f"{folder / path} is not a file type ShipReady accepts")
        pages = cached_pages(data, kind, PAGE_CACHE)
        parts = split_into_parts(pages, mode, ai)
        predicted[path] = tuple(part.doc_type for part in parts)
        documents += [
            DocumentText(
                len(documents) + n,
                part.doc_type,
                path,
                tuple(pages[part.first_page - 1 : part.last_page]),
            )
            for n, part in enumerate(parts, start=1)
        ]
    return predicted, documents


def _patiently[T](ask: Callable[[], T]) -> T:
    """Waits out the AI's rate limits, as the worker's retries do."""
    for _ in range(MAX_AI_WAITS):
        try:
            return ask()
        except RateLimited as error:
            if error.retry_after > MAX_AI_WAIT_S:
                raise RuntimeError(
                    f"AI quota spent; it resets in {error.retry_after / 3600:.1f} h. Answers so "
                    "far are cached, so running again then continues from here."
                ) from error
            time.sleep(error.retry_after)
    return ask()


class _PatientClassifier:
    def __init__(self, ai: PageClassifier) -> None:
        self.ai = ai

    def classify(self, page_text: str) -> AiAnswer:
        return _patiently(lambda: self.ai.classify(page_text))


class _PatientExtractor:
    def __init__(self, extractor: FieldExtractor) -> None:
        self.extractor = extractor
        self.model = extractor.model

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        return _patiently(lambda: self.extractor.extract(documents, guide))


PIPELINES: dict[str, Callable[[], Pipeline]] = {
    "empty": EmptyPipeline,
    "rules": partial(ClassifyPipeline, "never"),
    "rules+ai": partial(ClassifyPipeline, "fallback"),
    "ai": partial(ClassifyPipeline, "always"),
    "extract": ExtractPipeline,
}
