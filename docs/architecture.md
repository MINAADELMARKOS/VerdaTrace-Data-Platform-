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
| Ingestion | Pub/Sub worker and Kaggle CSV publisher | `verdatrace/ingestion.py`, `scripts/kaggle_to_pubsub.py` |
| Schema discovery/catalog | New pure layer adjacent to transformations | `verdatrace/catalog.py` |
| Quality | Existing row flags generalized to dataset reports | `verdatrace/quality.py` and compatible flags in `data_pipeline.py` |
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
source
  ↓ provenance registration
raw ingestion
  ↓ schema discovery
catalog / classification
  ↓ deterministic checks
quality report
  ↓ typed analytics
analysis result
  ↓ task readiness
evaluation
  ↓ safe chart/map rules
visualization recommendation
  ↓ normalized portal payload
interactive visualization
```

Each layer accepts plain records and typed results, and can be unit-tested without GCP. `MultimodalPipeline` composes the layers and adds audit/lineage events. The portal payload is built by `scripts/build_demo.py` from pipeline outcomes.

## Canonical model

The original BigQuery columns remain. Nullable multimodal columns add dataset identity, devices/routes/origins/destinations, WGS84 coordinates, speed/heading, environmental measurements, geometry JSON, CRS, and schema version.

Typed Python contracts include:

- `Provenance`;
- `FieldProfile` and `DatasetProfile`;
- `QualityIssue` and `QualityReport`;
- `AnalysisResult`;
- `EvaluationReport`;
- `VisualizationSpec` and `VisualizationRecommendation`;
- `PipelineOutcome`.

No downstream UI depends on pandas, BigQuery row objects, Leaflet objects, or another implementation-specific analytical object.

## Spatial choices

No server-side GIS stack existed. Adding PostGIS, GeoServer, or a distributed raster engine would have created a parallel platform. The implementation therefore uses:

- GeoJSON and WGS84 coordinate ingestion;
- bounds and geometry validity checks;
- simple point/line/polygon validation;
- BigQuery JSON geometry compatibility and a path to BigQuery GIS;
- Leaflet only in the browser for lightweight embedded maps;
- a GeoTIFF signature/metadata boundary that fails explicitly when rasterio/GDAL is required.

For high-volume spatial workloads, extend BigQuery with `GEOGRAPHY` columns, use server-side filters/aggregates, and publish vector/raster tiles. Do not send full operational datasets to the portal.

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
