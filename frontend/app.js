"use strict";

const DatasetUtils = window.VerdaTraceDatasetUtils;

const state = {
  payload: null,
  dataset: null,
  map: null,
  layers: {},
  currentRecords: [],
  filters: { query: "", domain: "all", datasetType: "all" },
};

const byId = (id) => document.getElementById(id);
const asArray = (value) => (Array.isArray(value) ? value : []);
const recordsForDataset = (dataset) =>
  asArray(dataset?.records).filter((record) => record && typeof record === "object" && !Array.isArray(record));
const isFiniteValue = (value) => DatasetUtils.numericValue(value) !== null;
const formatNumber = (value, digits = 0) => {
  if (!isFiniteValue(value)) return "—";
  return new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(Number(value));
};
const titleCase = (value) =>
  String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const MAP_FEATURE_LIMIT = 1500;

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
  if (isFiniteValue(record?.latitude) && isFiniteValue(record?.longitude)) {
    const point = [Number(record.latitude), Number(record.longitude)];
    if (point[0] >= -90 && point[0] <= 90 && point[1] >= -180 && point[1] <= 180) return point;
  }
  if (record?.geometry?.type === "Point" && Array.isArray(record.geometry.coordinates)) {
    const latitude = record.geometry.coordinates[1];
    const longitude = record.geometry.coordinates[0];
    if (isFiniteValue(latitude) && isFiniteValue(longitude)) {
      const point = [Number(latitude), Number(longitude)];
      if (point[0] >= -90 && point[0] <= 90 && point[1] >= -180 && point[1] <= 180) return point;
    }
  }
  return null;
}

function populateFilter(select, values, selected, allLabel) {
  clear(select);
  const all = element("option", "", allLabel);
  all.value = "all";
  select.append(all);
  values.forEach((value) => {
    const option = element("option", "", titleCase(value));
    option.value = value;
    select.append(option);
  });
  select.value = values.includes(selected) ? selected : "all";
}

function renderCatalogFilters() {
  const datasets = DatasetUtils.datasetsFromPayload(state.payload);
  populateFilter(
    byId("domain-filter"),
    DatasetUtils.availableDomainGroups(datasets),
    state.filters.domain,
    "All domains"
  );
  populateFilter(
    byId("type-filter"),
    DatasetUtils.availableDatasetTypes(datasets),
    state.filters.datasetType,
    "All types"
  );
  state.filters.domain = byId("domain-filter").value;
  state.filters.datasetType = byId("type-filter").value;
}

function renderDatasetList() {
  const list = byId("dataset-list");
  clear(list);
  const datasets = DatasetUtils.datasetsFromPayload(state.payload);
  const filtered = DatasetUtils.filterDatasets(datasets, state.filters);
  byId("dataset-count").textContent = filtered.length;
  byId("catalog-status").textContent =
    filtered.length === datasets.length
      ? datasets.length + (datasets.length === 1 ? " dataset" : " datasets")
      : "Showing " + filtered.length + " of " + datasets.length + " datasets";
  if (!filtered.length) {
    list.append(element("p", "catalog-empty", datasets.length ? "No datasets match these filters." : "No datasets are available."));
    return;
  }
  filtered.forEach((dataset) => {
    const button = element("button", "dataset-card");
    button.type = "button";
    button.setAttribute("role", "listitem");
    button.dataset.datasetId = dataset.id;
    button.append(element("span", "dataset-domain", titleCase(dataset.domain || DatasetUtils.datasetType(dataset) || "registered")));
    button.append(element("strong", "", DatasetUtils.datasetName(dataset)));
    const profile = dataset.outcome?.profile || {};
    const rows = formatNumber(profile.row_count);
    const categories = asArray(profile.categories);
    const details = [rows === "—" ? null : rows + " rows", categories.length ? categories.length + " categories" : null]
      .filter(Boolean)
      .join(" · ");
    button.append(element("small", "", details || "Metadata available after processing"));
    button.addEventListener("click", () => selectDataset(dataset.id, { updateUrl: true }));
    list.append(button);
  });
  if (state.dataset) updateActiveDatasetCard(state.dataset.id);
}

