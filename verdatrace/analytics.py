"""Composable analytics over normalized Python records."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .catalog import parse_datetime
from .errors import InsufficientDataError
from .models import AnalysisResult, DatasetProfile, Provenance, QualityReport, SemanticType, to_dict


def _number(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def numeric_summary(values: Iterable[Any]) -> Dict[str, float]:
    numbers = sorted(number for value in values if (number := _number(value)) is not None)
    if not numbers:
        return {}
    quartiles = statistics.quantiles(numbers, n=4, method="inclusive") if len(numbers) > 1 else [numbers[0]] * 3
    return {
        "count": len(numbers),
        "min": numbers[0],
        "max": numbers[-1],
        "mean": round(statistics.fmean(numbers), 6),
        "median": round(statistics.median(numbers), 6),
        "p25": round(quartiles[0], 6),
        "p75": round(quartiles[2], 6),
        "stddev": round(statistics.pstdev(numbers), 6),
    }


def pearson_correlation(pairs: Iterable[Tuple[Any, Any]]) -> Optional[float]:
    clean = [
        (left, right)
        for left_value, right_value in pairs
        if (left := _number(left_value)) is not None and (right := _number(right_value)) is not None
    ]
    if len(clean) < 3:
        return None
    left_values, right_values = zip(*clean)
    left_mean, right_mean = statistics.fmean(left_values), statistics.fmean(right_values)
    numerator = sum((left - left_mean) * (right - right_mean) for left, right in clean)
    denominator = math.sqrt(
        sum((left - left_mean) ** 2 for left in left_values)
        * sum((right - right_mean) ** 2 for right in right_values)
    )
    return round(numerator / denominator, 6) if denominator else None


def _unit(field: str, semantic: SemanticType) -> str:
    lowered = field.lower()
    if semantic == SemanticType.TEMPERATURE:
        return "degF" if lowered.endswith("_f") else "degC"
    if semantic == SemanticType.HUMIDITY:
        return "percent"
    if semantic == SemanticType.PRESSURE:
        return "hPa"
    if semantic == SemanticType.SPEED:
        return "mph" if "mph" in lowered else "km/h"
    if semantic == SemanticType.DISTANCE:
        return "miles" if "mile" in lowered else "km"
    if semantic in {SemanticType.CO, SemanticType.CO2, SemanticType.LPG, SemanticType.SMOKE, SemanticType.PARTICULATE_MATTER}:
        return "source_unit"
    if semantic == SemanticType.RAINFALL:
        return "mm"
    return "source_unit"


def analyze_dataset(
    rows: Iterable[Dict[str, Any]],
    profile: DatasetProfile,
    quality: QualityReport,
    provenance: Provenance,
    *,
    task: str = "auto",
) -> AnalysisResult:
    materialized = list(rows)
    if not materialized:
        raise InsufficientDataError(
            "analysis requires at least one record",
            corrective_action="Ingest a non-empty dataset before running analysis.",
        )

    semantic_fields: Dict[SemanticType, List[str]] = defaultdict(list)
    for field in profile.fields:
        if field.semantic_type in SemanticType._value2member_map_:
            semantic_fields[SemanticType(field.semantic_type)].append(field.name)

    numeric_fields = [
        field.name
        for field in profile.fields
        if field.data_type == "number"
        and field.semantic_type not in {SemanticType.LATITUDE.value, SemanticType.LONGITUDE.value}
    ]
    summaries = {
        field: numeric_summary(row.get(field) for row in materialized)
        for field in numeric_fields
    }
    summaries = {field: summary for field, summary in summaries.items() if summary}
    computed: Dict[str, Any] = {
        "row_count": len(materialized),
        "numeric_summaries": summaries,
    }
    warnings: List[str] = []
    dimensions: List[str] = []
    metrics = list(summaries)
    units: Dict[str, str] = {}

    for semantic, fields in semantic_fields.items():
        for field in fields:
            if field in summaries:
                units[field] = _unit(field, semantic)

    time_field = next(iter(semantic_fields[SemanticType.TIMESTAMP]), None) or next(
        iter(semantic_fields[SemanticType.DATE]), None
    )
    if time_field:
        dimensions.append(time_field)
        metric = next((field for field in numeric_fields if field not in semantic_fields[SemanticType.DURATION]), None)
        if metric:
            daily: Dict[str, List[float]] = defaultdict(list)
            for row in materialized:
                parsed = parse_datetime(row.get(time_field))
                value = _number(row.get(metric))
                if parsed is not None and value is not None:
                    daily[parsed.date().isoformat()].append(value)
            computed["temporal_aggregation"] = [
                {"period": period, "mean": round(statistics.fmean(values), 6), "count": len(values)}
                for period, values in sorted(daily.items())
            ]
            trend = computed["temporal_aggregation"]
            if len(trend) >= 2:
                computed["trend_change"] = round(trend[-1]["mean"] - trend[0]["mean"], 6)

    distance_field = next(iter(semantic_fields[SemanticType.DISTANCE]), None)
    speed_field = next(iter(semantic_fields[SemanticType.SPEED]), None)
    duration_field = next(iter(semantic_fields[SemanticType.DURATION]), None)
    if distance_field or speed_field or duration_field:
        mobility: Dict[str, Any] = {}
        if distance_field and distance_field in summaries:
            distances = [_number(row.get(distance_field)) for row in materialized]
            mobility["total_distance"] = round(sum(value for value in distances if value is not None), 6)
            mobility["average_distance"] = summaries[distance_field]["mean"]
        if speed_field and speed_field in summaries:
            mobility["average_speed"] = summaries[speed_field]["mean"]
        elif distance_field and duration_field:
            derived_speeds = []
            for row in materialized:
                distance, duration = _number(row.get(distance_field)), _number(row.get(duration_field))
                if distance is not None and duration is not None and duration > 0:
                    derived_speeds.append(distance / (duration / 3600))
            if derived_speeds:
                mobility["average_speed_derived"] = round(statistics.fmean(derived_speeds), 6)
        computed["mobility_summary"] = mobility

    if profile.geographic_bounds:
        computed["spatial_bounds"] = profile.geographic_bounds
        dimensions.extend(
            semantic_fields[SemanticType.LONGITUDE][:1] + semantic_fields[SemanticType.LATITUDE][:1]
        )

    correlation_fields = [
        field
        for field in numeric_fields
        if field not in semantic_fields[SemanticType.DURATION]
    ]
    if len(correlation_fields) >= 2:
        left, right = correlation_fields[:2]
        computed["correlations"] = {
            f"{left}__{right}": pearson_correlation((row.get(left), row.get(right)) for row in materialized)
        }

    group_field = next(
        (
            field.name
            for field in profile.fields
            if field.semantic_type in {
                SemanticType.CATEGORICAL.value,
                SemanticType.DEVICE_ID.value,
                SemanticType.VEHICLE_ID.value,
            }
            and field.unique_count <= 50
        ),
        None,
    )
    if group_field and numeric_fields:
        grouped: Dict[str, List[float]] = defaultdict(list)
        metric = numeric_fields[0]
        for row in materialized:
            value = _number(row.get(metric))
            if value is not None:
                grouped[str(row.get(group_field, "unknown"))].append(value)
        computed["grouped_statistics"] = [
            {"group": group, "metric": metric, "mean": round(statistics.fmean(values), 6), "count": len(values)}
            for group, values in sorted(grouped.items())
        ]
        dimensions.append(group_field)

    if not summaries and not profile.geographic_bounds:
        warnings.append("No numeric or spatial fields were available for quantitative analysis.")
    if quality.status == "failed":
        warnings.append("Quality errors are present; results exclude no rows and must be interpreted with caution.")

    inferred_task = task
    if task == "auto":
        if "mobility" in profile.categories or "logistics" in profile.categories:
            inferred_task = "mobility"
        elif "sensor_iot" in profile.categories:
            inferred_task = "sensor"
        elif "geospatial_vector" in profile.categories:
            inferred_task = "spatial"
        else:
            inferred_task = "descriptive"

    return AnalysisResult(
        result_type=f"{inferred_task}_analysis",
        computed_values=computed,
        dimensions=list(dict.fromkeys(dimensions)),
        metrics=metrics,
        units=units,
        warnings=warnings,
        provenance=to_dict(provenance),
        quality_reference=f"quality:{quality.dataset_id}",
        analysis_metadata={
            "task": inferred_task,
            "method": "deterministic_descriptive_v1",
            "input_rows": len(materialized),
            "quality_score": quality.score,
        },
    )
