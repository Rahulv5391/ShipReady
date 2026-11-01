"""The AI's extraction answers, kept on disk, so scoring a pipeline again does not spend the
free tier's quota on questions already answered.

The key is everything that shapes the answer: the model, the instructions, the field guide and
the documents' text. Any change asks the AI afresh.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from shipready.ai import EXTRACT_INSTRUCTIONS
from shipready.extract import DocumentText, FieldExtractor, RawField


class CachedExtractor:
    def __init__(self, extractor: FieldExtractor, directory: Path) -> None:
        self.extractor = extractor
        self.directory = directory
        self.model = extractor.model

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        question = {
            "model": self.extractor.model,
            "instructions": EXTRACT_INSTRUCTIONS,
            "guide": guide,
            "documents": [
                [d.part, d.doc_type, [[p.number, p.text] for p in d.pages]] for d in documents
            ],
        }
        key = hashlib.sha256(json.dumps(question, sort_keys=True).encode()).hexdigest()
        path = self.directory / f"{key}.json"
        if path.is_file():
            return [RawField(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
        fields = self.extractor.extract(documents, guide)
        self.directory.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_text(json.dumps([asdict(f) for f in fields]), encoding="utf-8")
        partial.replace(path)
        return fields
