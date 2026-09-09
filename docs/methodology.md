# KHANAN methodology and limitations

## 1. Design principle

The dataset has six distinct observation types:

1. **Factual georeferenced site records** — preserved from USGS MRDS with source IDs and source wording.
2. **Official inspection-table events** — IBM MCDR regional inspection records, with source wording and dates but without inferred production status or coordinates.
3. **Official abandoned-mine inventory records** — IBM's named 82-site historical-status list for reclamation context; coordinates and current status remain blank and the rows are excluded from scoring.
4. **Official aggregate resource inventory records** — IBM NMI 2025 national, grade/measure, and state/UT reserves/resources; coordinates remain blank and totals are not allocated to cells.
5. **Official critical-mineral auction events** — dated offer/result observations with source status, block names, states, minerals, concession types, bidders, and final offers where published. All tranche-I–VIII offer rows include source-published block footprints and document provenance; result-only rows retain blank geometry unless an offer lineage supplies a separate event row.
6. **Modeled area records** — approximately 36 km² H3 resolution-6 cells covering the India boundary. Cell centroids are indexing points, not proposed drill collars.

This separation prevents a predictive score from being presented as an observed deposit.

## 2. IBM National Mineral Inventory 2025

The Indian Bureau of Mines' *National Mineral Inventory at a Glance 2025*, Chapter 5, reports mineral-wise reserves and remaining resources as at 1 April 2025. The position-aware extractor preserves all 13 published numeric columns: UNFC 111, 121, 122, reserve total A, UNFC 211, 221, 222, 331, 332, 333, 334, remaining-resource total B, and total resources A+B.

The release contains 722 extracted rows across 45 mineral tables: 54 national-total rows, 206 source grade/measure rows, and 462 state/UT rows. Twenty-nine NMI source-mineral tables link to at least one material in the project's top-50 taxonomy. The output preserves ore versus contained-metal/compound rows instead of adding incomparable quantities.

Every extracted row is checked against all three identities: `A = 111 + 121 + 122`, `B = 211 + 221 + 222 + 331 + 332 + 333 + 334`, and `A+B = A + B`, using a scale-aware tolerance because IBM notes that figures are rounded. Seven visibly blank category cells are interpreted as zero only where the published subtotals validate that interpretation; the count is recorded per row. All 722 rows pass.

NMI state totals are contextual aggregates. They do not identify a deposit, imply prospectivity throughout a state, or provide a legal/economic mine status. They are excluded from model training and candidate scoring, and their latitude/longitude fields remain blank.

## 3. IBM regional MCDR inspection tables

IBM publishes MCDR inspection/report and violation-letter tables by regional office and financial year. The extract uses 36 verified official pages: FY 2025-26 pages where publicly discoverable, FY 2024-25 for offices without a discoverable 2025-26 table, and FY 2023-24 for Nagpur, whose later regional table was not publicly discoverable during this build. Together the pages cover all 14 IBM regional offices and yield 1,504 inspection-table event rows.

The event table preserves the financial year, office, source page/table/row, serial number, mine name, mine code, state/district, mineral, owner or lessee, inspection type/officer/date, violation/show-cause fields, exact page URL, source-page checksum, and all linked official row documents. Mine codes and hectare areas are parsed from mine-name text only when a strict format and unit are present, and each parsed value records its basis. Original date text is preserved. Five multi-day cells are not forced into a single date, while three apparent source-date anomalies remain parsed but are explicitly flagged as outside the labeled financial year.

The 1,353-row latest-inspected-mine view groups events by official mine code when available. Otherwise it uses a normalized regional-office, state, district, and mine-name key. This is a practical exact-text deduplication, not entity resolution; spelling changes can split one mine and generic repeated names can still collide.

Most importantly, an inspection record is not proof that a mine is producing, legally compliant, economically viable, or still active. The regional tables are not an exhaustive all-leases register. Summary pages provide no exact coordinates, so latitude/longitude remain blank and MCDR rows are excluded from prospectivity training and scoring.

