# Current pipeline audit

## Scope

This is a read-only Wave 0 audit of the current VerdaTrace execution path. It covers `pipeline.py`, the shared models, ingestion, profiling/cataloguing, quality, analytics, evaluation, visualization recommendation, lineage, authorization/auditing, and the governance record assembled by the pipeline. It does not propose a replacement architecture and does not change runtime behavior.

## Executive summary

`MultimodalPipeline.run` is already a reusable, dataset-ID-agnostic orchestration boundary. It accepts an iterable of normalized record dictionaries plus dataset metadata, then profiles, checks, analyzes, evaluates, recommends visualizations, records lineage, and assembles governance into one typed `PipelineOutcome` (`verdatrace/pipeline.py:27-39`, `verdatrace/pipeline.py:54-65`).

The actual ingestion adapter is **outside** that boundary: `run` receives records that a caller has already loaded. Local CSV/JSON/NDJSON/GeoJSON loading and allow-listed JSON retrieval are reusable services, but the pipeline does not select or invoke them (`verdatrace/ingestion.py:91-169`, `verdatrace/ingestion.py:210-249`, `verdatrace/pipeline.py:54-70`). GeoTIFF is recognized and can be header-probed, but it cannot enter the record-oriented pipeline without a raster-aware adapter (`verdatrace/ingestion.py:166-169`, `verdatrace/ingestion.py:185-202`).

No Cairo, refrigerated-route, or other concrete dataset ID is hard-coded in the audited core modules. Dataset references are derived from the caller-supplied `dataset_id` (`verdatrace/pipeline.py:58-64`, `verdatrace/pipeline.py:72-82`). The main constraints are instead implicit record, semantic, task, memory, and “first suitable field” assumptions documented below.

## Current execution flow

The requested logical flow and the implemented boundaries are:

```text
source/path/URL
  -> ingestion adapter (caller; outside MultimodalPipeline.run)
  -> iterable[dict[str, Any]]
  -> authorization + full materialization
  -> profile/classification
  -> quality
  -> analytics
  -> evaluation
  -> visualization recommendation
  -> lineage snapshot
  -> governance assembly
  -> PipelineOutcome
```

| Stage | Current implementation | Input contract | Output contract | Audit/lineage effect |
| --- | --- | --- | --- | --- |
| Ingestion | `iter_records`, `fetch_allowlisted_json`, or another caller-selected connector. `MultimodalPipeline.run` itself begins after records exist. | Approved local path or allow-listed HTTPS URL at adapter level; pipeline receives `Iterable[Dict[str, Any]]`. | Normalized dictionaries. GeoJSON features are flattened to properties plus `feature_id`, `geometry`, `crs`, and point coordinates. | Once `run` starts, records a `dataset_ingestion/start` audit event and a `raw_ingestion` lineage step; this describes the handoff, not the actual adapter call (`verdatrace/pipeline.py:69-82`). |
| Profile | `profile_dataset` | Materialized rows, `dataset_id`, `dataset_name`, `source_format`. | `DatasetProfile` containing field profiles, categories with confidence/evidence, bounds, and temporal coverage. | Adds `schema_discovery`, `raw:{id} -> catalog:{id}` (`verdatrace/pipeline.py:84-90`). |
| Quality | `evaluate_quality` | Rows, `DatasetProfile`, optional required field names. | `QualityReport` with score/status, issues, valid-row count, and metrics. | Adds `quality_checks`, `raw:{id} -> quality:{id}`, and a `quality_evaluation` audit event (`verdatrace/pipeline.py:92-101`). |
| Analytics | `analyze_dataset` | Rows, profile, quality report, provenance, task. | Normalized `AnalysisResult`. | Adds `analysis`, `quality:{id} -> analysis:{id}`, and an `analysis_execution` audit event (`verdatrace/pipeline.py:103-112`). |
| Evaluation | `evaluate_suitability` | Profile, quality, analysis, task. | `EvaluationReport` with eligibility, score, reasons, warnings, and named checks. | Adds `evaluation`, `analysis:{id} -> evaluation:{id}` (`verdatrace/pipeline.py:114-115`). |
| Visualization | `recommend_visualizations` | Profile and evaluation. | `VisualizationRecommendation` with deterministic specs, warnings, and unsupported fields. | Adds `visualization`, `evaluation:{id} -> visualization:{id}` (`verdatrace/pipeline.py:116-122`). |
| Lineage | `LineageTracker` is populated throughout the prior stages. | Stage/input/output/operation strings. | Ordered list of timestamped `LineageStep` dictionaries. | The current six steps are copied into `AnalysisResult.lineage`, then also returned as `PipelineOutcome.lineage` (`verdatrace/pipeline.py:123`, `verdatrace/pipeline.py:159`; `verdatrace/lineage.py:10-35`). |
| Governance | Inline `governance_record` assembly in `MultimodalPipeline.run`. | Provenance, profile categories, quality status, ingestion audit timestamp, and optional caller overrides. | Plain `Dict[str, Any]` on `PipelineOutcome`. | No governance lineage step or governance-specific audit event. A final `dataset_ingestion/succeeded` event is recorded after assembly (`verdatrace/pipeline.py:125-151`). |

