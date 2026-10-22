"""Read the CSV reference files packaged with shipready."""

import csv
from importlib.resources import files


def read_csv(name: str) -> list[dict[str, str]]:
    """Rows of reference/data/<name> as dicts keyed by the header row."""
    text = files("shipready.reference").joinpath("data", name).read_text(encoding="utf-8")
    return list(csv.DictReader(text.splitlines()))
