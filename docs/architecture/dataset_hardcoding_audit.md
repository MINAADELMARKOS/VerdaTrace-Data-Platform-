# Dataset hard-coding audit

## Scope and constraints

This Wave 0 audit is read-only with respect to production code. It covers:

- `scripts/build_demo.py`
- `config/datasets.json`
- `frontend/data/platform_demo.json`
- `scripts/fetch_open_meteo.py`
- `scripts/kaggle_to_pubsub.py`
- `scripts/run_multimodal_flow.py`
- `config/kaggle_datasets.yml`
- the payload-consumption points in `frontend/app.js` that affect dataset count

The audit distinguishes source-specific constants that correctly belong to a connector or provenance record from values that force a code change for every new dataset. Cairo Historical Weather and the Synthetic Refrigerated Shipment Route are existing behaviors to preserve; neither should be removed or silently renamed during registry work.

## Executive finding

The normalized pipeline itself is reusable, but `scripts/build_demo.py` is a fixed two-dataset assembly script. It declares two source paths, builds two different provenance/configuration branches, runs two explicit pipeline calls, and appends two literal payload objects. `config/datasets.json` centralizes verified provenance for four candidate sources, but it is not an executable dataset registry: it has no local source path, pipeline task, required fields, quality policy, governance policy, or adapter declaration. The demo builder does not read it.

The frontend does **not** contain a hard-coded dataset count. It renders `state.payload.datasets` with `forEach` and calculates the count from `.length` (`frontend/app.js:38-53`). However, startup selects index `0` without validating a non-empty collection (`frontend/app.js:454-465`), and every entry is assumed to contain the complete current shape (`id`, `title`, `domain`, `fixture`, `attribution`, `records`, and `outcome`). Therefore, adding a third correctly shaped entry works in principle, while generic onboarding and partial/format-specific payloads do not.

## `scripts/build_demo.py`

### Hard-coded paths

| Evidence | Value | Classification | Onboarding impact |
| --- | --- | --- | --- |
| `scripts/build_demo.py:18` | `data/samples/open_meteo_cairo_2024-01-01_2024-01-03.json` | Dataset-specific source path | Blocker: every additional source requires editing Python. |
| `scripts/build_demo.py:19` | `tests/fixtures/synthetic_mobility_route.geojson` | Intended fixture source path | The fixture is legitimate, but locating it in Python rather than configuration is an onboarding blocker. |
| `scripts/build_demo.py:20` | `frontend/data/platform_demo.json` | Application output path | Shared build constant, not dataset-specific. It is appropriate as a CLI default if it remains overrideable/testable. |
| `scripts/build_demo.py:45` | allowed root `tests/fixtures` | Security boundary coupled to one dataset | The root is valid least-privilege behavior, but it must come from validated source configuration or a source-type policy to support other approved roots. |

### Hard-coded dataset identity, task, validation, and governance

| Evidence | Dataset | Hard-coded values | Classification |
| --- | --- | --- | --- |
| `scripts/build_demo.py:24-40` | Cairo Historical Weather | JSON-envelope loading; ID `open_meteo_cairo_historical`; title `Cairo historical weather`; format `json`; task `climate`; four required fields; owner, sensitivity, and retention policy | Onboarding blocker. These are valid values but belong in one registry entry, not an explicit builder branch. |
| `scripts/build_demo.py:42-47` | Synthetic route | GeoJSON-specific `iter_records` call and fixture-only allowed root | Onboarding blocker in the builder; the ingestion function itself is reusable. |
| `scripts/build_demo.py:49-67` | Synthetic route | Dataset name, provider, repository URL, fixture retrieval/license markers, coverage, temporal range, schema, transformations, and limitations | Intended fixture provenance. Preserve these facts, but move the source of truth into validated registry/configuration rather than constructing `Provenance` inline. |
| `scripts/build_demo.py:68-81` | Synthetic route | ID `synthetic_refrigerated_route`; title; format `geojson`; task `mobility`; four required fields; governance owner, sensitivity, retention | Onboarding blocker. These are executable settings that should be registry data. |

The two pipeline calls use the same reusable `MultimodalPipeline.run` interface (`scripts/build_demo.py:27-40`, `68-81`). That is the clean extension point for a future `run_registered_dataset(config)` function; the new layer should prepare its arguments and delegate rather than copy pipeline logic.

### Fixed payload construction

The payload list is a literal with exactly two entries (`scripts/build_demo.py:83-114`):

