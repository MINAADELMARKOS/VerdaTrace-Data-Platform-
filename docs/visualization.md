# Visualization intelligence

`verdatrace.visualization.recommend_visualizations` is a deterministic, UI-independent rule engine. It uses profiled physical types, validated semantic types, row count, geometry evidence, and task suitability.

## Rules

| Visualization | Required evidence | Guardrails |
| --- | --- | --- |
| Line | Parsed time/date plus numeric metric | Time is explicitly ordered |
| Scatter | Two non-coordinate numeric fields | Latitude/longitude are excluded as ordinary business measures |
| Histogram | One numeric field | Distribution only; no categorical ordering implied |
| Bar | Bounded categorical field plus metric | Uses an explicit aggregate |
| Point map | Valid WGS84 latitude/longitude | Invalid coordinates reduce quality/readiness |
| Proportional symbol | Point coordinates plus magnitude | Magnitude is not silently normalized |
| Heatmap | At least 500 point observations | Avoids suggesting density for tiny samples |
| Route map | Coordinates, time, and route or vehicle identity | Time supplies ordering; a sensor device alone is not a vehicle |
| Temporal spatial animation | Coordinates plus time | Works for both moving and stationary observations |
| Polygon map | Polygon/MultiPolygon sample geometry | Point GeoJSON never triggers polygon rules |
| Choropleth | Polygon geometry plus normalized rate/ratio/percent/density field | Raw counts do not qualify |
| Raster map | GeoTIFF/TIFF classification | Full rendering requires raster worker metadata |

Every recommendation contains type, fields, confidence, reason, and optional configuration. Warnings state why a tempting but misleading chart is not recommended.

## Frontend choice

The original frontend had no visualization engine. Leaflet 1.9.4 was added only to the static portal because it is a focused, lightweight map renderer and does not require a server-side GIS stack. Analytical trends use the Canvas API, avoiding another chart dependency.

The public portal implements WGS84 points, route lines, bounds, layer visibility, tooltips, zoom/pan, dataset selection, temporal filtering, map-bounds filtering, and metric selection. Polygon/raster rules are returned by the engine but are not demonstrated with invented real data.
