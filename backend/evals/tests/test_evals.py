import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from evals import page_cache, pipeline
from evals.__main__ import main
from evals.answer_cache import CachedExtractor
from evals.cases import flatten, load_case, load_cases
from evals.harness import baseline_of, regressions, run, write_report
from evals.metrics import _f1, _normal, _percentile, meets, score_case, summarise
from evals.pipeline import PIPELINES, EmptyPipeline, Prediction
from shipgen.dataset import Case, write_dataset
from shipgen.mutations import missing_documents
from shipgen.reference import SnapshotReference
from shipready.ai import Question, RateLimited, Verdict
from shipready.extract import DocumentText, RawField
from shipready.pages import Page


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("dataset")
    write_dataset(12, 42, folder)
    return folder


class TruthPipeline:
    """Cheats by reading the answers, so every measure must come out perfect."""

    name = "truth"

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        this = load_case(folder)
        return Prediction(files=this.files, fields=this.fields, findings=this.findings)


class AlarmPipeline:
    """Reports the same rule on every shipment."""

    name = "alarm"

    def run(self, folder: Path, files: tuple[str, ...]) -> Prediction:
        return Prediction(findings=frozenset({"QTY-01"}))


def test_load_cases_reads_files_fields_and_findings(dataset: Path) -> None:
    for split in ("dev", "validation", "test"):
        for case in load_cases(dataset, split):
            stored = Case.model_validate_json((case.folder / "case.json").read_text("utf-8"))
            assert case.findings == stored.rule_ids
            assert set(case.files) == {p.name for p in case.folder.iterdir()} - {
                "case.json",
                "bundle.json",
            }
            documents = {path.split(".")[0] for path in case.fields}
            assert documents == set(case.media)
            assert not documents & missing_documents(stored.labels)


def test_load_cases_needs_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"manifest\.json"):
        load_cases(tmp_path, "dev")
    write_dataset(2, 42, tmp_path / "labels", files=False)
    split = json.loads((tmp_path / "labels" / "manifest.json").read_text("utf-8"))["cases"][0]
    with pytest.raises(FileNotFoundError, match="without --labels-only"):
        load_cases(tmp_path / "labels", split["split"])


def test_flatten_keeps_types_and_skips_empty_values() -> None:
    flat = flatten((Decimal("1.50"), "", None, date(2026, 1, 2)), "x")
    assert flat == {"x[0]": Decimal("1.50"), "x[3]": date(2026, 1, 2)}


def test_truth_pipeline_scores_perfectly(dataset: Path) -> None:
    metrics = run(TruthPipeline(), dataset, "dev").metrics
    for name in (
        "classification_accuracy",
        "field_accuracy_digital",
        "field_accuracy_image",
        "line_item_f1",
        "finding_recall",
        "blocker_recall",
        "finding_precision",
    ):
        assert metrics[name] in (1.0, None), name
    assert metrics["finding_recall"] == metrics["det_recall"] == metrics["det_precision"] == 1.0
    assert metrics["false_alarms_per_clean"] in (0.0, None)


def test_empty_pipeline_finds_nothing(dataset: Path) -> None:
    metrics = run(EmptyPipeline(), dataset, "dev").metrics
    assert metrics["finding_recall"] == 0.0
    assert metrics["finding_precision"] is None  # nothing reported: undefined, not 0
    assert metrics["classification_accuracy"] == 0.0
    assert metrics["line_item_f1"] == 0.0


def test_false_alarms_lower_precision(dataset: Path) -> None:
    cases = load_cases(dataset, "dev")
    results = [score_case(case, AlarmPipeline().run(case.folder, ()), 0.0) for case in cases]
    metrics = summarise(results)
    clean = [case for case in cases if case.clean]
    if clean:
        assert metrics["false_alarms_per_clean"] == 1.0
    real = sum(1 for case in cases if "QTY-01" in case.findings)
    assert metrics["finding_precision"] == real / len(cases)


