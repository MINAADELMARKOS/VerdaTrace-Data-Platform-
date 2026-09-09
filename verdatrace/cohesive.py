"""Cohesive data-pack ingestion, quality, profiling, and cross-domain analytics.

The supplied VerdaTrace data pack is intentionally synthetic and large enough to
exercise streaming ingestion.  This module keeps raw files outside the source
repository, reads them in bounded passes, and emits the same normalized portal
contracts used by the existing pipeline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import time
import xml.etree.ElementTree as ET
from fnmatch import fnmatch
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from .catalog import profile_dataset
from .ingestion import iter_records
from .models import DatasetManifest, DatasetProfile, EvaluationReport, Provenance, to_dict
from .visualization import recommend_visualizations


PACK_SPECS: Dict[str, Dict[str, Any]] = {
    "zones": {"file": "zones.csv", "format": "CSV", "domain": "master_reference", "pk": "zone_id"},
    "sites": {"file": "sites.csv", "format": "CSV", "domain": "master_reference", "pk": "site_id"},
    "vehicles": {"file": "vehicles.csv", "format": "CSV", "domain": "master_reference", "pk": "vehicle_id"},
    "sensors": {"file": "sensors.csv", "format": "CSV", "domain": "sensor_reference", "pk": "sensor_id"},
    "logistics_shipments": {"file": "logistics_shipments.csv", "format": "CSV", "domain": "logistics", "pk": "shipment_id", "time": "created_at"},
    "mobility_stream": {"file": "mobility_stream.jsonl", "format": "JSONL stream", "domain": "mobility", "pk": "event_id", "time": "event_time"},
    "iot_sensor_telemetry": {"file": "iot_sensor_telemetry.jsonl", "format": "JSONL stream", "domain": "iot", "pk": "telemetry_id", "time": "event_time"},
    "industrial_measurements": {"file": "industrial_measurements.xml", "format": "XML", "domain": "industrial", "pk": "measurement_id", "time": "event_time"},
    "climate_environment": {"file": "climate_environment.csv", "format": "CSV", "domain": "climate", "pk": "observation_id", "time": "observed_at"},
    "spatial_assets": {"file": "spatial_assets.geojson", "format": "GeoJSON", "domain": "geospatial", "pk": "asset_id"},
    "analytical_evaluation": {"file": "analytical_evaluation.csv", "format": "CSV", "domain": "evaluation", "pk": "evaluation_id", "time": "evaluation_time"},
    "governance_access_audit": {"file": "governance_access_audit.jsonl", "format": "JSONL", "domain": "governance", "pk": "audit_id", "time": "event_time"},
}

_CATALOG_FALLBACK: Dict[str, Dict[str, Any]] = {
    "zones": {"description": "Zone reference and centroids", "classification": "internal", "tags": ["zone", "geography"]},
    "sites": {"description": "Operational site reference and coordinates", "classification": "internal", "tags": ["site", "infrastructure"]},
    "vehicles": {"description": "Fleet reference and capacity", "classification": "internal", "tags": ["vehicle", "fleet"]},
    "sensors": {"description": "Sensor specifications and expected ranges", "classification": "internal", "tags": ["sensor", "reference"]},
}


def _portal_dataset_type(dataset_id: str) -> str:
    fmt = PACK_SPECS[dataset_id]["format"]
    if fmt == "GeoJSON":
        return "vector"
    if fmt in {"JSONL", "JSONL stream"}:
        return "streaming"
    return "tabular"


def resolve_pack_root(root: str | Path) -> Path:
    """Resolve a pack directory without accepting arbitrary child paths."""

    candidate = Path(root).expanduser().resolve()
    if (candidate / "raw").is_dir():
        return candidate
    nested = candidate / "verdatrace_data_pack"
    if (nested / "raw").is_dir():
        return nested
    raise FileNotFoundError(f"cohesive pack raw directory was not found under {candidate}")


def ingest_and_profile_file(path: str | Path, *, allowed_root: str | Path, dataset_id: Optional[str] = None, preview_limit: int = 300) -> Dict[str, Any]:
    """Generic upload hook for supported files.

    It detects the existing ingestion format, profiles a bounded sample while
    counting the full stream, and returns a catalog-ready manifest. A caller can
    then attach domain-specific rules or register the result without adding a
    dataset-specific frontend page.
    """

    source = Path(path).resolve()
    identifier = dataset_id or source.stem.lower().replace("-", "_")
    suffix = source.suffix.lower()
    format_name = {".csv": "CSV", ".json": "JSON", ".ndjson": "JSONL", ".geojson": "GeoJSON", ".xml": "XML"}.get(suffix, suffix.lstrip(".").upper())
    sample: List[Dict[str, Any]] = []
    count = 0
    for row in iter_records(source, allowed_roots=[allowed_root]):
        count += 1
        if len(sample) < preview_limit:
            sample.append(row)
    profile = profile_dataset(sample, dataset_id=identifier, name=identifier.replace("_", " ").title(), source_format=format_name)
    manifest = {"dataset_id": identifier, "dataset_name": profile.name, "provider": "not_provided", "source_format": format_name, "input_size": source.stat().st_size, "record_count": count, "geometry_types": _geometry_types(sample), "crs": "EPSG:4326" if format_name == "GeoJSON" else None, "bounding_box": _bounds(sample), "fixture": None, "ingestion_timestamp": datetime.now(timezone.utc).isoformat(), "checksum_sha256": _sha256(source), "source_system": "local upload", "schema_version": "verdatrace_upload_v1", "ingestion_status": "succeeded"}
    return {"manifest": manifest, "profile": to_dict(profile), "preview": sample, "next_steps": ["apply configured quality rules", "infer domain from profile evidence", "register the catalog entry", "run the shared analysis/evaluation/visualization stages"]}


def _raw_path(root: Path, dataset_id: str) -> Path:
    spec = PACK_SPECS[dataset_id]
    path = (root / "raw" / spec["file"]).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError(f"missing cohesive pack source for {dataset_id}: {spec['file']}")
    return path


def _as_number(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _normalize_xml_record(element: ET.Element) -> Dict[str, Any]:
    raw = {child.tag: child.text for child in element}
    record: Dict[str, Any] = {"measurement_id": element.attrib.get("measurement_id"), **raw}
    aliases = {"SiteID": "site_id", "SensorID": "sensor_id", "Timestamp": "event_time", "Metric": "metric", "Unit": "unit", "Value": "value", "CalibrationDate": "calibration_date", "EquipmentState": "equipment_state"}
    for source, target in aliases.items():
        if source in raw:
            record[target] = raw[source]
    if record.get("value") not in (None, ""):
        record["value"] = _as_number(record["value"])
    return record


def iter_pack_records(root: str | Path, dataset_id: str, *, max_records: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    """Stream normalized records from one pack source."""

    pack = resolve_pack_root(root)
    path = _raw_path(pack, dataset_id)
    fmt = PACK_SPECS[dataset_id]["format"]
    yielded = 0
    if fmt == "CSV":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield dict(row)
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
        return
    if fmt in {"JSONL", "JSONL stream"}:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at line {line_number} in {path.name}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL line {line_number} must contain an object")
                yield value
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
        return
    if fmt == "XML":
        for _, element in ET.iterparse(path, events=("end",)):
            if element.tag != "Measurement":
                continue
            yield _normalize_xml_record(element)
            yielded += 1
            element.clear()
            if max_records is not None and yielded >= max_records:
                return
        return
    if fmt == "GeoJSON":
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
            raise ValueError("spatial_assets must be a GeoJSON FeatureCollection")
        for index, feature in enumerate(value["features"]):
            if not isinstance(feature, dict):
                raise ValueError(f"GeoJSON feature {index} must be an object")
            properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            record = dict(properties)
            record["asset_id"] = record.get("asset_id") or feature.get("id") or index
            record["feature_id"] = feature.get("id") or record["asset_id"]
            record["geometry"] = feature.get("geometry")
            geometry = record.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") == "Point" and isinstance(geometry.get("coordinates"), list) and len(geometry["coordinates"]) >= 2:
                record["longitude"], record["latitude"] = geometry["coordinates"][:2]
            record["crs"] = "EPSG:4326"
            yield record
            yielded += 1
            if max_records is not None and yielded >= max_records:
                return
        return
    raise ValueError(f"unsupported pack format: {fmt}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geometry_types(records: Sequence[Mapping[str, Any]]) -> List[str]:
    return sorted({str(row["geometry"].get("type")) for row in records if isinstance(row.get("geometry"), dict) and row["geometry"].get("type")})


def _bounds(records: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
    points: List[Tuple[float, float]] = []
    for row in records:
        lat, lon = _as_number(row.get("latitude")), _as_number(row.get("longitude"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            points.append((lat, lon))
            continue
        geometry = row.get("geometry")
        if isinstance(geometry, dict):
            coords = geometry.get("coordinates")
            stack = [coords] if coords is not None else []
            while stack:
                value = stack.pop()
                if isinstance(value, (list, tuple)) and len(value) >= 2 and all(_as_number(x) is not None for x in value[:2]):
                    lon_value, lat_value = float(value[0]), float(value[1])
                    if -90 <= lat_value <= 90 and -180 <= lon_value <= 180:
                        points.append((lat_value, lon_value))
                elif isinstance(value, (list, tuple)):
                    stack.extend(value)
    if not points:
        return None
    lats, lons = zip(*points)
    return {"min_latitude": min(lats), "min_longitude": min(lons), "max_latitude": max(lats), "max_longitude": max(lons)}


def _profile(sample: Sequence[Dict[str, Any]], dataset_id: str, row_count: int) -> DatasetProfile:
    if not sample:
        return DatasetProfile(dataset_id=dataset_id, name=dataset_id, row_count=0, source_format=PACK_SPECS[dataset_id]["format"], fields=[], categories=[], category_confidence={}, category_evidence={})
    profile = profile_dataset(sample, dataset_id=dataset_id, name=dataset_id.replace("_", " ").title(), source_format=PACK_SPECS[dataset_id]["format"])
    # profile_dataset is the canonical semantic detector; only replace its bounded sample count.
    return DatasetProfile(dataset_id=profile.dataset_id, name=profile.name, row_count=row_count, source_format=profile.source_format, fields=profile.fields, categories=profile.categories, category_confidence=profile.category_confidence, category_evidence=profile.category_evidence, geographic_bounds=_bounds(sample), temporal_coverage=profile.temporal_coverage)


def _segment_intersects(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> bool:
    def orient(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 == 0 and on_segment(a, c, b):
        return True
    if o2 == 0 and on_segment(a, d, b):
        return True
    if o3 == 0 and on_segment(c, a, d):
        return True
    if o4 == 0 and on_segment(c, b, d):
        return True
    return o1 * o2 < 0 and o3 * o4 < 0


def _polygon_self_intersects(geometry: Mapping[str, Any]) -> bool:
    if geometry.get("type") != "Polygon":
        return False
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return False
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < 4:
            continue
        segments = list(zip(ring, ring[1:]))
        for i, (a, b) in enumerate(segments):
            for j, (c, d) in enumerate(segments):
                if j <= i + 1 or (i == 0 and j == len(segments) - 1):
                    continue
                if all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in (a, b, c, d)) and _segment_intersects(a, b, c, d):
                    return True
    return False


def _finding(issue: str, count: int, dimension: str, field: Optional[str], rule: str, severity: str = "error") -> Dict[str, Any]:
    return {
        "issue": issue,
        "count": int(count),
        "quality_dimension": dimension,
        "field": field,
        "rule": rule,
        "expected_condition": rule,
        "observed_examples": None,
        "remediation_status": "quarantined" if severity == "error" else "review",
        "severity": severity,
    }


def _quality_scores(row_count: int, findings: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    penalties: Dict[str, int] = defaultdict(int)
    for finding in findings:
        penalties[str(finding["quality_dimension"])] += int(finding.get("count") or 0)
    dimensions = {
        "completeness": "completeness",
        "validity": "range",
        "uniqueness": "uniqueness",
        "consistency": "domain",
        "referential_integrity": "referential",
        "geometry_quality": "geometry",
        "sensor_quality": "sensor_quality",
        "freshness": "freshness",
    }
    scores = {key: round(max(0.0, 100.0 * (1.0 - penalties.get(rule, 0) / max(row_count, 1))), 2) for key, rule in dimensions.items()}
    # Dimensions without applicable findings remain 100; overall is an auditable mean.
    scores["overall"] = round(sum(scores.values()) / len(scores), 2)
    return scores


def _quality_for_dataset(root: Path, dataset_id: str, sensors: Mapping[str, Mapping[str, Any]], zones: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    row_count = 0
    ids: Counter[str] = Counter()
    if dataset_id == "logistics_shipments":
        missing_dropoff = negative_weight = invalid_status = zero_duration = 0
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("shipment_id"))] += 1
            missing_dropoff += not bool(row.get("dropoff_site_id"))
            negative_weight += (_as_number(row.get("weight_kg")) is not None and _as_number(row.get("weight_kg")) <= 0)
            invalid_status += row.get("status") not in {"created", "assigned", "picked_up", "delivered", "cancelled"}
            zero_duration += (_as_number(row.get("actual_duration_min")) is not None and _as_number(row.get("actual_duration_min")) <= 0)
        findings += [_finding("missing dropoff_site_id", missing_dropoff, "completeness", "dropoff_site_id", "dropoff_site_id is populated"), _finding("negative weight_kg", negative_weight, "range", "weight_kg", "weight_kg > 0"), _finding("invalid status DELIVERD", invalid_status, "domain", "status", "status is one of created|assigned|picked_up|delivered|cancelled"), _finding("zero actual_duration_min", zero_duration, "range", "actual_duration_min", "actual_duration_min > 0"), _finding("duplicate shipment_id injected", sum(max(0, count - 1) for count in ids.values()), "uniqueness", "shipment_id", "shipment_id is unique")]
    elif dataset_id == "mobility_stream":
        speed = missing_vehicle = invalid_coordinates = swapped = 0
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("event_id"))] += 1
            value = _as_number(row.get("speed_kph")); speed += value is not None and value > 180
            missing_vehicle += not bool(row.get("vehicle_id"))
            lat, lon = _as_number(row.get("latitude")), _as_number(row.get("longitude"))
            invalid_coordinates += lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180)
            centroid = (zones or {}).get(str(row.get("zone_id")))
            if centroid and lat is not None and lon is not None:
                expected_lat, expected_lon = _as_number(centroid.get("centroid_lat")), _as_number(centroid.get("centroid_lon"))
                original_distance = (lat - expected_lat) ** 2 + (lon - expected_lon) ** 2 if expected_lat is not None and expected_lon is not None else math.inf
                swapped_distance = (lon - expected_lat) ** 2 + (lat - expected_lon) ** 2 if expected_lat is not None and expected_lon is not None else math.inf
                swapped += swapped_distance < original_distance and original_distance - swapped_distance > 0.05
        findings += [_finding("unrealistic speed > 180 kph", speed, "range", "speed_kph", "speed_kph <= 180"), _finding("coordinate swap anomalies", swapped, "geometry", "latitude/longitude", "coordinates fit the expected Egypt extent", "warning"), _finding("missing vehicle_id", missing_vehicle, "completeness", "vehicle_id", "vehicle_id is populated"), _finding("duplicate event_id", sum(max(0, count - 1) for count in ids.values()), "uniqueness", "event_id", "event_id is unique"), _finding("invalid coordinates", invalid_coordinates, "geometry", "latitude/longitude", "valid WGS84 coordinates")]
    elif dataset_id == "iot_sensor_telemetry":
        null_value = out_of_range = mismatch = unknown = low_battery = 0
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("telemetry_id"))] += 1
            sid = str(row.get("sensor_id")); spec = sensors.get(sid)
            value = _as_number(row.get("value")); null_value += value is None
            unknown += spec is None
            if spec and value is not None:
                out_of_range += value < (_as_number(spec.get("expected_min")) or -math.inf) or value > (_as_number(spec.get("expected_max")) or math.inf)
                mismatch += row.get("unit") != spec.get("expected_unit")
            low_battery += (_as_number(row.get("battery_pct")) is not None and _as_number(row.get("battery_pct")) < 20)
        findings += [_finding("out-of-range sensor value", out_of_range, "range", "value", "value is within sensor expected_min/expected_max"), _finding("unit mismatch", mismatch, "sensor_quality", "unit", "unit matches sensors.expected_unit"), _finding("null sensor value", null_value, "completeness", "value", "value is populated"), _finding("unknown sensor_id", unknown, "referential_integrity", "sensor_id", "sensor_id exists in sensors.csv"), _finding("low battery", low_battery, "sensor_quality", "battery_pct", "battery_pct >= 20", "warning")]
    elif dataset_id == "industrial_measurements":
        unknown_unit = extreme = missing_calibration = 0; known_units = {"C", "pct", "ppm", "kPa", "ug/m3", "mm/s"}
        thresholds = {"pressure_kpa": (0, 400), "temperature_c": (-20, 60), "humidity_pct": (0, 100), "co2_ppm": (0, 10000), "pm25_ugm3": (0, 500), "vibration_mm_s": (0, 80)}
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("measurement_id"))] += 1
            unknown_unit += row.get("unit") not in known_units
            value = _as_number(row.get("value")); bounds = thresholds.get(str(row.get("metric")))
            extreme += value is not None and bounds is not None and not (bounds[0] <= value <= bounds[1])
            missing_calibration += not bool(row.get("calibration_date"))
        findings += [_finding("unknown unit", unknown_unit, "sensor_quality", "unit", "unit is a known measurement unit"), _finding("extreme value", extreme, "range", "value", "metric-specific expected range"), _finding("missing calibration date", missing_calibration, "completeness", "calibration_date", "controlled measurements have calibration dates")]
    elif dataset_id == "climate_environment":
        humidity = missing_temp = negative_precip = 0
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("observation_id"))] += 1
            humidity += (_as_number(row.get("humidity_pct")) is not None and _as_number(row.get("humidity_pct")) > 100)
            missing_temp += row.get("temperature_c") in (None, "")
            negative_precip += (_as_number(row.get("precipitation_mm")) is not None and _as_number(row.get("precipitation_mm")) < 0)
        findings += [_finding("humidity > 100", humidity, "range", "humidity_pct", "humidity_pct is between 0 and 100"), _finding("missing temperature_c", missing_temp, "completeness", "temperature_c", "temperature_c is populated"), _finding("negative precipitation", negative_precip, "range", "precipitation_mm", "precipitation_mm >= 0")]
    elif dataset_id == "spatial_assets":
        null_geometry = invalid_geometry = self_intersection = 0
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get("asset_id"))] += 1
            geometry = row.get("geometry")
            null_geometry += geometry is None
            if isinstance(geometry, dict):
                coordinates = geometry.get("coordinates")
                malformed = geometry.get("type") not in {"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"} or coordinates is None
                invalid_geometry += malformed
                self_intersection += _polygon_self_intersects(geometry)
            else:
                invalid_geometry += geometry is not None
        findings += [_finding("null geometry", null_geometry, "geometry", "geometry", "geometry is non-null"), _finding("invalid geometry", invalid_geometry, "geometry", "geometry", "GeoJSON geometry is structurally valid"), _finding("self-intersecting polygons", self_intersection, "geometry", "geometry", "polygon rings do not self-intersect")]
    else:
        for row in iter_pack_records(root, dataset_id):
            row_count += 1; ids[str(row.get(PACK_SPECS[dataset_id]["pk"]))] += 1
    findings = [item for item in findings if item["count"] > 0]
    scores = _quality_scores(row_count, findings)
    status = "failed" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "passed")
    return {"dataset_id": dataset_id, "total_rows": row_count, "valid_rows": max(0, row_count - sum(int(item["count"]) for item in findings if item["severity"] == "error")), "score": scores["overall"], "status": status, "issues": findings, "metrics": {"quality_dimensions": scores, "issue_count": len(findings), "error_occurrences": sum(item["count"] for item in findings if item["severity"] == "error"), "warning_occurrences": sum(item["count"] for item in findings if item["severity"] == "warning"), "duplicate_rows": sum(max(0, count - 1) for count in ids.values())}}


def _expected_quality(root: Path) -> List[Dict[str, Any]]:
    path = root / "metadata" / "expected_quality_findings.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def compare_expected_findings(root: str | Path, detected: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Compare exact golden counts and report approximate targets transparently."""

    pack = resolve_pack_root(root)
    by_issue = {(str(dataset), str(issue)): int(item.get("count") or 0) for dataset, result in detected.items() for item in result.get("issues", []) for issue in [item.get("issue")]}
    comparison: List[Dict[str, Any]] = []
    for expected in _expected_quality(pack):
        raw = str(expected.get("expected_count", ""))
        approximate = raw.startswith("~")
        numeric = int(raw.lstrip("~")) if raw.lstrip("~").isdigit() else None
        actual = by_issue.get((expected.get("dataset", ""), expected.get("issue", "")), 0)
        passed = actual == numeric if numeric is not None and not approximate else (numeric is not None and abs(actual - numeric) <= max(10, numeric * 0.25))
        comparison.append({"dataset": expected.get("dataset"), "issue": expected.get("issue"), "expected_count": numeric, "detected_count": actual, "count_difference": None if numeric is None else actual - numeric, "validation_status": "passed" if passed else "review", "quality_dimension": expected.get("quality_dimension"), "approximate_target": approximate})
    return comparison


