"""Write golden shipments as JSON: one file per shipment with the shipment and its documents.

uv run python -m shipgen --count 5 --seed 42 --out ../data/shipgen
"""

import argparse
import json
from pathlib import Path

from shipgen.consistency import check_shipment
from shipgen.documents import build_documents
from shipgen.generator import generate_shipment


def write_shipments(count: int, seed: int, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        shipment = generate_shipment(seed, index)
        problems = check_shipment(shipment)
        if problems:
            # A golden shipment that breaks an invariant is a generator bug, never data to keep.
            raise RuntimeError(f"{shipment.shipment_id} is inconsistent: {'; '.join(problems)}")
        record = {
            "shipment": shipment.model_dump(mode="json"),
            "documents": build_documents(shipment).model_dump(mode="json"),
        }
        path = out / f"{shipment.shipment_id}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate golden ShipGen shipments as JSON.")
    parser.add_argument("--count", type=int, required=True, help="number of shipments")
    parser.add_argument("--seed", type=int, required=True, help="seed; same seed, same output")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")

    paths = write_shipments(args.count, args.seed, args.out)
    print(f"wrote {len(paths)} shipments to {args.out}")


if __name__ == "__main__":
    main()
