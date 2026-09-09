# Dataset sources, provenance, and selection

## Executable registry and candidate catalog

The static portal is built from validated `config/datasets/*.yaml` definitions. The executable registry currently contains:

- `open_meteo_cairo_historical.yaml`, pointing to the bounded attributed Cairo JSON sample;
- `synthetic_refrigerated_route.yaml`, pointing to the clearly labeled GeoJSON fixture.

These definitions preserve source path, source type/format, pipeline task, required fields, provenance, fixture status, attribution, quality options, and governance. Running `python scripts/build_demo.py` discovers all validated YAML entries and produces one normalized portal entry for each; no dataset count is hard-coded.

Three additional YAML definitions are intentionally disabled retrieval plans: Sentinel-2 Greater Cairo, ERA5-Land Cairo, and GHSL population 2015. They are validated as registry metadata but are not run or published until the referenced source file/credentials and product-specific semantics are supplied. See [raster.md](raster.md).

The existing `config/datasets.json` remains a provenance and source-selection catalog for evaluated retrieval-only candidates. Its Environmental Sensor Telemetry, NYC TLC, and Natural Earth records are not executable registrations and do not imply that source files were downloaded. They require compatible local/object-storage sources or source adapters plus validated YAML definitions before they can appear in the portal.

`osm_egypt_retrieval.yaml` is a disabled, reproducible OpenStreetMap Egypt PBF plan. It records the Geofabrik source page/download, ODbL attribution requirement, WGS84 target schema, known limitations, and the optional pyosmium dependency. The current extract is intentionally not committed because it is a large binary; retrieve it into `data/raw/egypt-latest.osm.pbf`, verify the exact extract date, and enable the definition only after the worker environment is approved. See [osm.md](osm.md).

