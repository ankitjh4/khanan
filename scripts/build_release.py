#!/usr/bin/env python3
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
VERSION = "v1.0-alpha.24"

BUNDLE_MEMBERS = [
    "README.md",
    "assets/README.md",
    "assets/maps/khanan-india-prospectivity-overview-v0.6.png",
    "assets/maps/khanan-emag2-magnetic-context-v0.7.png",
    "assets/maps/khanan-soilgrids-context-v0.8.png",
    "assets/maps/khanan-ibm-auction-mbs-geometries-alpha16.png",
    "assets/maps/khanan-earthchem-lithium-geochemistry-alpha17.png",
    "assets/maps/khanan-sentinel2-surface-context-alpha18.png",
    "assets/maps/khanan-gsi-ogd-deposit-preview-alpha21.png",
    "assets/maps/khanan-ibm-state-review-occurrence-context-alpha23.png",
    "assets/figures/khanan-sentinel2-spatial-ablation-v0.1.png",
    "assets/figures/khanan-emag2-spatial-ablation-v0.1.png",
    "assets/figures/khanan-soilgrids-spatial-ablation-v0.1.png",
    "assets/figures/khanan-official-block-transfer-v0.1.png",
    "data/README.md",
    "docs/methodology.md",
    "docs/material_ontology_v1.md",
    "docs/release_governance_alpha24.md",
    "docs/ibm_mineral_concessions_2024.md",
    "docs/ibm_auction_mbs_geometry_2023_24.md",
    "docs/ibm_auction_status_evidence_2023_24.md",
    "docs/emag2_spatial_ablation.md",
    "docs/earthchem_lithium_geochemistry.md",
    "docs/gsi_ogd_mineral_deposit_preview.md",
    "docs/ibm_imyb_state_review_occurrences_2024.md",
    "docs/sentinel2_surface_context.md",
    "docs/sentinel2_spatial_ablation.md",
    "docs/official_block_transfer_validation.md",
    "docs/ngdr_access_and_integration.md",
    "docs/soilgrids_features.md",
    "docs/soilgrids_spatial_ablation.md",
    "outputs/README.md",
    "scripts/plot_khanan_overview.py",
    "scripts/plot_emag2_context.py",
    "scripts/plot_emag2_ablation.py",
    "scripts/audit_ngdr_services.py",
    "scripts/build_emag2_features.py",
    "scripts/evaluate_emag2_spatial_ablation.py",
    "scripts/build_soilgrids_features.py",
    "scripts/plot_soilgrids_context.py",
    "scripts/evaluate_soilgrids_spatial_ablation.py",
    "scripts/plot_soilgrids_ablation.py",
    "scripts/build_ibm_abandoned_mines.py",
    "scripts/build_ibm_mineral_concessions_2024.py",
    "scripts/build_ibm_auction_mbs_geometry_2023_24.py",
    "scripts/build_ibm_auction_status_evidence_2023_24.py",
    "scripts/plot_ibm_auction_mbs_geometries.py",
    "scripts/build_earthchem_geochemistry.py",
    "scripts/plot_earthchem_geochemistry.py",
    "scripts/build_gsi_ogd_deposit_preview.py",
    "scripts/plot_gsi_ogd_deposit_preview.py",
    "scripts/build_ibm_imyb_state_review_occurrences.py",
    "scripts/plot_ibm_imyb_state_review_occurrences.py",
    "scripts/validate_ibm_imyb_state_review_csv_artifacts.mjs",
    "scripts/validate_material_ontology_csv_artifacts.mjs",
    "scripts/build_release_governance.py",
    "scripts/validate_release_governance_csv_artifacts.mjs",
    "scripts/build_sentinel2_surface_context.py",
    "scripts/plot_sentinel2_surface_context.py",
    "scripts/validate_sentinel2_csv_artifacts.mjs",
    "scripts/evaluate_sentinel2_spatial_ablation.py",
    "scripts/plot_sentinel2_ablation.py",
    "scripts/validate_sentinel2_ablation_csv_artifacts.mjs",
    "scripts/evaluate_official_block_transfer.py",
    "scripts/plot_official_block_transfer.py",
    "scripts/validate_official_block_transfer_csv_artifacts.mjs",
    "scripts/build_material_ontology.py",
    "config/materials.json",
    "config/weather_window.json",
    "config/official_critical_blocks.json",
    "config/ibm_imyb_2024_state_review_occurrences.json",
    "outputs/india_known_mining_sites.csv",
    "outputs/india_ibm_mcdr_inspection_events_2023_2026.csv",
    "outputs/india_ibm_mcdr_latest_inspected_mines.csv",
    "outputs/india_ibm_abandoned_mine_sites.csv",
    "outputs/india_ibm_mining_lease_distribution_2024.csv",
    "outputs/india_ibm_auctioned_mineral_concessions_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_geometries_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_geometries_2023_24.geojson",
    "outputs/india_ibm_auctioned_concession_status_evidence_2023_24.csv",
    "outputs/india_ibm_nmi_2025_resource_inventory.csv",
    "outputs/india_official_critical_mineral_blocks.csv",
    "outputs/india_official_critical_mineral_mbs_manifest.csv",
    "outputs/india_mining_prospectivity_grid_h3_r6.csv",
    "outputs/india_mining_candidate_areas_validation_gated.csv",
    "outputs/india_emag2v3_magnetic_features_h3_r6.csv",
    "outputs/india_soilgrids_v2_soil_features_h3_r6.csv",
    "outputs/india_earthchem_geochemical_samples.csv",
    "outputs/india_earthchem_geochemical_observations.csv",
    "outputs/india_gsi_ogd_mineral_deposit_preview.csv",
    "outputs/gsi_ogd_mineral_deposit_catalog_audit.csv",
    "outputs/india_ibm_state_mineral_occurrences_2024.csv",
    "outputs/india_ibm_district_mineral_occurrences_2024.csv",
    "outputs/india_ibm_district_mineral_context_h3_r6.csv",
    "outputs/india_sentinel2_surface_context_h3_r6.csv",
    "outputs/india_sentinel2_scene_manifest_2025.csv",
    "outputs/material_sentinel2_spatial_ablation.csv",
    "outputs/material_sentinel2_spatial_ablation_folds.csv",
    "outputs/material_official_block_transfer_validation.csv",
    "outputs/official_block_transfer_observations.csv",
    "outputs/india_strategic_materials_top50.csv",
    "outputs/india_material_ontology_v1.csv",
    "outputs/material_source_term_crosswalk_v1.csv",
    "outputs/material_ontology_validation_v1.json",
    "outputs/release_artifact_manifest.csv",
    "outputs/coverage_gap_register.csv",
    "outputs/release_governance_validation.json",
    "outputs/material_model_support.csv",
    "outputs/material_model_validation.csv",
    "outputs/ngdr_service_inventory.csv",
    "outputs/source_registry.csv",
    "outputs/data_dictionary.csv",
    "outputs/validation_report.json",
    "outputs/ibm_nmi_2025_extraction_validation.json",
    "outputs/ibm_mcdr_inspection_validation.json",
    "outputs/ibm_abandoned_mines_validation.json",
    "outputs/ibm_mineral_concessions_2024_validation.json",
    "outputs/ibm_auction_mbs_geometry_validation.json",
    "outputs/ibm_auction_status_evidence_2023_24_validation.json",
    "outputs/ngdr_service_validation.json",
    "outputs/emag2v3_magnetic_features_validation.json",
    "outputs/material_emag2_spatial_ablation.csv",
    "outputs/material_emag2_spatial_ablation_folds.csv",
    "outputs/emag2_spatial_ablation_validation.json",
    "outputs/soilgrids_v2_soil_features_validation.json",
    "outputs/material_soilgrids_spatial_ablation.csv",
    "outputs/material_soilgrids_spatial_ablation_folds.csv",
    "outputs/soilgrids_spatial_ablation_validation.json",
    "outputs/earthchem_geochemical_validation.json",
    "outputs/gsi_ogd_mineral_deposit_preview_validation.json",
    "outputs/ibm_imyb_state_review_occurrences_validation.json",
    "outputs/sentinel2_surface_context_validation.json",
    "outputs/sentinel2_spatial_ablation_validation.json",
    "outputs/official_block_transfer_validation.json",
    "outputs/nasa_power_rolling_12m_validation.json",
    "outputs/official_critical_blocks_validation.json",
]

