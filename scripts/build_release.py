#!/usr/bin/env python3
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
VERSION = "v1.0-alpha.2"

BUNDLE_MEMBERS = [
    "README.md",
    "assets/README.md",
    "assets/maps/khanan-india-prospectivity-overview-v0.6.png",
    "data/README.md",
    "docs/methodology.md",
    "outputs/README.md",
    "scripts/plot_khanan_overview.py",
    "scripts/build_ibm_abandoned_mines.py",
    "scripts/build_material_ontology.py",
    "config/materials.json",
    "config/weather_window.json",
    "config/official_critical_blocks.json",
    "outputs/india_known_mining_sites.csv",
    "outputs/india_ibm_mcdr_inspection_events_2023_2026.csv",
    "outputs/india_ibm_mcdr_latest_inspected_mines.csv",
    "outputs/india_ibm_abandoned_mine_sites.csv",
    "outputs/india_ibm_nmi_2025_resource_inventory.csv",
    "outputs/india_official_critical_mineral_blocks.csv",
    "outputs/india_official_critical_mineral_mbs_manifest.csv",
    "outputs/india_mining_prospectivity_grid_h3_r6.csv",
    "outputs/india_mining_candidate_areas_validation_gated.csv",
    "outputs/india_strategic_materials_top50.csv",
    "outputs/india_material_ontology_v1.csv",
    "outputs/material_source_term_crosswalk_v1.csv",
    "outputs/material_ontology_validation_v1.json",
    "outputs/material_model_support.csv",
    "outputs/material_model_validation.csv",
    "outputs/source_registry.csv",
    "outputs/data_dictionary.csv",
    "outputs/validation_report.json",
    "outputs/ibm_nmi_2025_extraction_validation.json",
    "outputs/ibm_mcdr_inspection_validation.json",
    "outputs/ibm_abandoned_mines_validation.json",
    "outputs/nasa_power_rolling_12m_validation.json",
    "outputs/official_critical_blocks_validation.json",
]

HASHED_ARTIFACTS = [
    "india_known_mining_sites.csv",
    "india_ibm_mcdr_inspection_events_2023_2026.csv",
    "india_ibm_mcdr_latest_inspected_mines.csv",
    "india_ibm_abandoned_mine_sites.csv",
    "india_ibm_nmi_2025_resource_inventory.csv",
    "india_official_critical_mineral_blocks.csv",
    "india_official_critical_mineral_mbs_manifest.csv",
    "india_mining_prospectivity_grid_h3_r6.csv",
    "india_mining_candidate_areas_validation_gated.csv",
    "india_strategic_materials_top50.csv",
    "india_material_ontology_v1.csv",
    "material_source_term_crosswalk_v1.csv",
    "material_ontology_validation_v1.json",
    "material_model_support.csv",
    "material_model_validation.csv",
    "source_registry.csv",
    "data_dictionary.csv",
    "validation_report.json",
    "ibm_nmi_2025_extraction_validation.json",
    "ibm_mcdr_inspection_validation.json",
    "ibm_abandoned_mines_validation.json",
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
