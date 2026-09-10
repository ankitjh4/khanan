# IBM Indian Minerals Yearbook 2024 State Review occurrence geography

## Scope

KHANAN alpha.22 introduced three machine-readable context layers from the mineral-occurrence prose in the Indian Bureau of Mines' *Indian Minerals Yearbook 2024* State Reviews. Alpha.23 reconciles every source material term with the central ontology. The reviewed section spans physical PDF pages 157–249 (printed pages 142–234), including continuation text on later pages. The pinned source file has SHA-256 `7e4cf991426ac8299ec0a365af68a05a8276f3b81ae2433fb6debd4358550354`.

The source is an official national compilation, not a uniform field survey. IBM states that the Yearbook is compiled internally from several divisions and other sources, advises readers to use discretion, and disclaims warranties. KHANAN therefore preserves this evidence as contextual geography and excludes it from model training, validation, scoring and candidate promotion.

## Outputs

`india_ibm_state_mineral_occurrences_2024.csv` contains 586 page-referenced rows across 31 source regions:

- 510 rows with source-published district lists;
- 44 rows with named fields, belts, basins, coalfields, talukas or other broad areas;
- 32 statewide rows where the chapter provides no finer occurrence geography.

The rows contain 101 distinct source material terms linked to 109 v1 ontology entities. Alpha.23 adds explicitly typed entries for six previously unresolved terms—`calcareous shale`, `leucoxene`, `sandstone`, `shale`, `slate` and `ultramafic rocks`—and corrects several over-broad mappings, including `diaspore`, `dunite` and `marble`. All 101 terms now resolve. Rocks, ores, mixtures and industrial-material classes retain controlled English names where no single chemical name exists.

`india_ibm_district_mineral_occurrences_2024.csv` explodes the district lists into 1,742 boundary-candidate rows. It preserves 352 distinct source-region/district terms and resolves 338 distinct 2011 boundary districts across 24 boundary states or territories. Every row includes the source term, matched 2011 name, crosswalk status, Census codes, a representative district point and selected district demographics.

`india_ibm_district_mineral_context_h3_r6.csv` is a sparse join table for 59,872 of the national grid's 88,857 cells (67.38%). Each included cell carries a compact district-profile key and summary counts; detailed material and provenance rows join through the containing 2011 state/district in the district occurrence table. This normalized design avoids repeating large arrays in every cell. An omitted cell means only that this source produced no admitted district join; it never means the material is absent.

## Administrative crosswalk

The State Reviews mix newer, older and alternate names. KHANAN matches normalized exact names first, then applies a reviewed crosswalk for cases such as Cuddapah → Y.S.R., Belagavi → Belgaum, Prayagraj → Allahabad and Pauri-Garhwal → Garhwal. Telangana districts are matched to undivided Andhra Pradesh because the boundary and Census framework is from 2011. Leh rows in the Jammu & Kashmir chapter are retained with an explicit administrative-vintage conflict.

Of 1,742 district candidate rows, 1,734 are unambiguous one-to-one matches and are admitted to the H3 context table. Eight rows arise from the historical parent names `24-Parganas` and `Midnapur`, each of which maps to two 2011 districts. Those candidate rows remain visible but are withheld from H3 propagation because the source text does not identify the relevant successor district.

The representative district latitude and longitude are interior indexing points calculated from the 2011 polygon. They are not mineral coordinates, discovery locations or proposed drill collars.

## Extraction and validation

The curated configuration records source regions, physical PDF pages, material terms and published place terms. The builder:

1. verifies the complete source PDF against the pinned SHA-256;
2. checks every curated material and place term against text extracted from the referenced pages;
3. expands shared-place material phrases without overwriting the source wording;
4. maps all 101 source terms to the 254-entity ontology and preserves English fallbacks per entity;
5. performs the explicit 2011 administrative crosswalk;
6. admits only one-to-one district matches to the H3 context layer;
7. joins existing H3 and district population fields without altering the national grid; and
8. verifies unique identifiers, parent linkage, H3 uniqueness and mandatory model exclusion.

The final audit reports zero unresolved source material terms, zero unmatched source district terms and zero unreviewed material/place text-presence exceptions. It retains the eight one-to-many boundary candidates as explicit withholds.

## Interpretation contract

These tables do not establish:

- an exact mine, deposit or discovery location;
- that a mineral occurs throughout a district or H3 cell;
- reserve/resource quantity, grade, continuity, depth or recoverability;
- current production, legal status, concession rights or permission to enter land;
- economic, environmental, social or archaeological feasibility; or
- an independent prediction or validation label.

The correct use is regional filtering and source-aware context. Any field programme must return to primary geological maps, survey reports, assays, controlling legal records and the relevant authorities and communities.

## Reproduction

From the repository root:

```bash
.venv/bin/python scripts/build_ibm_imyb_state_review_occurrences.py
.venv/bin/python scripts/plot_ibm_imyb_state_review_occurrences.py
```

The build configuration is `config/ibm_imyb_2024_state_review_occurrences.json`; the machine-readable audit is `outputs/ibm_imyb_state_review_occurrences_validation.json`.