def _read_catalog(root: Path) -> Dict[str, Dict[str, Any]]:
    path = root / "metadata" / "dataset_catalog.csv"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["dataset_name"]: row for row in csv.DictReader(handle)}


def _read_lineage(root: Path) -> List[Dict[str, Any]]:
    path = root / "metadata" / "lineage_edges.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_visualization_metadata(root: Path) -> Dict[str, Dict[str, Any]]:
    path = root / "metadata" / "visualization_recommendations.json"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    return {str(item.get("dataset")): item for item in values if isinstance(item, dict)}


def _read_rbac(root: Path) -> List[Dict[str, Any]]:
    path = root / "metadata" / "rbac_policy.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def rbac_allows(policy: Sequence[Mapping[str, Any]], *, role: str, resource: str, action: str) -> bool:
    """Evaluate the pack's least-privilege policy without granting defaults."""

    for rule in policy:
        if str(rule.get("role")) != role or not fnmatch(resource, str(rule.get("resource_pattern", "*"))):
            continue
        actions = {item.strip().upper() for item in str(rule.get("actions", "")).split("|")}
        if action.upper() in actions:
            return str(rule.get("allowed", "False")).strip().lower() == "true"
    return False


def _aggregate_pack(root: Path, sensors: Mapping[str, Mapping[str, Any]], sites: Mapping[str, Mapping[str, Any]], vehicles: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    zones: Dict[str, Dict[str, Any]] = {}
    for row in iter_pack_records(root, "zones"):
        zones[str(row["zone_id"])] = {**row, "site_count": 0, "active_site_count": 0, "shipment_count": 0, "delivered_shipments": 0, "cancelled_shipments": 0, "durations": [], "distance_km": 0.0, "weight_kg": 0.0, "sla_breaches": 0, "express_shipments": 0, "temperature_controlled_shipments": 0, "mobility_events": 0, "speeds": [], "sensor_count": 0, "sensor_anomalies": 0, "telemetry_count": 0, "climate_count": 0, "temperature": [], "humidity": [], "pm25": [], "precipitation": [], "visibility": [], "asset_count": 0, "risk_asset_count": 0, "geometry_issues": 0}
    for row in sites.values():
        zone = zones.get(str(row.get("zone_id")))
        if zone:
            zone["site_count"] += 1; zone["active_site_count"] += str(row.get("active")).lower() == "true"
    for row in iter_pack_records(root, "logistics_shipments"):
        site = sites.get(str(row.get("pickup_site_id"))); zone = zones.get(str(site.get("zone_id")) if site else "")
        if not zone: continue
        zone["shipment_count"] += 1; zone["delivered_shipments"] += row.get("status") == "delivered"; zone["cancelled_shipments"] += row.get("status") == "cancelled"; zone["sla_breaches"] += (_as_number(row.get("actual_duration_min")) or 0) > (_as_number(row.get("planned_duration_min")) or math.inf); zone["express_shipments"] += row.get("priority") == "express"; zone["temperature_controlled_shipments"] += str(row.get("temperature_controlled")).lower() == "true"; duration = _as_number(row.get("actual_duration_min")); distance = _as_number(row.get("distance_km")); weight = _as_number(row.get("weight_kg")); zone["durations"].append(duration) if duration is not None else None; zone["distance_km"] += distance or 0; zone["weight_kg"] += weight or 0
    for row in iter_pack_records(root, "mobility_stream"):
        zone = zones.get(str(row.get("zone_id")))
        if zone:
            zone["mobility_events"] += 1; speed = _as_number(row.get("speed_kph")); zone["speeds"].append(speed) if speed is not None and speed <= 180 else None
    for row in iter_pack_records(root, "iot_sensor_telemetry"):
        zone = zones.get(str(row.get("zone_id")))
        if zone:
            zone["telemetry_count"] += 1; spec = sensors.get(str(row.get("sensor_id"))); value = _as_number(row.get("value")); bad = value is None or spec is None or (spec and (value < (_as_number(spec.get("expected_min")) or -math.inf) or value > (_as_number(spec.get("expected_max")) or math.inf))) or (spec and row.get("unit") != spec.get("expected_unit")); zone["sensor_anomalies"] += bool(bad)
    for row in iter_pack_records(root, "climate_environment"):
        zone = zones.get(str(row.get("zone_id")))
        if zone:
            zone["climate_count"] += 1
            for target, field in (("temperature", "temperature_c"), ("humidity", "humidity_pct"), ("pm25", "pm25_ugm3"), ("precipitation", "precipitation_mm"), ("visibility", "visibility_km")):
                value = _as_number(row.get(field)); zone[target].append(value) if value is not None else None
    for row in iter_pack_records(root, "spatial_assets"):
        zone = zones.get(str(row.get("zone_id")))
        if zone:
            zone["asset_count"] += 1; zone["risk_asset_count"] += row.get("asset_type") == "risk_zone"; zone["geometry_issues"] += row.get("geometry") is None or (isinstance(row.get("geometry"), dict) and _polygon_self_intersects(row["geometry"]))

    def mean(values: Sequence[float]) -> Optional[float]: return round(statistics.mean(values), 2) if values else None
    def pct(part: int, whole: int) -> Optional[float]: return round(100 * part / whole, 2) if whole else None
    zone_rows: List[Dict[str, Any]] = []
    for zone_id, z in zones.items():
        avg_speed = mean(z["speeds"]); avg_pm25 = mean(z["pm25"]); avg_temp = mean(z["temperature"]); avg_precip = mean(z["precipitation"]); avg_visibility = mean(z["visibility"])
        pm_component = min(100.0, (avg_pm25 or 0) / 150 * 100); extreme_temp_component = 100.0 * sum(t < 5 or t > 40 for t in z["temperature"]) / max(len(z["temperature"]), 1); precip_component = min(100.0, (avg_precip or 0) / 50 * 100); visibility_component = min(100.0, max(0.0, 10 - (avg_visibility or 10)) / 10 * 100); environmental_risk = round(0.5 * pm_component + 0.2 * extreme_temp_component + 0.2 * precip_component + 0.1 * visibility_component, 2)
        delivery_success = pct(z["delivered_shipments"], z["shipment_count"]); sla_compliance = 100 - (pct(z["sla_breaches"], z["shipment_count"]) or 0); mobility_score = min(100.0, (avg_speed or 0) / 60 * 100); infra_score = min(100.0, 100 * z["active_site_count"] / max(z["site_count"], 1)); sensor_quality = 100 - (pct(z["sensor_anomalies"], z["telemetry_count"]) or 0); data_quality = round((sensor_quality + max(0, 100 - z["geometry_issues"] / max(z["asset_count"], 1) * 100)) / 2, 2); logistics_score = round(0.6 * (delivery_success or 0) + 0.4 * sla_compliance, 2); risk_penalty = round(0.15 * environmental_risk + (10 if z["risk_asset_count"] else 0), 2); suitability = round(max(0.0, 0.3 * mobility_score + 0.2 * logistics_score + 0.2 * infra_score + 0.15 * (100 - environmental_risk) + 0.1 * data_quality + 0.05 * min(100.0, 100 * z["asset_count"] / 10) - risk_penalty), 2)
        recommendation = "recommended" if suitability >= 70 else ("review" if suitability >= 50 else "avoid")
        positives = (["strong mobility accessibility"] if mobility_score >= 60 else []) + (["high delivery performance"] if logistics_score >= 70 else []) + (["active infrastructure coverage"] if infra_score >= 70 else [])
        negatives = (["elevated environmental risk"] if environmental_risk >= 50 else []) + (["sensor anomalies affect confidence"] if sensor_quality < 90 else []) + (["risk-zone geometry overlap"] if z["risk_asset_count"] else [])
        zone_rows.append({"zone_id": zone_id, "city": z.get("city"), "zone_name": z.get("zone_name"), "logistics": {"shipment_count": z["shipment_count"], "delivered_shipments": z["delivered_shipments"], "cancelled_shipments": z["cancelled_shipments"], "delivery_success_pct": delivery_success, "sla_compliance_pct": round(sla_compliance, 2), "average_delivery_time_min": mean(z["durations"]), "distance_km": round(z["distance_km"], 2), "weight_kg": round(z["weight_kg"], 2), "express_pct": pct(z["express_shipments"], z["shipment_count"]), "temperature_controlled_pct": pct(z["temperature_controlled_shipments"], z["shipment_count"])}, "mobility": {"event_count": z["mobility_events"], "average_speed_kph": avg_speed, "median_speed_kph": round(statistics.median(z["speeds"]), 2) if z["speeds"] else None, "p95_speed_kph": round(sorted(z["speeds"])[int(0.95 * (len(z["speeds"]) - 1))], 2) if z["speeds"] else None, "mobility_score": round(mobility_score, 2)}, "sensors": {"telemetry_count": z["telemetry_count"], "anomaly_count": z["sensor_anomalies"], "anomaly_pct": pct(z["sensor_anomalies"], z["telemetry_count"])}, "environment": {"observation_count": z["climate_count"], "average_temperature_c": avg_temp, "average_humidity_pct": mean(z["humidity"]), "average_pm25_ugm3": avg_pm25, "average_precipitation_mm": avg_precip, "average_visibility_km": avg_visibility, "environmental_risk_score": environmental_risk, "formula": "0.50 PM2.5 + 0.20 extreme-temperature + 0.20 precipitation + 0.10 low-visibility"}, "gis": {"asset_count": z["asset_count"], "risk_asset_count": z["risk_asset_count"], "geometry_issue_count": z["geometry_issues"]}, "scores": {"logistics_efficiency": logistics_score, "infrastructure_readiness": round(infra_score, 2), "data_quality": data_quality, "suitability": suitability, "risk_penalty": risk_penalty}, "recommendation": recommendation, "confidence": round(max(0.0, min(1.0, data_quality / 100)), 3), "explanation": {"positive_drivers": positives, "negative_drivers": negatives, "evidence": {"shipments": z["shipment_count"], "mobility_events": z["mobility_events"], "telemetry_records": z["telemetry_count"], "climate_observations": z["climate_count"], "gis_features": z["asset_count"]}, "quality_impact": "Confidence is derived from sensor and geometry quality; no synthetic confidence values are added."}})

    site_rows: List[Dict[str, Any]] = []
    sensor_rollup: Dict[str, Dict[str, Any]] = {sid: {"telemetry_count": 0, "anomaly_count": 0, "missing_count": 0, "unit_mismatch_count": 0, "low_battery_count": 0, "latest": None} for sid in sensors}
    for row in iter_pack_records(root, "iot_sensor_telemetry"):
        sid = str(row.get("sensor_id")); target = sensor_rollup.get(sid)
        if target is None: continue
        target["telemetry_count"] += 1; target["missing_count"] += _as_number(row.get("value")) is None; target["low_battery_count"] += (_as_number(row.get("battery_pct")) or 100) < 20; spec = sensors[sid]; value = _as_number(row.get("value")); target["unit_mismatch_count"] += row.get("unit") != spec.get("expected_unit"); target["anomaly_count"] += value is None or row.get("unit") != spec.get("expected_unit") or (value is not None and (value < (_as_number(spec.get("expected_min")) or -math.inf) or value > (_as_number(spec.get("expected_max")) or math.inf))); target["latest"] = row.get("event_time") if target["latest"] is None or str(row.get("event_time")) > str(target["latest"]) else target["latest"]
    for sid, spec in sensors.items():
        roll = sensor_rollup[sid]; site = sites.get(str(spec.get("site_id"))); score = round(max(0.0, 100 - 100 * roll["anomaly_count"] / max(roll["telemetry_count"], 1)), 2); site_rows.append({"sensor_id": sid, "site_id": spec.get("site_id"), "zone_id": spec.get("zone_id"), "sensor_type": spec.get("sensor_type"), "expected_unit": spec.get("expected_unit"), "telemetry_count": roll["telemetry_count"], "anomaly_rate_pct": round(100 * roll["anomaly_count"] / max(roll["telemetry_count"], 1), 2), "missing_value_rate_pct": round(100 * roll["missing_count"] / max(roll["telemetry_count"], 1), 2), "unit_mismatch_count": roll["unit_mismatch_count"], "low_battery_count": roll["low_battery_count"], "latest_measurement_time": roll["latest"], "reliability_score": score, "status": "healthy" if score >= 90 else ("review" if score >= 70 else "failed")})
    site360 = [{"site_id": sid, "zone_id": row.get("zone_id"), "site_type": row.get("site_type"), "latitude": _as_number(row.get("latitude")), "longitude": _as_number(row.get("longitude")), "active": str(row.get("active")).lower() == "true", "sensor_count": sum(1 for item in site_rows if item["site_id"] == sid), "sensor_anomaly_rate_pct": round(statistics.mean([item["anomaly_rate_pct"] for item in site_rows if item["site_id"] == sid]), 2) if any(item["site_id"] == sid for item in site_rows) else None} for sid, row in sites.items()]
    vehicle_rollup: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"shipments": 0, "delivered": 0, "weight": 0.0, "mobility_events": 0, "speeds": []})
    for row in iter_pack_records(root, "logistics_shipments"):
        target = vehicle_rollup[str(row.get("vehicle_id"))]; target["shipments"] += 1; target["delivered"] += row.get("status") == "delivered"; target["weight"] += _as_number(row.get("weight_kg")) or 0
    for row in iter_pack_records(root, "mobility_stream"):
        target = vehicle_rollup[str(row.get("vehicle_id"))]; target["mobility_events"] += 1; speed = _as_number(row.get("speed_kph")); target["speeds"].append(speed) if speed is not None and speed <= 180 else None
    vehicle360 = []
    for vid, row in vehicles.items():
        agg = vehicle_rollup[vid]; vehicle360.append({"vehicle_id": vid, "vehicle_type": row.get("vehicle_type"), "home_zone_id": row.get("home_zone_id"), "capacity_kg": _as_number(row.get("capacity_kg")), "logistics_volume": agg["shipments"], "delivered_shipments": agg["delivered"], "gps_event_count": agg["mobility_events"], "average_speed_kph": round(statistics.mean(agg["speeds"]), 2) if agg["speeds"] else None, "estimated_utilization_pct": round(100 * agg["weight"] / max(agg["shipments"] * (_as_number(row.get("capacity_kg")) or 1), 1), 2) if agg["shipments"] else None})
    return {"zone_360": zone_rows, "site_360": site360, "vehicle_360": vehicle360, "sensor_health": site_rows}