### Ordering details

1. Three permissions are checked before data materialization: `dataset:ingest`, `quality:evaluate`, and `analysis:execute` (`verdatrace/pipeline.py:66-70`). The default `steward` role has all three; `viewer`, `analyst`, and `ingestor` individually do not (`verdatrace/pipeline.py:43-52`; `verdatrace/security.py:17-45`).
2. `rows = list(records)` fully materializes the input once in the orchestrator (`verdatrace/pipeline.py:70`). Profiling, quality, and analytics each materialize their received iterable again, although they receive this existing list (`verdatrace/catalog.py:206-214`, `verdatrace/quality.py:118-128`, `verdatrace/analytics.py:79-88`).
3. The final success audit event is recorded after governance is created, but `PipelineOutcome.audit_events` is a copy of the recorder’s complete in-memory history, not events filtered to the current correlation ID (`verdatrace/pipeline.py:140-160`; `verdatrace/security.py:82-110`). Reusing one pipeline/recorder therefore returns earlier-run events too.
4. There is no explicit “curated dataset” transformation stage between quality and analytics. The analytics warning states that failed-quality rows are not excluded (`verdatrace/analytics.py:209-212`).

## Data structures passed between stages

All primary analytical contracts are frozen dataclasses and are recursively converted to JSON-safe primitives through `to_dict` (`verdatrace/models.py:64-169`, `verdatrace/models.py:171-182`).

### Pipeline input

`MultimodalPipeline.run` accepts:

- `records: Iterable[Dict[str, Any]]`;
- required `dataset_id`, `dataset_name`, `source_format`, and `Provenance`;
- optional free-form `task`, `required_fields`, and governance dictionary (`verdatrace/pipeline.py:54-65`).

`Provenance` carries dataset/provider/URL/retrieval/license/coverage/format/schema/transformation/target-schema/limitation fields, with explicit `unknown` or `not_provided` defaults where applicable (`verdatrace/models.py:64-77`).

### Profile contract

`DatasetProfile` carries identity, row count, source format, field profiles, dataset categories with evidence/confidence, geographic bounds, and temporal coverage (`verdatrace/models.py:80-105`). Each `FieldProfile` contains the inferred primitive type, semantic type, completeness/cardinality counts, confidence/evidence, and at most three sample values (`verdatrace/catalog.py:206-234`).

### Quality contract

`QualityReport` contains dataset ID, row counts, a 0–100 score, status, structured `QualityIssue` entries, and aggregate quality metrics (`verdatrace/models.py:107-126`). Issue entries include a stable code, severity, message, optional field, up to 100 affected row indexes, observed samples, and rule (`verdatrace/quality.py:93-115`).

### Analysis contract

`AnalysisResult` normalizes implementation output into result type, computed values, dimensions, metric names, units, warnings, serialized provenance, a quality reference, analysis metadata, and lineage (`verdatrace/models.py:129-140`). The current analyzer always supplies `row_count` and `numeric_summaries`, and may add temporal aggregation/trend, mobility summary, spatial bounds, one correlation, and grouped statistics (`verdatrace/analytics.py:99-113`, `verdatrace/analytics.py:124-207`).

