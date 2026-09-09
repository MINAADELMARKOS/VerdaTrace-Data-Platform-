from pathlib import Path

import pytest

from verdatrace.errors import UnsupportedFormatError
from verdatrace.catalog import profile_dataset
from verdatrace.osm import OSMAdapter, analyze_osm_records, osm_executive_kpis, profile_osm_records
from verdatrace.quality import evaluate_quality


def _elements():
    return [
        {"type": "node", "id": 1, "lon": 31.20, "lat": 30.10, "tags": {"amenity": "cafe"}},
        {
            "type": "way",
            "id": 2,
            "geometry": {"type": "LineString", "coordinates": [[31.2, 30.1], [31.3, 30.2]]},
            "tags": {"highway": "primary", "name": "Example Road"},
        },
        {
            "type": "way",
            "id": 3,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[31.2, 30.1], [31.2, 30.2], [31.3, 30.2], [31.2, 30.1]]],
            },
            "tags": {"building": "yes"},
        },
        {"type": "relation", "id": 4, "tags": {"type": "multipolygon"}},
    ]


def test_osm_adapter_streams_and_normalizes_without_materializing_pbf(tmp_path: Path):
    source = tmp_path / "egypt.osm.pbf"
    source.write_bytes(b"fixture")

    def parser(path, emit):
        assert path == source.resolve()
        for element in _elements():
            emit(element)

    records = list(OSMAdapter(parser=parser).iter_records(source, allowed_roots=[tmp_path]))

    assert [record["osm_id"] for record in records] == ["1", "2", "3", "4"]
    assert records[0]["geometry"]["type"] == "Point"
    assert records[1]["geometry"]["type"] == "LineString"
    assert records[2]["geometry"]["type"] == "Polygon"
    assert records[3]["geometry"] is None
    assert records[1]["highway"] == "primary"
    assert records[2]["building"] == "yes"

    limited = list(OSMAdapter(parser=parser).iter_records(source, allowed_roots=[tmp_path], max_records=2))
    assert len(limited) == 2
    assert list(OSMAdapter(parser=parser).iter_records(source, allowed_roots=[tmp_path], max_records=0)) == []


def test_default_osm_adapter_fails_explicitly_when_worker_dependency_is_unavailable(tmp_path: Path):
    source = tmp_path / "egypt.osm.pbf"
    source.write_bytes(b"not-a-real-pbf")
    try:
        import osmium  # type: ignore # noqa: F401
    except ImportError:
        with pytest.raises(UnsupportedFormatError, match="pyosmium"):
            next(OSMAdapter().iter_records(source, allowed_roots=[tmp_path]))
    else:
        pytest.skip("pyosmium is installed; dependency failure path is not applicable")


def test_osm_profile_analytics_and_kpis_are_source_derived():
    records = [
        # Use the same normalized contract produced by OSMAdapter.
        {"osm_id": "1", "feature_type": "node", "geometry_type": "Point", "geometry": {"type": "Point", "coordinates": [31.2, 30.1]}, "tags": {"amenity": "cafe"}, "amenity": "cafe"},
        {"osm_id": "2", "feature_type": "way", "geometry_type": "LineString", "geometry": {"type": "LineString", "coordinates": [[31.2, 30.1], [31.3, 30.2]]}, "tags": {"highway": "primary"}, "highway": "primary"},
        {"osm_id": "3", "feature_type": "way", "geometry_type": "Polygon", "geometry": {"type": "Polygon", "coordinates": [[[31.2, 30.1], [31.2, 30.2], [31.3, 30.2], [31.2, 30.1]]]}, "tags": {"building": "yes"}, "building": "yes"},
    ]
    profile = profile_osm_records(records)
    summary = analyze_osm_records(records)

    assert profile["feature_count"] == 3
    assert profile["geometry_counts"] == {"LineString": 1, "Point": 1, "Polygon": 1}
    assert profile["bounds"]["min_longitude"] == 31.2
    assert summary["road_count"] == 1
    assert summary["building_count"] == 1
    assert summary["poi_count"] == 1
    assert summary["road_length_km"] > 0
    assert summary["feature_completeness_percent"] == 100.0

    class Analysis:
        computed_values = {"osm_summary": summary}

    kpis = osm_executive_kpis(Analysis())
    assert {kpi.id for kpi in kpis} == {
        "road_network_length", "buildings_mapped", "pois", "infrastructure_features", "feature_completeness"
    }
    assert all(kpi.value is not None and kpi.source_metric for kpi in kpis)


def test_osm_quality_surfaces_invalid_coordinates_and_semantic_gaps():
    rows = [
        {"osm_id": "1", "feature_type": "node", "longitude": -245.1, "latitude": 30, "geometry": None, "tags": {}},
        {"osm_id": "1", "feature_type": "way", "geometry": None, "tags": {}},
    ]
    profile = profile_dataset(rows, dataset_id="osm-quality", source_format="osm_pbf")
    quality = evaluate_quality(rows, profile)
    codes = {issue.code for issue in quality.issues}
    assert "invalid_longitude" in codes
    assert "osm_missing_geometry" in codes
    assert "osm_empty_tags" in codes
    assert "duplicate_osm_id" in codes
