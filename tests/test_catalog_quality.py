from pathlib import Path

from verdatrace.catalog import profile_dataset
from verdatrace.ingestion import iter_records
from verdatrace.models import SemanticType
from verdatrace.quality import evaluate_quality

FIXTURES = Path(__file__).parent / "fixtures"


def _codes(report):
    return {issue.code for issue in report.issues}


def test_schema_detection_uses_values_as_evidence():
    profile = profile_dataset(
        [
            {"observed": "2024-01-01T00:00:00Z", "reading": "1.2"},
            {"observed": "2024-01-01T01:00:00Z", "reading": "2.3"},
            {"observed": "2024-01-01T02:00:00Z", "reading": "3.4"},
        ],
        dataset_id="value-evidence",
        source_format="csv",
    )
    observed = next(field for field in profile.fields if field.name == "observed")
    reading = next(field for field in profile.fields if field.name == "reading")
    assert observed.semantic_type == SemanticType.TIMESTAMP.value
    assert "parse as timestamps" in observed.evidence[0]
    assert reading.semantic_type == SemanticType.NUMERICAL.value


def test_quality_acceptance_cases_are_machine_readable():
    rows = list(iter_records(FIXTURES / "synthetic_sensor_quality_cases.csv", allowed_roots=[FIXTURES]))
    profile = profile_dataset(rows, dataset_id="quality-cases", source_format="csv")
    report = evaluate_quality(
        rows,
        profile,
        required_fields=["event_id", "event_timestamp", "latitude", "longitude"],
    )
    assert {
        "invalid_latitude",
        "invalid_longitude",
        "invalid_humidity",
        "missing_required_value",
        "missing_value",
        "duplicate_event",
    } <= _codes(report)
    assert report.status == "failed"
    assert report.valid_rows == 1


def test_broken_polygon_is_invalid_geometry():
    rows = list(iter_records(FIXTURES / "broken_polygon.geojson", allowed_roots=[FIXTURES]))
    profile = profile_dataset(rows, dataset_id="broken", source_format="geojson")
    report = evaluate_quality(rows, profile)
    issue = next(issue for issue in report.issues if issue.code == "invalid_geometry")
    assert issue.severity == "error"
    assert "self-intersects" in issue.observed[0]


def test_domain_ranges_are_only_applied_when_configured():
    rows = [
        {"event_id": "1", "event_timestamp": "2024-01-01T00:00:00Z", "temperature_c": 200},
        {"event_id": "2", "event_timestamp": "2024-01-01T01:00:00Z", "temperature_c": 201},
    ]
    profile = profile_dataset(rows, dataset_id="unknown-sensor", source_format="json")
    unconstrained = evaluate_quality(rows, profile)
    constrained = evaluate_quality(rows, profile, domain_constraints={"temperature_c": (-50, 80)})
    assert "domain_range_violation" not in _codes(unconstrained)
    assert "domain_range_violation" in _codes(constrained)
