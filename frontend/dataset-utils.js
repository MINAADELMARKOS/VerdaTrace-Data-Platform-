(function attachDatasetUtils(root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.VerdaTraceDatasetUtils = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createDatasetUtils() {
  "use strict";

  const DOMAIN_GROUPS = [
    ["Climate", ["climate", "environment", "weather"]],
    ["Mobility", ["mobility", "logistics", "transport", "route", "trip"]],
    ["Geoinformatics", ["geospatial", "spatial", "gis", "vector", "geometry"]],
    ["Remote Sensing", ["remote_sensing", "remote sensing", "raster", "satellite", "earth_observation", "land_cover"]],
    ["Population", ["population", "demograph", "census"]],
    ["Infrastructure", ["infrastructure", "road", "port", "warehouse", "hub"]],
    ["Sensor / IoT", ["sensor", "iot", "telemetry"]],
  ];
  const DATASET_TYPES = ["tabular", "vector", "raster", "streaming"];
  const MISSING_MARKERS = new Set(["unknown", "not_provided"]);

  function array(value) {
    return Array.isArray(value) ? value : [];
  }

  function hasValue(value) {
    if (value === null || value === undefined || value === "") return false;
    if (typeof value === "string" && MISSING_MARKERS.has(value.trim().toLowerCase())) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value).length > 0;
    return true;
  }

  function datasetsFromPayload(payload) {
    if (!payload || !Array.isArray(payload.datasets)) return [];
    return payload.datasets.filter(
      (dataset) => dataset && typeof dataset === "object" && hasValue(dataset.id)
    );
  }

  function numericValue(value) {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function datasetName(dataset) {
    return dataset?.title || dataset?.name || dataset?.id || "Unnamed dataset";
  }

  function metadataText(dataset) {
    const categories = array(dataset?.outcome?.profile?.categories);
    return [dataset?.domain, dataset?.dataset_type, ...categories]
      .filter(hasValue)
      .join(" ")
      .toLowerCase();
  }

  function domainGroupsFor(dataset) {
    const text = metadataText(dataset);
    return DOMAIN_GROUPS.filter(([, terms]) => terms.some((term) => text.includes(term)))
      .map(([label]) => label);
  }

  function availableDomainGroups(datasets) {
    const present = new Set(array(datasets).flatMap(domainGroupsFor));
    return DOMAIN_GROUPS.map(([label]) => label).filter((label) => present.has(label));
  }

  function datasetType(dataset) {
    const explicit = dataset?.dataset_type || dataset?.outcome?.manifest?.dataset_type;
    if (hasValue(explicit)) {
      const normalized = String(explicit).trim().toLowerCase();
      if (DATASET_TYPES.includes(normalized)) return normalized;
    }
    const format = String(
      dataset?.outcome?.manifest?.source_format || dataset?.outcome?.profile?.source_format || ""
    ).toLowerCase();
    if (["tif", "tiff", "geotiff"].includes(format)) return "raster";
    if (["geojson", "shp", "shapefile", "gpkg", "geopackage"].includes(format)) return "vector";
    if (["csv", "json", "ndjson", "parquet"].includes(format)) return "tabular";
    const categories = array(dataset?.outcome?.profile?.categories);
    if (categories.includes("geospatial_raster")) return "raster";
    if (categories.includes("geospatial_vector")) return "vector";
    if (categories.includes("tabular")) return "tabular";
    return null;
  }

  function availableDatasetTypes(datasets) {
    const present = new Set(array(datasets).map(datasetType).filter(Boolean));
    return DATASET_TYPES.filter((type) => present.has(type));
  }

  function filterDatasets(datasets, filters) {
    const query = String(filters?.query || "").trim().toLowerCase();
    const domain = String(filters?.domain || "all");
    const type = String(filters?.datasetType || "all").toLowerCase();
    return array(datasets).filter((dataset) => {
      const searchable = [dataset?.title, dataset?.name, dataset?.id, dataset?.domain]
        .filter(hasValue)
        .join(" ")
        .toLowerCase();
      const matchesQuery = !query || searchable.includes(query);
      const matchesDomain = domain === "all" || domainGroupsFor(dataset).includes(domain);
      const matchesType = type === "all" || datasetType(dataset) === type;
      return matchesQuery && matchesDomain && matchesType;
    });
  }

  function resolveDataset(datasets, requestedId) {
    const available = array(datasets);
    if (!available.length) return null;
    if (hasValue(requestedId)) {
      const match = available.find((dataset) => dataset.id === requestedId);
      if (match) return match;
    }
    return available[0];
  }

  function datasetIdFromSearch(search) {
    return new URLSearchParams(search || "").get("dataset");
  }

  function urlWithDataset(currentUrl, datasetId) {
    const url = new URL(currentUrl);
    if (hasValue(datasetId)) url.searchParams.set("dataset", datasetId);
    else url.searchParams.delete("dataset");
    return url.toString();
  }

  function profileCapabilities(dataset) {
    const profile = dataset?.outcome?.profile || {};
    const fields = array(profile.fields);
    const records = array(dataset?.records);
    const manifest = dataset?.outcome?.manifest || {};
    const spatial = Boolean(
      hasValue(profile.geographic_bounds) ||
        hasValue(manifest.bounding_box) ||
        hasValue(manifest.geometry_types) ||
        fields.some((field) => ["latitude", "longitude", "geometry"].includes(field?.semantic_type))
    );
    const temporal = Boolean(
      fields.some((field) => ["timestamp", "date"].includes(field?.semantic_type)) ||
        records.some((record) => hasValue(record?.event_timestamp))
    );
    const numeric = fields.some(
      (field) =>
        field?.data_type === "number" &&
        !["latitude", "longitude"].includes(field?.semantic_type)
    );
    const pointRecords = records.some((record) => {
      const lat = record?.latitude;
      const lon = record?.longitude;
      const topLevelPoint =
        lat !== null && lat !== undefined && lat !== "" &&
        lon !== null && lon !== undefined && lon !== "" &&
        Number.isFinite(Number(lat)) && Number.isFinite(Number(lon));
      const pointGeometry =
        record?.geometry?.type === "Point" && Array.isArray(record.geometry.coordinates);
      return topLevelPoint || pointGeometry;
    });
    return { spatial, temporal, numeric, pointRecords };
  }

  function manifestRows(dataset) {
    const outcome = dataset?.outcome || {};
    const manifest = outcome.manifest || {};
    const profile = outcome.profile || {};
    const governance = outcome.governance || {};
    const attribution = dataset?.attribution || {};
    const values = [
      ["Provider", manifest.provider ?? governance.source ?? attribution.label],
      ["Format", manifest.source_format ?? profile.source_format],
      ["Dataset type", manifest.dataset_type ?? dataset?.dataset_type ?? datasetType(dataset)],
      ["Input size", manifest.input_size, "bytes"],
      ["Records / features", manifest.record_count ?? profile.row_count],
      ["Geometry types", manifest.geometry_types],
      ["CRS", manifest.crs],
      ["Spatial extent", manifest.bounding_box ?? profile.geographic_bounds],
      ["Geographic coverage", manifest.geographic_coverage ?? governance.geographic_coverage],
      ["Temporal coverage", manifest.temporal_coverage ?? profile.temporal_coverage ?? governance.temporal_coverage],
      ["License", manifest.license ?? governance.license ?? attribution.license],
      ["Ingested", manifest.ingestion_timestamp ?? governance.ingestion_timestamp],
      ["Processed", manifest.processing_timestamp],
      ["Checksum", manifest.checksum_sha256],
      ["Source system", manifest.source_system],
      ["Schema version", manifest.schema_version],
      ["Ingestion status", manifest.ingestion_status],
      ["Fixture", manifest.fixture ?? dataset?.fixture, "boolean"],
    ];
    return values
      .filter(([, value]) => hasValue(value))
      .map(([label, value, kind]) => ({ label, value, kind: kind || null }));
  }

  function executiveKpis(dataset) {
    return array(dataset?.outcome?.executive_kpis).filter(
      (kpi) => kpi && typeof kpi === "object" && hasValue(kpi.id) && hasValue(kpi.label)
    );
  }

  return {
    DATASET_TYPES,
    array,
    availableDatasetTypes,
    availableDomainGroups,
    datasetIdFromSearch,
    datasetName,
    datasetType,
    datasetsFromPayload,
    domainGroupsFor,
    filterDatasets,
    hasValue,
    executiveKpis,
    manifestRows,
    numericValue,
    profileCapabilities,
    resolveDataset,
    urlWithDataset,
  };
});
