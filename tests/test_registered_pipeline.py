import shutil
from dataclasses import replace
from pathlib import Path

from scripts.build_demo import build_demo_payload
from verdatrace.models import DatasetQualityConfig, ExecutiveKPI, Provenance
from verdatrace.pipeline import MultimodalPipeline
from verdatrace.errors import InvalidSchemaError
from verdatrace.registered import run_registered_dataset
from verdatrace.registry import DatasetRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIRECTORY = PROJECT_ROOT / "config" / "datasets"


def _repository_registry() -> DatasetRegistry:
    return DatasetRegistry.discover(REGISTRY_DIRECTORY, project_root=PROJECT_ROOT)


def test_registered_cairo_and_route_preserve_complete_pipeline_behavior():
    registry = _repository_registry()
    cairo = run_registered_dataset(
        registry.get("open_meteo_cairo_historical"),
        project_root=PROJECT_ROOT,
        actor="regression-test",
    )
    route = run_registered_dataset(
        registry.get("synthetic_refrigerated_route"),
        project_root=PROJECT_ROOT,
        actor="regression-test",
    )

    assert len(cairo.records) == 72
    assert cairo.outcome.profile.row_count == 72
    assert cairo.outcome.quality.status == "passed"
    assert cairo.outcome.evaluation.task == "climate"
    assert cairo.outcome.evaluation.eligible is True
    assert {item.type for item in cairo.outcome.visualization.recommended_visualizations} >= {
        "line_chart",
        "point_map",
    }
    assert cairo.outcome.governance["source"] == "Open-Meteo"

    assert len(route.records) == 6
    assert route.outcome.profile.row_count == 6
    assert route.outcome.quality.status == "passed"
    assert route.outcome.evaluation.task == "mobility"
    assert route.outcome.evaluation.eligible is True
    assert "route_map" in {
        item.type for item in route.outcome.visualization.recommended_visualizations
    }
    assert [step["stage"] for step in route.outcome.lineage] == [
        "raw_ingestion",
        "schema_discovery",
        "quality_checks",
        "analysis",
        "evaluation",
        "visualization",
    ]


def test_registered_runner_adds_source_backed_nullable_manifest():
    registry = _repository_registry()
    cairo = run_registered_dataset(
        registry.get("open_meteo_cairo_historical"),
        project_root=PROJECT_ROOT,
    )
    route = run_registered_dataset(
        registry.get("synthetic_refrigerated_route"),
        project_root=PROJECT_ROOT,
    )

    cairo_manifest = cairo.outcome.manifest
    assert cairo_manifest.dataset_id == "open_meteo_cairo_historical"
    assert cairo_manifest.provider == "Open-Meteo"
    assert cairo_manifest.input_size == (
        PROJECT_ROOT / cairo.config.source.path
    ).stat().st_size
    assert cairo_manifest.record_count == len(cairo.records)
    assert cairo_manifest.geometry_types == []
    assert cairo_manifest.crs == "EPSG:4326"
    assert cairo_manifest.bounding_box == cairo.outcome.profile.geographic_bounds
    assert cairo_manifest.temporal_coverage == cairo.outcome.profile.temporal_coverage
    assert cairo_manifest.fixture is False
    assert cairo_manifest.ingestion_timestamp
    assert cairo_manifest.processing_timestamp

    assert route.outcome.manifest.dataset_type == "vector"
    assert route.outcome.manifest.geometry_types == ["Point"]
    assert route.outcome.manifest.crs == "EPSG:4326"
    assert route.outcome.manifest.fixture is True


def test_registered_runner_forwards_configured_quality_rules():
    base = _repository_registry().get("synthetic_refrigerated_route")
    constrained = replace(
        base,
        quality=DatasetQualityConfig(domain_constraints={"temperature_c": (0.0, 3.0)}),
    )

    result = run_registered_dataset(constrained, project_root=PROJECT_ROOT)

    assert result.outcome.quality.status == "failed"
    assert "domain_range_violation" in {
        issue.code for issue in result.outcome.quality.issues
    }


def test_disabled_registry_definition_cannot_be_executed():
    deferred = _repository_registry().get("sentinel2_greater_cairo_sample")

    try:
        run_registered_dataset(deferred, project_root=PROJECT_ROOT)
    except InvalidSchemaError as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("disabled dataset execution unexpectedly succeeded")


