"""Typed, deterministic discovery of repository-local dataset definitions."""

from __future__ import annotations

import math
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import yaml

from .errors import InvalidSchemaError, UnsupportedFormatError
from .models import DatasetConfig, DatasetGovernanceConfig, DatasetQualityConfig, DatasetSourceConfig

SCHEMA_VERSION = "verdatrace_dataset_config_v1"
SUPPORTED_SOURCE_FORMATS = {"csv", "json", "ndjson", "geojson", "tif", "tiff", "cog", "netcdf", "zarr"}
SUPPORTED_DATASET_TYPES = {"tabular", "vector", "raster", "streaming"}
SUPPORTED_TASKS = {
    "auto",
    "general",
    "descriptive",
    "time_series",
    "sensor",
    "climate",
    "spatial",
    "mobility",
    "correlation",
}

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "name",
    "domain",
    "source",
    "enabled",
    "task",
    "required_fields",
    "quality",
    "governance",
}
_SOURCE_KEYS = {
    "path",
    "format",
    "dataset_type",
    "dataset_name",
    "fixture",
    "provider",
    "original_url",
    "retrieved_at",
    "license",
    "geographic_coverage",
    "temporal_coverage",
    "crs",
    "original_schema",
    "transformations",
    "limitations",
    "attribution_label",
    "attribution_url",
}
_QUALITY_KEYS = {"domain_constraints", "telemetry_max_age_seconds"}
_RANGE_KEYS = {"minimum", "maximum"}
_GOVERNANCE_KEYS = {"owner", "sensitivity", "retention_policy"}
_FORMAT_SUFFIXES = {
    "csv": {".csv"},
    "json": {".json"},
    "ndjson": {".ndjson"},
    "geojson": {".geojson"},
    "tif": {".tif"},
    "tiff": {".tiff"},
    "cog": {".cog", ".tif", ".tiff"},
    "netcdf": {".nc", ".nc4", ".netcdf"},
    "zarr": {".zarr"},
}


def _invalid(message: str, config_path: Path, *, details: Optional[Dict[str, Any]] = None) -> InvalidSchemaError:
    context = {"config_path": str(config_path)}
    context.update(details or {})
    return InvalidSchemaError(
        message,
        corrective_action="Correct the dataset definition and reload the registry.",
        details=context,
    )


def _mapping(value: Any, label: str, config_path: Path) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"'{label}' must be an object", config_path)
    if not all(isinstance(key, str) for key in value):
        raise _invalid(f"'{label}' keys must be strings", config_path)
    return value


def _reject_unknown_keys(value: Mapping[str, Any], allowed: Set[str], label: str, config_path: Path) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _invalid(
            f"'{label}' contains unknown keys: {', '.join(unknown)}",
            config_path,
            details={"unknown_keys": unknown},
        )


