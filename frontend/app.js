"use strict";

const state = {
  payload: null,
  dataset: null,
  map: null,
  layers: {},
  currentRecords: [],
};

const byId = (id) => document.getElementById(id);
const formatNumber = (value, digits = 0) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(Number(value || 0));
const titleCase = (value) =>
  String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function coordinate(record) {
  if (Number.isFinite(Number(record.latitude)) && Number.isFinite(Number(record.longitude))) {
    return [Number(record.latitude), Number(record.longitude)];
  }
  if (record.geometry?.type === "Point" && Array.isArray(record.geometry.coordinates)) {
    return [Number(record.geometry.coordinates[1]), Number(record.geometry.coordinates[0])];
  }
  return null;
}

function renderDatasetList() {
  const list = byId("dataset-list");
  clear(list);
  byId("dataset-count").textContent = state.payload.datasets.length;
  state.payload.datasets.forEach((dataset) => {
    const button = element("button", "dataset-card");
    button.type = "button";
    button.setAttribute("role", "listitem");
    button.dataset.datasetId = dataset.id;
    button.append(element("span", "dataset-domain", titleCase(dataset.domain)));
    button.append(element("strong", "", dataset.title));
    const profile = dataset.outcome.profile;
    button.append(element("small", "", profile.row_count + " rows · " + profile.categories.length + " categories"));
    button.addEventListener("click", () => selectDataset(dataset.id));
    list.append(button);
  });
}

