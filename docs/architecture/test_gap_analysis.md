# Test gap analysis

## Scope and baseline

This audit covers every current test file under `tests/` and the production surfaces those tests exercise. No test or production code was modified for this audit.

Read-only verification executed on 2026-09-09:

```text
python -m pytest -q
23 passed, 1 warning in 6.48s
```

The warning reports that the local Python 3.10.1 environment will lose support in future `google.api_core` releases after Python 3.10 reaches end of life; it is not a test failure.

The suite contains five files:

- `tests/test_analytics_visualization.py`
- `tests/test_catalog_quality.py`
- `tests/test_data_pipeline.py`
- `tests/test_ingestion_security.py`
- `tests/test_security_pipeline.py`

There are 23 collected test cases from 21 test functions because the physical-value validation test has three parameter cases.

## Current coverage

### Pipeline coverage

`test_end_to_end_ingest_classify_quality_analyze_evaluate_visualize` exercises one synthetic mobility GeoJSON flow through `MultimodalPipeline.run()` and asserts classifications, passed quality, eligibility, a route recommendation, all six recorded lineage stages, and key audit operations (`tests/test_security_pipeline.py:35-70`). The authorization failure path is covered for a viewer (`tests/test_security_pipeline.py:73-86`).

Strength: this is a genuine integrated flow through the current orchestration, not a mocked sequence.

Limitations:

- only one dataset family is run through the orchestrator;
- ingestion file reading occurs outside `MultimodalPipeline.run()`, so source/config-to-outcome orchestration is not covered;
- no climate end-to-end regression uses the retained Cairo sample;
- no governance value assertions are present;
- no unsuccessful quality result is passed through analysis/evaluation/visualization at pipeline level;
- exact audit isolation across multiple runs on one `MultimodalPipeline` instance is not tested;
- empty input, malformed provenance, invalid task, and unsupported source format are not pipeline-level tests;
- there is no dataset manifest or processing metadata contract to test yet.

### Frontend payload coverage

There are no tests for `scripts/build_demo.py`, `frontend/data/platform_demo.json`, or `frontend/app.js`.

Consequently, the suite does not verify:

- payload schema version or required/nullable fields;
- that Cairo Historical Weather and Synthetic Refrigerated Shipment Route both appear;
- that output outcomes equal results produced from their configured sources;
- that an arbitrary number of registry datasets is emitted;
- that source attribution, fixture status, governance, lineage, and audit data survive serialization;
- that records and profiles remain aligned;
- frontend selection, rerendering, empty states, direct-link parameters, invalid-ID fallback, search, filters, or manifest rendering;
- absence of hard-coded numeric values when fields are missing.

The generated payload presently has two hand-built entries in `scripts/build_demo.py:83-114`, but this is implementation, not test evidence.

### Quality coverage

Current tests verify:

- value-based timestamp and numerical semantic detection (`tests/test_catalog_quality.py:15-29`);
- invalid latitude, invalid longitude, invalid humidity, missing required value, general missing value, duplicate event, failed status, and valid-row count using a fixture (`tests/test_catalog_quality.py:32-49`);
- a self-intersecting polygon produces a machine-readable `invalid_geometry` error (`tests/test_catalog_quality.py:52-58`);
- sensor/domain ranges are opt-in and generate `domain_range_violation` only when configured (`tests/test_catalog_quality.py:61-70`);
- transformation rejects invalid latitude, longitude, and humidity (`tests/test_data_pipeline.py:66-82`).

Not covered despite current implementation:

- invalid timestamp values distinct from missing timestamps;
- impossible negative/non-numeric CO, CO2, LPG, smoke, particulate, or rainfall values;
- Point, LineString, valid Polygon, MultiPolygon, unsupported geometry type, unclosed ring, and out-of-bounds geometry branches;
- statistical outlier, sensor gap, and stale telemetry rules (`verdatrace/quality.py:317-391`);
- duplicate fallback when no identifier semantic exists;
- multiple identifier fields and which identifier becomes the duplicate key;
- quality scoring, threshold/status boundaries, issue truncation to 100 row indexes, and zero-row behavior;
- overlapping issues on a row and valid-row de-duplication;
- null-cell and issue occurrence metrics;
- configuration-driven required fields and quality constraints from multiple dataset definitions;
- raster integrity/metadata quality beyond the ingestion-level corrupt-TIFF probe.

