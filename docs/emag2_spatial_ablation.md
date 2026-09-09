# EMAG2v3 spatial ablation

**Experiment:** `emag2-spatial-ablation-v0.1`

**Development release:** `v1.0-alpha.5`
**Status:** shadow-model evaluation; no production score or ranking changed

## Question

Does the alpha.4 EMAG2v3 magnetic feature family improve material-specific discrimination outside the spatial regions represented by the training evidence, after controlling for the existing geology, terrain, climate and proximity signals?

This is a feature-admission experiment. It does not estimate reserves, grade, depth, recoverability, mineability or discovery probability.

## Experimental unit and labels

- A positive is one unique H3 resolution-6 cell containing at least one coordinate-valid public-source record mapped to a retained v0.6 material target.
- Multiple records for the same material in the same H3 cell collapse to one positive. This reduces, but does not eliminate, catalog and deposit duplication.
- A background cell is deterministically sampled from cells more than 25 km from every mapped positive for that material.
- Background cells are pseudo-absences. They have not been confirmed barren.
- All 50 retained targets receive a result row. Evaluation requires at least 10 unique positive H3 cells and three H3 resolution-3 positive groups.

Fourteen materials meet those evaluation requirements. Zirconium has 12 raw coordinate-valid records but only six unique positive H3 cells, so it is correctly excluded from the cell-level ablation rather than treating colocated records as independent evidence.

## Paired models

Each fold fits two L2-regularized, class-balanced logistic models on the same training and test observations.

The baseline contains:

- elevation, approximate slope and local relief;
- rolling twelve-month temperature, precipitation, humidity and wind;
- fold-safe log distance to the nearest training positive;
- fold-safe count of training positives within 100 km; and
- fold-safe training-positive geological-unit affinity.

The extended model adds:

- signed and absolute EMAG2 anomaly;
- local 3×3-pixel anomaly mean, standard deviation and range;
- signed and absolute India-grid robust anomaly z-scores;
- published error estimate;
- absolute signal-to-error ratio; and
- an ambiguous/no-data source indicator.

Missing values are imputed from the training-fold median and receive missingness indicators. Features use training-fold 5th-to-95th-percentile robust scaling and are clipped to ±10 after scaling to bound extreme spatial extrapolation. The test fold never supplies imputation or scaling statistics.

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
3. At least 80% of positive cells have valid EMAG2 anomalies.
4. Extended-model ROC AUC is at least 0.60.
5. Paired ROC-AUC improvement is at least 0.02.
6. The spatial-group bootstrap 95% lower bound for that improvement is strictly positive.
7. Recall at the paired background top 5% does not decline.

Passing this gate would authorize only a separate nationwide shadow-ranking experiment. It would not automatically change production rankings.

## Result

No material passes the admission gate.

- Nine of 14 evaluated materials have a positive pooled ROC-AUC change, but every positive change has a bootstrap interval that crosses zero.
- Silicon has the largest eligible positive change: AUC increases from 0.7486 to 0.7838 (`+0.0352`), but its interval is `[-0.0108, 0.0706]`.
- Iron improves from 0.8156 to 0.8326 (`+0.0170`) and recall rises from 0.1293 to 0.2653, but the AUC gain is below 0.02 and its interval crosses zero.
- Zinc declines from 0.7117 to 0.6556 (`-0.0561`); its interval `[-0.1186, -0.0107]` is wholly negative.
- Graphite has a positive point estimate but only 15 unique positive cells, its interval crosses zero, and recall declines.

The scientifically defensible outcome is therefore to retain EMAG2v3 as contextual data and keep it out of the published prospectivity score. The result also shows why adding a plausible geophysical layer without ablation would have been unsafe.

## Published evidence

- `outputs/material_emag2_spatial_ablation.csv` contains one record for every retained target.
- `outputs/material_emag2_spatial_ablation_folds.csv` contains all completed fold metrics and spatial-separation checks.
- `outputs/emag2_spatial_ablation_validation.json` records input hashes, protocol constants, aggregate counts, output hashes and publication gates.
- `assets/figures/khanan-emag2-spatial-ablation-v0.1.png` visualizes paired AUC changes, bootstrap intervals and recall changes.

## Remaining limitations

- The positive catalog is incomplete and spatially biased, and multiple H3 cells can still belong to one deposit or district-scale exploration campaign.
- Pseudo-absence metrics can reward catalog geography rather than mineral-process generalization.
- EMAG2 is a heterogeneous global compilation at two-arc-minute resolution and a consistent 4 km altitude; deposit-scale magnetic structure is unresolved.
- Linear regularization is intentionally transparent but cannot express every deposit-type interaction.
- The experiment covers only the 14 targets with enough unique mapped cells. It says nothing reliable about unsupported materials.
- Independent deposits, time-separated discoveries, negative drilling, higher-resolution geophysics and deposit-type labels remain necessary for a discovery-grade model.
