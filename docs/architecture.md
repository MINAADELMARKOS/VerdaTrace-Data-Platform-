# Architecture and implementation map

## Repository discovery

The repository originally contained a single Python Pub/Sub worker, GCP SDK clients, a BigQuery/GCS target, Terraform, a GKE deployment, Kaggle-to-Pub/Sub loader, static Nginx portal, and pytest tests. There was no application database, HTTP API, GIS library, charting library, authentication service, orchestration engine, or server-side web framework.

The existing architectural intent was retained:

- Python and standard-library-first domain logic;
- GCP Pub/Sub for event ingestion;
- GKE for the long-running worker;
- BigQuery for curated analytics storage;
- Cloud Storage for controlled raw evidence;
- Secret Manager, KMS, IAM, DLP, Logging, and Monitoring for controls;
- static frontend deployment;
- pytest for automated validation;
- environment variables for runtime configuration.

The checked-out repository head also contained merge corruption: duplicated Python declarations and docstrings, invalid JSON samples, conflicting repeated Terraform attributes, duplicate Kubernetes object fields, and duplicated HTML. Those files had to be normalized before any reliable extension was possible.

## Implementation map

| Requested layer/capability | Existing component extended | Module |
| --- | --- | --- |
| Dataset registry/onboarding | Versioned repository-local configuration and deterministic discovery | `verdatrace/registry.py`, `config/datasets/*.yaml` |
| Registered execution | Thin adapter to existing ingestion and pipeline layers | `verdatrace/registered.py` |
| Ingestion | Pub/Sub worker, Kaggle CSV publisher, and streaming OSM PBF adapter | `verdatrace/ingestion.py`, `verdatrace/osm.py`, `scripts/kaggle_to_pubsub.py` |
| Schema discovery/catalog | New pure layer adjacent to transformations | `verdatrace/catalog.py` |
| Quality | Existing row flags generalized to dataset reports, spatial checks, routing, and quarantine | `verdatrace/quality.py` and compatible flags in `data_pipeline.py` |
| Analysis | New pure layer | `verdatrace/analytics.py` |
| Evaluation | New pure layer | `verdatrace/evaluation.py` |
| Normalized results | Typed dataclasses | `verdatrace/models.py` |
| Visualization intelligence | New pure deterministic rules | `verdatrace/visualization.py` |
| Spatial visualization | Existing static portal extended with Leaflet | `frontend/index.html`, `frontend/app.js` |
| Governance | Metadata carried beside results | `verdatrace/pipeline.py` |
| Authorization and audit | New cross-cutting service | `verdatrace/security.py` |
| Lineage | New cross-cutting graph | `verdatrace/lineage.py` |
| Storage/IAM | Existing Terraform resources repaired and narrowed | `main.tf` |
| Deployment hardening | Existing GKE manifest repaired | `deployment.yaml` |

## Layered flow

```
validated YAML registry definition
  ↓ registered source/provenance resolution
source
  ↓ bounded ingestion
raw ingestion
  ↓ schema discovery
catalog / classification
  ↓ deterministic checks
quality report
  ↓ record routing
valid / repairable / quarantined / rejected outcomes
  ↓ typed analytics
analysis result
  ↓ task readiness
evaluation
  ↓ safe chart/map rules
visualization recommendation
  ↓ normalized portal payload
interactive visualization
```

processing metrics and quarantine summaries are attached to the result; governance,
lineage, audit, and least-privilege authorization cross-cut every stage.

Each layer accepts plain records and typed results, and can be unit-tested without GCP. `MultimodalPipeline` composes the layers and adds audit/lineage events. `run_registered_dataset` prepares validated source, provenance, quality, governance, and manifest inputs and delegates to that existing pipeline. The portal payload is built by `scripts/build_demo.py` by iterating registry definitions rather than naming a fixed number of datasets.

## Executable dataset registry

`DatasetRegistry.discover` reads `*.yaml` files from `config/datasets/` in filename order. Each `verdatrace_dataset_config_v1` definition has top-level identity (`id`, `name`, `domain`), `task`, `required_fields`, `source`, optional `quality`, and optional `governance` sections. `source` carries a repository-relative path, format, dataset type, fixture flag, provenance, optional CRS, and optional presentation attribution. The quality section supports per-field numeric ranges and an optional positive telemetry maximum age. Governance carries owner, sensitivity, and retention policy.

Validation is fail-closed: files must be valid YAML; unknown keys are rejected; IDs must be unique across the discovered set; an enabled source must be an existing regular file inside the project root; its declared format must be supported and match the suffix; tasks and dataset types must use the supported enumerations; required fields must be a unique string list; numeric ranges must be finite and ordered; and attribution URLs, when supplied, must be HTTPS. A disabled retrieval plan may point at a not-yet-materialized source, but cannot execute or enter the portal payload.

The executable YAML registry is intentionally separate from the legacy `config/datasets.json` provenance catalog. The JSON catalog records evaluated retrieval-only candidates such as NYC TLC, Natural Earth, and the larger Kaggle sensor source. An entry there does not become executable until a compatible bounded source or adapter and a validated YAML definition exist.

`run_registered_dataset(config, project_root, actor, role)` in `verdatrace/registered.py` resolves the already-validated source, uses the existing `iter_records` ingestion path, constructs `Provenance`, and calls `MultimodalPipeline.run`. It passes task, required fields, quality constraints, freshness, governance, dataset type, actual file byte size, fixture status, and declared CRS; it does not duplicate profiling, quality, analytics, evaluation, visualization, lineage, or audit logic.