def test_partly_right_extraction(dataset: Path) -> None:
    case = load_cases(dataset, "dev")[0]
    # Every field right except one quantity on the first invoice line.
    wrong = "commercial_invoice.lines[0].quantity"
    fields = dict(case.fields) | {wrong: Decimal(case.fields[wrong]) + 1}  # type: ignore[arg-type]
    result = score_case(case, Prediction(fields=fields), 0.0)
    assert [hit for name, _, hit in result.fields].count(False) == 1
    assert result.lines_matched == result.lines_expected - 1


@pytest.mark.parametrize(
    ("predicted", "truth", "same"),
    [
        ("1,234.50", Decimal("1234.5"), True),
        (1234.5, Decimal("1234.50"), True),
        ("9103030", "09103030", False),  # an HS code keeps its leading zero
        ("09103030", "09103030", True),
        ("2026-10-16", date(2026, 10, 16), True),
        ("16/10/2026", date(2026, 10, 16), False),
        ("  Cotton   T-SHIRT ", "cotton t-shirt", True),
        ("abc", Decimal(1), False),
        ("true", True, True),
    ],
)
def test_values_compare_after_normalisation(predicted: object, truth: object, same: bool) -> None:
    assert (_normal(predicted, truth) == _normal(truth, truth)) is same


def test_percentile_and_f1() -> None:
    values = [float(v) for v in range(1, 101)]
    assert (_percentile(values, 50), _percentile(values, 95)) == (50.0, 95.0)
    assert _percentile([3.0], 95) == 3.0
    assert _f1(None, None) is None
    assert _f1(None, 0.0) == 0.0  # nothing reported
    assert _f1(0.5, 1.0) == pytest.approx(2 / 3)


def test_targets() -> None:
    assert meets("finding_recall", 0.96) is True
    assert meets("finding_recall", 0.90) is False
    assert meets("false_alarms_per_clean", 0.2) is True
    assert meets("finding_precision", None) is None


def test_report_and_gate(dataset: Path, tmp_path: Path) -> None:
    result = run(EmptyPipeline(), dataset, "dev")
    folder = write_report(result, tmp_path)
    report = json.loads((folder / "report.json").read_text("utf-8"))
    assert report["cases"] == len(result.results)
    assert "| finding_recall |" in (folder / "summary.md").read_text("utf-8")

    baseline = baseline_of(result)
    assert regressions(result, baseline) == []
    better = json.loads(json.dumps(baseline))
    better["metrics"]["finding_recall"] = 0.5
    assert regressions(result, better) == ["finding_recall: was 0.500, now 0.000"]
    with pytest.raises(ValueError, match="baseline is for"):
        regressions(replace(result, split="test"), baseline)


