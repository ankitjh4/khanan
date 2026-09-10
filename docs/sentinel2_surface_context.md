# Sentinel-2 surface-context layer

## Scope and interpretation

KHANAN v1.0-alpha.18 adds a reproducible, nationwide Sentinel-2 Level-2A surface-context table. The layer describes visible, near-infrared and short-wave-infrared surface conditions in two fixed 2025 windows. It is designed to control for vegetation, water, moisture, clouds, seasonal exposure and broad spectral variation before later mineral-model experiments.

The layer does **not** identify a mineral, metal, orebody or subsurface deposit. The published indices and ratios are non-specific and can respond to vegetation, soil moisture, land use, crop cycles, fire, atmosphere, mixed pixels and many rock or soil types. They are excluded from v0.6 training, validation, candidate classes and rankings pending material-wise spatial ablation.

## Source, access and licensing

- Scientific product: [Copernicus Sentinel-2 Collection-0 Level-2A](https://sentinels.copernicus.eu/web/sentinel/sentinel-data-access/sentinel-products/sentinel-2-data-products/collection-0-level-2a), which provides bottom-of-atmosphere reflectance, aerosol optical thickness, water vapour and scene classification.
- Product specification: [Sentinel-2 Product Specification Document v15.0](https://sentinels.copernicus.eu/documents/d/sentinel/s2-pdgs-cs-di-psd-v15-0).
- Catalog and cloud-optimized assets: [Microsoft Planetary Computer `sentinel-2-l2a` STAC collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a).
- Current official Copernicus STAC interface: [Copernicus Data Space Ecosystem STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html).
- Reuse context: [Copernicus Data Space Ecosystem terms and conditions](https://dataspace.copernicus.eu/terms-and-conditions).

Copernicus Sentinel data are available on a free, full and open basis under the Sentinel data legal notice. The Planetary Computer hosts processed cloud-optimized assets and describes its STAC collection licence separately. KHANAN publishes derived statistics and token-free lineage URLs, not the source rasters or transient signed access parameters. Users must preserve Copernicus attribution and review both providers' current terms.

## Fixed observation windows

The release deliberately avoids a moving “latest” composite:

| Season ID | Inclusive date range | Eligible catalog items |
|---|---|---:|
| `dry_pre_monsoon_2025` | 2025-01-01 to 2025-05-31 | 48,841 |
| `post_monsoon_2025` | 2025-10-01 to 2025-12-31 | 35,826 |

The initial catalog query uses the bounding box 67–99°E, 5–39.5°N and retains scenes with catalog cloud cover below 60% and nodata below 100%. India relevance and local coverage are then evaluated against the KHANAN H3 grid rather than inferred from tile name alone.

## Scene selection

One scene is selected for each India-relevant MGRS tile in each window. For a tile, the pipeline first maximizes the number of India H3 resolution-6 centroids inside the item footprint. It then minimizes:

```text
cloud_pct
+ snow_pct
+ 0.25 * cloud_shadow_pct
+ 0.5 * nodata_pct
+ 10 * degraded_data_pct
- 0.02 * not_vegetated_pct
```

Remaining ties are resolved by acquisition time and item ID. This rule yields 475 tiles per season and 950 manifest rows. The footprint-first criterion matters: a provisional 20% catalog nodata ceiling removed valid edge scenes and created regular gaps. The final build permits any catalog nodata value below 100%, but selects the scene with the greatest local India-grid coverage before applying the quality penalty. The map and validation checks exposed and verified the correction.

Every manifest row retains the scene ID, tile, acquisition time, quality metadata, projection, orbit, product URI, token-free asset URLs, product-metadata hash, radiometric constants and selection rule.

## Sampling and radiometry

Each of the 88,857 India H3 resolution-6 cells is subdivided into all 49 H3 resolution-8 children. Their centroids are sampled once in each season: 98 requested observations per parent cell and 8,707,986 requested seasonal observations nationally.

Six bands are read from cloud-optimized overviews at approximately 160 m ground sampling distance:

| Band | Label | Native resolution |
|---|---|---:|
| B02 | blue | 10 m |
| B03 | green | 10 m |
| B04 | red | 10 m |
| B08 | near infrared | 10 m |
| B11 | short-wave infrared 1 | 20 m |
| B12 | short-wave infrared 2 | 20 m |

Digital numbers are converted to bottom-of-atmosphere reflectance using each product's XML `BOA_QUANTIFICATION_VALUE` and band-specific `BOA_ADD_OFFSET`. All selected scenes report Processing Baseline 05.11, quantification value 10,000 and a −1,000 DN offset for these six bands; the per-scene values are still retained rather than assumed.

The Scene Classification Layer is sampled at its native 20 m resolution. Categorical overviews were not used because provider-side overview interpolation produced codes outside the documented 0–11 class domain in testing. Native sampling preserves valid integer classes. Reflectance summaries use only observations with all six bands valid. “Clear land” is SCL vegetation or not-vegetated surface (classes 4 or 5); “bare” is SCL class 5.

When multiple selected tile footprints cover a sample point, the deterministic choice prefers a clear-land local SCL observation, then complete reflectance bands, then greater distance from the tile edge. Source scene IDs remain traceable in the cell table.

## Derived features

Seasonal medians are published over clear-land observations for six reflectance bands and five broad indices:

```text
NDVI  = (B08 - B04) / (B08 + B04)
NDMI  = (B08 - B11) / (B08 + B11)
MNDWI = (B03 - B11) / (B03 + B11)
BSI   = ((B11 + B04) - (B08 + B02)) / ((B11 + B04) + (B08 + B02))
NDTI  = (B11 - B12) / (B11 + B12)
```

Across two-season bare-surface samples, the table also publishes band and index medians plus exploratory B04/B02 and B11/B12 ratios. BSI is useful for exposed-ground context, while the other indices help characterize vegetation, moisture, water and SWIR behaviour. None is a diagnostic mineral identification.

The `bare_surface_quality_status` field distinguishes:

- `two_season_bare_support`: usable bare observations in both windows;
- `one_season_dominant_bare_support`: usable bare observations in only one window;
- `insufficient_bare_support`: neither condition is met.

## Validation results

The build passes 25 structural and scientific guardrail checks:

- 88,857 unique H3 feature rows and unique record IDs;
- 950 unique scene rows, with identical 475-tile sets in both seasons;
- 97.16% of cells have all 49 requested samples covered in each season;
- 98.96% of cells have at least one clear-land observation;
- 84.25% have two-season bare support, 7.34% have one-season-dominant support and 8.41% have insufficient support;
- native SCL codes remain within 0–11;
- normalized indices remain within −1 to 1;
- reflectance passes the declared physical-screen range;
- no transient signed-access token is present in either public CSV;
- national-grid and candidate-table SHA-256 hashes are unchanged.

Coverage is not the same as scientific adequacy. The 928 cells with no clear-land sample and every cell with limited bare support remain present with blanks and machine-readable quality flags. No interpolation or zero filling is used.

## Outputs and reproducibility

- `outputs/india_sentinel2_surface_context_h3_r6.csv`: one row per national H3 resolution-6 cell.
- `outputs/india_sentinel2_scene_manifest_2025.csv`: complete scene selection and lineage.
- `outputs/sentinel2_surface_context_validation.json`: build contract, metrics and checks.
- `assets/maps/khanan-sentinel2-surface-context-alpha18.png`: coverage and broad surface-context map.

From the repository root:

```bash
.venv/bin/python scripts/build_sentinel2_surface_context.py
.venv/bin/python scripts/plot_sentinel2_surface_context.py
```

The build caches catalog selections, product metadata and per-scene samples below the ignored `sources/raw/sentinel2_surface_context_2025/` tree. Re-running from that cache regenerates the published tables deterministically without redistributing the source rasters.

## Admission work still required

Before any Sentinel feature affects a prospectivity score, KHANAN must define material- and deposit-type mechanisms, establish leakage-safe spatial folds, compare against the unchanged v0.6 baseline, estimate uncertainty across spatial groups, test independent regions and reject features that do not improve out-of-region performance. Hyperspectral or field-spectrometer measurements, geological mapping and laboratory confirmation remain necessary for material-specific interpretation.
