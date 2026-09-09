from pathlib import Path

from verdatrace.analytics import analyze_dataset
from verdatrace.catalog import profile_dataset
from verdatrace.evaluation import evaluate_suitability
from verdatrace.ingestion import iter_records
from verdatrace.models import Provenance
from verdatrace.quality import evaluate_quality
from verdatrace.visualization import recommend_visualizations

FIXTURES = Path(__file__).parent / "fixtures"


def _provenance(source_format="GeoJSON"):
    return Provenance(
        dataset_name="test",
        provider="test suite",
        original_url="repository://fixture",
        retrieved_at="not_applicable",
        source_format=source_format,
    )


def test_mobility_analysis_and_route_recommendation():
    rows = list(iter_records(FIXTURES / "synthetic_mobility_route.geojson", allowed_roots=[FIXTURES]))
    profile = profile_dataset(rows, dataset_id="route", source_format="geojson")
    quality = evaluate_quality(rows, profile, required_fields=["event_timestamp", "latitude", "longitude"])
    analysis = analyze_dataset(rows, profile, quality, _provenance(), task="mobility")
    evaluation = evaluate_suitability(profile, quality, analysis, task="mobility")
    recommendation = recommend_visualizations(profile, evaluation)
    types = {item.type for item in recommendation.recommended_visualizations}
    assert analysis.computed_values["spatial_bounds"]
    assert analysis.computed_values["mobility_summary"]["total_distance"] > 0
    assert {"point_map", "route_map", "temporal_spatial_animation"} <= types
    assert "choropleth_map" not in types


def test_choropleth_requires_polygon_and_normalized_metric():
    rows = [
        {
            "event_id": "a",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            },
            "population_count": 1000,
        }
    ]
    profile = profile_dataset(rows, dataset_id="polygon", source_format="geojson")
    quality = evaluate_quality(rows, profile)
    analysis = analyze_dataset(rows, profile, quality, _provenance(), task="spatial")
    evaluation = evaluate_suitability(profile, quality, analysis, task="spatial")
    recommendation = recommend_visualizations(profile, evaluation)
    types = {item.type for item in recommendation.recommended_visualizations}
    assert "polygon_map" in types
    assert "choropleth_map" not in types
    assert any("normalized" in warning for warning in recommendation.warnings)


def test_climate_points_are_not_misidentified_as_routes():
    rows = [
        {
            "event_id": f"w-{hour}",
            "event_timestamp": f"2024-01-01T{hour:02d}:00:00Z",
            "device_id": "weather-grid",
            "latitude": 30.0,
            "longitude": 31.0,
            "temperature_c": 20 + hour,
            "humidity_pct": 50,
        }
        for hour in range(4)
    ]
    profile = profile_dataset(rows, dataset_id="weather", source_format="json")
    quality = evaluate_quality(rows, profile)
    analysis = analyze_dataset(rows, profile, quality, _provenance("JSON"), task="climate")
    evaluation = evaluate_suitability(profile, quality, analysis, task="climate")
    recommendation = recommend_visualizations(profile, evaluation)
    types = {item.type for item in recommendation.recommended_visualizations}
    assert "line_chart" in types
    assert "point_map" in types
    assert "route_map" not in types


def test_osm_lines_and_geometry_categories_get_safe_spatial_recommendations():
    rows = [
        {
            "osm_id": "1",
            "feature_type": "way",
            "geometry_type": "LineString",
            "geometry": {"type": "LineString", "coordinates": [[31.2, 30.1], [31.3, 30.2]]},
            "highway": "primary",
            "tags": {"highway": "primary"},
        },
        {
            "osm_id": "2",
            "feature_type": "node",
            "geometry_type": "Point",
            "geometry": {"type": "Point", "coordinates": [31.2, 30.1]},
            "amenity": "cafe",
            "tags": {"amenity": "cafe"},
        },
    ]
    profile = profile_dataset(rows, dataset_id="osm", source_format="osm_pbf")
    quality = evaluate_quality(rows, profile)
    analysis = analyze_dataset(rows, profile, quality, _provenance("OSM PBF"), task="spatial")
    evaluation = evaluate_suitability(profile, quality, analysis, task="spatial")
    recommendation = recommend_visualizations(profile, evaluation)
    types = {item.type for item in recommendation.recommended_visualizations}

    assert profile.geographic_bounds == {
        "min_latitude": 30.1,
        "max_latitude": 30.2,
        "min_longitude": 31.2,
        "max_longitude": 31.3,
    }
    assert {"line_map", "geometry_distribution"} <= types
    assert analysis.computed_values["osm_summary"]["road_count"] == 1
