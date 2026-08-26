# End-to-end use cases

## Climate and environmental monitoring

The committed Open-Meteo sample exercises JSON ingestion, timestamp/coordinate/weather semantics, WGS84 bounds, physical quality rules, descriptive and temporal statistics, suitability evaluation, point/proportional-symbol/animation recommendations, canvas trends, provenance, attribution, audit, and lineage.

## Refrigerated logistics route

The explicit synthetic GeoJSON fixture combines an ordered vehicle route with speed, distance, temperature, and humidity. The pipeline classifies logistics, mobility, sensor, environmental, temporal, numerical, event, and vector-geospatial categories. The portal shows points, route, bounds, tooltips, temporal filtering, and chart field selection.

It is not presented as real operational data.

## Environmental sensor streaming

The selected Kaggle sensor source maps epoch timestamps, device IDs, Fahrenheit temperature, humidity, CO, LPG, smoke, light, and motion into Pub/Sub events. The source CSV is not committed. `scripts/kaggle_to_pubsub.py` waits for publish confirmation.

## Mobility expense assurance

NYC TLC trip records are retrieval-only and populate trip time, distance, fares, and zone identifiers. Compatibility flags detect negative distance, high amount per mile, unusual tips, and duplicates. A Parquet-capable batch loader remains a documented next step rather than a fake CSV implementation.

## Privacy-safe retail events

The original retail flow remains compatible. Direct identifiers are not persisted in curated rows; subject IDs are salted and hashed, and direct email/phone presence produces a compatibility quality flag.