function updateActiveDatasetCard(datasetId) {
  document.querySelectorAll(".dataset-card").forEach((card) => {
    const active = card.dataset.datasetId === datasetId;
    card.classList.toggle("active", active);
    card.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function renderProcessing() {
  const panel = byId("processing-panel");
  const container = byId("processing-metrics");
  const summary = byId("quarantine-summary");
  clear(container);
  clear(summary);
  const processing = state.dataset?.outcome?.processing;
  if (!processing || typeof processing !== "object") {
    panel.classList.add("hidden");
    summary.classList.add("hidden");
    return;
  }
  const formatBytes = (value) => {
    if (!isFiniteValue(value)) return "—";
    const bytes = Number(value);
    if (bytes < 1024) return bytes.toLocaleString() + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };
  const definitions = [
    ["records_processed", "Processed records", (value) => formatNumber(value)],
    ["records_valid", "Valid", (value) => formatNumber(value)],
    ["records_repaired", "Repaired", (value) => formatNumber(value)],
    ["records_quarantined", "Quarantined", (value) => formatNumber(value)],
    ["records_rejected", "Rejected", (value) => formatNumber(value)],
    ["duration_seconds", "Duration", (value) => formatNumber(value, 3) + " s"],
    ["throughput_records_per_second", "Throughput", (value) => formatNumber(value, 2) + " records/s"],
    ["input_bytes", "Input size", formatBytes],
    ["output_bytes", "Output size", formatBytes],
  ];
  definitions
    .filter(([key]) => DatasetUtils.hasValue(processing[key]))
    .forEach(([key, label, formatter]) => {
      const card = element("article", "processing-metric");
      card.append(element("span", "", label));
      card.append(element("strong", "", formatter(processing[key])));
      container.append(card);
    });
  const quarantine = asArray(state.dataset?.outcome?.quarantine);
  const statusCounts = state.dataset?.outcome?.quality?.metrics?.record_status_counts;
  if (statusCounts && typeof statusCounts === "object" && Number(statusCounts.REPAIRABLE || 0) > 0) {
    summary.append(element("strong", "", "Record routing: "+ ["VALID", "REPAIRABLE", "QUARANTINED", "REJECTED"]
      .filter((status) => DatasetUtils.hasValue(statusCounts[status]))
      .map((status) => titleCase(status) + ": " + statusCounts[status]).join(" · ")));
    summary.classList.remove("hidden");
  }
  if (quarantine.length) {
    const breakdown = {};
    quarantine.forEach((item) => {
      const code = item.issue_code || "quality_issue";
      breakdown[code] = (breakdown[code] || 0) + 1;
    });
    summary.append(element("strong", "", quarantine.length + " records routed out of the clean path"));
    summary.append(document.createTextNode(
      Object.entries(breakdown).map(([code, count]) => titleCase(code) + ": " + count).join(" · ")
    ));
    summary.classList.remove("hidden");
  }
  panel.classList.toggle("hidden", !container.childElementCount && !quarantine.length);
}

function renderHeader(dataset) {
  const outcome = dataset.outcome || {};
  const profile = outcome.profile || {};
  const quality = outcome.quality || {};
  const evaluation = outcome.evaluation || {};
  const recommendation = outcome.visualization || {};
  const fixture = outcome.manifest?.fixture ?? dataset.fixture;
  byId("dataset-title").textContent = DatasetUtils.datasetName(dataset);
  byId("source-tag").textContent = fixture === true ? "Demonstration data" : fixture === false ? "Verified external source" : "Registered dataset";
  byId("fixture-tag").classList.toggle("hidden", fixture !== true);
  const categories = asArray(profile.categories);
  byId("dataset-subtitle").textContent = categories.length
    ? categories.map(titleCase).join(" · ")
    : titleCase(dataset.domain || DatasetUtils.datasetType(dataset) || "Metadata not provided");
  const attribution = byId("attribution");
  const attributionData = dataset.attribution || {};
  const attributionText = [attributionData.label, attributionData.license]
    .filter(DatasetUtils.hasValue)
    .join(" · ");
  attribution.textContent = attributionText + (attributionData.url ? " ↗" : "");
  attribution.classList.toggle("hidden", !attributionText && !attributionData.url);
  if (attributionData.url) attribution.href = attributionData.url;
  else attribution.removeAttribute("href");
  byId("metric-rows").textContent = formatNumber(profile.row_count);
  byId("metric-fields").textContent = Array.isArray(profile.fields) ? profile.fields.length + " fields profiled" : "Field profile unavailable";
  byId("metric-quality").textContent = formatNumber(quality.score, 1);
  const qualityCounts = isFiniteValue(quality.valid_rows) && isFiniteValue(quality.total_rows)
    ? quality.valid_rows + "/" + quality.total_rows + " valid"
    : null;
  byId("metric-quality-status").textContent = [quality.status, qualityCounts].filter(DatasetUtils.hasValue).join(" · ") || "Quality not evaluated";
  const suitability = formatNumber(evaluation.score, 1);
  byId("metric-suitability").textContent = suitability === "—" ? "—" : suitability + "%";
  byId("metric-eligible").textContent =
    evaluation.eligible === true ? "eligible for requested task" : evaluation.eligible === false ? "remediation required" : "Suitability not evaluated";
  byId("metric-visuals").textContent = Array.isArray(recommendation.recommended_visualizations)
    ? recommendation.recommended_visualizations.length
    : "—";
  const crs = outcome.manifest?.crs;
  byId("crs-badge").textContent = crs || (profile.geographic_bounds ? "EPSG:4326 validated" : "No spatial CRS");
  updateActiveDatasetCard(dataset.id);
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
  state.layers.geometry = L.featureGroup().addTo(state.map);
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
  const preferredNames = new Set(["event_timestamp", "device_id", "vehicle_id", "temperature_c", "humidity_pct", "speed_kph"]);
  asArray(state.dataset?.outcome?.profile?.fields).forEach((field) => {
    if (!preferredNames.has(field.name) && DatasetUtils.hasValue(record[field.name]) && typeof record[field.name] !== "object") {
      fields.push([titleCase(field.name), record[field.name]]);
    }
  });
  return fields
    .filter((pair) => pair[1] !== undefined && pair[1] !== null && pair[1] !== "")
    .slice(0, 7)
    .map((pair) => pair[0] + ": " + pair[1])
    .join("\n");
}

function setMapStatus(message) {
  const status = byId("map-status");
  status.textContent = message || "";
  status.classList.toggle("hidden", !message);
}

function renderMapRecords(records, fit = false) {
  const capabilities = DatasetUtils.profileCapabilities(state.dataset);
  const spatialControls = ["toggle-points", "toggle-route", "toggle-bounds", "filter-bounds", "reset-map"];
  spatialControls.forEach((id) => {
    byId(id).disabled = !capabilities.spatial;
  });
  if (!state.map) {
    setMapStatus(capabilities.spatial ? "Spatial metadata is available, but the interactive map could not be loaded." : "This dataset has no spatial fields.");
    return;
  }
  Object.values(state.layers).forEach((layer) => layer.clearLayers());
  const mapRecords = records.slice(0, MAP_FEATURE_LIMIT);
  const mapTruncated = records.length > mapRecords.length;
  const located = mapRecords
    .map((record) => ({ record: record, point: coordinate(record) }))
    .filter((item) => item.point);
  const geometries = mapRecords.filter(
    (record) => record?.geometry && typeof record.geometry === "object" && typeof record.geometry.type === "string"
  );
  let renderedGeometries = 0;
  geometries.forEach((record) => {
    try {
      L.geoJSON(record.geometry, {
        style: { color: "#276a87", weight: 2, fillColor: "#9dc4d4", fillOpacity: 0.28 },
        pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
          radius: 5, color: "#276a87", weight: 2, fillColor: "#9dc4d4", fillOpacity: 0.85,
        }),
      }).bindTooltip(tooltipText(record), { direction: "top" }).addTo(state.layers.geometry);
      renderedGeometries += 1;
    } catch (error) {
      console.warn("Skipping an invalid preview geometry", error);
    }
  });
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
  const hasRoute = asArray(state.dataset?.outcome?.visualization?.recommended_visualizations).some(
    (item) => item.type === "route_map"
  );
  if (hasRoute && located.length > 1) {
    L.polyline(
      located.map((item) => item.point),
      { color: "#0d785c", weight: 4, opacity: 0.85 }
    ).addTo(state.layers.route);
  }
  const geometryBounds = renderedGeometries ? state.layers.geometry.getBounds() : null;
  if (located.length || (geometryBounds && geometryBounds.isValid())) {
    const bounds = located.length ? L.latLngBounds(located.map((item) => item.point)) : geometryBounds;
    L.rectangle(bounds.pad(0.08), {
      color: "#276a87",
      weight: 1,
      dashArray: "5 5",
      fillOpacity: 0.02,
    }).addTo(state.layers.bounds);
    if (fit) state.map.fitBounds(bounds.pad(0.25), { maxZoom: 12 });
  }
  if (mapTruncated) {
    setMapStatus("Map displays a bounded preview of the first " + MAP_FEATURE_LIMIT.toLocaleString() + " records; analytics reflect the complete processed dataset.");
  } else if (located.length || geometries.length) setMapStatus("");
  else if (capabilities.spatial) {
    setMapStatus("Spatial metadata is available, but this preview contains no renderable geometries.");
  } else setMapStatus("This dataset has no spatial fields, so map controls are not applicable.");
  byId("visible-count").textContent = (located.length + geometries.length) + " visible";
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
    const control = byId(controlId);
    if (!layer || !control) return;
    const visible = control.checked;
    if (visible && !state.map.hasLayer(layer)) layer.addTo(state.map);
    if (!visible && state.map.hasLayer(layer)) state.map.removeLayer(layer);
  });
}

