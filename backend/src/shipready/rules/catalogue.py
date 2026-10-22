"""Parse and validate the check catalogue (catalogue.yaml)."""

import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml

CHECK_TYPES = ("DET", "DEC", "LLM", "DET+DEC", "DET+LLM", "LLM+DET")
SEVERITIES = ("blocker", "major", "minor", "info")

_ID_RE = re.compile(r"^[A-Z]{2,4}-[0-9]{2}$")
_REQUIRED_TEXT = ("id", "title", "description", "check_type", "severity", "prevents", "source")
_OPTIONAL = ("params", "enabled")


class CatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class RuleSpec:
    id: str
    title: str
    description: str
    check_type: str
    severity: str
    prevents: str
    source: str
    params: dict[str, Any]
    enabled: bool


def parse_catalogue(text: str) -> list[RuleSpec]:
    """Parse catalogue YAML, raising CatalogueError that names the offending entry."""
    entries = yaml.safe_load(text)
    if not isinstance(entries, list):
        raise CatalogueError("catalogue must be a list of rules")
    rules = [_parse_rule(index, entry) for index, entry in enumerate(entries, start=1)]
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise CatalogueError(f"duplicate rule id {rule.id}")
        seen.add(rule.id)
    return rules


def load_catalogue() -> list[RuleSpec]:
    """The catalogue packaged with shipready."""
    return parse_catalogue(files("shipready.rules").joinpath("catalogue.yaml").read_text("utf-8"))


def _parse_rule(index: int, entry: object) -> RuleSpec:
    if not isinstance(entry, dict):
        raise CatalogueError(f"rule {index}: expected a mapping, got {entry!r}")
    label = f"rule {index} ({entry.get('id', 'no id')})"

    unknown = entry.keys() - {*_REQUIRED_TEXT, *_OPTIONAL}
    if unknown:
        raise CatalogueError(f"{label}: unknown keys {sorted(unknown)}")
    for key in _REQUIRED_TEXT:
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise CatalogueError(f"{label}: '{key}' must be non-empty text")

    if not _ID_RE.match(entry["id"]):
        raise CatalogueError(f"{label}: id must look like QTY-01")
    if entry["check_type"] not in CHECK_TYPES:
        raise CatalogueError(f"{label}: check_type must be one of {CHECK_TYPES}")
    if entry["severity"] not in SEVERITIES:
        raise CatalogueError(f"{label}: severity must be one of {SEVERITIES}")

    params = entry.get("params", {})
    if not isinstance(params, dict):
        raise CatalogueError(f"{label}: 'params' must be a mapping")
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CatalogueError(f"{label}: 'enabled' must be true or false")

    return RuleSpec(**{key: entry[key] for key in _REQUIRED_TEXT}, params=params, enabled=enabled)
