"""Schema discovery and evidence-based dataset categorization."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import DatasetCategory, DatasetProfile, FieldProfile, SemanticType

NORMALIZE = re.compile(r"[^a-z0-9]+")

ALIASES: Dict[SemanticType, set[str]] = {
    SemanticType.IDENTIFIER: {"id", "event_id", "transaction_id", "trip_id", "shipment_id", "order_id"},
    SemanticType.LATITUDE: {"lat", "latitude", "pickup_latitude", "dropoff_latitude", "y"},
    SemanticType.LONGITUDE: {"lon", "lng", "long", "longitude", "pickup_longitude", "dropoff_longitude", "x"},
    SemanticType.GEOMETRY: {"geometry", "geom", "the_geom", "wkt"},
    SemanticType.CRS: {"crs", "epsg", "srid"},
    SemanticType.TIMESTAMP: {"timestamp", "event_timestamp", "datetime", "time", "ts", "observed_at", "recorded_at"},
    SemanticType.DATE: {"date", "event_date", "service_date"},
    SemanticType.TEMPERATURE: {"temp", "temperature", "temperature_c", "temperature_f", "air_temperature"},
    SemanticType.HUMIDITY: {"humidity", "humidity_pct", "relative_humidity"},
    SemanticType.PRESSURE: {"pressure", "pressure_hpa", "barometric_pressure"},
    SemanticType.CO: {"co", "co_ppm", "carbon_monoxide"},
    SemanticType.CO2: {"co2", "co2_ppm", "carbon_dioxide", "co2e_kg"},
    SemanticType.LPG: {"lpg", "lpg_ppm"},
    SemanticType.SMOKE: {"smoke", "smoke_ppm"},
    SemanticType.PARTICULATE_MATTER: {"pm", "pm1", "pm10", "pm2_5", "pm25", "particulate_matter"},
    SemanticType.RAINFALL: {"rain", "rainfall", "rainfall_mm", "precipitation", "precipitation_mm"},
    SemanticType.SOLAR_RADIATION: {"solar_radiation", "shortwave_radiation", "irradiance"},
    SemanticType.WIND: {"wind", "wind_speed", "wind_speed_kph", "wind_direction"},
    SemanticType.NDVI: {"ndvi"},
    SemanticType.LAND_SURFACE_TEMPERATURE: {"land_surface_temperature", "lst"},
    SemanticType.ELEVATION: {"elevation", "elevation_m", "altitude"},
    SemanticType.LAND_COVER: {"land_cover", "land_cover_class", "landuse"},
    SemanticType.DEVICE_ID: {"device_id", "sensor_id", "station_id"},
    SemanticType.VEHICLE_ID: {"vehicle_id", "vehicle", "fleet_id"},
    SemanticType.ROUTE: {"route", "route_id", "route_name", "trip_sequence"},
    SemanticType.SPEED: {"speed", "speed_kph", "speed_mph", "velocity"},
    SemanticType.HEADING: {"heading", "bearing", "course"},
    SemanticType.ORIGIN: {"origin", "origin_id", "pickup", "pickup_location", "source_location"},
    SemanticType.DESTINATION: {"destination", "destination_id", "dropoff", "dropoff_location"},
    SemanticType.DISTANCE: {"distance", "distance_km", "distance_miles", "trip_distance", "trip_distance_miles"},
    SemanticType.DURATION: {"duration", "duration_seconds", "trip_duration", "travel_time"},
}

SENSOR_SEMANTICS = {
    SemanticType.TEMPERATURE,
    SemanticType.HUMIDITY,
    SemanticType.PRESSURE,
    SemanticType.CO,
    SemanticType.CO2,
    SemanticType.LPG,
    SemanticType.SMOKE,
    SemanticType.PARTICULATE_MATTER,
    SemanticType.RAINFALL,
    SemanticType.SOLAR_RADIATION,
    SemanticType.WIND,
}

MOBILITY_SEMANTICS = {
    SemanticType.VEHICLE_ID,
    SemanticType.ROUTE,
    SemanticType.SPEED,
    SemanticType.HEADING,
    SemanticType.ORIGIN,
    SemanticType.DESTINATION,
    SemanticType.DISTANCE,
    SemanticType.DURATION,
}


def normalize_name(name: str) -> str:
    return NORMALIZE.sub("_", name.strip().lower()).strip("_")


def parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _numeric(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _base_type(values: Sequence[Any]) -> str:
    non_null = [value for value in values if value not in (None, "")]
    if not non_null:
        return "unknown"
    if all(isinstance(value, bool) or str(value).strip().lower() in {"true", "false"} for value in non_null):
        return "boolean"
    if sum(_numeric(value) is not None for value in non_null) / len(non_null) >= 0.9:
        return "number"
    if sum(parse_datetime(value) is not None for value in non_null) / len(non_null) >= 0.9:
        return "datetime"
    if all(isinstance(value, (dict, list)) for value in non_null):
        return "object"
    return "string"


def _semantic(name: str, values: Sequence[Any], data_type: str) -> Tuple[SemanticType, float, List[str]]:
    normalized = normalize_name(name)
    non_null = [value for value in values if value not in (None, "")]
    matched = next((semantic for semantic, aliases in ALIASES.items() if normalized in aliases), None)
    evidence: List[str] = []
    confidence = 0.0

    if matched is not None:
        evidence.append(f"field name matches the {matched.value} alias set")
        confidence = 0.72
        if matched in {SemanticType.LATITUDE, SemanticType.LONGITUDE}:
            numeric_values = [_numeric(value) for value in non_null]
            numeric_values = [value for value in numeric_values if value is not None]
            upper = 90 if matched == SemanticType.LATITUDE else 180
            if numeric_values and len(numeric_values) / max(len(non_null), 1) >= 0.8:
                in_range = sum(-upper <= value <= upper for value in numeric_values) / len(numeric_values)
                evidence.append(f"{in_range:.0%} of numeric values are within coordinate bounds")
                confidence = 0.96 if in_range >= 0.9 else 0.82
        elif matched in {SemanticType.TIMESTAMP, SemanticType.DATE}:
            parsed = sum(parse_datetime(value) is not None for value in non_null)
            ratio = parsed / max(len(non_null), 1)
            evidence.append(f"{ratio:.0%} of populated values parse as dates/timestamps")
            confidence = 0.96 if ratio >= 0.9 else 0.6
        elif matched == SemanticType.GEOMETRY:
            valid_shapes = sum(
                isinstance(value, dict) and value.get("type") in {"Point", "LineString", "Polygon", "MultiPolygon"}
                for value in non_null
            )
            if valid_shapes:
                evidence.append("GeoJSON geometry objects were observed")
                confidence = 0.98
        elif matched in SENSOR_SEMANTICS | MOBILITY_SEMANTICS:
            if data_type in {"number", "string"}:
                evidence.append(f"observed values are compatible with {data_type} semantics")
                confidence = 0.9
        return matched, round(confidence, 2), evidence

    if data_type == "datetime":
        evidence.append("at least 90% of populated values parse as timestamps")
        return SemanticType.TIMESTAMP, 0.82, evidence
    if data_type == "boolean":
        return SemanticType.BOOLEAN, 0.95, ["populated values are boolean"]
    if data_type == "number":
        return SemanticType.NUMERICAL, 0.9, ["at least 90% of populated values are numeric"]
    if data_type == "string":
        unique = len({str(value) for value in non_null})
        threshold = max(20, int(math.sqrt(max(len(non_null), 1))) + 1)
        if unique <= threshold:
            return SemanticType.CATEGORICAL, 0.78, [f"{unique} distinct values indicate a bounded domain"]
        return SemanticType.TEXT, 0.75, ["free-form or high-cardinality string values observed"]
    return SemanticType.UNKNOWN, 0.3, ["no reliable semantic evidence detected"]


def _bounds(rows: Sequence[Dict[str, Any]], fields: Sequence[FieldProfile]) -> Optional[Dict[str, float]]:
    lat_name = next((field.name for field in fields if field.semantic_type == SemanticType.LATITUDE.value), None)
    lon_name = next((field.name for field in fields if field.semantic_type == SemanticType.LONGITUDE.value), None)
    if not lat_name or not lon_name:
        return None
    pairs = [(_numeric(row.get(lat_name)), _numeric(row.get(lon_name))) for row in rows]
    valid = [(lat, lon) for lat, lon in pairs if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180]
    if not valid:
        return None
    return {
        "min_latitude": min(pair[0] for pair in valid),
        "max_latitude": max(pair[0] for pair in valid),
        "min_longitude": min(pair[1] for pair in valid),
        "max_longitude": max(pair[1] for pair in valid),
    }


def _temporal(rows: Sequence[Dict[str, Any]], fields: Sequence[FieldProfile]) -> Optional[Dict[str, str]]:
    names = [field.name for field in fields if field.semantic_type in {SemanticType.TIMESTAMP.value, SemanticType.DATE.value}]
    parsed = [parse_datetime(row.get(name)) for name in names for row in rows]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return None
    return {"start": min(valid).isoformat(), "end": max(valid).isoformat()}


def profile_dataset(
    rows: Iterable[Dict[str, Any]],
    *,
    dataset_id: str,
    name: Optional[str] = None,
    source_format: str = "json",
) -> DatasetProfile:
    materialized = list(rows)
    field_names = sorted({key for row in materialized for key in row})
    profiles: List[FieldProfile] = []
    for field_name in field_names:
        values = [row.get(field_name) for row in materialized]
        non_null = [value for value in values if value not in (None, "")]
        data_type = _base_type(values)
        semantic, confidence, evidence = _semantic(field_name, values, data_type)
        unique_values = {repr(value) for value in non_null}
        profiles.append(
            FieldProfile(
                name=field_name,
                data_type=data_type,
                semantic_type=semantic.value,
                non_null_count=len(non_null),
                null_count=len(values) - len(non_null),
                unique_count=len(unique_values),
                confidence=confidence,
                evidence=evidence,
                sample_values=non_null[:3],
            )
        )

    semantics = {SemanticType(field.semantic_type) for field in profiles if field.semantic_type in SemanticType._value2member_map_}
    normalized_names = {normalize_name(field.name) for field in profiles}
    categories: List[DatasetCategory] = []
    confidence: Dict[str, float] = {}
    evidence: Dict[str, List[str]] = {}

    def add(category: DatasetCategory, score: float, reasons: List[str]) -> None:
        categories.append(category)
        confidence[category.value] = score
        evidence[category.value] = reasons

    if source_format.lower() in {"csv", "json", "ndjson", "geojson"}:
        add(DatasetCategory.TABULAR, 0.94, [f"records were ingested from {source_format.upper()}"])
    if source_format.lower() in {"geotiff", "tiff", "tif"}:
        add(DatasetCategory.GEOSPATIAL_RASTER, 0.99, ["GeoTIFF/TIFF source format detected"])
    if SemanticType.GEOMETRY in semantics or {SemanticType.LATITUDE, SemanticType.LONGITUDE} <= semantics:
        add(DatasetCategory.GEOSPATIAL_VECTOR, 0.96, ["valid coordinate or geometry fields were detected"])
    if SemanticType.NUMERICAL in semantics or semantics & SENSOR_SEMANTICS:
        add(DatasetCategory.NUMERICAL, 0.9, ["one or more numeric measurement fields were detected"])
    if SemanticType.CATEGORICAL in semantics or SemanticType.BOOLEAN in semantics:
        add(DatasetCategory.CATEGORICAL, 0.84, ["bounded categorical or boolean fields were detected"])
    if SemanticType.TIMESTAMP in semantics or SemanticType.DATE in semantics:
        add(DatasetCategory.TEMPORAL, 0.94, ["date or timestamp values were validated"])
    sensor_fields = semantics & SENSOR_SEMANTICS
    if len(sensor_fields) >= 2 or (sensor_fields and SemanticType.DEVICE_ID in semantics):
        add(DatasetCategory.SENSOR_IOT, 0.93, [f"{len(sensor_fields)} sensor/environmental measurements were detected"])
    if sensor_fields & {SemanticType.TEMPERATURE, SemanticType.HUMIDITY, SemanticType.RAINFALL, SemanticType.WIND, SemanticType.PRESSURE}:
        add(DatasetCategory.ENVIRONMENTAL, 0.9, ["environmental measurement semantics were detected"])
    if len(sensor_fields & {SemanticType.TEMPERATURE, SemanticType.HUMIDITY, SemanticType.RAINFALL, SemanticType.WIND, SemanticType.PRESSURE}) >= 2 and (SemanticType.TIMESTAMP in semantics or SemanticType.DATE in semantics):
        add(DatasetCategory.CLIMATE, 0.9, ["multiple timestamped weather/climate variables were detected"])
    mobility_fields = semantics & MOBILITY_SEMANTICS
    if len(mobility_fields) >= 2:
        add(DatasetCategory.MOBILITY, 0.92, [f"{len(mobility_fields)} mobility semantics were detected"])
    if (
        {SemanticType.ORIGIN, SemanticType.DESTINATION} <= semantics
        or normalized_names & {"shipment_id", "order_id", "warehouse_id", "hub_id", "port_id", "carrier"}
    ):
        add(DatasetCategory.LOGISTICS, 0.9, ["shipment or origin/destination semantics were detected"])
    if (SemanticType.TIMESTAMP in semantics or SemanticType.DATE in semantics) and (
        SemanticType.IDENTIFIER in semantics or normalized_names & {"event_id", "trip_id", "shipment_id"}
    ):
        add(DatasetCategory.EVENT, 0.91, ["event identity and event time were detected"])

    return DatasetProfile(
        dataset_id=dataset_id,
        name=name or dataset_id,
        row_count=len(materialized),
        source_format=source_format,
        fields=profiles,
        categories=[category.value for category in categories],
        category_confidence=confidence,
        category_evidence=evidence,
        geographic_bounds=_bounds(materialized, profiles),
        temporal_coverage=_temporal(materialized, profiles),
    )
