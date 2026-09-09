"""Format-neutral raster contracts and bounded, chunked raster operations.

The repository intentionally has no heavyweight raster dependency.  The built-in
GeoTIFF adapter validates the file signature and reports an explicit metadata
boundary; a worker can register a richer adapter without changing the contracts.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .errors import InvalidSchemaError, UnsupportedFormatError
from .ingestion import probe_geotiff
from .models import (
    RasterAnalysisResult,
    RasterBandStatistics,
    RasterProfile,
    RasterQualityIssue,
    RasterQualityReport,
    VisualizationSpec,
)

SUPPORTED_RASTER_FORMATS = {"geotiff", "cog", "netcdf", "zarr"}


class RasterAdapter(Protocol):
    """Common adapter boundary for a decoded or metadata-only raster source."""

    format: str

    def profile(self, path: str | Path, *, allowed_roots: Sequence[str | Path]) -> RasterProfile:
        ...


def profile_stac_item(item: Mapping[str, Any], *, raster_format: str = "cog") -> RasterProfile:
    """Extract verified scene metadata from a STAC Item without downloading pixels.

    This is deliberately metadata-only: values come from the supplied STAC item and
    are never inferred from a filename or fabricated when absent.
    """

    if not isinstance(item, Mapping) or item.get("type") not in {"Feature", "Item", None}:
        raise InvalidSchemaError(
            "STAC item must be an object with type Feature or Item",
            corrective_action="Pass a validated STAC Item response.",
        )
    assets = item.get("assets", {})
    if not isinstance(assets, Mapping):
        raise InvalidSchemaError(
            "STAC item assets must be an object",
            corrective_action="Validate the STAC response before profiling.",
        )
    bands: List[str] = []
    for key, asset in assets.items():
        if not isinstance(key, str) or not isinstance(asset, Mapping):
            continue
        roles = asset.get("roles", [])
        if isinstance(roles, list) and any(role in {"thumbnail", "overview", "metadata"} for role in roles):
            continue
        if asset.get("eo:bands") or (isinstance(roles, list) and "data" in roles) or key.upper().startswith("B"):
            bands.append(key)
    properties = item.get("properties", {})
    if not isinstance(properties, Mapping):
        properties = {}
    bounds = item.get("bbox")
    bounds_mapping = None
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
        try:
            bounds_mapping = {
                "west": float(bounds[0]),
                "south": float(bounds[1]),
                "east": float(bounds[2]),
                "north": float(bounds[3]),
            }
        except (TypeError, ValueError):
            bounds_mapping = None
    shape = properties.get("proj:shape")
    width = height = None
    if isinstance(shape, (list, tuple)) and len(shape) >= 2:
        try:
            height, width = int(shape[0]), int(shape[1])
        except (TypeError, ValueError):
            width = height = None
    raw_resolution = properties.get("proj:resolution")
    resolution = None
    if isinstance(raw_resolution, (int, float)):
        resolution = {"x": float(raw_resolution), "y": float(raw_resolution)}
    elif isinstance(raw_resolution, (list, tuple)) and len(raw_resolution) >= 2:
        try:
            resolution = {"x": float(raw_resolution[0]), "y": float(raw_resolution[1])}
        except (TypeError, ValueError):
            resolution = None
    crs = properties.get("proj:epsg")
    crs_value = f"EPSG:{crs}" if crs not in (None, "") and str(crs).isdigit() else properties.get("proj:wkt2")
    temporal = {
        key: properties[key]
        for key in ("datetime", "start_datetime", "end_datetime")
        if properties.get(key) not in (None, "")
    }
    cloud = properties.get("eo:cloud_cover")
    try:
        cloud_value = float(cloud) if cloud is not None else None
    except (TypeError, ValueError):
        cloud_value = None
    return RasterProfile(
        format=raster_format,
        width=width,
        height=height,
        bands=sorted(bands),
        pixel_count=width * height if width is not None and height is not None else None,
        crs=str(crs_value) if crs_value not in (None, "") else None,
        bounds=bounds_mapping,
        resolution=resolution,
        cloud_percentage=cloud_value,
        temporal_metadata=temporal,
        scene_id=str(item["id"]) if item.get("id") not in (None, "") else None,
        scene_metadata={"cloud_cover": cloud_value} if cloud_value is not None else {},
        readable=None,
    )


def _issue(issues: List[RasterQualityIssue], code: str, severity: str, message: str, observed: Any = None) -> None:
    issues.append(RasterQualityIssue(code=code, severity=severity, message=message, observed=observed))


def evaluate_raster_quality(
    profile: RasterProfile,
    *,
    expected_bands: Optional[Sequence[str]] = None,
    nodata_warning_percentage: Optional[float] = None,
    duplicate_scenes: Optional[Sequence[str]] = None,
    cloud_warning_percentage: Optional[float] = None,
) -> RasterQualityReport:
    """Evaluate metadata and decoded quality facts without reading raster pixels."""

    issues: List[RasterQualityIssue] = []
    bounds = profile.bounds
    required_bounds = {"west", "south", "east", "north"}
    if not profile.crs:
        _issue(issues, "missing_crs", "error", "raster CRS is missing")
    if bounds is None:
        _issue(issues, "missing_bounds", "warning", "raster bounds are unavailable")
    elif not required_bounds <= set(bounds):
        _issue(issues, "invalid_bounds", "error", "raster bounds must include west, south, east, and north")
    else:
        try:
            bound_values = {key: float(bounds[key]) for key in required_bounds}
        except (TypeError, ValueError):
            bound_values = {}
        if not (
            len(bound_values) == len(required_bounds)
            and all(math.isfinite(value) for value in bound_values.values())
            and bound_values["west"] < bound_values["east"]
            and bound_values["south"] < bound_values["north"]
        ):
            _issue(issues, "invalid_bounds", "error", "raster bounds are not finite and strictly ordered", bounds)

    missing_bands: List[str] = []
    if expected_bands is not None:
        missing_bands = [band for band in expected_bands if band not in profile.bands]
        if missing_bands:
            _issue(issues, "missing_bands", "error", "expected raster bands are unavailable", missing_bands)

    if profile.resolution is None:
        _issue(issues, "missing_resolution", "warning", "raster resolution is unavailable")
    else:
        resolution_values = [profile.resolution.get(axis) for axis in ("x", "y")]
        if any(value is None or not math.isfinite(float(value)) or float(value) <= 0 for value in resolution_values):
            _issue(issues, "resolution_inconsistent", "error", "raster resolution must have positive finite x/y values")
        elif profile.width is not None and profile.height is not None and (profile.width <= 0 or profile.height <= 0):
            _issue(issues, "resolution_inconsistent", "error", "raster dimensions must be positive")
    if profile.band_resolutions:
        normalized = set()
        for value in profile.band_resolutions.values():
            try:
                normalized.add((float(value.get("x")), float(value.get("y"))))
            except (AttributeError, TypeError, ValueError):
                normalized.add((math.nan, math.nan))
        if len(normalized) > 1 or any(not math.isfinite(axis) or axis <= 0 for pair in normalized for axis in pair):
            _issue(issues, "resolution_inconsistent", "error", "raster bands do not share a positive, consistent resolution")

    if profile.readable is False:
        _issue(issues, "unreadable_tile", "error", "raster source or tile could not be decoded")
    if duplicate_scenes:
        _issue(
            issues,
            "duplicate_scene_metadata",
            "error",
            "duplicate scene identifiers were detected",
            list(duplicate_scenes),
        )
    if profile.nodata_percentage is not None:
        if not 0 <= profile.nodata_percentage <= 100:
            _issue(issues, "invalid_nodata_percentage", "error", "NoData percentage must be between 0 and 100")
        elif (
            nodata_warning_percentage is not None
            and profile.nodata_percentage > nodata_warning_percentage
        ):
            _issue(
                issues,
                "high_nodata_percentage",
                "warning",
                "NoData percentage exceeds the configured quality objective",
                profile.nodata_percentage,
            )
    if profile.cloud_percentage is not None:
        if not 0 <= profile.cloud_percentage <= 100:
            _issue(issues, "invalid_cloud_percentage", "error", "cloud coverage must be between 0 and 100")
        elif cloud_warning_percentage is not None and profile.cloud_percentage > cloud_warning_percentage:
            _issue(
                issues,
                "high_cloud_coverage",
                "warning",
                "cloud coverage exceeds the configured quality objective",
                profile.cloud_percentage,
            )

    metrics = {
        "width": profile.width,
        "height": profile.height,
        "band_count": len(profile.bands),
        "pixel_count": profile.pixel_count,
        "nodata_percentage": profile.nodata_percentage,
        "missing_bands": missing_bands,
        "scene_id": profile.scene_id,
        "readable": profile.readable,
        "cloud_percentage": profile.cloud_percentage,
    }
    error_count = sum(issue.severity == "error" for issue in issues)
    warning_count = sum(issue.severity == "warning" for issue in issues)
    score = round(max(0.0, 100.0 - error_count * 20.0 - warning_count * 5.0), 2)
    status = "failed" if error_count else "warning" if warning_count else "passed"
    return RasterQualityReport(status=status, score=score, issues=issues, metrics=metrics)


class GeoTiffHeaderAdapter:
    """Safe built-in adapter that intentionally stops before pixel decoding."""

    format = "geotiff"

    def profile(self, path: str | Path, *, allowed_roots: Sequence[str | Path]) -> RasterProfile:
        metadata = probe_geotiff(path, allowed_roots=allowed_roots)
        return RasterProfile(
            format="geotiff",
            pixel_count=None,
            crs=None,
            dtype=None,
            readable=True,
            scene_metadata={"size_bytes": metadata["size_bytes"], "byte_order": metadata["byte_order"]},
        )


class UnsupportedRasterAdapter:
    def __init__(self, raster_format: str) -> None:
        self.format = raster_format

    def profile(self, path: str | Path, *, allowed_roots: Sequence[str | Path]) -> RasterProfile:
        display_format = {"cog": "COG", "netcdf": "NetCDF", "zarr": "Zarr"}.get(self.format, self.format)
        raise UnsupportedFormatError(
            f"{display_format} raster decoding is not configured",
            corrective_action="Register a vetted raster worker adapter for this format before execution.",
            details={"format": self.format, "path": str(path)},
        )


class RasterAdapterRegistry:
    def __init__(self, adapters: Optional[Iterable[RasterAdapter]] = None) -> None:
        self._adapters: Dict[str, RasterAdapter] = {}
        for adapter in adapters or [GeoTiffHeaderAdapter()]:
            self.register(adapter)

    def register(self, adapter: RasterAdapter) -> None:
        format_name = str(adapter.format).lower()
        if format_name not in SUPPORTED_RASTER_FORMATS:
            raise InvalidSchemaError(
                f"unsupported raster adapter format: {format_name}",
                corrective_action=f"Use one of: {', '.join(sorted(SUPPORTED_RASTER_FORMATS))}.",
            )
        self._adapters[format_name] = adapter

    def get(self, raster_format: str) -> RasterAdapter:
        format_name = raster_format.lower()
        if format_name not in SUPPORTED_RASTER_FORMATS:
            raise UnsupportedFormatError(
                f"unsupported raster format: {raster_format}",
                corrective_action=f"Use one of: {', '.join(sorted(SUPPORTED_RASTER_FORMATS))}.",
            )
        return self._adapters.get(format_name, UnsupportedRasterAdapter(format_name))


class _Accumulator:
    def __init__(self, nodata: Any) -> None:
        self.nodata = nodata
        self.count = 0
        self.nodata_count = 0
        self._sum = 0.0
        self._sum_squares = 0.0
        self.minimum: Optional[float] = None
        self.maximum: Optional[float] = None

    def update(self, value: Any) -> None:
        if value is None or value == self.nodata:
            self.nodata_count += 1
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            self.nodata_count += 1
            return
        if not math.isfinite(number):
            self.nodata_count += 1
            return
        self.count += 1
        self._sum += number
        self._sum_squares += number * number
        self.minimum = number if self.minimum is None else min(self.minimum, number)
        self.maximum = number if self.maximum is None else max(self.maximum, number)

    def result(self, band: str) -> RasterBandStatistics:
        mean = self._sum / self.count if self.count else None
        variance = (
            max(0.0, self._sum_squares / self.count - (mean * mean))
            if mean is not None
            else None
        )
        return RasterBandStatistics(
            band=band,
            count=self.count,
            nodata_count=self.nodata_count,
            minimum=self.minimum,
            maximum=self.maximum,
            mean=round(mean, 6) if mean is not None else None,
            stddev=round(math.sqrt(variance), 6) if variance is not None else None,
        )


def analyze_raster_bands(
    bands: Mapping[str, Iterable[Iterable[Any]]],
    *,
    nodata: Any = None,
) -> RasterAnalysisResult:
    """Compute per-band statistics from chunk iterables without materializing pixels."""

    statistics: List[RasterBandStatistics] = []
    for band, chunks in bands.items():
        accumulator = _Accumulator(nodata)
        for chunk in chunks:
            for value in chunk:
                accumulator.update(value)
        statistics.append(accumulator.result(str(band)))

    valid = sum(item.count for item in statistics)
    nodata_count = sum(item.nodata_count for item in statistics)
    total = valid + nodata_count
    return RasterAnalysisResult(
        result_type="raster_band_statistics",
        band_statistics=statistics,
        computed_values={
            "band_count": len(statistics),
            "valid_pixel_count": valid,
            "nodata_pixel_count": nodata_count,
            "nodata_percentage": round(100 * nodata_count / total, 6) if total else None,
            "coverage": round(valid / total, 6) if total else None,
        },
        warnings=["No valid pixel values were available for analysis."] if valid == 0 else [],
    )


def duplicate_scene_ids(profiles: Iterable[RasterProfile]) -> List[str]:
    """Return duplicate scene IDs while preserving first-seen order."""

    seen: set[str] = set()
    duplicates: List[str] = []
    for profile in profiles:
        scene_id = profile.scene_id
        if scene_id and scene_id in seen and scene_id not in duplicates:
            duplicates.append(scene_id)
        elif scene_id:
            seen.add(scene_id)
    return duplicates


def recommend_raster_visualizations(profile: RasterProfile) -> List[VisualizationSpec]:
    """Recommend only raster views supported by the available metadata."""

    recommendations: List[VisualizationSpec] = []
    spatially_ready = bool(profile.crs and profile.bounds)
    band_names = " ".join(profile.bands).lower()
    classified = any(token in band_names for token in ("class", "landcover", "land_cover", "mask"))
    if spatially_ready:
        if classified:
            recommendations.append(
                VisualizationSpec(
                    type="classified_raster",
                    fields=list(profile.bands),
                    confidence=0.92,
                    reason="Spatial metadata and categorical/classification band semantics were detected.",
                )
            )
        else:
            recommendations.append(
                VisualizationSpec(
                    type="raster_map",
                    fields=list(profile.bands),
                    confidence=0.9,
                    reason="A decoded raster has a declared CRS and spatial bounds.",
                )
            )
    if profile.temporal_metadata and spatially_ready:
        recommendations.append(
            VisualizationSpec(
                type="raster_timeseries",
                fields=list(profile.bands),
                confidence=0.84,
                reason="Spatially ready raster metadata includes a temporal dimension.",
            )
        )
    return recommendations
