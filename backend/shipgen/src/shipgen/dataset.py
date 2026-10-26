"""Build the labelled dataset: golden shipments with injected errors and look-alike non-errors,
split into dev / validation / test.

uv run python -m shipgen.dataset --count 200 --seed 42 --out ../data/dataset

Each case keeps the golden shipment (the truth), the documents as they would be printed (with the
errors and look-alikes in them, so the ground truth for extraction) and the labels (the ground
truth for findings). The same seed always gives the same dataset.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Literal

from shipgen.consistency import check_shipment
from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.lookalikes import LOOKALIKES
from shipgen.models import Shipment
from shipgen.mutations import MUTATIONS, Label, Mutation, apply
from shipgen.oracle import CHECKS, violations
from shipready.documents.models import Model, ShipmentDocuments

Split = Literal["dev", "validation", "test"]
# Cumulative percentage bounds: 60% dev, 20% validation, 20% test.
SPLITS: tuple[tuple[Split, int], ...] = (("dev", 60), ("validation", 80), ("test", 100))
CLEAN_SHARE = 0.3
MAX_ERRORS = 4
MAX_LOOKALIKES = 2


class Case(Model):
    shipment_id: str
    split: Split
    labels: tuple[Label, ...]
    shipment: Shipment
    documents: ShipmentDocuments

    @property
    def rule_ids(self) -> set[str]:
        return {rule for label in self.labels for rule in label.rule_ids}


def split_of(shipment_id: str) -> Split:
    """The split depends only on the shipment ID, so growing the dataset never moves a case
    between splits (and the test split never leaks into tuning)."""
    bucket = int(hashlib.sha256(shipment_id.encode()).hexdigest(), 16) % 100
    return next(name for name, bound in SPLITS if bucket < bound)


def build_case(seed: int, index: int) -> Case:
    shipment = generate_shipment(seed, index)
    problems = check_shipment(shipment)
    if problems:
        raise RuntimeError(f"{shipment.shipment_id} is inconsistent: {'; '.join(problems)}")
    rng = random.Random(f"{seed}:{index}:labels")
    errors = 0 if rng.random() < CLEAN_SHARE else rng.randint(1, MAX_ERRORS)
    lookalikes = rng.randint(0, MAX_LOOKALIKES)

    documents = build_documents(shipment)
    labels: list[Label] = []
    documents = _inject(documents, MUTATIONS, errors, rng, labels)
    documents = _inject(documents, LOOKALIKES, lookalikes, rng, labels)
    case = Case(
        shipment_id=shipment.shipment_id,
        split=split_of(shipment.shipment_id),
        labels=tuple(labels),
        shipment=shipment,
        documents=documents,
    )
    # A label that does not match what is broken would teach the evaluation the wrong answer.
    broken, labelled = violations(documents), case.rule_ids & CHECKS.keys()
    if broken != labelled:
        raise RuntimeError(
            f"{case.shipment_id}: labels name {sorted(labelled)} but {sorted(broken)} are broken"
        )
    return case


def _inject(
    documents: ShipmentDocuments,
    candidates: tuple[Mutation, ...],
    count: int,
    rng: random.Random,
    labels: list[Label],
) -> ShipmentDocuments:
    """Apply up to `count` of `candidates`, appending their labels. A candidate is skipped when
    it does not apply, repeats a rule already labelled, or touches a field (or the same line)
    another label changed: two edits on one line could hide each other, e.g. a unit change
    makes a quantity change incomparable."""
    added = 0
    for mutation in rng.sample(candidates, len(candidates)):
        if added == count:
            break
        rules = {rule for label in labels for rule in label.rule_ids}
        if rules & set(mutation.rule_ids):
            continue
        result = apply(mutation, documents, rng)
        if result is None or any(_overlaps(label, result[1]) for label in labels):
            continue
        documents, label = result
        labels.append(label)
        added += 1
    return documents


def _overlaps(a: Label, b: Label) -> bool:
    return bool(_touched(a) & _touched(b))


def _touched(label: Label) -> set[str]:
    # Changes collide on the same document field. Lines collide only on the same line, so
    # errors can sit on different lines; containers collide on any container, since one
    # mutation replaces the whole tuple.
    keys = set()
    for change in label.changes:
        head = change.field.split(".")[0]
        keys.add(f"{change.document}.{head}")
        if "[" in head and not head.startswith("lines["):
            keys.add(f"{change.document}.{head.split('[')[0]}")
    return keys


def write_dataset(count: int, seed: int, out: Path) -> list[Case]:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; remove it or choose another --out")
    cases = [build_case(seed, index) for index in range(count)]
    for case in cases:
        path = out / case.split / f"{case.shipment_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "seed": seed,
        "count": count,
        "cases": [
            {
                "shipment_id": case.shipment_id,
                "split": case.split,
                "rule_ids": sorted(case.rule_ids),
                "mutations": [label.mutation for label in case.labels if label.rule_ids],
                "lookalikes": [label.mutation for label in case.labels if not label.rule_ids],
            }
            for case in cases
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return cases


def summary(cases: list[Case]) -> list[str]:
    splits = Counter(case.split for case in cases)
    clean = sum(1 for case in cases if not case.rule_ids)
    rules = Counter(rule for case in cases for rule in case.rule_ids)
    lookalikes = sum(1 for case in cases for label in case.labels if not label.rule_ids)
    return [
        f"{len(cases)} cases: " + ", ".join(f"{name} {splits[name]}" for name, _ in SPLITS),
        f"clean {clean}, with errors {len(cases) - clean}, look-alikes {lookalikes}",
        "rules: " + ", ".join(f"{rule} {n}" for rule, n in sorted(rules.items())),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the labelled ShipGen dataset.")
    parser.add_argument("--count", type=int, required=True, help="number of shipments")
    parser.add_argument("--seed", type=int, required=True, help="seed; same seed, same dataset")
    parser.add_argument("--out", type=Path, required=True, help="empty output directory")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")

    try:
        cases = write_dataset(args.count, args.seed, args.out)
    except FileExistsError as error:
        parser.error(str(error))
    print(f"wrote {args.out}")
    for line in summary(cases):
        print(line)


if __name__ == "__main__":
    main()
