"use strict";

const assert = require("assert").strict;
const utils = require("../frontend/dataset-utils.js");

let failures = 0;
function test(name, run) {
  try {
    run();
    console.log("ok - " + name);
  } catch (error) {
    failures += 1;
    console.error("not ok - " + name);
    console.error(error);
  }
}

function dataset(overrides = {}) {
  return {
    id: "open_meteo_cairo_historical",
    title: "Cairo historical weather",
    domain: "climate_environmental",
    dataset_type: "tabular",
    fixture: false,
    records: [{ event_timestamp: "2024-01-01T00:00:00Z", latitude: 30, longitude: 31 }],
    attribution: { label: "Open-Meteo", license: "CC BY 4.0" },
    outcome: {
      profile: {
        source_format: "json",
        row_count: 1,
        geographic_bounds: { min_latitude: 30, min_longitude: 31, max_latitude: 30, max_longitude: 31 },
        temporal_coverage: { start: "2024-01-01T00:00:00Z", end: "2024-01-01T00:00:00Z" },
        categories: ["climate", "environmental", "geospatial_vector"],
        fields: [
          { name: "event_timestamp", data_type: "datetime", semantic_type: "timestamp" },
          { name: "temperature_c", data_type: "number", semantic_type: "temperature" },
        ],
      },
      manifest: {},
      governance: {},
    },
    ...overrides,
  };
}

test("payload handling accepts arbitrary and empty dataset arrays safely", () => {
  assert.deepEqual(utils.datasetsFromPayload({ datasets: [] }), []);
  assert.deepEqual(utils.datasetsFromPayload(null), []);
  assert.deepEqual(utils.datasetsFromPayload({ datasets: [{ title: "missing ID" }, dataset()] }).map((item) => item.id), [
    "open_meteo_cairo_historical",
  ]);
});

test("selection resolves known IDs and falls back for unknown IDs", () => {
  const cairo = dataset();
  const route = dataset({ id: "synthetic_refrigerated_route", title: "Synthetic refrigerated shipment route" });
  assert.equal(utils.resolveDataset([cairo, route], route.id), route);
  assert.equal(utils.resolveDataset([cairo, route], "does_not_exist"), cairo);
  assert.equal(utils.resolveDataset([], "does_not_exist"), null);
});

test("query helpers preserve a static-site path and encode dataset IDs", () => {
  assert.equal(utils.datasetIdFromSearch("?dataset=synthetic_refrigerated_route"), "synthetic_refrigerated_route");
  const updated = new URL(
    utils.urlWithDataset(
      "https://example.test/VerdaTrace-Data-Platform-/?view=map#workspace",
      "route one"
    )
  );
  assert.equal(updated.pathname, "/VerdaTrace-Data-Platform-/");
  assert.equal(updated.searchParams.get("view"), "map");
  assert.equal(updated.searchParams.get("dataset"), "route one");
  assert.equal(updated.hash, "#workspace");
});

test("search matches name, ID, and domain case-insensitively", () => {
  const cairo = dataset();
  const route = dataset({
    id: "synthetic_refrigerated_route",
    title: "Synthetic refrigerated shipment route",
    domain: "logistics_mobility_sensor",
    dataset_type: "vector",
  });
  const datasets = [cairo, route];
  assert.deepEqual(utils.filterDatasets(datasets, { query: "CAIRO" }), [cairo]);
  assert.deepEqual(utils.filterDatasets(datasets, { query: "refrigerated_route" }), [route]);
  assert.deepEqual(utils.filterDatasets(datasets, { query: "LOGISTICS" }), [route]);
  assert.deepEqual(
    utils.filterDatasets([dataset({ title: "Public label", name: "Registry weather name" })], { query: "registry weather" }).length,
    1
  );
});

test("domain and type filters are derived from dataset metadata", () => {
  const cairo = dataset();
  const route = dataset({
    id: "synthetic_refrigerated_route",
    title: "Synthetic refrigerated shipment route",
    domain: "logistics_mobility_sensor",
    dataset_type: "vector",
    outcome: {
      profile: { source_format: "geojson", categories: ["logistics", "mobility", "sensor_iot"], fields: [] },
      manifest: {},
      governance: {},
    },
  });
  assert.deepEqual(utils.availableDomainGroups([cairo, route]), ["Climate", "Mobility", "Geoinformatics", "Sensor / IoT"]);
  assert.deepEqual(utils.availableDatasetTypes([cairo, route]), ["tabular", "vector"]);
  assert.deepEqual(utils.filterDatasets([cairo, route], { domain: "Sensor / IoT" }), [route]);
  assert.deepEqual(utils.filterDatasets([cairo, route], { datasetType: "tabular" }), [cairo]);
});

test("manifest rows omit unavailable values but retain real zero and false values", () => {
  const rows = utils.manifestRows(
    dataset({
      outcome: {
        profile: { source_format: "json", row_count: 0, fields: [], categories: [] },
        governance: { source: "not_provided", license: "unknown" },
        manifest: { input_size: 0, record_count: 0, crs: null, fixture: false },
      },
      attribution: {},
    })
  );
  const byLabel = Object.fromEntries(rows.map((row) => [row.label, row.value]));
  assert.equal(byLabel["Input size"], 0);
  assert.equal(byLabel["Records / features"], 0);
  assert.equal(byLabel.Fixture, false);
  assert.equal("CRS" in byLabel, false);
  assert.equal("License" in byLabel, false);
  assert.equal(utils.hasValue(0), true);
  assert.equal(utils.hasValue(null), false);
  assert.equal(utils.numericValue(0), 0);
  assert.equal(utils.numericValue("0"), 0);
  assert.equal(utils.numericValue(null), null);
  assert.equal(utils.numericValue(""), null);
  assert.equal(utils.numericValue(false), null);
});

test("executive KPI contract is optional and keeps provenance fields", () => {
  assert.deepEqual(utils.executiveKpis(dataset({ outcome: { executive_kpis: [] } })), []);
  const kpi = {
    id: "mean_temperature",
    label: "Mean temperature",
    value: 0,
    unit: "degC",
    status: "observed",
    source_metric: "numeric_summaries.temperature_c.mean",
    analysis_stage: "analysis",
    fields_used: ["temperature_c"],
    calculation_description: "Mean over valid records",
  };
  assert.deepEqual(utils.executiveKpis(dataset({ outcome: { executive_kpis: [kpi] } })), [kpi]);
});

test("capabilities distinguish spatial, temporal, and numeric datasets", () => {
  assert.deepEqual(utils.profileCapabilities(dataset()), {
    spatial: true,
    temporal: true,
    numeric: true,
    pointRecords: true,
  });
  assert.deepEqual(
    utils.profileCapabilities({
      id: "categorical",
      records: [{ category: "a" }],
      outcome: { profile: { fields: [{ name: "category", data_type: "string", semantic_type: "categorical" }] } },
    }),
    { spatial: false, temporal: false, numeric: false, pointRecords: false }
  );
  assert.equal(
    utils.profileCapabilities({
      id: "coverage-only",
      records: [{}],
      outcome: { profile: { temporal_coverage: { start: "2024-01-01", end: "2024-01-02" }, fields: [] } },
    }).temporal,
    false
  );
});

if (failures) process.exitCode = 1;
