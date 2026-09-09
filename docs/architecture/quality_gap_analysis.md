# Quality gap analysis

## Scope and current boundary

This audit covers the deterministic quality implementation in `verdatrace/quality.py` and the format/CRS guards in `verdatrace/ingestion.py`. It is a Wave 0 assessment only; no production behavior is changed here.

`evaluate_quality()` materializes the supplied iterable before evaluating it (`quality.py:118-130`). That is suitable for the current small demo inputs, but it is the main scalability boundary for large telemetry, vector, or tabular datasets. Quality findings are structured `QualityIssue` records and a `QualityReport`; issue row indexes are capped at 100 for each grouped issue (`quality.py:93-115`).

## Coverage matrix

| Area | Current checks | Missing or incomplete checks | Practical extension point |
|---|---|---|---|
| Tabular | Required-value checks; semantic null counts; record/event-identifier duplicate detection; configurable numeric min/max constraints; numeric outer-fence outlier warnings; aggregate score/status/metrics (`quality.py:132-159`, `269-345`, `393-409`). | Explicit declared datatype/schema conformance; extra/missing column policy; composite uniqueness; configurable categorical domains; referential integrity; string length/pattern checks; per-field completeness thresholds; non-finite values reported distinctly; incremental/chunk-safe metrics. Duplicate identity currently uses only the first detected identifier and otherwise serializes a full row. | Extend `evaluate_quality` with a typed rule/config object while preserving current keyword arguments; emit new `QualityIssue` codes through `_add_grouped_issue` and keep the existing report contract. |
| Temporal | Missing timestamp warnings; parse validity; sampling gaps over 3x median; optional freshness/staleness objective (`quality.py:160-175`, `347-391`). | Event ordering/monotonicity; future timestamps; configurable coverage windows; timezone/offset consistency; duplicate timestamp policy per entity; cadence tolerance; start/end coverage conformance; late-arrival and watermark checks. Only the first semantic timestamp field is used for gaps and freshness. | Add temporal rules scoped by timestamp and optional entity fields. Reuse `catalog.parse_datetime`; calculate per entity where configured. |
| Spatial coordinates | Latitude and longitude numeric/WGS84 bounds; point/line/polygon coordinate bounds; ingestion rejects explicitly declared unsupported GeoJSON CRS (`quality.py:177-209`, `34-90`; `ingestion.py:69-86`). | Required lat/lon pairing; null asymmetry; zero-island detection; configurable geographic bounds/region containment; coordinate precision; axis-order ambiguity; antimeridian behavior; projected-coordinate validation; spatial duplicates; coordinate/geometry consistency. | Add spatial rule configuration to the quality layer; keep CRS normalization/reprojection at ingestion/adapter boundaries rather than silently interpreting projected coordinates. |
| Geometry | GeoJSON `Point`, `LineString`, `Polygon`, and `MultiPolygon`; minimum position/ring lengths; polygon ring closure; simple non-adjacent ring self-intersection detection; WGS84 bounds (`quality.py:34-90`). | `MultiPoint`, `MultiLineString`, `GeometryCollection`; holes/topology relationships; degenerate/zero-area rings; repeated vertices; line self-intersections; orientation; NaN/extra dimensions policy; robust topology validity; cross-feature overlap/gap/containment checks; geometry repair policy. Current segment test does not cover collinear/touching edge cases. | Preserve the dependency-light validator for fixtures; introduce an optional vector adapter backed by the repository-approved geospatial library when robust topology is required. Record, but do not silently repair, invalid geometry. |
| Raster | TIFF/GeoTIFF signature probe and explicit error for corrupt/unsupported inputs; the probe reports CRS as unknown and states that a raster worker is required (`ingestion.py:159-202`). Raster format classification exists (`catalog.py:247-250`). | No raster quality evaluation: CRS/geotransform, width/height/band metadata, nodata coverage, pixel datatype/range, corrupt tiles, bounds, resolution, overview/pyramid presence, band semantics, cloud/noise coverage, raster statistics, or alignment between rasters. | Add a future optional raster adapter (for example rasterio/GDAL only if approved) that returns normalized metadata and sampled/streamed quality findings without loading the full raster. Keep unsupported execution explicit until that dependency exists. |

## Existing acceptance-case coverage

- Invalid latitude, longitude, humidity, empty timestamps, and duplicate events are exercised by `tests/test_catalog_quality.py:32-49` using `tests/fixtures/synthetic_sensor_quality_cases.csv`.
- A self-intersecting polygon is exercised by `tests/test_catalog_quality.py:52-58` using `tests/fixtures/broken_polygon.geojson`.
- Unknown sensor specifications are respected: a temperature becomes invalid only when a caller supplies a justified `domain_constraints` range (`tests/test_catalog_quality.py:61-70`).
- Corrupt TIFF input and unsupported GeoJSON CRS are failure-path tested in `tests/test_ingestion_security.py:35-43` and `54-67`.

## Priority gaps for multi-dataset onboarding

1. Introduce typed, per-dataset quality configuration for required fields, ranges, categorical domains, uniqueness keys, freshness, and optional coverage bounds; absence of a rule must continue to mean “unknown/not configured,” never an invented constraint.
2. Validate configured fields against discovered schema and report rules that cannot execute.
3. Make duplicate, temporal-gap, and staleness checks entity-aware when an entity key is configured.
4. Add chunk/stream aggregation before onboarding large external sources; the current `list(rows)` behavior is not a production-scale execution model.
5. Treat vector and raster processing as adapters with explicit capability metadata. Do not imply robust topology or raster validation until the corresponding adapter is installed and invoked.
