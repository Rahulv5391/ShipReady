from collections import Counter

import pytest

from shipready.rules.catalogue import CatalogueError, load_catalogue, parse_catalogue

VALID_RULE = """
- id: QTY-01
  title: Quantities match
  description: Line quantities match.
  check_type: DET
  severity: blocker
  prevents: Shipping bill query
  source: Customs Act 1962, Section 50
"""


def test_catalogue_has_every_check_from_the_plan() -> None:
    rules = load_catalogue()
    assert len(rules) == 39
    types = Counter(rule.check_type for rule in rules)
    assert types["DET"] == 29
    assert types["DEC"] == 4
    assert types["LLM"] == 3
    assert types["DET+DEC"] + types["DET+LLM"] + types["LLM+DET"] == 3


def test_only_the_deferred_checks_are_disabled() -> None:
    disabled = {rule.id for rule in load_catalogue() if not rule.enabled}
    assert disabled == {"POL-02", "LC-01", "EML-01"}


def test_weight_tolerance_is_a_parameter() -> None:
    rules = {rule.id: rule for rule in load_catalogue()}
    assert rules["WT-01"].params == {"gross_weight_tolerance_pct": 0.5}
    assert rules["QTY-01"].params == {}


def test_optional_fields_default() -> None:
    (rule,) = parse_catalogue(VALID_RULE)
    assert rule.enabled is True
    assert rule.params == {}
    assert rule.source == "Customs Act 1962, Section 50"


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("", "must be a list"),
        ("id: QTY-01", "must be a list"),
        ("- just text", "rule 1: expected a mapping"),
        (VALID_RULE.replace("  source: Customs Act 1962, Section 50\n", ""), "'source' must be"),
        (VALID_RULE.replace("Shipping bill query", "''"), "'prevents' must be"),
        (VALID_RULE.replace("check_type: DET", "check_type: 1"), "'check_type' must be"),
        (VALID_RULE + "  owner: someone\n", "unknown keys \\['owner'\\]"),
        (VALID_RULE.replace("QTY-01", "qty1"), "id must look like"),
        (VALID_RULE.replace("check_type: DET", "check_type: RULE"), "check_type must be one of"),
        (VALID_RULE.replace("blocker", "critical"), "severity must be one of"),
        (VALID_RULE + "  params: [1, 2]\n", "'params' must be a mapping"),
        (VALID_RULE + "  enabled: maybe\n", "'enabled' must be true or false"),
        (VALID_RULE + VALID_RULE, "duplicate rule id QTY-01"),
    ],
)
def test_invalid_catalogue_is_rejected(yaml_text: str, message: str) -> None:
    with pytest.raises(CatalogueError, match=message):
        parse_catalogue(yaml_text)


def test_error_names_the_rule() -> None:
    second_rule_bad = VALID_RULE + VALID_RULE.replace("QTY-01", "QTY-02").replace("DET", "X")
    with pytest.raises(CatalogueError, match=r"rule 2 \(QTY-02\)"):
        parse_catalogue(second_rule_bad)
