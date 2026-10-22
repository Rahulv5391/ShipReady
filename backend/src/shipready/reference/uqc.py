"""UQC (unit quantity code) list used on GST returns, e-invoices and shipping bills."""

import csv
from importlib.resources import files


def _load_uqc() -> dict[str, str]:
    text = files("shipready.reference").joinpath("data/uqc.csv").read_text(encoding="utf-8")
    return {row["code"]: row["description"] for row in csv.DictReader(text.splitlines())}


UQC: dict[str, str] = _load_uqc()