### Visualization recommendation coverage

Current tests verify:

- a mobility route recommends `point_map`, `route_map`, and `temporal_spatial_animation` while excluding a choropleth (`tests/test_analytics_visualization.py:24-35`);
- polygon data gets a polygon map, but no choropleth without a normalized metric, including a normalization warning (`tests/test_analytics_visualization.py:38-57`);
- climate point observations get a line chart and point map but not a route map (`tests/test_analytics_visualization.py:60-81`).

Missing recommendation coverage:

- histogram, scatter, bar, proportional-symbol, heatmap/hexbin, eligible choropleth, and raster-map rules;
- unsupported fields and ineligible evaluation behavior;
- confidence, reason, fields, and config contract assertions beyond recommendation type;
- latitude/longitude exclusion from ordinary business charts;
- field cardinality and semantic edge cases;
- empty, categorical-only, numerical-only, geometry-only, and raster profiles;
- consistency between recommended visualizations and frontend render capabilities.

### Analytics and evaluation coverage

The mobility test asserts spatial bounds and positive total distance (`tests/test_analytics_visualization.py:24-34`). The climate test executes analytics and evaluation but asserts recommendation types only (`tests/test_analytics_visualization.py:60-81`).

Missing coverage includes descriptive statistics, temporal aggregates, trends, grouped statistics, correlations, units, warnings, normalized result provenance, quality reference, task inference, and evaluation reason/check behavior across completeness, temporal, spatial, and numerical readiness.

### Ingestion and security coverage

Current tests cover CSV batching, approved-root enforcement, unsupported extension, malformed JSON, corrupt TIFF headers, HTTPS/host allowlisting, and explicit rejection of a projected GeoJSON CRS (`tests/test_ingestion_security.py:15-67`). Authorization boundaries and audit redaction have focused tests (`tests/test_security_pipeline.py:14-32`).

Missing multi-dataset concerns include YAML configuration parsing, registry discovery, duplicate IDs, relative source resolution against an approved root, config-declared format mismatches, missing source paths, and per-dataset role/governance policy propagation.

### Backward compatibility coverage

`transform_event()` retains focused compatibility tests for pseudonymization/direct-identifier removal, legacy commerce fields, mobility-derived emissions and flags, and sensor/geospatial normalization (`tests/test_data_pipeline.py:6-63`). Salt and timestamp requirements are also covered (`tests/test_data_pipeline.py:85-92`).

Gaps:

- no golden/structural regression for both existing demo datasets;
- no proof that moving metadata from Python to registry files preserves profile, quality, analysis, evaluation, recommendations, lineage, governance, and frontend identity;
- no assertion that existing IDs remain `open_meteo_cairo_historical` and `synthetic_refrigerated_route`;
- no schema compatibility test for persisted `verdatrace_portal_payload_v1` consumers;
- no test that optional new manifest/config fields leave existing callers of `MultimodalPipeline.run()` unchanged.

## Tests required for multi-dataset onboarding

### Gate B1 — typed dataset configuration

Add unit tests for:

1. a complete valid configuration and a minimal valid configuration;
2. missing/blank dataset ID;
3. missing source and nonexistent local source;
4. supported and unsupported source formats;
5. every allowed task plus an invalid task;
6. valid list/object forms for required fields and malformed values;
7. nullable governance/provenance fields remaining unknown rather than being invented;
8. unknown keys according to the chosen compatibility policy;
9. safe relative path resolution without escaping the repository-approved root.

Uniqueness belongs to the registry rather than a single config model and should be asserted at Gate B2.

