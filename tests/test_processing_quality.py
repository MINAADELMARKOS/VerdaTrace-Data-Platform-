from verdatrace.catalog import profile_dataset
from verdatrace.models import Provenance
from verdatrace.pipeline import MultimodalPipeline
from verdatrace.quality import evaluate_quality, route_quality_outcomes


def _provenance():
    return Provenance(
        dataset_name="processing fixture",
        provider="test",
        original_url="repository://tests",
        retrieved_at="not_applicable",
    )


def test_quality_outcomes_route_valid_repairable_quarantined_and_rejected_records():
    rows = [
        {"event_id": "valid", "event_timestamp": "2024-01-01T00:00:00Z", "latitude": 30, "longitude": 31},
        {"event_id": "warning", "event_timestamp": "2024-01-01T01:00:00Z", "latitude": None, "longitude": 31},
        {"event_id": "bad-coord", "event_timestamp": "2024-01-01T02:00:00Z", "latitude": 138.4, "longitude": 31},
        {"event_id": "missing-time", "event_timestamp": "", "latitude": 30, "longitude": 31},
    ]
    profile = profile_dataset(rows, dataset_id="routing", source_format="json")
    quality = evaluate_quality(rows, profile, required_fields=["event_id", "event_timestamp"])

    statuses, quarantine = route_quality_outcomes(rows, quality, processing_timestamp="2024-01-01T03:00:00+00:00")

    assert statuses == ["VALID", "REPAIRABLE", "QUARANTINED", "REJECTED"]
    assert {record.issue_code for record in quarantine} == {"invalid_latitude", "missing_required_value"}
    assert all(record.dataset_id == "routing" for record in quarantine)
    assert all(record.processing_timestamp.endswith("+00:00") for record in quarantine)


def test_pipeline_emits_measured_processing_metrics_and_bounded_quarantine_details():
    rows = [
        {"event_id": "ok", "event_timestamp": "2024-01-01T00:00:00Z", "latitude": 30, "longitude": 31, "payload": "safe"},
        {"event_id": "bad", "event_timestamp": "2024-01-01T01:00:00Z", "latitude": 138.4, "longitude": 31, "payload": "x" * 1000},
    ]
    outcome = MultimodalPipeline(actor="test", role="steward").run(
        rows,
        dataset_id="processing",
        dataset_name="Processing fixture",
        source_format="json",
        provenance=_provenance(),
        required_fields=["event_id", "event_timestamp"],
        input_size=123,
    )

    metrics = outcome.processing
    assert metrics.input_bytes == 123
    assert metrics.output_bytes is None
    assert metrics.records_processed == 2
    assert metrics.records_valid == 1
    assert metrics.records_quarantined == 1
    assert metrics.records_rejected == 0
    assert metrics.records_repaired == 0
    assert metrics.duration_seconds is not None and metrics.duration_seconds >= 0
    assert metrics.throughput_records_per_second is not None
    assert len(outcome.quarantine) == 1
    assert outcome.quality.metrics["record_status_counts"] == {
        "VALID": 1,
        "REPAIRABLE": 0,
        "QUARANTINED": 1,
        "REJECTED": 0,
    }
    assert outcome.quarantine[0].observed_value == 138.4
    assert any(step["stage"] == "quality_routing" for step in outcome.lineage)
    assert any(event.operation == "quality_routing" for event in outcome.audit_events)


def test_spatial_quality_covers_geometry_and_crs_failure_modes():
    cases = [
        ({"type": "LineString", "coordinates": [[1, 1], [1, 1]]}, "zero length"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [2, 0], [0, 0]]]}, "zero area"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}, "not closed"),
    ]
    for geometry, expected in cases:
        rows = [{"event_id": "geometry", "geometry": geometry}]
        profile = profile_dataset(rows, dataset_id="geometry", source_format="geojson")
        report = evaluate_quality(rows, profile)
        invalid = next(issue for issue in report.issues if issue.code == "invalid_geometry")
        assert expected in invalid.observed[0]

    missing_crs_rows = [{"event_id": "missing-crs", "geometry": {"type": "Point", "coordinates": [31, 30]}}]
    missing_crs = evaluate_quality(
        missing_crs_rows,
        profile_dataset(missing_crs_rows, dataset_id="missing-crs", source_format="geojson"),
    )
    assert "missing_crs" in {issue.code for issue in missing_crs.issues}

    crs_rows = [
        {"event_id": "a", "geometry": {"type": "Point", "coordinates": [31, 30]}, "crs": "EPSG:3857"},
        {"event_id": "b", "geometry": {"type": "Point", "coordinates": [31.1, 30.1]}, "crs": "EPSG:4326"},
    ]
    crs_report = evaluate_quality(crs_rows, profile_dataset(crs_rows, dataset_id="crs", source_format="geojson"))
    crs_codes = {issue.code for issue in crs_report.issues}
    assert {"unsupported_crs", "inconsistent_crs"} <= crs_codes


def test_coordinate_checks_warn_on_missing_and_suspected_swapped_axes():
    rows = [
        {"event_id": "missing", "latitude": None, "longitude": 31},
        {"event_id": "swapped", "latitude": 120, "longitude": 30},
        {"event_id": "impossible", "latitude": 138.4, "longitude": -245.1},
    ]
    report = evaluate_quality(rows, profile_dataset(rows, dataset_id="coordinates", source_format="json"))
    codes = {issue.code for issue in report.issues}
    assert "missing_coordinates" in codes
    # Out-of-range axes are errors and also produce a warning for likely swaps.
    assert "invalid_latitude" in codes
    assert "invalid_longitude" in codes
    assert "suspected_swapped_coordinates" in codes
