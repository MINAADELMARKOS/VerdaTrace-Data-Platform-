# Raster and remote-sensing foundation

## Common contract

`verdatrace.raster` provides a format-neutral boundary for GeoTIFF, Cloud-Optimized GeoTIFF (COG), NetCDF, and Zarr. A `RasterAdapter` returns a `RasterProfile` with nullable width, height, bands, pixel count, CRS, bounds, resolution, NoData, dtype, temporal metadata, scene metadata, and readability. Adapters must fail explicitly when a decoder is unavailable.

The built-in `GeoTiffHeaderAdapter` validates the TIFF byte-order/magic header and reports file size only. It intentionally does not claim dimensions, bands, CRS, bounds, or pixel statistics. COG, NetCDF, and Zarr currently return an explicit unsupported-adapter error until a vetted rasterio/GDAL/xarray worker is installed.

## Quality and analytics

`evaluate_raster_quality` checks missing CRS, missing/invalid bounds, expected bands, positive finite and cross-band-consistent resolution, readability, NoData percentage, cloud-coverage objectives, and optional duplicate scene IDs. `analyze_raster_bands` consumes iterables of chunks and computes per-band count, NoData count, minimum, maximum, mean, standard deviation, overall coverage, and NoData percentage without materializing all pixels. Empty/all-NoData inputs return nullable statistics and a warning. `profile_stac_item` extracts only declared scene metadata (ID, datetime, assets/bands, cloud cover, CRS, bounds, shape, and resolution) and never downloads or invents pixels.

`recommend_raster_visualizations` emits `raster_map` only when CRS and bounds are present, `classified_raster` when band names provide classification evidence, and `raster_timeseries` when temporal metadata is present. No browser raster layer is implied by a recommendation alone.

## Deferred source plans

The following YAML definitions are deliberately `enabled: false` because the source files or credentials are not available in this repository. They contain retrieval metadata and no fabricated measurements:

- `sentinel2_greater_cairo_sample.yaml` — use the Copernicus Data Space STAC catalog (`https://stac.dataspace.copernicus.eu/v1/search`) for a bounded Greater Cairo scene, then supply a verified COG/GeoTIFF and scene metadata.
- `era5_land_cairo_retrieval.yaml` — use the Copernicus Climate Data Store ERA5-Land dataset (`https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land`) with operator credentials and a bounded request. Analysis-ready Zarr access is a provider service, not a committed file.
- `ghsl_population_2015_retrieval.yaml` — use the European Commission JRC GHSL distribution (`https://ghsl.jrc.ec.europa.eu/documents/GHSL_data_access.pdf`) and verify the selected population grid, epoch, resolution, and cell-area semantics before calculating totals or density.

Sentinel metadata extraction should preserve STAC scene ID, datetime, bands/assets, cloud metadata, CRS, bounds, and resolution. ERA5 should preserve variables, grid dimensions, timestamps, extent, resolution, units, and interval completeness. GHSL should preserve product, epoch, CRS, resolution, bounds, NoData, and grid coverage. Metrics such as NDVI, cloud-free coverage, observed area, population total, or built-up area are only valid after the corresponding product bands and semantics have been verified.

## Dependencies and safe rollout

Install a reviewed rasterio/GDAL or xarray stack in a dedicated worker, not in the static portal. Keep source objects in controlled storage, process in chunks, publish bounded statistics/tiles, and retain scene-level lineage. Add adapter, quality, analytics, and failure-path tests before enabling any deferred YAML definition.
