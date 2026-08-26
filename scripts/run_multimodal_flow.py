"""Run the complete local VerdaTrace pipeline over an approved input file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verdatrace.ingestion import iter_records
from verdatrace.models import Provenance
from verdatrace.pipeline import MultimodalPipeline


def load_provenance(source: Path, dataset_id: str) -> Provenance:
    if source.suffix.lower() in {".json", ".geojson"}:
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("provenance"), dict):
            return Provenance(**value["provenance"])
    registry = json.loads((ROOT / "config" / "datasets.json").read_text(encoding="utf-8"))
    item = next((entry for entry in registry["datasets"] if entry["id"] == dataset_id), None)
    if item is None:
        raise ValueError(
            "provenance is required: use a registered dataset_id or a JSON envelope with provenance"
        )
    allowed = {
        "dataset_name",
        "provider",
        "original_url",
        "retrieved_at",
        "license",
        "geographic_coverage",
        "temporal_coverage",
        "source_format",
        "original_schema",
        "transformations",
        "target_schema",
        "limitations",
    }
    return Provenance(**{key: value for key, value in item.items() if key in allowed})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, default=ROOT / "data")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-name")
    parser.add_argument("--task", default="general")
    parser.add_argument("--actor", default="local-developer")
    parser.add_argument("--role", default="steward")
    parser.add_argument("--max-records", type=int, default=100000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = args.input.resolve()
    records = list(
        iter_records(
            source,
            allowed_roots=[args.allowed_root.resolve()],
            max_records=args.max_records,
        )
    )
    provenance = load_provenance(source, args.dataset_id)
    outcome = MultimodalPipeline(actor=args.actor, role=args.role).run(
        records,
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name or provenance.dataset_name,
        source_format=source.suffix.lstrip("."),
        provenance=provenance,
        task=args.task,
    )
    rendered = json.dumps(outcome.to_dict(), indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