def test_executive_kpis_are_optional_typed_and_traceable():
    records = [{"event_id": "one", "metric": 4}, {"event_id": "two", "metric": 6}, {"event_id": "three", "metric": 8}]
    outcome = MultimodalPipeline(actor="kpi-test", role="steward").run(
        records,
        dataset_id="kpi-fixture",
        dataset_name="KPI fixture",
        source_format="json",
        provenance=Provenance(
            dataset_name="KPI fixture",
            provider="test",
            original_url="repository://tests",
            retrieved_at="not_applicable",
        ),
        task="descriptive",
        executive_kpis=[
            ExecutiveKPI(
                id="mean_metric",
                label="Mean metric",
                value=6.0,
                unit="units",
                status="observed",
                description="Mean of the configured metric.",
                source_metric="numeric_summaries.metric.mean",
                analysis_stage="analysis",
                fields_used=["metric"],
                calculation_description="Arithmetic mean over the three input records.",
            )
        ],
    )

    serialized = outcome.to_dict()
    assert serialized["executive_kpis"][0]["source_metric"] == "numeric_summaries.metric.mean"
    assert serialized["executive_kpis"][0]["fields_used"] == ["metric"]
    assert any(step["stage"] == "executive_kpis" for step in outcome.lineage)
    assert any(event.operation == "executive_kpi_generation" for event in outcome.audit_events)

    no_kpi = MultimodalPipeline(actor="kpi-test", role="steward").run(
        records,
        dataset_id="no-kpi-fixture",
        dataset_name="No KPI fixture",
        source_format="json",
        provenance=Provenance(
            dataset_name="No KPI fixture",
            provider="test",
            original_url="repository://tests",
            retrieved_at="not_applicable",
        ),
    )
    assert no_kpi.executive_kpis == []
    assert not any(step["stage"] == "executive_kpis" for step in no_kpi.lineage)


def test_demo_build_iterates_registry_and_accepts_a_third_dataset(tmp_path):
    for relative in (
        "data/samples/open_meteo_cairo_2024-01-01_2024-01-03.json",
        "tests/fixtures/synthetic_mobility_route.geojson",
        "config/datasets/open_meteo_cairo_historical.yaml",
        "config/datasets/synthetic_refrigerated_route.yaml",
    ):
        source = PROJECT_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    third_source = tmp_path / "data" / "samples" / "third.json"
    third_source.write_text(
        '[{"event_id":"3","value":7},{"event_id":"4","value":8},{"event_id":"5","value":9}]',
        encoding="utf-8",
    )
    (tmp_path / "config" / "datasets" / "third.yaml").write_text(
        """\
schema_version: verdatrace_dataset_config_v1
id: third_dataset
name: Third registered dataset
domain: infrastructure
task: descriptive
required_fields: [event_id]
source:
  path: data/samples/third.json
  format: json
  dataset_type: tabular
  fixture: true
quality: {}
governance: {}
""",
        encoding="utf-8",
    )

    payload = build_demo_payload(project_root=tmp_path)

    assert [dataset["id"] for dataset in payload["datasets"]] == [
        "open_meteo_cairo_historical",
        "synthetic_refrigerated_route",
        "third_dataset",
    ]
    assert len(payload["datasets"]) == len(
        DatasetRegistry.discover(
            tmp_path / "config" / "datasets",
            project_root=tmp_path,
        )
    )
    assert payload["datasets"][2]["outcome"]["manifest"]["record_count"] == 3


def test_portal_preview_is_bounded_and_explicitly_marked():
    registry = _repository_registry()
    result = run_registered_dataset(registry.get("open_meteo_cairo_historical"), project_root=PROJECT_ROOT)
    portal = result.to_portal_dict(preview_limit=2)
    assert len(portal["records"]) == 2
    assert portal["preview"] == {
        "is_sample": True,
        "records_shown": 2,
        "record_count": 72,
        "strategy": "head",
    }
    assert portal["outcome"]["manifest"]["record_count"] == 72


def test_z1_new_registered_dataset_reaches_every_governed_stage(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(
        '[{"event_id":"a","event_timestamp":"2024-01-01T00:00:00Z","value":1},'
        '{"event_id":"b","event_timestamp":"2024-01-01T01:00:00Z","value":2}]',
        encoding="utf-8",
    )
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "new.yaml").write_text(
        """\
schema_version: verdatrace_dataset_config_v1
id: z1_new_dataset
name: Z1 acceptance dataset
domain: infrastructure
task: descriptive
required_fields: [event_id]
source:
  path: input.json
  format: json
  dataset_type: tabular
  provider: acceptance-fixture
  original_url: repository://acceptance
  retrieved_at: not_applicable
  license: not_applicable_test_fixture
quality: {}
governance: {}
""",
        encoding="utf-8",
    )

    payload = build_demo_payload(project_root=tmp_path, registry_directory=registry_dir)
    dataset = payload["datasets"][0]
    outcome = dataset["outcome"]
    assert dataset["id"] == "z1_new_dataset"
    assert dataset["preview"]["is_sample"] is False
    assert all(key in outcome for key in ("manifest", "profile", "quality", "analysis", "evaluation", "visualization", "governance", "lineage"))
    assert [step["stage"] for step in outcome["lineage"] if step["stage"] != "executive_kpis"] == [
        "raw_ingestion", "schema_discovery", "quality_checks", "analysis", "evaluation", "visualization"
    ]
