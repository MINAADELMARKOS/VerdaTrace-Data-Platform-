# Scaling and preview boundaries

The tested repository sample is a bounded 72-record Open-Meteo JSON envelope and a six-record synthetic route fixture. Local end-to-end execution and the static payload are validated for those samples; no production throughput, latency, memory, or business KPI benchmark is claimed.

CSV and NDJSON readers iterate records and expose `iter_batches`. GeoJSON parsing currently materializes a standards-compliant JSON document, and `MultimodalPipeline` materializes its input so profiling, quality, and analytics can share a deterministic snapshot. The registered demo runner therefore intentionally targets bounded files.

For larger or operational sources:

- keep raw downloads in object storage and use a bounded retrieval window;
- add pagination, streaming snapshots, query pushdown, or server-side aggregation before registry execution;
- use BigQuery partitioning/clustering and GIS functions for curated spatial data;
- simplify or tile vector layers before browser delivery;
- use chunked raster workers and COG/Zarr tiling/pyramids;
- publish a preview/sample separately from full-dataset analytics;
- expose actual input bytes, records/features, pixels, duration, memory, and output size from instrumentation when measured.

The frontend payload is a preview contract. Its `manifest.record_count` describes the processed payload input, and the UI must not imply that a bounded map represents an entire production dataset when sampling is active.