## 4. IBM abandoned-mine inventory

IBM's public *List of 82 Abandoned Mine Sites Identified for Reclamation* is acquired reproducibly after establishing the portal's English-language session. The cached HTML source is hashed, and the extractor requires the exact 82-row serial sequence before publication. The page was last updated on 9 September 2026, but it does not state when the underlying site-identification study was conducted.

The source narrative distinguishes four quantities that must not be collapsed: 297 abandoned/orphaned sites were identified nationally; IBM identified 106 sites belonging to public-sector, major, and other private-sector companies as requiring reclamation or rehabilitation; 24 of those became operational again; and the published table lists the remaining 82. KHANAN therefore records the source classification and its scope but sets `current_legal_or_operational_status_verified=false` for every row.

All 82 rows preserve the official serial number, state wording, mine name, mineral wording, and earlier lessee. Three state spellings are normalized in a separate field, while the originals remain intact. Twenty-six mineral spellings are crosswalked to the v1 ontology, including transparent expansions of source abbreviations such as `Qtrz/felds` and `Pb-zn-cu`; the raw terms are never overwritten.

IBM publishes no district, latitude, longitude, mine code, lease polygon, closure date, or controlling current-status document on this page. Those fields remain blank, and every record is `excluded_context_only` for model evidence. Name-based geocoding would convert a guess into apparent evidence, so it is deliberately not performed. Earlier-lessee names are historical context, not assertions of current ownership or rights.

## 5. Official critical-mineral auction events

The auction table contains 199 event observations rather than pretending to be a deduplicated legal block register: all 143 non-superseded offer observations across tranches I–VIII and 56 successful preferred-bidder results through tranche VII. Offer counts reconcile exactly to the eight official tender lists: 20, 18, 7, 21, 15, 23, 19, and 20. The successful rows reconcile to the published tranche totals: 6, 4, 4, 10, 10, 12, and 10 for tranches I–VII. Mock-auction rows displayed by MSTC and two superseded block-summary files are explicitly excluded.

Every row retains a source date, exact source URL, tranche, offer/result event kind, status at that date, source mineral wording, normalized material links, and concession type. Where published, rows also preserve districts, bidders, numeric final offers, MSTC auction numbers, registration numbers, and IST start/close timestamps. Offer rows also retain MBS/NIT filenames, URLs, SHA-256 hashes, byte sizes, page counts, extraction methods, and qualification notes. A normalized `block_lineage_key` links repeated observations by locality after documented spelling and mineral-descriptor normalization; it is a convenience key, not legal entity resolution.

For all 143 offers, source-published corner coordinates and concession areas were extracted from linked MSTC mineral block summary PDFs, with documented official-NIT fallbacks where standalone summaries omit coordinate tables. Most tables publish WGS84 latitude/longitude; one explicitly published UTM table is transformed to WGS84. A two-part cluster is preserved as a MultiPolygon. The builder closes rings, derives representative centroids, computes ellipsoidal areas, and compares them with published areas. All 143 geometries are valid and the largest area difference is 4.64%.

Each centroid is also tested against the stated state/UT in the 2011 Census district boundary layer. Telangana rows are validated against undivided Andhra Pradesh because Telangana was not separate in that layer. One official Biarpalli coordinate table places an Odisha block near 89°E, outside Odisha; the source-published footprint is retained with `geometry_quality_flag=source_location_mismatch` rather than silently corrected. These geometries are useful for overlays but are excluded from prospectivity training and scoring to avoid treating auction inventory as independent occurrence evidence. Boundaries and auction/grant status must still be verified against controlling tender and legal documents before operational use.

The 143 offer observations reconstruct to 100 distinct published footprints. The tranche-VIII PIB release separately reports a cumulative total of 88 blocks offered. Because the event-level portal evidence does not reconcile to that aggregate, this release records the discrepancy and does not force unrelated footprints into a single lineage.

An auction offer or preferred-bidder result is not proof of production, final concession grant, resource/reserve quantity, grade, economic viability, clearance, or permission to enter land.

