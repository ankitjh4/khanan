# Official-block transfer validation

**Development release:** `v1.0-alpha.20`

**Experiment:** `official-block-transfer-v0.1`

**Production scoring effect:** none

## Question

Do KHANAN v0.6 target-material scores rank official Indian auction and exploration blocks above background areas when the official block tables are held out from model construction?

This is a transfer-alignment test, not discovery validation. An auction or exploration block is evidence that an official programme selected and described an area for a material. It is not proof of a deposit, resource, reserve, recoverable grade, economic viability, current grant, operating mine, or permission to enter land.

## Held-out sources

The evaluation uses two existing authoritative KHANAN layers that have always been excluded from v0.6 training and scoring:

- 99 unique accepted central critical-mineral auction footprints. These represent 142 accepted offer-event rows after reoffers are deduplicated by `block_lineage_key`. The Biarpalli source-location mismatch remains excluded.
- 67 admitted State auction Mine Block Summary footprints linked to IBM's 2023–24 granted-concession table.

Together they provide a screened pool of 166 unique official footprints. After retaining only names mapped to the 50 v0.6 target materials, 151 footprints—87 central and 64 State—contribute 221 block-material observations across 24 materials. The other 15 remain in their authoritative source layers but do not generate a v0.6 target observation. A multi-material block contributes one observation per normalized target. Central reoffers contribute one footprint, while every represented event ID and name variant remains traceable.

The official sources are publication-independent of the USGS MRDS extract used to build v0.6. They are not proven knowledge-independent: Indian exploration programmes may have used historical geological knowledge that also influenced MRDS or its references. This unresolved dependence is a hard production-admission guardrail.

## Exact score reconstruction

The evaluator independently rebuilds all 50 full-data v0.6 material scores from the published MRDS evidence, India H3 grid and geological map-unit IDs. It reproduces the model evidence filter requiring India-bounded coordinates and a successful Census district join. It then recomputes the published geology, distance, density, support-weight and national-percentile calculations.

All 444,285 published top-five score, percentile and distance values match exactly after their documented rounding. This check prevents a subtly different reimplementation from being presented as an external test of v0.6.

## Unit of analysis

One observation is one unique official footprint and one normalized target material. The score is sampled from the H3 resolution-6 cell containing the authoritative polygon centroid. Using one centroid per block prevents larger polygons from receiving more statistical weight. The observation output still points to the source geometry table and official document.

## Leakage and background controls

The primary positive cohort excludes block centroids within 25 km of any MRDS training record for the same material. This removes direct local proximity cases from the transfer estimate.

For each evaluated material, the deterministic background pool contains India H3 resolution-6 cells that are:

- more than 25 km from every MRDS training occurrence for that material; and
- more than 25 km from every retained official block centroid naming that material.

The sample size is the smaller of the available pool and the larger of 500 or 20 times the positive-block count. The smallest realized background distance is 25.10 km from MRDS evidence and 25.16 km from an official block.

The candidate-distance subset is also reported separately. It requires a block centroid to be more than 25 km and no more than 250 km from MRDS evidence, matching the v0.6 distance domain for candidate promotion.

## Metrics and uncertainty

Materials require at least five outside-25-km official blocks across three H3 resolution-3 groups for point estimates and spatial uncertainty. Twelve materials meet this descriptive threshold.

For each material, the release reports:

- ROC-AUC against deterministic background;
- average precision, with an explicit warning that it depends on the chosen background ratio;
- recall at the background 95th-percentile score threshold;
- a 500-replicate H3 resolution-3 group bootstrap interval for AUC and recall;
- median national percentile and shares above the 95th, 99th and 99.5th percentiles;
- the rate at which the official source target is the published top material or appears in the published top five; and
- the rate at which the target itself would meet the v0.6 minimum priority thresholds at the block centroid.

Positive and background spatial groups are resampled separately with replacement. This preserves both classes in every replicate and reduces false precision from clustered blocks or neighbouring background cells.

## Predeclared statistical gate

