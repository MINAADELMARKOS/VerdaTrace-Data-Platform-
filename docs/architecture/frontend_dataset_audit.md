# Frontend dataset audit

## Scope and conclusion

This audit covers `frontend/index.html`, `frontend/app.js`, and `frontend/styles.css` as they existed before multi-dataset onboarding work. No production code was changed.

The frontend already has the right high-level shape for a dynamic catalog: it renders `state.payload.datasets`, stores one selected dataset in `state.dataset`, and reruns one shared workspace when a catalog card is selected (`frontend/app.js:38-54`, `frontend/app.js:407-419`). It does **not** assume exactly two datasets in the catalog UI.

It is not yet safe for arbitrary registry datasets. Renderers require a fixed, complete, point/time-series-oriented payload; there are no payload guards, search/filter controls, direct dataset URLs, generic manifest view, polygon/raster adapters, or empty-state behavior. The smallest clean change is to keep the single workspace and make its existing render functions capability-aware and null-safe.

## Current payload and selection flow

1. `start()` fetches one fixed artifact, `./data/platform_demo.json`, and assigns the parsed object to `state.payload` (`frontend/app.js:454-460`).
2. `renderDatasetList()` iterates `state.payload.datasets`, creates one button per entry, and binds each button to `selectDataset(dataset.id)` (`frontend/app.js:38-54`). The displayed count is derived from the array length, so the catalog itself supports any non-empty number of entries (`frontend/app.js:41-42`).
3. `initMap()` creates one Leaflet map and three reusable layer groups (`frontend/app.js:83-96`).
4. `bindControls()` installs the shared layer, metric, time-window, and map-bound handlers (`frontend/app.js:421-452`).
5. Startup unconditionally selects the first entry (`frontend/app.js:464`). There is no query-parameter lookup or empty-catalog guard.
6. A catalog click calls `selectDataset()`, which finds the matching entry, copies its records, and rerenders the whole workspace (`frontend/app.js:407-419`). A missing ID leaves `state.dataset` undefined and then dereferences it on the next line.

`index.html` supplies one catalog rail and one reusable main stage rather than dataset-specific pages (`frontend/index.html:66-143`). The responsive rules already allow the catalog to become a grid on narrower layouts (`frontend/styles.css:44-62`, `frontend/styles.css:144-157`).

## State model

The singleton state contains:

- `payload`: the loaded top-level JSON object;
- `dataset`: the currently selected dataset object;
- `map`: the reusable Leaflet instance;
- `layers`: the fixed `points`, `route`, and `bounds` layer groups;
- `currentRecords`: the selected dataset's records after temporal or map filtering.

Evidence: `frontend/app.js:3-9`, layer initialization at `frontend/app.js:93-95`, and selection at `frontend/app.js:407-409`.

This is sufficient for catalog selection but has no state for a search term, domain/type filters, selected manifest fields, or a parsed URL dataset ID.

## Renderer audit

| Concern | Current behavior | Dataset assumptions and risks | Evidence |
|---|---|---|---|
| Catalog | Iterates all entries and shows domain, title, row count, and category count. | Requires `datasets`, `id`, `domain`, `title`, `outcome.profile.row_count`, and `outcome.profile.categories`; no search, filters, or empty catalog state. | `frontend/app.js:38-54` |
| Header and summary metrics | Shows fixture/source state, categories, attribution, rows, quality, suitability, visualization count, and a CRS badge. | Assumes all nested objects exist. `formatNumber()` converts a missing value to zero, which could present an unknown metric as a real zero. The CRS label is hard-coded to EPSG:4326 whenever geographic bounds exist. | `frontend/app.js:12-15`, `frontend/app.js:56-80` |
| Map coordinates | Accepts top-level latitude/longitude or GeoJSON `Point` geometry. | Does not accept configurable field names, Feature geometries other than Point, or a manifest-declared geometry adapter. | `frontend/app.js:28-36` |
| Map layers | Draws circle markers for located records, optionally draws a route if `route_map` was recommended, and derives a rectangle from displayed points. | Fixed point/route/bounds layers only. No polygon, choropleth, heatmap, raster, tile, or streaming rendering. Empty/nonspatial datasets leave an empty map rather than a capability-specific state. | `frontend/app.js:112-150`, `frontend/app.js:152-164` |
| Tooltips | Displays time, device/vehicle, temperature, humidity, and speed. | Field names and units are hard-coded to the two current dataset families. New domains silently produce blank or incomplete tooltips. | `frontend/app.js:98-110` |
| Temporal filtering | Uses a slider from one through record count and takes the first `N` records. | Assumes record order is meaningful and calls the result a temporal window even when no timestamp exists. It is not a date-range filter and does not sort by a semantic timestamp. | `frontend/app.js:166-172`, `frontend/app.js:426-435` |
| Map-bound filtering | Filters records for which `coordinate(record)` returns a point within current bounds. | Appropriate for point records only; polygons and rasters would all be removed. | `frontend/app.js:436-445` |
| Metric selection | Lists numeric profile fields except semantic latitude/longitude. | Generic for numeric columns, but requires exact `data_type === "number"`; does not consult visualization eligibility, units, or manifest roles. | `frontend/app.js:174-190` |
| Trend | Plots the selected value in current record order and labels endpoints using `event_timestamp`. Computes min, max, and mean from the displayed records. | The calculation is real, not a stored KPI, but a line/trend presentation can be misleading for unordered tabular data. Timestamp field name is hard-coded. Empty numeric data is handled, but an empty metric select is only indirectly handled. | `frontend/app.js:193-285` |
| Recommendations | Iterates normalized specs and renders type, reason, fields, confidence, and joined warnings. | Requires all recommendation arrays and item fields. No explicit empty eligible/ineligible state and no rendering of `unsupported_fields`. | `frontend/app.js:287-306` |
| Quality | Renders report status and one card per issue. | Requires `quality.issues`. The no-issue view hard-codes `100` instead of using `quality.score`, which is unsafe for optional or differently scored reports. | `frontend/app.js:308-336` |
| Semantic profile | Iterates all fields and renders physical type, semantic type, confidence, and evidence. | Structurally generic, but assumes `evidence` is always an array and confidence is a valid number. | `frontend/app.js:338-359` |
| Lineage | Iterates arbitrary lineage steps and renders stage, operation, input, and output. | Structurally generic but assumes every step has all four string values. | `frontend/app.js:361-377` |
| Governance and audit | Renders eight fixed governance keys and a count-only audit summary. | Extra governance fields are ignored; unknown fields are displayed as `not_provided`. It assumes `audit_events` is an array. | `frontend/app.js:379-405` |

