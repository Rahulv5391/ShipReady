"""Load ShipGen's labelled dataset as evaluation cases: the files a pipeline is given, and the
truth it is scored against (document types per file, field values, expected findings)."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from shipgen.bundle import Bundle
from shipgen.dataset import Case, Split
from shipgen.mutations import missing_documents
from shipready.rules.catalogue import load_catalogue

Medium = Literal["digital", "image"]  # PDF or Excel with text, or a scan or photo
# How each bundle format reaches a pipeline.
MEDIUM: dict[str, Medium] = {"pdf": "digital", "xlsx": "digital", "scan": "image", "photo": "image"}


@dataclass(frozen=True)
class EvalCase:
    shipment_id: str
    folder: Path
    files: dict[str, tuple[str, ...]]  # file path -> document types in it, in page order
    fields: dict[str, object]  # field path, e.g. "packing_list.lines[0].quantity" -> value
    media: dict[str, Medium]  # document type -> how it arrived
    findings: frozenset[str]  # rule IDs that must be reported

    @property
    def clean(self) -> bool:
        return not self.findings


def load_cases(dataset: Path, split: Split) -> list[EvalCase]:
    """Every case of `split`, in manifest order. Cases written with --labels-only (no files)
    are refused: a pipeline needs the files."""
    manifest = dataset / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"{manifest} not found; build the dataset with shipgen.dataset")
    entries = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
    return [
        _load(dataset / split / entry["shipment_id"])
        for entry in entries
        if entry["split"] == split
    ]


def _load(folder: Path) -> EvalCase:
    bundle_path = folder / "bundle.json"
    if not bundle_path.is_file():
        raise FileNotFoundError(f"{bundle_path} not found; build the dataset without --labels-only")
    case = Case.model_validate_json((folder / "case.json").read_text(encoding="utf-8"))
    bundle = Bundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    missing = missing_documents(case.labels)
    fields: dict[str, object] = {}
    for name in type(case.documents).model_fields:
        document = getattr(case.documents, name)
        if document is not None and name not in missing:
            fields.update(flatten(document, name))
    return EvalCase(
        shipment_id=case.shipment_id,
        folder=folder,
        files={file.path: file.documents for file in bundle.files},
        fields=fields,
        media={name: MEDIUM[file.format] for file in bundle.files for name in file.documents},
        findings=frozenset(case.rule_ids),
    )


def flatten(value: object, path: str) -> dict[str, object]:
    """Every scalar under `value` by its path, keeping Python types (Decimal, date) so values
    compare exactly. Empty and missing values are left out: there is nothing to extract."""
    if isinstance(value, BaseModel):
        return {
            key: item
            for name in type(value).model_fields
            for key, item in flatten(getattr(value, name), f"{path}.{name}").items()
        }
    if isinstance(value, tuple):
        return {
            key: item
            for i, element in enumerate(value)
            for key, item in flatten(element, f"{path}[{i}]").items()
        }
    if value is None or value == "":
        return {}
    return {path: value}


@cache
def severities() -> dict[str, str]:
    return {rule.id: rule.severity for rule in load_catalogue()}
