# Multi-dataset target design

## Decision summary

Wave 0 found no reason for a framework or pipeline rewrite. `MultimodalPipeline.run()` remains the single analytical orchestration path. The smallest clean extension is a typed configuration/registry layer in front of it, a thin registered-dataset runner that selects the existing ingestion adapter, and a registry-driven demo serializer. The existing single-page frontend remains one reusable workspace with capability-aware, nullable rendering.

This design preserves both current datasets and their stable IDs:

- `open_meteo_cairo_historical` — Cairo Historical Weather;
- `synthetic_refrigerated_route` — Synthetic Refrigerated Shipment Route.

Derived profile counts, quality scores, suitability scores, analytics, and recommendations continue to come from source records and existing pipeline logic. They are never configuration values.

## Dataset Registry

### Location and discovery

Executable definitions live as one dataset per file under:

```text
config/datasets/*.yaml
```

Discovery is deterministic by path name. A `DatasetRegistry` parses every `*.yaml` file, validates each definition, rejects duplicate IDs across files, and exposes iteration, length, IDs, and exact-ID lookup. Invalid files fail the whole discovery/build; the portal must never publish a silently partial registry.

`config/datasets.json` remains a provenance/candidate catalog during migration. It is not the executable registry and is not silently interpreted as one.

### Security boundary

Local `source.path` values are repository-relative. Resolution must remain within the caller-supplied project/approved root and must identify an existing regular file. Source format must be supported by the existing ingestion boundary. Registry files cannot grant broader filesystem access, roles, or credentials.

## Dataset configuration schema

The initial version is `verdatrace_dataset_config_v1` and follows existing frozen-dataclass conventions.

```yaml
schema_version: verdatrace_dataset_config_v1
id: open_meteo_cairo_historical
name: Cairo historical weather
domain: climate_environmental
enabled: true
task: climate
source:
  path: data/samples/example.json
  format: json
  dataset_type: tabular
  fixture: false
  provider: not_provided
  original_url: ""
  retrieved_at: not_provided
  license: not_provided
  geographic_coverage: unknown
  temporal_coverage: unknown
  crs: null
  original_schema: {}
  transformations: []
  limitations: []
required_fields:
  - event_id
quality:
  domain_constraints: {}
  telemetry_max_age_seconds: null
governance:
  owner: not_provided
  sensitivity: not_provided
  retention_policy: not_provided
```

Required validation:

- non-empty `id`, unique within a registry;
- non-empty `name` and `domain`;
- `source` is an object and its local path exists inside the approved root;
- `source.format` is one of the formats advertised by existing ingestion (`csv`, `json`, `ndjson`, `geojson`, `tif`, `tiff`, `cog`, `netcdf`, `zarr`), with executable record ingestion limited explicitly where raster support is not implemented;
- an optional boolean `enabled` defaults to `true`; disabled retrieval plans may point to an unavailable source but are validated and never executed/published;
- `source.dataset_type` is one of `tabular`, `vector`, `raster`, or `streaming`;
- `task` is one of the task names already understood by analytics/evaluation (`auto`, `general`, `descriptive`, `time_series`, `sensor`, `climate`, `spatial`, `mobility`, or `correlation`);
- `required_fields` is a list of unique, non-empty strings;
- quality ranges are field-keyed nullable minimum/maximum pairs, and freshness is a positive number of seconds when supplied;
- provenance/governance unknowns remain `unknown` or `not_provided`; validation never invents them.

Unknown top-level or nested keys are rejected in v1 so misspelled security, source, quality, or governance settings cannot be silently ignored.

## Generic onboarding flow

```text
discover config/datasets/*.yaml
  -> parse and validate all definitions
  -> resolve source within approved root
  -> existing iter_records adapter
  -> existing MultimodalPipeline.run
       profile -> quality -> analytics -> evaluation -> visualization
       + lineage + governance + audit
  -> add manifest/processing metadata
  -> serialize one normalized frontend dataset entry
  -> append to payload.datasets
```

`run_registered_dataset(config)` is a thin adapter, not a second pipeline. It converts configured source facts to the existing `Provenance`, forwards required fields and supported quality options, and calls `MultimodalPipeline.run()`. It returns the source records plus the existing typed `PipelineOutcome`; the manifest and optional `executive_kpis` list are part of that outcome. Disabled definitions fail closed if execution is attempted and are skipped by the demo builder.

Raster definitions can be discovered and described, but invoking them must fail with the existing explicit raster-worker error until a raster execution adapter exists.

## Frontend payload contract

The top-level contract remains backward compatible with `verdatrace_portal_payload_v1`:

```json
{
  "schema_version": "verdatrace_portal_payload_v1",
  "generated_at": "ISO-8601 UTC",
  "datasets": []
}
```

Each dataset entry is normalized as:

```json
{
  "id": "stable registry ID",
  "title": "display name",
  "domain": "registry domain",
  "dataset_type": "tabular|vector|raster|streaming",
  "fixture": false,
  "attribution": {
    "label": "provider or explicit fixture label",
    "url": "verified URL or null",
    "license": "verified value or not_provided"
  },
  "records": [],
  "outcome": {
    "manifest": {},
    "profile": {},
    "quality": {},
    "analysis": {},
    "evaluation": {},
    "visualization": {},
    "governance": {},
    "lineage": [],
    "audit_events": []
  },
  "preview": {
    "is_sample": false,
    "records_shown": 0,
    "record_count": 0,
    "strategy": "complete"
  }
}
```

