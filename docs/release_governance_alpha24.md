# Alpha.24 release governance and coverage audit

## Purpose

Alpha.24 adds a release-wide contract around KHANAN's existing evidence, context, validation and model outputs. It does not add a mineral occurrence, change a feature admitted to production scoring, retrain a model, promote a cell or make a discovery claim.

The milestone addresses two Alpha 3.0 completion requirements that previously existed only across many layer-specific documents:

1. freeze and validate the schema, key, evidence role, source lineage and interpretation boundary of every published table and geospatial feature collection; and
2. consolidate known geographic, temporal, licensing, access, method, validation and operational limitations into one machine-readable coverage report.

## Release artifact manifest

`outputs/release_artifact_manifest.csv` contains 44 rows: 43 root-level CSV artifacts and the 67-feature State auction-footprint GeoJSON. Every row declares:

- a release-relative path, serialization type and Alpha.24 schema version;
- the row or feature grain and ordered primary-key fields;
- row/feature and column/property counts;
- a canonical schema SHA-256 and artifact-byte SHA-256;
- external source identifiers and source-specific licence/access notes;
- geographic and temporal scope;
- coordinate/geometry, uncertainty and exclusion/quality fields discovered from the frozen schema;
- one controlled evidence role and a model-use restriction;
- the primary builder, validation artifact and interpretation limitation.

The controlled roles are `observed_source_evidence`, `contextual_feature`, `model_hypothesis`, `validation_evidence` and `metadata_governance`. They prevent a source observation, district-level context, modeled environmental feature, validation result or model-generated candidate from being silently treated as the same kind of evidence.

Every primary key is nonblank and unique in this snapshot. Every schema hash matches the frozen contract in `scripts/build_release_governance.py`. A breaking or semantic schema change requires a new release version, an explicit dictionary and schema-hash update, validation and a documented migration note.

### Manifest self-hash rule

A file cannot contain its own final byte hash without changing those bytes. The manifest therefore leaves `artifact_sha256` blank only in its own row and marks the exception as `external_SHA256SUMS_only_self_reference_exception`. `outputs/SHA256SUMS.txt`, generated after the manifest, supplies the manifest's final byte hash. All other manifest rows contain their artifact hash directly.

## Complete data dictionary

Alpha.24 rebuilds `outputs/data_dictionary.csv` in exact filename and source-column order. It now has 1,928 unique table/column definitions, exactly one for every column in all 43 published CSVs. The rebuild:

- normalizes nine older extensionless table labels to their actual `.csv` filenames;
- copies the already-published national-grid definitions to the candidate subset's 90 inherited EMAG2 and SoilGrids fields;
- adds the previously absent 11 model-support and seven material-validation definitions;
- defines the source registry and the data dictionary itself; and
- adds complete definitions for the manifest and coverage-gap register.

The governance validator rejects a missing, extra or duplicate dictionary key.

## Coverage-gap register

`outputs/coverage_gap_register.csv` has 58 rows:

- 38 source-specific rows reproduce every nonblank limitation from `outputs/source_registry.csv`, infer one or more descriptive gap categories and list the affected release artifacts; and
- 20 project-wide rows consolidate gaps that span sources or represent an absent evidence family.

The project-wide rows cover material/model support, known-site completeness, mine and concession status, analytical geochemistry, NGDR access, historical GSI catalogue access, geophysics, soil, Sentinel-2 leakage and temporal scope, independent transfer evidence, administrative/demographic vintages, weather, ecology, hydrology, environmental/social/archaeological safeguards and infrastructure, deposit-type modeling, public large-file distribution, field verification, resource/economic assessment and cross-source licensing.

An open gap is not silently recoded as a zero or negative observation. Each row states its scientific or operational impact, current mitigation, evidence required for resolution, model effect and required treatment in the Alpha 3.0 completion audit. Alpha 3.0 can disclose a scope limitation without pretending India has been exhaustively explored; it cannot hide or contradict that limitation.

## Validation

`outputs/release_governance_validation.json` verifies:

- exactly 44 registered artifacts: 43 CSVs and one GeoJSON;
- all 44 schemas match their release contracts;
- all primary keys are unique and contain no blank components;
- exactly 1,928 dictionary rows cover all CSV columns with no missing, extra or duplicate keys;
- all 38 source-registry entries have a source-specific gap row;
- exactly 20 project-wide gaps are present;
- all five evidence roles are represented; and
- the v0.12 national-grid and v0.6 candidate hashes are unchanged.

The manifest, gap register and dictionary are also imported, inspected, recalculated, rendered and scanned for spreadsheet error tokens by `scripts/validate_release_governance_csv_artifacts.mjs` using the bundled spreadsheet runtime.

## Reproduction

Run the governance build only after every data, context and validation table for the release has been generated:

```bash
.venv/bin/python scripts/build_release_governance.py
node --expose-gc scripts/validate_release_governance_csv_artifacts.mjs
.venv/bin/python scripts/build_release.py
shasum -a 256 -c outputs/SHA256SUMS.txt
```

Running `build_release_governance.py` twice against identical upstream artifacts must reproduce identical manifest, gap-register, dictionary and validation bytes. The release packager separately fixes ZIP timestamps, permissions and member order.

## Interpretation boundary

Alpha.24 is a release-control milestone, not a scientific discovery milestone. The 2,784 candidate cells remain v0.6 reconnaissance hypotheses. None is field verified by KHANAN, and no row in this release establishes a reserve, resource, grade, current operating status, legal right, permission to enter land or drill target.
