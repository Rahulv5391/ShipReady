"""Run the deterministic checks over a shipment's fields.

Each enabled DET rule of the catalogue gives a `Result`: pass, fail, or not verified when a value
it needs is missing or our reference data cannot decide it. A result's evidence is the field
paths the check read, which lead to the fields' quotes and boxes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from shipready.checks import amounts, goods, parties, shipping
from shipready.checks.fields import Fields, NotVerified
from shipready.checks.reference import Reference
from shipready.rules.catalogue import RuleSpec, load_catalogue

Outcome = Literal["pass", "fail", "not_verified"]
Verification = Literal["kept", "misread"]
OUTCOMES: tuple[Outcome, ...] = ("pass", "fail", "not_verified")
Check = Callable[[Fields, Reference, dict[str, Any]], str | None]  # a problem, or None

CHECKS: dict[str, Check] = {**amounts.CHECKS, **shipping.CHECKS, **goods.CHECKS, **parties.CHECKS}


@dataclass(frozen=True)
class Citation:
    """A passage of a regulatory text a finding relies on (shipready.knowledge)."""

    source_id: str
    page: int | None
    text: str


@dataclass(frozen=True)
class Result:
    rule_id: str
    outcome: Outcome
    message: str  # what is wrong, or why it could not be decided; empty on a pass
    evidence: tuple[str, ...]  # field paths the check read, in order
    citations: tuple[Citation, ...] = ()
    # The critic's review of a failure (shipready.checks.critic): kept, or misread when the page
    # images show the documents are right; None when not reviewed.
    verification: Verification | None = None
    critic_reason: str = ""


def deterministic_rules() -> list[RuleSpec]:
    """The enabled rules decided by code alone; each must have a check here."""
    rules = [rule for rule in load_catalogue() if rule.enabled and rule.check_type == "DET"]
    unchecked = [rule.id for rule in rules if rule.id not in CHECKS]
    if unchecked:
        raise RuntimeError(f"no check for catalogue rules {unchecked}")
    return rules


def run_checks(values: Mapping[str, object], reference: Reference) -> list[Result]:
    return [_run(rule, values, reference) for rule in deterministic_rules()]


def _run(rule: RuleSpec, values: Mapping[str, object], reference: Reference) -> Result:
    fields = Fields(values)
    try:
        problem = CHECKS[rule.id](fields, reference, rule.params)
    except NotVerified as error:
        return Result(rule.id, "not_verified", str(error), _evidence(fields))
    if problem:
        return Result(rule.id, "fail", problem, _evidence(fields))
    return Result(rule.id, "pass", "", _evidence(fields))


def _evidence(fields: Fields) -> tuple[str, ...]:
    """The paths read that hold a value: a missing one has nothing to show."""
    return tuple(dict.fromkeys(path for path in fields.read if path in fields.values))
