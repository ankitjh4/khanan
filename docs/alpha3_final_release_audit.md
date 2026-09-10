# KHANAN Alpha 3.0 final release audit

## Completion boundary

Alpha 3.0 is the user-defined stopping point for the current KHANAN goal. Completion means that the declared open-source intelligence dataset is reproducible, publicly accessible, provenance-bearing and suitable for independent scientific evaluation. It does not mean that India has been exhaustively explored, that every mine or mineral occurrence is known, or that any model-generated candidate is a discovery.

The machine-readable audit is `outputs/alpha3_completion_audit.json`. The independent package verification is `outputs/independent_release_verification.json`. The 58-row `outputs/coverage_gap_register.csv` remains the authoritative limitation register.

## Requirement-by-requirement result

| Requirement | Result | Authoritative evidence |
|---|---|---|
| Reliable normalized material coverage | Pass | 254 unique evidence-derived entities in `india_material_ontology_v1.csv`: 69 elements, 89 mineral species and 96 other ores, rocks, groups, mixtures, industrial materials and energy commodities. Every entity has an authority classification, evidence-source lineage and English-name fallback. The count is not padded to satisfy a ceiling or floor. |
| Source-term normalization | Pass | 611 audited source terms in `material_source_term_crosswalk_v1.csv`: 602 mapped and nine deliberately unresolved or nonspecific. |
| Mine and occurrence evidence | Pass within declared source scope | MRDS coordinates, IBM MCDR inspection events and latest-mine identities, the IBM abandoned-mine inventory, IBM State Review occurrence geography and the partial GSI/OGD deposit preview are separate observed-evidence tables with source-specific limitations. |
| Lease and concession evidence | Pass within declared source scope | IBM lease aggregates, 97 auctioned concession rows, a complete MBS match audit, 67 admitted State MBS polygons and separate dated status evidence. None is promoted to current legal or operating status. |
| Geochemistry | Pass within declared source scope | 13 CC-BY EarthChem samples and 1,323 long-form analytical observations at two sites, with methods, qualifiers, hashes, source cells and model exclusion. The layer is sparse and targeted. |
| Geophysics | Pass within declared source scope | EMAG2v3 values, error estimates, source-grid codes and quality flags for 88,857 cells. The feature family failed its production admission test and remains contextual. |
| Soil | Pass within declared source scope | Nine SoilGrids properties at two depths with mean, p05 and p95 values. The feature family failed its production admission test and remains contextual. |
| Remote sensing | Pass within declared source scope | Two fixed 2025 Sentinel-2 seasons, 950 selected scenes, native quality masking, coverage fields and surface-context variables for 88,857 cells. Leakage and non-specificity block production admission. |
| Spatially validated rankings | Pass for supported v0.6 targets | Fifty targets are declared. Fifteen have sufficient evidence for spatial holdout estimates and fourteen meet the minimum 0.60 pseudo-absence ROC-AUC gate. The 2,784 promoted cells have unique contiguous national ranks, support tiers, spatial metrics, provenance and promotion rules. Unsupported materials remain unscored. |
| Uncertainty and exclusions | Pass | Candidate records retain validation support, spatial AUC and recall, EMAG2 error fields, SoilGrids p05/p95 ranges, uncertainty interpretations, model-use statuses, limitations and quality flags. These do not constitute calibrated discovery probabilities. |
| CSV and geospatial publication | Pass | The 88,857-cell national CSV includes centroids and H3 polygon WKT. The 2,784-row candidate CSV now has an exact typed polygon GeoJSON counterpart. The public overview map remains reproducible from release tables. |
| Provenance and schema governance | Pass | A frozen 45-row manifest covers 43 CSVs and two GeoJSON files. A 1,928-row dictionary covers every CSV column. All primary keys, schemas, hashes, source IDs, evidence roles, model-use limits and validation artifacts are declared. |
| Final coverage and limitation disclosure | Pass | Thirty-eight source-specific rows preserve every source-registry limitation exactly. Twenty project-wide rows cover geographic, temporal, licensing, access, method, validation, environmental, social, archaeological, infrastructure, field-verification and economic gaps. |
| Reproducible independent evaluation | Pass | The deterministic ZIP fixes member order, timestamps, permissions and compression. The standard-library independent verifier recomputes manifest contracts, keys, schemas, hashes, dictionary coverage, gap lineage, validation gates, candidate/grid parity, GeoJSON parity and interpretation guardrails without importing project builders. |
| Unsupported-claim prohibition | Pass | Model outputs describe reconnaissance hypotheses, not discoveries, reserves, resources, grades, legal rights, operating status or drill targets. Explicit current-status verification fields remain false. Source-reported IBM aggregates stay in observed-evidence tables and are not assigned to candidate cells. |

## What the rankings mean

The model ranks H3 cells by a relative reconnaissance index for supported materials. It uses broad host-unit association, distance to mapped source evidence and evidence density under spatial separation and candidate-promotion gates. The score is not a calibrated probability of discovering an economically recoverable deposit.

The candidate CSV and GeoJSON contain the same 2,784 records. Each GeoJSON feature carries typed properties and a SHA-256 of its exact source CSV row. This makes the geometry auditable without changing the frozen v0.6 score, class or rank.

## Remaining limitations

The release still lacks a complete current statutory mine and lease register with exact geometries; national systematic field geochemistry; higher-resolution and deposit-specific geophysics; drill logs; site-level grade, tonnage, depth, recovery and economics; authoritative protected-area, forest, hydrology, tenure, cultural, archaeological, community and infrastructure overlays; and qualified field verification of candidates.

These are scientific and operational scope limits, not hidden release failures. They prohibit treating KHANAN as a permission, title, investment, reserve-reporting, drilling or field-access product. Any future work requires lawful source access, expert geological review, environmental and heritage assessment, community engagement and qualified field validation.

## Reproduction and publication evidence

The README gives the full build order. The final sequence is:

```bash
.venv/bin/python scripts/build_candidate_geojson.py
.venv/bin/python scripts/build_release_governance.py
.venv/bin/python scripts/build_alpha3_completion_audit.py
node --expose-gc scripts/validate_release_governance_csv_artifacts.mjs
.venv/bin/python scripts/build_release.py
shasum -a 256 -c outputs/SHA256SUMS.txt
.venv/bin/python scripts/verify_release_independent.py \
  --bundle outputs/india_mining_dataset_csv_bundle_v1.0-alpha.30.zip \
  --checksums outputs/SHA256SUMS.txt \
  --workspace . \
  --output outputs/independent_release_verification.json
```

The public repository and commit-specific files are checked after the final commit is pushed. The commit hash is not embedded in release artifacts because doing so would create a self-referential hash cycle.
