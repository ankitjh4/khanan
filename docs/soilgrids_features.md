# SoilGrids 2.0 soil-context layer

**Feature transformation:** `soilgrids-v2-h3-r6-v0.1`

**Development release:** `v1.0-alpha.6`

## Decision

KHANAN publishes nine SoilGrids 2.0 soil-property predictions for every national H3 resolution-6 cell where the source has coverage. The layer is lawful to redistribute with attribution under CC BY 4.0 and carries explicit prediction-uncertainty bounds. It is context only: no SoilGrids field changes the v0.6 prospectivity scores, classes or ranks.

The layer fills a national soil-context gap without treating a modeled pedological surface as a geochemical assay. A separate leakage-aware spatial ablation is required before any field may enter a material model.

## Authoritative source and licence

ISRIC describes [SoilGrids 2.0](https://docs.isric.org/globaldata/soilgrids/index.html) as global 250 m machine-learning predictions of soil properties at six standard depth intervals. The product includes lower and upper bounds of a 90% prediction interval and is published under CC BY 4.0. KHANAN cites Poggio et al. (2021), [DOI 10.5194/soil-7-217-2021](https://doi.org/10.5194/soil-7-217-2021).

The [official layer documentation](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html) supplies the mapped units and conversion factors. The [official WCS documentation](https://docs.isric.org/globaldata/soilgrids/wcs.html) identifies Web Coverage Service as the supported mechanism for obtaining spatial subsets.

## Properties and units

KHANAN extracts the mean, 5th-percentile and 95th-percentile prediction for 0–5 cm and 30–60 cm depth:

| Code | Property | Published unit after conversion |
|---|---|---|
| `phh2o` | pH in water | pH |
| `clay` | clay content | percent by mass |
| `sand` | sand content | percent by mass |
| `silt` | silt content | percent by mass |
| `soc` | soil organic carbon | g/kg |
| `cec` | cation exchange capacity at pH 7 | cmol(c)/kg |
| `nitrogen` | total nitrogen | g/kg |
| `bdod` | bulk density of fine earth | kg/dm³ |
| `cfvo` | coarse fragments | volume percent |

The `p05` and `p95` columns preserve the source's 90% prediction interval. The interval width is exactly reconstructible as `p95 - p05` and is not duplicated as a stored column.

## Spatial extraction

`scripts/build_soilgrids_features.py` performs 54 WCS requests: nine properties × two depth intervals × three prediction statistics. Each request uses:

- WCS 1.0.0 `GetCoverage`;
- EPSG:4326 output;
- bounding box 68°E–98°E and 6°N–38°N;
- 1,200 columns × 1,280 rows;
- nominal 0.025-degree output cells;
- nearest-neighbour interpolation;
- signed 16-bit GeoTIFF output.

Each local raster is schema-checked and SHA-256 hashed. The ignored source cache is `sources/raw/soilgrids_v2_india_0p025deg/`. The feature build samples the nearest output-pixel centre for every H3 centroid and records the source-pixel coordinates and great-circle join distance.

The 0.025-degree derivative is approximately 2.2–2.8 km across India. It is deliberately coarser than the native 250 m source because KHANAN's H3 cells are approximately 36 km² and this release is a national screening layer. Users needing local analysis should return to the native product and appropriate field observations.

## Derived texture class

KHANAN sums the mean sand, silt and clay predictions at each depth, records that pre-normalization sum, normalizes the three fractions to 100%, and applies USDA texture-triangle rules. This class is a deterministic convenience derivative. It does not replace a measured soil description, and independent SoilGrids property models can make the unnormalized fractions differ modestly from 100%.

## Validation result

The alpha.6 build produced:

- 88,857 feature rows and 88,857 unique H3 cells;
- 54 aligned WCS rasters;
- 99.28% minimum national coverage across means and interval endpoints;
- 99.82% minimum mean-property coverage among the 2,784 candidate cells;
- zero `p05 > p95` violations;
- a maximum H3-centroid to WCS-pixel-centre distance of 1.938 km;
- identical hashes for the eight protected production-ranking columns before and after augmentation.

The machine-readable evidence is in `outputs/soilgrids_v2_soil_features_validation.json`. Source request URLs, local raster hashes, dimensions, transforms, bounds, nodata values and coverage are retained for all 54 inputs.

## Interpretation limits

- SoilGrids predicts soil properties; it does not measure ore minerals, elemental anomalies, grades, tonnage or deposit depth.
- Global models can have regional bias and spatially varying uncertainty.
- SoilGrids models use climate, land-cover, terrain and other environmental covariates. Some fields therefore overlap conceptually with existing KHANAN predictors and cannot be assumed statistically independent.
- Centroid sampling does not describe all within-cell variation.
- The p05–p95 interval expresses SoilGrids prediction uncertainty, not mineral-prospectivity or discovery confidence.
- Soil properties may reflect parent material, weathering, transport, land use and climate. A plausible mechanism and spatial out-of-region gain are required before model admission.