### Evaluation and visualization contracts

`EvaluationReport` carries the original task string, eligibility, a percentage score over seven generic checks, reasons, warnings, and the full check map (`verdatrace/evaluation.py:17-57`; `verdatrace/models.py:143-150`). `VisualizationRecommendation` contains the derived dataset type, evaluation-gated eligibility, a list of `VisualizationSpec` values, warnings, and unsupported fields (`verdatrace/models.py:153-168`, `verdatrace/visualization.py:200-215`).

### Final outcome

`PipelineOutcome` bundles the six typed outputs plus governance as an untyped dictionary, lineage as dictionaries, and audit events as typed dataclasses (`verdatrace/pipeline.py:27-39`).

## Dataset-specific and implicit assumptions

### Ingestion and record shape

- The shared analytical path is record-oriented. Every record is assumed to be a dictionary; CSV strings are not coerced during ingestion, and type interpretation occurs during profiling (`verdatrace/ingestion.py:101-108`, `verdatrace/catalog.py:112-124`).
- Local sources must be below an explicit approved root and have one of six suffixes. The allowed suffix set is fixed to CSV, JSON, NDJSON, GeoJSON, TIF, and TIFF (`verdatrace/ingestion.py:16-39`).
- JSON accepts an object, an array of objects, a `records` array, or GeoJSON `FeatureCollection`; other JSON shapes are rejected (`verdatrace/ingestion.py:130-164`).
- GeoJSON is restricted to EPSG:4326/CRS84 declarations. Missing CRS is assumed to be EPSG:4326, and other CRSs must be reprojected before ingestion (`verdatrace/ingestion.py:69-88`). Point features get convenience latitude/longitude fields; lines and polygons do not (`verdatrace/ingestion.py:42-66`).
- External JSON requires HTTPS, an exact allow-listed host, no redirects, a 5 MB default cap, and a 20-second timeout (`verdatrace/ingestion.py:205-249`).
- TIFF support is metadata-only and recognizes only the four-byte TIFF signature. CRS/bands/bounds require an external rasterio/GDAL worker (`verdatrace/ingestion.py:185-202`).

### Profiling and classification

- Field semantics combine hard-coded alias sets with value characteristics. Alias matches start from fixed confidences; latitude/longitude and time aliases receive additional range/parse evidence (`verdatrace/catalog.py:14-46`, `verdatrace/catalog.py:127-162`). Unmatched fields fall back to datetime, boolean, number, categorical, text, or unknown based on content (`verdatrace/catalog.py:164-177`).
- Primitive numeric/datetime inference requires at least 90% of populated values to parse. Low-cardinality strings are categorical when distinct values are at most `max(20, sqrt(n)+1)` (`verdatrace/catalog.py:112-124`, `verdatrace/catalog.py:169-176`).
- Field order is alphabetical, because names are collected into a set and sorted. This order later controls every “first field” choice in analytics and visualization (`verdatrace/catalog.py:213-216`).
- Dataset categories are deterministic combinations of source format, detected semantic fields, and several name tokens. Sensor/IoT needs at least two sensor fields or a sensor field plus device ID; mobility needs at least two mobility semantics; logistics can be inferred from origin/destination or shipment/warehouse/hub/port/carrier names (`verdatrace/catalog.py:247-277`).
- Geographic bounds require separate latitude and longitude semantics. Geometry-only vector data can be classified spatial but receives no profile bounding box (`verdatrace/catalog.py:180-194`, `verdatrace/catalog.py:251-252`).
- Temporal coverage combines every detected timestamp/date field rather than selecting a configured authoritative time field (`verdatrace/catalog.py:197-203`).

### Quality