## 6. Spatial framework

The India land boundary is polyfilled with H3 resolution 6. A small number of coastal H3 cells containing valid source sites are added even when their centroid is outside the center-contained land polyfill. Each row retains `cell_boundary_wkt` and `grid_area_km2`; users should use the polygon rather than treating the centroid as the entire represented area.

District context uses 2011 boundaries to align with the latest completed published population census used in this release. The boundary repository itself documents geometry shifts and imperfections, so spatial joins carry quality flags where missing.

## 7. Known-site preparation

The global MRDS CSV was filtered to India, giving 781 source rows:

- 310 known mine/past-producer rows;
- 416 prospects/occurrences;
- 50 plants;
- 5 unknown-status rows.

All source records are retained in the factual CSV. Two records have coordinates outside expected India bounds and are explicitly flagged: `MRDS-10133908` and `MRDS-10231095`. They are excluded from model evidence.

Commodity text used by the v0.6 model is normalized to its 50-target set using anchored aliases and regular-expression rules. The v1 ontology build separately crosswalks raw MRDS commodity, ore, gangue, and other-material fields to typed entities while preserving the original wording. Normalized chemical names and symbols/formulae are emitted as JSON arrays. Where no chemical name is defensible—such as bulk coal or petroleum—the English material/form name is retained rather than inventing a single compound.

## 8. Environmental and human context

- **Climate:** NASA POWER daily UTC meteorology for 1 September 2025–31 August 2026, the twelve complete calendar months ending immediately before the release month. Daily T2M, T2M_MIN, T2M_MAX, PRECTOTCORR, RH2M, and WS2M values are aggregated into rolling-window summaries and month-labelled JSON arrays. All 3,120 native grid points have all 365 days for every parameter. Values are joined from the nearest native grid point; `climate_grid_distance_km` records the offset. NASA documents daily meteorology as available from 1981 to near real time in its [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/). NASA also notes that recent near-real-time products may later be superseded by long-term MERRA-2; all 96 raw regional files and their SHA256 checksums are preserved in `nasa_power_rolling_12m_validation.json`.
- **Population:** WorldPop 2020 unconstrained 1 km population pixels are summed inside each H3 cell. This is a modeled estimate, not a census.
- **Demographics:** Census 2011 district totals and derived shares are contextual attributes, not H3-cell counts. The CSV names each field with the `_2011_district` suffix.
- **Geology:** age, supergroup, group, stratigraphy, and map-unit ID are sampled at each centroid from the public Esri India feature service. The service metadata does not identify the polygon source, scale, or reuse license, so the release redistributes only sampled attributes and flags this limitation.
- **Terrain:** WorldClim 2.1 elevation, derived from SRTM, supplies centroid elevation and reconnaissance-scale slope/relief estimates.

## 9. NGDR/GSI service audit

The v1.0-alpha.3 pipeline establishes a public guest session at the National Geoscience Data Repository and audits the session-scoped WMS 1.1.1 and WFS 1.0.0 services used by the guest map. The 10 September 2026 audit observed 1,114 named WMS layers and 751 WFS feature types. Eleven nationally relevant feature types were selected across commodity occurrences, critical minerals, mineralization, stream-sediment and soil geochemistry, national soils, magnetics, gravity, lithology and regional geology.

For each selected layer, the pipeline records the WFS feature count, WGS84 bounding box, default SRS, declared geometry and non-geometry XML schema fields. A one-feature GeoJSON request verifies machine-readable access, but the public inventory contains no feature-property values. The selected services report 2,459,737 features in total; this is a live catalog count, not a count of unique samples, mines, deposits or model evidence. Ten capability bounding boxes are plausible WGS84 extents. The regolith layer publishes floating-point sentinel values in its western and southern bounds, so the numeric bounding columns are left blank and the raw capability values and quality flag are preserved separately.

