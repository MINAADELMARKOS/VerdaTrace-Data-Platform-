# Add a dataset

Adding a supported dataset should normally require a source and one YAML definition. It must not require a new HTML page, dataset-specific JavaScript, a duplicate pipeline, or a duplicate quality engine.

## Workflow

1. Add a bounded source under an approved repository path (or mount/retrieve it into `data/raw/`; keep large raw files ignored).
2. Record verified provenance, license/redistribution status, coverage, original schema, transformations, and limitations. Use `unknown`, `not_provided`, or `null` when a fact is unavailable.
3. Add `config/datasets/<stable-id>.yaml` with `schema_version: verdatrace_dataset_config_v1`.
4. Set `source.format`, `source.dataset_type`, task, required fields, quality rules, and governance values. The enabled source must exist and remain inside the project root.
5. Select an existing adapter: CSV/JSON/NDJSON/GeoJSON/OSM PBF record ingestion, or the raster adapter boundary for GeoTIFF/COG/NetCDF/Zarr.
6. Run `python scripts/build_demo.py`. The registry is discovered in filename order; every enabled definition runs through ingestion → profile → quality → analytics → evaluation → visualization → lineage → governance and becomes one payload entry.
7. Run `python -m pytest -q`, `node --check frontend/app.js`, and `node tests/frontend_dataset_utils.test.js` before publishing.

For an uploaded CSV, JSON/JSONL, XML, or GeoJSON file that does not yet have a
domain adapter, call `verdatrace.cohesive.ingest_and_profile_file(...)`. It
detects the existing safe reader, counts the full stream, emits checksum and
bounded-preview metadata, and returns next steps for applying configured
quality rules and registering the result. Existing registry definitions remain
the preferred governed execution path; the hook does not bypass path or URL
validation.

## Minimal definition

```yaml
schema_version: verdatrace_dataset_config_v1
id: example_dataset
name: Example dataset
domain: environmental
task: descriptive
required_fields: [event_id]
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
quality: {}
governance: {}
```

The parser rejects unknown keys, duplicate IDs, missing enabled sources, path traversal, format/extension mismatches, unsupported task/type values, malformed required fields, and invalid quality ranges. Set `enabled: false` only for an explicitly documented retrieval plan; disabled definitions are validated and visible to registry tooling but are not executed or published.

## Optional executive KPIs

`MultimodalPipeline.run(..., executive_kpis=[...])` accepts typed `ExecutiveKPI` values. Each value must be source-backed and may include `source_metric`, `analysis_stage`, `fields_used`, and `calculation_description`. The portal hides the KPI section when no KPI is present. Do not add a KPI merely to fill a card.

## Source-specific adapters

Keep provider-specific mapping in a connector. For example, Open-Meteo retrieval stays in `scripts/fetch_open_meteo.py`; its YAML points at the resulting attributed envelope. OSM PBF uses the optional `pyosmium` worker and a bounded callback queue; keep large extracts outside Git and leave the registry disabled until the source and dependency are verified. For a new file format, first implement a `RasterAdapter` or record adapter and its tests, then add the registry entry. Do not bypass the approved-root and allow-list checks.
