"""What the harness asks of a pipeline: given a shipment's files, say what each file is, what the
documents contain and which checks fail.

A pipeline sees only the files, never case.json or bundle.json, which hold the answers.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol


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


PIPELINES: dict[str, type[Pipeline]] = {"empty": EmptyPipeline}