The GSI Data Sharing and Accessibility Policy, 2019 distinguishes open viewing from registered download and includes non-transfer and third-party redistribution restrictions for supplied digital data. The WFS schemas also omit essential scientific metadata for several analytical layers, including definitive units, methods, detection limits, survey scale, reduction parameters and missing-value codes. KHANAN therefore publishes only the metadata audit in this release. Raw probes remain in the ignored local source cache and all NGDR feature values are excluded from training, validation and candidate ranking. The exact decision and admission gates are documented in [`ngdr_access_and_integration.md`](ngdr_access_and_integration.md).

## 10. Material ontology and model eligibility

The v1.0-alpha.2 ontology contains 230 unique, typed entities derived from material terms actually observed in the India source tables, plus the retained v0.6 targets. It contains 69 elements, 85 mineral species, and 76 other entities spanning ores, rocks, groups, mixtures, varieties, industrial materials, and energy commodities. Stable typed IDs prevent an element, ore, mineral species, and informal group from being silently treated as the same thing.

Identity is checked against three reference layers where applicable: the IUPAC periodic table for elements, the September 2026 IMA-CNMNC list for approved mineral species and formulae, and USGS Mineral Commodity Summaries 2026 for additional India commodity evidence. The parser recovered 6,048 rows from the IMA document's stated 6,239 valid species (96.94% document-row coverage); this does not mean all IMA species are inserted into KHANAN. Only source-relevant identities are admitted.

The source-term crosswalk audits 450 distinct terms from MRDS, IBM NMI, IBM MCDR, IBM abandoned-mine records, central critical-mineral auction records, and USGS MCS. It maps 443 (98.44%). Seven nonspecific terms—including `Metal`, `Stone`, and `Associated minerals`—remain explicitly unresolved. Co-occurrence alone is not used to assign a vague term to every other material in its source row.

Ranks 1–30 in the legacy target set reproduce India's official 2023 critical-mineral list. Ranks 31–50 are a project extension covering major battery, energy, metal, construction, fertilizer, ceramic, plastic-feedstock, and plastic-filler materials; they are not an official Government of India priority order. Individual rare-earth and platinum-group elements can have their own ontology identities while remaining members of an official aggregate group.

Ontology inclusion never confers model eligibility. The geospatial prediction columns remain limited to the 50 explicitly retained v0.6 targets until each additional entity has enough mapped evidence, a defensible deposit-process hypothesis, and spatial validation. Four legacy energy targets have no direct occurrences in the current nonfuel-focused source set and are retained only for compatibility.

Ontology arrays identify names, possible compounds, or representative forms; they do not assert assay, grade, recoverability, mineral processing route, or economic value at a site. Formulas are supplied only for elements, verified species, or defensible compounds. Otherwise the English names are preserved in arrays as requested.

## 11. Reconnaissance score

For a material with at least five mapped source records, cell score components are:

\[
S_{raw}=0.50G+0.35D+0.15N
\]

where:

- `G` is smoothed host-map-unit enrichment: material evidence count in a geologic unit relative to all known-site records in that unit, normalized at the material's 95th percentile;
- `D = exp(-distance_km / 100)` is decay from the nearest mapped record for that material;
- `N` is the number of material records within 100 km, normalized at the nationwide 95th percentile.

The score is multiplied by an evidence-support factor:

\[
W=0.4+0.6\min\left(1,\frac{\log(1+n)}{\log(21)}\right)
\]

and clipped to 0–1. Materials with one to four evidence records receive a low-support distance/density score (`0.80D + 0.20N`) but no candidate percentile. Materials with no mapped MRDS evidence receive no score.

The score is a relative reconnaissance index. It is **not a calibrated discovery probability**.

## 12. Spatial validation

Materials with at least 10 mapped India evidence records are evaluated with up to five GroupKFold splits grouped by H3 resolution-3 cells. Each fold trains the same score recipe on geographically separated evidence and compares held-out occurrences with a deterministic sample of grid cells more than 25 km from any catalog evidence.

Two metrics are published:

- pseudo-absence ROC AUC;
- held-out recall above the sampled background's 95th-percentile score.

