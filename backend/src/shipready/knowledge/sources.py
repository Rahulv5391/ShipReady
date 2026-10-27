"""The regulatory sources of the knowledge base (sources.yaml), validated on load."""

from dataclasses import dataclass
from importlib.resources import files
from typing import Literal
from urllib.parse import urlsplit

import yaml

from shipready.rules.catalogue import load_catalogue

Format = Literal["pdf", "html"]
FORMATS: tuple[Format, ...] = ("pdf", "html")
# Government sites only: a knowledge base built from copies on other sites could quote text
# that differs from the law in force.
OFFICIAL_HOSTS = (
    "content.dgft.gov.in",
    "www.dgft.gov.in",
    "cbic-gst.gov.in",
    "taxinformation.cbic.gov.in",
    "www.cbic.gov.in",
    "www.icegate.gov.in",
)
_FIELDS = ("id", "title", "issuer", "version", "url", "format", "used_by")


class SourcesError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    issuer: str
    version: str
    url: str
    format: Format
    used_by: tuple[str, ...]


def parse_sources(text: str) -> list[Source]:
    entries = yaml.safe_load(text)
    if not isinstance(entries, list) or not entries:
        raise SourcesError("sources must be a non-empty list")
    rules = {rule.id for rule in load_catalogue()}
    sources = [_parse(index, entry, rules) for index, entry in enumerate(entries, start=1)]
    ids = [source.id for source in sources]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SourcesError(f"duplicate source ids {duplicates}")
    return sources


def load_sources() -> list[Source]:
    return parse_sources(files("shipready.knowledge").joinpath("sources.yaml").read_text("utf-8"))


def _parse(index: int, entry: object, rules: set[str]) -> Source:
    if not isinstance(entry, dict):
        raise SourcesError(f"source {index}: expected a mapping")
    label = f"source {index} ({entry.get('id', 'no id')})"
    if set(entry) != set(_FIELDS):
        raise SourcesError(f"{label}: fields must be exactly {_FIELDS}")
    text = [entry[key] for key in _FIELDS[:5]]
    if not all(isinstance(value, str) and value.strip() for value in text):
        raise SourcesError(f"{label}: id, title, issuer, version and url must be non-empty text")
    url = urlsplit(entry["url"])
    if url.scheme != "https" or url.hostname not in OFFICIAL_HOSTS:
        raise SourcesError(f"{label}: url must be https on an official host {OFFICIAL_HOSTS}")
    if entry["format"] not in FORMATS:
        raise SourcesError(f"{label}: format must be one of {FORMATS}")
    used_by = entry["used_by"]
    if not isinstance(used_by, list) or not used_by or not set(used_by) <= rules:
        raise SourcesError(f"{label}: used_by must list check IDs from the catalogue")
    return Source(
        id=entry["id"],
        title=entry["title"],
        issuer=entry["issuer"],
        version=entry["version"],
        url=entry["url"],
        format=entry["format"],
        used_by=tuple(used_by),
    )
