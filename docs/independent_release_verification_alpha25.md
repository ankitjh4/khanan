# Alpha.25 independent release verification

## Purpose

Alpha.25 audits the portable KHANAN release as an external evaluator would. It does not add evidence, retrain a model, change a score or rank, promote a cell, or make a discovery claim. The national v0.6 grid and candidate files remain byte-identical to their frozen baselines.

The audit found that the Alpha.24 ZIP omitted five builders referenced by the release manifest, plus the source downloader, the workbook builder, the release packager, a PDF-rendering helper and `requirements-geospatial.txt`. Alpha.25 includes those files so the portable archive contains the declared build entry points and dependencies instead of relying on the surrounding Git checkout.

## Independent verifier

`scripts/verify_release_independent.py` uses only the Python standard library. It does not import `build_release.py`, `build_release_governance.py`, or any data-layer builder. Given the ZIP, it independently checks:

- safe, unique ZIP paths, CRC integrity, fixed timestamps, Unix `100644` permissions and deterministic deflate metadata;
- absence of redistributed source PDFs;
- presence of the requirements file, acquisition/build entry points, packager, verifier, documentation and public overview map;
- every manifest-declared CSV and GeoJSON, including byte hashes, schema hashes, row or feature counts, column or property counts, ordered primary keys, nonblank keys and key uniqueness;
- exact one-to-one data-dictionary coverage for every published CSV column in filename and source-column order;
- exact preservation of all 38 source-registry limitations in 38 source-specific gap rows, plus the 20 project-wide gaps;
- all five controlled evidence roles and the declared model-use boundaries;
- successful parsing and declared pass gates for every referenced validation JSON;
- false values in every explicit deposit, mine, legal or operational status-verification field;
- the frozen national-grid and candidate hashes, the candidate table as an exact subset of the grid, contiguous ranks, nonblank model disclosures, JSON material arrays and the mandatory field-validation flag; and
- explicit language that model outputs are hypotheses, not discoveries, reserves, grades or legal rights.

When a workspace path is supplied, the verifier also compares every ZIP member with the corresponding file in the source tree. When `SHA256SUMS.txt` is supplied, it recomputes every declared target it can resolve, including the ZIP and all manifest artifacts.

The machine-readable result is `outputs/independent_release_verification.json`. It is intentionally outside the ZIP and checksum inventory so the verifier can report on the completed bundle without creating a self-referential hash cycle.

## Reproduction

From the repository root, after rebuilding the release-governance artifacts:

```bash
.venv/bin/python scripts/build_release.py
shasum -a 256 -c outputs/SHA256SUMS.txt
.venv/bin/python scripts/verify_release_independent.py \
  --bundle outputs/india_mining_dataset_csv_bundle_v1.0-alpha.25.zip \
  --checksums outputs/SHA256SUMS.txt \
  --workspace . \
  --output outputs/independent_release_verification.json
```

Run the verifier without `--workspace` to test the bundle as a standalone archive. The repository comparison is an additional release-engineering check, not a requirement for downstream users.

## Interpretation boundary

A passing Alpha.25 verification means the declared files are structurally consistent, reproducibly packaged and explicit about their evidence roles and limitations. It does not independently confirm mineral occurrence in the field, completeness of public source coverage, economic extractability, resource or reserve estimates, current mine status, legal rights, environmental approval, community consent or safety. The 2,784 candidates remain model-generated reconnaissance hypotheses requiring qualified field and legal review.