function temporalFieldName(profile) {
  return asArray(profile?.fields).find((field) => ["timestamp", "date"].includes(field.semantic_type))?.name || null;
}

function configureTemporalFilter(records) {
  const slider = byId("time-filter");
  const temporal = DatasetUtils.profileCapabilities(state.dataset).temporal;
  byId("time-control").classList.toggle("hidden", !temporal);
  slider.disabled = !temporal || !records.length;
  slider.min = "1";
  slider.max = String(Math.max(records.length, 1));
  slider.value = String(Math.max(records.length, 1));
  byId("time-label").textContent = temporal
    ? "All " + records.length + " observations"
    : "No temporal field detected";
}

function numericFields(profile) {
  return asArray(profile?.fields).filter(
    (field) =>
      field.data_type === "number" &&
      !["latitude", "longitude"].includes(field.semantic_type)
  );
}

function renderMetricOptions() {
  const select = byId("metric-select");
  clear(select);
  const fields = numericFields(state.dataset?.outcome?.profile);
  fields.forEach((field) => {
    const option = element("option", "", titleCase(field.name));
    option.value = field.name;
    select.append(option);
  });
  select.disabled = !fields.length;
  drawTrend();
}

function drawCanvasMessage(context, canvas, message, summary) {
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#687a74";
  context.font = "16px sans-serif";
  context.fillText(message, 26, 46);
  byId("chart-summary").textContent = summary;
}

