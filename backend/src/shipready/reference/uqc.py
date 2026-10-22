"""UQC (unit quantity code) list used on GST returns, e-invoices and shipping bills."""

from shipready.reference.files import read_csv

UQC: dict[str, str] = {row["code"]: row["description"] for row in read_csv("uqc.csv")}
