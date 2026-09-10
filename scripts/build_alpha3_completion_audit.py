#!/usr/bin/env python3
"""Build the machine-readable KHANAN Alpha 3.0 completion audit."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RELEASE_VERSION = "v1.0-alpha.30"
OUTPUT_PATH = OUT / "alpha3_completion_audit.json"
EXPECTED_GRID_SHA256 = "13307723efac1054666308c77b52ca0c93820a63ce535f578b23a294906136d9"
EXPECTED_CANDIDATE_SHA256 = "f730ee1c72a72764c49e95b0cf1b29873df4e32f2ceed2610e534915c760cf04"
EXPECTED_ROLES = {
    "observed_source_evidence",
    "contextual_feature",
    "model_hypothesis",
    "validation_evidence",
    "metadata_governance",
}
EVIDENCE_REQUIREMENTS = {
    "mine_and_occurrence_evidence": {
        "outputs/india_known_mining_sites.csv",
        "outputs/india_ibm_mcdr_inspection_events_2023_2026.csv",
        "outputs/india_ibm_mcdr_latest_inspected_mines.csv",
        "outputs/india_ibm_abandoned_mine_sites.csv",
    },
    "lease_and_concession_evidence": {
        "outputs/india_ibm_mining_lease_distribution_2024.csv",
        "outputs/india_ibm_auctioned_mineral_concessions_2023_24.csv",
        "outputs/india_ibm_auctioned_concession_geometries_2023_24.geojson",
    },
    "analytical_geochemistry": {
        "outputs/india_earthchem_geochemical_samples.csv",
        "outputs/india_earthchem_geochemical_observations.csv",
    },
    "geophysics": {"outputs/india_emag2v3_magnetic_features_h3_r6.csv"},
    "soil": {"outputs/india_soilgrids_v2_soil_features_h3_r6.csv"},
    "remote_sensing": {
        "outputs/india_sentinel2_surface_context_h3_r6.csv",
        "outputs/india_sentinel2_scene_manifest_2025.csv",
    },
}
STATUS_VERIFICATION_FIELDS = {
    "current_legal_or_operational_status_verified",
    "deposit_or_mine_status_verified",
}


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def csv_header(name: str) -> list[str]:
    with (OUT / name).open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle))


def sha256_file(name: str) -> str:
    digest = hashlib.sha256()
    with (OUT / name).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def source_row_hash(fields: list[str], row: dict[str, str]) -> str:
    return hashlib.sha256(
        compact_json([row.get(field, "") for field in fields]).encode("utf-8")
    ).hexdigest()


def polygon_from_wkt(value: str) -> list[list[list[float]]]:
    match = re.fullmatch(r"POLYGON \(\((.+)\)\)", value.strip())
    if not match:
        raise ValueError("unsupported WKT")
    ring = [[float(part) for part in pair.strip().split()] for pair in match.group(1).split(",")]
    return [ring]


def main() -> None:
    checks: list[dict[str, Any]] = []

    def check(requirement: str, passed: bool, evidence: Any) -> None:
        checks.append(
            {"requirement": requirement, "passed": bool(passed), "evidence": evidence}
        )

    ontology = read_csv("india_material_ontology_v1.csv")
    ontology_ids = [row["material_id"] for row in ontology]
    material_names = [row["material_name"] for row in ontology]
    ontology_errors: Counter[str] = Counter()
    for row in ontology:
        try:
            english = json.loads(row["english_names_json"])
            chemical = json.loads(row["chemical_names_json"])
            symbols = json.loads(row["symbols_or_formulae_json"])
            evidence = json.loads(row["evidence_source_ids_json"])
            if not isinstance(english, list) or not english:
                ontology_errors["missing_english_name_array"] += 1
            if not isinstance(chemical, list) or not isinstance(symbols, list):
                ontology_errors["invalid_chemical_or_symbol_array"] += 1
            if not chemical and not english:
                ontology_errors["missing_chemical_and_english_names"] += 1
            if not isinstance(evidence, list) or not evidence:
                ontology_errors["missing_evidence_lineage"] += 1
        except (json.JSONDecodeError, TypeError):
            ontology_errors["invalid_json"] += 1
        for field in ["material_id", "material_name", "entity_type", "authority_status"]:
            if not row[field].strip():
                ontology_errors[f"blank_{field}"] += 1
    check(
        "Reliable normalized material catalogue without synthetic count padding",
        len(ontology) == 254
        and len(ontology_ids) == len(set(ontology_ids))
        and len(material_names) == len(set(material_names))
        and not ontology_errors,
        {
            "entities": len(ontology),
            "entity_types": dict(sorted(Counter(row["entity_type"] for row in ontology).items())),
            "authority_statuses": dict(
                sorted(Counter(row["authority_status"] for row in ontology).items())
            ),
            "errors": dict(sorted(ontology_errors.items())),
            "interpretation": "254 is evidence-derived coverage, not a target padded to a hard ceiling or floor.",
        },
    )

    crosswalk = read_csv("material_source_term_crosswalk_v1.csv")
    mapping_counts = Counter(row["mapping_status"] for row in crosswalk)
    check(
        "Every observed material term is mapped or explicitly unresolved",
        len(crosswalk) == 611
        and mapping_counts == {"mapped": 602, "unresolved_or_nonspecific": 9},
        {"rows": len(crosswalk), "mapping_statuses": dict(sorted(mapping_counts.items()))},
    )

    manifest = read_csv("release_artifact_manifest.csv")
    manifest_paths = {row["relative_path"] for row in manifest}
    roles = set(row["evidence_role"] for row in manifest)
    source_registry = read_csv("source_registry.csv")
    registry_ids = {row["source_id"] for row in source_registry}
    unresolved_manifest_sources = set()
    for row in manifest:
        unresolved_manifest_sources.update(
            set(json.loads(row["source_ids_json"])) - registry_ids
        )
    missing_evidence = {
        family: sorted(paths - manifest_paths)
        for family, paths in EVIDENCE_REQUIREMENTS.items()
        if paths - manifest_paths
    }
    check(
        "Mine, lease, geochemistry, geophysics, soil and remote-sensing evidence is integrated",
        not missing_evidence and not unresolved_manifest_sources,
        {
            "families": {
                family: sorted(paths) for family, paths in EVIDENCE_REQUIREMENTS.items()
            },
            "missing": missing_evidence,
            "unresolved_source_ids": sorted(unresolved_manifest_sources),
        },
    )
    check(
        "Observed evidence, contextual features, validation evidence and model hypotheses are separate",
        roles == EXPECTED_ROLES,
        {
            "role_counts": dict(
                sorted(Counter(row["evidence_role"] for row in manifest).items())
            )
        },
    )

    model_validation = read_csv("material_model_validation.csv")
    auc_rows = [
        row for row in model_validation if row["spatial_holdout_pseudoabsence_roc_auc"]
    ]
    auc_gate_rows = [
        row
        for row in auc_rows
        if float(row["spatial_holdout_pseudoabsence_roc_auc"]) >= 0.60
    ]
    check(
        "Prospectivity models use spatially separated validation and disclose unsupported targets",
        len(model_validation) == 50 and len(auc_rows) == 15 and len(auc_gate_rows) == 14,
        {
            "targets": len(model_validation),
            "spatially_validated": len(auc_rows),
            "meeting_minimum_auc_gate": len(auc_gate_rows),
            "unsupported_targets_remain_unscored": True,
        },
    )

    candidate_name = "india_mining_candidate_areas_validation_gated.csv"
    candidate_fields = csv_header(candidate_name)
    candidates = read_csv(candidate_name)
    candidate_ids = [row["record_id"] for row in candidates]
    candidate_h3 = [row["h3_r6"] for row in candidates]
    ranks = [int(row["candidate_rank_national"]) for row in candidates]
    candidate_errors: Counter[str] = Counter()
    for row in candidates:
        if row["record_observation_type"] != "modelled reconnaissance screening cell":
            candidate_errors["invalid_observation_type"] += 1
        if "not discovery probability" not in row["prospectivity_index_definition"].lower():
            candidate_errors["missing_discovery_guardrail"] += 1
        try:
            flags = json.loads(row["data_quality_flags_json"])
            materials = json.loads(row["top_materials_json"])
            chemical = json.loads(row["top_material_chemical_names_json"])
            source_ids = json.loads(row["source_dataset_ids_json"])
            if "candidate_requires_field_validation" not in flags:
                candidate_errors["missing_field_validation_flag"] += 1
            if not materials or not isinstance(chemical, list):
                candidate_errors["invalid_material_arrays"] += 1
            if not source_ids or set(source_ids) - registry_ids:
                candidate_errors["invalid_source_lineage"] += 1
        except (json.JSONDecodeError, TypeError):
            candidate_errors["invalid_json"] += 1
    check(
        "Candidate rankings are complete, unique, provenance-bearing reconnaissance hypotheses",
        len(candidates) == 2784
        and len(candidate_ids) == len(set(candidate_ids))
        and len(candidate_h3) == len(set(candidate_h3))
        and ranks == list(range(1, len(candidates) + 1))
        and not candidate_errors,
        {
            "candidate_rows": len(candidates),
            "record_classes": dict(
                sorted(Counter(row["record_class"] for row in candidates).items())
            ),
            "errors": dict(sorted(candidate_errors.items())),
        },
    )
    check(
        "Published model outputs remain byte-identical to the frozen v0.6 baseline",
        sha256_file("india_mining_prospectivity_grid_h3_r6.csv")
        == EXPECTED_GRID_SHA256
        and sha256_file(candidate_name) == EXPECTED_CANDIDATE_SHA256,
        {
            "grid_sha256": sha256_file("india_mining_prospectivity_grid_h3_r6.csv"),
            "candidate_sha256": sha256_file(candidate_name),
        },
    )

    uncertainty_fields = [
        field
        for field in candidate_fields
        if re.search(r"p05|p95|uncert|error|support|spatial_cv|completeness", field)
    ]
    exclusion_fields = [
        field
        for field in candidate_fields
        if re.search(r"quality|flag|limitation|model_use|promotion|validation", field)
    ]
    required_uncertainty_fields = {
        "model_support_level",
        "top_material_spatial_cv_auc",
        "top_material_spatial_cv_recall_at_background_top5pct",
        "emag2_error_estimate_nt",
        "emag2_uncertainty_interpretation",
        "soilgrids_phh2o_0_5cm_p05",
        "soilgrids_phh2o_0_5cm_p95",
        "soilgrids_uncertainty_interpretation",
    }
    required_exclusion_fields = {
        "model_validation_tier",
        "candidate_promotion_rule",
        "model_limitations",
        "data_quality_flags_json",
        "emag2_model_use_status",
        "emag2_data_quality_flags_json",
        "soilgrids_model_use_status",
        "soilgrids_data_quality_flags_json",
    }
    check(
        "Candidate release preserves uncertainty, validation and exclusion fields",
        required_uncertainty_fields <= set(candidate_fields)
        and required_exclusion_fields <= set(candidate_fields),
        {
            "uncertainty_or_support_fields": uncertainty_fields,
            "exclusion_or_validation_fields": exclusion_fields,
            "required_uncertainty_fields_present": sorted(
                required_uncertainty_fields & set(candidate_fields)
            ),
            "required_exclusion_fields_present": sorted(
                required_exclusion_fields & set(candidate_fields)
            ),
        },
    )

    candidate_geojson = json.loads(
        (OUT / "india_mining_candidate_areas_validation_gated.geojson").read_text(
            encoding="utf-8"
        )
    )
    features = candidate_geojson.get("features", [])
    candidate_by_id = {row["record_id"]: row for row in candidates}
    geojson_errors: Counter[str] = Counter()
    for feature in features:
        record_id = str(feature.get("id", ""))
        properties = feature.get("properties", {})
        source_row = candidate_by_id.get(record_id)
        if source_row is None or properties.get("record_id") != record_id:
            geojson_errors["unmatched_record_id"] += 1
            continue
        if feature.get("geometry", {}).get("type") != "Polygon":
            geojson_errors["invalid_geometry_type"] += 1
        elif feature["geometry"].get("coordinates") != polygon_from_wkt(
            source_row["cell_boundary_wkt"]
        ):
            geojson_errors["geometry_mismatch"] += 1
        if properties.get("source_csv_row_sha256") != source_row_hash(
            candidate_fields, source_row
        ):
            geojson_errors["source_row_hash_mismatch"] += 1
        if not isinstance(properties.get("latitude"), (int, float)):
            geojson_errors["latitude_not_numeric"] += 1
        if not isinstance(properties.get("top_materials_json"), list):
            geojson_errors["material_array_not_typed"] += 1
    check(
        "Ranked candidates have an exact typed polygon GeoJSON counterpart",
        candidate_geojson.get("type") == "FeatureCollection"
        and candidate_geojson.get("release_version") == RELEASE_VERSION
        and len(features) == len(candidates)
        and {feature.get("id") for feature in features} == set(candidate_ids)
        and not geojson_errors,
        {
            "features": len(features),
            "coordinate_reference_system": candidate_geojson.get(
                "coordinate_reference_system"
            ),
            "errors": dict(sorted(geojson_errors.items())),
        },
    )

    gap_rows = read_csv("coverage_gap_register.csv")
    source_gaps = [row for row in gap_rows if row["gap_level"] == "source_specific"]
    project_gaps = [row for row in gap_rows if row["gap_level"] == "project_wide"]
    gap_categories = set()
    for row in gap_rows:
        gap_categories.update(json.loads(row["gap_categories_json"]))
    gap_by_source = {row["affected_source_id"]: row for row in source_gaps}
    gap_mapping_ok = all(
        source_id in gap_by_source
        and gap_by_source[source_id]["gap_description"] == row["limitations"]
        for source_id, row in {row["source_id"]: row for row in source_registry}.items()
    )
    required_gap_categories = {
        "geographic_coverage",
        "temporal_coverage",
        "licensing",
        "source_access",
    }
    check(
        "Final coverage report preserves every known source limitation and cross-cutting gap",
        len(source_registry) == len(source_gaps) == 38
        and len(project_gaps) == 20
        and gap_mapping_ok
        and required_gap_categories <= gap_categories,
        {
            "registered_sources": len(source_registry),
            "source_specific_gaps": len(source_gaps),
            "project_wide_gaps": len(project_gaps),
            "required_categories_present": sorted(
                required_gap_categories & gap_categories
            ),
        },
    )

    invalid_statuses: Counter[str] = Counter()
    for path in sorted(OUT.glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or []) & STATUS_VERIFICATION_FIELDS
            if not fields:
                continue
            for row in reader:
                for field in fields:
                    if row[field].strip().lower() not in {"false", "0", "no"}:
                        invalid_statuses[f"{path.name}:{field}={row[field] or '<blank>'}"] += 1
    candidate_claim_columns = sorted(
        field
        for field in candidate_fields
        if re.search(r"reserve|resource_quantity|grade|legal_right|operating_status", field)
    )
    check(
        "No model row asserts a discovery, reserve, grade, current operation or legal right",
        not invalid_statuses and not candidate_claim_columns and not candidate_errors,
        {
            "invalid_verified_statuses": dict(sorted(invalid_statuses.items())),
            "candidate_claim_columns": candidate_claim_columns,
            "field_verified_candidate_discoveries_claimed": 0,
        },
    )

    governance = json.loads(
        (OUT / "release_governance_validation.json").read_text(encoding="utf-8")
    )
    dictionary_rows = read_csv("data_dictionary.csv")
    check(
        "Release schemas, keys, dictionary and source registry are frozen and validated",
        governance.get("checks_pass") is True
        and governance.get("release_version") == RELEASE_VERSION
        and governance.get("manifest_rows") == 45
        and governance.get("csv_artifacts_registered") == 43
        and governance.get("geojson_artifacts_registered") == 2
        and governance.get("data_dictionary_rows") == len(dictionary_rows) == 1928,
        {
            "manifest_artifacts": governance.get("manifest_rows"),
            "csv_artifacts": governance.get("csv_artifacts_registered"),
            "geojson_artifacts": governance.get("geojson_artifacts_registered"),
            "data_dictionary_rows": len(dictionary_rows),
            "all_primary_keys_unique": governance.get("all_primary_keys_unique"),
        },
    )

    passed = sum(item["passed"] for item in checks)
    report = {
        "release_version": RELEASE_VERSION,
        "audit_scope": "KHANAN v1.0 objective and declared Alpha 3.0 data gates",
        "scope_boundary": (
            "Completion means the declared open-source intelligence dataset and release "
            "are reproducible and independently evaluable. It does not mean India has "
            "been exhaustively explored or that any model hypothesis is a discovery."
        ),
        "summary": {
            "requirements_total": len(checks),
            "requirements_passed": passed,
            "requirements_failed": len(checks) - passed,
        },
        "checks_pass": passed == len(checks),
        "requirements": checks,
        "publication_verification": (
            "The public repository and commit-specific artifacts are verified after the "
            "final commit is pushed; a commit hash is not embedded to avoid a hash cycle."
        ),
        "remaining_scientific_and_operational_limitations": (
            "The 58-row coverage-gap register remains authoritative. Open gaps are "
            "declared scope limitations, not hidden completion claims."
        ),
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report["summary"])
    if not report["checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
