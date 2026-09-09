# KHANAN data layout

KHANAN separates immutable source downloads from derived release artifacts:

- `../sources/raw/` — downloaded public-source material and caches; intentionally excluded from Git because of size and source-specific redistribution terms.
- `../outputs/` — derived CSV, JSON, XLSX, validation, checksum, and release-bundle artifacts.
- `../outputs/archive/releases/` — superseded local release bundles; intentionally excluded from Git.
- `../outputs/diagnostics/` — local rendering and inspection evidence; intentionally excluded from Git.
- `../config/` — legacy modeling-target definitions, weather window, and curated auction-result configuration.
- `../outputs/source_registry.csv` — source-by-source provenance, usage, licensing/access notes, and limitations.
- `../outputs/data_dictionary.csv` — field definitions and missing-value rules.

The compressed `../outputs/india_mining_dataset_csv_bundle_v1.0-alpha.3.zip` is the current portable development release. It packages the v0.6 geospatial/model baseline together with the v1 ontology, source-term crosswalk, IBM abandoned-mine context layer, and metadata-only NGDR/GSI service audit. The uncompressed nationwide grid is regenerated locally and excluded from the Git checkout because it exceeds GitHub's ordinary file-size limit.
