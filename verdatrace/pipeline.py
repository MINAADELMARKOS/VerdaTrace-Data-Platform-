"""Orchestration that keeps each pipeline stage independently testable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .analytics import analyze_dataset
from .catalog import profile_dataset
from .evaluation import evaluate_suitability
from .lineage import LineageTracker
from .models import (
    AnalysisResult,
    DatasetProfile,
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

        quality = evaluate_quality(rows, profile, required_fields=required_fields)
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
        analysis = replace(analysis, lineage=lineage.as_list())

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
        self.audit.record(
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
        return PipelineOutcome(
            profile=profile,
            quality=quality,
            analysis=analysis,
            evaluation=evaluation,
            visualization=visualization,
            governance=governance_record,
            lineage=lineage.as_list(),
            audit_events=list(self.audit.events),
        )
