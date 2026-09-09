# SoilGrids spatial ablation

**Experiment:** `soilgrids-spatial-ablation-v0.1`

**Development release:** `v1.0-alpha.7`

**Status:** shadow-model evaluation; no production score or ranking changed

## Question

Does the alpha.6 SoilGrids feature family improve material-specific discrimination outside the spatial regions represented by the training evidence, after controlling for the existing geology, terrain, climate and proximity signals?

This is a feature-admission experiment. It does not estimate reserves, grade, depth, recoverability, mineability or discovery probability. SoilGrids is a modeled pedological product, not a geochemical assay.

## Experimental unit and labels

- A positive is one unique H3 resolution-6 cell containing at least one coordinate-valid public-source record mapped to a retained v0.6 material target.
- Multiple records for the same material in the same cell collapse to one positive.
- A background cell is deterministically sampled from cells more than 25 km from every mapped positive for that material.
- Background cells are pseudo-absences. They have not been confirmed barren.
- All 50 retained targets receive a result row. Evaluation requires at least 10 unique positive H3 cells and three H3 resolution-3 positive groups.

Fourteen materials meet those evaluation requirements. The deterministic sample membership, spatial folds, purges and baseline predictions are identical to the EMAG2 ablation, which permits a direct feature-family comparison.

## Paired models

Each fold fits two L2-regularized, class-balanced logistic models on the same training and test observations.

The baseline contains:

- elevation, approximate slope and local relief;
- rolling twelve-month temperature, precipitation, humidity and wind;
- fold-safe log distance to the nearest training positive;
- fold-safe count of training positives within 100 km; and
- fold-safe training-positive geological-unit affinity.

The extended model adds 36 SoilGrids variables:

- mean pH in water, clay, sand, silt, soil organic carbon, cation exchange capacity, total nitrogen, bulk density and coarse fragments at 0–5 cm and 30–60 cm; and
- the source p95 minus p05 interval width for every property-depth pair.

The 18 widths preserve the scale of the source's 90% prediction interval without treating it as prospectivity confidence. At least 80% complete-positive coverage is required for admission, where complete means that all 18 mean values are present. Missing values are imputed from the training-fold median and receive missingness indicators. Features use training-fold 5th-to-95th-percentile robust scaling and are clipped to ±10 after scaling. The test fold never supplies imputation or scaling statistics.

## Spatial separation

`StratifiedGroupKFold` assigns whole H3 resolution-3 regions to folds. Training and test group identifiers must be disjoint. The pipeline then purges every training observation within 50 km of a held-out positive. Across all 70 completed folds, the observed minimum distance from a held-out positive to a retained training positive is at least 50 km.

The dynamic distance, density and geological-affinity predictors are rebuilt from training positives inside each fold. A training-positive row uses leave-one-out distance, density and geological count so it cannot identify itself as evidence.

## Metrics and uncertainty

The paired out-of-fold predictions produce:

- pseudo-absence ROC AUC;
- average precision;
- positive recall above each fold's background 95th-percentile score; and
- Brier score, retained as a provisional diagnostic because class-balanced fitting does not produce a calibrated prevalence estimate.

The uncertainty interval for the ROC-AUC change uses 500 paired bootstrap replicates sampled by spatial group, stratified between positive-containing and background-only groups.

## Admission gate

A material can pass only when all of the following are true:

1. At least 20 unique positive H3 cells and four positive H3 resolution-3 groups.
2. Every planned spatial fold completes.
3. At least 80% of positive cells have all 18 SoilGrids means.
4. Extended-model ROC AUC is at least 0.60.
5. Paired ROC-AUC improvement is at least 0.02.
6. The spatial-group bootstrap 95% lower bound for that improvement is strictly positive.
7. Recall at the paired background top 5% does not decline.

Passing this gate would authorize only a separate nationwide shadow-ranking and geological-mechanism review. It would not automatically change production rankings.

## Result

No material passes the admission gate.

- Four of 14 evaluated materials have a positive pooled ROC-AUC change and ten decline. No positive change has a bootstrap interval with a strictly positive lower bound.
- Vanadium has the largest point improvement (`+0.1253`), but it has only 10 unique positive cells, its extended AUC is `0.5546`, and its interval `[-0.1152, 0.3134]` is wide and crosses zero.
- Silver improves by `+0.0532`, but its extended AUC is `0.5850` and its interval `[-0.1190, 0.2474]` crosses zero.
- Aluminium is the strongest adequately supported point result: AUC increases from `0.7251` to `0.7558` (`+0.0307`) and recall rises from `0.1286` to `0.1714`. Its interval `[-0.0101, 0.0757]` still crosses zero.
- Phosphorus declines by `-0.0421` with interval `[-0.0832, -0.0089]`; manganese declines by `-0.0886` with interval `[-0.1915, -0.0201]`. Both intervals are wholly negative.

The defensible result is to retain SoilGrids as contextual data and keep it out of the published prospectivity score. The experiment also shows that a plausible environmental layer can degrade generalization once the comparison is spatially separated.

## Published evidence

- `outputs/material_soilgrids_spatial_ablation.csv` contains one record for every retained target.
- `outputs/material_soilgrids_spatial_ablation_folds.csv` contains all completed fold metrics and spatial-separation checks.
- `outputs/soilgrids_spatial_ablation_validation.json` records input hashes, protocol constants, aggregate results, output hashes and publication gates.
- `assets/figures/khanan-soilgrids-spatial-ablation-v0.1.png` visualizes paired AUC changes, bootstrap intervals and recall changes.

## Remaining limitations

- The positive catalog is incomplete and spatially biased, and multiple H3 cells can still belong to one deposit or district-scale exploration campaign.
- Pseudo-absence metrics can reward catalog geography rather than mineral-process generalization.
- SoilGrids predicts near-surface soil properties from environmental covariates; it does not directly measure ore minerals, elemental anomalies, deposit depth or alteration.
- The model adds correlated composition fields and environmental derivatives. Regularization limits instability but does not establish a causal mechanism.
- Linear regularization is intentionally transparent but cannot express every deposit-type interaction.
- The experiment covers only the 14 targets with enough unique mapped cells. It says nothing reliable about unsupported materials.
- Independent deposit labels, measured India-specific soil geochemistry, analytical methods, detection limits, negative drilling and deposit-type labels remain necessary for a discovery-grade model.