- `MultimodalPipeline.run` passes only `required_fields` to quality. Existing `domain_constraints`, freshness age, and reference time parameters cannot currently be supplied through the orchestrator (`verdatrace/pipeline.py:92`; `verdatrace/quality.py:118-126`).
- Built-in semantic constraints are WGS84 coordinate ranges, 0–100% humidity, non-negative values for CO/CO2/LPG/smoke/particulate/rainfall, parseable timestamps, and supported GeoJSON geometry (`verdatrace/quality.py:145-267`). Temperature, pressure, speed, heading, distance, duration, NDVI, elevation, solar radiation, and wind have no universal range check unless caller-supplied domain constraints are used.
- Geometry validation supports Point, LineString, Polygon, and MultiPolygon only. Polygon validation checks closure, positions, WGS84 coordinate ranges, and simple ring self-intersection; it does not cover holes/topology validity beyond that algorithm (`verdatrace/quality.py:34-90`).
- Duplicate identity uses only the first identifier-semantic field; without one it uses a representation of the complete sorted record (`verdatrace/quality.py:289-315`).
- Outliers require at least eight valid numeric values, exclude latitude/longitude, and use three IQRs as a warning threshold (`verdatrace/quality.py:317-344`).
- Gaps and staleness use only the first timestamp field. Gaps need at least four parsed times and are flagged above three times the median interval (`verdatrace/quality.py:346-391`).
- Each error occurrence has an eight-point-per-row penalty and each warning a two-point penalty normalized by row count; any error forces failed status (`verdatrace/quality.py:393-413`). This is a platform rule, not a dataset benchmark.

### Analytics

- All numeric fields except latitude/longitude are summarized; failed rows are retained (`verdatrace/analytics.py:99-113`, `verdatrace/analytics.py:209-212`).
- Units are inferred from semantics and field-name suffixes/tokens. Unrecognized measurement units are explicitly `source_unit`; they are not recovered from provenance or configuration (`verdatrace/analytics.py:60-76`).
- Temporal analytics uses the first timestamp, else first date, and the first eligible numeric metric. It produces daily means and a simple last-minus-first change, not a fitted trend (`verdatrace/analytics.py:124-143`).
- Mobility totals/averages use the first detected distance, speed, and duration fields. Derived speed assumes distance per hour after treating duration as seconds, regardless of explicit unit metadata (`verdatrace/analytics.py:145-164`).
- Correlation is computed for only the first two eligible numeric fields and requires three paired values (`verdatrace/analytics.py:42-57`, `verdatrace/analytics.py:172-181`).
- Grouped statistics use the first categorical/device/vehicle field with at most 50 values and the first numeric field (`verdatrace/analytics.py:183-207`).
- `task="auto"` maps categories to mobility, sensor, spatial, or descriptive. Any other task string is accepted and used verbatim in `result_type` (`verdatrace/analytics.py:214-239`).

### Evaluation

- Seven checks are always scored equally, including checks not required by the selected task (`verdatrace/evaluation.py:17-29`, `verdatrace/evaluation.py:40-41`).
- Only exact task strings `time_series`, `sensor`, `climate`, `spatial`, `mobility`, `correlation`, and `descriptive` add task-specific requirements. An unknown/custom task requires only rows and an analysis result (`verdatrace/evaluation.py:32-38`).
- Eligibility requires every task-required check and quality score at least 40. This means a failed quality report can remain eligible when its score is at least 40, although a warning is added (`verdatrace/evaluation.py:47-49`).

### Visualization recommendation

- Recommendations are deterministic and UI-independent (`verdatrace/visualization.py:1-23`). They choose the first timestamp/date, latitude, longitude, geometry, route, vehicle, numeric, and categorical fields, inheriting alphabetical profile order (`verdatrace/visualization.py:24-53`).
- Point clustering is enabled at 100 rows; heatmap recommendation starts at 500 rows (`verdatrace/visualization.py:94-122`). These are rendering heuristics, not performance measurements.
- Route maps require point latitude/longitude plus time and route or vehicle semantics; a geometry LineString alone does not trigger `route_map` (`verdatrace/visualization.py:123-141`).
- Geometry type detection uses only up to three profile sample values. Polygon choropleths require a numeric field name containing `rate`, `ratio`, `percent`, `pct`, `density`, or `per_`; otherwise the engine recommends a polygon map and warns when numeric fields exist (`verdatrace/visualization.py:143-182`; sample limit at `verdatrace/catalog.py:232`).
- Raster recommendation depends only on the `geospatial_raster` category and can emit a spec with no fields even though the record pipeline does not process TIFF data (`verdatrace/visualization.py:184-193`).
- Specification generation and final eligibility are separate: specs may be returned even when `eligible` is false because eligibility is gated by the evaluation report at return time (`verdatrace/visualization.py:209-214`).