HASHED_ARTIFACTS = [
    "india_known_mining_sites.csv",
    "india_ibm_mcdr_inspection_events_2023_2026.csv",
    "india_ibm_mcdr_latest_inspected_mines.csv",
    "india_ibm_abandoned_mine_sites.csv",
    "india_ibm_mining_lease_distribution_2024.csv",
    "india_ibm_auctioned_mineral_concessions_2023_24.csv",
    "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv",
    "india_ibm_auctioned_concession_geometries_2023_24.csv",
    "india_ibm_auctioned_concession_geometries_2023_24.geojson",
    "india_ibm_auctioned_concession_status_evidence_2023_24.csv",
    "india_ibm_nmi_2025_resource_inventory.csv",
    "india_official_critical_mineral_blocks.csv",
    "india_official_critical_mineral_mbs_manifest.csv",
    "india_mining_prospectivity_grid_h3_r6.csv",
    "india_mining_candidate_areas_validation_gated.csv",
    "india_emag2v3_magnetic_features_h3_r6.csv",
    "india_soilgrids_v2_soil_features_h3_r6.csv",
    "india_earthchem_geochemical_samples.csv",
    "india_earthchem_geochemical_observations.csv",
    "india_gsi_ogd_mineral_deposit_preview.csv",
    "gsi_ogd_mineral_deposit_catalog_audit.csv",
    "india_ibm_state_mineral_occurrences_2024.csv",
    "india_ibm_district_mineral_occurrences_2024.csv",
    "india_ibm_district_mineral_context_h3_r6.csv",
    "india_sentinel2_surface_context_h3_r6.csv",
    "india_sentinel2_scene_manifest_2025.csv",
    "material_sentinel2_spatial_ablation.csv",
    "material_sentinel2_spatial_ablation_folds.csv",
    "material_official_block_transfer_validation.csv",
    "official_block_transfer_observations.csv",
    "india_strategic_materials_top50.csv",
    "india_material_ontology_v1.csv",
    "material_source_term_crosswalk_v1.csv",
    "material_ontology_validation_v1.json",
    "release_artifact_manifest.csv",
    "coverage_gap_register.csv",
    "release_governance_validation.json",
    "material_model_support.csv",
    "material_model_validation.csv",
    "ngdr_service_inventory.csv",
    "source_registry.csv",
    "data_dictionary.csv",
    "validation_report.json",
    "ibm_nmi_2025_extraction_validation.json",
    "ibm_mcdr_inspection_validation.json",
    "ibm_abandoned_mines_validation.json",
    "ibm_mineral_concessions_2024_validation.json",
    "ibm_auction_mbs_geometry_validation.json",
    "ibm_auction_status_evidence_2023_24_validation.json",
    "ngdr_service_validation.json",
    "emag2v3_magnetic_features_validation.json",
    "material_emag2_spatial_ablation.csv",
    "material_emag2_spatial_ablation_folds.csv",
    "emag2_spatial_ablation_validation.json",
    "soilgrids_v2_soil_features_validation.json",
    "material_soilgrids_spatial_ablation.csv",
    "material_soilgrids_spatial_ablation_folds.csv",
    "soilgrids_spatial_ablation_validation.json",
    "earthchem_geochemical_validation.json",
    "gsi_ogd_mineral_deposit_preview_validation.json",
    "ibm_imyb_state_review_occurrences_validation.json",
    "sentinel2_surface_context_validation.json",
    "sentinel2_spatial_ablation_validation.json",
    "official_block_transfer_validation.json",
    "nasa_power_rolling_12m_validation.json",
    "official_critical_blocks_validation.json",
    f"india_mining_dataset_csv_bundle_{VERSION}.zip",
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    missing = [name for name in BUNDLE_MEMBERS if not (ROOT / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing bundle members: {missing}")
    bundle = OUT / f"india_mining_dataset_csv_bundle_{VERSION}.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in BUNDLE_MEMBERS:
            # Fix ZIP metadata so an identical source tree produces identical
            # bundle bytes regardless of local mtimes, UID/GID or host OS.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                (ROOT / name).read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None or archive.namelist() != BUNDLE_MEMBERS:
            raise RuntimeError("Bundle integrity or member-order validation failed")
    lines = []
    for name in HASHED_ARTIFACTS:
        path = OUT / name
        if not path.exists():
            raise FileNotFoundError(path)
        lines.append(f"{sha256(path)}  outputs/{name}")
    (OUT / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
    print({"bundle": str(bundle), "members": len(BUNDLE_MEMBERS), "checksums": len(lines)})


if __name__ == "__main__":
    main()
