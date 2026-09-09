"""Typed, implementation-neutral contracts shared by every platform layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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
class DatasetSourceConfig:
    path: str
    format: str
    dataset_type: str
    dataset_name: Optional[str] = None
    fixture: bool = False
    provider: str = "not_provided"
    original_url: str = ""
    retrieved_at: str = "not_provided"
    license: str = "not_provided"
    geographic_coverage: str = "unknown"
    temporal_coverage: str = "unknown"
    crs: Optional[str] = None
    original_schema: Dict[str, str] = dc_field(default_factory=dict)
    transformations: List[str] = dc_field(default_factory=list)
    limitations: List[str] = dc_field(default_factory=list)
    attribution_label: Optional[str] = None
    attribution_url: Optional[str] = None


@dataclass(frozen=True)
class DatasetQualityConfig:
    domain_constraints: Dict[str, Tuple[Optional[float], Optional[float]]] = dc_field(default_factory=dict)
    telemetry_max_age_seconds: Optional[float] = None


@dataclass(frozen=True)
class DatasetGovernanceConfig:
    owner: str = "not_provided"
    sensitivity: str = "not_provided"
    retention_policy: str = "not_provided"


@dataclass(frozen=True)
class DatasetConfig:
    id: str
    name: str
    domain: str
    source: DatasetSourceConfig
    enabled: bool = True
    task: str = "general"
    required_fields: List[str] = dc_field(default_factory=list)
    quality: DatasetQualityConfig = dc_field(default_factory=DatasetQualityConfig)
    governance: DatasetGovernanceConfig = dc_field(default_factory=DatasetGovernanceConfig)
    schema_version: str = "verdatrace_dataset_config_v1"


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
class DatasetManifest:
    dataset_id: str
    dataset_name: str
    provider: Optional[str]
    source_format: Optional[str]
    dataset_type: Optional[str]
    input_size: Optional[int]
    record_count: int
    geometry_types: List[str]
    crs: Optional[str]
    bounding_box: Optional[Dict[str, float]]
    geographic_coverage: Optional[str]
    temporal_coverage: Optional[Dict[str, str]]
    license: Optional[str]
    ingestion_timestamp: str
    processing_timestamp: str
    fixture: Optional[bool]


@dataclass(frozen=True)
class RasterProfile:
    """Format-neutral raster metadata; values remain nullable until decoded."""

    format: str
    width: Optional[int] = None
    height: Optional[int] = None
    bands: List[str] = dc_field(default_factory=list)
    pixel_count: Optional[int] = None
    crs: Optional[str] = None
    bounds: Optional[Dict[str, float]] = None
    resolution: Optional[Dict[str, float]] = None
    band_resolutions: Dict[str, Dict[str, float]] = dc_field(default_factory=dict)
    nodata: Optional[float] = None
    nodata_percentage: Optional[float] = None
    cloud_percentage: Optional[float] = None
    dtype: Optional[str] = None
    temporal_metadata: Dict[str, Any] = dc_field(default_factory=dict)
    scene_id: Optional[str] = None
    scene_metadata: Dict[str, Any] = dc_field(default_factory=dict)
    readable: Optional[bool] = None


@dataclass(frozen=True)
class RasterQualityIssue:
    code: str
    severity: str
    message: str
    observed: Any = None


@dataclass(frozen=True)
class RasterQualityReport:
    status: str
    score: float
    issues: List[RasterQualityIssue]
    metrics: Dict[str, Any]


@dataclass(frozen=True)
class RasterBandStatistics:
    band: str
    count: int
    nodata_count: int
    minimum: Optional[float]
    maximum: Optional[float]
    mean: Optional[float]
    stddev: Optional[float]


@dataclass(frozen=True)
class RasterAnalysisResult:
    result_type: str
    band_statistics: List[RasterBandStatistics]
    computed_values: Dict[str, Any]
    warnings: List[str] = dc_field(default_factory=list)


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
class ExecutiveKPI:
    """Optional business KPI with enough context to audit its origin."""

    id: str
    label: str
    value: Optional[float] = None
    unit: str = ""
    status: Optional[str] = None
    description: str = ""
    source_metric: Optional[str] = None
    analysis_stage: Optional[str] = None
    fields_used: List[str] = dc_field(default_factory=list)
    calculation_description: Optional[str] = None


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
