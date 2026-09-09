"""Machine-readable quality checks for tabular, sensor, temporal, and GIS data."""

from __future__ import annotations

import math
import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .catalog import parse_datetime
from .models import DatasetProfile, QualityIssue, QualityReport, QuarantineRecord, SemanticType


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


def _position_is_valid(point: Any) -> bool:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return False
    lon, lat = _number(point[0]), _number(point[1])
    return lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90


def _ring_area(ring: Sequence[Sequence[float]]) -> float:
    return abs(
        sum(
            (float(left[0]) * float(right[1])) - (float(right[0]) * float(left[1]))
            for left, right in zip(ring, ring[1:])
        )
        / 2
    )


def validate_geometry(geometry: Any) -> Optional[str]:
    """Return a stable validation error, or None for a supported valid geometry."""

    if not isinstance(geometry, dict):
        return "geometry must be a GeoJSON object"
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        if not _position_is_valid(coordinates):
            return "Point must contain longitude and latitude"
        return None
    if kind == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return "LineString requires at least two positions"
        if not all(_position_is_valid(point) for point in coordinates):
            return "LineString contains coordinates outside WGS84 bounds or an invalid position"
        if all(point[:2] == coordinates[0][:2] for point in coordinates[1:]):
            return "LineString has zero length"
        return None
    if kind == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return "Polygon requires at least one linear ring"
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4:
                return "Polygon ring requires at least four positions"
            if ring[0] != ring[-1]:
                return "Polygon ring is not closed"
            if not all(_position_is_valid(point) for point in ring):
                return "Polygon contains coordinates outside WGS84 bounds or an invalid position"
            segments = list(zip(ring[:-1], ring[1:]))
            for left_index, (a, b) in enumerate(segments):
                for right_index, (c, d) in enumerate(segments):
                    if abs(left_index - right_index) <= 1:
                        continue
                    if {left_index, right_index} == {0, len(segments) - 1}:
                        continue
                    if _segments_intersect(a, b, c, d):
                        return "Polygon ring self-intersects"
            if _ring_area(ring) == 0:
                return "Polygon ring has zero area"
        return None
    if kind == "MultiPoint":
        if not isinstance(coordinates, list) or not coordinates:
            return "MultiPoint requires at least one position"
        return None if all(_position_is_valid(point) for point in coordinates) else "MultiPoint contains an invalid position"
    if kind == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            return "MultiLineString requires at least one line"
        for line in coordinates:
            error = validate_geometry({"type": "LineString", "coordinates": line})
            if error:
                return error
        return None
    if kind == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            return "MultiPolygon requires polygon coordinates"
        for polygon in coordinates:
            error = validate_geometry({"type": "Polygon", "coordinates": polygon})
            if error:
                return error
        return None
    if kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list) or not geometries:
            return "GeometryCollection requires at least one geometry"
        for child in geometries:
            error = validate_geometry(child)
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

    latitude_fields = [field.name for field in profile.fields if field.semantic_type == SemanticType.LATITUDE.value]
    longitude_fields = [field.name for field in profile.fields if field.semantic_type == SemanticType.LONGITUDE.value]
    latitude_field = latitude_fields[0] if latitude_fields else None
    longitude_field = longitude_fields[0] if longitude_fields else None
    if latitude_field and longitude_field:
        missing_coordinates = [
            index
            for index, row in enumerate(materialized)
            if row.get(latitude_field) in (None, "") or row.get(longitude_field) in (None, "")
        ]
        _add_grouped_issue(
            issues,
            code="missing_coordinates",
            severity="warning",
            message="one or both coordinate fields are missing",
            field=f"{latitude_field},{longitude_field}",
            indexes=missing_coordinates,
            rule="latitude and longitude should be present together",
        )
        swapped = [
            index
            for index, row in enumerate(materialized)
            if (_number(row.get(latitude_field)) is not None and _number(row.get(longitude_field)) is not None)
            and abs(_number(row.get(latitude_field)) or 0) > 90
            and abs(_number(row.get(longitude_field)) or 0) <= 90
        ]
        _add_grouped_issue(
            issues,
            code="suspected_swapped_coordinates",
            severity="warning",
            message="coordinate magnitudes suggest latitude and longitude may be swapped",
            field=f"{latitude_field},{longitude_field}",
            indexes=swapped,
            observed=[(materialized[index].get(latitude_field), materialized[index].get(longitude_field)) for index in swapped[:5]],
            rule="review coordinate axis order; warning only",
        )

    geometry_fields = [field.name for field in profile.fields if field.semantic_type == SemanticType.GEOMETRY.value]
    for geometry_field in geometry_fields:
        geometry_values = [row.get(geometry_field) for row in materialized]
        empty_geometry = [
            index for index, value in enumerate(geometry_values)
            if value in (None, "") or value == {}
        ]
        _add_grouped_issue(
            issues,
            code="empty_geometry",
            severity="warning",
            message=f"'{geometry_field}' is empty for one or more records",
            field=geometry_field,
            indexes=empty_geometry,
            rule="geometry should be present when a spatial layer is expected",
        )
        signatures: Dict[str, int] = {}
        duplicate_geometry: List[int] = []
        for index, value in enumerate(geometry_values):
            if value in (None, "") or value == {}:
                continue
            try:
                signature = json.dumps(value, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError):
                continue
            if signature in signatures:
                duplicate_geometry.append(index)
            else:
                signatures[signature] = index
        _add_grouped_issue(
            issues,
            code="duplicate_geometry",
            severity="warning",
            message=f"duplicate '{geometry_field}' geometries were detected",
            field=geometry_field,
            indexes=duplicate_geometry,
            rule="geometry signature should be unique where feature identity requires it",
        )

    geometry_observed = any(row.get("geometry") not in (None, "") for row in materialized)
    crs_fields = [field.name for field in profile.fields if field.semantic_type == SemanticType.CRS.value]
    crs_field = crs_fields[0] if crs_fields else "crs"
    crs_values = {
        str(row.get(crs_field)).strip().upper()
        for row in materialized
        if row.get(crs_field) not in (None, "")
    }
    if geometry_observed and not crs_values:
        _add_grouped_issue(
            issues,
            code="missing_crs",
            severity="warning",
            message="geometry is present but CRS metadata is missing",
            field=crs_field,
            indexes=list(range(len(materialized))),
            rule="declare a supported CRS before spatial analysis",
        )
    assumed_crs = [
        index for index, row in enumerate(materialized)
        if str(row.get("crs_source", "")).lower() in {"assumed", "assumed_default"}
    ]
    _add_grouped_issue(
        issues,
        code="crs_assumed",
        severity="warning",
        message="CRS was defaulted by the ingestion adapter because the source did not declare it",
        field=crs_field,
        indexes=assumed_crs,
        rule="prefer explicit CRS metadata",
    )
    if len(crs_values) > 1:
        _add_grouped_issue(
            issues,
            code="inconsistent_crs",
            severity="error",
            message="records declare more than one CRS",
            field=crs_field,
            indexes=[index for index, row in enumerate(materialized) if row.get(crs_field) not in (None, "")],
            observed=sorted(crs_values),
            rule="one supported CRS per normalized dataset",
        )
    unsupported_crs = [
        index
        for index, row in enumerate(materialized)
        if row.get(crs_field) not in (None, "")
        and str(row.get(crs_field)).strip().upper() not in {"EPSG:4326", "CRS84", "OGC:CRS84", "URN:OGC:DEF:CRS:OGC:1.3:CRS84"}
    ]
    _add_grouped_issue(
        issues,
        code="unsupported_crs",
        severity="error",
        message="records declare a CRS outside the supported WGS84 boundary",
        field=crs_field,
        indexes=unsupported_crs,
        rule="EPSG:4326 or CRS84 required unless an explicit reprojection adapter is configured",
    )

    if any("osm_id" in row or "feature_type" in row for row in materialized):
        missing_geometry = [
            index for index, row in enumerate(materialized)
            if row.get("geometry") in (None, "") or row.get("geometry") == {}
        ]
        _add_grouped_issue(
            issues,
            code="osm_missing_geometry",
            severity="warning",
            message="OSM feature has no geometry",
            field="geometry",
            indexes=missing_geometry,
            rule="source geometry should be retained for spatial analysis",
        )
        empty_tags = [
            index for index, row in enumerate(materialized)
            if not isinstance(row.get("tags"), dict) or not row.get("tags")
        ]
        _add_grouped_issue(
            issues,
            code="osm_empty_tags",
            severity="warning",
            message="OSM feature has no source tags",
            field="tags",
            indexes=empty_tags,
            rule="empty tags are incomplete metadata, not necessarily source corruption",
        )
        missing_classification = [
            index for index, row in enumerate(materialized)
            if not any(row.get(key) not in (None, "") for key in ("highway", "building", "amenity", "landuse"))
        ]
        _add_grouped_issue(
            issues,
            code="osm_missing_classification",
            severity="warning",
            message="OSM feature has no common classification tag",
            field="tags",
            indexes=missing_classification,
            rule="classification completeness is warning-level",
        )
        seen_osm: Dict[str, int] = {}
        duplicate_osm: List[int] = []
        for index, row in enumerate(materialized):
            osm_id = row.get("osm_id")
            if osm_id in (None, ""):
                continue
            key = str(osm_id)
            if key in seen_osm:
                duplicate_osm.append(index)
            else:
                seen_osm[key] = index
        _add_grouped_issue(
            issues,
            code="duplicate_osm_id",
            severity="error",
            message="duplicate OSM identifiers were detected",
            field="osm_id",
            indexes=duplicate_osm,
            rule="osm_id must be unique within the normalized extract",
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


_REPAIRABLE_QUALITY_CODES = {
    "missing_value",
    "missing_coordinates",
    "empty_geometry",
    "duplicate_geometry",
    "statistical_outlier",
    "sensor_gap",
    "stale_telemetry",
    "crs_assumed",
    "suspected_swapped_coordinates",
    "osm_missing_geometry",
    "osm_empty_tags",
    "osm_missing_classification",
}
_REJECTED_QUALITY_CODES = {"missing_required_value", "invalid_timestamp", "unsupported_crs"}


def _safe_observed_value(value: Any) -> Any:
    """Keep quarantine context useful without copying large or sensitive payloads."""

    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:256] + ("…" if len(value) > 256 else "")
    if isinstance(value, dict):
        return {"type": value.get("type")} if value.get("type") else "[object]"
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    return str(value)[:256]


