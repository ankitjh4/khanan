# KHANAN material ontology v1

## Scope

KHANAN alpha.23 publishes 254 normalized material entities observed in the project's India evidence sources or required to represent official Indian critical-mineral groups. The catalogue contains 69 elements, 89 mineral-species rows and 96 ores, rocks, mixtures, varieties, groups, industrial materials, chemical commodities and energy commodities.

The count is descriptive, not a target-driven inventory. A source synonym does not become a new entity merely to increase coverage, and inclusion does not imply that the material has a deposit, reserve, economic grade or validated prediction in India.

## Identity and authority

Each row in `india_material_ontology_v1.csv` has a stable, type-prefixed `material_id`. Identity is assigned under the following rules:

1. element names, symbols and atomic numbers follow the IUPAC periodic table;
2. mineral-species names, formulae and status are matched to the IMA-CNMNC master list when the parser recovers an exact name;
3. rocks, ores, mineral mixtures, varieties, industrial materials and commodity groups are explicitly typed as non-species entities;
4. official Indian critical-mineral aggregates and their named members are preserved separately; and
5. the 50 legacy v0.6 modeling targets retain their identities without granting model eligibility to other ontology rows.

The `ima_status` field is populated for 112 entities. This number exceeds the 89 `mineral_species` rows because some IUPAC element entities also have an approved native-element mineral entry in the IMA list. It must not be read as 112 independently observed Indian mineral species.

## Source-term crosswalk

`material_source_term_crosswalk_v1.csv` contains 611 distinct source/table/field/term combinations. Of these, 602 map to one or more controlled entities and nine remain unresolved because the terms are nonspecific process, commodity or associated-material labels. The mapping rate is 98.53%.

Mappings retain the original source term and the number of source rows carrying it. Those counts measure textual/source-record support, not geological abundance, tonnage, confidence or independence. A term may map to several entities when the source names an ore and its constituent elements or combines materials in one label.

The crosswalk currently audits terms from:

- USGS MRDS India records;
- IBM NMI 2025 resource tables;
- IBM MCDR inspection listings;
- IBM abandoned-mine inventory;
- IBM 2024 mineral-concession tables;
- IBM 2023–24 auction-granted concessions;
- IBM 2024 State Review occurrence geography;
- central critical-mineral auction block summaries; and
- USGS Mineral Commodity Summaries India rows.

## Alpha.23 reconciliation

The IBM State Review layer contributes 101 official source material terms. Alpha.23 maps all 101 and adds 21 source-observed entities that were previously absent or over-collapsed:

- Ball clay, Plastic clay and Fuller's earth as variable industrial clay classes;
- Calcareous shale, Shale, Sandstone, Slate, Dunite, Pyroxenite, Marble and Ultramafic rocks as rocks or industrial rock materials;
- Copper ore, Lead-zinc ore and Manganese ore as ore classes;
- Leucoxene, Nickeliferous chromite and Vanadiferous magnetite as mixture/ore terms rather than mineral species;
- Glass sand and Silica sand as specification-dependent industrial materials;
- Soapstone as a talc-rich rock/industrial material; and
- Diaspore as an exact IMA-listed mineral species with formula `AlO(OH)`.

This correction separates `diaspore` from the earlier broad kyanite-related grouping and separates `dunite` and `marble` from compositional proxy groups. Every added entity carries the IBM State Review source identifier in `evidence_source_ids_json`.

## Names and formulae

The ontology keeps identity fields separate:

- `english_names_json` contains the preferred English name;
- `chemical_names_json` contains an established chemical name only when one is meaningful;
- `symbols_or_formulae_json` contains element symbols or source/authority formulae;
- `aliases_json` contains alternate names attached to the same controlled entity; and
- `representative_ores_or_forms_json` contains examples without asserting equivalence.

Rocks, ores, mixtures and commodity groups often have no single chemical formula. Their chemical-name and formula arrays remain empty instead of inventing a composition. In the IBM occurrence table, `chemical_or_english_names_json` is assembled per mapped entity: it uses chemical names where available and the controlled English name for every entity without one.

## Model separation

Ontology coverage and prediction eligibility are independent. Alpha.23 still scores only the 50 retained v0.6 targets. The national grid and validation-gated candidate table retain their prior SHA-256 hashes, and the ontology validator checks those hashes on every rebuild.

The remaining 204 ontology entities are vocabulary and evidence-normalization records. They do not acquire prospectivity scores, training labels or candidate rankings by being present in the catalogue.

## Validation and reproduction

The machine-readable audit verifies unique identifiers and names, entity counts, IMA parser coverage, source hashes, crosswalk coverage, all 21 State Review additions, source attribution, all 101 State Review mappings and unchanged model artifacts. It is published as `outputs/material_ontology_validation_v1.json`.

Rebuild and inspect the layer from the repository root:

```bash
.venv/bin/python scripts/build_material_ontology.py
.venv/bin/python scripts/build_ibm_imyb_state_review_occurrences.py
node --expose-gc scripts/validate_material_ontology_csv_artifacts.mjs
```

The IMA and IBM inputs are hash-pinned locally by the build. Source licensing and access limitations are recorded in `outputs/source_registry.csv`.
