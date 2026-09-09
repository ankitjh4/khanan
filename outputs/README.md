# KHANAN outputs

This directory contains the current derived release artifacts. It is organized as follows:

- The root contains the v0.6 geospatial/model baseline plus the current v1.0-alpha.3 development release: the v1 ontology, IBM abandoned-mine context, metadata-only NGDR/GSI service audit, crosswalk, validation, checksums and compressed bundle.
- `archive/releases/` contains superseded local release bundles and is not committed to Git.
- `diagnostics/workbook/` contains local workbook renders, inspections and formula-error scans and is not committed to Git.

The full `india_mining_prospectivity_grid_h3_r6.csv` is intentionally excluded from the Git checkout because it exceeds GitHub's normal single-file limit. It remains available locally and inside `india_mining_dataset_csv_bundle_v1.0-alpha.3.zip`.

The v1 material layer comprises `india_material_ontology_v1.csv` (230 typed entities), `material_source_term_crosswalk_v1.csv` (450 audited terms), and `material_ontology_validation_v1.json`. The IBM contextual mine layer comprises `india_ibm_abandoned_mine_sites.csv` (82 records) and its validation JSON. Ontology inclusion is not model eligibility: current prediction columns still use the 50 retained v0.6 targets.

See the repository root `README.md`, `source_registry.csv`, `data_dictionary.csv`, and `validation_report.json` before using the data.