function drawTrend() {
  const canvas = byId("trend-chart");
  const context = canvas.getContext("2d");
  const field = byId("metric-select").value;
  const capabilities = DatasetUtils.profileCapabilities(state.dataset);
  if (!capabilities.numeric) {
    drawCanvasMessage(context, canvas, "No numeric measurements available", "This dataset has no profiled numeric measure to chart.");
    return;
  }
  if (!capabilities.temporal) {
    drawCanvasMessage(context, canvas, "No temporal field detected", "A trend is not rendered because record order has no verified temporal meaning.");
    return;
  }
  const timeField = temporalFieldName(state.dataset?.outcome?.profile);
  const values = state.currentRecords
    .map((record, index) => ({
      index: index,
      value: isFiniteValue(record[field]) ? Number(record[field]) : null,
      time: timeField ? record[timeField] : record.event_timestamp,
    }))
    .filter((item) => item.value !== null);
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  if (!values.length) {
    drawCanvasMessage(context, canvas, "No numeric values available", "Choose another field or dataset.");
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
  const localTime = (value, fallback) => {
    if (!value) return fallback;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
      ? fallback
      : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  };
  const start = localTime(values[0].time, "First");
  const finalValue = values[values.length - 1];
  const end = localTime(finalValue.time, "Last");
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
  const recommendation = state.dataset?.outcome?.visualization || {};
  const recommendations = asArray(recommendation.recommended_visualizations);
  if (!recommendations.length) {
    container.append(element("p", "panel-empty", "No safe visualization has been recommended for this dataset."));
  }
  recommendations.forEach((item, index) => {
    const card = element("div", "recommendation");
    card.append(element("div", "recommendation-icon", String(index + 1).padStart(2, "0")));
    const copy = element("div");
    copy.append(element("strong", "", titleCase(item.type || "visualization")));
    copy.append(element("p", "", item.reason || "Recommendation reason was not provided."));
    const fields = asArray(item.fields);
    copy.append(element("code", "", fields.length ? fields.join(" · ") : "dataset layer"));
    card.append(copy);
    if (isFiniteValue(item.confidence)) card.append(element("span", "confidence", Math.round(item.confidence * 100) + "%"));
    container.append(card);
  });
  const warningBox = byId("recommendation-warnings");
  const warnings = asArray(recommendation.warnings);
  warningBox.classList.toggle("hidden", warnings.length === 0);
  warningBox.textContent = warnings.join(" ");
}

function renderQuality() {
  const quality = state.dataset?.outcome?.quality;
  const pill = byId("quality-pill");
  const container = byId("quality-results");
  clear(container);
  if (!quality) {
    pill.textContent = "not evaluated";
    pill.className = "status-pill";
    container.append(element("p", "panel-empty", "No machine-readable quality report is available."));
    return;
  }
  pill.textContent = quality.status || "not evaluated";
  pill.className = "status-pill " + (quality.status || "");
  const issues = asArray(quality.issues);
  if (!issues.length) {
    const empty = element("div", "quality-empty");
    const copy = element("div");
    copy.append(element("strong", "", formatNumber(quality.score, 1)));
    copy.append(element("span", "", isFiniteValue(quality.score) ? "No issues were reported by the configured checks." : "No quality issues or score were reported."));
    empty.append(copy);
    container.append(empty);
    return;
  }
  issues.forEach((issue) => {
    const card = element("div", "quality-issue " + issue.severity);
    const issueLabel = issue.code || issue.issue || "quality_issue";
    const issueCount = Array.isArray(issue.row_indexes) ? issue.row_indexes.length : issue.count;
    const issueMessage = issue.message || issue.reason || issue.expected_condition || "Quality rule was triggered.";
    card.append(
      element(
        "strong",
        "",
        titleCase(issueLabel) + (DatasetUtils.hasValue(issueCount) ? " · " + formatNumber(issueCount) + " rows" : "")
      )
    );
    card.append(element("span", "", issueMessage));
    container.append(card);
  });
}

function renderFieldTable() {
  const body = byId("field-table");
  clear(body);
  const fields = asArray(state.dataset?.outcome?.profile?.fields);
  if (!fields.length) {
    const row = document.createElement("tr");
    const cell = element("td", "table-empty", "No semantic field profile is available.");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
    return;
  }
  fields.forEach((field) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.append(element("code", "", field.name));
    row.append(name);
    row.append(element("td", "", titleCase(field.data_type)));
    row.append(element("td", "", titleCase(field.semantic_type)));
    const confidence = document.createElement("td");
    confidence.append(document.createTextNode(isFiniteValue(field.confidence) ? Math.round(field.confidence * 100) + "%" : "—"));
    const bar = element("div", "confidence-bar");
    const fill = element("span");
    fill.style.width = isFiniteValue(field.confidence) ? Math.max(0, Math.min(100, field.confidence * 100)) + "%" : "0";
    bar.append(fill);
    confidence.append(bar);
    row.append(confidence);
    row.append(element("td", "", asArray(field.evidence).join("; ") || "No evidence provided"));
    body.append(row);
  });
}