`datasets` cardinality is unconstrained. A valid empty collection is rendered as an explicit empty catalog. Existing names (`title`, `records`, `outcome`) are retained so current consumers do not break.

The browser treats nested fields as nullable. Missing metrics render as unavailable, never zero. Search matches case-insensitive dataset name/title, ID, or domain. Domain and dataset-type filter values are generated from payload metadata; labels may map stable domain tokens to the requested human categories without filtering on dataset IDs.

Selection remains:

```text
Catalog -> select ID -> state.dataset -> rerender shared workspace
```

`?dataset=<id>` selects a known ID. Unknown IDs safely fall back to the first available dataset. User selection updates the URL with `history.replaceState`, preserving static GitHub Pages compatibility.

## Dataset manifest contract

Every `PipelineOutcome` includes one typed, JSON-safe `manifest`:

```json
{
  "dataset_id": "string",
  "dataset_name": "string",
  "provider": "string|null",
  "source_format": "string|null",
  "dataset_type": "string|null",
  "input_size": 123,
  "record_count": 72,
  "geometry_types": ["Point"],
  "crs": "EPSG:4326|null",
  "bounding_box": {"min_latitude": 0, "min_longitude": 0, "max_latitude": 0, "max_longitude": 0},
  "geographic_coverage": "string|null",
  "temporal_coverage": {"start": "...", "end": "..."},
  "license": "string|null",
  "ingestion_timestamp": "ISO-8601 UTC",
  "processing_timestamp": "ISO-8601 UTC",
  "fixture": false
}
```

`input_size` is bytes from the validated local file, not a benchmark or estimated dataset size. `record_count`, bounds, temporal coverage, and geometry types are derived from the records/profile. `crs` is included only when declared or supplied by a verified source configuration. Non-applicable or unknown fields are `null` (or an empty geometry-type list), not inferred by the frontend.

The frontend metadata component lists only populated values. Zero is retained only when it is an actual value.

## Processing metadata contract

Processing metadata remains on `AnalysisResult.analysis_metadata` and is supplemented by manifest timestamps and the existing lineage/audit records. At minimum it records:

- configured task and actual deterministic analysis method;
- input record count;
- quality reference and score;
- source/config identity through stable dataset ID;
- stage timestamps through lineage;
- ingestion and processing completion timestamps through the manifest;
- actor, outcome, target, and correlation ID through audit.

Volatile timestamps, UUIDs, and correlation IDs are intentionally excluded from byte-for-byte regression assertions. Stable behavior is compared structurally.

## Optional executive KPI contract

Executive KPIs are optional and absent by default. No current dataset defines them. If later supplied by a real analytical result, each item uses the typed contract:

```json
{
  "id": "stable_metric_id",
  "label": "Human label",
  "value": null,
  "unit": "verified unit",
  "status": null,
  "description": "calculation meaning",
  "source_metric": "analysis.metric.path",
  "analysis_stage": "analysis",
  "fields_used": ["field_name"],
  "calculation_description": "auditable calculation description"
}
```

KPIs must be computed or source-backed. The frontend renders no KPI card for an absent/unknown metric and never substitutes a benchmark, target, dataset size, business result, or zero.

## Future vector/raster adapter design

The registry source contract includes `dataset_type` so dispatch can grow without changing the analytical models.

- **Vector adapter:** keep GeoJSON on the existing `iter_records` path. A later optional Shapefile/GeoPackage adapter must normalize features to the same dictionaries, explicitly reproject to the configured CRS boundary, and report geometry types/bounds. The browser gets sibling Point, line, and polygon renderers selected by manifest/recommendation capability, not dataset ID.
- **Raster adapter:** retain `probe_geotiff` for bounded metadata validation. A future optional rasterio/GDAL worker returns a normalized raster descriptor (bands, CRS, bounds, resolution, nodata, statistics, render asset) without converting pixels into record dictionaries or loading the full raster in the web payload.
- **Streaming adapter:** a later bounded snapshot/pagination contract may populate the existing record-oriented pipeline, while the manifest identifies streaming source type and freshness. It must not grant administrative or broader ingestion privileges.

Until adapters exist, unsupported formats fail explicitly and do not appear as successfully processed portal datasets.

## Compatibility and implementation gates

1. Add typed models and registry validation with unit tests.
2. Add the two retained YAML entries and prove stable configuration semantics.
3. Add the thin registered runner and manifest while keeping all existing `MultimodalPipeline.run()` call sites valid through optional parameters.
4. Replace only `scripts/build_demo.py` dataset branches with registry iteration; preserve output schema and both current entries.
5. Add payload/regression tests, including a temporary third dataset and failure paths.
6. Add frontend boundary helpers, safe selection/query behavior, search, generated filters, and nullable manifest rendering; keep one HTML page and the current visual system.
7. Rebuild the committed payload and run Python, JavaScript, JSON, workflow, Terraform, container-availability, and static-site validation.

## Wave 0 evidence

This design consolidates:

- `docs/architecture/current_pipeline_audit.md`;
- `docs/architecture/dataset_hardcoding_audit.md`;
- `docs/architecture/frontend_dataset_audit.md`;
- `docs/architecture/quality_gap_analysis.md`;
- `docs/architecture/test_gap_analysis.md`.

No production module was changed during Wave 0. The baseline test run was 23 passed with one local Python 3.10 dependency-support warning.
