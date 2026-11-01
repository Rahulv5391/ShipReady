"""What the harness asks of a pipeline: given a shipment's files, say what each file is, what the
documents contain and which checks fail.

A pipeline sees only the files, never case.json or bundle.json, which hold the answers.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from shipready.ai import AiAnswer, AiMode, GeminiClassifier, PageClassifier, RateLimited
from shipready.api.uploads import media_type
from shipready.classify import split_into_parts
from shipready.pages import read_pages

# Waits for a rate-limited AI before the run gives up (a spent daily quota will not recover).
MAX_AI_WAITS = 3


@dataclass(frozen=True)
class Prediction:
    files: dict[str, tuple[str, ...]] = field(default_factory=dict)  # file -> document types
    fields: dict[str, object] = field(default_factory=dict)  # same paths as EvalCase.fields
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
    It predicts document types only; fields and findings come with later phases."""

    def __init__(self, mode: AiMode) -> None:
        self.mode = mode
        self.name = {"never": "rules", "fallback": "rules+ai", "always": "ai"}[mode]
        self.ai: PageClassifier | None = None
        if mode != "never":
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ValueError(f"the {self.name} pipeline needs GEMINI_API_KEY")
            self.ai = _Patient(GeminiClassifier(key))

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        predicted = {}
        for path in files:
            data = (folder / path).read_bytes()
            kind = media_type(data)
            if kind is None:
                raise ValueError(f"{folder / path} is not a file type ShipReady accepts")
            parts = split_into_parts(read_pages(data, kind), self.mode, self.ai)
            predicted[path] = tuple(part.doc_type for part in parts)
        return Prediction(files=predicted)


class _Patient:
    """Waits out the AI's rate limits, as the worker's retries do."""

    def __init__(self, ai: PageClassifier) -> None:
        self.ai = ai

    def classify(self, page_text: str) -> AiAnswer:
        for _ in range(MAX_AI_WAITS):
            try:
                return self.ai.classify(page_text)
            except RateLimited as error:
                time.sleep(error.retry_after)
        return self.ai.classify(page_text)


PIPELINES: dict[str, Callable[[], Pipeline]] = {
    "empty": EmptyPipeline,
    "rules": lambda: ClassifyPipeline("never"),
    "rules+ai": lambda: ClassifyPipeline("fallback"),
    "ai": lambda: ClassifyPipeline("always"),
}
