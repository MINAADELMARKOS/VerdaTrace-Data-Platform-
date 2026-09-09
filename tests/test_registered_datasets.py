from pathlib import Path

from verdatrace.registry import DatasetRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIRECTORY = PROJECT_ROOT / "config" / "datasets"
REQUIRED_EVENT_FIELDS = ["event_id", "event_timestamp", "latitude", "longitude"]


def _registry() -> DatasetRegistry:
    return DatasetRegistry.discover(REGISTRY_DIRECTORY, project_root=PROJECT_ROOT)


def test_repository_registry_loads_both_existing_demo_datasets():
    registry = _registry()

    assert {"open_meteo_cairo_historical", "synthetic_refrigerated_route"} <= set(registry.ids)
    assert registry.get("open_meteo_cairo_historical").enabled is True
    assert registry.get("synthetic_refrigerated_route").enabled is True
    assert all(
        not registry.get(dataset_id).enabled
        for dataset_id in registry.ids
        if dataset_id not in {"open_meteo_cairo_historical", "synthetic_refrigerated_route"}
    )


def test_cairo_registry_entry_preserves_source_pipeline_and_governance_values():
    dataset = _registry().get("open_meteo_cairo_historical")

    assert dataset.name == "Cairo historical weather"
    assert dataset.domain == "climate_environmental"
    assert dataset.task == "climate"
    assert dataset.required_fields == REQUIRED_EVENT_FIELDS
    assert dataset.source.path == "data/samples/open_meteo_cairo_2024-01-01_2024-01-03.json"
    assert dataset.source.format == "json"
    assert dataset.source.dataset_type == "tabular"
    assert dataset.source.dataset_name == "Open-Meteo Historical Weather API — Cairo sample"
    assert dataset.source.fixture is False
    assert dataset.source.provider == "Open-Meteo"
    assert dataset.source.original_url == (
        "https://archive-api.open-meteo.com/v1/archive?latitude=30.0444&longitude=31.2357"
        "&start_date=2024-01-01&end_date=2024-01-03&hourly=temperature_2m%2C"
        "relative_humidity_2m%2Cprecipitation%2Cwind_speed_10m&timezone=UTC"
    )
    assert dataset.source.retrieved_at == "2026-08-26T13:06:50.722273+00:00"
    assert dataset.source.license == "CC BY 4.0"
    assert dataset.source.geographic_coverage == "point sample near 30.052723, 31.190199"
    assert dataset.source.temporal_coverage == (
        "2024-01-01T00:00:00Z to 2024-01-03T23:00:00Z"
    )
    assert dataset.source.crs == "EPSG:4326"
    assert dataset.source.original_schema == {
        "hourly.time": "ISO-8601",
        "hourly.temperature_2m": "degC",
        "hourly.relative_humidity_2m": "percent",
        "hourly.precipitation": "mm",
        "hourly.wind_speed_10m": "km/h",
    }
    assert dataset.source.transformations == [
        "zipped hourly arrays",
        "attached WGS84 query coordinates",
        "renamed fields to VerdaTrace canonical semantics",
    ]
    assert dataset.source.limitations == [
        "Point sample is not representative of all Cairo microclimates.",
        "Values inherit upstream weather-model and reanalysis limitations.",
    ]
    assert dataset.source.attribution_label == "Weather data by Open-Meteo.com"
    assert dataset.source.attribution_url == "https://open-meteo.com/"
    assert dataset.quality.domain_constraints == {}
    assert dataset.quality.telemetry_max_age_seconds is None
    assert dataset.governance.owner == "not_provided"
    assert dataset.governance.sensitivity == "public"
    assert dataset.governance.retention_policy == (
        "sample retained in source control; refresh reproducibly"
    )


def test_route_registry_entry_preserves_fixture_pipeline_and_governance_values():
    dataset = _registry().get("synthetic_refrigerated_route")

    assert dataset.name == "Synthetic refrigerated shipment route"
    assert dataset.domain == "logistics_mobility_sensor"
    assert dataset.task == "mobility"
    assert dataset.required_fields == REQUIRED_EVENT_FIELDS
    assert dataset.source.path == "tests/fixtures/synthetic_mobility_route.geojson"
    assert dataset.source.format == "geojson"
    assert dataset.source.dataset_type == "vector"
    assert dataset.source.dataset_name == "Synthetic refrigerated shipment route fixture"
    assert dataset.source.fixture is True
    assert dataset.source.provider == "VerdaTrace test suite"
    assert dataset.source.original_url == (
        "repository://tests/fixtures/synthetic_mobility_route.geojson"
    )
    assert dataset.source.retrieved_at == "not_applicable_generated_fixture"
    assert dataset.source.license == "not_applicable_test_fixture"
    assert dataset.source.geographic_coverage == (
        "Synthetic route near Alexandria, Egypt; not operational data"
    )
    assert dataset.source.temporal_coverage == (
        "2024-02-10T08:00:00Z to 2024-02-10T08:44:00Z"
    )
    assert dataset.source.crs == "EPSG:4326"
    assert dataset.source.original_schema == {
        "geometry": "GeoJSON Point EPSG:4326",
        "event_timestamp": "ISO-8601",
        "vehicle_id": "string",
        "route_id": "string",
        "speed_kph": "number",
        "temperature_c": "number",
    }
    assert dataset.source.transformations == [
        "flattened GeoJSON properties",
        "derived latitude and longitude from Point geometry",
    ]
    assert dataset.source.limitations == [
        "Synthetic fixture for deterministic tests and UI demonstration; not a real shipment."
    ]
    assert dataset.source.attribution_label == "Clearly labeled generated test fixture"
    assert dataset.source.attribution_url == (
        "https://github.com/MINAADELMARKOS/VerdaTrace-Data-Platform-"
    )
    assert dataset.quality.domain_constraints == {}
    assert dataset.quality.telemetry_max_age_seconds is None
    assert dataset.governance.owner == "VerdaTrace maintainers"
    assert dataset.governance.sensitivity == "public_fixture"
    assert dataset.governance.retention_policy == "repository test fixture"