def _string(
    value: Any,
    label: str,
    config_path: Path,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise _invalid(f"'{label}' must be {qualifier}", config_path)
    return value.strip()


def _string_list(value: Any, label: str, config_path: Path, *, unique: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise _invalid(f"'{label}' must be a list", config_path)
    items = [_string(item, f"{label}[]", config_path) for item in value]
    if unique and len(set(items)) != len(items):
        raise _invalid(f"'{label}' must contain unique field names", config_path)
    return items


def _optional_string(value: Any, label: str, config_path: Path) -> Optional[str]:
    if value is None:
        return None
    return _string(value, label, config_path)


def _optional_https_url(value: Any, label: str, config_path: Path) -> Optional[str]:
    url = _optional_string(value, label, config_path)
    if url is None:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise _invalid(f"'{label}' must be an HTTPS URL", config_path)
    return url


def _number_or_none(value: Any, label: str, config_path: Path) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"'{label}' must be a number or null", config_path)
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(f"'{label}' must be finite", config_path)
    return number


def _parse_source(
    value: Any,
    config_path: Path,
    project_root: Path,
    *,
    require_exists: bool = True,
) -> DatasetSourceConfig:
    source = _mapping(value, "source", config_path)
    _reject_unknown_keys(source, _SOURCE_KEYS, "source", config_path)

    raw_path = _string(source.get("path"), "source.path", config_path)
    relative_path = Path(raw_path)
    if relative_path.is_absolute():
        raise _invalid("'source.path' must be repository-relative", config_path)
    resolved_path = (project_root / relative_path).resolve()
    if resolved_path != project_root and project_root not in resolved_path.parents:
        raise _invalid(
            "'source.path' resolves outside the project root",
            config_path,
            details={"source_path": raw_path},
        )
    if require_exists and not resolved_path.is_file():
        raise _invalid(
            "'source.path' must reference an existing regular file",
            config_path,
            details={"source_path": raw_path},
        )

    source_format = _string(source.get("format"), "source.format", config_path).lower()
    if source_format not in SUPPORTED_SOURCE_FORMATS:
        raise UnsupportedFormatError(
            f"unsupported dataset source format: {source_format}",
            corrective_action=f"Use one of: {', '.join(sorted(SUPPORTED_SOURCE_FORMATS))}.",
            details={"config_path": str(config_path), "source_path": raw_path},
        )
    if resolved_path.suffix.lower() not in _FORMAT_SUFFIXES[source_format]:
        raise _invalid(
            "'source.format' does not match the source file extension",
            config_path,
            details={"source_format": source_format, "suffix": resolved_path.suffix.lower()},
        )

    dataset_type = _string(source.get("dataset_type"), "source.dataset_type", config_path).lower()
    if dataset_type not in SUPPORTED_DATASET_TYPES:
        raise _invalid(
            f"unsupported source dataset type: {dataset_type}",
            config_path,
            details={"supported": sorted(SUPPORTED_DATASET_TYPES)},
        )

    fixture = source.get("fixture", False)
    if not isinstance(fixture, bool):
        raise _invalid("'source.fixture' must be a boolean", config_path)

    original_schema = _mapping(source.get("original_schema", {}), "source.original_schema", config_path)
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in original_schema.items()):
        raise _invalid("'source.original_schema' must map strings to strings", config_path)

    return DatasetSourceConfig(
        path=relative_path.as_posix(),
        format=source_format,
        dataset_type=dataset_type,
        dataset_name=_optional_string(source.get("dataset_name"), "source.dataset_name", config_path),
        fixture=fixture,
        provider=_string(source.get("provider", "not_provided"), "source.provider", config_path),
        original_url=_string(source.get("original_url", ""), "source.original_url", config_path, allow_empty=True),
        retrieved_at=_string(source.get("retrieved_at", "not_provided"), "source.retrieved_at", config_path),
        license=_string(source.get("license", "not_provided"), "source.license", config_path),
        geographic_coverage=_string(
            source.get("geographic_coverage", "unknown"),
            "source.geographic_coverage",
            config_path,
        ),
        temporal_coverage=_string(
            source.get("temporal_coverage", "unknown"),
            "source.temporal_coverage",
            config_path,
        ),
        crs=_optional_string(source.get("crs"), "source.crs", config_path),
        original_schema=dict(original_schema),
        transformations=_string_list(
            source.get("transformations", []),
            "source.transformations",
            config_path,
        ),
        limitations=_string_list(source.get("limitations", []), "source.limitations", config_path),
        attribution_label=_optional_string(source.get("attribution_label"), "source.attribution_label", config_path),
        attribution_url=_optional_https_url(source.get("attribution_url"), "source.attribution_url", config_path),
    )