The comparison cells are not confirmed barren, so these metrics measure catalog-ranking behavior, not economic discovery accuracy. Spatial clustering, duplicate/dependent source records, uneven exploration intensity, and missing deposits remain sources of bias.

In v0.1, 15 material models have at least 10 records and spatial validation results. Vanadium's holdout AUC was below the promotion threshold and is therefore not labeled as a candidate even when its raw score is high.

## 13. Candidate promotion rules

A cell is never promoted when it is within 5 km of any mapped source site. For all candidate classes, the top material must have at least 10 source records and the nearest same-material evidence must be more than 25 km and no more than 250 km away.

`priority_candidate` additionally requires:

- spatial holdout pseudo-absence ROC AUC ≥ 0.60;
- within-material percentile ≥ 0.995;
- score ≥ 0.50.

`high_priority_candidate` additionally requires:

- AUC ≥ 0.75;
- held-out recall at the background top 5% ≥ 0.20;
- percentile ≥ 0.999;
- score ≥ 0.55.

The national rank sorts passing candidates by validation AUC, then percentile, then score. Neighboring high-ranked H3 cells are usually one regional signal and should be dissolved/clustered before field planning.

## 14. Validation and quality controls

The release checks:

- unique record IDs and H3 IDs;
- required row counts;
- expected India coordinate bounds for source sites;
- district, geology, climate, and population join rates;
- exact rolling-weather period, 96 regional source files, 365 daily observations per parameter/native grid point, cached-file checksums, and plausible meteorological ranges;
- 199 official auction-event rows, all 143 non-superseded tranche-I–VIII offers, all 56 published successful results through tranche VII, exact event and concession counts by tranche, 143 valid offer footprints, document hashes, state-boundary quality flags, and polygon/source-area reconciliation;
- score range;
- 30 official critical aggregate targets and 50 retained v0.6 modeling targets;
- 82 unique IBM abandoned-mine inventory rows, contiguous source serials, all 26 material terms mapped, blank coordinates, source-page hash, and mandatory exclusion from model evidence;
- 230 unique typed ontology entities, 450 audited source terms, a 98.44% mapped-term rate, seven explicitly unresolved nonspecific terms, and 96.94% row recovery from the referenced IMA list;
- 45 IBM NMI 2025 mineral tables, unique extract IDs, and UNFC subtotal arithmetic for every inventory row;
- 36 IBM MCDR source pages, all 14 regional offices, unique event/latest-view IDs, date parsing and financial-year exceptions, blank coordinates, and explicit non-production/non-exhaustiveness flags;
- explicit record-level flags and source provenance.
- 1,114 named NGDR WMS layers, 751 WFS feature types, 11 selected-layer schemas and bounded probes, 2,459,737 reported selected-layer features, and mandatory exclusion of raw NGDR values from public outputs and model evidence.

Build-time results are written to `outputs/validation_report.json`. A passing report means the pipeline's structural checks passed; it does not validate mineral occurrence in the field.

## 15. What is required for a defensible discovery model

Before using the output to allocate exploration capital, add:

- authorized National Geoscience Data Repository geochemistry, geophysics, baseline geology, boreholes, and exploration reports;
- current Indian Bureau of Mines and state lease/working-mine registers, plus deposit-level NMI geometry where authorized;
- exact geometry and controlling legal/grant status for auction/exploration blocks not yet covered by the tranche-VIII summaries;
- multispectral/hyperspectral alteration indices and structural lineaments;
- deposit-type labels, grade/tonnage/depth, ore mineralogy, and negative/sterile drilling outcomes;
- accessibility, road/rail/port/power/water features;
- forests, protected areas, land tenure, clearances, displacement risk, and community-impact constraints;
- deposit-level rather than point-level deduplication;
- spatially and temporally independent validation, uncertainty calibration, and field confirmation.

The [National Geoscience Data Repository](https://geodataindia.gov.in/NGDR/register) is the most important next source, but its gated access and terms should be handled explicitly rather than bypassed.
