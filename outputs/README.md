# KHANAN outputs

This directory contains the current derived release artifacts. It is organized as follows:

- The root contains the v0.11 geospatial feature baseline and unchanged v0.6 prospectivity model in the current v1.0-alpha.14 development release: the v1 ontology, IBM abandoned-mine and 2024 mineral-concession context, reviewed State MBS geometries and Andhra status evidence, metadata-only NGDR/GSI service audit, EMAG2v3 and SoilGrids context plus paired spatial ablations, crosswalk, validation, checksums and compressed bundle.
- `archive/releases/` contains superseded local release bundles and is not committed to Git.
- `diagnostics/workbook/` contains local workbook renders, inspections and formula-error scans and is not committed to Git.

The full `india_mining_prospectivity_grid_h3_r6.csv` is intentionally excluded from the Git checkout because it exceeds GitHub's normal single-file limit. It remains available locally and inside `india_mining_dataset_csv_bundle_v1.0-alpha.14.zip`.

The v1 material layer comprises `india_material_ontology_v1.csv` (233 typed entities), `material_source_term_crosswalk_v1.csv` (510 audited terms), and `material_ontology_validation_v1.json`. The IBM context layer comprises 82 abandoned-mine records, 123 official lease-distribution rows and 97 auction-granted concession rows. The alpha.14 State MBS audit reviews 44 rows: 39 exact document selections, five Andhra rows with no exact match in the current public State index, 24 admitted source footprints, fifteen selected-MBS records withheld, and 53 records unreviewed. The separate five-row Andhra status layer retains dated official-secondary evidence and one Mincheri auction-date conflict without claiming current operation or creating geometry. The EMAG2 layer comprises `india_emag2v3_magnetic_features_h3_r6.csv` (88,857 H3 cells), feature validation, and 50 material-level plus 70 fold-level ablation records. The SoilGrids layer comprises `india_soilgrids_v2_soil_features_h3_r6.csv` (88,857 H3 cells), feature validation covering 54 WCS rasters, and another 50 material-level plus 70 fold-level ablation records. Ontology or feature inclusion is not model eligibility: current prediction columns still use the 50 retained v0.6 targets, and the new MBS, status, EMAG2 and SoilGrids layers do not alter scoring.

See the repository root `README.md`, `source_registry.csv`, `data_dictionary.csv`, and `validation_report.json` before using the data.