`scripts/build_demo.py` exposes `--project-root`, `--registry`, `--output`, `--actor`, and `--preview-limit`. By default it discovers `config/datasets/*.yaml` and writes `frontend/data/platform_demo.json`. Each registered result is converted to the existing v1 portal entry (`id`, `title`, `domain`, `dataset_type`, `fixture`, `attribution`, `records`, `preview`, and `outcome`), preserving static-site compatibility. The preview limit applies only to serialized browser records; the pipeline's source snapshot remains the basis for full-dataset analytics.

## Canonical model

The original BigQuery columns remain. Nullable multimodal columns add dataset identity, devices/routes/origins/destinations, WGS84 coordinates, speed/heading, environmental measurements, geometry JSON, CRS, and schema version.

Typed Python contracts include:

- `Provenance`;
- `DatasetSourceConfig`, `DatasetQualityConfig`, `DatasetGovernanceConfig`, and `DatasetConfig`;
- `FieldProfile` and `DatasetProfile`;
- `DatasetManifest`;
- `QualityIssue` and `QualityReport`;
- `ProcessingMetrics` and bounded `QuarantineRecord`;
- `AnalysisResult`;
- `ExecutiveKPI`;
- `EvaluationReport`;
- `VisualizationSpec` and `VisualizationRecommendation`;
- `PipelineOutcome`.

Raster-specific adapters use `RasterProfile`, `RasterQualityReport`, `RasterBandStatistics`, and `RasterAnalysisResult` without forcing pixel data into the record-oriented contracts.

No downstream UI depends on pandas, BigQuery row objects, Leaflet objects, or another implementation-specific analytical object.

## Processing metadata and portal contract

Every `PipelineOutcome` contains `manifest`, `profile`, `quality`, `analysis`, `evaluation`, `visualization`, `governance`, `lineage`, `audit_events`, measured `processing` counters, bounded `quarantine` records, and an optional `executive_kpis` list. The manifest normalizes:

- dataset ID and display name;
- provider, source format, and dataset type;
- input byte size and record count;
- observed geometry types, declared/observed CRS, and computed bounding box;
- geographic and computed temporal coverage;
- license;
- ingestion and processing timestamps;
- fixture status.

Values are derived from validated configuration, file metadata, the source provenance, observed records, and audit timestamps. Unknown provider, coverage, and license markers become `null` in the manifest, and non-applicable fields such as geometry types, CRS, or bounding box remain empty or `null`. The platform does not estimate dataset sizes, coverage, benchmarks, or business KPIs. `input_size` is the actual registered source file size in bytes; `record_count`, geometry types, bounds, and temporal coverage are computed from the processed records.

The portal treats `payload.datasets` as an arbitrary-length collection. It supports catalog search by name/ID/domain, metadata-generated domain and type filters, an empty-catalog state, safe fallback for an unknown `?dataset=<id>` parameter, URL updates on selection, capability-aware map/trend controls, and a manifest panel that renders only known values.

Executive KPI cards are rendered only when a result contains typed `ExecutiveKPI` values. Each KPI can expose a source metric, analysis stage, fields used, and calculation description; an absent KPI list hides the section.

Processing counters are facts measured by the run. Input bytes come from the registered source when available; output bytes remain `null` unless an output writer reports them. Quality routing never auto-repairs records: warning-only findings are `REPAIRABLE`, configured fatal findings are `REJECTED`, and other quality errors are `QUARANTINED`. Quarantine records contain only a bounded identifier, issue code, field, safe observed-value summary, reason, and processing timestamp.

## Spatial choices

No server-side GIS stack existed. Adding PostGIS, GeoServer, or a distributed raster engine would have created a parallel platform. The implementation therefore uses:

- GeoJSON and WGS84 coordinate ingestion;
- bounds and geometry validity checks;
- simple point/line/polygon validation;
- BigQuery JSON geometry compatibility and a path to BigQuery GIS;
- Leaflet only in the browser for lightweight embedded maps;
- a GeoTIFF signature/metadata boundary that fails explicitly when rasterio/GDAL is required.

For high-volume spatial workloads, extend BigQuery with `GEOGRAPHY` columns, use server-side filters/aggregates, and publish vector/raster tiles. Do not send full operational datasets to the portal.

The current vector path supports bounded GeoJSON, OSM PBF normalization, and lightweight point/line/polygon rendering. Polygon ingestion can be profiled and recommended, but production polygon visualization still needs capability-specific frontend layers, simplification, and server-side tiling for scale. Raster definitions support an explicit `enabled: false` retrieval-plan state for COG, NetCDF, Zarr, and unmaterialized GeoTIFF sources; the `verdatrace.raster` module provides the common profile/quality/chunked-statistics boundary and metadata-only STAC extraction. Pixel-backed raster decoding, reprojection, and browser rendering require a separate GDAL/rasterio/xarray worker and object-storage delivery design. The OSM adapter is streaming and queue-bounded, but the shared pipeline currently materializes its normalized snapshot to preserve existing multi-pass contracts; large extracts therefore need persisted snapshots, aggregation, or tile adapters before onboarding.

## Cross-cutting controls

Authorization runs before ingestion, quality execution, and analysis. Governance is attached to every outcome. Audit events contain metadata only. Lineage references immutable logical resources rather than embedding rows. Structured errors include a stable code, message, corrective action, and bounded details.

## Deployment topology

```
Publishers / Cloud Run jobs
          ↓
     Pub/Sub topic ─────→ dead-letter topic
          ↓
 GKE worker with Workload Identity
      ↙                 ↘
GCS raw archive      BigQuery curated table

Secret Manager → worker
KMS → Pub/Sub, GCS, BigQuery service agents
Logging/Monitoring ← worker and GKE
```

The worker service account and GKE node service account are distinct. Permissions are bound at subscription, dataset, bucket, and secret scope whenever the GCP provider supports it.
