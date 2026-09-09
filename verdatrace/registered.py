"""Execution adapter for validated registry datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .ingestion import iter_records
from .errors import InvalidSchemaError
from .models import DatasetConfig, Provenance
from .pipeline import MultimodalPipeline, PipelineOutcome


_DISPLAY_FORMATS = {
    "csv": "CSV",
    "json": "JSON",
    "ndjson": "NDJSON",
    "geojson": "GeoJSON",
    "tif": "GeoTIFF",
    "tiff": "GeoTIFF",
}


@dataclass(frozen=True)
class RegisteredDatasetResult:
    config: DatasetConfig
    records: List[Dict[str, Any]]
    outcome: PipelineOutcome

    def to_portal_dict(self, *, preview_limit: int | None = None) -> Dict[str, Any]:
        """Return the stable v1 frontend entry without inventing attribution."""

        if preview_limit is not None and preview_limit < 0:
            raise ValueError("preview_limit must be non-negative")
        source = self.config.source
        attribution_url = source.attribution_url
        if attribution_url is None and source.original_url.startswith("https://"):
            attribution_url = source.original_url
        portal_records = self.records if preview_limit is None else self.records[:preview_limit]
        manifest_count = self.outcome.manifest.record_count if self.outcome.manifest else len(self.records)
        preview = {
            "is_sample": len(portal_records) < manifest_count,
            "records_shown": len(portal_records),
            "record_count": manifest_count,
            "strategy": "head" if len(portal_records) < len(self.records) else "complete",
        }
        return {
            "id": self.config.id,
            "title": self.config.name,
            "domain": self.config.domain,
            "dataset_type": source.dataset_type,
            "fixture": source.fixture,
            "attribution": {
                "label": source.attribution_label or source.provider,
                "url": attribution_url,
                "license": source.license,
            },
            "records": portal_records,
            "preview": preview,
            "outcome": self.outcome.to_dict(),
        }


def run_registered_dataset(
    config: DatasetConfig,
    *,
    project_root: str | Path,
    actor: str = "registry-runner",
    role: str = "steward",
) -> RegisteredDatasetResult:
    """Load one validated definition and delegate to the existing pipeline."""

    if not config.enabled:
        raise InvalidSchemaError(
            f"dataset '{config.id}' is disabled for execution",
            corrective_action="Provide and verify the configured source, then set enabled: true.",
            details={"dataset_id": config.id},
        )
    root = Path(project_root).resolve()
    source_path = root / config.source.path
    records = list(iter_records(source_path, allowed_roots=[root]))
    source = config.source
    provenance = Provenance(
        dataset_name=source.dataset_name or config.name,
        provider=source.provider,
        original_url=source.original_url,
        retrieved_at=source.retrieved_at,
        license=source.license,
        geographic_coverage=source.geographic_coverage,
        temporal_coverage=source.temporal_coverage,
        source_format=_DISPLAY_FORMATS[source.format],
        original_schema=source.original_schema,
        transformations=source.transformations,
        limitations=source.limitations,
    )
    outcome = MultimodalPipeline(actor=actor, role=role).run(
        records,
        dataset_id=config.id,
        dataset_name=config.name,
        source_format=config.source.format,
        provenance=provenance,
        task=config.task,
        required_fields=config.required_fields,
        governance={
            "owner": config.governance.owner,
            "sensitivity": config.governance.sensitivity,
            "retention_policy": config.governance.retention_policy,
        },
        domain_constraints=config.quality.domain_constraints,
        telemetry_max_age_seconds=config.quality.telemetry_max_age_seconds,
        dataset_type=config.source.dataset_type,
        input_size=source_path.stat().st_size,
        fixture=config.source.fixture,
        declared_crs=config.source.crs,
    )
    return RegisteredDatasetResult(config=config, records=records, outcome=outcome)
