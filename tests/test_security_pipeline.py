from pathlib import Path

import pytest

from verdatrace.errors import AuthorizationError
from verdatrace.ingestion import iter_records
from verdatrace.models import Provenance
from verdatrace.pipeline import MultimodalPipeline
from verdatrace.security import AuditRecorder, authorize

FIXTURES = Path(__file__).parent / "fixtures"


def test_read_only_role_cannot_ingest_or_analyze():
    authorize("viewer", "catalog:read")
    with pytest.raises(AuthorizationError):
        authorize("viewer", "dataset:ingest")
    with pytest.raises(AuthorizationError):
        authorize("ingestor", "analysis:execute")


def test_audit_recorder_redacts_secret_like_details():
    recorder = AuditRecorder()
    event = recorder.record(
        actor="svc",
        operation="ingest",
        target="dataset",
        outcome="failed",
        details={"api_token": "do-not-log", "count": 2},
    )
    assert event.details["api_token"] == "[REDACTED]"
    assert event.details["count"] == 2


def test_end_to_end_ingest_classify_quality_analyze_evaluate_visualize():
    records = list(iter_records(FIXTURES / "synthetic_mobility_route.geojson", allowed_roots=[FIXTURES]))
    outcome = MultimodalPipeline(actor="integration-test", role="steward").run(
        records,
        dataset_id="integration-route",
        dataset_name="Integration route",
        source_format="geojson",
        provenance=Provenance(
            dataset_name="Synthetic integration route",
            provider="test suite",
            original_url="repository://synthetic_mobility_route.geojson",
            retrieved_at="not_applicable",
            source_format="GeoJSON",
            limitations=["Synthetic test fixture; not real operational data."],
        ),
        task="mobility",
        required_fields=["event_id", "event_timestamp", "latitude", "longitude"],
    )
    assert {"logistics", "mobility", "geospatial_vector"} <= set(outcome.profile.categories)
    assert outcome.quality.status == "passed"
    assert outcome.evaluation.eligible
    assert outcome.visualization.eligible
    assert any(item.type == "route_map" for item in outcome.visualization.recommended_visualizations)
    assert [step["stage"] for step in outcome.lineage] == [
        "raw_ingestion",
        "schema_discovery",
        "quality_checks",
        "analysis",
        "evaluation",
        "visualization",
    ]
    assert {event.operation for event in outcome.audit_events} >= {
        "dataset_ingestion",
        "quality_evaluation",
        "analysis_execution",
    }


def test_pipeline_enforces_role_boundary():
    with pytest.raises(AuthorizationError):
        MultimodalPipeline(actor="viewer", role="viewer").run(
            [],
            dataset_id="forbidden",
            dataset_name="Forbidden",
            source_format="json",
            provenance=Provenance(
                dataset_name="x",
                provider="x",
                original_url="repository://x",
                retrieved_at="not_applicable",
            ),
        )


def test_pipeline_audit_events_are_scoped_to_one_execution():
    recorder = AuditRecorder()
    pipeline = MultimodalPipeline(actor="scope-test", role="steward", audit=recorder)
    provenance = Provenance(
        dataset_name="scope",
        provider="test",
        original_url="repository://scope",
        retrieved_at="not_applicable",
    )
    first = pipeline.run([{"event_id": "first-row", "value": 1}], dataset_id="first", dataset_name="first", source_format="json", provenance=provenance)
    second = pipeline.run([{"event_id": "second-row", "value": 2}], dataset_id="second", dataset_name="second", source_format="json", provenance=provenance)
    assert first.audit_events
    assert second.audit_events
    assert {event.target for event in first.audit_events} == {"first"}
    assert {event.target for event in second.audit_events} == {"second"}
