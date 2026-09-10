#!/usr/bin/env python3
"""Independently verify the KHANAN Alpha.25 release bundle.

This verifier uses only the Python standard library.  It deliberately does
not import any KHANAN builder or packager, and it treats the ZIP, its manifest
and the optional checksum file as evaluator-supplied inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


RELEASE_VERSION = "v1.0-alpha.25"
EXPECTED_GRID_SHA256 = "13307723efac1054666308c77b52ca0c93820a63ce535f578b23a294906136d9"
EXPECTED_CANDIDATE_SHA256 = "f730ee1c72a72764c49e95b0cf1b29873df4e32f2ceed2610e534915c760cf04"
EXPECTED_ROLES = {
    "observed_source_evidence",
    "contextual_feature",
    "model_hypothesis",
    "validation_evidence",
    "metadata_governance",
}
EXPECTED_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_MODE = stat.S_IFREG | 0o644
REQUIRED_REPRODUCTION_MEMBERS = {
    "README.md",
    "requirements-geospatial.txt",
    "scripts/download_sources.py",
    "scripts/build_dataset.py",
    "scripts/build_official_mbs_inventory.py",
    "scripts/build_official_blocks.py",
    "scripts/build_ibm_nmi2025.py",
    "scripts/build_ibm_mcdr_inspections.py",
    "scripts/render_pdf_pages.py",
    "scripts/build_workbook.mjs",
    "scripts/build_release_governance.py",
    "scripts/build_release.py",
    "scripts/verify_release_independent.py",
    "docs/independent_release_verification_alpha25.md",
    "assets/maps/khanan-india-prospectivity-overview-v0.6.png",
}
STATUS_VERIFICATION_FIELDS = {
    "current_legal_or_operational_status_verified",
    "deposit_or_mine_status_verified",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_member(archive: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with archive.open(member) as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_sha(fields: Iterable[str]) -> str:
    encoded = json.dumps(
        list(fields), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def member_text(archive: zipfile.ZipFile, member: str):
    return io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="")


def read_csv_rows(archive: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    with member_text(archive, member) as handle:
        return list(csv.DictReader(handle))


def csv_stats(
    archive: zipfile.ZipFile, member: str, primary_keys: list[str]
) -> dict[str, Any]:
    with member_text(archive, member) as handle:
        reader = csv.reader(handle)
        try:
            fields = next(reader)
        except StopIteration:
            fields = []
        missing_keys = sorted(set(primary_keys) - set(fields))
        key_indexes = [fields.index(key) for key in primary_keys if key in fields]
        status_indexes = {
            name: fields.index(name)
            for name in STATUS_VERIFICATION_FIELDS
            if name in fields
        }
        rows = 0
        blank_keys = 0
        duplicates = 0
        keys: set[tuple[str, ...]] = set()
        invalid_verified_statuses: Counter[str] = Counter()
        for values in reader:
            rows += 1
            key = tuple(
                (values[index] if index < len(values) else "").strip()
                for index in key_indexes
            )
            if len(key_indexes) != len(primary_keys) or any(not value for value in key):
                blank_keys += 1
            if key in keys:
                duplicates += 1
            keys.add(key)
            for name, index in status_indexes.items():
                value = (values[index] if index < len(values) else "").strip().lower()
                if value not in {"false", "0", "no"}:
                    invalid_verified_statuses[f"{name}={value or '<blank>'}"] += 1
        return {
            "fields": fields,
            "row_count": rows,
            "blank_keys": blank_keys,
            "duplicate_keys": duplicates,
            "missing_key_fields": missing_keys,
            "invalid_verified_statuses": dict(sorted(invalid_verified_statuses.items())),
        }


def geojson_stats(
    archive: zipfile.ZipFile, member: str, primary_keys: list[str]
) -> dict[str, Any]:
    payload = json.loads(archive.read(member).decode("utf-8"))
    features = payload.get("features", [])
    fields = list(features[0].get("properties", {})) if features else []
    keys: set[tuple[str, ...]] = set()
    blank_keys = 0
    duplicates = 0
    for feature in features:
        props = feature.get("properties", {})
        key = tuple(str(props.get(name, "")).strip() for name in primary_keys)
        blank_keys += int(any(not value for value in key))
        duplicates += int(key in keys)
        keys.add(key)
    return {
        "fields": fields,
        "row_count": len(features),
        "blank_keys": blank_keys,
        "duplicate_keys": duplicates,
        "missing_key_fields": sorted(set(primary_keys) - set(fields)),
        "invalid_verified_statuses": {},
    }


def validation_gate(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "top-level JSON is not an object"
    if "checks_pass" in payload:
        return payload["checks_pass"] is True, "checks_pass"
    if "all_checks_passed" in payload:
        return payload["all_checks_passed"] is True, "all_checks_passed"
    if "status" in payload:
        value = str(payload["status"]).strip().lower()
        return value in {"pass", "passed", "ok"}, "status"
    invariance = payload.get("model_output_invariance")
    if isinstance(invariance, dict) and "unchanged" in invariance:
        return invariance["unchanged"] is True, "model_output_invariance.unchanged"
    return True, "parsed_without_global_gate"


def parse_checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"Malformed checksum line {line_number}")
        digest, relative_path = match.groups()
        if relative_path in result:
            raise ValueError(f"Duplicate checksum path: {relative_path}")
        result[relative_path] = digest
    return result


def verify(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    bundle = args.bundle.resolve()
    check("bundle_exists", bundle.is_file(), bundle.name)
    if not bundle.is_file():
        return {"release_version": RELEASE_VERSION, "checks_pass": False, "checks": checks}

    bundle_sha = sha256_file(bundle)
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        name_set = set(names)
        unsafe = []
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or not name:
                unsafe.append(name)
        check("zip_member_names_unique", len(names) == len(name_set), {"members": len(names)})
        check("zip_paths_safe", not unsafe, {"unsafe": unsafe})
        check("zip_crc_integrity", archive.testzip() is None, "all members passed CRC")
        check(
            "zip_metadata_deterministic",
            all(
                info.date_time == EXPECTED_FIXED_ZIP_TIME
                and info.create_system == 3
                and (info.external_attr >> 16) == EXPECTED_MODE
                and info.compress_type == zipfile.ZIP_DEFLATED
                for info in infos
            ),
            {
                "fixed_timestamp": list(EXPECTED_FIXED_ZIP_TIME),
                "unix_mode": "100644",
                "compression": "deflate",
            },
        )
        pdf_members = sorted(name for name in names if name.lower().endswith(".pdf"))
        check("no_source_pdfs_redistributed", not pdf_members, {"pdf_members": pdf_members})
        missing_repro = sorted(REQUIRED_REPRODUCTION_MEMBERS - name_set)
        check(
            "reproduction_inputs_present",
            not missing_repro,
            {"required": len(REQUIRED_REPRODUCTION_MEMBERS), "missing": missing_repro},
        )

        manifest_member = "outputs/release_artifact_manifest.csv"
        check("manifest_present", manifest_member in name_set, manifest_member)
        if manifest_member not in name_set:
            return {
                "release_version": RELEASE_VERSION,
                "bundle": {"name": bundle.name, "sha256": bundle_sha, "members": len(names)},
                "checks_pass": False,
                "checks": checks,
            }

        manifest_rows = read_csv_rows(archive, manifest_member)
        manifest_ids = [row.get("artifact_id", "") for row in manifest_rows]
        check(
            "manifest_inventory",
            len(manifest_rows) == 44 and len(manifest_ids) == len(set(manifest_ids)),
            {"rows": len(manifest_rows), "unique_artifact_ids": len(set(manifest_ids))},
        )
        releases = sorted(set(row.get("release_version", "") for row in manifest_rows))
        check("manifest_release_version", releases == [RELEASE_VERSION], releases)
        roles = set(row.get("evidence_role", "") for row in manifest_rows)
        check("evidence_roles_separated", roles == EXPECTED_ROLES, sorted(roles))

        manifest_paths = [row.get("relative_path", "") for row in manifest_rows]
        missing_manifest_members = sorted(set(manifest_paths) - name_set)
        check(
            "manifest_artifacts_present_in_bundle",
            not missing_manifest_members,
            {"registered": len(manifest_paths), "missing": missing_manifest_members},
        )

        referenced_builders = set()
        for row in manifest_rows:
            referenced_builders.update(
                re.findall(r"scripts/[A-Za-z0-9_./-]+\.(?:py|mjs)", row.get("build_script", ""))
            )
        missing_builders = sorted(referenced_builders - name_set)
        check(
            "manifest_builders_present_in_bundle",
            not missing_builders,
            {"referenced": len(referenced_builders), "missing": missing_builders},
        )

        artifact_results = []
        invalid_statuses: Counter[str] = Counter()
        for row in manifest_rows:
            member = row.get("relative_path", "")
            if member not in name_set:
                artifact_results.append({"artifact": member, "passed": False, "reason": "missing"})
                continue
            try:
                primary_keys = json.loads(row.get("primary_key_columns_json", "[]"))
                if row.get("artifact_type") == "tabular_csv":
                    stats_result = csv_stats(archive, member, primary_keys)
                elif row.get("artifact_type") == "vector_geojson":
                    stats_result = geojson_stats(archive, member, primary_keys)
                else:
                    raise ValueError(f"unknown artifact type {row.get('artifact_type')}")
                listed_fields = (
                    json.loads(row.get("coordinate_or_geometry_fields_json", "[]"))
                    + json.loads(row.get("uncertainty_fields_json", "[]"))
                    + json.loads(row.get("exclusion_or_quality_fields_json", "[]"))
                )
                missing_declared_fields = sorted(set(listed_fields) - set(stats_result["fields"]))
                content_hash = sha256_member(archive, member)
                is_self = member == manifest_member
                hash_ok = (
                    row.get("artifact_sha256", "") == ""
                    and row.get("artifact_sha256_status", "")
                    == "external_SHA256SUMS_only_self_reference_exception"
                ) if is_self else (
                    row.get("artifact_sha256", "") == content_hash
                    and row.get("artifact_sha256_status", "")
                    == "computed_from_release_artifact_bytes"
                )
                passed = all(
                    [
                        stats_result["row_count"] == int(row.get("row_count", "-1")),
                        len(stats_result["fields"]) == int(row.get("column_count", "-1")),
                        schema_sha(stats_result["fields"]) == row.get("schema_sha256", ""),
                        not stats_result["missing_key_fields"],
                        stats_result["blank_keys"] == 0,
                        stats_result["duplicate_keys"] == 0,
                        row.get("primary_key_unique", "").lower() == "true",
                        not missing_declared_fields,
                        hash_ok,
                    ]
                )
                invalid_statuses.update(stats_result["invalid_verified_statuses"])
                artifact_results.append(
                    {
                        "artifact": member,
                        "passed": passed,
                        "rows_or_features": stats_result["row_count"],
                        "columns_or_properties": len(stats_result["fields"]),
                        "blank_keys": stats_result["blank_keys"],
                        "duplicate_keys": stats_result["duplicate_keys"],
                        "missing_declared_fields": missing_declared_fields,
                        "hash_verified": hash_ok,
                    }
                )
            except Exception as exc:  # report all independent failures together
                artifact_results.append({"artifact": member, "passed": False, "reason": str(exc)})
        failed_artifacts = [result for result in artifact_results if not result["passed"]]
        check(
            "manifest_contracts_recomputed",
            not failed_artifacts and len(artifact_results) == 44,
            {"verified": len(artifact_results), "failed": failed_artifacts},
        )
        check(
            "unverified_current_status_preserved",
            not invalid_statuses,
            {"invalid_status_values": dict(sorted(invalid_statuses.items()))},
        )

        dictionary_rows = read_csv_rows(archive, "outputs/data_dictionary.csv")
        actual_dictionary_pairs = [(row.get("table", ""), row.get("column", "")) for row in dictionary_rows]
        expected_dictionary_pairs = []
        for row in sorted(
            (item for item in manifest_rows if item.get("artifact_type") == "tabular_csv"),
            key=lambda item: Path(item["relative_path"]).name,
        ):
            member = row["relative_path"]
            with member_text(archive, member) as handle:
                fields = next(csv.reader(handle))
            expected_dictionary_pairs.extend((Path(member).name, field) for field in fields)
        check(
            "data_dictionary_exact_column_coverage",
            actual_dictionary_pairs == expected_dictionary_pairs
            and len(actual_dictionary_pairs) == len(set(actual_dictionary_pairs)),
            {
                "rows": len(actual_dictionary_pairs),
                "expected": len(expected_dictionary_pairs),
                "duplicate_pairs": len(actual_dictionary_pairs) - len(set(actual_dictionary_pairs)),
            },
        )

        source_rows = read_csv_rows(archive, "outputs/source_registry.csv")
        gap_rows = read_csv_rows(archive, "outputs/coverage_gap_register.csv")
        source_limitations = {row["source_id"]: row["limitations"] for row in source_rows}
        source_gap_rows = [row for row in gap_rows if row.get("gap_level") == "source_specific"]
        project_gap_rows = [row for row in gap_rows if row.get("gap_level") == "project_wide"]
        gap_by_source = {row.get("affected_source_id", ""): row for row in source_gap_rows}
        gap_mapping_ok = (
            len(source_rows) == len(source_gap_rows) == 38
            and len(gap_by_source) == 38
            and set(gap_by_source) == set(source_limitations)
            and all(
                gap_by_source[source_id].get("gap_description") == limitation
                for source_id, limitation in source_limitations.items()
            )
        )
        check(
            "source_limitations_map_to_gap_register",
            gap_mapping_ok,
            {
                "sources": len(source_rows),
                "source_specific_gaps": len(source_gap_rows),
                "project_wide_gaps": len(project_gap_rows),
            },
        )
        check("project_wide_gap_inventory", len(project_gap_rows) == 20, len(project_gap_rows))

        validation_members = sorted(set(row.get("validation_artifact", "") for row in manifest_rows))
        validation_results = []
        for member in validation_members:
            if member not in name_set:
                validation_results.append({"artifact": member, "passed": False, "gate": "missing"})
                continue
            try:
                payload = json.loads(archive.read(member).decode("utf-8"))
                passed, gate = validation_gate(payload)
                validation_results.append({"artifact": member, "passed": passed, "gate": gate})
            except Exception as exc:
                validation_results.append({"artifact": member, "passed": False, "gate": str(exc)})
        failed_validations = [item for item in validation_results if not item["passed"]]
        check(
            "validation_artifacts_parse_and_pass_declared_gates",
            not failed_validations,
            {
                "validation_artifacts": len(validation_results),
                "failed": failed_validations,
                "without_global_gate": sum(
                    item["gate"] == "parsed_without_global_gate" for item in validation_results
                ),
            },
        )

        grid_member = "outputs/india_mining_prospectivity_grid_h3_r6.csv"
        candidate_member = "outputs/india_mining_candidate_areas_validation_gated.csv"
        grid_hash = sha256_member(archive, grid_member)
        candidate_hash = sha256_member(archive, candidate_member)
        check(
            "model_output_hashes_unchanged",
            grid_hash == EXPECTED_GRID_SHA256 and candidate_hash == EXPECTED_CANDIDATE_SHA256,
            {"grid_sha256": grid_hash, "candidate_sha256": candidate_hash},
        )

        candidate_rows = read_csv_rows(archive, candidate_member)
        candidate_fields = list(candidate_rows[0]) if candidate_rows else []
        required_model_fields = {
            "record_id",
            "record_class",
            "top_material",
            "top_materials_json",
            "top_material_chemical_names_json",
            "top_material_symbols_or_formulae_json",
            "prospectivity_score_max",
            "top_material_percentile",
            "candidate_rank_national",
            "candidate_promotion_rule",
            "model_version",
            "prospectivity_index_definition",
            "model_limitations",
            "record_observation_type",
            "data_quality_flags_json",
        }
        missing_model_fields = sorted(required_model_fields - set(candidate_fields))
        candidate_ids = set()
        candidate_by_id: dict[str, tuple[str, ...]] = {}
        ranks = []
        candidate_guardrail_errors: Counter[str] = Counter()
        for row in candidate_rows:
            record_id = row.get("record_id", "")
            candidate_ids.add(record_id)
            candidate_by_id[record_id] = tuple(row.get(field, "") for field in candidate_fields)
            for field in required_model_fields - {"record_id"}:
                if not row.get(field, "").strip():
                    candidate_guardrail_errors[f"blank_{field}"] += 1
            try:
                ranks.append(int(row.get("candidate_rank_national", "")))
            except ValueError:
                candidate_guardrail_errors["invalid_candidate_rank_national"] += 1
            if row.get("record_class") not in {"priority_candidate", "high_priority_candidate"}:
                candidate_guardrail_errors["invalid_record_class"] += 1
            if row.get("record_observation_type") != "modelled reconnaissance screening cell":
                candidate_guardrail_errors["invalid_observation_type"] += 1
            if "not discovery probability" not in row.get("prospectivity_index_definition", "").lower():
                candidate_guardrail_errors["missing_not_discovery_probability_guardrail"] += 1
            try:
                flags = json.loads(row.get("data_quality_flags_json", "[]"))
                materials = json.loads(row.get("top_materials_json", "[]"))
                chemical_names = json.loads(row.get("top_material_chemical_names_json", "[]"))
                symbols = json.loads(row.get("top_material_symbols_or_formulae_json", "[]"))
                if "candidate_requires_field_validation" not in flags:
                    candidate_guardrail_errors["missing_field_validation_flag"] += 1
                if not isinstance(materials, list) or not materials:
                    candidate_guardrail_errors["invalid_material_array"] += 1
                if not isinstance(chemical_names, list) or not isinstance(symbols, list):
                    candidate_guardrail_errors["invalid_chemical_array"] += 1
            except json.JSONDecodeError:
                candidate_guardrail_errors["invalid_json_array"] += 1
        if ranks != list(range(1, len(candidate_rows) + 1)):
            candidate_guardrail_errors["candidate_ranks_not_contiguous_in_file_order"] += 1

        grid_candidate_ids = set()
        grid_subset_mismatches = 0
        with member_text(archive, grid_member) as handle:
            reader = csv.DictReader(handle)
            grid_fields = reader.fieldnames or []
            for row in reader:
                if row.get("record_class") in {"priority_candidate", "high_priority_candidate"}:
                    record_id = row.get("record_id", "")
                    grid_candidate_ids.add(record_id)
                    expected = candidate_by_id.get(record_id)
                    observed = tuple(row.get(field, "") for field in candidate_fields)
                    if expected is None or candidate_fields != grid_fields or expected != observed:
                        grid_subset_mismatches += 1
        check(
            "candidate_hypothesis_guardrails",
            not missing_model_fields
            and not candidate_guardrail_errors
            and len(candidate_ids) == len(candidate_rows),
            {
                "candidate_rows": len(candidate_rows),
                "unique_ids": len(candidate_ids),
                "missing_fields": missing_model_fields,
                "errors": dict(sorted(candidate_guardrail_errors.items())),
            },
        )
        check(
            "candidate_is_exact_grid_subset",
            candidate_ids == grid_candidate_ids and grid_subset_mismatches == 0,
            {
                "candidate_ids": len(candidate_ids),
                "grid_candidate_ids": len(grid_candidate_ids),
                "row_mismatches": grid_subset_mismatches,
            },
        )

        model_rows = [row for row in manifest_rows if row.get("evidence_role") == "model_hypothesis"]
        model_role_ok = len(model_rows) == 2 and all(
            all(
                term in (row.get("role_definition", "") + " " + row.get("limitations", "")).lower()
                for term in ["discovery", "reserve", "grade", "legal"]
            )
            for row in model_rows
        )
        check(
            "model_hypotheses_disclaim_unsupported_claims",
            model_role_ok,
            {"model_hypothesis_artifacts": [row.get("relative_path") for row in model_rows]},
        )

        workspace_result: dict[str, Any] = {"requested": args.workspace is not None}
        if args.workspace is not None:
            workspace = args.workspace.resolve()
            mismatches = []
            missing_workspace = []
            for member in names:
                path = workspace / member
                if not path.is_file():
                    missing_workspace.append(member)
                elif sha256_file(path) != sha256_member(archive, member):
                    mismatches.append(member)
            workspace_result.update(
                {
                    "members_compared": len(names),
                    "missing": missing_workspace,
                    "mismatched": mismatches,
                }
            )
            check(
                "bundle_members_byte_identical_to_workspace",
                not missing_workspace and not mismatches,
                workspace_result,
            )

        checksum_result: dict[str, Any] = {"requested": args.checksums is not None}
        if args.checksums is not None:
            checksum_path = args.checksums.resolve()
            try:
                checksum_rows = parse_checksums(checksum_path)
                verified = 0
                missing_checksum_targets = []
                checksum_mismatches = []
                for relative_path, expected_hash in checksum_rows.items():
                    if relative_path == f"outputs/{bundle.name}":
                        actual_hash = bundle_sha
                    elif relative_path in name_set:
                        actual_hash = sha256_member(archive, relative_path)
                    elif args.workspace is not None and (args.workspace.resolve() / relative_path).is_file():
                        actual_hash = sha256_file(args.workspace.resolve() / relative_path)
                    else:
                        missing_checksum_targets.append(relative_path)
                        continue
                    verified += 1
                    if actual_hash != expected_hash:
                        checksum_mismatches.append(relative_path)
                missing_manifest_checksums = sorted(set(manifest_paths) - set(checksum_rows))
                checksum_result.update(
                    {
                        "file_sha256": sha256_file(checksum_path),
                        "declared": len(checksum_rows),
                        "verified": verified,
                        "missing_targets": missing_checksum_targets,
                        "mismatches": checksum_mismatches,
                        "manifest_artifacts_without_checksum": missing_manifest_checksums,
                    }
                )
                checksum_ok = (
                    not missing_checksum_targets
                    and not checksum_mismatches
                    and not missing_manifest_checksums
                )
            except Exception as exc:
                checksum_result["error"] = str(exc)
                checksum_ok = False
            check("external_checksums_verified", checksum_ok, checksum_result)

    passed_count = sum(item["passed"] for item in checks)
    report = {
        "release_version": RELEASE_VERSION,
        "verification_method": "Python standard library; no KHANAN builder or packager imports",
        "bundle": {"name": bundle.name, "sha256": bundle_sha, "members": len(names)},
        "workspace_comparison": workspace_result,
        "checksum_verification": checksum_result,
        "summary": {
            "checks_total": len(checks),
            "checks_passed": passed_count,
            "checks_failed": len(checks) - passed_count,
            "manifest_artifacts_verified": len(artifact_results),
            "candidate_rows_verified": len(candidate_rows),
        },
        "checks_pass": passed_count == len(checks),
        "checks": checks,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args)
    except Exception as exc:
        report = {
            "release_version": RELEASE_VERSION,
            "verification_method": "Python standard library; no KHANAN builder or packager imports",
            "checks_pass": False,
            "summary": {"checks_total": 1, "checks_passed": 0, "checks_failed": 1},
            "checks": [
                {"check": "fatal_verifier_error", "passed": False, "detail": str(exc)}
            ],
        }
    if "summary" not in report:
        report["summary"] = {
            "checks_total": len(report.get("checks", [])),
            "checks_passed": sum(item.get("passed") is True for item in report.get("checks", [])),
            "checks_failed": sum(item.get("passed") is not True for item in report.get("checks", [])),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    if not report["checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