function renderLineage() {
  const list = byId("lineage-list");
  clear(list);
  const lineage = asArray(state.dataset?.outcome?.lineage);
  if (!lineage.length) {
    list.append(element("li", "lineage-empty", "No lineage steps are available."));
    return;
  }
  lineage.forEach((step, index) => {
    const item = element("li");
    item.dataset.step = String(index + 1);
    item.append(element("strong", "", titleCase(step.stage)));
    item.append(
      element(
        "small",
        "",
        [titleCase(step.operation), step.input_ref && step.output_ref ? step.input_ref + " → " + step.output_ref : null]
          .filter(Boolean)
          .join(" · ") || "Details not provided"
      )
    );
    list.append(item);
  });
}

function renderGovernance() {
  const governance = state.dataset?.outcome?.governance || {};
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
    wrapper.append(element("dd", "", DatasetUtils.hasValue(value) ? value : "not_provided"));
    list.append(wrapper);
  });
  const audit = asArray(state.dataset?.outcome?.audit_events);
  byId("audit-summary").textContent =
    audit.length +
    " structured audit records · actor, operation, outcome, target, timestamp, and correlation ID retained · secret-like fields redacted.";
}

function formatManifestValue(row) {
  const value = row.value;
  if (row.kind === "boolean") return value ? "Yes" : "No";
  if (row.kind === "bytes") return formatNumber(value) + " bytes";
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") {
    if (value.start || value.end) return [value.start, value.end].filter(DatasetUtils.hasValue).join(" → ");
    const minLatitude = value.min_latitude ?? value.south;
    const minLongitude = value.min_longitude ?? value.west;
    const maxLatitude = value.max_latitude ?? value.north;
    const maxLongitude = value.max_longitude ?? value.east;
    if ([minLatitude, minLongitude, maxLatitude, maxLongitude].every(isFiniteValue)) {
      return minLatitude + ", " + minLongitude + " → " + maxLatitude + ", " + maxLongitude;
    }
    return Object.entries(value).map(([key, item]) => titleCase(key) + ": " + item).join(" · ");
  }
  return String(value);
}

function renderManifest() {
  const list = byId("manifest-list");
  clear(list);
  const rows = DatasetUtils.manifestRows(state.dataset);
  byId("manifest-empty").classList.toggle("hidden", rows.length > 0);
  const note = byId("preview-note");
  const total = state.dataset?.outcome?.manifest?.record_count;
  const shown = asArray(state.dataset?.records).length;
  if (note) {
    note.textContent = Number.isFinite(total) && shown < total
      ? `Browser maps and charts show a bounded preview (${shown.toLocaleString()} of ${total.toLocaleString()} records); full-dataset analytics remain in the VerdaTrace pipeline.`
      : "Browser maps and charts render the records in this portal payload; full-dataset analytics remain in the VerdaTrace pipeline.";
  }
  rows.forEach((row) => {
    const wrapper = element("div");
    wrapper.append(element("dt", "", row.label));
    wrapper.append(element("dd", "", formatManifestValue(row)));
    list.append(wrapper);
  });
}

function renderAnalysisSummary() {
  const panel = byId("analysis-summary-panel");
  const container = byId("analysis-summary");
  if (!panel || !container) return;
  clear(container);
  const values = state.dataset?.outcome?.analysis?.computed_values || {};
  const entries = Object.entries(values).filter(([key, value]) => key !== "source_sha256" && DatasetUtils.hasValue(value));
  panel.classList.toggle("hidden", entries.length === 0);
  entries.slice(0, 12).forEach(([key, value]) => {
    const card = element("div", "analysis-metric");
    card.append(element("span", "", titleCase(key)));
    const display = typeof value === "number" ? formatNumber(value, 2) : typeof value === "object" ? JSON.stringify(value) : String(value);
    card.append(element("strong", "", display));
    container.append(card);
  });
}

