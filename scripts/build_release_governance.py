#!/usr/bin/env python3
"""Build KHANAN Alpha.24 release contracts and consolidated gap disclosure.

The release-artifact manifest freezes the schema of every published CSV plus
the public auction-footprint GeoJSON.  The coverage-gap register preserves one
row for every source-registry limitation and adds project-wide gaps that cannot
be represented by one source record.  Neither artifact changes model inputs,
scores, classes, ranks, or candidate promotion.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RELEASE_VERSION = "v1.0-alpha.24"
SCHEMA_FREEZE_STATUS = "frozen_for_v1.0-alpha.24"

MANIFEST_PATH = OUT / "release_artifact_manifest.csv"
GAP_PATH = OUT / "coverage_gap_register.csv"
VALIDATION_PATH = OUT / "release_governance_validation.json"
DICTIONARY_PATH = OUT / "data_dictionary.csv"
SOURCE_REGISTRY_PATH = OUT / "source_registry.csv"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"

BASELINE_GRID_SHA256 = "13307723efac1054666308c77b52ca0c93820a63ce535f578b23a294906136d9"
BASELINE_CANDIDATE_SHA256 = "f730ee1c72a72764c49e95b0cf1b29873df4e32f2ceed2610e534915c760cf04"

MANIFEST_FIELDS = [
    "artifact_id", "relative_path", "artifact_type", "release_version",
    "schema_version", "evidence_role", "role_definition", "model_use_status",
    "row_grain", "primary_key_columns_json", "primary_key_unique",
    "primary_key_blank_rows", "row_count", "column_count", "schema_sha256",
    "artifact_sha256", "artifact_sha256_status", "source_ids_json",
    "geographic_scope", "temporal_scope", "coordinate_or_geometry_fields_json",
    "uncertainty_fields_json", "exclusion_or_quality_fields_json",
    "license_or_access_basis", "schema_freeze_status", "schema_change_policy",
    "build_script", "validation_artifact", "limitations",
]

GAP_FIELDS = [
    "gap_id", "gap_level", "gap_categories_json", "evidence_family",
    "affected_source_id", "affected_artifacts_json", "geographic_scope",
    "temporal_scope", "gap_description", "quantitative_evidence",
    "scientific_or_operational_impact", "current_mitigation",
    "resolution_evidence_required", "model_effect", "alpha3_completion_effect",
    "status", "provenance_basis",
]

EXPECTED_SCHEMA_SHA256 = {
    "data_dictionary.csv": "d3199f2f05c96d572250fd918cc88453ee0e655e7ac4d570947cfc2667f65b6e",
    "gsi_ogd_mineral_deposit_catalog_audit.csv": "dc489394bda09e6dd13b4ddaf76ac16d986cc8289654628b9558bf82eb037516",
    "india_earthchem_geochemical_observations.csv": "766dbbcf11b5bee92f72f746f75c648111192250e99ca8489121043876764fbc",
    "india_earthchem_geochemical_samples.csv": "2c0f3cea17edc4762fb05ebc422e4b4191ce6e51d948b22916d421de29f6f30c",
    "india_emag2v3_magnetic_features_h3_r6.csv": "24b6174b0052fe7887c94b380f95c26c2ba5fc63dfa30a4689e1a344d5db7a9c",
    "india_gsi_ogd_mineral_deposit_preview.csv": "d982a47bb9692c0645d91586f7141cbc6997aed9af4699e7c1a91ddc11e16d03",
    "india_ibm_abandoned_mine_sites.csv": "f294cc6dbb8b6d498f81ee68d366b1381c0ae3656629f94c3d28940ad2e27b02",
    "india_ibm_auctioned_concession_geometries_2023_24.csv": "4b4dc7e6749e44a1c4a796197e40fd235c183b84dbe494f2eb079ea076971acb",
    "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv": "7c52ac748509382a5515c115441fa336a52a945ed5f4a0a8952f6ae0be050cac",
    "india_ibm_auctioned_concession_status_evidence_2023_24.csv": "14e9ff61ed649e0c0164048131adceba6c765132aa5dd4dbe9c674cd60db84f0",
    "india_ibm_auctioned_mineral_concessions_2023_24.csv": "f18a812591bb297e979a3d70f78c0bbbb6c650e9d2d55794a643ea58c5ad2582",
    "india_ibm_district_mineral_context_h3_r6.csv": "531009092be94967694abb7ebd6823413c7b3f98e75852740014e2bb93883b13",
    "india_ibm_district_mineral_occurrences_2024.csv": "67d046055ccfd534d32ae85ea65b0717c0ee7301889081206681ef375fe0ebda",
    "india_ibm_mcdr_inspection_events_2023_2026.csv": "06a3d8a4464b508d00f3fe146f64e987e5381c614a4a46ecbc16cf08ed4c0ddf",
    "india_ibm_mcdr_latest_inspected_mines.csv": "c07eab55a51ed59bbf532d8121f78edd8eb116661c9b00692bf9b0da2a7f86e0",
    "india_ibm_mining_lease_distribution_2024.csv": "44703321c71d649510d80a5c982a85f1aebaa06356849fd385167bcdccd48b24",
    "india_ibm_nmi_2025_resource_inventory.csv": "7e233f3f20081456e84afaed4fadde44adaa08f318476283477d624701e50dd7",
    "india_ibm_state_mineral_occurrences_2024.csv": "54479dea824ceb474dd214f796e1870bb187d445215aa1f60f854a2b4c329960",
    "india_known_mining_sites.csv": "54641ba4f03383ef6ada476c1cffb00abe608ae581147114eb2630d92a535a79",
    "india_material_ontology_v1.csv": "44a02e13cef8f02996f8333c42211908aa6a78ad776a91c400a65e7b38559f9a",
    "india_mining_candidate_areas_validation_gated.csv": "70c85fd1fcb0fd8aaea0a4a13773d7a8ea6b6a7ab19d6e669efc34fb4e935827",
    "india_mining_prospectivity_grid_h3_r6.csv": "70c85fd1fcb0fd8aaea0a4a13773d7a8ea6b6a7ab19d6e669efc34fb4e935827",
    "india_official_critical_mineral_blocks.csv": "910296e2e96b117b9e63ca9eaf902a10b1e6caa1513eb1a6ce1a46f5e1edf095",
    "india_official_critical_mineral_mbs_manifest.csv": "aa90f3e288e53b52b544abf2a5928dc0cf00e2447e87e899d76f13c95dbc9d26",
    "india_sentinel2_scene_manifest_2025.csv": "81d11b8850865cf71209e5984d50c9115df31f8974dc45e76f34d76b5c6ed190",
    "india_sentinel2_surface_context_h3_r6.csv": "4e301c8f9362bc200b551e477af33033207edb237fc22c0aefc564dea1559b3a",
    "india_soilgrids_v2_soil_features_h3_r6.csv": "503235d8d23c200e263d84c9bc1a75cc7960db953532136fc0d783b885f675be",
    "india_strategic_materials_top50.csv": "6b55aacea9e4ca89f2b48e6f0089450f00fb31f61341e2ca24e7f9c4cc440328",
    "material_emag2_spatial_ablation.csv": "080800a68d84e0526971363eb09bcc0706353682c3617719a9f3f688064ac3d2",
    "material_emag2_spatial_ablation_folds.csv": "9113786539cd275f5bea8bfee0d255371cd9a1e37dc3ec59a2a16c597d2955b7",
    "material_model_support.csv": "20de1fe6f544066530e2bfdd3fadf75f7a6ab6167d26af1bab093fda59e9ed1e",
    "material_model_validation.csv": "e86bff570d2ad8dcdc2518c59f866b1505af65dd30a553c96cad569c8fd276b3",
    "material_official_block_transfer_validation.csv": "ee0cf2e04459dbd5ea2ee03941889a16c95dd2b1d89dd656be3625c22a50151b",
    "material_sentinel2_spatial_ablation.csv": "0cb77e6ba5f3d6fb2f0e1ef697638a0579df4875bc5df7f6d5066cce4597326d",
    "material_sentinel2_spatial_ablation_folds.csv": "db4e9c0e84c24b32104e74b6ffff8f8deb7da5d4802d7583538457fefc06f8b7",
    "material_soilgrids_spatial_ablation.csv": "9b6bed400635771c4e138657523e94163fc2e68aaa20cfb9d82c1799a6d0ea05",
    "material_soilgrids_spatial_ablation_folds.csv": "f1e609ac4a0d446ad74aff169fb173a1b15ef315f9da1dd9ec283ab39ce08bfb",
    "material_source_term_crosswalk_v1.csv": "fc1f1088fc1d2c1b79e652e8f0eaa45ab90f1f9ad8c056a2afe9bf0c087a80bf",
    "ngdr_service_inventory.csv": "127fcab299e71e3f74308c5b13a0045f765abeb7dde2f79418ed3e23c10eb373",
    "official_block_transfer_observations.csv": "0d4092e83f8bb52b39148122d7fcd7ab89ea681406d21c4d802ecb652885b876",
    "source_registry.csv": "7aa820863f0b3935d8d85456d7e4b80e9a693adec774d46173e4d7ec13b42185",
    "coverage_gap_register.csv": "380363c525e34cba0c48a13803cc00de030b3cdb6c26d6bf420aca4819635672",
    "release_artifact_manifest.csv": "724eb57b334fb2a01f1361ff4249eb304ad3b359ecf447a36d5379679db71e3c",
    "india_ibm_auctioned_concession_geometries_2023_24.geojson": "8c8e207e26380212c8b6fcfa277ab85af2caad671ee2082eb84babec3cbead03",
}

ROLE_DEFINITIONS = {
    "observed_source_evidence": "Source-reported observation, event, inventory, sample, catalogue row, or reviewed footprint; not automatically a model label or current-status fact.",
    "contextual_feature": "Derived spatial or environmental context excluded from production scoring unless a separate admission test passes.",
    "model_hypothesis": "Model-generated reconnaissance output; not a probability, discovery, reserve, resource, grade, legal right, or drill target.",
    "validation_evidence": "Holdout, ablation, transfer, support, or quality-control evidence used to evaluate a model or source family.",
    "metadata_governance": "Ontology, provenance, schema, source, access, limitation, or release-control metadata; not geological evidence.",
}


def contract(key: list[str], role: str, model_use: str, grain: str,
             geography: str, temporal: str, builder: str, validation: str,
             limitations: str) -> dict[str, Any]:
    return {
        "key": key, "role": role, "model_use": model_use, "grain": grain,
        "geography": geography, "temporal": temporal, "builder": builder,
        "validation": validation, "limitations": limitations,
    }


CONTRACTS = {
    "coverage_gap_register.csv": contract(["gap_id"], "metadata_governance", "metadata_only", "One explicitly disclosed source-specific or project-wide coverage gap.", "India or stated source scope", "Mixed; stated per row", "scripts/build_release_governance.py", "outputs/release_governance_validation.json", "A disclosed gap is not evidence that every unknown limitation has been discovered."),
    "data_dictionary.csv": contract(["table", "column"], "metadata_governance", "metadata_only", "One published CSV column definition.", "Not spatial", "Release snapshot", "scripts/build_release_governance.py", "outputs/release_governance_validation.json", "Definitions describe the current release schema and do not replace source documentation."),
    "gsi_ogd_mineral_deposit_catalog_audit.csv": contract(["catalog_record_id"], "metadata_governance", "metadata_only", "One audited GSI/OGD mineral-deposit catalogue.", "India; eight commodity catalogues", "2013 catalogues; access snapshot 2026-09-10", "scripts/build_gsi_ogd_deposit_preview.py", "outputs/gsi_ogd_mineral_deposit_preview_validation.json", "Public previews expose only 78 of 381 reported catalogue rows."),
    "india_earthchem_geochemical_observations.csv": contract(["observation_id"], "observed_source_evidence", "context_only_excluded_from_v0.6", "One published sample, analytical scope, sequence, and parameter observation.", "Two western-Assam coordinate sites", "Published 2026; source analytical campaigns", "scripts/build_earthchem_geochemistry.py", "outputs/earthchem_geochemical_validation.json", "Targeted samples are not a systematic regional survey or discovery evidence."),
    "india_earthchem_geochemical_samples.csv": contract(["record_id"], "observed_source_evidence", "context_only_excluded_from_v0.6", "One coordinate-bearing published EarthChem sample.", "Two western-Assam coordinate sites", "Published 2026; source analytical campaigns", "scripts/build_earthchem_geochemistry.py", "outputs/earthchem_geochemical_validation.json", "Thirteen targeted samples cannot establish regional continuity, resources, or economic viability."),
    "india_emag2v3_magnetic_features_h3_r6.csv": contract(["h3_r6"], "contextual_feature", "excluded_after_spatial_ablation", "One India H3 resolution-6 cell.", "National H3 grid", "Static EMAG2v3 source snapshot", "scripts/build_emag2_features.py", "outputs/emag2v3_magnetic_features_validation.json", "Four-kilometre upward-continued anomaly is broad context and has source gaps."),
    "india_gsi_ogd_mineral_deposit_preview.csv": contract(["record_id"], "observed_source_evidence", "excluded_from_training_validation_and_scoring", "One row exposed by a public GSI/OGD preview endpoint.", "India; eight commodity catalogues", "2013 catalogues; preview accessed 2026-09-10", "scripts/build_gsi_ogd_deposit_preview.py", "outputs/gsi_ogd_mineral_deposit_preview_validation.json", "The 20.47% preview is incomplete, non-random, and not knowledge-independent."),
    "india_ibm_abandoned_mine_sites.csv": contract(["record_id"], "observed_source_evidence", "context_only_no_coordinates", "One IBM abandoned-mine inventory row.", "Published state and district names; no coordinates", "Portal snapshot last updated 2026-09-09", "scripts/build_ibm_abandoned_mines.py", "outputs/ibm_abandoned_mines_validation.json", "Published abandoned status does not prove current legal or operating status."),
    "india_ibm_auctioned_concession_geometries_2023_24.csv": contract(["record_id"], "observed_source_evidence", "context_and_transfer_validation_only", "One admitted State Mine Block Summary footprint.", "Ten relevant States; 67 admitted footprints", "IBM 2023-24 table and reviewed portal documents", "scripts/build_ibm_auction_mbs_geometry_2023_24.py", "outputs/ibm_auction_mbs_geometry_validation.json", "Admission verifies geometry consistency, not current operation, title, resource, reserve, or grade."),
    "india_ibm_auctioned_concession_geometries_2023_24.geojson": contract(["record_id"], "observed_source_evidence", "context_and_transfer_validation_only", "One admitted State Mine Block Summary polygon feature.", "Ten relevant States; 67 admitted footprints", "IBM 2023-24 table and reviewed portal documents", "scripts/build_ibm_auction_mbs_geometry_2023_24.py", "outputs/ibm_auction_mbs_geometry_validation.json", "Polygon admission does not establish legal or operational status."),
    "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv": contract(["record_id"], "validation_evidence", "source_geometry_audit_only", "One IBM auction row and its reviewed State MBS selection outcome.", "Ten relevant States", "IBM 2023-24 table and portal snapshot", "scripts/build_ibm_auction_mbs_geometry_2023_24.py", "outputs/ibm_auction_mbs_geometry_validation.json", "Twenty-five selected documents are withheld and five Andhra rows lack an exact current public boundary match."),
    "india_ibm_auctioned_concession_status_evidence_2023_24.csv": contract(["record_id"], "observed_source_evidence", "context_only_no_geometry", "One block and dated official-secondary status evidence record.", "Andhra Pradesh; five IBM rows", "Dated source snapshots through 2026", "scripts/build_ibm_auction_status_evidence_2023_24.py", "outputs/ibm_auction_status_evidence_2023_24_validation.json", "Historical events do not prove current legal or operational status."),
    "india_ibm_auctioned_mineral_concessions_2023_24.csv": contract(["record_id"], "observed_source_evidence", "context_only", "One IBM 2023-24 auction-granted concession row.", "India; State-level named blocks", "2023-24 reporting year", "scripts/build_ibm_mineral_concessions_2024.py", "outputs/ibm_mineral_concessions_2024_validation.json", "The compilation has no coordinates and is not a controlling current-status register."),
    "india_ibm_district_mineral_context_h3_r6.csv": contract(["h3_r6"], "contextual_feature", "excluded_from_v0.6_scoring", "One H3 cell inheriting admitted 2011-district occurrence context.", "Selected 2011 districts with IBM State Review terms", "IBM 2024 State Reviews; 2011 boundaries", "scripts/build_ibm_imyb_state_review_occurrences.py", "outputs/ibm_imyb_state_review_occurrences_validation.json", "District inheritance is not an exact occurrence location or evidence of uniform mineralization."),
    "india_ibm_district_mineral_occurrences_2024.csv": contract(["record_id"], "observed_source_evidence", "context_crosswalk_only", "One source occurrence and candidate 2011-district crosswalk.", "India; 2011 district crosswalk", "IBM 2024 State Reviews; mostly 2020-04-01 resource basis", "scripts/build_ibm_imyb_state_review_occurrences.py", "outputs/ibm_imyb_state_review_occurrences_validation.json", "Eight one-to-many historical district matches are withheld from H3 propagation."),
    "india_ibm_mcdr_inspection_events_2023_2026.csv": contract(["record_id"], "observed_source_evidence", "context_only_no_coordinates", "One IBM regional inspection-table event row.", "Fourteen IBM regional offices; published district names", "Fiscal years 2023-24 to 2025-26", "scripts/build_ibm_mcdr_inspections.py", "outputs/ibm_mcdr_inspection_validation.json", "Inspection presence does not prove production, compliance, exact location, or current legal status."),
    "india_ibm_mcdr_latest_inspected_mines.csv": contract(["record_id"], "observed_source_evidence", "context_only_no_coordinates", "One resolved mine identity retaining its latest published inspection event.", "Fourteen IBM regional offices; published district names", "Fiscal years 2023-24 to 2025-26", "scripts/build_ibm_mcdr_inspections.py", "outputs/ibm_mcdr_inspection_validation.json", "Name/code identity resolution is incomplete and rows lack coordinates."),
    "india_ibm_mining_lease_distribution_2024.csv": contract(["record_id"], "observed_source_evidence", "aggregate_context_only", "One state, mineral, sector, or area-band lease aggregate.", "India and State/UT aggregates", "As at 2024 source reference", "scripts/build_ibm_mineral_concessions_2024.py", "outputs/ibm_mineral_concessions_2024_validation.json", "Aggregates are not exact lease locations or proof of any individual lease status."),
    "india_ibm_nmi_2025_resource_inventory.csv": contract(["record_id"], "observed_source_evidence", "aggregate_context_only", "One mineral, geography, grade, and UNFC aggregate row.", "National and State/UT aggregates", "Resources mainly as at 2020-04-01", "scripts/build_ibm_nmi2025.py", "outputs/ibm_nmi_2025_extraction_validation.json", "Aggregate resources cannot be assigned uniformly to a state or interpreted as site-level grade."),
    "india_ibm_state_mineral_occurrences_2024.csv": contract(["record_id"], "observed_source_evidence", "context_only", "One source region, material term, and geography-scope occurrence row.", "31 source regions", "IBM 2024 State Reviews; mixed underlying dates", "scripts/build_ibm_imyb_state_review_occurrences.py", "outputs/ibm_imyb_state_review_occurrences_validation.json", "Occurrence prose is not a mine, assay, reserve, legal-status, or discovery register."),
    "india_known_mining_sites.csv": contract(["record_id"], "observed_source_evidence", "training_evidence_with_source_quality_controls", "One public-source mine, prospect, occurrence, or past-producer record.", "India selection; 779 of 781 coordinates in expected bounds", "Historical MRDS records with mixed source dates", "scripts/build_dataset.py", "outputs/validation_report.json", "MRDS is incomplete, partly historical, and has variable point precision and status currency."),
    "india_material_ontology_v1.csv": contract(["material_id"], "metadata_governance", "ontology_only_no_automatic_model_eligibility", "One typed material entity.", "Not spatial", "Authority snapshots through 2026-09", "scripts/build_material_ontology.py", "outputs/material_ontology_validation_v1.json", "Ontology inclusion does not establish occurrence in India or prediction eligibility."),
    "india_mining_candidate_areas_validation_gated.csv": contract(["h3_r6"], "model_hypothesis", "production_model_output_v0.6", "One H3 cell that passes published candidate-promotion gates.", "National H3 grid; promoted subset", "Feature reference periods vary; model v0.6", "scripts/build_dataset.py", "outputs/validation_report.json", "Scores are uncalibrated reconnaissance indices for 50 targets and are not discoveries or drill targets."),
    "india_mining_prospectivity_grid_h3_r6.csv": contract(["h3_r6"], "model_hypothesis", "production_model_output_v0.6", "One H3 resolution-6 cell covering India.", "National H3 grid; 88,857 cells", "Feature reference periods vary; model v0.6", "scripts/build_dataset.py", "outputs/validation_report.json", "Only supported materials receive scores; context layers failing admission remain excluded from rankings."),
    "india_official_critical_mineral_blocks.csv": contract(["record_id"], "observed_source_evidence", "context_and_transfer_validation_only", "One central critical-mineral auction offer or result event.", "India; official named auction blocks", "Tranches 1-8 and results through source snapshots", "scripts/build_official_blocks.py", "outputs/official_critical_blocks_validation.json", "Auction events do not prove production, final grant, resource, reserve, or access rights."),
    "india_official_critical_mineral_mbs_manifest.csv": contract(["event_id"], "observed_source_evidence", "geometry_source_manifest_only", "One auction-offer event and its MBS/notice document lineage.", "India; central critical-mineral auction blocks", "Tranches 1-8", "scripts/build_official_mbs_inventory.py", "outputs/official_critical_blocks_validation.json", "Document availability and geometry checks do not establish current legal status."),
    "india_sentinel2_scene_manifest_2025.csv": contract(["season_id", "scene_item_id"], "observed_source_evidence", "surface_context_lineage_only", "One selected Sentinel-2 scene per fixed season and MGRS tile.", "475 India-relevant MGRS tiles per season", "Two fixed 2025 seasons", "scripts/build_sentinel2_surface_context.py", "outputs/sentinel2_surface_context_validation.json", "Scene selection and provider metadata do not establish mineral presence."),
    "india_sentinel2_surface_context_h3_r6.csv": contract(["h3_r6"], "contextual_feature", "excluded_after_spatial_ablation", "One national H3 cell with two-season surface summaries.", "National H3 grid", "Two fixed 2025 seasons", "scripts/build_sentinel2_surface_context.py", "outputs/sentinel2_surface_context_validation.json", "Multispectral proxies are non-specific and can encode post-discovery disturbance or confounders."),
    "india_soilgrids_v2_soil_features_h3_r6.csv": contract(["h3_r6"], "contextual_feature", "excluded_after_spatial_ablation", "One national H3 cell with modeled soil properties at two depths.", "National H3 grid", "SoilGrids 2.0 model snapshot", "scripts/build_soilgrids_features.py", "outputs/soilgrids_v2_soil_features_validation.json", "Global modeled soil predictions are not India field assays or ore geochemistry."),
    "india_strategic_materials_top50.csv": contract(["material_name"], "metadata_governance", "model_target_registry_v0.6", "One retained strategic modeling target.", "Not spatial", "Project v0.6 target definition", "scripts/build_dataset.py", "outputs/validation_report.json", "Target inclusion does not imply sufficient evidence, a score, or an occurrence in every region."),
    "material_emag2_spatial_ablation.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material-level paired baseline versus EMAG2 result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_emag2_spatial_ablation.py", "outputs/emag2_spatial_ablation_validation.json", "No material passed the predefined admission gate."),
    "material_emag2_spatial_ablation_folds.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material and held-out spatial fold result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_emag2_spatial_ablation.py", "outputs/emag2_spatial_ablation_validation.json", "Fold estimates are not independent discoveries or calibrated probabilities."),
    "material_model_support.csv": contract(["material_name"], "validation_evidence", "model_support_metadata", "One target material support and validation summary.", "India model evidence", "Model v0.6", "scripts/build_dataset.py", "outputs/validation_report.json", "Sparse positives and pseudo-absence evaluation limit generalization."),
    "material_model_validation.csv": contract(["material_name"], "validation_evidence", "model_validation_metadata", "One target material spatial-validation summary.", "India spatial folds", "Model v0.6", "scripts/build_dataset.py", "outputs/validation_report.json", "Pseudo-absence metrics do not establish deposit probability or economic value."),
    "material_official_block_transfer_validation.csv": contract(["record_id"], "validation_evidence", "independent_transfer_diagnostic_only", "One target-material official-block transfer summary.", "Accepted official footprints across India", "Auction source snapshots through Alpha.20", "scripts/evaluate_official_block_transfer.py", "outputs/official_block_transfer_validation.json", "No material passed every gate and source-label independence remains unresolved."),
    "material_sentinel2_spatial_ablation.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material-level paired baseline versus Sentinel-2 result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_sentinel2_spatial_ablation.py", "outputs/sentinel2_spatial_ablation_validation.json", "No material passed all support, coverage, uncertainty, recall, and leakage gates."),
    "material_sentinel2_spatial_ablation_folds.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material and held-out spatial fold result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_sentinel2_spatial_ablation.py", "outputs/sentinel2_spatial_ablation_validation.json", "Fold estimates remain conditional on sparse historical labels."),
    "material_soilgrids_spatial_ablation.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material-level paired baseline versus SoilGrids result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_soilgrids_spatial_ablation.py", "outputs/soilgrids_spatial_ablation_validation.json", "No material passed the predefined admission gate."),
    "material_soilgrids_spatial_ablation_folds.csv": contract(["record_id"], "validation_evidence", "feature_admission_test_only", "One material and held-out spatial fold result.", "Purged India H3 r3 spatial folds", "Experiment v0.1", "scripts/evaluate_soilgrids_spatial_ablation.py", "outputs/soilgrids_spatial_ablation_validation.json", "Fold estimates do not make modeled soil values field measurements."),
    "material_source_term_crosswalk_v1.csv": contract(["source_id", "source_table", "source_field", "source_term"], "metadata_governance", "ontology_mapping_only", "One distinct source, table, field, and source-term mapping.", "Not spatial", "Source snapshots through Alpha.23", "scripts/build_material_ontology.py", "outputs/material_ontology_validation_v1.json", "Nine nonspecific terms remain deliberately unresolved."),
    "ngdr_service_inventory.csv": contract(["layer_id"], "metadata_governance", "catalog_metadata_only", "One selected NGDR OGC layer schema and availability audit row.", "Nominally national layers", "Guest service snapshot 2026-09-09", "scripts/audit_ngdr_services.py", "outputs/ngdr_service_validation.json", "Feature values are not redistributed or modeled because reuse and method/unit metadata remain unresolved."),
    "official_block_transfer_observations.csv": contract(["record_id"], "validation_evidence", "independent_transfer_diagnostic_only", "One official footprint and normalized target-material observation.", "Accepted official footprints across India", "Auction source snapshots through Alpha.20", "scripts/evaluate_official_block_transfer.py", "outputs/official_block_transfer_validation.json", "Official targeting is not proven independent of all prior geological knowledge."),
    "release_artifact_manifest.csv": contract(["artifact_id"], "metadata_governance", "metadata_only", "One published CSV or GeoJSON release artifact.", "India release scope or stated artifact scope", "Alpha.24 release snapshot", "scripts/build_release_governance.py", "outputs/release_governance_validation.json", "The manifest self-row uses the external SHA256SUMS file because a file cannot contain its own content hash."),
    "source_registry.csv": contract(["source_id"], "metadata_governance", "metadata_only", "One external source or source family.", "Varies by source", "Varies by source", "scripts/build_dataset.py and layer builders", "outputs/release_governance_validation.json", "Registry notes summarize, but do not supersede, provider terms or source documentation."),
}

BASE_SOURCES = [
    "SRC_USGS_MRDS", "SRC_ESRI_INDIA_GEOLOGY", "SRC_CENSUS_PCA_2011",
    "SRC_CENSUS_A01_2011", "SRC_DATAMEET_DISTRICTS_2011",
    "SRC_DATAMEET_INDIA_BOUNDARY", "SRC_NASA_POWER_ROLLING_12M",
    "SRC_WORLDPOP_2020", "SRC_WORLDCLIM_ELEV", "SRC_INDIA_CRITICAL_2023",
]
CRITICAL_BLOCK_SOURCES = [
    "SRC_PIB_CRITICAL_BLOCKS_T1", "SRC_PIB_CRITICAL_BLOCKS_T5",
    "SRC_PIB_CRITICAL_RESULTS_T1", "SRC_PIB_CRITICAL_RESULTS_T2_T3",
    "SRC_PIB_CRITICAL_RESULTS_T4_A", "SRC_PIB_CRITICAL_RESULTS_T4_B",
    "SRC_MSTC_CRITICAL_RESULTS_T6_T7", "SRC_PIB_CRITICAL_BLOCKS_T8",
    "SRC_MSTC_CRITICAL_MBS_T1_T8", "SRC_MSTC_CRITICAL_NIT_T1_T8",
]
STATIC_SOURCE_IDS = {
    "india_known_mining_sites.csv": BASE_SOURCES,
    "india_mining_prospectivity_grid_h3_r6.csv": BASE_SOURCES,
    "india_mining_candidate_areas_validation_gated.csv": BASE_SOURCES,
    "india_strategic_materials_top50.csv": BASE_SOURCES,
    "material_model_support.csv": BASE_SOURCES,
    "material_model_validation.csv": BASE_SOURCES,
    "india_official_critical_mineral_blocks.csv": CRITICAL_BLOCK_SOURCES,
    "india_official_critical_mineral_mbs_manifest.csv": CRITICAL_BLOCK_SOURCES,
    "material_emag2_spatial_ablation.csv": BASE_SOURCES + ["SRC_NOAA_EMAG2V3"],
    "material_emag2_spatial_ablation_folds.csv": BASE_SOURCES + ["SRC_NOAA_EMAG2V3"],
    "material_soilgrids_spatial_ablation.csv": BASE_SOURCES + ["SRC_ISRIC_SOILGRIDS_V2"],
    "material_soilgrids_spatial_ablation_folds.csv": BASE_SOURCES + ["SRC_ISRIC_SOILGRIDS_V2"],
    "material_sentinel2_spatial_ablation.csv": BASE_SOURCES + ["SRC_COPERNICUS_SENTINEL2_L2A_PC"],
    "material_sentinel2_spatial_ablation_folds.csv": BASE_SOURCES + ["SRC_COPERNICUS_SENTINEL2_L2A_PC"],
    "material_official_block_transfer_validation.csv": BASE_SOURCES + CRITICAL_BLOCK_SOURCES + ["SRC_MSTC_STATE_MBS_IBM_AUCTIONS_2023_24"],
    "official_block_transfer_observations.csv": BASE_SOURCES + CRITICAL_BLOCK_SOURCES + ["SRC_MSTC_STATE_MBS_IBM_AUCTIONS_2023_24"],
    "india_ibm_auctioned_concession_geometries_2023_24.geojson": ["SRC_IBM_INDIAN_MINERALS_YEARBOOK_2024_CONCESSIONS", "SRC_MSTC_STATE_MBS_IBM_AUCTIONS_2023_24"],
}


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=isinstance(value, dict), allow_nan=False)


def cross_gap(gap_id: str, categories: list[str], family: str,
              artifacts: list[str], geography: str, temporal: str,
              description: str, quantitative: str, impact: str,
              mitigation: str, resolution: str, model_effect: str,
              basis: str) -> dict[str, str]:
    return {
        "gap_id": gap_id, "gap_level": "project_wide",
        "gap_categories_json": jdump(categories), "evidence_family": family,
        "affected_source_id": "", "affected_artifacts_json": jdump(artifacts),
        "geographic_scope": geography, "temporal_scope": temporal,
        "gap_description": description, "quantitative_evidence": quantitative,
        "scientific_or_operational_impact": impact, "current_mitigation": mitigation,
        "resolution_evidence_required": resolution, "model_effect": model_effect,
        "alpha3_completion_effect": "must_remain_disclosed_in_final_coverage_audit",
        "status": "open_scope_limitation", "provenance_basis": basis,
    }


CROSS_CUTTING_GAPS = [
    cross_gap("GAP-PROJECT-001", ["material_coverage", "model_support"], "material ontology and prediction eligibility", ["india_material_ontology_v1.csv", "india_strategic_materials_top50.csv", "material_model_support.csv"], "India", "Alpha.24 snapshot", "Ontology coverage is much broader than prediction eligibility and validated scoring support.", "254 ontology entities; 50 model targets; 34 with MRDS evidence; 20 with percentiles; 15 spatially validated; 14 passing minimum holdout AUC.", "Most catalogued materials cannot receive defensible rankings.", "Unsupported materials remain explicitly unscored.", "Independent coordinate-bearing positives and deposit-type labels sufficient for spatial holdout.", "No automatic score is created from ontology membership.", "outputs/validation_report.json and outputs/material_ontology_validation_v1.json"),
    cross_gap("GAP-PROJECT-002", ["known_site_completeness", "coordinate_quality"], "known sites", ["india_known_mining_sites.csv"], "India selection", "Mixed historical MRDS dates", "The primary coordinate-bearing known-site layer is not an exhaustive or current statutory mine register.", "781 records; 779 within expected India bounds; two retained out-of-bounds source coordinates.", "Label incompleteness and positional error can bias training and evaluation.", "Source quality codes, raw coordinates, bounds flags, and limitations remain published.", "Authoritative, reusable national mine/occurrence register with dated status and coordinate accuracy.", "Model training uses these points with spatial holdout but cannot correct missing positives.", "outputs/validation_report.json"),
    cross_gap("GAP-PROJECT-003", ["legal_status", "operating_status", "identity_resolution"], "mine and concession status", ["india_ibm_mcdr_latest_inspected_mines.csv", "india_ibm_abandoned_mine_sites.csv", "india_ibm_auctioned_mineral_concessions_2023_24.csv"], "India; published administrative geography", "2023-24 to 2026 snapshots", "KHANAN does not have a controlling nationwide current operating, title, clearance, suspension, or closure register linked to exact geometries.", "1,353 latest inspected identities; 82 abandoned-mine rows; 97 IBM auction rows; zero rows asserted as currently legally or operationally verified.", "No operational recommendation or current-status claim can be made.", "Event types and dates remain separate; unverified current status is explicit.", "Dated controlling lease, clearance, production, suspension, and closure sources joined by stable mine/lease identifiers.", "Status-context rows are excluded from spatial scoring.", "source registry and per-layer validations"),
    cross_gap("GAP-PROJECT-004", ["geochemistry", "spatial_coverage", "sampling_design"], "analytical geochemistry", ["india_earthchem_geochemical_samples.csv", "india_earthchem_geochemical_observations.csv"], "Two western-Assam sites", "One published 2026 dataset", "Redistributable coordinate-bearing analytical geochemistry is extremely sparse and targeted.", "13 samples, two coordinate sites, and 1,323 observations.", "The layer cannot validate national anomalies or regional grade continuity.", "It remains independent context outside training and validation.", "Systematic India-wide measurements with method, detection limit, medium, depth, uncertainty, and reusable coordinates.", "No score or candidate rank changes.", "outputs/earthchem_geochemical_validation.json"),
    cross_gap("GAP-PROJECT-005", ["source_access", "licensing", "method_metadata"], "NGDR/GSI geoscience services", ["ngdr_service_inventory.csv"], "Nominal national coverage", "Guest-service snapshot 2026-09-09", "NGDR feature values are not redistributed because dataset-specific reuse authority and essential unit/method metadata are unresolved.", "1,114 WMS layers; 751 WFS types; 11 audited relevant layers; 2,459,737 reported features; zero feature-value rows published.", "High-value Indian geochemistry, geophysics, lithology, soil, and structural evidence remains unavailable to the model.", "Only catalog metadata, schemas, endpoints, and exclusions are published.", "Dataset-specific written reuse basis plus complete coordinate, unit, analytical-method, scale, and missingness metadata.", "NGDR values remain excluded from model training and scoring.", "outputs/ngdr_service_validation.json"),
    cross_gap("GAP-PROJECT-006", ["source_access", "catalog_completeness"], "historical GSI/OGD deposit catalogues", ["gsi_ogd_mineral_deposit_catalog_audit.csv", "india_gsi_ogd_mineral_deposit_preview.csv"], "India; eight mineral catalogues", "2013 catalogues; accessed 2026-09-10", "Interactive CAPTCHA-gated downloads prevented acquisition of complete historical catalogues.", "78 preview rows of 381 reported rows (20.47%); 303 rows not exposed.", "The public preview is incomplete and non-random.", "All preview rows retain selection mechanism, completeness status, and model exclusion.", "Lawful full-workbook access or an official bulk endpoint with stable identifiers and licence metadata.", "Preview rows remain excluded from training, validation, and scoring.", "outputs/gsi_ogd_mineral_deposit_preview_validation.json"),
    cross_gap("GAP-PROJECT-007", ["geophysics", "resolution", "coverage"], "magnetic context", ["india_emag2v3_magnetic_features_h3_r6.csv", "material_emag2_spatial_ablation.csv"], "National H3 grid", "Static EMAG2v3 snapshot", "The available open magnetic layer is regional, upward-continued, and incomplete over some cells.", "95.31% valid anomaly coverage; 92.78% valid error coverage; 6,418 ambiguous/no-data source-code cells; zero materials admitted after ablation.", "It cannot resolve local targets and does not demonstrate out-of-region incremental value.", "Error, source-code, distance, coverage, and ablation fields remain explicit.", "Higher-resolution lawful magnetic, gravity, radiometric, and structural data with independent labels.", "EMAG2 remains excluded from production scoring.", "outputs/emag2v3_magnetic_features_validation.json and outputs/emag2_spatial_ablation_validation.json"),
    cross_gap("GAP-PROJECT-008", ["soil", "measurement_basis", "validation"], "soil context", ["india_soilgrids_v2_soil_features_h3_r6.csv", "material_soilgrids_spatial_ablation.csv"], "National H3 grid", "SoilGrids 2.0 snapshot", "SoilGrids values are global model predictions rather than India-specific measured regolith or geochemical assays.", "Nine properties at two depths with p05/p95; minimum coverage 99.28%; zero materials admitted after ablation.", "Modeled soil context cannot substantiate subsurface mineralization.", "Prediction intervals and model exclusion are preserved.", "Reusable India-specific measured soil/regolith observations with analytical method, depth, and spatially independent validation.", "SoilGrids remains excluded from production scoring.", "outputs/soilgrids_v2_soil_features_validation.json and outputs/soilgrids_spatial_ablation_validation.json"),
    cross_gap("GAP-PROJECT-009", ["remote_sensing", "temporal_coverage", "leakage"], "Sentinel-2 surface context", ["india_sentinel2_surface_context_h3_r6.csv", "material_sentinel2_spatial_ablation.csv"], "National H3 grid", "Two fixed 2025 seasons", "Two-season multispectral surface proxies are non-specific and may encode mining disturbance that occurred after a deposit was already known.", "950 scenes; 98.96% of cells with any clear-land observation; 84.25% with two-season bare support; zero materials admitted.", "Surface signals cannot be interpreted as mineral identification or knowledge-independent prediction.", "Native SCL masking, coverage, support, leakage guardrail, and ablation decisions are published.", "Time-safe pre-discovery imagery, hyperspectral evidence, deposit-type mechanisms, and independent transfer validation.", "Sentinel features remain excluded from v0.6 scoring.", "outputs/sentinel2_surface_context_validation.json and outputs/sentinel2_spatial_ablation_validation.json"),
    cross_gap("GAP-PROJECT-010", ["independent_validation", "label_independence"], "official-block transfer", ["material_official_block_transfer_validation.csv", "official_block_transfer_observations.csv"], "166 accepted official footprints", "Auction source snapshots through Alpha.20", "Official target selection is not proven independent of all historical geological knowledge and no material passes every production-admission gate.", "151 target-mapped footprints; 221 material observations; 12 evaluated materials; zero production admissions.", "Transfer performance cannot establish discovery probability or unbiased future performance.", "Results are validation-only and preserve uncertainty intervals and support gates.", "Genuinely knowledge-independent confirmed positives or time-split future outcomes.", "No candidate scores, classes, or ranks changed.", "outputs/official_block_transfer_validation.json"),
    cross_gap("GAP-PROJECT-011", ["administrative_vintage", "demographics"], "population and demographics", ["india_known_mining_sites.csv", "india_mining_prospectivity_grid_h3_r6.csv", "india_ibm_district_mineral_context_h3_r6.csv"], "India; 2011 district boundaries", "2011 Census and 2020 WorldPop", "Administrative boundaries, Census demographics, and gridded population have different reference years and do not capture later boundary or population change.", "2011 district joins cover 99.985% of grid cells; population join is complete for the 2020 grid.", "Demographic context is approximate for current planning and must not be treated as a geological cause.", "Reference years, codes, join status, and aggregate-only interpretation remain explicit.", "New authoritative Census/boundary releases and documented crosswalks when publicly available.", "Population and demographics are contextual and not mineral-causation labels.", "outputs/validation_report.json"),
    cross_gap("GAP-PROJECT-012", ["weather", "temporal_coverage"], "weather and climate", ["india_known_mining_sites.csv", "india_mining_prospectivity_grid_h3_r6.csv"], "National H3 grid", "2025-09-01 to 2026-08-31 rolling window", "The weather layer is one complete rolling twelve-month period rather than a long-term climatology or future projection.", "365 expected days and 100% complete-period rate.", "One year cannot represent long-run variability, extremes, or future operational conditions.", "Exact period, day count, completeness, and monthly values remain published.", "Multi-decadal normals, extremes, and time-updated observations with stable versioning.", "Weather remains context; it is not direct mineral evidence.", "outputs/nasa_power_rolling_12m_validation.json"),
    cross_gap("GAP-PROJECT-013", ["ecology", "feature_absence"], "vegetation and agriculture", ["india_sentinel2_surface_context_h3_r6.csv"], "India", "Not implemented beyond broad two-season surface classes", "Crop calendars, phenology, moisture stress, thermal anomalies, and India-specific vegetation mechanisms are not yet integrated.", "No dedicated ecological table or production predictor.", "The requested ecological context is incomplete and cannot support causal claims.", "No values are fabricated; the missing family is explicitly registered.", "Reusable crop, land-cover, phenology, moisture, and thermal evidence plus mechanism-aware spatial ablation.", "No ecological signal affects scoring.", "README feature-readiness table and roadmap"),
    cross_gap("GAP-PROJECT-014", ["hydrology", "feature_absence"], "hydrology and groundwater", [], "India", "Not implemented", "Drainage, watersheds, erosion, groundwater chemistry, and surface-water context are not integrated.", "No dedicated hydrology table.", "Transport pathways and water constraints cannot be evaluated nationally.", "The absent family is disclosed rather than imputed.", "Reusable catchment, groundwater, surface-water, erosion, and chemistry layers with provenance and validation.", "No hydrological feature affects scoring.", "README feature-readiness table and roadmap"),
    cross_gap("GAP-PROJECT-015", ["environmental_safeguards", "archaeology", "tenure", "infrastructure"], "responsible opportunity constraints", [], "India", "Not implemented", "Protected areas, forests, water stress, archaeological/cultural sites, tenure, communities, roads, rail, ports, power, and processing infrastructure are not yet assembled as exclusion/caution layers.", "No operational field-prioritization or permission product is published.", "Model candidates cannot support access, permitting, investment, or operational recommendations.", "README and model limitations prohibit operational interpretation.", "Authoritative, current legal/environmental/cultural/social/infrastructure layers plus expert and community review protocol.", "Candidates remain reconnaissance hypotheses only.", "README Phase 7 and project guardrails"),
    cross_gap("GAP-PROJECT-016", ["model_form", "deposit_type"], "prospectivity modeling", ["india_mining_prospectivity_grid_h3_r6.csv", "india_mining_candidate_areas_validation_gated.csv"], "India", "Model v0.6", "Current material screens are generic and are not deposit-type or geological-process models.", "50 retained targets; only 14 meet the current minimum holdout AUC gate; high-priority outputs occur for chromium and iron.", "A high index may reflect broad association rather than a specific mineral system.", "Support levels, spatial metrics, nearest-evidence distances, and model limitations remain row-visible.", "Deposit-type labels, process features, calibrated baselines, independent deposits, and time-split evaluation.", "Existing rankings remain explicitly uncalibrated reconnaissance indices.", "outputs/validation_report.json and docs/methodology.md"),
    cross_gap("GAP-PROJECT-017", ["public_distribution", "file_size"], "release distribution", ["india_mining_prospectivity_grid_h3_r6.csv"], "National H3 grid", "Alpha.24 snapshot", "The full national CSV exceeds GitHub's normal single-file limit and is not stored as a standalone tracked file.", "88,857 rows and 187 columns; included inside the public deterministic ZIP bundle.", "Direct row-level Git browsing of the full grid is unavailable.", "The bundle, checksums, candidate subset, data dictionary, and build scripts remain public.", "A durable large-object, GeoParquet, object-storage, or versioned data-release endpoint.", "No scientific result changes; this is an access-format limitation.", "outputs/README.md and scripts/build_release.py"),
    cross_gap("GAP-PROJECT-018", ["field_verification", "ground_truth"], "field verification", ["india_mining_candidate_areas_validation_gated.csv"], "All candidate cells", "No KHANAN field campaign", "No KHANAN candidate has been verified by mapping, sampling, drilling, laboratory assay, resource estimation, or competent-person review.", "2,784 candidate cells; zero field-verified discoveries claimed.", "Model hypotheses cannot be described as finds, deposits, resources, reserves, grades, or drill targets.", "Every public interpretation repeats the reconnaissance-only boundary.", "Independent permitted fieldwork, QA/QC assays, drilling where lawful, geological interpretation, and qualified review.", "No candidate is labeled as a discovery.", "README, outputs/validation_report.json, and candidate model_limitations"),
    cross_gap("GAP-PROJECT-019", ["material_quantity", "grade", "economics"], "resource and economic assessment", ["india_ibm_nmi_2025_resource_inventory.csv", "india_mining_candidate_areas_validation_gated.csv"], "India and aggregates", "Mixed", "KHANAN does not estimate candidate-cell tonnage, grade, recovery, cut-off, processing route, cost, price, or economic viability.", "IBM quantities remain national/state/grade aggregates; candidate rows contain no inferred resource or reserve quantity.", "Rankings cannot support valuation, feasibility, reserve reporting, or investment decisions.", "Source aggregates and hypotheses are stored in separate tables with explicit units and exclusions.", "Site-specific qualified exploration, QA/QC, resource modeling, metallurgy, environmental review, and economic studies.", "The model produces only relative screening indices.", "outputs/ibm_nmi_2025_extraction_validation.json and outputs/validation_report.json"),
    cross_gap("GAP-PROJECT-020", ["licensing", "reuse"], "cross-source release licensing", ["source_registry.csv", "release_artifact_manifest.csv"], "All release artifacts", "Alpha.24 snapshot", "Source licences and access terms vary; several publicly queryable government or hosted services do not provide a blanket redistribution licence for every underlying value.", "38 source-registry entries with source-specific licence/access notes.", "Users cannot assume one uniform licence applies to every upstream dataset.", "The release publishes derived data where justified, withholds restricted/unclear feature values, and carries source-specific notes into the manifest.", "Dataset-specific provider terms or permissions sufficient for the intended redistribution and reuse.", "Unclear-source values remain metadata-only or excluded.", "outputs/source_registry.csv and docs/ngdr_access_and_integration.md"),
]


DICTIONARY_DEFINITIONS = {
    "release_artifact_manifest.csv": {
        "artifact_id": ("Stable release-artifact identifier derived from the filename.", "string", "", "Required."),
        "relative_path": ("Repository-relative path of the published artifact.", "string", "", "Required."),
        "artifact_type": ("Serialization type: tabular_csv or vector_geojson.", "string", "", "Required."),
        "release_version": ("KHANAN development release that generated the manifest.", "string", "", "Required."),
        "schema_version": ("Release-scoped schema identifier containing the canonical schema-hash prefix.", "string", "", "Required."),
        "evidence_role": ("Controlled separation of observed evidence, context, model hypotheses, validation, and metadata.", "string", "", "Required."),
        "role_definition": ("Interpretation boundary for evidence_role.", "string", "", "Required."),
        "model_use_status": ("Permitted relationship between the artifact and model training, validation, scoring, or metadata.", "string", "", "Required."),
        "row_grain": ("Meaning of one row or GeoJSON feature.", "string", "", "Required."),
        "primary_key_columns_json": ("Ordered columns forming the release-contract primary key.", "JSON array", "", "Required."),
        "primary_key_unique": ("Whether every nonblank primary-key tuple is unique.", "boolean", "", "Required; true is a release gate."),
        "primary_key_blank_rows": ("Rows or features with at least one blank primary-key component.", "integer", "rows", "Required; zero is a release gate."),
        "row_count": ("CSV data-row or GeoJSON feature count.", "integer", "rows or features", "Required."),
        "column_count": ("CSV column or GeoJSON property count.", "integer", "columns or properties", "Required."),
        "schema_sha256": ("SHA-256 of the canonical ordered column/property-name JSON array.", "string", "", "Required."),
        "artifact_sha256": ("SHA-256 of artifact bytes; blank only for the manifest self-row.", "string", "", "Blank for manifest self-row to avoid self-reference."),
        "artifact_sha256_status": ("Hash provenance or the explicit self-reference exception.", "string", "", "Required."),
        "source_ids_json": ("Sorted source_registry.csv identifiers contributing to the artifact.", "JSON array", "", "Empty only for derived release-governance metadata."),
        "geographic_scope": ("Declared geographic coverage or non-spatial scope.", "string", "", "Required."),
        "temporal_scope": ("Declared observation, reference, or release period.", "string", "", "Required."),
        "coordinate_or_geometry_fields_json": ("Columns carrying coordinates, H3 indexes, boundaries, or geometries.", "JSON array", "", "Empty when not spatial."),
        "uncertainty_fields_json": ("Columns explicitly representing intervals, errors, support, completeness, or uncertainty.", "JSON array", "", "Empty when not applicable."),
        "exclusion_or_quality_fields_json": ("Columns representing quality, validation, admission, exclusion, status, or interpretation controls.", "JSON array", "", "Empty only when no such field exists."),
        "license_or_access_basis": ("Source-specific licence/access notes serialized as JSON.", "JSON object", "", "Uses an internal-derivation note when no external source applies."),
        "schema_freeze_status": ("Release-scoped schema-freeze label.", "string", "", "Required."),
        "schema_change_policy": ("Required process for a breaking or semantic schema change.", "string", "", "Required."),
        "build_script": ("Primary reproducible builder or builder family.", "string", "", "Required."),
        "validation_artifact": ("Primary machine-readable validation result.", "string", "", "Required."),
        "limitations": ("Artifact-specific interpretation limitation.", "string", "", "Required."),
    },
    "coverage_gap_register.csv": {
        "gap_id": ("Stable identifier for a disclosed limitation or gap.", "string", "", "Required."),
        "gap_level": ("source_specific or project_wide.", "string", "", "Required."),
        "gap_categories_json": ("One or more controlled descriptive gap categories.", "JSON array", "", "Required."),
        "evidence_family": ("Source use or project evidence family affected by the gap.", "string", "", "Required."),
        "affected_source_id": ("Source registry identifier for source-specific gaps.", "string", "", "Blank for project-wide gaps."),
        "affected_artifacts_json": ("Published artifacts affected by the gap.", "JSON array", "", "May be empty for wholly absent feature families."),
        "geographic_scope": ("Geography to which the gap applies.", "string", "", "Required."),
        "temporal_scope": ("Time or source snapshot to which the gap applies.", "string", "", "Required."),
        "gap_description": ("Factual description of unavailable, incomplete, uncertain, or excluded evidence.", "string", "", "Required."),
        "quantitative_evidence": ("Count, rate, date, or other audit evidence supporting the disclosure.", "string", "", "Blank only when no numeric control exists."),
        "scientific_or_operational_impact": ("How the gap limits interpretation or use.", "string", "", "Required."),
        "current_mitigation": ("Current non-fabricating safeguard or disclosure.", "string", "", "Required."),
        "resolution_evidence_required": ("Evidence needed to close or materially reduce the gap.", "string", "", "Required."),
        "model_effect": ("How the gap affects training, validation, scoring, or interpretation.", "string", "", "Required."),
        "alpha3_completion_effect": ("Required treatment of the gap in the Alpha 3.0 completion audit.", "string", "", "Required."),
        "status": ("Current disclosure status.", "string", "", "Required."),
        "provenance_basis": ("File or source record supporting the disclosure.", "string", "", "Required."),
    },
    "source_registry.csv": {
        "source_id": ("Stable source or source-family identifier.", "string", "", "Required."),
        "publisher": ("Publishing organization.", "string", "", "Required."),
        "title": ("Source title or service family.", "string", "", "Required."),
        "release_or_reference_date": ("Source release, reference, or access date text.", "string", "", "Required where published."),
        "url": ("Primary public source page.", "string", "", "Required."),
        "download_url": ("Download, API, service, or document URL used for acquisition.", "string", "", "Blank when the primary URL is the only access surface."),
        "license_or_access_note": ("Source-specific reuse, attribution, or access qualification.", "string", "", "Required."),
        "used_for": ("KHANAN use of the source.", "string", "", "Required."),
        "limitations": ("Source-specific completeness, method, currency, precision, or interpretation limitation.", "string", "", "Required."),
    },
    "data_dictionary.csv": {
        "table": ("Published CSV filename whose column is defined.", "string", "", "Required."),
        "column": ("Exact column name in source order.", "string", "", "Required."),
        "definition": ("Plain-language field definition.", "string", "", "Required."),
        "data_type": ("Intended analytical data type.", "string", "", "Required."),
        "unit": ("Measurement unit when applicable.", "string", "", "Blank when dimensionless or not applicable."),
        "missing_value_policy": ("Meaning or permitted treatment of a blank or missing value.", "string", "", "Required."),
    },
}

MODEL_FIELD_DEFINITIONS = {
    "material_name": ("Normalized strategic material name.", "string", "", "Required."),
    "known_evidence_records": ("Count of known-site evidence records mapped to the material.", "integer", "records", "Required."),
    "modelled": ("Whether a material-specific screen was fitted.", "boolean", "", "Required."),
    "model_support_level": ("Support category derived from known-evidence count and validation availability.", "string", "", "Required."),
    "score_note": ("Explanation of score availability or exclusion.", "string", "", "Required."),
    "spatial_cv_positive_records": ("Positive records participating in spatial cross-validation.", "integer", "records", "Blank when no model is evaluated."),
    "spatial_cv_folds": ("Completed spatial cross-validation fold count.", "integer", "folds", "Blank when no model is evaluated."),
    "spatial_cv_background_cells": ("Pseudo-absence background cells used in spatial validation.", "integer", "cells", "Blank when no model is evaluated."),
    "spatial_holdout_pseudoabsence_roc_auc": ("Out-of-fold ROC-AUC against sampled pseudo-absence background.", "number", "0-1", "Blank when support is insufficient."),
    "spatial_holdout_recall_at_background_top5pct": ("Positive recall at the score threshold exceeded by 5% of held-out background cells.", "number", "0-1", "Blank when support is insufficient."),
    "validation_note": ("Material-specific validation interpretation and limitation.", "string", "", "Required."),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_sha(fields: Iterable[str]) -> str:
    return hashlib.sha256(jdump(list(fields)).encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_json_strings(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, str):
        return [parsed]
    return []


def source_ids_for_csv(path: Path, registry_ids: set[str]) -> list[str]:
    fields = csv_header(path)
    source_fields = [field for field in fields if "source_id" in field]
    found = set(STATIC_SOURCE_IDS.get(path.name, []))
    if source_fields:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                for field in source_fields:
                    for value in parse_json_strings(row.get(field, "")):
                        if value in registry_ids:
                            found.add(value)
    unknown = found - registry_ids
    if unknown:
        raise ValueError(f"Unknown source IDs for {path.name}: {sorted(unknown)}")
    return sorted(found)


def related_fields(fields: list[str], patterns: list[str]) -> list[str]:
    regex = re.compile("|".join(patterns), re.IGNORECASE)
    return [field for field in fields if regex.search(field)]


def infer_gap_categories(text: str) -> list[str]:
    folded = text.casefold()
    categories = []
    tests = [
        ("licensing", r"licen[cs]|reuse|terms|redistribut|attribution|copyright|proprietary"),
        ("source_access", r"access|captcha|download|preview|endpoint|portal|unavailable"),
        ("geographic_coverage", r"geograph|coverage|national|regional|state|district|india"),
        ("coordinate_or_geometry", r"coordinate|location|point|datum|geometry|polygon|precision|boundary"),
        ("temporal_currency", r"histor|current|date|year|snapshot|time|updated|status"),
        ("method_or_unit_metadata", r"method|unit|detection|instrument|scale|resolution|metadata|sampling"),
        ("completeness", r"incomplete|exhaustive|partial|missing|limited|not a|not an"),
        ("legal_or_operational_status", r"legal|operation|production|lease|permission|access status"),
        ("model_interpretation", r"model|training|validation|score|prospect|discover|reserve|resource|grade"),
    ]
    for category, pattern in tests:
        if re.search(pattern, folded):
            categories.append(category)
    return categories or ["source_scope"]


def source_artifact_index(registry_ids: set[str]) -> dict[str, list[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for name in sorted(CONTRACTS):
        if not name.endswith(".csv") or name in {MANIFEST_PATH.name, GAP_PATH.name, DICTIONARY_PATH.name}:
            continue
        path = OUT / name
        for source_id in source_ids_for_csv(path, registry_ids):
            index[source_id].add(name)
    for name, ids in STATIC_SOURCE_IDS.items():
        for source_id in ids:
            if source_id in registry_ids:
                index[source_id].add(name)
    return {source_id: sorted(names) for source_id, names in index.items()}


def build_gap_register(source_rows: list[dict[str, str]], artifact_index: dict[str, list[str]]) -> list[dict[str, str]]:
    rows = []
    for source in sorted(source_rows, key=lambda row: row["source_id"]):
        source_id = source["source_id"]
        limitation = source["limitations"].strip()
        if not limitation:
            raise ValueError(f"Source {source_id} has no limitations text")
        combined = " ".join([source.get("license_or_access_note", ""), limitation])
        rows.append({
            "gap_id": f"GAP-SOURCE-{source_id.removeprefix('SRC_')}",
            "gap_level": "source_specific",
            "gap_categories_json": jdump(infer_gap_categories(combined)),
            "evidence_family": source["used_for"],
            "affected_source_id": source_id,
            "affected_artifacts_json": jdump(artifact_index.get(source_id, [])),
            "geographic_scope": "Source-defined; see source title and affected artifacts.",
            "temporal_scope": source["release_or_reference_date"],
            "gap_description": limitation,
            "quantitative_evidence": "See source-specific validation and affected artifact counts.",
            "scientific_or_operational_impact": "Interpretation is limited to the source's stated scope, currency, precision, access, and method constraints.",
            "current_mitigation": "Retain source wording, provenance, quality fields, and model-use restrictions; do not fabricate missing values.",
            "resolution_evidence_required": "A newer or more complete authoritative source with explicit reuse, method, coordinate, and status metadata where applicable.",
            "model_effect": "The source is used only for the role stated in source_registry.csv and the release manifest.",
            "alpha3_completion_effect": "must_remain_disclosed_in_final_coverage_audit",
            "status": "open_source_limitation",
            "provenance_basis": f"outputs/source_registry.csv#{source_id}",
        })
    rows.extend(CROSS_CUTTING_GAPS)
    return sorted(rows, key=lambda row: row["gap_id"])


def generic_definition(column: str) -> tuple[str, str, str, str]:
    label = column.replace("_json", "").replace("_", " ")
    if column.endswith("_json"):
        return (f"Structured {label} values serialized as JSON.", "JSON", "", "Empty JSON array/object or blank means unavailable as defined by the source table.")
    if column.startswith("is_") or column.endswith(("_available", "_verified", "_valid", "_pass", "_unique")):
        return (f"Boolean indicator for {label}.", "boolean", "", "Blank means not evaluated or unavailable.")
    if any(token in column for token in ["count", "rows", "records", "folds", "rank", "number"]):
        return (f"Count or ordinal value for {label}.", "integer", "", "Blank means unavailable or not applicable.")
    if any(token in column for token in ["pct", "rate", "share", "auc", "recall", "score", "fraction", "percentile"]):
        return (f"Numeric value for {label}.", "number", "See field name", "Blank means unavailable or not evaluated.")
    return (f"{label[:1].upper() + label[1:]}.", "string", "", "Blank means unavailable or not applicable.")


def rebuild_data_dictionary(csv_names: list[str]) -> list[dict[str, str]]:
    existing = read_csv(DICTIONARY_PATH)
    available = set(csv_names)
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    global_columns: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in existing:
        table = row["table"]
        if table not in available and f"{table}.csv" in available:
            table = f"{table}.csv"
        normalized = {**row, "table": table}
        lookup[(table, row["column"])] = normalized
        global_columns[row["column"]].append(normalized)

    grid_defs = {
        row["column"]: row for (table, _), row in lookup.items()
        if table == "india_mining_prospectivity_grid_h3_r6.csv"
    }
    output = []
    for table in sorted(csv_names):
        path = OUT / table
        fields = MANIFEST_FIELDS if table == MANIFEST_PATH.name else GAP_FIELDS if table == GAP_PATH.name else csv_header(path)
        for column in fields:
            row = lookup.get((table, column))
            if row is None and table == "india_mining_candidate_areas_validation_gated.csv":
                row = grid_defs.get(column)
            if row is None and table in {"material_model_support.csv", "material_model_validation.csv"}:
                definition = MODEL_FIELD_DEFINITIONS.get(column)
                if definition:
                    row = dict(zip(["definition", "data_type", "unit", "missing_value_policy"], definition))
            if row is None and table in DICTIONARY_DEFINITIONS:
                definition = DICTIONARY_DEFINITIONS[table].get(column)
                if definition:
                    row = dict(zip(["definition", "data_type", "unit", "missing_value_policy"], definition))
            if row is None and global_columns.get(column):
                source = global_columns[column][0]
                row = {field: source[field] for field in ["definition", "data_type", "unit", "missing_value_policy"]}
            if row is None:
                definition = generic_definition(column)
                row = dict(zip(["definition", "data_type", "unit", "missing_value_policy"], definition))
            output.append({
                "table": table, "column": column, "definition": row["definition"],
                "data_type": row["data_type"], "unit": row["unit"],
                "missing_value_policy": row["missing_value_policy"],
            })
    return output


def csv_manifest_stats(path: Path, contract_row: dict[str, Any], registry_ids: set[str]) -> dict[str, Any]:
    fields = csv_header(path)
    key_fields = contract_row["key"]
    missing_keys = sorted(set(key_fields) - set(fields))
    if missing_keys:
        raise ValueError(f"Missing primary-key fields in {path.name}: {missing_keys}")
    row_count = 0
    blank_keys = 0
    seen = set()
    duplicates = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            key = tuple((row.get(field) or "").strip() for field in key_fields)
            if any(not value for value in key):
                blank_keys += 1
            if key in seen:
                duplicates += 1
            seen.add(key)
    return {
        "fields": fields, "row_count": row_count, "blank_keys": blank_keys,
        "primary_key_unique": duplicates == 0,
        "source_ids": source_ids_for_csv(path, registry_ids) if path.name not in {MANIFEST_PATH.name, GAP_PATH.name, DICTIONARY_PATH.name} else [],
    }


def geojson_manifest_stats(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    fields = list(features[0].get("properties", {})) if features else []
    keys = []
    blank = 0
    for feature in features:
        value = str(feature.get("properties", {}).get("record_id", "")).strip()
        keys.append(value)
        blank += int(not value)
    return {
        "fields": fields, "row_count": len(features), "blank_keys": blank,
        "primary_key_unique": len(keys) == len(set(keys)),
        "source_ids": STATIC_SOURCE_IDS[path.name],
    }


def build_manifest(source_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    registry = {row["source_id"]: row for row in source_rows}
    registry_ids = set(registry)
    rows = []
    for name in sorted(CONTRACTS):
        path = OUT / name
        spec = CONTRACTS[name]
        if not path.exists() and name != MANIFEST_PATH.name:
            raise FileNotFoundError(path)
        if name == MANIFEST_PATH.name:
            stats = {
                "fields": MANIFEST_FIELDS, "row_count": len(CONTRACTS),
                "blank_keys": 0, "primary_key_unique": True, "source_ids": [],
            }
        elif name.endswith(".geojson"):
            stats = geojson_manifest_stats(path)
        else:
            stats = csv_manifest_stats(path, spec, registry_ids)
        fields = stats["fields"]
        actual_schema = schema_sha(fields)
        expected_schema = EXPECTED_SCHEMA_SHA256[name]
        if actual_schema != expected_schema:
            raise ValueError(f"Schema drift for {name}: {actual_schema} != {expected_schema}")
        source_ids = stats["source_ids"]
        licence = {
            source_id: registry[source_id]["license_or_access_note"]
            for source_id in source_ids
        } if source_ids else {"KHANAN_DERIVED": "Release metadata derived from the versioned public artifacts; upstream source terms remain controlling."}
        spatial = related_fields(fields, [r"(^|_)lat", r"(^|_)lon", r"h3", r"wkt", r"geometry", r"bbox", r"boundary"])
        uncertainty = related_fields(fields, [r"p05", r"p95", r"ci95", r"uncert", r"error", r"std", r"support", r"completeness", r"coverage"])
        controls = related_fields(fields, [r"quality", r"flag", r"status", r"valid", r"admission", r"exclusion", r"limitation", r"verified", r"interpretation", r"decision", r"promotion"])
        artifact_hash = "" if name == MANIFEST_PATH.name else sha256_file(path)
        rows.append({
            "artifact_id": Path(name).stem,
            "relative_path": f"outputs/{name}",
            "artifact_type": "vector_geojson" if name.endswith(".geojson") else "tabular_csv",
            "release_version": RELEASE_VERSION,
            "schema_version": f"alpha24-schema-{actual_schema[:12]}",
            "evidence_role": spec["role"],
            "role_definition": ROLE_DEFINITIONS[spec["role"]],
            "model_use_status": spec["model_use"],
            "row_grain": spec["grain"],
            "primary_key_columns_json": jdump(spec["key"]),
            "primary_key_unique": str(stats["primary_key_unique"]).lower(),
            "primary_key_blank_rows": stats["blank_keys"],
            "row_count": stats["row_count"],
            "column_count": len(fields),
            "schema_sha256": actual_schema,
            "artifact_sha256": artifact_hash,
            "artifact_sha256_status": "external_SHA256SUMS_only_self_reference_exception" if name == MANIFEST_PATH.name else "computed_from_release_artifact_bytes",
            "source_ids_json": jdump(source_ids),
            "geographic_scope": spec["geography"],
            "temporal_scope": spec["temporal"],
            "coordinate_or_geometry_fields_json": jdump(spatial),
            "uncertainty_fields_json": jdump(uncertainty),
            "exclusion_or_quality_fields_json": jdump(controls),
            "license_or_access_basis": jdump(licence),
            "schema_freeze_status": SCHEMA_FREEZE_STATUS,
            "schema_change_policy": "Any breaking or semantic change requires a new release version, explicit dictionary and schema-hash update, validation, and documented migration note.",
            "build_script": spec["builder"],
            "validation_artifact": spec["validation"],
            "limitations": spec["limitations"],
        })
    return rows


def validate_dictionary(csv_names: list[str], rows: list[dict[str, str]]) -> tuple[int, list[tuple[str, str]], list[tuple[str, str]]]:
    keys = [(row["table"], row["column"]) for row in rows]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    expected = []
    for table in sorted(csv_names):
        fields = MANIFEST_FIELDS if table == MANIFEST_PATH.name else GAP_FIELDS if table == GAP_PATH.name else csv_header(OUT / table)
        expected.extend((table, field) for field in fields)
    missing = sorted(set(expected) - set(keys))
    extra = sorted(set(keys) - set(expected))
    if duplicates or missing or extra or len(rows) != len(expected):
        raise ValueError({"dictionary_duplicates": duplicates, "dictionary_missing": missing, "dictionary_extra": extra, "rows": len(rows), "expected": len(expected)})
    return len(expected), missing, extra


def update_validation_report(validation: dict[str, Any]) -> None:
    path = OUT / "validation_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["development_release_version"] = RELEASE_VERSION
    report["release_governance_alpha24"] = {
        "release_artifacts_registered": validation["manifest_rows"],
        "tabular_csv_artifacts_registered": validation["csv_artifacts_registered"],
        "vector_geojson_artifacts_registered": validation["geojson_artifacts_registered"],
        "frozen_schema_contracts": validation["schemas_matching_frozen_contract"],
        "data_dictionary_rows": validation["data_dictionary_rows"],
        "data_dictionary_complete_for_all_csv_columns": validation["data_dictionary_complete"],
        "source_specific_gap_rows": validation["source_specific_gap_rows"],
        "project_wide_gap_rows": validation["project_wide_gap_rows"],
        "observed_context_hypothesis_roles_explicit": validation["role_separation_complete"],
        "baseline_grid_unchanged": validation["baseline_grid_unchanged"],
        "baseline_candidate_unchanged": validation["baseline_candidate_unchanged"],
        "checks_pass": validation["checks_pass"],
    }
    path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    if set(EXPECTED_SCHEMA_SHA256) != set(CONTRACTS):
        raise ValueError("Schema contracts and artifact contracts differ")
    source_rows = read_csv(SOURCE_REGISTRY_PATH)
    registry_ids = {row["source_id"] for row in source_rows}
    if len(source_rows) != 38 or len(registry_ids) != len(source_rows):
        raise ValueError("Expected 38 unique registered sources")

    index = source_artifact_index(registry_ids)
    gap_rows = build_gap_register(source_rows, index)
    write_csv(GAP_PATH, GAP_FIELDS, gap_rows)

    csv_names = sorted(name for name in CONTRACTS if name.endswith(".csv"))
    dictionary_rows = rebuild_data_dictionary(csv_names)
    write_csv(DICTIONARY_PATH, ["table", "column", "definition", "data_type", "unit", "missing_value_policy"], dictionary_rows)

    root_csvs = {path.name for path in OUT.glob("*.csv")}
    expected_before_manifest = set(csv_names) - {MANIFEST_PATH.name}
    if frozenset(root_csvs) not in {frozenset(expected_before_manifest), frozenset(csv_names)}:
        raise ValueError({"unregistered_csvs": sorted(root_csvs - set(csv_names)), "missing_csvs": sorted(expected_before_manifest - root_csvs)})

    manifest_rows = build_manifest(source_rows)
    write_csv(MANIFEST_PATH, MANIFEST_FIELDS, manifest_rows)
    if {path.name for path in OUT.glob("*.csv")} != set(csv_names):
        raise ValueError("Final root CSV inventory does not match the release contracts")
    dictionary_expected, _, _ = validate_dictionary(csv_names, dictionary_rows)

    all_keys_unique = all(row["primary_key_unique"] == "true" for row in manifest_rows)
    blank_key_rows = sum(int(row["primary_key_blank_rows"]) for row in manifest_rows)
    role_counts = Counter(row["evidence_role"] for row in manifest_rows)
    role_separation = set(role_counts) == set(ROLE_DEFINITIONS)
    manifest_self = next(row for row in manifest_rows if row["artifact_id"] == MANIFEST_PATH.stem)
    self_exception_valid = manifest_self["artifact_sha256"] == "" and manifest_self["artifact_sha256_status"] == "external_SHA256SUMS_only_self_reference_exception"
    validation = {
        "release_version": RELEASE_VERSION,
        "manifest_rows": len(manifest_rows),
        "csv_artifacts_registered": len(csv_names),
        "geojson_artifacts_registered": sum(name.endswith(".geojson") for name in CONTRACTS),
        "schemas_matching_frozen_contract": len(manifest_rows),
        "all_primary_keys_unique": all_keys_unique,
        "primary_key_blank_rows": blank_key_rows,
        "manifest_self_hash_exception_valid": self_exception_valid,
        "data_dictionary_rows": len(dictionary_rows),
        "data_dictionary_expected_rows": dictionary_expected,
        "data_dictionary_complete": len(dictionary_rows) == dictionary_expected,
        "source_registry_rows": len(source_rows),
        "source_specific_gap_rows": sum(row["gap_level"] == "source_specific" for row in gap_rows),
        "project_wide_gap_rows": sum(row["gap_level"] == "project_wide" for row in gap_rows),
        "gap_rows": len(gap_rows),
        "all_registered_sources_have_gap_rows": {row["affected_source_id"] for row in gap_rows if row["gap_level"] == "source_specific"} == registry_ids,
        "role_counts": dict(sorted(role_counts.items())),
        "role_separation_complete": role_separation,
        "baseline_grid_sha256": sha256_file(GRID_PATH),
        "baseline_candidate_sha256": sha256_file(CANDIDATE_PATH),
        "baseline_grid_unchanged": sha256_file(GRID_PATH) == BASELINE_GRID_SHA256,
        "baseline_candidate_unchanged": sha256_file(CANDIDATE_PATH) == BASELINE_CANDIDATE_SHA256,
    }
    validation["checks_pass"] = all([
        len(manifest_rows) == len(CONTRACTS) == 44,
        len(csv_names) == 43,
        all_keys_unique,
        blank_key_rows == 0,
        self_exception_valid,
        len(dictionary_rows) == dictionary_expected == 1928,
        len(source_rows) == 38,
        validation["source_specific_gap_rows"] == 38,
        validation["project_wide_gap_rows"] == 20,
        validation["gap_rows"] == 58,
        validation["all_registered_sources_have_gap_rows"],
        role_separation,
        validation["baseline_grid_unchanged"],
        validation["baseline_candidate_unchanged"],
    ])
    if not validation["checks_pass"]:
        raise RuntimeError(validation)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    update_validation_report(validation)
    print(validation)


if __name__ == "__main__":
    main()
