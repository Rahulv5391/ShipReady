import random
import re
from collections import Counter
from functools import cache
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from shipgen.bundle import (
    DIGITAL_SHARE,
    SCAN_SHARE,
    Bundle,
    _format,
    write_bundle,
)
from shipgen.dataset import Case, build_case
from shipgen.mutations import get_at, missing_documents
from shipgen.render.common import text


@cache
def labelled_cases() -> tuple[Case, ...]:
    return tuple(build_case(42, index) for index in range(200))


def find(condition: str) -> Case:
    for case in labelled_cases():
        if condition == "missing" and missing_documents(case.labels):
            return case
        if condition == "errors" and len(case.rule_ids) >= 3:
            return case
    raise AssertionError(f"no case with {condition}")


def squash(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def write(case: Case, folder: Path) -> Bundle:
    return write_bundle(case.shipment_id, case.documents, case.labels, folder)


def test_every_document_is_in_exactly_one_file(tmp_path: Path) -> None:
    for case in labelled_cases()[:4]:
        bundle = write(case, tmp_path / case.shipment_id)
        filed = Counter(name for file in bundle.files for name in set(file.documents))
        present = {
            name
            for name in type(case.documents).model_fields
            if getattr(case.documents, name) is not None
            and name not in missing_documents(case.labels)
        }
        assert set(filed) == present
        # Each photo page is its own file, so a document may span several photo files.
        assert all(
            n == 1 or all(f.format == "photo" for f in bundle.files if name in f.documents)
            for name, n in filed.items()
        )
        assert all((tmp_path / case.shipment_id / f.path).is_file() for f in bundle.files)


def test_missing_document_is_left_out(tmp_path: Path) -> None:
    case = find("missing")
    bundle = write(case, tmp_path)
    (missing,) = missing_documents(case.labels)
    assert bundle.missing == (missing,)
    assert all(missing not in file.documents for file in bundle.files)


def test_digital_files_show_the_labelled_values(tmp_path: Path) -> None:
    checked = 0
    for case in labelled_cases():
        if checked >= 3:
            break
        bundle = write(case, tmp_path / case.shipment_id)
        for file in bundle.files:
            if file.format != "pdf":
                continue
            document = pdfium.PdfDocument(tmp_path / case.shipment_id / file.path)
            shown = squash("".join(page.get_textpage().get_text_range() for page in document))
            for label in case.labels:
                for change in label.changes:
                    if change.document not in file.documents or not change.field:
                        continue
                    path = (change.document, *_steps(change.field))
                    value = get_at(case.documents, path)
                    if value is None or value == "" or isinstance(value, tuple):
                        continue
                    layout = file.layouts[file.documents.index(change.document)]
                    assert squash(text(value, layout)) in shown
                    checked += 1
    assert checked >= 3


def _steps(field: str) -> list[str | int]:
    """'lines[3].quantity' -> ['lines', 3, 'quantity']."""
    return [int(step) if step.isdigit() else step for step in re.findall(r"\w+", field)]


def test_bundle_is_reproducible(tmp_path: Path) -> None:
    case = labelled_cases()[0]
    first, second = write(case, tmp_path / "a"), write(case, tmp_path / "b")
    assert first == second
    for file in first.files:
        assert (tmp_path / "a" / file.path).read_bytes() == (
            tmp_path / "b" / file.path
        ).read_bytes()


def test_bundle_json_matches_the_files(tmp_path: Path) -> None:
    case = labelled_cases()[1]
    bundle = write(case, tmp_path)
    assert Bundle.model_validate_json((tmp_path / "bundle.json").read_text("utf-8")) == bundle
    for file in bundle.files:
        if file.path.endswith(".pdf"):
            assert len(pdfium.PdfDocument(tmp_path / file.path)) == file.pages


@pytest.mark.parametrize("name", ["commercial_invoice", "packing_list"])
def test_format_mix(name: str) -> None:
    rng = random.Random(0)
    formats = Counter(_format(name, rng) for _ in range(20_000))
    assert abs(formats["pdf"] / 20_000 - DIGITAL_SHARE) < 0.02
    assert abs(formats["scan"] / 20_000 - SCAN_SHARE) < 0.02
    if name == "packing_list":
        assert formats["xlsx"] > 0 and formats["photo"] > 0
    else:
        assert formats["xlsx"] == 0
