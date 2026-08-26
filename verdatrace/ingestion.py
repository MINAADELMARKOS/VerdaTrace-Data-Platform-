"""Bounded, streaming ingestion for local and allow-listed external sources."""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .errors import ExternalSourceError, InvalidSchemaError, UnsupportedCrsError, UnsupportedFormatError

SUPPORTED_SUFFIXES = {".csv", ".json", ".ndjson", ".geojson", ".tif", ".tiff"}


def validate_local_path(path: str | Path, allowed_roots: Sequence[str | Path]) -> Path:
    candidate = Path(path).expanduser().resolve()
    roots = [Path(root).expanduser().resolve() for root in allowed_roots]
    if not roots or not any(candidate == root or root in candidate.parents for root in roots):
        raise InvalidSchemaError(
            "source path is outside the configured ingestion roots",
            corrective_action="Move the file into an approved landing directory.",
            details={"path": str(candidate)},
        )
    if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(
            f"unsupported file extension: {candidate.suffix or '<none>'}",
            corrective_action=f"Use one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
        )
    if not candidate.is_file():
        raise InvalidSchemaError(
            "source path does not reference a readable file",
            corrective_action="Provide an existing regular file.",
            details={"path": str(candidate)},
        )
    return candidate


def _flatten_feature(feature: Dict[str, Any], index: int, crs: str) -> Dict[str, Any]:
    if feature.get("type") != "Feature":
        raise InvalidSchemaError(
            "GeoJSON collection contains a non-Feature entry",
            corrective_action="Provide a valid GeoJSON FeatureCollection.",
            details={"feature_index": index},
        )
    properties = feature.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise InvalidSchemaError("GeoJSON feature properties must be an object")
    geometry = feature.get("geometry")
    coordinate_fields: Dict[str, Any] = {}
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            coordinate_fields = {"longitude": coordinates[0], "latitude": coordinates[1]}
    return {
        **properties,
        "feature_id": feature.get("id", index),
        "geometry": geometry,
        "crs": crs,
        **coordinate_fields,
    }


def _geojson_crs(value: Dict[str, Any]) -> str:
    declared = value.get("crs")
    if declared is None:
        return "EPSG:4326"
    name = ""
    if isinstance(declared, dict):
        properties = declared.get("properties")
        if isinstance(properties, dict):
            name = str(properties.get("name") or "")
    normalized = name.upper()
    if normalized in {
        "EPSG:4326",
        "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
        "URN:OGC:DEF:CRS:EPSG::4326",
    }:
        return "EPSG:4326"
    raise UnsupportedCrsError(
        f"unsupported GeoJSON CRS: {name or 'unrecognized declaration'}",
        corrective_action="Reproject the source to EPSG:4326 before ingestion.",
    )


def iter_records(
    path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    max_records: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    source = validate_local_path(path, allowed_roots)
    suffix = source.suffix.lower()
    yielded = 0

    if suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield dict(row)
                yielded += 1
                if max_records and yielded >= max_records:
                    return
        return

    if suffix == ".ndjson":
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise InvalidSchemaError(
                        f"invalid NDJSON at line {line_number}",
                        corrective_action="Ensure each populated line contains one JSON object.",
                    ) from exc
                if not isinstance(value, dict):
                    raise InvalidSchemaError(f"NDJSON line {line_number} is not an object")
                yield value
                yielded += 1
                if max_records and yielded >= max_records:
                    return
        return

    if suffix in {".json", ".geojson"}:
        with source.open("r", encoding="utf-8") as handle:
            try:
                value = json.load(handle)
            except json.JSONDecodeError as exc:
                raise InvalidSchemaError(
                    "source contains malformed JSON",
                    corrective_action="Validate the source as JSON before ingestion.",
                ) from exc
        if isinstance(value, dict) and value.get("type") == "FeatureCollection":
            crs = _geojson_crs(value)
            records: Iterable[Dict[str, Any]] = (
                _flatten_feature(feature, index, crs)
                for index, feature in enumerate(value.get("features", []))
            )
        elif isinstance(value, list):
            if not all(isinstance(item, dict) for item in value):
                raise InvalidSchemaError("JSON arrays must contain objects only")
            records = value
        elif (
            isinstance(value, dict)
            and isinstance(value.get("records"), list)
            and all(isinstance(item, dict) for item in value["records"])
        ):
            records = value["records"]
        elif isinstance(value, dict):
            records = [value]
        else:
            raise InvalidSchemaError("JSON source must be an object, array of objects, or FeatureCollection")
        for record in records:
            yield record
            yielded += 1
            if max_records and yielded >= max_records:
                return
        return

    raise UnsupportedFormatError(
        "GeoTIFF is recognized but requires a raster-aware execution path",
        corrective_action="Use probe_geotiff for metadata or configure a rasterio/GDAL processing worker.",
    )


def iter_batches(records: Iterable[Dict[str, Any]], batch_size: int = 1000) -> Iterator[List[Dict[str, Any]]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    batch: List[Dict[str, Any]] = []
    for record in records:
        batch.append(record)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def probe_geotiff(path: str | Path, *, allowed_roots: Sequence[str | Path]) -> Dict[str, Any]:
    source = validate_local_path(path, allowed_roots)
    if source.suffix.lower() not in {".tif", ".tiff"}:
        raise UnsupportedFormatError("raster probe accepts only .tif or .tiff files")
    with source.open("rb") as handle:
        header = handle.read(4)
    if header not in {b"II*\x00", b"MM\x00*"}:
        raise InvalidSchemaError(
            "file does not contain a valid TIFF byte-order and magic-number header",
            corrective_action="Provide a valid, uncorrupted GeoTIFF.",
        )
    return {
        "format": "GeoTIFF",
        "byte_order": "little_endian" if header.startswith(b"II") else "big_endian",
        "size_bytes": source.stat().st_size,
        "crs": "unknown",
        "warning": "CRS, bands, and bounds require the optional rasterio/GDAL worker.",
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def fetch_allowlisted_json(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    max_bytes: int = 5_000_000,
    timeout_seconds: int = 20,
) -> Any:
    parsed = urllib.parse.urlsplit(url)
    allowed = {host.lower() for host in allowed_hosts}
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed:
        raise ExternalSourceError(
            "external source URL is not an allow-listed HTTPS endpoint",
            corrective_action="Add the exact trusted host to the connector configuration.",
            details={"host": parsed.hostname, "scheme": parsed.scheme},
        )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VerdaTrace/1.0", "Accept": "application/json"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise ExternalSourceError("external response exceeds the configured size limit")
            payload = response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        if isinstance(exc, ExternalSourceError):
            raise
        raise ExternalSourceError(
            "external source retrieval failed",
            corrective_action="Confirm source availability, allow-list configuration, and network access.",
        ) from exc
    if len(payload) > max_bytes:
        raise ExternalSourceError("external response exceeds the configured size limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidSchemaError("external response is not valid UTF-8 JSON") from exc
