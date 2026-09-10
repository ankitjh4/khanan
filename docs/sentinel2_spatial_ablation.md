# Sentinel-2 spatial ablation

**Experiment:** `sentinel2-spatial-ablation-v0.1`

**Development release:** `v1.0-alpha.19`

**Status:** shadow-model evaluation; no production score or ranking changed

## Question

Does the alpha.18 Sentinel-2 surface-context family improve material-specific discrimination outside the spatial regions represented by the training evidence, after controlling for the existing geology, terrain, climate and fold-safe proximity signals?

This is a feature-admission experiment. It does not estimate reserves, grade, depth, recoverability, mineability or discovery probability. The input bands and indices are broad surface measurements, not diagnostic mineral spectra or subsurface observations.

## Experimental unit and labels

- A positive is one unique H3 resolution-6 cell containing at least one coordinate-valid public-source record mapped to a retained v0.6 material target.
- Multiple records for the same material in the same cell collapse to one positive.
- A background cell is deterministically sampled from cells more than 25 km from every mapped positive for that material.
- Background cells are pseudo-absences. They have not been confirmed barren.
- All 50 retained targets receive a result row. Evaluation requires at least 10 unique positive H3 cells and three positive H3 resolution-3 groups.

Fourteen materials meet those evaluation requirements and produce 70 completed folds. The deterministic evidence, background samples, spatial folds, 50 km purge and baseline model are identical to the published SoilGrids ablation. All baseline counts and metrics reproduce exactly to eight decimal places.

## Paired models

Each fold fits two L2-regularized, class-balanced logistic models on the same training and test observations.

The baseline contains:

- elevation, approximate slope and local relief;
- rolling twelve-month temperature, precipitation, humidity and wind;
- fold-safe log distance to the nearest training positive;
- fold-safe count of training positives within 100 km; and
- fold-safe training-positive geological-unit affinity.

The extended model adds 18 Sentinel-2 variables:

- two-season bare-surface medians for B02, B03, B04, B08, B11 and B12 bottom-of-atmosphere reflectance;
- two-season bare-surface NDVI, NDMI, BSI and NDTI medians;
- exploratory bare-surface B04/B02 and B11/B12 ratios; and
- dry/pre-monsoon and post-monsoon clear-land NDVI, NDMI and BSI medians.

Observation counts, coverage fractions, selected scene IDs, support classes and quality flags are excluded from the model. Missing Sentinel values receive training-fold medians before the extended pipeline so imagery missingness does not become a predictor. Runtime checks confirm that the extended design adds exactly 18 columns beyond the paired baseline after preprocessing. Features use training-fold 5th-to-95th-percentile robust scaling and are clipped to ±10 after scaling. The test fold never supplies imputation or scaling statistics.

The observation date creates a separate unresolved leakage risk. A 2025 pixel at a known mine can contain excavation, waste rock, haul roads or other post-discovery disturbance. Spatial folds prevent neighbouring records from crossing the train/test boundary, but they cannot prove that a positive pixel represents pre-discovery geology rather than a visible mine. The production gate therefore also requires this risk to be resolved with pre-activity imagery, mine-footprint masking, off-footprint ring features or prospect-only independent validation. That condition is false in alpha.19.

## Spatial separation

`StratifiedGroupKFold` assigns whole H3 resolution-3 regions to folds. Training and test group identifiers must be disjoint. The pipeline then purges every training observation within 50 km of a held-out positive. The smallest observed distance from a held-out positive to a retained training positive is 50.372 km.

The dynamic distance, density and geological-affinity predictors are rebuilt from training positives inside each fold. A training-positive row uses leave-one-out distance, density and geological count so it cannot identify itself as evidence.

## Metrics and uncertainty

The paired out-of-fold predictions produce:

- pseudo-absence ROC AUC;
- average precision;
- positive recall above each fold's background 95th-percentile score; and
- Brier score, retained as a provisional diagnostic because class-balanced fitting does not produce a calibrated prevalence estimate.

The uncertainty interval for the ROC-AUC change uses 500 paired bootstrap replicates sampled by spatial group and stratified between positive-containing and background-only groups.

## Admission gate

A material can pass only when all of the following are true:

1. At least 20 unique positive H3 cells and four positive H3 resolution-3 groups.
2. Every planned spatial fold completes.
3. At least 80% of positive cells have all 18 Sentinel-2 predictors before fold-only imputation.
4. Extended-model ROC AUC is at least 0.60.
5. Paired ROC-AUC improvement is at least 0.02.
6. The spatial-group bootstrap 95% lower bound for that improvement is strictly positive.
7. Recall at the paired background top 5% does not decline.
8. Post-label mine-disturbance leakage is resolved with an independently validated design.

Passing would authorize only geological-domain review and a separate nationwide shadow-ranking test. It would not change production rankings automatically.

## Result

No material passes the admission gate. Four of 14 evaluated materials improve in pooled ROC AUC and ten decline.

- Vanadium has the largest point improvement: AUC rises from `0.4293` to `0.6817` (`+0.2524`) with interval `[+0.0890, +0.3764]`, and recall rises from `0.0000` to `0.1000`. It has only 10 unique positive cells, half the admission minimum, so the result is not admitted.
- Silver has 20 positive cells and improves from `0.5318` to `0.6570` (`+0.1252`) with interval `[+0.0212, +0.2329]`. Its high-score recall falls from `0.2500` to `0.2000`, so it fails the fixed non-degradation gate.
- Lead improves by `+0.0619` to AUC `0.6611` and recall increases, but its interval `[-0.0179, +0.1392]` crosses zero.
- Copper improves by only `+0.0072`; its interval crosses zero and the point change is below the `+0.02` minimum.
- Titanium, manganese and phosphorus have wholly negative AUC-change intervals. Their extended models degrade spatial generalization under this feature family.

The defensible result is to retain the Sentinel-2 layer as surface context and keep it out of the published prospectivity score. The apparently strong Vanadium and Silver results are scientifically useful leads for additional labels, deposit-type mechanisms and independent testing, not discoveries or current candidate evidence.

## Published evidence

- `outputs/material_sentinel2_spatial_ablation.csv` contains one record for every retained target.
- `outputs/material_sentinel2_spatial_ablation_folds.csv` contains all completed fold metrics and spatial-separation checks.
- `outputs/sentinel2_spatial_ablation_validation.json` records input hashes, protocol constants, baseline parity, aggregate results, output hashes and publication gates.
- `assets/figures/khanan-sentinel2-spatial-ablation-v0.1.png` visualizes paired AUC changes, bootstrap intervals and recall changes.

## Remaining limitations

- The positive catalog is incomplete and spatially biased, and multiple H3 cells can belong to one deposit or district-scale exploration campaign.
- Pseudo-absence metrics can reward catalog geography rather than mineral-process generalization.
- The 2025 surface at a known mine may encode the mine's own disturbance or infrastructure. This post-label leakage risk is unresolved and independently blocks production admission.
- The broad feature family was intentionally shared across materials; it is not a deposit-type or mineral-specific spectral model.
- Sentinel-2 measures surface reflectance. Vegetation, moisture, land use, atmosphere, mixed pixels and seasonal exposure remain confounders even after SCL masking.
- The two 2025 windows are fixed snapshots, not a multi-year phenology or atmospheric-robust composite.
- Linear regularization is transparent but cannot express every geological interaction.
- The experiment covers only 14 targets with enough unique mapped cells. It says nothing reliable about unsupported materials.
- Independent deposit labels, hyperspectral or field spectra, alteration mineralogy, measured geochemistry, negative drilling and deposit-type labels remain necessary for a discovery-grade model.
