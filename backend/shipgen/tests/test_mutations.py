import random
from decimal import Decimal
from typing import Any

import pytest

from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.lookalikes import LOOKALIKES
from shipgen.mutations import (
    MUTATIONS,
    Label,
    Mutation,
    apply,
    change_digit,
    format_path,
    nudge,
)
from shipgen.oracle import CHECKS, violations
from shipready.documents.models import ShipmentDocuments
from shipready.rules.catalogue import load_catalogue

# Enough shipments to include air, "to order" bills of lading and several containers.
SHIPMENTS = [build_documents(generate_shipment(11, index)) for index in range(40)]


def leaves(value: Any, path: str = "") -> dict[str, Any]:
    """Every scalar in a dumped model, by its path in Change.field notation."""
    if isinstance(value, dict):
        return {
            k: v
            for key, item in value.items()
            for k, v in leaves(item, f"{path}.{key}".lstrip(".")).items()
        }
    if isinstance(value, (list, tuple)):
        return {
            k: v for i, item in enumerate(value) for k, v in leaves(item, f"{path}[{i}]").items()
        }
    return {path: value}


def changed_leaves(before: ShipmentDocuments, after: ShipmentDocuments) -> set[str]:
    old, new = leaves(before.model_dump()), leaves(after.model_dump())
    return {path for path in old.keys() | new.keys() if old.get(path) != new.get(path)}


def label_paths(label: Label) -> set[str]:
    return {f"{change.document}.{change.field}" for change in label.changes}


def under(leaf: str, path: str) -> bool:
    return leaf == path or leaf.startswith((f"{path}.", f"{path}["))


def applications(mutation: Mutation) -> list[tuple[ShipmentDocuments, ShipmentDocuments, Label]]:
    results = []
    for index, documents in enumerate(SHIPMENTS):
        result = apply(mutation, documents, random.Random(index))
        if result is not None:
            results.append((documents, *result))
    assert results, f"{mutation.name} applied to none of the test shipments"
    return results


def test_golden_documents_break_no_rule() -> None:
    for documents in SHIPMENTS:
        assert violations(documents) == set()


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m.name)
def test_mutation_breaks_exactly_its_rules(mutation: Mutation) -> None:
    for _, mutated, label in applications(mutation):
        assert label.rule_ids == mutation.rule_ids
        assert violations(mutated) == set(mutation.rule_ids) & CHECKS.keys()


@pytest.mark.parametrize("lookalike", LOOKALIKES, ids=lambda m: m.name)
def test_lookalike_breaks_no_rule(lookalike: Mutation) -> None:
    for _, mutated, label in applications(lookalike):
        assert label.rule_ids == ()
        assert violations(mutated) == set()


@pytest.mark.parametrize("mutation", MUTATIONS + LOOKALIKES, ids=lambda m: m.name)
def test_mutation_changes_only_the_labelled_fields(mutation: Mutation) -> None:
    for documents, mutated, label in applications(mutation):
        paths = label_paths(label)
        changed = changed_leaves(documents, mutated)
        assert all(any(under(leaf, path) for path in paths) for leaf in changed)
        assert all(any(under(leaf, path) for leaf in changed) for path in paths)
        assert all(change.original != change.mutated for change in label.changes)
        # The mutated bundle is still well-typed: it survives a JSON round trip.
        assert ShipmentDocuments.model_validate_json(mutated.model_dump_json()) == mutated


@pytest.mark.parametrize("mutation", MUTATIONS + LOOKALIKES, ids=lambda m: m.name)
def test_mutation_is_deterministic(mutation: Mutation) -> None:
    for documents in SHIPMENTS[:5]:
        assert apply(mutation, documents, random.Random(7)) == apply(
            mutation, documents, random.Random(7)
        )


def test_mutations_name_enabled_rules_the_oracle_covers() -> None:
    enabled = {rule.id for rule in load_catalogue() if rule.enabled}
    labelled = {rule for mutation in MUTATIONS for rule in mutation.rule_ids}
    assert labelled <= enabled
    # HS-03 (plausibility of a description for its HS code) needs judgement.
    assert labelled - CHECKS.keys() == {"HS-03"}
    names = [mutation.name for mutation in MUTATIONS + LOOKALIKES]
    assert len(names) == len(set(names))


def test_unchanged_value_is_rejected() -> None:
    path = ("shipping_bill", "invoice_value")
    same = Mutation("noop", ("VAL-02",), lambda d, rng: [(path, d.shipping_bill.invoice_value)])
    with pytest.raises(ValueError, match=r"left shipping_bill[.]invoice_value unchanged"):
        apply(same, SHIPMENTS[0], random.Random(0))


def test_label_records_every_change_as_json() -> None:
    gstin_typo = next(m for m in MUTATIONS if m.name == "gstin_checksum_typo")
    result = apply(gstin_typo, SHIPMENTS[0], random.Random(0))
    assert result is not None
    _, label = result
    assert [change.document for change in label.changes] == [
        "commercial_invoice",
        "shipping_bill",
        "lut",
    ]
    assert {change.field for change in label.changes} == {"gstin"}
    assert all(isinstance(change.original, str) for change in label.changes)


@pytest.mark.parametrize(
    "value", [Decimal(1), Decimal(3), Decimal("0.01"), Decimal("12.500"), Decimal("98765.43")]
)
def test_nudge_always_changes_and_stays_positive(value: Decimal) -> None:
    for seed in range(200):
        moved = nudge(value, random.Random(seed), 0.02, 0.10)
        assert moved != value
        assert moved > 0
        assert moved.as_tuple().exponent == value.as_tuple().exponent


@pytest.mark.parametrize("value", [Decimal(0), Decimal(-5), Decimal("NaN")])
def test_nudge_rejects_non_positive_values(value: Decimal) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        nudge(value, random.Random(0), 0.02, 0.10)


def test_change_digit() -> None:
    for seed in range(50):
        changed = change_digit("EXP/26-27/4995", random.Random(seed))
        assert changed != "EXP/26-27/4995"
        assert sum(a != b for a, b in zip(changed, "EXP/26-27/4995", strict=True)) == 1
    with pytest.raises(ValueError, match="no digit"):
        change_digit("ABC", random.Random(0))


def test_format_path() -> None:
    assert format_path(("lines", 2, "quantity")) == "lines[2].quantity"
    assert format_path(("invoice_value",)) == "invoice_value"
