# Dataset sources, provenance, and selection

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

## Included fixtures

| Fixture | Purpose | Status |
| --- | --- | --- |
| `synthetic_mobility_route.geojson` | Successful logistics → mobility → sensor → spatial integration flow and portal route | Explicitly synthetic; not a real shipment |
| `synthetic_sensor_quality_cases.csv` | Invalid latitude/longitude, 130% humidity, missing timestamp, and duplicate event | Explicitly synthetic negative test |
| `broken_polygon.geojson` | Self-intersecting polygon failure path | Explicitly synthetic negative test |

Fixtures do not claim a real provider, license, or measurement history.

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
