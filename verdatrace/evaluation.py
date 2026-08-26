"""Suitability scoring for analytical and visualization tasks."""

from __future__ import annotations

from typing import Dict, List

from .models import AnalysisResult, DatasetProfile, EvaluationReport, QualityReport, SemanticType


def evaluate_suitability(
    profile: DatasetProfile,
    quality: QualityReport,
    analysis: AnalysisResult,
    *,
    task: str = "general",
) -> EvaluationReport:
    semantics = {field.semantic_type for field in profile.fields}
    checks: Dict[str, bool] = {
        "has_rows": profile.row_count > 0,
        "sample_size": profile.row_count >= 3,
        "quality_acceptable": quality.score >= 60 and quality.status != "failed",
        "has_numeric_metric": any(field.data_type == "number" for field in profile.fields),
        "has_temporal_axis": bool({SemanticType.TIMESTAMP.value, SemanticType.DATE.value} & semantics),
        "spatial_ready": (
            {SemanticType.LATITUDE.value, SemanticType.LONGITUDE.value} <= semantics
            or SemanticType.GEOMETRY.value in semantics
        ),
        "analysis_produced": bool(analysis.computed_values),
    }
    reasons: List[str] = []
    warnings: List[str] = []
    required = {"has_rows", "analysis_produced"}
    if task in {"time_series", "sensor", "climate"}:
        required |= {"has_temporal_axis", "has_numeric_metric"}
    elif task in {"spatial", "mobility"}:
        required |= {"spatial_ready"}
    elif task in {"correlation", "descriptive"}:
        required |= {"has_numeric_metric"}

    passed = sum(1 for value in checks.values() if value)
    score = round(100 * passed / len(checks), 2)
    for name in sorted(required):
        if checks.get(name):
            reasons.append(f"{name.replace('_', ' ')} requirement is satisfied")
        else:
            warnings.append(f"{name.replace('_', ' ')} requirement is not satisfied")
    if quality.status == "failed":
        warnings.append("quality errors should be remediated before production decision-making")
    eligible = all(checks.get(name, False) for name in required) and quality.score >= 40
    return EvaluationReport(
        task=task,
        eligible=eligible,
        score=score,
        reasons=reasons,
        warnings=warnings,
        checks=checks,
    )