Registry validation requires unique IDs, existing repository-relative paths, matching supported formats, valid task/type values, and well-formed required-field, quality, and governance sections. Unknown facts stay `unknown`, `not_provided`, or `null` downstream; registration must not invent provider facts, license terms, source sizes, coverage, measurements, or KPIs. The complete schema and execution contract are documented in [architecture.md](architecture.md#executable-dataset-registry).

## Included real sample

### Open-Meteo Historical Weather API — Cairo

| Attribute | Value |
| --- | --- |
| Purpose | Climate/environmental time-series, sensor-like quality checks, temporal analysis, and point-map visualization |
| Provider | Open-Meteo |
| Original URL | The exact parameterized request is stored in the sample's `provenance.original_url` |
| Retrieval date | `2026-08-26T13:06:50.722273+00:00` |
| License | CC BY 4.0 |
| Redistribution | Permitted with attribution; the portal links to Open-Meteo |
| Coverage | One returned grid point near Cairo, Egypt |
| Time | 2024-01-01 00:00 UTC through 2024-01-03 23:00 UTC |
| Source format | JSON hourly arrays |
| Target | 72 `verdatrace_multimodal_v1` records |
| Transformations | Hourly arrays zipped; WGS84 coordinates attached; fields renamed |
| Limitations | A single grid point does not represent all Cairo microclimates; upstream model/reanalysis limitations apply |

Refresh:

```
python scripts/fetch_open_meteo.py
python scripts/build_demo.py
```

Direct local/static access after building is available at `?dataset=open_meteo_cairo_historical`. The catalog can also find it by name, ID, or domain and filter it by available domain/type metadata.

## Included fixtures

| Fixture | Purpose | Status |
| --- | --- | --- |
| `synthetic_mobility_route.geojson` | Successful logistics → mobility → sensor → spatial integration flow and portal route | Explicitly synthetic; not a real shipment |
| `synthetic_sensor_quality_cases.csv` | Invalid latitude/longitude, 130% humidity, missing timestamp, and duplicate event | Explicitly synthetic negative test |
| `broken_polygon.geojson` | Self-intersecting polygon failure path | Explicitly synthetic negative test |

Fixtures do not claim a real provider, license, or measurement history.

The refrigerated route is registered as `synthetic_refrigerated_route`, remains visibly marked as a fixture, and is directly addressable with `?dataset=synthetic_refrigerated_route`.

## Connected retrieval-only sources

### Environmental Sensor Telemetry Data

- Provider: Gary A. Stafford via Kaggle.
- URL: https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k
- Kaggle metadata displayed CC0: Public Domain when verified on 2026-08-26.
- Format/size: one 61.93 MB CSV with timestamp, device, CO, humidity, light, LPG, motion, smoke, and Fahrenheit temperature.
- Retrieval may require Kaggle credentials, so the source file is not committed.
- `config/kaggle_datasets.yml` and `scripts/kaggle_to_pubsub.py` provide the retrieval/streaming path.
- Locations, calibration, exact source units for gas values, and sensor specifications are not provided. Quality rules therefore enforce only justified physical constraints unless operators configure domain ranges.

### NYC TLC Trip Record Data

- Provider: New York City Taxi and Limousine Commission.
- URL: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- Purpose: verified mobility trips, distances, fares, pickup/drop-off times, and taxi-zone IDs.
- Current files are monthly Parquet. No file is committed.
- The source page states that TLC cannot guarantee record accuracy or completeness.
- Specific license/redistribution terms were not provided on the source page at verification, so the registry records `not_provided` and treats the files as retrieval-only.

### Natural Earth Admin 0

- Provider: Natural Earth.
- URL: https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/
- License: Public Domain.
- Purpose: global generalized country polygons and future normalized choropleth/spatial-join tests.
- The platform prefers the official source over the Kaggle mirror. No archive is committed.
- Small-scale boundaries are not suitable for cadastral, navigation, or legal-boundary decisions.

## Candidate dataset evaluation

The following decisions avoid importing datasets solely to satisfy a checklist. `not verified` means that license, redistribution rights, downloadable schema, or all three were not established in the implementation environment; no data from that source was committed.

| Candidate | Decision | Reason |
| --- | --- | --- |
| Environmental Sensor Telemetry Data | Selected, retrieval-only | Strong schema fit; CC0 shown; manageable streaming CSV; no location/calibration metadata |
| Rural Landscape Monitoring Dataset | Deferred | License/schema/redistribution not verified; unclear incremental value over selected climate/vector sources |
| Bangladesh air quality | Deferred | Useful domain fit, but license/redistribution and sensor specification were not verified |
| Smart House Data Pack | Deferred | License/schema not verified and household context may introduce privacy/sensitivity questions |
| Real-world IoT Data for Environmental Analysis | Deferred | License, provenance depth, and source units were not verified |
| GeoPlant | Deferred | Image/geolocation ML corpus is large and outside the first operational ingestion slice |
| Temperature Over Time by State | Deferred | Overlaps the reproducible Open-Meteo climate sample; license/lineage not verified |
| Berkeley Earth surface temperature mirror | Deferred | Prefer a primary provider or documented API over an unverified Kaggle mirror |
| Climate Change Dataset 2000–2024 | Deferred | License, methodology, and original provider lineage not verified |
| World Countries — Natural Earth mirror | Replaced with official source | Official Natural Earth source is public domain and avoids mirror ambiguity |
| Geospatial environmental/socioeconomic data | Deferred | License, join keys, normalization definitions, and source lineage not verified |
| OpenEarthMap | Deferred | Large imagery/segmentation corpus requires object storage, raster workers, and ML-specific use cases |
| EuroSAT RGB | Deferred | Large raster classification corpus; not needed for the validated vector/telemetry slice |
| Sentinel-2 wildfire | Deferred | Large raster research corpus with storage/tiling/model requirements beyond the existing architecture |
| Bhuvan satellite image/mask | Deferred | Download rights, license, and redistribution not verified; heavyweight imagery pipeline required |
| World Cities | Deferred | Low incremental value for the selected flows; license and primary-source lineage not verified |

## Storage policy

```
data/raw/           ignored large downloads
data/intermediate/  ignored generated working outputs
data/samples/       bounded attributed real samples
tests/fixtures/     small explicit synthetic test data
frontend/data/      generated normalized public-demo payload
```

Large real datasets belong in GCS/object storage with lifecycle rules, not the source repository. Git LFS was not introduced because this repository did not already use it.

The current registered runner and static portal are intentionally bounded-sample paths. Large vectors need conversion/simplification, spatial query pushdown, and vector tiles or bounded GeoJSON delivery. Full rasters need GDAL/rasterio decoding and validation, reprojection, derived statistics, object-storage tiling/pyramids, and a compatible browser raster layer. Streaming sources need a connector and paginated or aggregated result contract rather than embedding an unbounded record array in the generated payload.
