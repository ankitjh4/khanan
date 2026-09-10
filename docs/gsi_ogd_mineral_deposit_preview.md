# GSI OGD mineral-deposit preview layer

## Outcome

Alpha.21 recovers a machine-readable, coordinate-bearing subset of eight Geological Survey of India mineral-deposit catalogs from the Open Government Data Platform India. The catalogs cover bauxite, baryte, copper, diamond, gold, iron ore, lead-zinc and manganese and report **381 total rows**. The portal's public server-side preview exposes **78 first rows (20.472441%)**; those are the only deposit rows published by KHANAN in this release.

The layer adds GSI locality, state, Survey of India toposheet, source DMS latitude/longitude, commodity, host rock, deposit morphogenesis, formation and metallogenic province or belt. Source coordinate ranges are preserved and represented on the map by their arithmetic midpoint. No range is converted into a deposit boundary.

## Source and access contract

The exact catalog, resource, metadata, preview and workbook URLs are recorded in `outputs/gsi_ogd_mineral_deposit_catalog_audit.csv`. The catalog and resource pages are public and identify the Geological Survey of India under the Ministry of Mines as provider. OGD states that published datasets/resources and metadata are licensed under the [Government Open Data License - India](https://www.data.gov.in/godl).

The portal currently requires an interactive download-purpose form and CAPTCHA before it returns the source workbook. KHANAN does not bypass that control. Direct workbook metadata URLs returned HTTP 403 during the alpha.21 access audit. The public preview endpoint remained available without authentication and returned a reported total plus up to ten source rows. Baryte reported nine total rows but exposed eight preview rows; the discrepancy is retained rather than silently imputed.

Raw metadata and preview responses are cached under the ignored `sources/raw/gsi_ogd_deposit_preview/` directory. Their SHA-256 hashes are recorded in the validation artifact. Run:

```bash
.venv/bin/python scripts/build_gsi_ogd_deposit_preview.py --access-date 2026-09-10 --refresh
.venv/bin/python scripts/plot_gsi_ogd_deposit_preview.py
```

## Coordinate interpretation

- Exact DMS points are encoded in decimal degrees.
- Independent latitude or longitude ranges are preserved as minimum and maximum values; the arithmetic midpoint is used only as a representative mapping point.
- One lead-zinc latitude string omits an apparent range separator (`26 31 26 32N`). The parser records the source defect and its explicit two-endpoint interpretation in `data_quality_flags_json`.
- Iron and manganese source decimal fields are retained separately. They frequently encode the first range endpoint, so KHANAN does not substitute them for the derived midpoint.
- The source coordinate datum is not stated. `EPSG:4326` is an interoperability encoding, not a claim that GSI published WGS84.
- Representative points are checked against the 2011 district boundaries. Historical spellings such as `ORISSA`/Odisha and `CHATTISGARH`/Chhattisgarh are normalized only for the comparison; the source text remains unchanged.

## Cross-source comparison and model role

Each preview row is compared with the existing KHANAN known-site layer using great-circle distance to the nearest site and to the nearest site with a comparable material. Exact normalized locality-name overlap is also reported. These are diagnostics for likely source overlap, not entity-resolution proof.

The catalogs were published in 2013 and may incorporate the same historical geological knowledge represented by MRDS or other source compilations. Independence is therefore not demonstrated. The preview is also incomplete and selected by source order rather than randomly. Every GSI row is consequently excluded from v0.6 training, validation, scoring and candidate promotion. The national grid and validation-gated candidate hashes are checked before and after the build and must remain unchanged.

No row in this layer establishes a current mine, operating status, grade, tonnage, reserve, economic viability, access right or new discovery. A location without a nearby KHANAN known-site match must not be called undiscovered: the comparison layer is itself incomplete.
