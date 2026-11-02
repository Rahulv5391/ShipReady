"""How ready a shipment is to file, from its check results: a suggestion for the person who
marks it ready (PLAN.md Section 10.2), never a decision on its own.

- needs_fix: a blocker or major check failed;
- needs_review: nothing failed, but a blocker or major check could not be verified;
- ready: every blocker and major check passed.

The score is the share of the rulebook the shipment passes, weighted by severity; a check not
verified counts as not passed, since what is unknown is not ready.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from typing import Literal

from shipready.checks.engine import Result
from shipready.rules.catalogue import load_catalogue

Readiness = Literal["ready", "needs_fix", "needs_review"]
READINESS: tuple[Readiness, ...] = ("ready", "needs_fix", "needs_review")
# A blocker stops filing, a major check is likely to cause a query; a minor one is cosmetic.
WEIGHTS = {"blocker": 5, "major": 3, "minor": 1, "info": 0}
GATING = ("blocker", "major")


@dataclass(frozen=True)
class Assessment:
    readiness: Readiness
    score: Decimal  # 0 to 100
    reasons: tuple[str, ...]  # the rule IDs that decided the readiness


@cache
def _severities() -> dict[str, str]:
    return {rule.id: rule.severity for rule in load_catalogue()}


def assess(results: Iterable[Result]) -> Assessment:
    results = list(results)
    if not results:
        raise ValueError("a shipment without check results cannot be assessed")
    severity = _severities()
    gating = [r for r in results if severity[r.rule_id] in GATING]
    failed = tuple(r.rule_id for r in gating if r.outcome == "fail")
    unverified = tuple(r.rule_id for r in gating if r.outcome == "not_verified")
    if failed:
        readiness: Readiness = "needs_fix"
        reasons = failed
    elif unverified:
        readiness, reasons = "needs_review", unverified
    else:
        readiness, reasons = "ready", ()
    total = sum(WEIGHTS[severity[r.rule_id]] for r in results)
    passed = sum(WEIGHTS[severity[r.rule_id]] for r in results if r.outcome == "pass")
    score = (Decimal(100) * passed / total if total else Decimal(100)).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    return Assessment(readiness, score, reasons)