def _executive_kpis(aggregates: Mapping[str, Any], quality: Mapping[str, Any]) -> List[Dict[str, Any]]:
    zones = list(aggregates["zone_360"]); shipments = sum(int(row["logistics"]["shipment_count"]) for row in zones); delivered = sum(int(row["logistics"]["delivered_shipments"]) for row in zones); mobility = sum(int(row["mobility"]["event_count"]) for row in zones); sensors = list(aggregates["sensor_health"]); recommended = sum(row["recommendation"] == "recommended" for row in zones); high_risk = sum(row["environment"]["environmental_risk_score"] >= 50 for row in zones); quality_score = quality.get("overall_score")
    def kpi(identifier: str, label: str, value: Optional[float], unit: str, description: str, metric: str, fields: Sequence[str]) -> Dict[str, Any]:
        return {"id": identifier, "label": label, "value": value, "unit": unit, "status": None, "description": description, "source_metric": metric, "analysis_stage": "curated_zone_360", "fields_used": list(fields), "calculation_description": description}
    return [kpi("total_shipments", "Total Shipments", shipments, "records", "Count of ingested logistics shipment records.", "logistics.shipment_count", ["shipment_id"]), kpi("delivery_success", "Delivery Success", round(100 * delivered / max(shipments, 1), 2), "%", "Delivered shipments divided by all shipments.", "logistics.delivery_success_pct", ["status"]), kpi("mobility_events", "Mobility Events", mobility, "events", "Count of streamed GPS events.", "mobility.event_count", ["event_id"]), kpi("active_sensors", "Sensors with Telemetry", sum(item["telemetry_count"] > 0 for item in sensors), "sensors", "Sensors with at least one telemetry record.", "sensor_health.telemetry_count", ["sensor_id", "telemetry_id"]), kpi("sensor_health", "Sensor Health", round(statistics.mean([item["reliability_score"] for item in sensors]), 2) if sensors else None, "%", "Mean reliability score from range, null, unit, and battery checks.", "sensor_health.reliability_score", ["value", "unit", "battery_pct"]), kpi("zones_recommended", "Recommended Zones", recommended, "zones", "Zones scoring at least 70 after configured risk penalty.", "zone_360.suitability", ["suitability", "risk_penalty"]), kpi("high_environmental_risk", "High Environmental Risk Zones", high_risk, "zones", "Zones with environmental risk score at least 50.", "zone_360.environmental_risk_score", ["pm25_ugm3", "temperature_c", "precipitation_mm", "visibility_km"]), kpi("overall_data_quality", "Overall Data Quality", quality_score, "%", "Mean of explainable quality dimensions across pack datasets.", "quality.overall", ["quality_dimensions"])]