### Lineage, governance, authorization, and audit

- Lineage references are string conventions (`raw:{id}`, `catalog:{id}`, and so on), with process-time UTC timestamps. There is no persisted graph, entity type, run ID, parent dataset ID, or registry/config reference in `LineageStep` (`verdatrace/lineage.py:10-35`).
- The recorded graph has six stages: raw ingestion, schema discovery, quality checks, analysis, evaluation, and visualization. Governance is returned but not represented in lineage (`verdatrace/pipeline.py:82-139`).
- Governance is an untyped dictionary with fixed defaults: owner `unknown`, sensitivity/retention `not_provided`, and schema version `verdatrace_multimodal_v1`. Caller-supplied governance is expanded last and can override any default (`verdatrace/pipeline.py:125-139`).
- `source` in governance is the provenance provider, while the lineage source is the original URL or `source:{dataset_id}` fallback (`verdatrace/pipeline.py:72`, `verdatrace/pipeline.py:125-137`).
- Authorization is fail-closed for unknown roles and is enforced once at pipeline entry (`verdatrace/security.py:17-56`, `verdatrace/pipeline.py:66-68`). There is no per-stage dataset policy object.
- Audit details recursively redact keys matching secret/password/token/credential/API-key/raw-data patterns, and only bounded metadata is passed by this pipeline (`verdatrace/security.py:14-16`, `verdatrace/security.py:59-67`, `verdatrace/pipeline.py:74-81`). Exceptions after the start event do not currently create a failed completion event.

## Hard-coded IDs and constants

### Concrete dataset IDs

None. All resource references and audit targets interpolate the runtime `dataset_id`; no audited module names Cairo Historical Weather, Synthetic Refrigerated Route, or any other registered/example dataset (`verdatrace/pipeline.py:58-64`, `verdatrace/pipeline.py:72-82`, `verdatrace/pipeline.py:90-120`).

### Hard-coded platform conventions

- default actor `local-developer`, default role `steward` (`verdatrace/pipeline.py:43-52`);
- default task `general` at orchestration/evaluation, versus `auto` when the analyzer is called directly (`verdatrace/pipeline.py:62`, `verdatrace/analytics.py:85`, `verdatrace/evaluation.py:15`);
- namespaced lineage/reference strings and operation labels (`verdatrace/pipeline.py:72-123`);
- target schema/governance schema version `verdatrace_multimodal_v1` (`verdatrace/models.py:76`, `verdatrace/pipeline.py:134`);
- classification alias sets, category rules, confidence values, quality rules/penalties, task names, visualization thresholds, and normalized-metric name tokens in their respective modules.

These are shared platform policies rather than dataset-specific IDs, but a registry/config layer must either deliberately preserve them or expose narrowly scoped overrides.

## Shared reusable components