### Gate B2 — registry discovery

Use temporary directories and add tests for:

1. deterministic discovery of multiple `config/datasets/*.yaml` files;
2. valid iteration and lookup by ID;
3. duplicate IDs across different files;
4. malformed YAML and wrong top-level types;
5. unsupported file/config source format;
6. empty registry behavior;
7. non-YAML files being ignored or rejected according to the documented rule;
8. error messages including the responsible config path without leaking secrets.

### Gate B3 — retained dataset registry entries

Add regression tests that load both retained definitions and assert:

- stable IDs and user-facing names;
- source file and format;
- task and required fields;
- fixture distinction and verified attribution/provenance;
- governance values previously supplied by `scripts/build_demo.py`;
- no disappearance of Cairo Historical Weather or Synthetic Refrigerated Shipment Route.

Do not assert volatile timestamps as exact values.

### Gate C1 — generic registered-dataset runner

Add one success test per current dataset family plus failure tests for missing files, invalid config, unsupported format, and failed required-field quality. Assert the stage outputs and processing metadata, and verify the function delegates to existing ingestion and `MultimodalPipeline` behavior rather than producing a parallel outcome model.

### Gate C2/C3 — registry-driven demo build and regression

Build into a temporary output path and assert:

- dataset count equals registry count rather than a literal two;
- each registry ID appears exactly once;
- the two retained datasets still load, profile, validate, analyze, evaluate, recommend, produce lineage, and serialize;
- adding a third temporary config causes a third output entry without changing Python source;
- one invalid config fails the build explicitly without silently publishing a partial payload;
- fixture records remain clearly labeled and real-source provenance remains intact;
- stable fields are identical, or intentionally equivalent, to the pre-registry output; volatile processing/audit timestamps and correlation IDs should be normalized out of comparisons.

### Dataset manifest and processing metadata

Contract tests should cover every proposed field as present, null, or absent according to the final schema. Specifically test that no input size, CRS, geometry type, license, spatial extent, coverage, timestamp, or KPI is guessed. Derivable `record_count` must match emitted records. Bounding boxes and temporal coverage should agree with the profile when both exist.

### Frontend behavior

Without introducing a large framework, isolate payload-selection/filtering helpers so Node can test them, or use the repository's chosen lightweight DOM test harness. Cover:

1. arbitrary catalog size and empty catalog;
2. selection updates `state.dataset` and rerenders the shared workspace;
3. `?dataset=<known-id>` selection;
4. unknown query ID fallback without an exception;
5. URL update after switching;
6. case-insensitive search by name, ID, and domain;
7. metadata-derived domain and dataset-type filters;
8. combined search/filter behavior and no-results state;
9. nullable manifest rendering that omits unavailable fields;
10. missing values render as unknown, never numeric zero;
11. nonspatial, nontemporal, and nonnumeric datasets produce appropriate non-applicable states;
12. retained Cairo point/trend behavior and refrigerated route behavior;
13. payload contract rejection with a visible, safe error state.

### Future vector/raster adapters

Before those adapters are considered complete, add fixtures and tests for Point, LineString/route, Polygon/MultiPolygon, choropleth join/normalization eligibility, raster metadata/probe success, corrupt raster failure, CRS support/rejection, geometry counts, extents, and frontend adapter dispatch. Avoid large binary fixtures; use the smallest valid TIFF metadata fixture or a generated test fixture consistent with repository policy.

## Recommended test order

1. Configuration model and registry unit tests.
2. Existing-dataset registry regression tests.
3. Generic runner success and failure tests.
4. Temporary-output build/payload contract tests.
5. Frontend pure selection/search/filter/manifest tests.
6. End-to-end multi-dataset regression over Cairo weather and the refrigerated route.
7. Future vector/raster adapter tests only as those adapters are implemented.

This order protects current behavior first, then makes registry-driven cardinality and frontend onboarding independently testable without a broad rewrite.
