from decimal import Decimal

import pytest

from shipready.checks.engine import Outcome, Result
from shipready.checks.readiness import WEIGHTS, assess
from shipready.rules.catalogue import load_catalogue

SEVERITY = {rule.id: rule.severity for rule in load_catalogue()}
ENABLED = [rule.id for rule in load_catalogue() if rule.enabled]


def all_results(**outcomes: Outcome) -> list[Result]:
    """Every enabled rule passing, except those given (rule ID with "-" as "_")."""
    given = {key.replace("_", "-"): value for key, value in outcomes.items()}
    return [Result(rule, given.get(rule, "pass"), "", ()) for rule in ENABLED]


def test_a_shipment_passing_every_check_is_ready() -> None:
    assessment = assess(all_results())
    assert (assessment.readiness, assessment.score, assessment.reasons) == (
        "ready",
        Decimal("100.00"),
        (),
    )


def test_a_failed_blocker_needs_fixing_and_lowers_the_score() -> None:
    assert SEVERITY["QTY-01"] == "blocker"
    assessment = assess(all_results(QTY_01="fail"))
    assert (assessment.readiness, assessment.reasons) == ("needs_fix", ("QTY-01",))
    total = sum(WEIGHTS[SEVERITY[rule]] for rule in ENABLED)
    assert assessment.score == (Decimal(100) * (total - 5) / total).quantize(Decimal("0.01"))


def test_a_failed_minor_check_does_not_hold_the_shipment() -> None:
    assert SEVERITY["UQC-01"] == "minor"
    assessment = assess(all_results(UQC_01="fail"))
    assert assessment.readiness == "ready"
    assert assessment.score < Decimal(100)


def test_an_unverified_major_check_needs_review() -> None:
    assert SEVERITY["FX-01"] == "major"
    assessment = assess(all_results(FX_01="not_verified"))
    assert (assessment.readiness, assessment.reasons) == ("needs_review", ("FX-01",))


def test_a_failure_outweighs_what_could_not_be_verified() -> None:
    assessment = assess(all_results(FX_01="not_verified", ID_02="fail"))
    assert (assessment.readiness, assessment.reasons) == ("needs_fix", ("ID-02",))


def test_nothing_passed_scores_zero() -> None:
    results = [Result(rule, "not_verified", "", ()) for rule in ENABLED]
    assert assess(results).score == Decimal("0.00")


def test_no_results_cannot_be_assessed() -> None:
    with pytest.raises(ValueError, match="without check results"):
        assess([])