def route_quality_outcomes(
    rows: Sequence[Dict[str, Any]],
    quality: QualityReport,
    *,
    processing_timestamp: Optional[str] = None,
) -> Tuple[List[str], List[QuarantineRecord]]:
    """Route records using deterministic quality findings; no automatic repair occurs."""

    timestamp = processing_timestamp or datetime.now(timezone.utc).isoformat()
    issues_by_row: Dict[int, List[QualityIssue]] = {}
    for issue in quality.issues:
        for index in issue.row_indexes:
            issues_by_row.setdefault(index, []).append(issue)
    statuses: List[str] = []
    quarantine: List[QuarantineRecord] = []
    for index, row in enumerate(rows):
        row_issues = issues_by_row.get(index, [])
        if not row_issues:
            statuses.append("VALID")
            continue
        errors = [issue for issue in row_issues if issue.severity == "error"]
        if not errors:
            statuses.append(
                "REPAIRABLE"
                if any(issue.code in _REPAIRABLE_QUALITY_CODES or issue.severity == "warning" for issue in row_issues)
                else "VALID"
            )
            continue
        selected = next((issue for issue in errors if issue.code in _REJECTED_QUALITY_CODES), errors[0])
        status = "REJECTED" if selected.code in _REJECTED_QUALITY_CODES else "QUARANTINED"
        statuses.append(status)
        raw_id = row.get("record_id") or row.get("event_id") or row.get("feature_id") or row.get("osm_id") or index
        observed = row.get(selected.field) if selected.field else selected.observed
        quarantine.append(
            QuarantineRecord(
                dataset_id=quality.dataset_id,
                record_id=str(raw_id),
                issue_code=selected.code,
                severity=selected.severity,
                field=selected.field,
                observed_value=_safe_observed_value(observed),
                reason=selected.message,
                processing_timestamp=timestamp,
            )
        )
    return statuses, quarantine
