#!/usr/bin/env python3
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
VERSION = "v1.0-alpha.11"

BUNDLE_MEMBERS = [
    "README.md",
    "assets/README.md",
    "assets/maps/khanan-india-prospectivity-overview-v0.6.png",
    "assets/maps/khanan-emag2-magnetic-context-v0.7.png",
    "assets/maps/khanan-soilgrids-context-v0.8.png",
    "assets/maps/khanan-ibm-auction-mbs-geometries-alpha11.png",
    "assets/figures/khanan-emag2-spatial-ablation-v0.1.png",
    "assets/figures/khanan-soilgrids-spatial-ablation-v0.1.png",
    "data/README.md",
    "docs/methodology.md",
    "docs/ibm_mineral_concessions_2024.md",
    "docs/ibm_auction_mbs_geometry_2023_24.md",
    "docs/emag2_spatial_ablation.md",
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
    "scripts/plot_ibm_auction_mbs_geometries.py",
    "scripts/build_material_ontology.py",
    "config/materials.json",
    "config/weather_window.json",
    "config/official_critical_blocks.json",
    "outputs/india_known_mining_sites.csv",
    "outputs/india_ibm_mcdr_inspection_events_2023_2026.csv",
    "outputs/india_ibm_mcdr_latest_inspected_mines.csv",
    "outputs/india_ibm_abandoned_mine_sites.csv",
    "outputs/india_ibm_mining_lease_distribution_2024.csv",
    "outputs/india_ibm_auctioned_mineral_concessions_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_geometries_2023_24.csv",
    "outputs/india_ibm_auctioned_concession_geometries_2023_24.geojson",
    "outputs/india_ibm_nmi_2025_resource_inventory.csv",
    "outputs/india_official_critical_mineral_blocks.csv",
    "outputs/india_official_critical_mineral_mbs_manifest.csv",
    "outputs/india_mining_prospectivity_grid_h3_r6.csv",
    "outputs/india_mining_candidate_areas_validation_gated.csv",
    "outputs/india_emag2v3_magnetic_features_h3_r6.csv",
    "outputs/india_soilgrids_v2_soil_features_h3_r6.csv",
    "outputs/india_strategic_materials_top50.csv",
    "outputs/india_material_ontology_v1.csv",
    "outputs/material_source_term_crosswalk_v1.csv",
    "outputs/material_ontology_validation_v1.json",
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
    "outputs/ngdr_service_validation.json",
    "outputs/emag2v3_magnetic_features_validation.json",
    "outputs/material_emag2_spatial_ablation.csv",
    "outputs/material_emag2_spatial_ablation_folds.csv",
    "outputs/emag2_spatial_ablation_validation.json",
    "outputs/soilgrids_v2_soil_features_validation.json",
    "outputs/material_soilgrids_spatial_ablation.csv",
    "outputs/material_soilgrids_spatial_ablation_folds.csv",
    "outputs/soilgrids_spatial_ablation_validation.json",
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
    "india_ibm_nmi_2025_resource_inventory.csv",
    "india_official_critical_mineral_blocks.csv",
    "india_official_critical_mineral_mbs_manifest.csv",
    "india_mining_prospectivity_grid_h3_r6.csv",
    "india_mining_candidate_areas_validation_gated.csv",
    "india_emag2v3_magnetic_features_h3_r6.csv",
    "india_soilgrids_v2_soil_features_h3_r6.csv",
    "india_strategic_materials_top50.csv",
    "india_material_ontology_v1.csv",
    "material_source_term_crosswalk_v1.csv",
    "material_ontology_validation_v1.json",
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
    "ngdr_service_validation.json",
    "emag2v3_magnetic_features_validation.json",
    "material_emag2_spatial_ablation.csv",
    "material_emag2_spatial_ablation_folds.csv",
    "emag2_spatial_ablation_validation.json",
    "soilgrids_v2_soil_features_validation.json",
    "material_soilgrids_spatial_ablation.csv",
    "material_soilgrids_spatial_ablation_folds.csv",
    "soilgrids_spatial_ablation_validation.json",
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
            archive.write(ROOT / name, arcname=name)
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
