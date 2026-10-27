"""Score predictions against the truth: the measures of PLAN.md Section 16.

A measure is None when it is undefined for the run (precision with no findings reported, for
example), never 0, so a report never shows a score nobody earned.
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from evals.cases import EvalCase, Medium, severities
from evals.pipeline import Prediction

# Measure -> (direction, MVP target on synthetic data), from PLAN.md Section 16.
TARGETS: dict[str, tuple[str, float]] = {
    "classification_accuracy": (">=", 0.98),
    "field_accuracy_digital": (">=", 0.95),
    "field_accuracy_image": (">=", 0.90),
    "line_item_f1": (">=", 0.92),
    "finding_recall": (">=", 0.95),
    "blocker_recall": (">=", 0.98),
    "finding_precision": (">=", 0.90),
    "false_alarms_per_clean": ("<=", 0.3),
    "latency_p50_s": ("<=", 90),
    "latency_p95_s": ("<=", 180),
    "cost_per_shipment_usd": ("<=", 0.50),
}
_INDEX = re.compile(r"\[\d+\]")
_LINE = re.compile(r"^(?P<line>[a-z_]+\.lines\[\d+\])\.(?P<field>.+)$")


@dataclass(frozen=True)
class CaseResult:
    shipment_id: str
    expected: frozenset[str]
    reported: frozenset[str]
    files_correct: int
    files_total: int
    fields: tuple[tuple[str, Medium, bool], ...]  # (field name, medium, extracted correctly)
    lines_matched: int
    lines_reported: int
    lines_expected: int
    latency_s: float
    cost_usd: Decimal

    @property
    def clean(self) -> bool:
        return not self.expected


def score_case(case: EvalCase, prediction: Prediction, latency_s: float) -> CaseResult:
    fields = tuple(
        (
            _INDEX.sub("[]", path),
            case.media[path.split(".")[0]],
            path in prediction.fields and _same(prediction.fields[path], truth),
        )
        for path, truth in case.fields.items()
    )
    expected_lines, reported_lines = (
        _lines(case.fields, case.fields),
        _lines(prediction.fields, case.fields),
    )
    return CaseResult(
        shipment_id=case.shipment_id,
        expected=case.findings,
        reported=prediction.findings,
        files_correct=sum(
            1 for path, documents in case.files.items() if prediction.files.get(path) == documents
        ),
        files_total=len(case.files),
        fields=fields,
        lines_matched=sum((expected_lines & reported_lines).values()),
        lines_reported=sum(reported_lines.values()),
        lines_expected=sum(expected_lines.values()),
        latency_s=latency_s,
        cost_usd=prediction.cost_usd,
    )


def summarise(results: list[CaseResult]) -> dict[str, float | None]:
    if not results:
        raise ValueError("no cases to score")
    blockers = {rule for rule, severity in severities().items() if severity == "blocker"}
    found = sum(len(r.expected & r.reported) for r in results)
    expected = sum(len(r.expected) for r in results)
    reported = sum(len(r.reported) for r in results)
    blockers_found = sum(len(r.expected & r.reported & blockers) for r in results)
    blockers_expected = sum(len(r.expected & blockers) for r in results)
    clean = [r for r in results if r.clean]
    matched = sum(r.lines_matched for r in results)
    latencies = sorted(r.latency_s for r in results)
    return {
        "classification_accuracy": _ratio(
            sum(r.files_correct for r in results), sum(r.files_total for r in results)
        ),
        "field_accuracy_digital": _field_accuracy(results, "digital"),
        "field_accuracy_image": _field_accuracy(results, "image"),
        "line_item_f1": _f1(
            _ratio(matched, sum(r.lines_reported for r in results)),
            _ratio(matched, sum(r.lines_expected for r in results)),
        ),
        "finding_recall": _ratio(found, expected),
        "blocker_recall": _ratio(blockers_found, blockers_expected),
        "finding_precision": _ratio(found, reported),
        "false_alarms_per_clean": (
            sum(len(r.reported) for r in clean) / len(clean) if clean else None
        ),
        "latency_p50_s": _percentile(latencies, 50),
        "latency_p95_s": _percentile(latencies, 95),
        "cost_per_shipment_usd": float(sum(r.cost_usd for r in results) / len(results)),
    }


def recall_by_rule(results: list[CaseResult]) -> dict[str, float]:
    expected: Counter[str] = Counter(rule for r in results for rule in r.expected)
    found: Counter[str] = Counter(rule for r in results for rule in r.expected & r.reported)
    return {rule: found[rule] / count for rule, count in sorted(expected.items())}


def meets(measure: str, value: float | None) -> bool | None:
    """Whether `value` meets the PLAN.md target; None when the measure is undefined."""
    if value is None:
        return None
    direction, target = TARGETS[measure]
    return value >= target if direction == ">=" else value <= target


def _same(predicted: object, truth: object) -> bool:
    return _normal(predicted, truth) == _normal(truth, truth)


def _normal(value: object, like: object) -> object:
    """`value` in a form that compares equal to the truth when it means the same: numbers as
    decimals (1,234.50 == 1234.5), dates as dates, text without case or extra spaces. The
    truth's type decides, so an HS code like 09103030 stays text and keeps its leading zero."""
    try:
        if isinstance(like, bool):
            return value if isinstance(value, bool) else str(value).casefold() == "true"
        if isinstance(like, int | Decimal):
            return Decimal(str(value).replace(",", "")).normalize()
        if isinstance(like, date):
            return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (ValueError, InvalidOperation):
        return ("unreadable", str(value))
    return " ".join(str(value).split()).casefold()


def _lines(fields: dict[str, object], truth: dict[str, object]) -> Counter[tuple[object, ...]]:
    """Each line item as one hashable value: its document and all its normalised fields. A
    reported line counts only if every field matches a true line."""
    lines: dict[str, dict[str, object]] = defaultdict(dict)
    for path, value in fields.items():
        match = _LINE.match(path)
        if match:
            like = truth.get(path, "")
            lines[match["line"]][match["field"]] = _normal(value, like)
    return Counter(
        (path.split(".")[0], tuple(sorted(values.items(), key=lambda item: item[0])))
        for path, values in lines.items()
    )


def _field_accuracy(results: list[CaseResult], medium: Medium) -> float | None:
    """Macro average: each field name (e.g. packing_list.lines[].quantity) weighs the same,
    however often it occurs."""
    hits: dict[str, list[bool]] = defaultdict(list)
    for result in results:
        for name, field_medium, hit in result.fields:
            if field_medium == medium:
                hits[name].append(hit)
    if not hits:
        return None
    return sum(sum(values) / len(values) for values in hits.values()) / len(hits)


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    """None when there was nothing to find; 0 when nothing was reported."""
    if recall is None:
        return None
    if not precision or not recall:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _percentile(values: list[float], percent: int) -> float:
    """Nearest-rank percentile of sorted `values`."""
    rank = max(1, math.ceil(percent / 100 * len(values)))
    return values[rank - 1]
