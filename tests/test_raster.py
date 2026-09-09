from pathlib import Path

import pytest

from verdatrace.errors import InvalidSchemaError, UnsupportedFormatError
from verdatrace.models import RasterProfile
from verdatrace.raster import (
    RasterAdapterRegistry,
    analyze_raster_bands,
    duplicate_scene_ids,
    evaluate_raster_quality,
    recommend_raster_visualizations,
    profile_stac_item,
)


def test_geotiff_header_adapter_is_explicitly_metadata_only(tmp_path: Path):
    source = tmp_path / "scene.tif"
    source.write_bytes(b"II*\x00" + b"header-bytes")

    profile = RasterAdapterRegistry().get("geotiff").profile(source, allowed_roots=[tmp_path])

    assert profile.format == "geotiff"
    assert profile.readable is True
    assert profile.pixel_count is None
    assert profile.crs is None
    assert profile.scene_metadata["size_bytes"] == source.stat().st_size


def test_raster_registry_rejects_unsupported_execution_explicitly(tmp_path: Path):
    registry = RasterAdapterRegistry()
    with pytest.raises(UnsupportedFormatError, match="COG"):
        registry.get("cog").profile(tmp_path / "scene.cog", allowed_roots=[tmp_path])
    with pytest.raises(UnsupportedFormatError, match="NetCDF"):
        registry.get("netcdf").profile(tmp_path / "scene.nc", allowed_roots=[tmp_path])
    with pytest.raises(InvalidSchemaError, match="unsupported raster adapter"):
        registry.register(type("BadAdapter", (), {"format": "unknown"})())


def test_raster_quality_checks_profile_metadata():
    missing = evaluate_raster_quality(
        RasterProfile(format="geotiff", bands=["B04"], nodata_percentage=25),
        expected_bands=["B02", "B04"],
    )
    assert missing.status == "failed"
    assert {issue.code for issue in missing.issues} >= {
        "missing_crs",
        "missing_bands",
    }
    assert missing.metrics["nodata_percentage"] == 25

    valid = evaluate_raster_quality(
        RasterProfile(
            format="geotiff",
            width=2,
            height=2,
            bands=["B02", "B04"],
            pixel_count=4,
            crs="EPSG:4326",
            bounds={"west": 30, "south": 29, "east": 31, "north": 30},
            resolution={"x": 10, "y": 10},
            nodata_percentage=0,
            readable=True,
        ),
        expected_bands=["B02", "B04"],
    )
    assert valid.status == "passed"
    assert valid.issues == []


def test_raster_quality_rejects_invalid_bounds_and_nodata_percentage():
    report = evaluate_raster_quality(
        RasterProfile(
            format="geotiff",
            crs="EPSG:4326",
            bounds={"west": "bad", "south": 1, "east": 0, "north": 2},
            resolution={"x": -1, "y": 1},
            nodata_percentage=101,
        ),
        duplicate_scenes=["scene-1"],
    )
    assert {issue.code for issue in report.issues} >= {
        "invalid_bounds",
        "resolution_inconsistent",
        "invalid_nodata_percentage",
        "duplicate_scene_metadata",
    }


def test_raster_analytics_streams_chunks_and_reports_per_band_statistics():
    chunks = {
        "B04": (chunk for chunk in ([1, 2], [None, 3])),
        "B08": ([10], [None, 14]),
    }

    result = analyze_raster_bands(chunks)

    assert result.computed_values == {
        "band_count": 2,
        "valid_pixel_count": 5,
        "nodata_pixel_count": 2,
        "nodata_percentage": 28.571429,
        "coverage": 0.714286,
    }
    assert result.band_statistics[0].mean == 2.0
    assert result.band_statistics[0].minimum == 1.0
    assert result.band_statistics[0].maximum == 3.0
    assert result.band_statistics[1].stddev == 2.0


def test_raster_analytics_handles_all_nodata_without_fabricating_values():
    result = analyze_raster_bands({"B01": ([None, None],)})

    stats = result.band_statistics[0]
    assert stats.count == 0
    assert stats.minimum is None
    assert stats.mean is None
    assert result.computed_values["coverage"] == 0.0
    assert result.warnings


def test_duplicate_scene_ids_are_detected_only_when_declared():
    profiles = [
        RasterProfile(format="geotiff", scene_id="scene-1"),
        RasterProfile(format="geotiff", scene_id="scene-1"),
        RasterProfile(format="geotiff"),
        RasterProfile(format="geotiff", scene_id="scene-2"),
        RasterProfile(format="geotiff", scene_id="scene-2"),
    ]

    assert duplicate_scene_ids(profiles) == ["scene-1", "scene-2"]


def test_raster_recommendations_require_spatial_metadata_and_respect_semantics():
    assert recommend_raster_visualizations(RasterProfile(format="geotiff", bands=["B04"])) == []
    classified = recommend_raster_visualizations(
        RasterProfile(
            format="geotiff",
            bands=["land_cover_class"],
            crs="EPSG:4326",
            bounds={"west": 30, "south": 29, "east": 31, "north": 30},
            temporal_metadata={"date": "2024-01-01"},
        )
    )
    assert [item.type for item in classified] == ["classified_raster", "raster_timeseries"]


def test_raster_quality_checks_band_resolution_and_cloud_objectives():
    report = evaluate_raster_quality(
        RasterProfile(
            format="cog",
            crs="EPSG:4326",
            bounds={"west": 30, "south": 29, "east": 31, "north": 30},
            resolution={"x": 10, "y": 10},
            band_resolutions={"B02": {"x": 10, "y": 10}, "B08": {"x": 20, "y": 20}},
            cloud_percentage=42,
        ),
        cloud_warning_percentage=20,
    )
    assert {issue.code for issue in report.issues} >= {"resolution_inconsistent", "high_cloud_coverage"}


def test_stac_profile_extracts_declared_sentinel_metadata_without_pixels():
    profile = profile_stac_item(
        {
            "type": "Feature",
            "id": "S2A_20240101",
            "bbox": [30.0, 29.0, 31.0, 30.0],
            "properties": {
                "datetime": "2024-01-01T10:00:00Z",
                "proj:epsg": 32636,
                "proj:shape": [100, 200],
                "proj:resolution": [10, 10],
                "eo:cloud_cover": 12.5,
            },
            "assets": {
                "B02": {"roles": ["data"], "eo:bands": [{"name": "B02"}]},
                "B08": {"roles": ["data"], "eo:bands": [{"name": "B08"}]},
                "thumbnail": {"roles": ["thumbnail"]},
            },
        }
    )
    assert profile.scene_id == "S2A_20240101"
    assert profile.bands == ["B02", "B08"]
    assert profile.crs == "EPSG:32636"
    assert profile.width == 200 and profile.height == 100
    assert profile.pixel_count == 20_000
    assert profile.cloud_percentage == 12.5