def _parse_quality(value: Any, config_path: Path) -> DatasetQualityConfig:
    quality = _mapping(value, "quality", config_path)
    _reject_unknown_keys(quality, _QUALITY_KEYS, "quality", config_path)
    raw_constraints = _mapping(quality.get("domain_constraints", {}), "quality.domain_constraints", config_path)
    constraints: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for raw_field, raw_range in raw_constraints.items():
        field = _string(raw_field, "quality.domain_constraints field", config_path)
        range_value = _mapping(raw_range, f"quality.domain_constraints.{field}", config_path)
        _reject_unknown_keys(range_value, _RANGE_KEYS, f"quality.domain_constraints.{field}", config_path)
        minimum = _number_or_none(
            range_value.get("minimum"),
            f"quality.domain_constraints.{field}.minimum",
            config_path,
        )
        maximum = _number_or_none(
            range_value.get("maximum"),
            f"quality.domain_constraints.{field}.maximum",
            config_path,
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise _invalid(
                f"quality range minimum exceeds maximum for '{field}'",
                config_path,
            )
        constraints[field] = (minimum, maximum)

    freshness = _number_or_none(
        quality.get("telemetry_max_age_seconds"),
        "quality.telemetry_max_age_seconds",
        config_path,
    )
    if freshness is not None and freshness <= 0:
        raise _invalid("'quality.telemetry_max_age_seconds' must be positive", config_path)
    return DatasetQualityConfig(
        domain_constraints=constraints,
        telemetry_max_age_seconds=freshness,
    )


def _parse_governance(value: Any, config_path: Path) -> DatasetGovernanceConfig:
    governance = _mapping(value, "governance", config_path)
    _reject_unknown_keys(governance, _GOVERNANCE_KEYS, "governance", config_path)
    return DatasetGovernanceConfig(
        owner=_string(governance.get("owner", "not_provided"), "governance.owner", config_path),
        sensitivity=_string(
            governance.get("sensitivity", "not_provided"),
            "governance.sensitivity",
            config_path,
        ),
        retention_policy=_string(
            governance.get("retention_policy", "not_provided"),
            "governance.retention_policy",
            config_path,
        ),
    )


def load_dataset_config(config_path: str | Path, *, project_root: str | Path) -> DatasetConfig:
    """Parse and validate one versioned YAML dataset definition."""

    path = Path(config_path).resolve()
    root = Path(project_root).resolve()
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise _invalid("dataset configuration is not readable valid YAML", path) from exc

    definition = _mapping(raw, "dataset configuration", path)
    _reject_unknown_keys(definition, _TOP_LEVEL_KEYS, "dataset configuration", path)
    schema_version = _string(definition.get("schema_version"), "schema_version", path)
    if schema_version != SCHEMA_VERSION:
        raise _invalid(
            f"unsupported dataset configuration schema version: {schema_version}",
            path,
            details={"supported": SCHEMA_VERSION},
        )

    task = _string(definition.get("task", "general"), "task", path).lower()
    if task not in SUPPORTED_TASKS:
        raise _invalid(
            f"unsupported dataset task: {task}",
            path,
            details={"supported": sorted(SUPPORTED_TASKS)},
        )

    required_fields = _string_list(
        definition.get("required_fields", []),
        "required_fields",
        path,
        unique=True,
    )
    enabled = definition.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _invalid("'enabled' must be a boolean", path)
    return DatasetConfig(
        id=_string(definition.get("id"), "id", path),
        name=_string(definition.get("name"), "name", path),
        domain=_string(definition.get("domain"), "domain", path),
        source=_parse_source(definition.get("source"), path, root, require_exists=enabled),
        enabled=enabled,
        task=task,
        required_fields=required_fields,
        quality=_parse_quality(definition.get("quality", {}), path),
        governance=_parse_governance(definition.get("governance", {}), path),
        schema_version=schema_version,
    )


class DatasetRegistry(Sequence[DatasetConfig]):
    """An immutable-by-convention, deterministically ordered dataset collection."""

    def __init__(self, definitions: Sequence[DatasetConfig]) -> None:
        by_id: Dict[str, DatasetConfig] = {}
        for definition in definitions:
            if definition.id in by_id:
                raise InvalidSchemaError(
                    f"duplicate dataset ID: {definition.id}",
                    corrective_action="Assign a unique ID to every dataset definition.",
                    details={"dataset_id": definition.id},
                )
            by_id[definition.id] = definition
        self._definitions = tuple(definitions)
        self._by_id = by_id

    @classmethod
    def discover(
        cls,
        config_directory: str | Path,
        *,
        project_root: str | Path,
    ) -> "DatasetRegistry":
        directory = Path(config_directory).resolve()
        if not directory.is_dir():
            raise InvalidSchemaError(
                "dataset configuration directory does not exist",
                corrective_action="Create the configured registry directory before discovery.",
                details={"config_directory": str(directory)},
            )
        definitions = [
            load_dataset_config(path, project_root=project_root)
            for path in sorted(directory.glob("*.yaml"), key=lambda item: item.name)
        ]
        return cls(definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self) -> Iterator[DatasetConfig]:
        return iter(self._definitions)

    def __getitem__(self, index: int | slice) -> DatasetConfig | tuple[DatasetConfig, ...]:
        return self._definitions[index]

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(definition.id for definition in self._definitions)

    def get(self, dataset_id: str) -> DatasetConfig:
        try:
            return self._by_id[dataset_id]
        except KeyError as exc:
            raise KeyError(f"unknown dataset ID: {dataset_id}") from exc
