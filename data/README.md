# KHANAN data layout

KHANAN separates immutable source downloads from derived release artifacts:

- `../sources/raw/` — downloaded public-source material and caches; intentionally excluded from Git because of size and source-specific redistribution terms.
- `../outputs/` — derived CSV, JSON, XLSX, validation, checksum, and release-bundle artifacts.
- `../outputs/archive/releases/` — superseded local release bundles; intentionally excluded from Git.
- `../outputs/diagnostics/` — local rendering and inspection evidence; intentionally excluded from Git.
- `../config/` — material taxonomy, weather window, and curated auction-result configuration.
- `../outputs/source_registry.csv` — source-by-source provenance, usage, licensing/access notes, and limitations.
- `../outputs/data_dictionary.csv` — field definitions and missing-value rules.

The compressed `../outputs/india_mining_dataset_csv_bundle_v0.6.zip` is the portable canonical release. The uncompressed nationwide grid is regenerated locally and excluded from Git because it exceeds GitHub's ordinary file-size limit.