## HTML and styling constraints

- The catalog rail contains only the heading, count, list, and source note; there are no search/filter controls or result status region (`frontend/index.html:67-71`).
- Four metric cards are permanently present and assume every dataset has profile, quality, evaluation, and visualization results (`frontend/index.html:83-88`).
- The spatial workspace, temporal slider, and trend panel are always visible, including for nonspatial or unordered datasets (`frontend/index.html:90-118`).
- Recommendations, quality, semantic profile, lineage, and governance each have reusable containers and can remain a single component per concern (`frontend/index.html:120-142`).
- Styles are reusable around `.dataset-card`, `.panel`, tables, status pills, and responsive grids (`frontend/styles.css:50-58`, `frontend/styles.css:71-138`), but there are no selectors for search, filter chips, catalog empty states, manifest rows, or non-applicable panel states.

## Can the current frontend support arbitrary payload datasets?

### Already reusable

- Dataset count and catalog cards are array-driven.
- One `selectDataset()` path rerenders the same workspace.
- Metrics are read from normalized outcome models rather than being hard-coded business KPIs.
- Recommendation, quality issue, profile field, and lineage lists are array-driven.
- The map can display any record with canonical latitude/longitude or Point geometry.
- The metric picker can display any numeric field identified by the profile.

### Blocking assumptions

- Non-empty payload and exact nested shape are assumed.
- Dataset title is `title`, while the target registry model is expected to use `name`; there is no normalized frontend contract yet.
- Attribution and governance are split across fixed top-level/nested shapes rather than a generic manifest.
- Missing numerical values may be rendered as zero.
- Only point records and route overlays render; vector polygons and rasters do not.
- Timestamp display and tooltips use current canonical field names instead of profile/config semantics.
- The trend is drawn for any numeric data regardless of ordering or recommendation.
- Panels cannot be hidden or marked not applicable based on dataset capabilities.
- Direct-link selection, safe invalid-ID fallback, search, domain filters, and dataset-type filters are absent.

## Minimal changes for fully dynamic onboarding

These changes preserve the single page, the existing state object, and all current Cairo weather and refrigerated route behavior.

1. **Normalize and validate the payload at the boundary.** Add small accessors/defaults for optional arrays and nullable values. Keep unknown values as `—`/`not provided`; never coerce them to zero. Reject only an invalid top-level contract and provide explicit empty states.
2. **Keep `selectDataset()` as the sole transition.** Make it resolve a requested ID safely, fall back to the first available dataset, or render an empty catalog. Continue rerendering all existing concerns from this function.
3. **Add static-site-compatible URL selection.** Read `new URLSearchParams(location.search).get("dataset")` at startup. On catalog selection, use `history.replaceState` or `pushState` to set `?dataset=<encoded id>`. An unknown ID must select the documented fallback without throwing.
4. **Add search/filter state and one derived catalog function.** Search normalized `name/title`, `id`, and `domain`; generate domain and type filter options from present manifest/config values, with human-readable group labels where necessary. Do not encode a fixed dataset count.
5. **Render a nullable dataset manifest.** Add one metadata panel/component that lists only provided values such as provider, format, input size, record/feature count, geometry types, CRS, extent, temporal coverage, license, timestamps, and fixture status. Do not infer missing provenance in the browser.
6. **Make existing panels capability-aware.** Preserve point and route behavior for the two existing datasets. Hide or mark the temporal control when no timestamp semantic exists, do not call an unordered series a trend, and show explicit nonspatial/unnumeric states instead of errors.
7. **Use semantic/profile metadata for labels.** Resolve timestamp, coordinate, identifier, units, and tooltip fields from the profile or visualization specs, retaining the existing canonical-name behavior as compatibility fallback.
8. **Add spatial adapters incrementally.** Route canonical Point/route data through the current renderer; add separate polygon and raster adapters only when registry entries of those types are onboarded. The layer registry can grow without replacing Leaflet or creating separate pages.
9. **Render normalized results, not executive claims.** Continue computing bounded descriptive summaries from visible records, but treat future executive KPIs as optional configured result objects with name, value, unit, definition, provenance, and applicability. Missing KPI data should not create cards or substitute values.
10. **Add focused tests before behavior changes.** Required coverage is listed in `docs/architecture/test_gap_analysis.md`.

## Extension points

- `renderDatasetList()` can consume a filtered dataset array without changing card selection.
- `selectDataset()` is the natural query-parameter and safe-fallback boundary.
- `coordinate()` is the current Point adapter; sibling vector/raster adapters can avoid complicating it.
- `renderMapRecords()`, `drawTrend()`, and `renderGovernance()` can be guarded using profile/manifest capabilities.
- The existing catalog rail can receive search and generated filter controls immediately before `#dataset-list` without changing page navigation.

No separate HTML page, frontend framework, new visualization library, or replacement state-management system is needed for registry-driven onboarding.
