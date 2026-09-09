# OpenStreetMap PBF support

VerdaTrace includes a generic OSM adapter for `.osm.pbf` extracts. The repository registers `osm_egypt` as a validated, disabled retrieval plan; no large binary extract is committed. The source definition points to the Geofabrik Egypt extract page and records the OpenStreetMap ODbL attribution requirement. Retrieve the extract into `data/raw/egypt-latest.osm.pbf`, verify the download and license/attribution obligations, install the optional `pyosmium` worker dependency, then set `enabled: true` in a controlled environment.

```text
Geofabrik/OpenStreetMap PBF
        ↓ streaming pyosmium callback
normalized OSM records
        ↓
profile → quality routing → OSM analytics → evaluation
        ↓
line/point/geometry-distribution recommendations and optional KPIs
```

## Normalized record contract

The adapter keeps the source's useful structure without flattening arbitrary tags:

| Field | Meaning |
| --- | --- |
| `osm_id` | Source node, way, or relation identifier |
| `feature_type` | `node`, `way`, or `relation` |
| `geometry` | WGS84 GeoJSON when locations are available |
| `geometry_type` | GeoJSON geometry type, when present |
| `tags` | Source tag object |
| `name`, `highway`, `building`, `amenity`, `landuse` | Common classification fields |
| `crs` | `EPSG:4326` for normalized geometry |
| `source_metadata` | Version/timestamp/changeset when exposed by the parser |

Nodes, ways, and relations are emitted through a bounded queue. The adapter does not read the PBF into one parser-side list and supports `max_records` for bounded previews and tests. The current generic pipeline still takes a deterministic normalized snapshot for the shared profile/quality/analytics stages; production-scale execution should use a worker that persists or aggregates that snapshot before the browser payload is produced.

## Quality and analytics

OSM-specific quality findings are machine-readable: missing or invalid geometry, duplicate `osm_id`, empty tags, and missing common classification tags. Semantic incompleteness is warning-level; duplicate identifiers and invalid geometry are error-level and route affected records to quarantine. OSM summaries calculate feature/geometry/category counts, road/building/POI/infrastructure counts, road length from tagged line geometry, bounds, and classification completeness. Executive KPIs are optional and expose their source metric, fields, and calculation description.

## Retrieval and attribution

Use the official [Geofabrik Egypt extract page](https://download.geofabrik.de/africa/egypt.html) to choose and record the exact extract date and download URL. Keep the binary in `data/raw/` or object storage, never in the main source repository. Preserve the configured attribution in downstream maps and exports.
