"""Score a pipeline on a split of the labelled dataset.

uv run python -m evals --pipeline empty --split validation --dataset ../data/dataset
uv run python -m evals --pipeline empty --split validation --gate evals/baseline.json
uv run python -m evals --pipeline empty --split validation --write-baseline evals/baseline.json

With --gate, exits with status 1 if any measure is worse than the baseline.
"""

import argparse
import json
import sys
from pathlib import Path

from evals.harness import baseline_of, regressions, run, summary, write_report
from evals.pipeline import PIPELINES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a pipeline on the labelled dataset.")
    parser.add_argument("--pipeline", choices=sorted(PIPELINES), required=True)
    parser.add_argument("--split", choices=["dev", "validation", "test"], required=True)
    parser.add_argument("--dataset", type=Path, default=Path("../data/dataset"))
    parser.add_argument("--out", type=Path, default=Path("../data/evals"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gate", type=Path, help="baseline file to compare with")
    group.add_argument("--write-baseline", type=Path, help="save this run as the baseline")
    args = parser.parse_args(argv)

    try:
        result = run(PIPELINES[args.pipeline](), args.dataset, args.split)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    folder = write_report(result, args.out)
    print(summary(result))
    print(f"report: {folder}")

    if args.write_baseline:
        text = json.dumps(baseline_of(result), indent=2) + "\n"
        args.write_baseline.write_text(text, encoding="utf-8")
        print(f"baseline written to {args.write_baseline}")
    if args.gate:
        baseline = json.loads(args.gate.read_text(encoding="utf-8"))
        problems = regressions(result, baseline)
        if problems:
            print("regressions against the baseline:", *problems, sep="\n  ")
            return 1
        print("no regressions against the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