| Component | Reuse value | Boundary/caution |
| --- | --- | --- |
| `iter_records` / `iter_batches` | Safe local tabular/vector loading and bounded batching. | TIFF is intentionally excluded from record iteration; CSV values remain strings (`verdatrace/ingestion.py:91-182`). |
| `fetch_allowlisted_json` | Bounded SSRF-resistant JSON retrieval. | Returns raw decoded JSON, not normalized pipeline records (`verdatrace/ingestion.py:210-249`). |
| `profile_dataset` | Generic schema discovery and evidence-bearing classification. | Materializes input and depends on alias/heuristic policy (`verdatrace/catalog.py:206-290`). |
| `evaluate_quality` | Structured, independently testable tabular/temporal/sensor/vector checks. | Orchestrator exposes only required fields; other existing knobs need forwarding (`verdatrace/quality.py:118-126`, `verdatrace/pipeline.py:92`). |
| `analyze_dataset` | Generic descriptive, temporal, mobility, grouped, correlation, and spatial-bound analysis. | First-field selection and implicit duration/unit assumptions limit multi-measure datasets (`verdatrace/analytics.py:124-207`). |
| `evaluate_suitability` | Structured task readiness assessment. | Task vocabulary is implicit and unknown tasks fall back to generic requirements (`verdatrace/evaluation.py:32-49`). |
| `recommend_visualizations` | Deterministic UI-independent recommendation engine. | Returns specs separately from evaluation-gated eligibility (`verdatrace/visualization.py:20-23`, `verdatrace/visualization.py:209-215`). |
| `LineageTracker` | Small ordered provenance trail. | In-memory only; identifiers are string conventions (`verdatrace/lineage.py:19-35`). |
| `AuditRecorder` / `authorize` | Least-privilege entry check and secret-safe audit metadata. | Recorder accumulates across runs; failure events are not orchestrated (`verdatrace/security.py:49-110`). |
| `PipelineOutcome.to_dict` | Single JSON-ready boundary for builders/APIs/frontends. | Governance and lineage remain dictionary-shaped rather than typed (`verdatrace/pipeline.py:27-39`). |

## Minimal extension points for multi-dataset onboarding

These extension points preserve the current pipeline rather than duplicating it:

1. **Registry before orchestration.** A typed dataset definition can validate ID/name/source/format/task/required fields/quality/governance, select the existing ingestion adapter, and pass normalized records plus existing `Provenance` into `MultimodalPipeline.run`. No dataset branch is required inside the core orchestrator.
2. **A thin `run_registered_dataset(config)` service.** This should own source dispatch and config-to-existing-argument mapping. It should reuse `iter_records`, `probe_geotiff`, `fetch_allowlisted_json`, and `MultimodalPipeline.run`, with a separate raster result adapter because TIFF cannot be represented as ordinary rows today.
3. **Forward existing quality controls.** Optional configuration can map to the already implemented `domain_constraints` and freshness controls. The smallest core change would be optional `run` parameters forwarded to `evaluate_quality`; defaults can preserve current output.
4. **Validate task vocabulary at configuration load.** Current core functions accept arbitrary strings. Registry validation can constrain supported task values without changing direct-call backward compatibility.
5. **Add a manifest at the outer result/payload boundary.** Dataset provider, source format, byte size, geometry types, CRS, bounding box, coverage, license, timestamps, and fixture status can be assembled from config/provenance/profile/ingestion metadata. Nullable fields avoid inventing unknown facts. This does not require altering analytical calculations.
6. **Keep vector and raster adapters distinct.** Vector records already flow through GeoJSON flattening. A future raster adapter should return typed raster metadata/results and only join the record pipeline where a deliberate tabularization/aggregation exists; it should not manufacture empty record rows.
7. **Add explicit lineage/governance steps only compatibly.** A registry/source-config reference and governance stage can be appended to lineage while retaining the existing six step names/order for consumers that rely on them. If run-scoped audit output is required, filter by the generated correlation ID without changing the recorder’s persistent history.
8. **Avoid dataset-dependent field selection in core config initially.** The existing outcomes for Cairo and the refrigerated route depend on alphabetical “first field” choices. Registry onboarding should preserve those defaults first; later optional authoritative time/metric/group/route fields can be additive and explicitly tested.

## Gate 0 conclusions

- The reusable center is `MultimodalPipeline.run` and its typed stage functions; a dataset registry belongs in front of it.
- The audited core has no fixed dataset count and no concrete dataset ID dependency.
- The principal blockers to arbitrary onboarding are source dispatch/config validation, unexposed quality options, implicit task/field-selection policy, and the absence of a raster execution contract—not a need for a large pipeline rewrite.
- Existing Cairo Historical Weather and Synthetic Refrigerated Route behavior can be preserved by moving only their source/provenance/task/required-field/governance declarations into registry entries and invoking the same pipeline arguments.
