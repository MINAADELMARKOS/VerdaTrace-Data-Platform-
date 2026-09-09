# VerdaTrace Cohesive Data Platform — Synthetic Data Pack

This pack is deliberately cross-linked across logistics, mobility, IoT, GIS, climate,
evaluation, and governance so it can exercise one platform rather than separate demos.

## Shared keys
- `zone_id`: common spatial aggregation key
- `site_id`: warehouse/hub/factory/weather/charging/port location
- `vehicle_id`: logistics + mobility link
- `sensor_id`: IoT + industrial telemetry link
- event timestamps: allow time-window joins and lineage

## Architecture mapping

### 01 Ingest
- CSV: `logistics_shipments.csv`, `climate_environment.csv`
- JSONL streams: `mobility_stream.jsonl`, `iot_sensor_telemetry.jsonl`, `governance_access_audit.jsonl`
- GeoJSON: `spatial_assets.geojson`
- XML: `industrial_measurements.xml`

### 02 Quality
Intentional issues include:
- duplicate IDs
- missing foreign keys
- misspelled categorical values
- negative weights and precipitation
- impossible humidity
- out-of-range telemetry
- unit mismatches
- unknown sensor IDs
- GPS coordinate swaps / unrealistic speeds
- missing or self-intersecting geometry
- missing calibration dates

Use `metadata/quality_rules.csv` and `schemas/` for automated validation.

### 03 Catalog
Use `metadata/dataset_catalog.csv` for:
- domain
- semantics
- primary key
- event-time field
- classification
Use `metadata/lineage_edges.csv` for lineage relationships.

### 04 Analyze
Suggested analyses:
- route and delivery SLA by zone
- congestion from mobility speed
- sensor anomaly rate by site
- climate exposure by zone
- point-in-polygon / spatial joins
- environmental + mobility correlation
- site readiness trends

### 05 Evaluate
Use `analytical_evaluation.csv` as a target/output model for:
- suitability
- readiness
- risk penalty
- explainable recommendation

### 06 Visualize
Useful visual types:
- map layers by suitability
- route density
- time-series telemetry
- climate heatmaps
- anomaly dashboards
- executive KPI cards
- recommendation explanation panels

### Governance
Use:
- `governance_access_audit.jsonl`
- dataset classification in catalog
- lineage edges
- least-privilege RBAC checks

## Record counts
- zones.csv: 60
- sites.csv: 600
- vehicles.csv: 3,500
- sensors.csv: 5,000
- logistics_shipments.csv: 100,000
- mobility_stream.jsonl: 120,000
- iot_sensor_telemetry.jsonl: 150,000
- industrial_measurements.xml: 30,000
- climate_environment.csv: 80,000
- spatial_assets.geojson: 8,000
- analytical_evaluation.csv: 20,000
- governance_access_audit.jsonl: 20,000

## Suggested unified flow
Raw ingest -> schema validation -> quality scoring -> catalog registration -> enriched silver layer
-> spatial/time joins -> evaluation scoring -> visualization recommendation -> governed serving layer.


## Additional platform-control metadata
- `metadata/dataset_profile_expectations.csv`: automated profiling/categorization targets
- `metadata/visualization_recommendations.json`: explainable chart/map recommendations
- `metadata/rbac_policy.csv`: least-privilege policy examples
- `metadata/expected_quality_findings.csv`: golden targets for testing your quality engine

These metadata files make it possible to test not only ingestion and analytics, but also
profiling, recommendation logic, governance, evidence, confidence, and auditability.