1. Cairo entry at `scripts/build_demo.py:87-99` duplicates ID, title, domain, fixture status, attribution label/URL/license, and records/outcome selection.
2. Synthetic route entry at `scripts/build_demo.py:100-112` duplicates the same presentation fields for the fixture.

The printed count is computed dynamically (`scripts/build_demo.py:117`), but that does not make discovery dynamic; the list that precedes it is fixed. There is no loop, registry discovery, enabled/disabled flag, adapter dispatch, or per-entry error isolation.

## `config/datasets.json`

`config/datasets.json` is a provenance catalog with a version and `datasets` array (`config/datasets.json:2-3`). It contains these hard-coded source facts:

| Lines | ID | Name / provider / source format | Status |
| --- | --- | --- | --- |
| `config/datasets.json:5-32` | `open_meteo_cairo_historical` | Open-Meteo Cairo sample / Open-Meteo / JSON | Intended, verified provenance and retrieval policy. This is the only listed entry currently included in the demo build. |
| `config/datasets.json:35-67` | `environmental_sensor_telemetry_132k` | Environmental Sensor Telemetry Data / Gary A. Stafford via Kaggle / CSV | Intended retrieval metadata. Not executable by the demo builder. |
| `config/datasets.json:70-97` | `nyc_tlc_trip_records` | NYC TLC Trip Record Data / NYC Taxi and Limousine Commission / Parquet | Intended retrieval metadata. The current generic file ingestion does not advertise Parquet support, and the entry is not executable by the demo builder. |
| `config/datasets.json:100-123` | `natural_earth_admin0` | Natural Earth Admin 0 Countries / Natural Earth / Shapefile or GeoPackage | Intended retrieval metadata. The entry documents a future conversion but is not executable by the demo builder. |

Names, providers, source URLs, licenses, schemas, transformations, limitations, and commit policies are provenance constants and should remain explicit. They are **not** problematic merely because they are literal. The onboarding gap is structural: none of the four entries defines a source locator usable by local ingestion, `task`, `required_fields`, quality options, governance settings, fixture state, presentation title/domain/attribution, or adapter/format conversion. The file also has no typed validation or uniqueness enforcement in the inspected code.

`scripts/run_multimodal_flow.py:24-44` reads this file only as a provenance fallback, filtering known fields into `Provenance`. Consequently, it cannot obtain task, required-field policy, governance, or source location from it. `scripts/build_demo.py` does not read it at all, so Cairo metadata exists both in the source envelope/config catalog and in Python.

## `frontend/data/platform_demo.json`

This file is a generated snapshot, not an authoring interface. It contains exactly two top-level entries:

| Lines | Dataset | Fixed top-level presentation data |
| --- | --- | --- |
| `frontend/data/platform_demo.json:6-15` | Cairo | ID, title, domain `climate_environmental`, fixture flag, Open-Meteo attribution and license |
| `frontend/data/platform_demo.json:1563-1572` | Synthetic route | ID, title, domain `logistics_mobility_sensor`, fixture flag, repository attribution and fixture license marker |

The Cairo snapshot contains 72 source records (`frontend/data/platform_demo.json:15-880`); the route snapshot contains 6 source records beginning at `frontend/data/platform_demo.json:1573`. These are recorded source/fixture observations, not hard-coded KPIs. The pipeline-derived profile, quality, analytics, evaluation, recommendations, lineage, governance, and audit data must continue to be generated from records rather than copied into configuration.

Generated ID repetitions are expected lineage/result references rather than independent hard-coding sites. For Cairo these include profile/result IDs, quality references, lineage references, and audit targets (`frontend/data/platform_demo.json:883`, `1129`, `1271`, `1282-1317`, `1465-1500`, `1511-1550`). The corresponding route references appear at `frontend/data/platform_demo.json:1714`, `2078`, `2243`, `2254-2289`, `2452-2487`, and `2498-2537`. A registry-driven build should regenerate all of them through `MultimodalPipeline`; it should not template or edit them directly.

The generated tasks are `climate` (`frontend/data/platform_demo.json:1273`, `1324`) and `mobility` (`frontend/data/platform_demo.json:2245`, `2296`). Providers reappear through normalized provenance/governance at `frontend/data/platform_demo.json:1245-1247`, `1435`, `2218-2220`, and `2421`. Those repetitions demonstrate traceability, but their source of truth should be one validated dataset definition plus the original source envelope where applicable.

## Dataset-specific scripts

### `scripts/fetch_open_meteo.py`

This is properly a provider-specific adapter, so several constants are intentional:

