import json
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from shipgen.dataset import (
    CLEAN_SHARE,
    MAX_ERRORS,
    MAX_LOOKALIKES,
    Case,
    build_case,
    main,
    split_of,
    write_dataset,
)
from shipgen.lookalikes import LOOKALIKES
from shipgen.mutations import MUTATIONS
from shipgen.oracle import CHECKS, violations
from shipready.rules.catalogue import load_catalogue


@cache
def cases() -> tuple[Case, ...]:
    return tuple(build_case(42, index) for index in range(200))


def test_labels_match_what_is_broken() -> None:
    for case in cases():
        assert violations(case.documents) == case.rule_ids & CHECKS.keys()


def test_mix_of_clean_cases_errors_and_lookalikes() -> None:
    clean = sum(1 for case in cases() if not case.rule_ids)
    assert abs(clean / len(cases()) - CLEAN_SHARE) < 0.1
    for case in cases():
        errors = [label for label in case.labels if label.rule_ids]
        lookalikes = [label for label in case.labels if not label.rule_ids]
        assert len(errors) <= MAX_ERRORS
        assert len(lookalikes) <= MAX_LOOKALIKES
        rules = [rule for label in errors for rule in label.rule_ids]
        assert len(rules) == len(set(rules))


def test_every_mutation_and_lookalike_is_used() -> None:
    used = Counter(label.mutation for case in cases() for label in case.labels)
    assert {m.name for m in MUTATIONS + LOOKALIKES} <= used.keys()


def test_every_label_names_enabled_rules() -> None:
    enabled = {rule.id for rule in load_catalogue() if rule.enabled}
    assert all(case.rule_ids <= enabled for case in cases())


def test_case_is_deterministic() -> None:
    assert build_case(42, 3) == cases()[3]
    assert build_case(43, 3) != cases()[3]


def test_split_is_stable_and_proportioned() -> None:
    splits = Counter(split_of(f"SG42-{index:04d}") for index in range(3000))
    assert abs(splits["dev"] / 3000 - 0.6) < 0.03
    assert abs(splits["validation"] / 3000 - 0.2) < 0.03
    assert abs(splits["test"] / 3000 - 0.2) < 0.03
    assert all(case.split == split_of(case.shipment_id) for case in cases())


def test_write_dataset(tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    written = write_dataset(12, 42, out)
    assert written == list(cases()[:12])
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["seed"], manifest["count"]) == (42, 12)
    for entry, case in zip(manifest["cases"], written, strict=True):
        path = out / case.split / f"{case.shipment_id}.json"
        assert Case.model_validate_json(path.read_text(encoding="utf-8")) == case
        assert entry["rule_ids"] == sorted(case.rule_ids)
        assert len(entry["mutations"]) + len(entry["lookalikes"]) == len(case.labels)


def test_write_dataset_refuses_a_non_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="is not empty"):
        write_dataset(1, 42, tmp_path)


def test_main_prints_a_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--count", "5", "--seed", "42", "--out", str(tmp_path / "out")])
    output = capsys.readouterr().out
    assert "5 cases: dev" in output
    assert "look-alikes" in output


def test_main_rejects_a_zero_count(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--count", "0", "--seed", "42", "--out", str(tmp_path)])
