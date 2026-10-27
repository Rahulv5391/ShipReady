"""Run a pipeline over one split, write the report, and compare it with a baseline."""

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from evals.cases import load_cases
from evals.metrics import TARGETS, CaseResult, meets, recall_by_rule, score_case, summarise
from evals.pipeline import Pipeline
from shipgen.dataset import Split

# Scores may move by this much before the gate calls it a regression (rounding noise).
TOLERANCE = 0.005
# Timings vary from machine to machine, so the gate leaves them out.
UNGATED = {"latency_p50_s", "latency_p95_s"}


@dataclass(frozen=True)
class Run:
    pipeline: str
    split: Split
    dataset: Path
    git_sha: str | None
    started: datetime
    results: list[CaseResult]
    metrics: dict[str, float | None]


def run(pipeline: Pipeline, dataset: Path, split: Split) -> Run:
    cases = load_cases(dataset, split)
    if not cases:
        raise ValueError(f"no {split} cases in {dataset}")
    started = datetime.now(UTC)
    results = []
    for case in cases:
        start = time.perf_counter()
        prediction = pipeline.run(case.folder, tuple(case.files))
        results.append(score_case(case, prediction, time.perf_counter() - start))
    return Run(
        pipeline=pipeline.name,
        split=split,
        dataset=dataset,
        git_sha=_git_sha(),
        started=started,
        results=results,
        metrics=summarise(results),
    )


def write_report(result: Run, out: Path) -> Path:
    """Write report.json and summary.md into a new folder under `out`; return the folder."""
    stamp = result.started.strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{result.pipeline}-{result.split}"
    folder, number = out / name, 1
    while folder.exists():  # two runs in the same second
        number += 1
        folder = out / f"{name}-{number}"
    folder.mkdir(parents=True)
    report = {
        "pipeline": result.pipeline,
        "split": result.split,
        "dataset": str(result.dataset),
        "git_sha": result.git_sha,
        "started": result.started.isoformat(),
        "cases": len(result.results),
        "metrics": result.metrics,
        "targets_met": {name: meets(name, value) for name, value in result.metrics.items()},
        "recall_by_rule": recall_by_rule(result.results),
        "case_results": [
            {
                "shipment_id": r.shipment_id,
                "expected": sorted(r.expected),
                "reported": sorted(r.reported),
                "missed": sorted(r.expected - r.reported),
                "false_alarms": sorted(r.reported - r.expected),
                "latency_s": round(r.latency_s, 3),
                "cost_usd": str(r.cost_usd),
            }
            for r in result.results
        ],
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (folder / "summary.md").write_text(summary(result), encoding="utf-8")
    return folder


def summary(result: Run) -> str:
    lines = [
        f"# Evaluation: {result.pipeline} on {result.split}",
        "",
        f"{len(result.results)} cases from {result.dataset}, commit {result.git_sha or 'unknown'}, "
        f"{result.started:%Y-%m-%d %H:%M} UTC.",
        "",
        "| Measure | Value | Target | Met |",
        "|---|---|---|---|",
    ]
    for name, value in result.metrics.items():
        direction, target = TARGETS[name]
        met = {True: "yes", False: "no", None: "n/a"}[meets(name, value)]
        shown = "n/a" if value is None else f"{value:.3f}"
        lines.append(f"| {name} | {shown} | {direction} {target} | {met} |")
    lines += ["", "| Rule | Recall |", "|---|---|"]
    lines += [
        f"| {rule} | {recall:.2f} |" for rule, recall in recall_by_rule(result.results).items()
    ]
    return "\n".join(lines) + "\n"


def regressions(result: Run, baseline: dict[str, object]) -> list[str]:
    """Measures that got worse than the baseline by more than TOLERANCE. A baseline for a
    different pipeline or split is an error, not a pass."""
    if (baseline.get("pipeline"), baseline.get("split")) != (result.pipeline, result.split):
        raise ValueError(
            f"baseline is for {baseline.get('pipeline')} on {baseline.get('split')}, "
            f"not {result.pipeline} on {result.split}"
        )
    expected = baseline.get("metrics")
    if not isinstance(expected, dict):
        raise ValueError("baseline has no metrics")
    problems = []
    for name, before in expected.items():
        if name in UNGATED or before is None:
            continue
        now = result.metrics.get(name)
        direction = TARGETS[name][0]
        if now is None:
            problems.append(f"{name}: was {before:.3f}, now undefined")
        elif (direction == ">=" and now < before - TOLERANCE) or (
            direction == "<=" and now > before + TOLERANCE
        ):
            problems.append(f"{name}: was {before:.3f}, now {now:.3f}")
    return problems


def baseline_of(result: Run) -> dict[str, object]:
    return {
        "pipeline": result.pipeline,
        "split": result.split,
        "git_sha": result.git_sha,
        "metrics": {k: v for k, v in result.metrics.items() if k not in UNGATED},
    }


def _git_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()