def test_cli_gate_fails_on_regression(dataset: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    args = ["--pipeline", "empty", "--split", "dev", "--dataset", str(dataset)]
    args += ["--out", str(tmp_path / "reports")]
    assert main([*args, "--write-baseline", str(baseline)]) == 0
    assert main([*args, "--gate", str(baseline)]) == 0
    stored = json.loads(baseline.read_text("utf-8"))
    stored["metrics"]["finding_recall"] = 0.9
    baseline.write_text(json.dumps(stored), encoding="utf-8")
    assert main([*args, "--gate", str(baseline)]) == 1


def test_cli_rejects_a_missing_dataset(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--pipeline", "empty", "--split", "dev", "--dataset", str(tmp_path)])


def test_misclassified_files_are_listed(dataset: Path, tmp_path: Path) -> None:
    case = load_cases(dataset, "dev")[0]
    first, *rest = case.files
    files = {path: case.files[path] for path in rest} | {first: ("other",)}
    result = score_case(case, Prediction(files=files), 0.0)
    assert result.misclassified == ((first, case.files[first], ("other",)),)
    assert result.files_correct == len(case.files) - 1


def test_page_cache_returns_the_same_pages(dataset: Path, tmp_path: Path) -> None:
    case = load_cases(dataset, "dev")[0]
    path = next(p for p, _ in case.files.items() if p.endswith(".pdf"))
    data = (case.folder / path).read_bytes()
    first = page_cache.cached_pages(data, "application/pdf", tmp_path)
    (stored,) = tmp_path.iterdir()
    assert stored.name.endswith(f"-{page_cache.reader_fingerprint()}.json")
    again = page_cache.cached_pages(data, "application/pdf", tmp_path)
    assert again == first
    assert all(page.image is None for page in again)


def test_page_cache_reads_afresh_when_the_reader_changes(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = load_cases(dataset, "dev")[0]
    path = next(p for p, _ in case.files.items() if p.endswith(".pdf"))
    data = (case.folder / path).read_bytes()
    page_cache.cached_pages(data, "application/pdf", tmp_path)
    monkeypatch.setattr(page_cache, "reader_fingerprint", lambda: "changed-reader")
    page_cache.cached_pages(data, "application/pdf", tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 2


class CountingExtractor:
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, documents: list[DocumentText], guide: str) -> list[RawField]:
        self.calls += 1
        return [RawField(1, "arn", "AD1", "AD1", 1)]


def test_answer_cache_asks_once_per_question(tmp_path: Path) -> None:
    inner = CountingExtractor()
    cached = CachedExtractor(inner, tmp_path)
    page = Page(1, "ARN AD1", (), "pdf_text", None)
    documents = [DocumentText(1, "lut", "lut.pdf", (page,))]
    first = cached.extract(documents, "lut:\n  arn")
    assert (
        cached.extract(documents, "lut:\n  arn") == first == [RawField(1, "arn", "AD1", "AD1", 1)]
    )
    assert inner.calls == 1
    cached.extract(documents, "lut:\n  arn (another guide)")
    assert inner.calls == 2


def test_a_spent_quota_stops_the_run_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr("evals.pipeline.time.sleep", waits.append)
    answers = iter([RateLimited(30)])

    def ask() -> str:
        error = next(answers, None)
        if error is not None:
            raise error
        return "answer"

    assert pipeline._patiently(ask) == "answer"
    assert waits == [30]

    def spent() -> str:
        raise RateLimited(47_000)

    with pytest.raises(RuntimeError, match=r"quota spent; it resets in 13\.1 h"):
        pipeline._patiently(spent)


class AgreeingJudge:
    model = "agreeing"

    def judge(self, questions: list[Question]) -> list[Verdict]:
        return [Verdict(q.id, True, 1.0, "") for q in questions]


class NoCitations:
    def cite(self, rule_id: str) -> None:
        return None


def test_checks_on_labels_find_the_planted_errors(
    dataset: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # ShipGen's reference data instead of the database's; a judge that sees no conflict.
    monkeypatch.setattr("evals.pipeline.make_engine", lambda: None)
    monkeypatch.setattr("evals.pipeline.DbReference", lambda session: SnapshotReference())
    monkeypatch.setattr("evals.pipeline.judge_from_env", AgreeingJudge)
    monkeypatch.setattr("evals.pipeline.embedder_from_env", lambda: None)
    monkeypatch.setattr("evals.pipeline.DbKnowledge", lambda session, embedder: NoCitations())
    monkeypatch.setattr("evals.pipeline.ANSWER_CACHE", tmp_path)
    result = run(PIPELINES["checks-on-labels"](), dataset, "dev")
    metrics = result.metrics
    assert metrics["det_recall"] == metrics["det_precision"] == 1.0
    assert metrics["finding_precision"] == 1.0
    assert metrics["false_alarms_per_clean"] in (0.0, None)
    # Everything code decides is found; only what the judge would have flagged is missed.
    missed = {rule for r in result.results for rule in r.expected - r.reported}
    assert missed <= {"HS-03", "DESC-01"}
    assert any(tmp_path.glob("*.json"))  # the judge's answers were cached


def test_deterministic_measures_ignore_the_judgement_rules(dataset: Path) -> None:
    case = load_cases(dataset, "dev")[0]
    judged = Prediction(findings=frozenset({"HS-03", "DESC-01"}))
    metrics = summarise([score_case(case, judged, 0.1)])
    assert metrics["det_precision"] is None  # no deterministic rule reported
