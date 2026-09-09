"""Streaming OpenStreetMap PBF adapter and bounded OSM summaries.

The optional pyosmium dependency is deliberately kept outside the base
runtime. Tests and downstream workers can inject a parser callback with the
same (path, emit) contract. The adapter never materializes the PBF.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from queue import Full, Queue
from threading import Event, Thread
from typing import Any, Dict, Iterator, List, Optional

from .errors import InvalidSchemaError, UnsupportedFormatError
from .ingestion import validate_local_path
from .models import ExecutiveKPI

OSM_FORMAT = "osm_pbf"
CLASSIFICATION_KEYS = ("highway", "building", "amenity", "landuse")
_DONE = object()


def _default_parser(path: Path, emit: Callable[[Any], None]) -> None:
    try:
        import osmium  # type: ignore
    except ImportError as exc:
        raise UnsupportedFormatError(
            "OSM PBF decoding requires the optional pyosmium dependency",
            corrective_action="Install a vetted pyosmium worker dependency before enabling OSM PBF ingestion.",
            details={"format": OSM_FORMAT},
        ) from exc

    class Handler(osmium.SimpleHandler):
        def node(self, node: Any) -> None:
            emit(node)

        def way(self, way: Any) -> None:
            emit(way)

        def relation(self, relation: Any) -> None:
            emit(relation)

    Handler().apply_file(str(path), locations=True)


def _tags(element: Any) -> Dict[str, str]:
    raw = element.get("tags", {}) if isinstance(element, Mapping) else getattr(element, "tags", {})
    if raw is None:
        return {}
    try:
        return {str(key): str(value) for key, value in dict(raw).items() if value not in (None, "")}
    except (TypeError, ValueError):
        return {}


def _location(value: Any) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        lon, lat = value.get("lon"), value.get("lat")
    else:
        lon, lat = getattr(value, "lon", None), getattr(value, "lat", None)
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [lon, lat]


def _element_type(element: Any) -> str:
    if isinstance(element, Mapping):
        return str(element.get("feature_type") or element.get("kind") or element.get("type") or "unknown").lower()
    name = element.__class__.__name__.lower()
    return name if name in {"node", "way", "relation"} else "unknown"


def _geometry_from_element(element: Any, feature_type: str, tags: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    if isinstance(element, Mapping):
        geometry = element.get("geometry")
        if isinstance(geometry, Mapping):
            return dict(geometry)
        coordinates = element.get("coordinates")
        geometry_type = element.get("geometry_type")
        if geometry_type and isinstance(coordinates, list):
            return {"type": str(geometry_type), "coordinates": coordinates}
        point = _location(element)
        if point is not None:
            return {"type": "Point", "coordinates": point}
        return None
    if feature_type == "node":
        point = _location(getattr(element, "location", None))
        return {"type": "Point", "coordinates": point} if point else None
    if feature_type == "way":
        positions: List[List[float]] = []
        for node in getattr(element, "nodes", []) or []:
            point = _location(getattr(node, "location", None))
            if point is not None:
                positions.append(point)
        if len(positions) < 2:
            return None
        closed = positions[0] == positions[-1] and len(positions) >= 4
        if closed and ("building" in tags or "landuse" in tags):
            return {"type": "Polygon", "coordinates": [positions]}
        return {"type": "LineString", "coordinates": positions}
    return None


def normalize_osm_element(element: Any) -> Dict[str, Any]:
    """Normalize one node/way/relation without flattening arbitrary OSM tags."""

    feature_type = _element_type(element)
    if isinstance(element, Mapping):
        osm_id = element.get("osm_id", element.get("id"))
    else:
        osm_id = getattr(element, "id", None)
    if osm_id in (None, ""):
        raise InvalidSchemaError(
            "OSM element is missing an identifier",
            corrective_action="Ensure the PBF parser exposes node, way, and relation IDs.",
        )
    tags = _tags(element)
    geometry = _geometry_from_element(element, feature_type, tags)
    geometry_type = geometry.get("type") if isinstance(geometry, Mapping) else None
    coordinate_fields: Dict[str, Any] = {}
    if isinstance(element, Mapping) and ("lon" in element or "lat" in element):
        # Preserve raw coordinate values so quality checks can report an
        # explicitly invalid source coordinate instead of silently dropping it.
        coordinate_fields = {"longitude": element.get("lon"), "latitude": element.get("lat")}
    elif feature_type == "node":
        location = getattr(element, "location", None)
        if location is not None:
            coordinate_fields = {
                "longitude": getattr(location, "lon", None),
                "latitude": getattr(location, "lat", None),
            }
    source_metadata = {}
    for key in ("version", "timestamp", "changeset"):
        value = element.get(key) if isinstance(element, Mapping) else getattr(element, key, None)
        if value not in (None, ""):
            source_metadata[key] = str(value)
    return {
        "osm_id": str(osm_id),
        "feature_type": feature_type,
        "geometry": geometry,
        "geometry_type": geometry_type,
        "tags": tags,
        "name": tags.get("name"),
        "highway": tags.get("highway"),
        "building": tags.get("building"),
        "amenity": tags.get("amenity"),
        "landuse": tags.get("landuse"),
        "crs": "EPSG:4326",
        "source_metadata": source_metadata,
        **coordinate_fields,
    }


class OSMAdapter:
    """PBF adapter with bounded queue back-pressure between parser and consumer."""

    format = OSM_FORMAT

    def __init__(self, parser: Optional[Callable[[Path, Callable[[Any], None]], None]] = None) -> None:
        self.parser = parser or _default_parser

    def iter_records(
        self,
        path: str | Path,
        *,
        allowed_roots: Sequence[str | Path],
        max_records: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        source = validate_local_path(path, allowed_roots)
        if not source.name.lower().endswith(".osm.pbf"):
            raise UnsupportedFormatError(
                "OSM adapter accepts only .osm.pbf sources",
                corrective_action="Provide a file named with the .osm.pbf extension.",
            )
        if max_records is not None and max_records <= 0:
            return
        queue: Queue[Any] = Queue(maxsize=256)
        stopped = Event()
        failure: List[BaseException] = []

        def emit(element: Any) -> None:
            while not stopped.is_set():
                try:
                    queue.put(element, timeout=0.1)
                    return
                except Full:
                    continue

        def worker() -> None:
            try:
                self.parser(source, emit)
            except BaseException as exc:  # propagate parser failures to the consumer
                failure.append(exc)
            finally:
                while True:
                    try:
                        queue.put(_DONE, timeout=0.1)
                        break
                    except Full:
                        if stopped.is_set():
                            return

        thread = Thread(target=worker, name="verdatrace-osm-parser", daemon=True)
        thread.start()
        yielded = 0
        try:
            while True:
                element = queue.get()
                if element is _DONE:
                    if failure:
                        raise failure[0]
                    return
                yield normalize_osm_element(element)
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
        finally:
            stopped.set()


def _coordinates(geometry: Any) -> Iterator[List[float]]:
    if not isinstance(geometry, Mapping):
        return
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "GeometryCollection":
        for child in geometry.get("geometries", []) or []:
            yield from _coordinates(child)
        return
    if isinstance(coordinates, list) and len(coordinates) >= 2 and all(isinstance(value, (int, float)) for value in coordinates[:2]):
        yield [float(coordinates[0]), float(coordinates[1])]
        return
    if isinstance(coordinates, list):
        for child in coordinates:
            yield from _coordinates({"coordinates": child})


def profile_osm_records(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    feature_counts: Counter[str] = Counter()
    geometry_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    min_lon = min_lat = math.inf
    max_lon = max_lat = -math.inf
    count = 0
    for record in records:
        count += 1
        feature_type = str(record.get("feature_type") or "unknown")
        feature_counts[feature_type] += 1
        geometry = record.get("geometry")
        geometry_type = str(record.get("geometry_type") or (geometry.get("type") if isinstance(geometry, Mapping) else "none"))
        geometry_counts[geometry_type] += 1
        category = next((key for key in CLASSIFICATION_KEYS if record.get(key) not in (None, "")), "unclassified")
        category_counts[category] += 1
        for lon, lat in _coordinates(geometry):
            min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
    bounds = None
    if min_lon != math.inf:
        bounds = {"min_longitude": min_lon, "max_longitude": max_lon, "min_latitude": min_lat, "max_latitude": max_lat}
    return {
        "feature_count": count,
        "feature_counts": dict(sorted(feature_counts.items())),
        "geometry_counts": dict(sorted(geometry_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "bounds": bounds,
    }


def _haversine_km(left: Sequence[float], right: Sequence[float]) -> float:
    radius = 6371.0088
    lon1, lat1, lon2, lat2 = map(math.radians, (left[0], left[1], right[0], right[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def _line_length_km(geometry: Any) -> float:
    if not isinstance(geometry, Mapping):
        return 0.0
    kind = geometry.get("type")
    if kind == "LineString":
        positions = list(_coordinates(geometry))
        return sum(_haversine_km(left, right) for left, right in zip(positions, positions[1:]))
    if kind == "MultiLineString":
        return sum(_line_length_km({"type": "LineString", "coordinates": line}) for line in geometry.get("coordinates", []))
    return 0.0


def analyze_osm_records(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compute source-backed OSM counts and road lengths."""

    rows = list(records)
    profile = profile_osm_records(rows)
    road_rows = [row for row in rows if row.get("highway") not in (None, "")]
    building_rows = [row for row in rows if row.get("building") not in (None, "")]
    poi_rows = [row for row in rows if row.get("amenity") not in (None, "")]
    infrastructure_rows = [
        row for row in rows
        if any(row.get(key) not in (None, "") for key in CLASSIFICATION_KEYS)
    ]
    classified = sum(1 for row in rows if any(row.get(key) not in (None, "") for key in CLASSIFICATION_KEYS))
    return {
        **profile,
        "road_count": len(road_rows),
        "building_count": len(building_rows),
        "poi_count": len(poi_rows),
        "infrastructure_feature_count": len(infrastructure_rows),
        "road_length_km": round(sum(_line_length_km(row.get("geometry")) for row in road_rows), 6),
        "feature_completeness_percent": round(100 * classified / len(rows), 6) if rows else None,
    }


