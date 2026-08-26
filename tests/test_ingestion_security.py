import json
from pathlib import Path

import pytest

from verdatrace.errors import (
    ExternalSourceError,
    InvalidSchemaError,
    UnsupportedCrsError,
    UnsupportedFormatError,
)
from verdatrace.ingestion import fetch_allowlisted_json, iter_batches, iter_records, probe_geotiff


def test_csv_ingestion_batches_without_loading_everything(tmp_path):
    source = tmp_path / "events.csv"
    source.write_text("event_id,value\n1,10\n2,20\n3,30\n", encoding="utf-8")
    batches = list(iter_batches(iter_records(source, allowed_roots=[tmp_path]), batch_size=2))
    assert [len(batch) for batch in batches] == [2, 1]


def test_path_traversal_and_unsupported_extension_are_rejected(tmp_path):
    allowed = tmp_path / "landing"
    allowed.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidSchemaError, match="outside"):
        list(iter_records(outside, allowed_roots=[allowed]))
    unsupported = allowed / "payload.exe"
    unsupported.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        list(iter_records(unsupported, allowed_roots=[allowed]))


def test_malformed_json_and_corrupt_raster_fail_explicitly(tmp_path):
    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad", encoding="utf-8")
    with pytest.raises(InvalidSchemaError, match="malformed"):
        list(iter_records(malformed, allowed_roots=[tmp_path]))
    raster = tmp_path / "bad.tif"
    raster.write_bytes(b"not a tiff")
    with pytest.raises(InvalidSchemaError, match="TIFF"):
        probe_geotiff(raster, allowed_roots=[tmp_path])


def test_external_connector_requires_exact_https_allowlist():
    with pytest.raises(ExternalSourceError, match="allow-listed"):
        fetch_allowlisted_json(
            "http://127.0.0.1/admin",
            allowed_hosts=["archive-api.open-meteo.com"],
        )


def test_unsupported_geojson_crs_fails_with_corrective_error(tmp_path):
    source = tmp_path / "projected.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedCrsError, match="EPSG:3857"):
        list(iter_records(source, allowed_roots=[tmp_path]))
