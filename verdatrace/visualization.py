"""Deterministic visualization recommendations independent from the UI."""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import (
    DatasetProfile,
    EvaluationReport,
    SemanticType,
    VisualizationRecommendation,
    VisualizationSpec,
)


def _first(fields: Dict[SemanticType, List[str]], semantic: SemanticType) -> Optional[str]:
    return fields.get(semantic, [None])[0]


def recommend_visualizations(
    profile: DatasetProfile,
    evaluation: EvaluationReport,
) -> VisualizationRecommendation:
    semantic_fields: Dict[SemanticType, List[str]] = {}
    numeric_fields: List[str] = []
    category_fields: List[str] = []
    unsupported: List[str] = []
    for field in profile.fields:
        if field.semantic_type in SemanticType._value2member_map_:
            semantic = SemanticType(field.semantic_type)
            semantic_fields.setdefault(semantic, []).append(field.name)
        if field.data_type == "number" and field.semantic_type not in {
            SemanticType.LATITUDE.value,
            SemanticType.LONGITUDE.value,
        }:
            numeric_fields.append(field.name)
        if field.semantic_type in {
            SemanticType.CATEGORICAL.value,
            SemanticType.LAND_COVER.value,
            SemanticType.BOOLEAN.value,
        }:
            category_fields.append(field.name)
        if field.semantic_type in {SemanticType.TEXT.value, SemanticType.UNKNOWN.value}:
            unsupported.append(field.name)

    specs: List[VisualizationSpec] = []
    warnings: List[str] = []
    time_field = _first(semantic_fields, SemanticType.TIMESTAMP) or _first(semantic_fields, SemanticType.DATE)
    lat_field = _first(semantic_fields, SemanticType.LATITUDE)
    lon_field = _first(semantic_fields, SemanticType.LONGITUDE)
    geometry_field = _first(semantic_fields, SemanticType.GEOMETRY)
    route_field = _first(semantic_fields, SemanticType.ROUTE)
    vehicle_field = _first(semantic_fields, SemanticType.VEHICLE_ID)

    if time_field and numeric_fields:
        specs.append(
            VisualizationSpec(
                type="line_chart",
                fields=[time_field, numeric_fields[0]],
                confidence=0.95,
                reason="A validated temporal axis and continuous numeric measurement were detected.",
                config={"aggregate": "mean", "sort": "ascending_time"},
            )
        )
    if len(numeric_fields) >= 2:
        specs.append(
            VisualizationSpec(
                type="scatter_plot",
                fields=numeric_fields[:2],
                confidence=0.9,
                reason="Two continuous numeric variables support relationship analysis.",
            )
        )
    if numeric_fields:
        specs.append(
            VisualizationSpec(
                type="histogram",
                fields=[numeric_fields[0]],
                confidence=0.88,
                reason="A continuous numeric field supports distribution analysis.",
            )
        )
    if category_fields and numeric_fields:
        specs.append(
            VisualizationSpec(
                type="bar_chart",
                fields=[category_fields[0], numeric_fields[0]],
                confidence=0.9,
                reason="A bounded categorical dimension and numeric metric support comparison.",
                config={"aggregate": "mean"},
            )
        )

    if lat_field and lon_field:
        specs.append(
            VisualizationSpec(
                type="point_map",
                fields=[lon_field, lat_field],
                confidence=0.98,
                reason="Validated WGS84 longitude and latitude observations were detected.",
                config={"crs": "EPSG:4326", "cluster": profile.row_count >= 100},
            )
        )
        if numeric_fields:
            specs.append(
                VisualizationSpec(
                    type="proportional_symbol_map",
                    fields=[lon_field, lat_field, numeric_fields[0]],
                    confidence=0.9,
                    reason="Geographic points have an associated magnitude field.",
                    config={"crs": "EPSG:4326"},
                )
            )
        if profile.row_count >= 500:
            specs.append(
                VisualizationSpec(
                    type="heatmap",
                    fields=[lon_field, lat_field],
                    confidence=0.88,
                    reason="Dense point observations are better summarized as spatial intensity.",
                )
            )
        if time_field and (route_field or vehicle_field):
            specs.append(
                VisualizationSpec(
                    type="route_map",
                    fields=[lon_field, lat_field, time_field] + ([route_field] if route_field else [vehicle_field]),
                    confidence=0.96,
                    reason="Ordered geographic observations with temporal sequencing were detected.",
                    config={"crs": "EPSG:4326", "order_by": time_field},
                )
            )
        if time_field:
            specs.append(
                VisualizationSpec(
                    type="temporal_spatial_animation",
                    fields=[lon_field, lat_field, time_field],
                    confidence=0.87,
                    reason="Timestamped geographic observations support temporal playback.",
                )
            )

    if geometry_field:
        geometry_profile = next(field for field in profile.fields if field.name == geometry_field)
        geometry_types = {
            value.get("type")
            for value in geometry_profile.sample_values
            if isinstance(value, dict) and value.get("type")
        }
        polygon_geometry = bool(geometry_types & {"Polygon", "MultiPolygon"})
        normalized = (
            next(
                (
                    field
                    for field in numeric_fields
                    if any(token in field.lower() for token in ("rate", "ratio", "percent", "pct", "density", "per_"))
                ),
                None,
            )
            if polygon_geometry
            else None
        )
        if normalized and polygon_geometry:
            specs.append(
                VisualizationSpec(
                    type="choropleth_map",
                    fields=[geometry_field, normalized],
                    confidence=0.94,
                    reason="Polygon geometry and a normalized comparison metric were detected.",
                )
            )
        elif polygon_geometry:
            specs.append(
                VisualizationSpec(
                    type="polygon_map",
                    fields=[geometry_field],
                    confidence=0.9,
                    reason="Polygon geometry can be displayed, but no normalized choropleth metric was detected.",
                )
            )
            if numeric_fields:
                warnings.append("A choropleth was not recommended because no normalized polygon metric was detected.")

    if "geospatial_raster" in profile.categories:
        specs.append(
            VisualizationSpec(
                type="raster_map",
                fields=[],
                confidence=0.96,
                reason="A geospatial raster source format was detected.",
                config={"rendering": "classified" if semantic_fields.get(SemanticType.LAND_COVER) else "continuous"},
            )
        )

    if not specs:
        warnings.append("No safe deterministic visualization could be recommended for the detected schema.")
    if not time_field and any(spec.type == "line_chart" for spec in specs):
        warnings.append("Line charts require an ordered temporal field.")

    if "mobility" in profile.categories and "geospatial_vector" in profile.categories:
        dataset_type = "mobility_geospatial"
    elif "sensor_iot" in profile.categories and "geospatial_vector" in profile.categories:
        dataset_type = "sensor_geospatial"
    elif profile.categories:
        dataset_type = profile.categories[0]
    else:
        dataset_type = "unknown"

    return VisualizationRecommendation(
        dataset_type=dataset_type,
        eligible=bool(specs) and evaluation.eligible,
        recommended_visualizations=specs,
        warnings=warnings + ([] if evaluation.eligible else evaluation.warnings),
        unsupported_fields=unsupported,
    )