A material must satisfy every condition:

- at least 10 primary positive blocks;
- at least four positive H3 resolution-3 groups;
- at least 10 MRDS training records;
- published internal spatial-holdout AUC at least 0.60;
- transfer AUC at least 0.60;
- transfer AUC 95% lower bound strictly above 0.50;
- transfer recall at the background top 5% at least 0.20; and
- official target appears in the published top five at least 20% of the time.

Even a statistical pass would remain diagnostic. Production admission additionally requires a genuinely independent confirmed occurrence/deposit set or field validation. That condition is unresolved in alpha.20.

## Results

| Material | Eligible blocks | H3 r3 groups | Transfer AUC | 95% interval | Recall at background top 5% | Target in published top five | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Manganese | 7 | 3 | 0.9517 | 0.8663–0.9890 | 0.8571 | 0.8571 | Strong point estimate and interval, but below both support gates. |
| Calcium and limestone | 26 | 6 | 0.7962 | 0.3146–0.8795 | 0.0000 | 0.0000 | Broad interval, only six training records, and no high-score or top-five retrieval. |
| Iron | 14 | 7 | 0.6677 | 0.4860–0.8209 | 0.0000 | 0.5000 | Interval crosses 0.50 and high-score recall is zero. |
| Phosphorus | 10 | 7 | 0.6596 | 0.3720–0.8714 | 0.4000 | 0.7000 | Recall and retrieval are positive, but the interval crosses 0.50. |
| Aluminium | 8 | 6 | 0.6480 | 0.4194–0.7924 | 0.0000 | 0.8750 | Below block support; interval crosses 0.50 and recall is zero. |
| Cobalt | 5 | 4 | 0.6456 | 0.3007–0.8718 | 0.0000 | 0.0000 | Minimal block support, only four training records, and no retrieval. |
| Graphite | 16 | 10 | 0.5693 | 0.3124–0.8356 | 0.2500 | 0.2500 | Point estimate is below the AUC threshold. |
| Rare-earth elements | 13 | 11 | 0.5232 | 0.4211–0.6172 | 0.0769 | 0.0000 | Near chance, only nine training records, and no top-five retrieval. |
| Vanadium | 21 | 12 | 0.4907 | 0.3101–0.7054 | 0.0476 | 0.0476 | Point estimate is below chance and internal v0.6 AUC is below 0.60. |
| Nickel | 7 | 6 | 0.4820 | 0.2506–0.7292 | 0.1429 | 0.0000 | Below support and transfer thresholds. |
| Titanium | 11 | 9 | 0.4109 | 0.2795–0.5550 | 0.0000 | 0.1818 | Transfer result contradicts reliable out-of-source ranking. |
| Molybdenum | 7 | 4 | 0.1166 | 0.0626–0.2167 | 0.0000 | 0.0000 | Strong negative transfer result with only four training records. |

No material passes the complete predeclared statistical gate. No material passes the production-admission gate. The candidate table and national grid hashes remain unchanged.

## Interpretation

The result materially narrows how v0.6 should be used. Manganese warrants additional independent evaluation because the seven eligible official blocks score much higher than background, but seven blocks in three broad regions are insufficient for the fixed gate. Iron and Phosphorus have positive point estimates, yet their spatial uncertainty includes chance performance. Graphite, Vanadium, Titanium and Molybdenum show important transfer weakness despite some having useful internal or Sentinel-related signals.

The official blocks should not be converted into discoveries or production labels. They are best used to identify which material models need better coordinates, deposit-type labels, geochemistry, geophysics, and temporally independent evidence. Alpha.20 therefore adds evidence about model limitations without promoting or reranking any area.

## Reproduction

```bash
.venv/bin/python scripts/evaluate_official_block_transfer.py
.venv/bin/python scripts/plot_official_block_transfer.py
```

The evaluator emits the material summary, block-material observations, validation JSON, dictionary additions and release-level validation summary. It asserts exact v0.6 score parity and unchanged national-grid and candidate hashes on every run.
