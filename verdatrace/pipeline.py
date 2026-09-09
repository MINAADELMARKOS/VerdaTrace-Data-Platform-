"""Orchestration that keeps each pipeline stage independently testable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .analytics import analyze_dataset
from .catalog import profile_dataset
from .evaluation import evaluate_suitability
from .lineage import LineageTracker
from .models import (
    AnalysisResult,
    DatasetManifest,
    DatasetProfile,
    ExecutiveKPI,
    EvaluationReport,
    Provenance,
    QualityReport,
    VisualizationRecommendation,
    to_dict,
)
from .quality import evaluate_quality
from .security import AuditEvent, AuditRecorder, authorize
from .visualization import recommend_visualizations


@dataclass(frozen=True)
class PipelineOutcome:
    profile: DatasetProfile
    quality: QualityReport
    analysis: AnalysisResult
    evaluation: EvaluationReport
    visualization: VisualizationRecommendation
    governance: Dict[str, Any]
    lineage: List[Dict[str, Any]]
    audit_events: List[AuditEvent]
    # Appended optional fields preserve the original positional outcome contract.
    manifest: Optional[DatasetManifest] = None
    executive_kpis: List[ExecutiveKPI] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return to_dict(self)


class MultimodalPipeline:
    def __init__(
        self,
        *,
        actor: str = "local-developer",
        role: str = "steward",
        audit: Optional[AuditRecorder] = None,
    ) -> None:
        self.actor = actor
        self.role = role
        self.audit = audit or AuditRecorder()

    def run(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        dataset_id: str,
        dataset_name: str,
        source_format: str,
        provenance: Provenance,
        task: str = "general",
        required_fields: Optional[Sequence[str]] = None,
        governance: Optional[Dict[str, Any]] = None,
        domain_constraints: Optional[Dict[str, tuple[Optional[float], Optional[float]]]] = None,
        telemetry_max_age_seconds: Optional[float] = None,
        dataset_type: Optional[str] = None,
        input_size: Optional[int] = None,
        fixture: Optional[bool] = None,
        declared_crs: Optional[str] = None,
        executive_kpis: Optional[Sequence[ExecutiveKPI]] = None,
    ) -> PipelineOutcome:
        authorize(self.role, "dataset:ingest")
        authorize(self.role, "quality:evaluate")
        authorize(self.role, "analysis:execute")
        correlation_id = str(uuid.uuid4())
        rows = list(records)
        lineage = LineageTracker()
        source_ref = provenance.original_url or f"source:{dataset_id}"

        started_event = self.audit.record(
            actor=self.actor,
            operation="dataset_ingestion",
            target=dataset_id,
            outcome="started",
            correlation_id=correlation_id,
            details={"record_count": len(rows), "source_format": source_format},
        )
        lineage.add("raw_ingestion", source_ref, f"raw:{dataset_id}", f"ingest_{source_format.lower()}")

        profile = profile_dataset(
            rows,
            dataset_id=dataset_id,
            name=dataset_name,
            source_format=source_format,
        )
        lineage.add("schema_discovery", f"raw:{dataset_id}", f"catalog:{dataset_id}", "profile_and_classify")

        quality = evaluate_quality(
            rows,
            profile,
            required_fields=required_fields,
            domain_constraints=domain_constraints,
            telemetry_max_age=(
                timedelta(seconds=telemetry_max_age_seconds)
                if telemetry_max_age_seconds is not None
                else None
            ),
        )
        lineage.add("quality_checks", f"raw:{dataset_id}", f"quality:{dataset_id}", "deterministic_quality_rules")
        self.audit.record(
            actor=self.actor,
            operation="quality_evaluation",
            target=dataset_id,
            outcome=quality.status,
            correlation_id=correlation_id,
            details={"quality_score": quality.score, "issue_count": len(quality.issues)},
        )

        analysis = analyze_dataset(rows, profile, quality, provenance, task=task)
        lineage.add("analysis", f"quality:{dataset_id}", f"analysis:{dataset_id}", analysis.result_type)
        self.audit.record(
            actor=self.actor,
            operation="analysis_execution",
            target=dataset_id,
            outcome="succeeded",
            correlation_id=correlation_id,
            details={"result_type": analysis.result_type, "metric_count": len(analysis.metrics)},
        )

        evaluation = evaluate_suitability(profile, quality, analysis, task=task)
        lineage.add("evaluation", f"analysis:{dataset_id}", f"evaluation:{dataset_id}", f"evaluate_{task}")
        visualization = recommend_visualizations(profile, evaluation)
        lineage.add(
            "visualization",
            f"evaluation:{dataset_id}",
            f"visualization:{dataset_id}",
            "deterministic_recommendation",
        )
        kpis = list(executive_kpis or [])
        if kpis:
            lineage.add(
                "executive_kpis",
                f"analysis:{dataset_id}",
                f"kpis:{dataset_id}",
                "configured_result_metrics",
            )
            self.audit.record(
                actor=self.actor,
                operation="executive_kpi_generation",
                target=dataset_id,
                outcome="succeeded",
                correlation_id=correlation_id,
                details={"kpi_count": len(kpis)},
            )
        analysis = replace(
            analysis,
            lineage=lineage.as_list(),
            analysis_metadata={
                **analysis.analysis_metadata,
                "dataset_id": dataset_id,
                "source_format": source_format,
            },
        )

        governance_record = {
            "owner": "unknown",
            "source": provenance.provider,
            "license": provenance.license,
            "classification": profile.categories,
            "sensitivity": "not_provided",
            "retention_policy": "not_provided",
            "ingestion_timestamp": started_event.timestamp,
            "transformation_history": provenance.transformations,
            "schema_version": "verdatrace_multimodal_v1",
            "quality_status": quality.status,
            "geographic_coverage": provenance.geographic_coverage,
            "temporal_coverage": provenance.temporal_coverage,
            **(governance or {}),
        }
        finished_event = self.audit.record(
            actor=self.actor,
            operation="dataset_ingestion",
            target=dataset_id,
            outcome="succeeded",
            correlation_id=correlation_id,
            details={
                "quality_status": quality.status,
                "analysis_result_type": analysis.result_type,
                "visualization_count": len(visualization.recommended_visualizations),
            },
        )
        geometry_types = sorted(
            {
                str(geometry["type"])
                for row in rows
                if isinstance((geometry := row.get("geometry")), dict) and geometry.get("type")
            }
        )
        observed_crs = {
            str(row["crs"])
            for row in rows
            if row.get("crs") not in (None, "")
        }

        def known(value: str) -> Optional[str]:
            return None if value.strip().lower() in {"", "unknown", "not_provided"} else value

        manifest = DatasetManifest(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            provider=known(provenance.provider),
            source_format=known(source_format),
            dataset_type=dataset_type,
            input_size=input_size,
            record_count=profile.row_count,
            geometry_types=geometry_types,
            crs=declared_crs or (next(iter(observed_crs)) if len(observed_crs) == 1 else None),
            bounding_box=profile.geographic_bounds,
            geographic_coverage=known(provenance.geographic_coverage),
            temporal_coverage=profile.temporal_coverage,
            license=known(provenance.license),
            ingestion_timestamp=started_event.timestamp,
            processing_timestamp=finished_event.timestamp,
            fixture=fixture,
        )
        return PipelineOutcome(
            manifest=manifest,
            profile=profile,
            quality=quality,
            analysis=analysis,
            evaluation=evaluation,
            visualization=visualization,
            governance=governance_record,
            lineage=lineage.as_list(),
            # Keep an outcome scoped to this execution even when a recorder is reused.
            audit_events=[event for event in self.audit.events if event.correlation_id == correlation_id],
            executive_kpis=kpis,
        )
