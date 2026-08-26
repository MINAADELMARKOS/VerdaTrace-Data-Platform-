"""Typed, implementation-neutral contracts shared by every platform layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from enum import Enum
from typing import Any, Dict, List, Optional


class DatasetCategory(str, Enum):
    LOGISTICS = "logistics"
    MOBILITY = "mobility"
    SENSOR_IOT = "sensor_iot"
    GEOSPATIAL_VECTOR = "geospatial_vector"
    GEOSPATIAL_RASTER = "geospatial_raster"
    CLIMATE = "climate"
    ENVIRONMENTAL = "environmental"
    TEMPORAL = "temporal_time_series"
    TABULAR = "tabular"
    CATEGORICAL = "categorical"
    NUMERICAL = "numerical"
    EVENT = "event_data"


class SemanticType(str, Enum):
    IDENTIFIER = "identifier"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    GEOMETRY = "geometry"
    CRS = "crs"
    TIMESTAMP = "timestamp"
    DATE = "date"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    CO = "carbon_monoxide"
    CO2 = "carbon_dioxide"
    LPG = "lpg"
    SMOKE = "smoke"
    PARTICULATE_MATTER = "particulate_matter"
    RAINFALL = "rainfall"
    SOLAR_RADIATION = "solar_radiation"
    WIND = "wind"
    NDVI = "ndvi"
    LAND_SURFACE_TEMPERATURE = "land_surface_temperature"
    ELEVATION = "elevation"
    LAND_COVER = "land_cover_class"
    DEVICE_ID = "device_identifier"
    VEHICLE_ID = "vehicle_identifier"
    ROUTE = "route"
    SPEED = "speed"
    HEADING = "heading"
    ORIGIN = "origin"
    DESTINATION = "destination"
    DISTANCE = "distance"
    DURATION = "duration"
    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Provenance:
    dataset_name: str
    provider: str
    original_url: str
    retrieved_at: str
    license: str = "not_provided"
    geographic_coverage: str = "unknown"
    temporal_coverage: str = "unknown"
    source_format: str = "unknown"
    original_schema: Dict[str, str] = dc_field(default_factory=dict)
    transformations: List[str] = dc_field(default_factory=list)
    target_schema: str = "verdatrace_multimodal_v1"
    limitations: List[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class FieldProfile:
    name: str
    data_type: str
    semantic_type: str
    non_null_count: int
    null_count: int
    unique_count: int
    confidence: float
    evidence: List[str] = dc_field(default_factory=list)
    sample_values: List[Any] = dc_field(default_factory=list)


@dataclass(frozen=True)
class DatasetProfile:
    dataset_id: str
    name: str
    row_count: int
    source_format: str
    fields: List[FieldProfile]
    categories: List[str]
    category_confidence: Dict[str, float]
    category_evidence: Dict[str, List[str]]
    geographic_bounds: Optional[Dict[str, float]] = None
    temporal_coverage: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    field: Optional[str] = None
    row_indexes: List[int] = dc_field(default_factory=list)
    observed: Any = None
    rule: Optional[str] = None


@dataclass(frozen=True)
class QualityReport:
    dataset_id: str
    total_rows: int
    valid_rows: int
    score: float
    status: str
    issues: List[QualityIssue]
    metrics: Dict[str, Any]


@dataclass(frozen=True)
class AnalysisResult:
    result_type: str
    computed_values: Dict[str, Any]
    dimensions: List[str]
    metrics: List[str]
    units: Dict[str, str]
    warnings: List[str]
    provenance: Dict[str, Any]
    quality_reference: str
    analysis_metadata: Dict[str, Any]
    lineage: List[Dict[str, Any]] = dc_field(default_factory=list)


@dataclass(frozen=True)
class EvaluationReport:
    task: str
    eligible: bool
    score: float
    reasons: List[str]
    warnings: List[str]
    checks: Dict[str, bool]


@dataclass(frozen=True)
class VisualizationSpec:
    type: str
    fields: List[str]
    confidence: float
    reason: str
    config: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class VisualizationRecommendation:
    dataset_type: str
    eligible: bool
    recommended_visualizations: List[VisualizationSpec]
    warnings: List[str]
    unsupported_fields: List[str]


def to_dict(value: Any) -> Any:
    """Recursively convert dataclass and enum values to JSON-safe primitives."""

    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dict(item) for item in value]
    return value