def osm_executive_kpis(analysis: Any) -> List[ExecutiveKPI]:
    """Return optional KPIs from a completed OSM analysis, never from estimates."""

    summary = getattr(analysis, "computed_values", {}).get("osm_summary", {})
    if not summary:
        return []
    values = [
        ("road_network_length", "Road Network Length", summary.get("road_length_km"), "km", "osm_summary.road_length_km", "Sum of haversine lengths across tagged highway line geometries."),
        ("buildings_mapped", "Buildings Mapped", summary.get("building_count"), "features", "osm_summary.building_count", "Count of features with a building classification tag."),
        ("pois", "POIs", summary.get("poi_count"), "features", "osm_summary.poi_count", "Count of features with an amenity classification tag."),
        ("infrastructure_features", "Infrastructure Features", summary.get("infrastructure_feature_count"), "features", "osm_summary.infrastructure_feature_count", "Count of features with a highway, building, amenity, or landuse tag."),
        ("feature_completeness", "Feature Completeness", summary.get("feature_completeness_percent"), "percent", "osm_summary.feature_completeness_percent", "Share of features with at least one common classification tag."),
    ]
    return [
        ExecutiveKPI(
            id=identifier,
            label=label,
            value=float(value) if isinstance(value, (int, float)) else None,
            unit=unit,
            status="observed",
            description="Derived from the registered OSM extract.",
            source_metric=metric,
            analysis_stage="analysis",
            fields_used=["osm_id", "geometry", *CLASSIFICATION_KEYS],
            calculation_description=calculation,
        )
        for identifier, label, value, unit, metric, calculation in values
    ]