def build_cohesive_payload(root: str | Path, *, preview_limit: int = 300) -> Dict[str, Any]:
    """Run the supplied pack through one governed, bounded platform flow."""

    started = time.perf_counter(); pack = resolve_pack_root(root); catalog = _read_catalog(pack); lineage_edges = _read_lineage(pack); viz_metadata = _read_visualization_metadata(pack); rbac = _read_rbac(pack)
    master: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for dataset_id in ("zones", "sites", "vehicles", "sensors"):
        master[dataset_id] = {str(row[PACK_SPECS[dataset_id]["pk"]]): row for row in iter_pack_records(pack, dataset_id)}
    detected_quality: Dict[str, Dict[str, Any]] = {}
    dataset_entries: List[Dict[str, Any]] = []
    for dataset_id, spec in PACK_SPECS.items():
        path = _raw_path(pack, dataset_id); sample: List[Dict[str, Any]] = []; count = 0; temporal_values: List[datetime] = []; observed_geometry_types: set[str] = set(); observed_bbox: Optional[Dict[str, float]] = None
        for row in iter_pack_records(pack, dataset_id):
            count += 1
            if len(sample) < preview_limit: sample.append(row)
            geometry = row.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type"):
                observed_geometry_types.add(str(geometry["type"]))
            if geometry is not None or row.get("latitude") is not None or row.get("longitude") is not None:
                current_bbox = _bounds([row])
                if current_bbox:
                    observed_bbox = current_bbox if observed_bbox is None else {
                        "min_latitude": min(observed_bbox["min_latitude"], current_bbox["min_latitude"]),
                        "min_longitude": min(observed_bbox["min_longitude"], current_bbox["min_longitude"]),
                        "max_latitude": max(observed_bbox["max_latitude"], current_bbox["max_latitude"]),
                        "max_longitude": max(observed_bbox["max_longitude"], current_bbox["max_longitude"]),
                    }
            if spec.get("time") and len(temporal_values) < 1000:
                parsed = _parse_time(row.get(spec["time"])); temporal_values.append(parsed) if parsed else None
        profile = _profile(sample, dataset_id, count); detected_quality[dataset_id] = _quality_for_dataset(pack, dataset_id, master["sensors"], master["zones"])
        quality = detected_quality[dataset_id]; evaluation = EvaluationReport(task="descriptive", eligible=quality["score"] >= 40 and count > 0, score=quality["score"], reasons=["records were ingested", "quality dimensions were computed from configured rules"], warnings=[item["issue"] for item in quality["issues"] if item["severity"] == "error"], checks={"has_rows": count > 0, "quality_acceptable": quality["score"] >= 40})
        visualization = recommend_visualizations(profile, evaluation)
        if dataset_id in viz_metadata:
            visualization_reason = viz_metadata[dataset_id].get("reason")
            if visualization_reason:
                visualization = visualization.__class__(dataset_type=visualization.dataset_type, eligible=visualization.eligible, recommended_visualizations=visualization.recommended_visualizations, warnings=visualization.warnings + ["Pack metadata: " + visualization_reason], unsupported_fields=visualization.unsupported_fields)
        retrieved = datetime.now(timezone.utc).isoformat(); manifest = DatasetManifest(dataset_id=dataset_id, dataset_name=catalog.get(dataset_id, {}).get("description") or dataset_id.replace("_", " ").title(), provider="VerdaTrace Cohesive Data Pack (synthetic)", source_format=spec["format"], dataset_type=spec["domain"], input_size=path.stat().st_size, record_count=count, geometry_types=sorted(observed_geometry_types), crs="EPSG:4326" if dataset_id == "spatial_assets" else None, bounding_box=observed_bbox, geographic_coverage="Egypt (synthetic Cairo, Alexandria, and related zones)", temporal_coverage={"start": min(temporal_values).isoformat(), "end": max(temporal_values).isoformat()} if temporal_values else None, license="not_provided", ingestion_timestamp=retrieved, processing_timestamp=datetime.now(timezone.utc).isoformat(), fixture=True, checksum_sha256=_sha256(path), source_system="VerdaTrace Cohesive Data Pack", schema_version="cohesive_pack_v1", ingestion_status="succeeded")
        lineage = [{"stage": "raw_ingestion", "input_ref": f"pack:{spec['file']}", "output_ref": f"raw:{dataset_id}", "operation": "stream_parse"}, {"stage": "quality", "input_ref": f"raw:{dataset_id}", "output_ref": f"quality:{dataset_id}", "operation": "configured_quality_rules"}, {"stage": "catalog", "input_ref": f"quality:{dataset_id}", "output_ref": f"catalog:{dataset_id}", "operation": "semantic_profile_and_classification"}, {"stage": "analysis", "input_ref": f"catalog:{dataset_id}", "output_ref": f"analysis:{dataset_id}", "operation": "domain_analytics"}, {"stage": "evaluation", "input_ref": f"analysis:{dataset_id}", "output_ref": f"evaluation:{dataset_id}", "operation": "suitability_readiness"}, {"stage": "visualization", "input_ref": f"evaluation:{dataset_id}", "output_ref": f"visualization:{dataset_id}", "operation": "deterministic_recommendations"}, {"stage": "governance", "input_ref": f"visualization:{dataset_id}", "output_ref": f"governance:{dataset_id}", "operation": "policy_and_audit_metadata"}]
        outcome_payload = {
            "profile": to_dict(profile),
            "quality": quality,
            "analysis": {
                "result_type": spec["domain"] + "_summary",
                "computed_values": {"record_count": count, "source_sha256": _sha256(path)},
                "dimensions": [], "metrics": [], "units": {}, "warnings": [],
                "provenance": {"source_file": spec["file"]},
                "quality_reference": f"quality:{dataset_id}",
                "analysis_metadata": {"streaming": spec["format"] in {"JSONL", "JSONL stream", "XML"}},
            },
            "evaluation": to_dict(evaluation),
            "visualization": to_dict(visualization),
            "governance": {
                "owner": "not_provided", "source": "VerdaTrace Cohesive Data Pack",
                "license": "not_provided",
                "classification": catalog.get(dataset_id, {}).get("classification", _CATALOG_FALLBACK.get(dataset_id, {}).get("classification", "internal")),
                "sensitivity": catalog.get(dataset_id, {}).get("classification", "not_provided"),
                "retention_policy": "not_provided",
                "lineage_edges": [edge for edge in lineage_edges if edge.get("source_dataset") == dataset_id or edge.get("target_dataset") == dataset_id],
            },
            "lineage": lineage,
            "audit_events": [],
            "manifest": to_dict(manifest),
            "executive_kpis": [],
            "processing": {
                "input_bytes": path.stat().st_size, "output_bytes": None,
                "records_processed": count, "records_valid": quality["valid_rows"],
                "records_repaired": 0, "records_quarantined": quality["metrics"]["error_occurrences"],
                "records_rejected": 0, "duration_seconds": None, "throughput_records_per_second": None,
            },
        }
        entry = {
            "id": "pack_" + dataset_id, "title": manifest.dataset_name, "domain": spec["domain"],
            "dataset_type": _portal_dataset_type(dataset_id), "fixture": True,
            "attribution": {"label": "VerdaTrace Cohesive Data Pack (synthetic)", "url": None, "license": "not_provided"},
            "records": sample,
            "preview": {"is_sample": len(sample) < count, "records_shown": len(sample), "record_count": count, "strategy": "head"},
            "outcome": outcome_payload,
        }
        dataset_entries.append(entry)
    aggregates = _aggregate_pack(pack, master["sensors"], master["sites"], master["vehicles"])
    # Attach domain metrics to the same per-dataset result contract so selecting
    # a dataset in the existing workspace exposes real derived values.
    zone_rows = aggregates["zone_360"]
    totals = {
        "logistics_shipments": {
            "total_shipments": sum(row["logistics"]["shipment_count"] for row in zone_rows),
            "delivered_shipments": sum(row["logistics"]["delivered_shipments"] for row in zone_rows),
            "cancelled_shipments": sum(row["logistics"]["cancelled_shipments"] for row in zone_rows),
            "delivery_success_pct": round(100 * sum(row["logistics"]["delivered_shipments"] for row in zone_rows) / max(sum(row["logistics"]["shipment_count"] for row in zone_rows), 1), 2),
            "average_delivery_time_min": round(sum((row["logistics"]["average_delivery_time_min"] or 0) * row["logistics"]["shipment_count"] for row in zone_rows) / max(sum(row["logistics"]["shipment_count"] for row in zone_rows), 1), 2),
        },
        "mobility_stream": {
            "event_count": sum(row["mobility"]["event_count"] for row in zone_rows),
            "average_speed_kph": round(sum((row["mobility"]["average_speed_kph"] or 0) * row["mobility"]["event_count"] for row in zone_rows) / max(sum(row["mobility"]["event_count"] for row in zone_rows), 1), 2),
            "active_vehicles": sum(1 for row in aggregates["vehicle_360"] if row["gps_event_count"] > 0),
        },
        "iot_sensor_telemetry": {
            "telemetry_count": sum(row["sensors"]["telemetry_count"] for row in zone_rows),
            "anomaly_count": sum(row["sensors"]["anomaly_count"] for row in zone_rows),
        },
        "climate_environment": {
            "observation_count": sum(row["environment"]["observation_count"] for row in zone_rows),
            "average_pm25_ugm3": round(sum((row["environment"]["average_pm25_ugm3"] or 0) * row["environment"]["observation_count"] for row in zone_rows) / max(sum(row["environment"]["observation_count"] for row in zone_rows), 1), 2),
            "average_temperature_c": round(sum((row["environment"]["average_temperature_c"] or 0) * row["environment"]["observation_count"] for row in zone_rows) / max(sum(row["environment"]["observation_count"] for row in zone_rows), 1), 2),
        },
        "spatial_assets": {
            "asset_count": sum(row["gis"]["asset_count"] for row in zone_rows),
            "risk_asset_count": sum(row["gis"]["risk_asset_count"] for row in zone_rows),
            "geometry_issue_count": sum(row["gis"]["geometry_issue_count"] for row in zone_rows),
        },
    }
    for entry in dataset_entries:
        pack_id = str(entry["id"])[5:]
        computed = entry["outcome"]["analysis"]["computed_values"]
        computed.update(totals.get(pack_id, {}))
        if pack_id == "iot_sensor_telemetry":
            computed["anomaly_pct"] = round(100 * computed["anomaly_count"] / max(computed["telemetry_count"], 1), 2)
        entry["outcome"]["analysis"]["metrics"] = sorted(computed)
    quality_dimensions = [result["score"] for result in detected_quality.values()]; quality_overall = round(statistics.mean(quality_dimensions), 2) if quality_dimensions else None
    expected_comparison = compare_expected_findings(pack, detected_quality)
    target_scores: Dict[str, List[float]] = defaultdict(list)
    target_recommendations: Counter[str] = Counter()
    for row in iter_pack_records(pack, "analytical_evaluation"):
        value = _as_number(row.get("overall_suitability_score"))
        if value is not None:
            target_scores[str(row.get("zone_id"))].append(value)
        if row.get("recommendation"):
            target_recommendations[str(row.get("recommendation"))] += 1
    aligned = [abs(statistics.mean(values) - next(zone["scores"]["suitability"] for zone in zone_rows if zone["zone_id"] == zone_id)) for zone_id, values in target_scores.items() if values and any(zone["zone_id"] == zone_id for zone in zone_rows)]
    evaluation_alignment = {"target_record_count": sum(len(values) for values in target_scores.values()), "target_recommendation_counts": dict(target_recommendations), "zone_mean_absolute_error": round(statistics.mean(aligned), 2) if aligned else None, "method": "mean supplied analytical_evaluation score per zone compared with independently derived Zone 360 suitability"}
    platform = {"schema_version": "verdatrace_cohesive_platform_v1", "source_pack": {"name": "VerdaTrace Cohesive Data Pack", "fixture": True, "license": "not_provided", "raw_data_policy": "Raw pack files are not committed; point --pack-root at the supplied retrieval directory.", "manifest": [dict(row) for row in csv.DictReader((pack / "manifest.csv").open("r", encoding="utf-8-sig"))] if (pack / "manifest.csv").is_file() else []}, "zone_360": aggregates["zone_360"], "site_360": aggregates["site_360"], "vehicle_360": aggregates["vehicle_360"], "sensor_health": aggregates["sensor_health"], "executive_kpis": _executive_kpis(aggregates, {"overall_score": quality_overall}), "quality_summary": {"overall_score": quality_overall, "datasets": detected_quality, "expected_findings_validation": expected_comparison}, "evaluation_alignment": evaluation_alignment, "lineage": {"edges": lineage_edges, "stage_sequence": ["raw_ingestion", "quality", "catalog", "analysis", "evaluation", "visualization", "governance"]}, "governance": {"rbac_policy": rbac, "audit_summary": _audit_summary(pack), "least_privilege": "Read-only executive access is separated from raw write and catalog mutation permissions."}, "recommendations": sorted(aggregates["zone_360"], key=lambda row: row["scores"]["suitability"], reverse=True)[:10], "processing": {"duration_seconds": round(time.perf_counter() - started, 3), "datasets_processed": len(dataset_entries), "raw_records_processed": sum(item["outcome"]["manifest"]["record_count"] for item in dataset_entries), "preview_strategy": f"head sample capped at {preview_limit} records per dataset"}}
    return {"schema_version": "verdatrace_portal_payload_v2", "generated_at": datetime.now(timezone.utc).isoformat(), "datasets": dataset_entries, "platform": platform}


def _audit_summary(root: Path) -> Dict[str, Any]:
    allowed = denied = 0; by_role: Counter[str] = Counter(); by_action: Counter[str] = Counter(); sample: List[Dict[str, Any]] = []
    for row in iter_pack_records(root, "governance_access_audit"):
        decision = str(row.get("decision", "")).upper(); allowed += decision == "ALLOW"; denied += decision == "DENY"; by_role[str(row.get("role"))] += 1; by_action[str(row.get("action"))] += 1
        if len(sample) < 25:
            sample.append({key: row.get(key) for key in ("audit_id", "event_time", "principal_id", "role", "dataset", "action", "decision", "reason", "request_id")})
    return {"records": allowed + denied, "allowed": allowed, "denied": denied, "by_role": dict(by_role), "by_action": dict(by_action), "sample": sample}