function renderHeader(dataset) {
  const outcome = dataset.outcome;
  const profile = outcome.profile;
  const quality = outcome.quality;
  const evaluation = outcome.evaluation;
  byId("dataset-title").textContent = dataset.title;
  byId("source-tag").textContent = dataset.fixture ? "Demonstration data" : "Verified external source";
  byId("fixture-tag").classList.toggle("hidden", !dataset.fixture);
  byId("dataset-subtitle").textContent = profile.categories.map(titleCase).join(" · ");
  const attribution = byId("attribution");
  attribution.textContent = dataset.attribution.label + " · " + dataset.attribution.license + " ↗";
  attribution.href = dataset.attribution.url;
  byId("metric-rows").textContent = formatNumber(profile.row_count);
  byId("metric-fields").textContent = profile.fields.length + " fields profiled";
  byId("metric-quality").textContent = formatNumber(quality.score, 1);
  byId("metric-quality-status").textContent = quality.status + " · " + quality.valid_rows + "/" + quality.total_rows + " valid";
  byId("metric-suitability").textContent = formatNumber(evaluation.score, 1) + "%";
  byId("metric-eligible").textContent = evaluation.eligible ? "eligible for requested task" : "remediation required";
  byId("metric-visuals").textContent = outcome.visualization.recommended_visualizations.length;
  byId("crs-badge").textContent = profile.geographic_bounds ? "EPSG:4326 validated" : "No spatial CRS";
  document.querySelectorAll(".dataset-card").forEach((card) => {
    const active = card.dataset.datasetId === dataset.id;
    card.classList.toggle("active", active);
    card.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function initMap() {
  if (!window.L) {
    byId("map").textContent = "The map library could not be loaded. Dataset results remain available below.";
    return;
  }
  state.map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([30.4, 30.9], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(state.map);
  state.layers.points = L.layerGroup().addTo(state.map);
  state.layers.route = L.layerGroup().addTo(state.map);
  state.layers.bounds = L.layerGroup().addTo(state.map);
}

function tooltipText(record) {
  const fields = [
    ["Time", record.event_timestamp],
    ["Device", record.device_id || record.vehicle_id],
    ["Temperature", record.temperature_c !== undefined ? record.temperature_c + " °C" : null],
    ["Humidity", record.humidity_pct !== undefined ? record.humidity_pct + "%" : null],
    ["Speed", record.speed_kph !== undefined ? record.speed_kph + " km/h" : null],
  ];
  return fields
    .filter((pair) => pair[1] !== undefined && pair[1] !== null && pair[1] !== "")
    .map((pair) => pair[0] + ": " + pair[1])
    .join("\n");
}

function renderMapRecords(records, fit = false) {
  if (!state.map) return;
  Object.values(state.layers).forEach((layer) => layer.clearLayers());
  const located = records
    .map((record) => ({ record: record, point: coordinate(record) }))
    .filter((item) => item.point);
  located.forEach(({ record, point }) => {
    L.circleMarker(point, {
      radius: 6,
      color: "#074e3d",
      weight: 2,
      fillColor: "#b7e566",
      fillOpacity: 0.9,
    })
      .bindTooltip(tooltipText(record), { direction: "top" })
      .addTo(state.layers.points);
  });
  const hasRoute = state.dataset.outcome.visualization.recommended_visualizations.some(
    (item) => item.type === "route_map"
  );
  if (hasRoute && located.length > 1) {
    L.polyline(
      located.map((item) => item.point),
      { color: "#0d785c", weight: 4, opacity: 0.85 }
    ).addTo(state.layers.route);
  }
  if (located.length) {
    const bounds = L.latLngBounds(located.map((item) => item.point));
    L.rectangle(bounds.pad(0.08), {
      color: "#276a87",
      weight: 1,
      dashArray: "5 5",
      fillOpacity: 0.02,
    }).addTo(state.layers.bounds);
    if (fit) state.map.fitBounds(bounds.pad(0.25), { maxZoom: 12 });
  }
  byId("visible-count").textContent = located.length + " visible";
  syncLayerVisibility();
}

function syncLayerVisibility() {
  if (!state.map) return;
  [
    ["points", "toggle-points"],
    ["route", "toggle-route"],
    ["bounds", "toggle-bounds"],
  ].forEach(([layerName, controlId]) => {
    const layer = state.layers[layerName];
    const visible = byId(controlId).checked;
    if (visible && !state.map.hasLayer(layer)) layer.addTo(state.map);
    if (!visible && state.map.hasLayer(layer)) state.map.removeLayer(layer);
  });
}

function configureTemporalFilter(records) {
  const slider = byId("time-filter");
  slider.min = "1";
  slider.max = String(Math.max(records.length, 1));
  slider.value = String(Math.max(records.length, 1));
  byId("time-label").textContent = "All " + records.length + " observations";
}

function numericFields(profile) {
  return profile.fields.filter(
    (field) =>
      field.data_type === "number" &&
      !["latitude", "longitude"].includes(field.semantic_type)
  );
}

function renderMetricOptions() {
  const select = byId("metric-select");
  clear(select);
  numericFields(state.dataset.outcome.profile).forEach((field) => {
    const option = element("option", "", titleCase(field.name));
    option.value = field.name;
    select.append(option);
  });
  drawTrend();
}

function drawTrend() {
  const canvas = byId("trend-chart");
  const context = canvas.getContext("2d");
  const field = byId("metric-select").value;
  const values = state.currentRecords
    .map((record, index) => ({
      index: index,
      value: Number(record[field]),
      time: record.event_timestamp,
    }))
    .filter((item) => Number.isFinite(item.value));
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  if (!values.length) {
    context.fillStyle = "#687a74";
    context.font = "16px sans-serif";
    context.fillText("No numeric values available", 26, 46);
    byId("chart-summary").textContent = "Choose another field or dataset.";
    return;
  }
  const padding = { left: 58, right: 22, top: 30, bottom: 42 };
  const min = Math.min(...values.map((item) => item.value));
  const max = Math.max(...values.map((item) => item.value));
  const span = max - min || 1;
  const x = (position) =>
    padding.left +
    (position / Math.max(values.length - 1, 1)) *
      (width - padding.left - padding.right);
  const y = (value) =>
    padding.top +
    (1 - (value - min) / span) *
      (height - padding.top - padding.bottom);
  context.strokeStyle = "#dfe8e3";
  context.fillStyle = "#687a74";
  context.lineWidth = 1;
  context.font = "11px sans-serif";
  for (let step = 0; step <= 4; step += 1) {
    const value = min + (span * step) / 4;
    const vertical = y(value);
    context.beginPath();
    context.moveTo(padding.left, vertical);
    context.lineTo(width - padding.right, vertical);
    context.stroke();
    context.fillText(value.toFixed(span < 10 ? 1 : 0), 8, vertical + 4);
  }
  const gradient = context.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, "rgba(13,120,92,.28)");
  gradient.addColorStop(1, "rgba(13,120,92,.01)");
  context.beginPath();
  values.forEach((item, position) => {
    if (position === 0) context.moveTo(x(position), y(item.value));
    else context.lineTo(x(position), y(item.value));
  });
  context.lineTo(x(values.length - 1), height - padding.bottom);
  context.lineTo(x(0), height - padding.bottom);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();
  context.beginPath();
  values.forEach((item, position) => {
    if (position === 0) context.moveTo(x(position), y(item.value));
    else context.lineTo(x(position), y(item.value));
  });
  context.strokeStyle = "#0d785c";
  context.lineWidth = 3;
  context.stroke();
  context.fillStyle = "#10251f";
  const start = values[0].time
    ? new Date(values[0].time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "First";
  const finalValue = values[values.length - 1];
  const end = finalValue.time
    ? new Date(finalValue.time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "Last";
  context.fillText(start, padding.left, height - 16);
  const endWidth = context.measureText(end).width;
  context.fillText(end, width - padding.right - endWidth, height - 16);
  const mean = values.reduce((sum, item) => sum + item.value, 0) / values.length;
  byId("chart-summary").textContent =
    titleCase(field) +
    " ranges from " +
    formatNumber(min, 2) +
    " to " +
    formatNumber(max, 2) +
    "; mean " +
    formatNumber(mean, 2) +
    " across " +
    values.length +
    " observations.";
}

function renderRecommendations() {
  const container = byId("recommendations");
  clear(container);
  const recommendation = state.dataset.outcome.visualization;
  recommendation.recommended_visualizations.forEach((item, index) => {
    const card = element("div", "recommendation");
    card.append(element("div", "recommendation-icon", String(index + 1).padStart(2, "0")));
    const copy = element("div");
    copy.append(element("strong", "", titleCase(item.type)));
    copy.append(element("p", "", item.reason));
    copy.append(element("code", "", item.fields.length ? item.fields.join(" · ") : "dataset layer"));
    card.append(copy);
    card.append(element("span", "confidence", Math.round(item.confidence * 100) + "%"));
    container.append(card);
  });
  const warningBox = byId("recommendation-warnings");
  const warnings = recommendation.warnings || [];
  warningBox.classList.toggle("hidden", warnings.length === 0);
  warningBox.textContent = warnings.join(" ");
}

function renderQuality() {
  const quality = state.dataset.outcome.quality;
  const pill = byId("quality-pill");
  pill.textContent = quality.status;
  pill.className = "status-pill " + quality.status;
  const container = byId("quality-results");
  clear(container);
  if (!quality.issues.length) {
    const empty = element("div", "quality-empty");
    const copy = element("div");
    copy.append(element("strong", "", "100"));
    copy.append(element("span", "", "All configured checks passed for this bounded sample."));
    empty.append(copy);
    container.append(empty);
    return;
  }
  quality.issues.forEach((issue) => {
    const card = element("div", "quality-issue " + issue.severity);
    card.append(
      element(
        "strong",
        "",
        titleCase(issue.code) + " · " + issue.row_indexes.length + " rows"
      )
    );
    card.append(element("span", "", issue.message));
    container.append(card);
  });
}

function renderFieldTable() {
  const body = byId("field-table");
  clear(body);
  state.dataset.outcome.profile.fields.forEach((field) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.append(element("code", "", field.name));
    row.append(name);
    row.append(element("td", "", titleCase(field.data_type)));
    row.append(element("td", "", titleCase(field.semantic_type)));
    const confidence = document.createElement("td");
    confidence.append(document.createTextNode(Math.round(field.confidence * 100) + "%"));
    const bar = element("div", "confidence-bar");
    const fill = element("span");
    fill.style.width = field.confidence * 100 + "%";
    bar.append(fill);
    confidence.append(bar);
    row.append(confidence);
    row.append(element("td", "", field.evidence.join("; ")));
    body.append(row);
  });
}

function renderLineage() {
  const list = byId("lineage-list");
  clear(list);
  state.dataset.outcome.lineage.forEach((step, index) => {
    const item = element("li");
    item.dataset.step = String(index + 1);
    item.append(element("strong", "", titleCase(step.stage)));
    item.append(
      element(
        "small",
        "",
        titleCase(step.operation) + " · " + step.input_ref + " → " + step.output_ref
      )
    );
    list.append(item);
  });
}

function renderGovernance() {
  const governance = state.dataset.outcome.governance;
  const list = byId("governance-list");
  clear(list);
  [
    "owner",
    "source",
    "license",
    "sensitivity",
    "retention_policy",
    "schema_version",
    "quality_status",
    "temporal_coverage",
  ].forEach((key) => {
    const wrapper = element("div");
    wrapper.append(element("dt", "", titleCase(key)));
    const value = Array.isArray(governance[key])
      ? governance[key].join(", ")
      : governance[key];
    wrapper.append(element("dd", "", value || "not_provided"));
    list.append(wrapper);
  });
  const audit = state.dataset.outcome.audit_events;
  byId("audit-summary").textContent =
    audit.length +
    " structured audit records · actor, operation, outcome, target, timestamp, and correlation ID retained · secret-like fields redacted.";
}

function selectDataset(datasetId) {
  state.dataset = state.payload.datasets.find((dataset) => dataset.id === datasetId);
  state.currentRecords = state.dataset.records.slice();
  renderHeader(state.dataset);
  configureTemporalFilter(state.dataset.records);
  renderMapRecords(state.currentRecords, true);
  renderMetricOptions();
  renderRecommendations();
  renderQuality();
  renderFieldTable();
  renderLineage();
  renderGovernance();
}

function bindControls() {
  ["toggle-points", "toggle-route", "toggle-bounds"].forEach((id) =>
    byId(id).addEventListener("change", syncLayerVisibility)
  );
  byId("metric-select").addEventListener("change", drawTrend);
  byId("time-filter").addEventListener("input", (event) => {
    const count = Number(event.target.value);
    state.currentRecords = state.dataset.records.slice(0, count);
    byId("time-label").textContent =
      count === state.dataset.records.length
        ? "All " + count + " observations"
        : "First " + count + " observations";
    renderMapRecords(state.currentRecords);
    drawTrend();
  });
  byId("filter-bounds").addEventListener("click", () => {
    if (!state.map) return;
    const bounds = state.map.getBounds();
    state.currentRecords = state.dataset.records.filter((record) => {
      const point = coordinate(record);
      return point && bounds.contains(point);
    });
    renderMapRecords(state.currentRecords);
    drawTrend();
  });
  byId("reset-map").addEventListener("click", () => {
    state.currentRecords = state.dataset.records.slice();
    configureTemporalFilter(state.currentRecords);
    renderMapRecords(state.currentRecords, true);
    drawTrend();
  });
}

async function start() {
  try {
    const response = await fetch("./data/platform_demo.json", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    state.payload = await response.json();
    renderDatasetList();
    initMap();
    bindControls();
    selectDataset(state.payload.datasets[0].id);
  } catch (error) {
    byId("dataset-title").textContent = "Demo data could not be loaded";
    byId("dataset-subtitle").textContent =
      "Serve the frontend directory over HTTP and rebuild the normalized payload.";
    console.error("VerdaTrace startup failed", error);
  }
}

document.addEventListener("DOMContentLoaded", start);
