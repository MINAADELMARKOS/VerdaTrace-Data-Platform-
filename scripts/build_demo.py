"""Generate the portal payload from every validated dataset definition."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verdatrace.registered import run_registered_dataset
from verdatrace.registry import DatasetRegistry
from verdatrace.cohesive import build_cohesive_payload

DEFAULT_OUTPUT = ROOT / "frontend" / "data" / "platform_demo.json"


def build_demo_payload(
    *,
    project_root: str | Path = ROOT,
    registry_directory: Optional[str | Path] = None,
    actor: str = "demo-builder",
    preview_limit: int | None = 5000,
    pack_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Build one normalized entry per enabled registry definition.

    The pipeline still computes analytics from the source; ``preview_limit`` only
    bounds records serialized into the browser payload.
    """

    root = Path(project_root).resolve()
    registry_path = (
        Path(registry_directory).resolve()
        if registry_directory is not None
        else root / "config" / "datasets"
    )
    registry = DatasetRegistry.discover(registry_path, project_root=root)
    datasets = [
        run_registered_dataset(config, project_root=root, actor=actor).to_portal_dict(preview_limit=preview_limit)
        for config in registry
        if config.enabled
    ]
    payload: Dict[str, Any] = {
        "schema_version": "verdatrace_portal_payload_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": datasets,
    }
    # The cohesive pack is optional so existing registry-only deployments remain
    # backward compatible.  Raw files are intentionally supplied at build time.
    resolved_pack = Path(pack_root).resolve() if pack_root is not None else None
    if resolved_pack is None and root == ROOT:
        import os

        configured = os.environ.get("VERDATARACE_PACK_ROOT")
        resolved_pack = Path(configured).resolve() if configured else None
    if resolved_pack is not None:
        cohesive = build_cohesive_payload(resolved_pack, preview_limit=min(preview_limit or 300, 500))
        payload["schema_version"] = "verdatrace_portal_payload_v2"
        payload["datasets"].extend(cohesive["datasets"])
        payload["platform"] = cohesive["platform"]
    return payload


def write_demo_payload(payload: Dict[str, Any], output: str | Path) -> Path:
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--actor", default="demo-builder")
    parser.add_argument(
        "--pack-root",
        type=Path,
        help="path to the extracted VerdaTrace Cohesive Data Pack (raw/ and metadata/)",
    )
    parser.add_argument(
        "--preview-limit",
        type=int,
        default=5000,
        help="maximum records serialized per dataset for the browser payload (default: 5000)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    payload = build_demo_payload(
        project_root=args.project_root,
        registry_directory=args.registry,
        actor=args.actor,
        preview_limit=args.preview_limit,
        pack_root=args.pack_root,
    )
    output = write_demo_payload(payload, args.output)
    print(f"wrote {len(payload['datasets'])} normalized datasets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
