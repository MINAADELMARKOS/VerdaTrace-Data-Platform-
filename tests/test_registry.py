from pathlib import Path

import pytest

from verdatrace.errors import InvalidSchemaError, UnsupportedFormatError
from verdatrace.models import DatasetConfig
from verdatrace.registry import DatasetRegistry, load_dataset_config


def _write_source(root: Path, relative_path: str = "data/records.json") -> Path:
    source = root / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("[]", encoding="utf-8")
    return source


def _definition(
    dataset_id: str = "example",
    *,
    source_path: str = "data/records.json",
    source_format: str = "json",
    task: str = "general",
    required_fields: str = "[]",
    extra: str = "",
) -> str:
    return f"""\
schema_version: verdatrace_dataset_config_v1
id: {dataset_id}
name: Example dataset
domain: environmental
task: {task}
source:
  path: {source_path}
  format: {source_format}
  dataset_type: tabular
required_fields: {required_fields}
{extra}"""


def _write_config(root: Path, name: str, body: str) -> Path:
    directory = root / "config" / "datasets"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_registry_loads_minimal_config_with_typed_defaults_and_deterministic_order(tmp_path):
    _write_source(tmp_path)
    _write_config(tmp_path, "b.yaml", _definition("second"))
    first = _definition(
        "first",
        task="sensor",
        required_fields="[event_id, observed_at]",
        extra="""\
quality:
  domain_constraints:
    humidity:
      minimum: 0
      maximum: 100
  telemetry_max_age_seconds: 3600
governance:
  owner: data-team
""",
    )
    _write_config(tmp_path, "a.yaml", first)

    registry = DatasetRegistry.discover(tmp_path / "config" / "datasets", project_root=tmp_path)

    assert registry.ids == ("first", "second")
    assert isinstance(registry[0], DatasetConfig)
    assert registry.get("first").source.path == "data/records.json"
    assert registry.get("first").required_fields == ["event_id", "observed_at"]
    assert registry.get("first").quality.domain_constraints == {"humidity": (0.0, 100.0)}
    assert registry.get("first").quality.telemetry_max_age_seconds == 3600.0
    assert registry.get("first").governance.owner == "data-team"
    assert registry.get("second").governance.owner == "not_provided"


def test_registry_rejects_duplicate_dataset_ids(tmp_path):
    _write_source(tmp_path)
    _write_config(tmp_path, "a.yaml", _definition("duplicate"))
    _write_config(tmp_path, "b.yaml", _definition("duplicate"))

    with pytest.raises(InvalidSchemaError, match="duplicate dataset ID"):
        DatasetRegistry.discover(tmp_path / "config" / "datasets", project_root=tmp_path)


def test_registry_rejects_malformed_yaml(tmp_path):
    _write_source(tmp_path)
    _write_config(tmp_path, "bad.yaml", "id: [unterminated")

    with pytest.raises(InvalidSchemaError, match="valid YAML"):
        DatasetRegistry.discover(tmp_path / "config" / "datasets", project_root=tmp_path)


@pytest.mark.parametrize("source_path", ["data/missing.json", "../outside.json"])
def test_registry_rejects_missing_source_and_path_traversal(tmp_path, source_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    config = _write_config(tmp_path, "source.yaml", _definition(source_path=source_path))

    with pytest.raises(InvalidSchemaError, match="source.path"):
        load_dataset_config(config, project_root=tmp_path)


@pytest.mark.parametrize("task", ["forecast_business_kpi", "", "MOBILITY_UNKNOWN"])
def test_registry_rejects_invalid_tasks(tmp_path, task):
    _write_source(tmp_path)
    config = _write_config(tmp_path, "task.yaml", _definition(task=task))

    with pytest.raises(InvalidSchemaError, match="task"):
        load_dataset_config(config, project_root=tmp_path)


@pytest.mark.parametrize(
    "required_fields",
    ["event_id", "[event_id, event_id]", "[event_id, '']", "[event_id, 3]"],
)
def test_registry_rejects_invalid_required_fields(tmp_path, required_fields):
    _write_source(tmp_path)
    config = _write_config(
        tmp_path,
        "required.yaml",
        _definition(required_fields=required_fields),
    )

    with pytest.raises(InvalidSchemaError, match="required_fields"):
        load_dataset_config(config, project_root=tmp_path)


def test_registry_rejects_unsupported_or_mismatched_source_formats(tmp_path):
    _write_source(tmp_path)
    unsupported = _write_config(tmp_path, "unsupported.yaml", _definition(source_format="parquet"))
    with pytest.raises(UnsupportedFormatError, match="parquet"):
        load_dataset_config(unsupported, project_root=tmp_path)

    mismatched = _write_config(tmp_path, "mismatched.yaml", _definition(source_format="csv"))
    with pytest.raises(InvalidSchemaError, match="extension"):
        load_dataset_config(mismatched, project_root=tmp_path)


@pytest.mark.parametrize(
    "quality",
    [
        "telemetry_max_age_seconds: 0",
        "telemetry_max_age_seconds: old",
        "domain_constraints: {humidity: {minimum: 101, maximum: 100}}",
        "domain_constraints: {humidity: {minimum: zero}}",
        "domain_constraints: {humidity: {minimum: .nan}}",
    ],
)
def test_registry_rejects_invalid_quality_configuration(tmp_path, quality):
    _write_source(tmp_path)
    config = _write_config(
        tmp_path,
        "quality.yaml",
        _definition(extra=f"quality:\n  {quality}\n"),
    )

    with pytest.raises(InvalidSchemaError, match="quality"):
        load_dataset_config(config, project_root=tmp_path)


def test_registry_rejects_unknown_keys(tmp_path):
    _write_source(tmp_path)
    config = _write_config(tmp_path, "unknown.yaml", _definition(extra="unexpected: true\n"))

    with pytest.raises(InvalidSchemaError, match="unknown keys"):
        load_dataset_config(config, project_root=tmp_path)


def test_disabled_retrieval_plan_can_reference_unavailable_source(tmp_path):
    config = _write_config(
        tmp_path,
        "deferred.yaml",
        """\
schema_version: verdatrace_dataset_config_v1
id: deferred
name: Deferred raster
domain: remote_sensing
enabled: false
task: spatial
required_fields: []
source:
  path: data/raw/scene.tif
  format: tif
  dataset_type: raster
quality: {}
governance: {}
""",
    )

    definition = load_dataset_config(config, project_root=tmp_path)

    assert definition.enabled is False
    assert definition.source.path == "data/raw/scene.tif"


def test_registry_rejects_non_https_frontend_attribution(tmp_path):
    _write_source(tmp_path)
    config = _write_config(
        tmp_path,
        "attribution.yaml",
        _definition(),
    )
    body = config.read_text(encoding="utf-8").replace(
        "  dataset_type: tabular",
        "  dataset_type: tabular\n  attribution_url: javascript:alert(1)",
    )
    config.write_text(body, encoding="utf-8")

    with pytest.raises(InvalidSchemaError, match="HTTPS URL"):
        load_dataset_config(config, project_root=tmp_path)
