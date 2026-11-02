"""The AI's answers, kept on disk, so scoring a pipeline again does not spend the free tier's
quota on questions already answered.

The key is everything that shapes an answer: the model, the instructions and the question (the
field guide and documents' text for extraction, the questions for the judge). Any change asks the
AI afresh.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shipready.ai import (
    CRITIC_INSTRUCTIONS,
    EXTRACT_INSTRUCTIONS,
    JUDGE_INSTRUCTIONS,
    Critic,
    Judge,
    Question,
    Review,
    Suspect,
    Verdict,
)
from shipready.extract import DocumentText, FieldExtractor, RawField


def _answer[T: (RawField, Verdict, Review)](
    directory: Path,
    question: object,
    ask: Callable[[], list[T]],
    read: Callable[[dict[str, Any]], T],
) -> list[T]:
    """The cached answer to `question`, or `ask()`'s, stored for next time."""
    key = hashlib.sha256(json.dumps(question, sort_keys=True).encode()).hexdigest()
    path = directory / f"{key}.json"
    if path.is_file():
        return [read(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    answer = ask()
    directory.mkdir(parents=True, exist_ok=True)
    # Written beside and then moved, so a run stopped mid-write leaves no half file to read.
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps([asdict(item) for item in answer]), encoding="utf-8")
    partial.replace(path)
    return answer


class CachedExtractor:
    def __init__(self, extractor: FieldExtractor, directory: Path) -> None:
        self.inner = extractor
        self.directory = directory
        self.model = extractor.model

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        question = {
            "model": self.model,
            "instructions": EXTRACT_INSTRUCTIONS,
            "guide": guide,
            "documents": [
                [d.part, d.doc_type, [[p.number, p.text] for p in d.pages]] for d in documents
            ],
        }
        return _answer(
            self.directory,
            question,
            lambda: self.inner.extract(documents, guide),
            lambda item: RawField(**item),
        )


class CachedJudge:
    def __init__(self, judge: Judge, directory: Path) -> None:
        self.inner = judge
        self.directory = directory
        self.model = judge.model

    def judge(self, questions: list[Question]) -> list[Verdict]:
        question = {
            "model": self.model,
            "instructions": JUDGE_INSTRUCTIONS,
            "questions": [[q.id, q.text] for q in questions],
        }
        return _answer(
            self.directory,
            question,
            lambda: self.inner.judge(questions),
            lambda item: Verdict(**item),
        )


class CachedCritic:
    def __init__(self, critic: Critic, directory: Path) -> None:
        self.inner = critic
        self.directory = directory
        self.model = critic.model

    def review(self, suspects: list[Suspect]) -> list[Review]:
        question = {
            "model": self.model,
            "instructions": CRITIC_INSTRUCTIONS,
            "suspects": [
                [
                    s.id,
                    s.check,
                    s.problem,
                    [list(f) for f in s.fields],
                    [[c.path, hashlib.sha256(c.png).hexdigest()] for c in s.crops],
                ]
                for s in suspects
            ],
        }
        return _answer(
            self.directory,
            question,
            lambda: self.inner.review(suspects),
            lambda item: Review(**item),
        )
