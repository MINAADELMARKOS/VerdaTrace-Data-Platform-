"""Machine-readable quality checks for tabular, sensor, temporal, and GIS data."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .catalog import parse_datetime
from .models import DatasetProfile, QualityIssue, QualityReport, SemanticType


def _number(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _orientation(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    return ((o1 > 0 > o2) or (o2 > 0 > o1)) and ((o3 > 0 > o4) or (o4 > 0 > o3))


def validate_geometry(geometry: Any) -> Optional[str]:
    """Return a stable validation error, or None for a supported valid geometry."""

    if not isinstance(geometry, dict):
        return "geometry must be a GeoJSON object"
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return "Point must contain longitude and latitude"
        lon, lat = _number(coordinates[0]), _number(coordinates[1])
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return "Point coordinates are outside WGS84 bounds"
        return None
    if kind == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return "LineString requires at least two positions"
        for point in coordinates:
            if not isinstance(point, list) or len(point) < 2:
                return "LineString contains an invalid position"
            lon, lat = _number(point[0]), _number(point[1])
            if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                return "LineString contains coordinates outside WGS84 bounds"
        return None
    if kind == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return "Polygon requires at least one linear ring"
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4:
                return "Polygon ring requires at least four positions"
            if ring[0] != ring[-1]:
                return "Polygon ring is not closed"
            for point in ring:
                if not isinstance(point, list) or len(point) < 2:
                    return "Polygon ring contains an invalid position"
                lon, lat = _number(point[0]), _number(point[1])
                if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    return "Polygon contains coordinates outside WGS84 bounds"
            segments = list(zip(ring[:-1], ring[1:]))
            for left_index, (a, b) in enumerate(segments):
                for right_index, (c, d) in enumerate(segments):
                    if abs(left_index - right_index) <= 1:
                        continue
                    if {left_index, right_index} == {0, len(segments) - 1}:
                        continue
                    if _segments_intersect(a, b, c, d):
                        return "Polygon ring self-intersects"
        return None
    if kind == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            return "MultiPolygon requires polygon coordinates"
        for polygon in coordinates:
            error = validate_geometry({"type": "Polygon", "coordinates": polygon})
            if error:
                return error
        return None
    return f"unsupported GeoJSON geometry type: {kind}"


def _add_grouped_issue(
    issues: List[QualityIssue],
    *,
    code: str,
    severity: str,
    message: str,
    field: Optional[str],
    indexes: List[int],
    observed: Any = None,
    rule: Optional[str] = None,
) -> None:
    if indexes:
        issues.append(
            QualityIssue(
                code=code,
                severity=severity,
                message=message,
                field=field,
                row_indexes=indexes[:100],
                observed=observed,
                rule=rule,
            )
        )


def evaluate_quality(
    rows: Iterable[Dict[str, Any]],
    profile: DatasetProfile,
    *,
    required_fields: Optional[Sequence[str]] = None,
    domain_constraints: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,
    telemetry_max_age: Optional[timedelta] = None,
    now: Optional[datetime] = None,
) -> QualityReport:
    materialized = list(rows)
    issues: List[QualityIssue] = []
    failed_rows: set[int] = set()
    semantics = {field.name: SemanticType(field.semantic_type) for field in profile.fields if field.semantic_type in SemanticType._value2member_map_}

    for field in required_fields or []:
        missing = [index for index, row in enumerate(materialized) if row.get(field) in (None, "")]
        failed_rows.update(missing)
        _add_grouped_issue(
            issues,
            code="missing_required_value",
            severity="error",
            message=f"required field '{field}' is missing",
            field=field,
            indexes=missing,
            rule="value must be present",
        )

    for field, semantic in semantics.items():
        values = [row.get(field) for row in materialized]
        nulls = [index for index, value in enumerate(values) if value in (None, "")]
        if nulls:
            severity = "warning" if semantic in {SemanticType.TIMESTAMP, SemanticType.DATE} else "info"
            _add_grouped_issue(
                issues,
                code="missing_value",
                severity=severity,
                message=f"{len(nulls)} rows have no value for '{field}'",
                field=field,
                indexes=nulls,
                rule="completeness",
            )

        if semantic in {SemanticType.TIMESTAMP, SemanticType.DATE}:
            invalid = [
                index
                for index, value in enumerate(values)
                if value not in (None, "") and parse_datetime(value) is None
            ]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="invalid_timestamp",
                severity="error",
                message=f"'{field}' contains timestamps that cannot be parsed",
                field=field,
                indexes=invalid,
                rule="ISO-8601 or epoch timestamp required",
            )
        elif semantic == SemanticType.LATITUDE:
            invalid = [
                index
                for index, value in enumerate(values)
                if value not in (None, "") and (_number(value) is None or not -90 <= (_number(value) or 0) <= 90)
            ]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="invalid_latitude",
                severity="error",
                message="latitude must be numeric and between -90 and 90",
                field=field,
                indexes=invalid,
                observed=[values[index] for index in invalid[:5]],
                rule="-90 <= latitude <= 90",
            )
        elif semantic == SemanticType.LONGITUDE:
            invalid = [
                index
                for index, value in enumerate(values)
                if value not in (None, "") and (_number(value) is None or not -180 <= (_number(value) or 0) <= 180)
            ]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="invalid_longitude",
                severity="error",
                message="longitude must be numeric and between -180 and 180",
                field=field,
                indexes=invalid,
                observed=[values[index] for index in invalid[:5]],
                rule="-180 <= longitude <= 180",
            )
        elif semantic == SemanticType.HUMIDITY:
            invalid = [
                index
                for index, value in enumerate(values)
                if value not in (None, "") and (_number(value) is None or not 0 <= (_number(value) or 0) <= 100)
            ]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="invalid_humidity",
                severity="error",
                message="relative humidity must be between 0 and 100 percent",
                field=field,
                indexes=invalid,
                observed=[values[index] for index in invalid[:5]],
                rule="0 <= relative humidity <= 100",
            )
        elif semantic in {
            SemanticType.CO,
            SemanticType.CO2,
            SemanticType.LPG,
            SemanticType.SMOKE,
            SemanticType.PARTICULATE_MATTER,
            SemanticType.RAINFALL,
        }:
            invalid = [
                index
                for index, value in enumerate(values)
                if value not in (None, "") and (_number(value) is None or (_number(value) or 0) < 0)
            ]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="impossible_sensor_reading",
                severity="error",
                message=f"'{field}' contains a negative or non-numeric physical measurement",
                field=field,
                indexes=invalid,
                rule="measurement must be numeric and non-negative",
            )
        elif semantic == SemanticType.GEOMETRY:
            invalid_pairs = [
                (index, validate_geometry(value))
                for index, value in enumerate(values)
                if value not in (None, "") and validate_geometry(value) is not None
            ]
            invalid = [index for index, _ in invalid_pairs]
            failed_rows.update(invalid)
            _add_grouped_issue(
                issues,
                code="invalid_geometry",
                severity="error",
                message="one or more GeoJSON geometries are invalid",
                field=field,
                indexes=invalid,
                observed=[message for _, message in invalid_pairs[:5]],
                rule="valid supported GeoJSON geometry",
            )

    for field, (minimum, maximum) in (domain_constraints or {}).items():
        invalid: List[int] = []
        for index, row in enumerate(materialized):
            value = row.get(field)
            number = _number(value)
            if value in (None, ""):
                continue
            if number is None or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
                invalid.append(index)
        failed_rows.update(invalid)
        _add_grouped_issue(
            issues,
            code="domain_range_violation",
            severity="error",
            message=f"'{field}' violates a configured sensor/domain range",
            field=field,
            indexes=invalid,
            rule=f"{minimum if minimum is not None else '-inf'} <= value <= {maximum if maximum is not None else 'inf'}",
        )

    event_identity_fields = [
        field.name
        for field in profile.fields
        if field.semantic_type == SemanticType.IDENTIFIER.value
    ]
    duplicate_key = event_identity_fields[0] if event_identity_fields else None
    seen: Dict[str, int] = {}
    duplicates: List[int] = []
    for index, row in enumerate(materialized):
        if duplicate_key and row.get(duplicate_key) not in (None, ""):
            signature = f"{duplicate_key}:{row.get(duplicate_key)}"
        else:
            signature = repr(sorted(row.items(), key=lambda item: item[0]))
        if signature in seen:
            duplicates.append(index)
        else:
            seen[signature] = index
    failed_rows.update(duplicates)
    _add_grouped_issue(
        issues,
        code="duplicate_event",
        severity="error",
        message="duplicate records or event identifiers were detected",
        field=duplicate_key,
        indexes=duplicates,
        rule="record/event identity must be unique",
    )

    numeric_fields = [
        field.name
        for field in profile.fields
        if field.data_type == "number"
        and field.semantic_type not in {SemanticType.LATITUDE.value, SemanticType.LONGITUDE.value}
    ]
    for field in numeric_fields:
        indexed = [(index, _number(row.get(field))) for index, row in enumerate(materialized)]
        valid = [(index, value) for index, value in indexed if value is not None]
        if len(valid) < 8:
            continue
        ordered = sorted(value for _, value in valid)
        quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
        lower, upper = quartiles[0], quartiles[2]
        iqr = upper - lower
        if iqr <= 0:
            continue
        low_fence, high_fence = lower - 3 * iqr, upper + 3 * iqr
        outliers = [index for index, value in valid if value < low_fence or value > high_fence]
        _add_grouped_issue(
            issues,
            code="statistical_outlier",
            severity="warning",
            message=f"'{field}' contains extreme values beyond three interquartile ranges",
            field=field,
            indexes=outliers,
            rule="Tukey outer fence (3 x IQR)",
        )

    time_field = next(
        (field.name for field in profile.fields if field.semantic_type == SemanticType.TIMESTAMP.value),
        None,
    )
    if time_field:
        parsed_times = sorted(
            (parse_datetime(row.get(time_field)), index)
            for index, row in enumerate(materialized)
            if parse_datetime(row.get(time_field)) is not None
        )
        if len(parsed_times) >= 4:
            gaps = [
                (parsed_times[index][0] - parsed_times[index - 1][0]).total_seconds()
                for index in range(1, len(parsed_times))
            ]
            median_gap = statistics.median(gaps)
            gap_indexes = [
                parsed_times[index][1]
                for index in range(1, len(parsed_times))
                if median_gap > 0 and gaps[index - 1] > median_gap * 3
            ]
            _add_grouped_issue(
                issues,
                code="sensor_gap",
                severity="warning",
                message="telemetry contains gaps greater than three times the median interval",
                field=time_field,
                indexes=gap_indexes,
                rule="gap <= 3 x median sampling interval",
            )
        if telemetry_max_age is not None:
            reference = now or datetime.now(timezone.utc)
            stale = [
                index
                for parsed, index in parsed_times
                if reference - parsed > telemetry_max_age
            ]
            _add_grouped_issue(
                issues,
                code="stale_telemetry",
                severity="warning",
                message="telemetry is older than the configured freshness objective",
                field=time_field,
                indexes=stale,
                rule=f"age <= {telemetry_max_age}",
            )

    error_count = sum(len(issue.row_indexes) for issue in issues if issue.severity == "error")
    warning_count = sum(len(issue.row_indexes) for issue in issues if issue.severity == "warning")
    penalty = (error_count * 8 + warning_count * 2) / max(len(materialized), 1)
    score = round(max(0.0, 100.0 - min(100.0, penalty)), 2)
    status = "failed" if error_count or score < 60 else ("warning" if warning_count else "passed")
    metrics = {
        "error_occurrences": error_count,
        "warning_occurrences": warning_count,
        "duplicate_rows": len(duplicates),
        "null_cells": sum(field.null_count for field in profile.fields),
        "field_count": len(profile.fields),
    }
    return QualityReport(
        dataset_id=profile.dataset_id,
        total_rows=len(materialized),
        valid_rows=max(0, len(materialized) - len(failed_rows)),
        score=score,
        status=status,
        issues=issues,
        metrics=metrics,
    )