- Open-Meteo archive endpoint (`scripts/fetch_open_meteo.py:19`) and exact hourly field list (`scripts/fetch_open_meteo.py:22-33`, `38-44`).
- Provider response-to-canonical field mapping (`scripts/fetch_open_meteo.py:36-65`).
- Provider name, license, schema, transformations, and limitations (`scripts/fetch_open_meteo.py:67-94`).
- Exact allowlisted host (`scripts/fetch_open_meteo.py:115`), which is a desirable security control.

The script is also Cairo-instance-specific in ways that should not leak into a generic registry runner:

- Every event ID contains `open-meteo-cairo` regardless of requested coordinates (`scripts/fetch_open_meteo.py:54`).
- The default coordinate, dates, and filename are Cairo/January 2024 values (`scripts/fetch_open_meteo.py:101-109`).
- Output is restricted to `data/samples` (`scripts/fetch_open_meteo.py:18`, `111-113`). This is safe but must remain a retrieval-script policy, not a universal registry source rule.
- `device_id` and `source_system` are provider constants (`scripts/fetch_open_meteo.py:56`, `63`); they are legitimate for this adapter but should be explicit in adapter tests.

The smallest clean design is to keep this specialized retrieval adapter, fix or parameterize only instance identity where required, and let a registry entry point at its produced JSON envelope. It should not become a universal ingestion framework.

### `scripts/kaggle_to_pubsub.py`

This script uses a hard-coded four-way adapter switch (`scripts/kaggle_to_pubsub.py:23-78`) and fixed CLI choices (`scripts/kaggle_to_pubsub.py:110-119`):

| Lines | Task/use case | Dataset/provider assumptions |
| --- | --- | --- |
| `scripts/kaggle_to_pubsub.py:26-38` | `mobility_expense_assurance` | NYC yellow-taxi column names, service type, USD currency, and source dataset ID |
| `scripts/kaggle_to_pubsub.py:39-54` | `environmental_sensor_telemetry` | Kaggle telemetry column names, ID `environmental_sensor_telemetry_132k`, Fahrenheit input, sensor fields, and source dataset ID |
| `scripts/kaggle_to_pubsub.py:55-66` | `esg_transport_emissions` | DataCo column aliases, shipment defaults, USD currency, and DataCo source ID |
| `scripts/kaggle_to_pubsub.py:67-77` | `retail_transaction_privacy` | E-commerce event columns, USD currency, and source dataset ID |

The Pub/Sub topic default `verdatrace-transaction-events` and row limit `10000` (`scripts/kaggle_to_pubsub.py:109`, `121`) are operational defaults, not fixed demo-count assumptions. The documentation example contains a fixed sample path `/data/yellow_tripdata_2016-01.csv` (`scripts/kaggle_to_pubsub.py:5-10`), while the actual `--csv` argument is required and arbitrary (`scripts/kaggle_to_pubsub.py:120`).

The schema mappings are legitimate adapter logic, but the monolithic `if` chain and CLI choices mean every new Kaggle dataset requires a code edit. This script is separate from the static demo build and should not be confused with registry discovery. A future registry may reference a named adapter, while adapter implementations continue to own provider-specific column mapping.

### `config/kaggle_datasets.yml`

This file contains four literal task keys and their Kaggle slugs/expected filenames (`config/kaggle_datasets.yml:3-38`). These are appropriate retrieval constants. The current file is a second, unvalidated catalog distinct from `config/datasets.json`, with different IDs (`environmental_sensor_telemetry` versus `environmental_sensor_telemetry_132k`) and no demonstrated join rule. That mismatch is an onboarding risk. It should either become adapter-specific supplemental configuration referenced by the canonical registry ID or be merged without losing verified provenance.

### `scripts/run_multimodal_flow.py`

This is the most reusable current command. Input path, dataset ID, name, task, actor, role, max records, and output are arguments (`scripts/run_multimodal_flow.py:47-58`). Remaining hard-coded conventions are:

- Provenance fallback path `config/datasets.json` and expected `datasets` array shape (`scripts/run_multimodal_flow.py:24-25`).
- Default allowed root `data` (`scripts/run_multimodal_flow.py:50`), a safe default but not sufficient for fixture or external mounted-data registry entries.
- Default task `general` (`scripts/run_multimodal_flow.py:53`) rather than a task from validated dataset configuration.
- Source format inferred only from the filename suffix (`scripts/run_multimodal_flow.py:73`).
- It does not pass configured required fields or governance to `MultimodalPipeline.run` (`scripts/run_multimodal_flow.py:69-76`).