function renderExecutiveKpis() {
  const panel = byId("executive-kpi-panel");
  const container = byId("executive-kpis");
  clear(container);
  const kpis = DatasetUtils.executiveKpis(state.dataset);
  panel.classList.toggle("hidden", kpis.length === 0);
  kpis.forEach((kpi) => {
    const card = element("article", "executive-kpi");
    const value = kpi.value === null || kpi.value === undefined || kpi.value === ""
      ? "—"
      : isFiniteValue(kpi.value) ? formatNumber(kpi.value, 2) : String(kpi.value);
    card.append(element("span", "executive-kpi-label", kpi.label));
    card.append(element("strong", "executive-kpi-value", value + (DatasetUtils.hasValue(kpi.unit) ? " " + kpi.unit : "")));
    if (DatasetUtils.hasValue(kpi.status)) card.append(element("span", "executive-kpi-status", kpi.status));
    if (DatasetUtils.hasValue(kpi.description)) card.append(element("p", "executive-kpi-description", kpi.description));
    const provenance = [
      kpi.source_metric ? "Metric: " + kpi.source_metric : null,
      kpi.analysis_stage ? "Stage: " + kpi.analysis_stage : null,
      Array.isArray(kpi.fields_used) && kpi.fields_used.length ? "Fields: " + kpi.fields_used.join(", ") : null,
      kpi.calculation_description ? "Calculation: " + kpi.calculation_description : null,
    ].filter(Boolean);
    if (provenance.length) card.append(element("small", "executive-kpi-provenance", provenance.join(" · ")));
    container.append(card);
  });
}

