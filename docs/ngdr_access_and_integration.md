# NGDR/GSI access and integration decision

**Status: metadata audit completed for v1.0-alpha.3; feature values are not yet integrated or redistributed.**

KHANAN established a public guest session at the [National Geoscience Data Repository](https://geodataindia.gov.in/guestuser) and queried the session-scoped OGC proxy used by the guest map. The audit found 1,114 named WMS layers and 751 WFS feature types. Eleven nationally relevant layers were then checked with `DescribeFeatureType` and a bounded one-feature GeoJSON request.

The public `outputs/ngdr_service_inventory.csv` contains only service metadata: exact layer names, feature counts reported by WFS, bounding boxes, declared coordinate systems, geometry types, field names and XML schema types. It contains no GSI observation values. Raw capabilities, schemas, bounded probes and the policy PDF are cached under `sources/raw/ngdr_service_audit/`, which is excluded from Git and release bundles.

## Audited layers

| Evidence family | WFS feature type | Reported features | Declared geometry |
|---|---|---:|---|
| National commodity map | `cite:commodity_pan_india_mineral_map_ngdr` | 2,583 | Point |
| Critical-mineral occurrences | `cite:critical_mineral_gcs_ngdr` | 244 | Point |
| Mineralization | `cite:mineralization_gcs_ngdr` | 11,569 | Point |
| Stream-sediment geochemistry | `cite:stream_sediments_gcs_ngdr` | 510,641 | Point |
| C-horizon soil geochemistry | `cite:soil_c_horizon_gcs_ngdr` | 45,854 | Point |
| Regolith geochemistry | `cite:soil_regolith_gcs_ngdr` | 8,735 | Point |
| National soil map | `cite:india_soil` | 42,097 | MultiPolygon |
| Magnetics | `cite:magnetic_gcs_ngdr` | 716,352 | Point |
| Gravity | `cite:gravity_gcs_ngdr` | 756,405 | Point |
| Lithology | `cite:lithology_gcs_ngdr` | 360,702 | MultiPolygon |
| Regional geology | `cite:geology_2m_gcs_ngdr` | 4,555 | MultiPolygon |

Together the selected services report 2,459,737 features. This total is a live service inventory, not a count of documents parsed, unique samples, deposits, mines, or records admitted to KHANAN's model. Layer overlap and feature identity have not yet been resolved.

Ten selected layers publish plausible WGS84 bounding boxes. The regolith layer publishes `-3.4028235e+38` in its western and southern bounds, a common floating-point sentinel rather than a geographic coordinate. KHANAN preserves that service response in `bbox_raw_json`, leaves the four numeric bounding columns blank for that row, and sets an explicit coordinate-metadata flag.

## Publication decision

The [GSI Data Sharing and Accessibility Policy, 2019](https://geodataindia.gov.in/assets/Document_Pdf/4.%20Data%20Dissemination%20policy%202019.pdf) says on policy page 3 that regional and pre-competitive baseline data should be openly disseminated free of charge. The same page distinguishes data that may be viewed without registration from data downloadable through registered access and an online non-disclosure agreement.

Annexure III, policy pages 20–21, describes a limited, non-exclusive, non-transferable licence for thematic services. It permits value-added or derivative work with GSI acknowledgement but prohibits assigning or transferring supplied data or maps in whole or part. Annexure IV, policy page 22, says registered-user downloads must not be resold, transmitted or conveyed to a third party in full or part.

Those provisions do not establish a simple blanket right for KHANAN to mirror raw WFS features in a public GitHub release. The guest service's machine-readable schema also does not establish all analytical units, laboratory methods, detection limits, survey scale, reduction parameters or missing-value codes needed for defensible modelling.

KHANAN therefore applies the following conservative rule in v1.0-alpha.3:

- publish service metadata, schemas, counts, hashes and reproducible request instructions;
- keep raw GSI feature values in the ignored local cache;
- do not use NGDR feature values in prospectivity training, validation or candidate ranking;
- obtain dataset-specific reuse authority or written permission before raw redistribution;
- obtain authoritative method and unit documentation before interpreting concentrations or anomalies;
- acknowledge GSI conspicuously in any future permitted value-added product.

This is a project publication decision, not legal advice.

## Scientific admission gates

An NGDR layer may enter production features only after all applicable checks pass:

1. **Identity:** exact layer version, responsible GSI programme, source project and stable feature identifier are known.
2. **Coordinates:** CRS, survey positioning, precision, geometry validity, India coverage and duplicate handling are audited.
3. **Measurement meaning:** medium, sampling depth, fraction, laboratory method, analytical unit, detection limit, censored-value code and quality-control protocol are documented.
4. **Scale and processing:** survey spacing, map scale, magnetic/gravity corrections, interpolation and other transformations are documented.
5. **Access and reuse:** licence class, attribution wording, permitted derivatives and redistribution scope are documented for the exact dataset.
6. **Missingness:** null, zero, below-detection and not-analysed values remain distinguishable.
7. **Leakage:** inputs derived from known deposits, exploration targeting or later discoveries are separated from evaluation labels by space and time.
8. **Validation:** the feature adds out-of-region predictive value beyond geology, proximity and exploration-intensity controls.
9. **Release:** only permitted derivatives are published, with source version, hashes, transformation code and uncertainty.

## Reproduction

Run:

```bash
python scripts/audit_ngdr_services.py
```

The script first establishes the guest session, retrieves current WMS and WFS capabilities, checks the selected schemas and one bounded feature from each layer, writes the metadata inventory and validation report, and updates the source registry, data dictionary and release validation. The live service can change, so a later audit may report different layer or feature counts; changes must be reviewed rather than silently accepted.