These are small extension points. Registry execution can reuse the command's ingestion/provenance pattern and the existing pipeline instead of creating parallel analysis code.

## Frontend fixed-count and payload assumptions

### Count behavior

- Dynamic: dataset count is `state.payload.datasets.length`, and cards are generated with `forEach` (`frontend/app.js:38-53`). There is no literal `2` or branch on the two current IDs.
- Fixed startup assumption: the first entry is selected unconditionally (`frontend/app.js:454-465`). An empty or missing `datasets` array fails in the general startup error handler.
- Selection is ID-based with `find`, but an unknown ID produces `undefined` and the next line dereferences `.records` (`frontend/app.js:407-419`). This matters for future deep links but is not a fixed-count issue.

### Required per-dataset shape

The current renderer assumes all of the following exist:

- `id`, `title`, `domain`, and `outcome.profile` for cards (`frontend/app.js:42-51`).
- `fixture`, `attribution.label`, `attribution.license`, `attribution.url`, profile fields/categories, quality, evaluation, and visualization for the header (`frontend/app.js:56-80`).
- an in-browser `records` array for temporal, map, bounds, and trend interactions (`frontend/app.js:112-150`, `166-203`, `407-450`).
- `outcome.visualization.recommended_visualizations`, `outcome.quality.issues`, `outcome.profile.fields`, `outcome.lineage`, `outcome.governance`, and `outcome.audit_events` (`frontend/app.js:287-405`).

This allows an arbitrary **number** of homogeneous, fully materialized datasets, but not arbitrary dataset types. Vector polygons, rasters, streaming references, server-paginated records, optional outcome stages, or metadata-only catalog entries need an explicit payload contract and capability-aware rendering rather than per-ID branches.

## Onboarding blockers versus intended constants

| Category | Keep as explicit data/adapter behavior | Remove from central build path |
| --- | --- | --- |
| Dataset names and providers | Verified names/providers in provenance and fixture labels | Duplicate names/providers in each explicit `build_demo.py` branch |
| Source URLs and licenses | Exact source URL, license, limitations, and retrieval policy | Duplicate top-level attribution assembled separately from the provenance/config source of truth |
| Paths | Least-privilege approved roots and a default payload output | One Python constant and one loader branch per dataset |
| Tasks and required fields | Validated per-dataset configuration values | Literal `task=` and `required_fields=` calls in the demo builder |
| Source mappings | Open-Meteo and Kaggle adapter-specific field mapping | A central builder that must understand each provider schema |
| Fixtures | Synthetic route path, fixture flag, and explicit non-operational provenance | Treating the fixture as a special hand-built payload object rather than a registered dataset |
| Results and metrics | Pipeline-computed record counts, quality scores, analytics, evaluations, and recommendations | Copying derived values into registry configuration or fabricating executive KPIs |

## Minimal target change implied by this audit

1. Define one typed executable dataset configuration schema that supplements, rather than discards, verified provenance.
2. Discover validated definitions from `config/datasets/*.yaml`, rejecting duplicate IDs and unsupported source formats before execution.
3. Preserve entries with IDs `open_meteo_cairo_historical` and `synthetic_refrigerated_route`, including the existing real source and clearly labeled fixture semantics.
4. Implement one `run_registered_dataset(config)` adapter that resolves an approved path, uses `iter_records`, builds/reuses `Provenance`, and calls `MultimodalPipeline.run` with task, required fields, and governance.
5. Replace the two literal payload entries in `build_demo.py` with registry iteration. Presentation attribution should be derived from validated configuration/provenance, while analytics and metrics remain pipeline-derived.
6. Keep `frontend/data/platform_demo.json` as generated output and add tests that assert its dataset set includes both existing IDs and that the build result count equals registry-enabled entries rather than a literal number.
7. Add an empty-registry/unknown-ID fallback in the frontend separately; do not introduce per-dataset pages or ID-specific rendering.

## Validation requirements for the implementation wave

No tests were run for this documentation-only audit. Subsequent implementation should add regression coverage proving:

- both existing IDs remain present;
- their source formats, tasks, fixture flags, provenance providers, and required-field behavior are unchanged or intentionally equivalent;
- all registry entries are iterated without a fixed count;
- duplicate IDs, malformed entries, unsupported formats, missing sources, and invalid required-field structures fail explicitly;
- pipeline-derived results are regenerated rather than read from configuration;
- an empty payload and an unknown selected ID fail or fall back safely in the browser.