function renderPlatformOverview(platform) {
  const overview = byId("platform-overview");
  if (!overview) return;
  if (!platform || typeof platform !== "object") {
    overview.classList.add("hidden");
    return;
  }
  overview.classList.remove("hidden");
  const source = platform.source_pack || {};
  byId("pack-status").textContent = source.fixture === true ? "Synthetic pack · derived" : "Pack loaded";
  const kpiContainer = byId("platform-kpis");
  clear(kpiContainer);
  asArray(platform.executive_kpis).forEach((kpi) => {
    const card = element("article", "executive-kpi");
    const value = kpi.value === null || kpi.value === undefined ? "—" : isFiniteValue(kpi.value) ? formatNumber(kpi.value, 2) : String(kpi.value);
    card.append(element("span", "executive-kpi-label", kpi.label || kpi.id || "KPI"));
    card.append(element("strong", "executive-kpi-value", value + (kpi.unit ? " " + kpi.unit : "")));
    if (kpi.description) card.append(element("p", "executive-kpi-description", kpi.description));
    if (kpi.source_metric) card.append(element("small", "executive-kpi-provenance", "Source: " + kpi.source_metric));
    kpiContainer.append(card);
  });
  if (!kpiContainer.childElementCount) kpiContainer.append(element("p", "panel-empty", "No executive KPIs were produced."));

  const zones = asArray(platform.zone_360);
  const zoneSelect = byId("zone-select");
  clear(zoneSelect);
  zones.forEach((zone) => {
    const option = element("option", "", zone.zone_id + (zone.city ? " · " + zone.city : ""));
    option.value = zone.zone_id;
    zoneSelect.append(option);
  });
  const requestedZone = zones[0]?.zone_id;
  const renderZone = (zoneId) => {
    const zone = zones.find((item) => item.zone_id === zoneId) || zones[0];
    if (!zone) {
      byId("zone-detail").textContent = "No zone rollup is available.";
      return;
    }
    zoneSelect.value = zone.zone_id;
    const detail = byId("zone-detail");
    clear(detail);
    const heading = element("div", "zone-detail-heading");
    heading.append(element("strong", "", zone.zone_id + (zone.zone_name ? " · " + zone.zone_name : "")));
    heading.append(element("span", "status-pill " + (zone.recommendation === "recommended" ? "passed" : zone.recommendation === "avoid" ? "failed" : "warning"), titleCase(zone.recommendation || "not evaluated")));
    detail.append(heading);
    const cells = [
      ["Suitability", zone.scores?.suitability, "%"], ["Data quality", zone.scores?.data_quality, "%"],
      ["Environmental risk", zone.environment?.environmental_risk_score, "%"], ["Shipments", zone.logistics?.shipment_count, ""],
      ["Mobility events", zone.mobility?.event_count, ""], ["Sensor anomalies", zone.sensors?.anomaly_pct, "%"],
      ["PM2.5", zone.environment?.average_pm25_ugm3, " µg/m³"], ["GIS features", zone.gis?.asset_count, ""],
    ];
    const grid = element("div", "zone-detail-grid");
    cells.forEach(([label, value, unit]) => {
      const cell = element("div", "zone-detail-cell");
      cell.append(element("span", "", label));
      cell.append(element("strong", "", isFiniteValue(value) ? formatNumber(value, 2) + unit : "—"));
      grid.append(cell);
    });
    detail.append(grid);
    const explanation = zone.explanation || {};
    if (asArray(explanation.positive_drivers).length || asArray(explanation.negative_drivers).length) {
      detail.append(element("p", "zone-explanation", "Positive: " + (asArray(explanation.positive_drivers).join(", ") || "none") + " · Watch: " + (asArray(explanation.negative_drivers).join(", ") || "none")));
    }
  };
  zoneSelect.addEventListener("change", () => renderZone(zoneSelect.value));
  renderZone(requestedZone);

  const recommendations = byId("zone-recommendations");
  clear(recommendations);
  asArray(platform.recommendations).forEach((zone) => {
    const row = document.createElement("tr");
    row.append(element("td", "", zone.zone_id));
    row.append(element("td", "", isFiniteValue(zone.scores?.suitability) ? formatNumber(zone.scores.suitability, 1) + "%" : "—"));
    row.append(element("td", "", isFiniteValue(zone.environment?.environmental_risk_score) ? formatNumber(zone.environment.environmental_risk_score, 1) + "%" : "—"));
    row.append(element("td", "", titleCase(zone.recommendation || "not evaluated")));
    const evidence = zone.explanation?.evidence || {};
    row.append(element("td", "", [evidence.shipments ? formatNumber(evidence.shipments) + " shipments" : null, evidence.mobility_events ? formatNumber(evidence.mobility_events) + " GPS" : null].filter(Boolean).join(" · ") || "—"));
    row.addEventListener("click", () => { zoneSelect.value = zone.zone_id; renderZone(zone.zone_id); });
    recommendations.append(row);
  });

  const quality = platform.quality_summary || {};
  const qualityPill = byId("pack-quality-pill");
  qualityPill.textContent = isFiniteValue(quality.overall_score) ? formatNumber(quality.overall_score, 1) + "%" : "—";
  qualityPill.className = "status-pill " + (quality.overall_score >= 80 ? "passed" : quality.overall_score >= 60 ? "warning" : "failed");
  const qualityContainer = byId("pack-quality-summary");
  clear(qualityContainer);
  const qualityRows = Object.entries(quality.datasets || {});
  qualityRows.forEach(([id, result]) => {
    const row = element("div", "pack-quality-row");
    row.append(element("strong", "", titleCase(id)));
    row.append(element("span", "", (isFiniteValue(result.score) ? formatNumber(result.score, 1) + "%" : "—") + " · " + titleCase(result.status || "not evaluated")));
    qualityContainer.append(row);
  });
  const comparisons = asArray(quality.expected_findings_validation);
  const reviewCount = comparisons.filter((item) => item.validation_status !== "passed").length;
  qualityContainer.append(element("p", "chart-summary", comparisons.length + " golden quality targets checked · " + reviewCount + " require review"));

  const lineage = byId("platform-lineage");
  clear(lineage);
  asArray(platform.lineage?.edges).forEach((edge) => {
    const item = element("div", "lineage-edge");
    item.append(element("strong", "", (edge.source_dataset || "source") + " → " + (edge.target_dataset || "target")));
    item.append(element("small", "", edge.relationship || "derived relationship"));
    lineage.append(item);
  });
  if (!lineage.childElementCount) lineage.append(element("p", "panel-empty", "No cross-domain lineage edges are available."));

  const audit = platform.governance?.audit_summary || {};
  const auditContainer = byId("platform-audit");
  clear(auditContainer);
  [["Audit records", audit.records], ["Allowed", audit.allowed], ["Denied", audit.denied], ["Roles observed", Object.keys(audit.by_role || {}).length]].forEach(([label, value]) => {
    const row = element("div", "audit-metric");
    row.append(element("span", "", label));
    row.append(element("strong", "", formatNumber(value)));
    auditContainer.append(row);
  });
  asArray(audit.sample).slice(0, 5).forEach((event) => {
    const row = element("div", "audit-event");
    row.append(element("strong", "", (event.principal_id || "principal") + " · " + (event.action || "action")));
    row.append(element("small", "", [event.role, event.dataset, event.decision, event.reason].filter(Boolean).join(" · ") || "audit detail unavailable"));
    auditContainer.append(row);
  });
  auditContainer.append(element("p", "chart-summary", platform.governance?.least_privilege || "Least-privilege policy metadata was not provided."));
}

