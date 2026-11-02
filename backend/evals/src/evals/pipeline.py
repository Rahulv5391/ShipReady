"""What the harness asks of a pipeline: given a shipment's files, say what each file is, what the
documents contain and which checks fail.

A pipeline sees only the files, never case.json or bundle.json, which hold the answers.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

from evals.answer_cache import CachedCritic, CachedExtractor, CachedJudge
from evals.cases import load_case
from evals.page_cache import cached_pages, page_image
from shipready.ai import (
    AiAnswer,
    AiMode,
    Critic,
    GeminiClassifier,
    Judge,
    PageClassifier,
    Question,
    RateLimited,
    Review,
    Suspect,
    Verdict,
    critic_from_env,
    embedder_from_env,
    extractor_from_env,
    judge_from_env,
)
from shipready.api.uploads import media_type
from shipready.checks.critic import crop_png, review
from shipready.checks.engine import run_checks
from shipready.checks.readiness import assess
from shipready.checks.reference import DbReference
from shipready.checks.semantic import DbKnowledge, run_semantic_checks
from shipready.classify import split_into_parts
from shipready.db.session import make_engine
from shipready.extract import Box, DocumentText, FieldExtractor, RawField, extract_fields

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
    readiness: str | None = None  # ready, needs_fix or needs_review (Phase 15)
    # Where each extracted field was read: path -> (file, quote, page, box).
    evidence: dict[str, tuple[str, str, int, Box | None]] = field(default_factory=dict)
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
        files_of = {document.part: document.filename for document in documents}
        return Prediction(
            files=predicted,
            fields={f.path: f.value for f in fields},
            located=frozenset(f.path for f in fields if f.box is not None),
            evidence={f.path: (files_of[f.part], f.quote, f.page, f.box) for f in fields},
        )


class FileEvidence:
    """The critic's evidence from the dataset's files: crops of the cached page images."""

    def __init__(self, folder: Path, prediction: Prediction) -> None:
        self.folder = folder
        self.prediction = prediction

    def read(self, path: str) -> tuple[str, str] | None:
        if path not in self.prediction.evidence:
            return None
        return str(self.prediction.fields[path]), self.prediction.evidence[path][1]

    def crop(self, path: str) -> bytes | None:
        if path not in self.prediction.evidence:
            return None
        file, _, page, box = self.prediction.evidence[path]
        if box is None:
            return None
        data = (self.folder / file).read_bytes()
        image = page_image(data, media_type(data) or "", page, PAGE_CACHE)
        return crop_png(image, (box.x0, box.y0, box.x1, box.y1)) if image else None


class ChecksPipeline:
    """Runs every check, deterministic (Phase 13) and semantic (Phase 14), on fields: those
    `ExtractPipeline` reads from the files, or, with `on_labels`, the dataset's labelled fields.
    The latter is the one pipeline that reads the answers (case.json): it measures the checks
    apart from extraction. With `critic`, failures are reviewed against the page images
    (Phase 15). The judge's and critic's answers are cached like extraction's."""

    def __init__(self, on_labels: bool, critic: bool = False) -> None:
        self.name = "checks-on-labels" if on_labels else "checks+critic" if critic else "checks"
        self.extract = None if on_labels else ExtractPipeline()
        self.critic = (
            CachedCritic(_PatientCritic(critic_from_env()), ANSWER_CACHE) if critic else None
        )
        self.session = Session(make_engine())
        self.reference = DbReference(self.session)
        try:
            judge, embedder = judge_from_env(), embedder_from_env()
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        self.judge = CachedJudge(_PatientJudge(judge), ANSWER_CACHE)
        self.knowledge = DbKnowledge(self.session, embedder)

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        if self.extract is None:
            read = Prediction(fields=load_case(folder).fields)
        else:
            read = self.extract.run(folder, files)
        results = run_checks(read.fields, self.reference) + run_semantic_checks(
            read.fields, self.reference, self.judge, self.knowledge
        )
        if self.critic is not None:
            results = review(results, FileEvidence(folder, read), self.critic)
        failed = frozenset(r.rule_id for r in results if r.outcome == "fail")
        return replace(read, findings=failed, readiness=assess(results).readiness)


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


class _PatientCritic:
    def __init__(self, critic: Critic) -> None:
        self.inner = critic
        self.model = critic.model

    def review(self, suspects: list[Suspect]) -> list[Review]:
        return _patiently(lambda: self.inner.review(suspects))


class _PatientJudge:
    def __init__(self, judge: Judge) -> None:
        self.inner = judge
        self.model = judge.model

    def judge(self, questions: list[Question]) -> list[Verdict]:
        return _patiently(lambda: self.inner.judge(questions))


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
    "checks": partial(ChecksPipeline, on_labels=False),
    "checks-on-labels": partial(ChecksPipeline, on_labels=True),
    "checks+critic": partial(ChecksPipeline, on_labels=False, critic=True),
}