function renderEmptyWorkspace(title, detail) {
  state.dataset = null;
  state.currentRecords = [];
  byId("dataset-title").textContent = title;
  byId("dataset-subtitle").textContent = detail;
  byId("source-tag").textContent = "Catalog";
  byId("fixture-tag").classList.add("hidden");
  byId("attribution").classList.add("hidden");
  ["metric-rows", "metric-quality", "metric-suitability", "metric-visuals"].forEach((id) => {
    byId(id).textContent = "—";
  });
  byId("metric-fields").textContent = "Field profile unavailable";
  byId("metric-quality-status").textContent = "Quality not evaluated";
  byId("metric-eligible").textContent = "Suitability not evaluated";
  byId("preview-note").textContent = "Select an available dataset to compare portal records with full-dataset pipeline analytics.";
  byId("crs-badge").textContent = "No spatial CRS";
  renderMapRecords([]);
  configureTemporalFilter([]);
  renderMetricOptions();
  renderRecommendations();
  renderQuality();
  renderFieldTable();
  renderLineage();
  clear(byId("governance-list"));
  byId("audit-summary").textContent = "No governance or audit records are available.";
  renderManifest();
  renderAnalysisSummary();
  renderProcessing();
  renderExecutiveKpis();
}

function updateDatasetUrl(datasetId) {
  if (!window.history?.replaceState) return;
  try {
    window.history.replaceState({}, "", DatasetUtils.urlWithDataset(window.location.href, datasetId));
  } catch (error) {
    console.warn("Dataset URL could not be updated", error);
  }
}

function selectDataset(datasetId, options = {}) {
  const datasets = DatasetUtils.datasetsFromPayload(state.payload);
  const selected = DatasetUtils.resolveDataset(datasets, datasetId);
  if (!selected) {
    renderEmptyWorkspace("No datasets available", "Add a valid registered dataset and rebuild the normalized payload.");
    return null;
  }
  state.dataset = selected;
  state.currentRecords = recordsForDataset(selected).slice();
  renderHeader(state.dataset);
  renderProcessing();
  configureTemporalFilter(state.currentRecords);
  renderMapRecords(state.currentRecords, true);
  renderMetricOptions();
  renderRecommendations();
  renderQuality();
  renderFieldTable();
  renderLineage();
  renderGovernance();
  renderManifest();
  renderAnalysisSummary();
  renderExecutiveKpis();
  if (options.updateUrl) updateDatasetUrl(selected.id);
  return selected;
}

function bindControls() {
  ["toggle-points", "toggle-route", "toggle-bounds"].forEach((id) =>
    byId(id).addEventListener("change", syncLayerVisibility)
  );
  byId("metric-select").addEventListener("change", drawTrend);
  byId("dataset-search").addEventListener("input", (event) => {
    state.filters.query = event.target.value;
    renderDatasetList();
  });
  byId("domain-filter").addEventListener("change", (event) => {
    state.filters.domain = event.target.value;
    renderDatasetList();
  });
  byId("type-filter").addEventListener("change", (event) => {
    state.filters.datasetType = event.target.value;
    renderDatasetList();
  });
  byId("time-filter").addEventListener("input", (event) => {
    if (!state.dataset) return;
    const count = Number(event.target.value);
    const records = recordsForDataset(state.dataset);
    state.currentRecords = records.slice(0, count);
    byId("time-label").textContent =
      count === records.length
        ? "All " + count + " observations"
        : "First " + count + " observations";
    renderMapRecords(state.currentRecords);
    drawTrend();
  });
  byId("filter-bounds").addEventListener("click", () => {
    if (!state.map || !state.dataset) return;
    const bounds = state.map.getBounds();
    state.currentRecords = recordsForDataset(state.dataset).filter((record) => {
      const point = coordinate(record);
      return point && bounds.contains(point);
    });
    renderMapRecords(state.currentRecords);
    drawTrend();
  });
  byId("reset-map").addEventListener("click", () => {
    if (!state.dataset) return;
    state.currentRecords = recordsForDataset(state.dataset).slice();
    configureTemporalFilter(state.currentRecords);
    renderMapRecords(state.currentRecords, true);
    drawTrend();
  });
  window.addEventListener("popstate", () => {
    const requestedId = DatasetUtils.datasetIdFromSearch(window.location.search);
    selectDataset(requestedId, { updateUrl: false });
  });
}

async function start() {
  if (!DatasetUtils) {
    byId("dataset-title").textContent = "Dataset utilities could not be loaded";
    byId("dataset-subtitle").textContent = "Reload the page or verify that dataset-utils.js is deployed with the portal.";
    return;
  }
  try {
    const response = await fetch("./data/platform_demo.json", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.datasets)) throw new Error("Payload must contain a datasets array");
    state.payload = { ...payload, datasets: DatasetUtils.datasetsFromPayload(payload) };
    renderPlatformOverview(payload.platform);
    initMap();
    bindControls();
    renderCatalogFilters();
    renderDatasetList();
    const requestedId = DatasetUtils.datasetIdFromSearch(window.location.search);
    const selected = selectDataset(requestedId, { updateUrl: false });
    if (requestedId && selected && selected.id !== requestedId) updateDatasetUrl(selected.id);
  } catch (error) {
    renderEmptyWorkspace(
      "Demo data could not be loaded",
      "Serve the frontend directory over HTTP and rebuild a valid normalized payload."
    );
    console.error("VerdaTrace startup failed", error);
  }
}

document.addEventListener("DOMContentLoaded", start);
