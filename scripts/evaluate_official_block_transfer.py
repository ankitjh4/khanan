#!/usr/bin/env python3
"""Evaluate v0.6 material scores against held-out official auction blocks.

The central and State auction/MBS layers are excluded from KHANAN training and
scoring.  This script treats their unique source footprints as an external
alignment set, recomputes every v0.6 material score exactly, and compares block
centroid scores with deterministic background cells more than 25 km from both
MRDS evidence and an official block for the same material.

Official auction or exploration targeting is not a confirmed deposit label and
can reflect earlier geological knowledge.  Results are diagnostic only and do
not rewrite the national grid, candidate classes, scores, or ranks.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.neighbors import BallTree


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"
KNOWN_PATH = OUT / "india_known_mining_sites.csv"
MATERIAL_CONFIG_PATH = ROOT / "config" / "materials.json"
MODEL_SUPPORT_PATH = OUT / "material_model_support.csv"
CENTRAL_BLOCK_PATH = OUT / "india_official_critical_mineral_blocks.csv"
STATE_BLOCK_PATH = OUT / "india_ibm_auctioned_concession_geometries_2023_24.csv"

SUMMARY_PATH = OUT / "material_official_block_transfer_validation.csv"
OBSERVATION_PATH = OUT / "official_block_transfer_observations.csv"
VALIDATION_PATH = OUT / "official_block_transfer_validation.json"

RELEASE_VERSION = "v1.0-alpha.20"
EXPERIMENT_VERSION = "official-block-transfer-v0.1"
MODEL_VERSION = "recon-screening-v0.1.0"
EARTH_RADIUS_KM = 6371.0088
GLOBAL_SEED = 20260910
BOOTSTRAP_REPLICATES = 500
PRIMARY_EXCLUSION_KM = 25.0
CANDIDATE_MAX_DISTANCE_KM = 250.0
MIN_EVALUATION_BLOCKS = 5
MIN_EVALUATION_GROUPS = 3
MIN_GATE_BLOCKS = 10
MIN_GATE_GROUPS = 4
MIN_GATE_AUC = 0.60
MIN_GATE_RECALL = 0.20
MIN_GATE_TOP5_RATE = 0.20
SOURCE_LABEL_INDEPENDENCE_RESOLVED = False


SUMMARY_FIELDS = {
    "record_id": ("Stable material-level transfer-evaluation identifier.", "text", ""),
    "material_name": ("Normalized v0.6 modeling-target name.", "text", ""),
    "priority_rank": ("Priority order in the retained top-50 target configuration.", "integer", "rank"),
    "known_evidence_records": ("MRDS records used by the published full-data material score.", "integer", "records"),
    "internal_spatial_cv_auc": ("Published v0.6 grouped spatial-holdout ROC-AUC against pseudo-absence background.", "number", "0-1"),
    "internal_spatial_cv_recall_at_background_top5pct": ("Published v0.6 held-out-positive recall at the background 95th-percentile threshold.", "number", "0-1"),
    "official_block_material_pairs": ("Unique official block centroids carrying the material after central reoffer deduplication.", "integer", "block-material pairs"),
    "central_critical_block_pairs": ("Material pairs from unique central critical-mineral auction block lineages.", "integer", "block-material pairs"),
    "state_auction_mbs_block_pairs": ("Material pairs from admitted 2023-24 State auction MBS footprints.", "integer", "block-material pairs"),
    "outside_25km_official_block_pairs": ("Official block-material pairs whose centroids exceed 25 km from any training occurrence for the material.", "integer", "block-material pairs"),
    "candidate_distance_domain_pairs": ("Official pairs more than 25 km and no more than 250 km from training evidence for the material.", "integer", "block-material pairs"),
    "primary_transfer_positive_blocks": ("Outside-25-km official block pairs used as positive observations when evaluation support is sufficient.", "integer", "blocks"),
    "primary_transfer_positive_h3_r3_groups": ("Distinct H3 resolution-3 groups among primary positive blocks.", "integer", "groups"),
    "background_cells_sampled": ("Deterministically sampled background cells beyond 25 km from training evidence and official block centroids.", "integer", "cells"),
    "transfer_roc_auc": ("ROC-AUC separating official block centroids from sampled background using the unchanged target-material score.", "number", "0-1"),
    "transfer_roc_auc_ci95_low": ("Lower 2.5th percentile of the paired spatial-group bootstrap transfer ROC-AUC.", "number", "0-1"),
    "transfer_roc_auc_ci95_high": ("Upper 97.5th percentile of the paired spatial-group bootstrap transfer ROC-AUC.", "number", "0-1"),
    "transfer_average_precision": ("Average precision against the deterministic sampled background; depends on the published sampling ratio.", "number", "0-1"),
    "transfer_recall_at_background_top5pct": ("Share of official blocks scoring at or above the sampled-background 95th percentile.", "number", "0-1"),
    "transfer_recall_ci95_low": ("Lower spatial-group bootstrap bound for transfer recall at the background top 5 percent.", "number", "0-1"),
    "transfer_recall_ci95_high": ("Upper spatial-group bootstrap bound for transfer recall at the background top 5 percent.", "number", "0-1"),
    "official_block_median_national_percentile": ("Median target-material national percentile across primary official block centroids.", "number", "0-1"),
    "official_block_share_at_or_above_p95": ("Share of primary official blocks at or above the target-material 95th national percentile.", "number", "0-1"),
    "official_block_share_at_or_above_p99": ("Share of primary official blocks at or above the target-material 99th national percentile.", "number", "0-1"),
    "official_block_share_at_or_above_p995": ("Share of primary official blocks at or above the target-material 99.5th national percentile.", "number", "0-1"),
    "target_material_top1_rate": ("Share of primary official blocks whose published v0.6 top material equals the source target.", "number", "0-1"),
    "target_material_top5_rate": ("Share of primary official blocks whose source target appears in the published v0.6 top-five materials.", "number", "0-1"),
    "published_candidate_centroid_rate": ("Share of primary official blocks whose centroid cell is a published priority or high-priority candidate for any top material.", "number", "0-1"),
    "target_specific_priority_gate_rate": ("Share of primary official blocks satisfying the v0.6 priority thresholds when applied to the source target itself.", "number", "0-1"),
    "minimum_positive_to_known_evidence_km": ("Minimum target-material distance from an evaluated official block centroid to training evidence.", "number", "km"),
    "transfer_evaluation_status": ("Reason the material was or was not evaluated.", "category", ""),
    "passes_predeclared_statistical_gate": ("Whether support, internal validation, transfer AUC/CI, recall, and top-five retrieval thresholds all pass.", "boolean", ""),
    "source_label_independence_resolved": ("Whether official targeting is proven independent of all historical knowledge represented by the training source.", "boolean", ""),
    "passes_production_admission_gate": ("Whether statistical criteria and source-label independence both permit production admission.", "boolean", ""),
    "candidate_scores_recomputed": ("Whether the experiment rewrote candidate scores or classes.", "boolean", ""),
    "production_scoring_changed": ("Whether the experiment changed the v0.6 production scoring recipe or ranking.", "boolean", ""),
    "interpretation": ("Material-specific interpretation and limitations of the transfer result.", "text", ""),
}


OBSERVATION_FIELDS = {
    "record_id": ("Stable official block-material transfer-observation identifier.", "text", ""),
    "source_family": ("Official source family supplying the held-out block footprint.", "category", ""),
    "source_record_id": ("Canonical source row or lineage key for the official block.", "text", ""),
    "source_event_record_ids_json": ("Central reoffer event IDs represented by the deduplicated block, or the single State record ID.", "json", ""),
    "source_event_count": ("Number of source event rows represented by the unique block footprint.", "integer", "events"),
    "block_name": ("Official block name selected for the canonical record.", "text", ""),
    "block_name_aliases_json": ("Distinct source block-name variants across deduplicated events.", "json", ""),
    "state_or_ut": ("Source-stated Indian State or Union Territory.", "text", ""),
    "district": ("Source-stated district when available.", "text", ""),
    "block_area_ha": ("Source-published block or concession area when available.", "number", "ha"),
    "exploration_level": ("Source-published exploration level when available.", "text", ""),
    "latitude": ("Official block centroid latitude.", "number", "degrees north"),
    "longitude": ("Official block centroid longitude.", "number", "degrees east"),
    "h3_r6": ("H3 resolution-6 cell containing the official block centroid.", "text", ""),
    "h3_r3": ("H3 resolution-3 group used for spatial uncertainty resampling.", "text", ""),
    "target_material": ("Normalized v0.6 material named by the official source for the block.", "text", ""),
    "target_chemical_names_json": ("Configured chemical names for the target material.", "json", ""),
    "target_symbols_or_formulae_json": ("Configured symbols or formulae for the target material.", "json", ""),
    "source_label_type": ("Scientific interpretation of the official held-out label.", "category", ""),
    "geometry_quality_status": ("Input geometry-admission status from the authoritative source audit.", "category", ""),
    "geometry_model_role": ("Input contract excluding the block from v0.6 training and scoring.", "category", ""),
    "geometry_source_url": ("Official source document containing the block geometry.", "url", ""),
    "source_url": ("Official source record or document URL.", "url", ""),
    "target_known_evidence_records": ("MRDS records used by the published full-data target score.", "integer", "records"),
    "internal_spatial_cv_auc": ("Published v0.6 grouped spatial-holdout AUC for the target material.", "number", "0-1"),
    "internal_spatial_cv_recall_at_background_top5pct": ("Published v0.6 grouped spatial-holdout recall for the target material.", "number", "0-1"),
    "nearest_known_target_evidence_km": ("Distance from the block centroid to the nearest training occurrence for the target material.", "number", "km"),
    "outside_25km_known_evidence": ("Whether the block centroid exceeds the primary 25 km training-evidence exclusion.", "boolean", ""),
    "within_250km_known_evidence": ("Whether the block centroid is no more than 250 km from target-material training evidence.", "boolean", ""),
    "primary_transfer_cohort": ("Whether the pair enters the primary outside-25-km transfer cohort before minimum-support checks.", "boolean", ""),
    "candidate_distance_domain": ("Whether the pair falls in the published greater-than-25-to-250-km candidate distance domain.", "boolean", ""),
    "target_prospectivity_score": ("Exact v0.6 full-data score for the source target at the block centroid cell.", "number", "0-1"),
    "target_national_percentile": ("Exact v0.6 target-material national percentile for the centroid cell among cells beyond 10 km from training evidence.", "number", "0-1"),
    "target_score_rank_among_50": ("Competitive rank of the source target score among the 50 configured material scores at the centroid.", "integer", "rank"),
    "target_is_centroid_top1": ("Whether the source target equals the published top material at the centroid.", "boolean", ""),
    "target_in_centroid_top5": ("Whether the source target appears in the published top-five material list at the centroid.", "boolean", ""),
    "centroid_published_top_material": ("Published top material at the official block centroid.", "text", ""),
    "centroid_published_record_class": ("Published v0.6 record class at the official block centroid.", "category", ""),
    "centroid_is_published_candidate": ("Whether the centroid is a published priority or high-priority candidate for its top material.", "boolean", ""),
    "target_specific_priority_gate": ("Whether the source target itself meets the v0.6 minimum support, internal AUC, distance, percentile, and score thresholds.", "boolean", ""),
    "source_label_limitations": ("Why an official auction/exploration target is not a confirmed deposit or discovery label.", "text", ""),
    "data_quality_flags_json": ("Record-level transfer-evaluation limitations and exclusions.", "json", ""),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def safe_float(value):
    return None if pd.isna(value) else float(value)


def score_all_materials(
    grid: pd.DataFrame,
    known: pd.DataFrame,
    materials: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """Reproduce the published full-data v0.6 scores for all 50 targets."""
    coords = np.radians(grid[["latitude", "longitude"]].to_numpy())
    all_unit_counts = known["geology_geom_id"].value_counts(dropna=True)
    score_matrix = np.full((len(grid), len(materials)), np.nan, dtype="float32")
    percentile_matrix = np.full_like(score_matrix, np.nan)
    distance_matrix = np.full_like(score_matrix, np.nan)
    support_counts: list[int] = []

    for material_index, material in enumerate(materials):
        name = material["material_name"]
        evidence = known[known["_priority_materials"].map(lambda values: name in values)]
        n = len(evidence)
        support_counts.append(n)
        if n == 0:
            continue
        tree = BallTree(
            np.radians(evidence[["latitude", "longitude"]].to_numpy()),
            metric="haversine",
        )
        distance, _ = tree.query(coords, k=1)
        distance_km = distance[:, 0] * EARTH_RADIUS_KM
        density = tree.query_radius(
            coords, r=100.0 / EARTH_RADIUS_KM, count_only=True
        ).astype(float)
        distance_score = np.exp(-distance_km / 100.0)
        density_scale = max(float(np.percentile(density, 95)), 1.0)
        density_score = np.clip(density / density_scale, 0, 1)

        positive_unit_counts = evidence["geology_geom_id"].value_counts(dropna=True)
        raw_geology = {
            unit: (float(count) + 0.5) / (float(all_unit_counts.get(unit, 0)) + 5.0)
            for unit, count in positive_unit_counts.items()
        }
        geology_values = grid["geology_geom_id"].map(raw_geology).fillna(0).to_numpy(float)
        if raw_geology:
            geology_scale = max(float(np.percentile(list(raw_geology.values()), 95)), 1e-9)
            geology_score = np.clip(geology_values / geology_scale, 0, 1)
        else:
            geology_score = np.zeros(len(grid), dtype=float)

        if n >= 5:
            combined = 0.50 * geology_score + 0.35 * distance_score + 0.15 * density_score
        else:
            combined = 0.80 * distance_score + 0.20 * density_score
        support_weight = 0.4 + 0.6 * min(1.0, math.log1p(n) / math.log1p(20))
        combined = np.clip(combined * support_weight, 0, 1)
        score_matrix[:, material_index] = combined.astype("float32")
        distance_matrix[:, material_index] = distance_km.astype("float32")
        if n >= 5:
            eligible = distance_km > 10.0
            percentiles = np.full(len(grid), np.nan, dtype=float)
            percentiles[eligible] = rankdata(combined[eligible], method="average") / eligible.sum()
            percentile_matrix[:, material_index] = percentiles.astype("float32")
    return score_matrix, percentile_matrix, distance_matrix, support_counts


def validate_score_parity(
    grid: pd.DataFrame,
    material_index: dict[str, int],
    scores: np.ndarray,
    percentiles: np.ndarray,
    distances: np.ndarray,
) -> dict:
    score_mismatches = 0
    percentile_mismatches = 0
    distance_mismatches = 0
    comparisons = 0
    for row_number, row in grid.iterrows():
        names = json.loads(row["top_materials_json"])
        published_scores = json.loads(row["top_material_scores_json"])
        published_percentiles = json.loads(row["top_material_percentiles_json"])
        published_distances = json.loads(row["top_material_nearest_known_km_json"])
        for name, published_score, published_percentile, published_distance in zip(
            names,
            published_scores,
            published_percentiles,
            published_distances,
        ):
            index = material_index[name]
            comparisons += 1
            if round(float(scores[row_number, index]), 4) != published_score:
                score_mismatches += 1
            calculated_percentile = (
                None
                if np.isnan(percentiles[row_number, index])
                else round(float(percentiles[row_number, index]), 5)
            )
            if calculated_percentile != published_percentile:
                percentile_mismatches += 1
            if round(float(distances[row_number, index]), 2) != published_distance:
                distance_mismatches += 1
    return {
        "top5_value_comparisons": comparisons,
        "score_mismatches": score_mismatches,
        "percentile_mismatches": percentile_mismatches,
        "distance_mismatches": distance_mismatches,
        "exact_published_score_parity": not any(
            [score_mismatches, percentile_mismatches, distance_mismatches]
        ),
    }


def canonical_central_blocks(frame: pd.DataFrame) -> pd.DataFrame:
    offered = frame[
        frame["auction_event_kind"].eq("auction_offer")
        & frame["geometry_quality_flag"].eq("accepted")
        & frame["block_boundary_wkt"].notna()
    ].copy()
    offered["_tranche_number"] = pd.to_numeric(offered["auction_tranche"], errors="coerce")
    offered = offered.sort_values(
        ["block_lineage_key", "_tranche_number", "source_date", "record_id"],
        na_position="first",
    )
    rows = []
    for lineage, group in offered.groupby("block_lineage_key", sort=True):
        selected = group.iloc[-1]
        rows.append(
            {
                "source_family": "central_critical_mineral_auction",
                "source_record_id": lineage,
                "source_event_record_ids_json": jdump(sorted(group["record_id"].tolist())),
                "source_event_count": int(len(group)),
                "block_name": selected["block_name"],
                "block_name_aliases_json": jdump(sorted(group["block_name"].dropna().unique().tolist())),
                "state_or_ut": selected["state_or_ut"],
                "district": selected["district"],
                "block_area_ha": safe_float(selected["block_area_ha"]),
                "exploration_level": "",
                "latitude": float(selected["latitude"]),
                "longitude": float(selected["longitude"]),
                "materials": json.loads(selected["normalized_top50_materials_json"]),
                "geometry_quality_status": selected["geometry_quality_flag"],
                "geometry_model_role": selected["integration_status"],
                "geometry_source_url": selected["geometry_source_url"],
                "source_url": selected["source_url"],
            }
        )
    return pd.DataFrame(rows)


def canonical_state_blocks(frame: pd.DataFrame, target_names: set[str]) -> pd.DataFrame:
    admitted = frame[
        frame["geometry_admission_status"].eq(
            "admitted_authoritative_source_footprint"
        )
        & frame["polygon_wkt"].notna()
    ].copy()
    rows = []
    for _, selected in admitted.sort_values("record_id").iterrows():
        materials = [
            name
            for name in json.loads(selected["normalized_material_names_json"])
            if name in target_names
        ]
        rows.append(
            {
                "source_family": "ibm_2023_24_state_auction_mbs",
                "source_record_id": selected["record_id"],
                "source_event_record_ids_json": jdump([selected["record_id"]]),
                "source_event_count": 1,
                "block_name": selected["block_name"],
                "block_name_aliases_json": jdump([selected["block_name"]]),
                "state_or_ut": selected["state_or_ut"],
                "district": "",
                "block_area_ha": safe_float(selected["ibm_area_ha"]),
                "exploration_level": selected["exploration_level"],
                "latitude": float(selected["centroid_latitude"]),
                "longitude": float(selected["centroid_longitude"]),
                "materials": materials,
                "geometry_quality_status": selected["geometry_admission_status"],
                "geometry_model_role": selected["model_evidence_role"],
                "geometry_source_url": selected["selected_mbs_url"],
                "source_url": selected["selected_mbs_url"],
            }
        )
    return pd.DataFrame(rows)


def build_observations(
    blocks: pd.DataFrame,
    grid: pd.DataFrame,
    materials: list[dict],
    support: pd.DataFrame,
    scores: np.ndarray,
    percentiles: np.ndarray,
    distances: np.ndarray,
    support_counts: list[int],
) -> pd.DataFrame:
    material_index = {item["material_name"]: i for i, item in enumerate(materials)}
    material_by_name = {item["material_name"]: item for item in materials}
    support_by_name = support.set_index("material_name")
    grid_index = {value: index for index, value in enumerate(grid["h3_r6"])}
    rows = []
    for _, block in blocks.iterrows():
        h3_r6 = h3.latlng_to_cell(block["latitude"], block["longitude"], 6)
        h3_r3 = h3.latlng_to_cell(block["latitude"], block["longitude"], 3)
        if h3_r6 not in grid_index:
            raise RuntimeError(f"official block centroid does not join the India grid: {block['source_record_id']}")
        grid_row_number = grid_index[h3_r6]
        grid_row = grid.iloc[grid_row_number]
        published_top5 = json.loads(grid_row["top_materials_json"])
        centroid_scores = scores[grid_row_number]
        for target in block["materials"]:
            index = material_index[target]
            target_score = scores[grid_row_number, index]
            target_percentile = percentiles[grid_row_number, index]
            target_distance = distances[grid_row_number, index]
            known_count = support_counts[index]
            internal_auc = support_by_name.loc[target, "spatial_holdout_pseudoabsence_roc_auc"]
            internal_recall = support_by_name.loc[
                target, "spatial_holdout_recall_at_background_top5pct"
            ]
            outside_25 = bool(np.isfinite(target_distance) and target_distance > PRIMARY_EXCLUSION_KM)
            within_250 = bool(
                np.isfinite(target_distance) and target_distance <= CANDIDATE_MAX_DISTANCE_KM
            )
            candidate_distance = outside_25 and within_250
            candidate_gate = bool(
                candidate_distance
                and known_count >= 10
                and pd.notna(internal_auc)
                and internal_auc >= 0.60
                and np.isfinite(target_percentile)
                and target_percentile >= 0.995
                and np.isfinite(target_score)
                and target_score >= 0.50
            )
            finite_scores = centroid_scores[np.isfinite(centroid_scores)]
            target_rank = (
                int(1 + np.sum(finite_scores > target_score))
                if np.isfinite(target_score)
                else None
            )
            flags = ["official_auction_or_exploration_target_not_confirmed_deposit"]
            if not outside_25:
                flags.append("within_25km_of_training_evidence_excluded_from_primary_transfer_cohort")
            if known_count < 10:
                flags.append("target_model_below_published_minimum_support")
            if pd.isna(internal_auc) or internal_auc < 0.60:
                flags.append("target_model_does_not_pass_internal_minimum_holdout_auc")
            if not SOURCE_LABEL_INDEPENDENCE_RESOLVED:
                flags.append("complete_historical_source_label_independence_not_established")
            key = f"{block['source_family']}|{block['source_record_id']}|{target}"
            rows.append(
                {
                    "record_id": f"OBT-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                    "source_family": block["source_family"],
                    "source_record_id": block["source_record_id"],
                    "source_event_record_ids_json": block["source_event_record_ids_json"],
                    "source_event_count": block["source_event_count"],
                    "block_name": block["block_name"],
                    "block_name_aliases_json": block["block_name_aliases_json"],
                    "state_or_ut": block["state_or_ut"],
                    "district": block["district"],
                    "block_area_ha": block["block_area_ha"],
                    "exploration_level": block["exploration_level"],
                    "latitude": block["latitude"],
                    "longitude": block["longitude"],
                    "h3_r6": h3_r6,
                    "h3_r3": h3_r3,
                    "target_material": target,
                    "target_chemical_names_json": jdump(material_by_name[target]["chemical_names"]),
                    "target_symbols_or_formulae_json": jdump(material_by_name[target]["symbols_or_formulae"]),
                    "source_label_type": "official_auction_or_exploration_target_not_confirmed_deposit",
                    "geometry_quality_status": block["geometry_quality_status"],
                    "geometry_model_role": block["geometry_model_role"],
                    "geometry_source_url": block["geometry_source_url"],
                    "source_url": block["source_url"],
                    "target_known_evidence_records": known_count,
                    "internal_spatial_cv_auc": safe_float(internal_auc),
                    "internal_spatial_cv_recall_at_background_top5pct": safe_float(internal_recall),
                    "nearest_known_target_evidence_km": safe_float(target_distance),
                    "outside_25km_known_evidence": outside_25,
                    "within_250km_known_evidence": within_250,
                    "primary_transfer_cohort": outside_25 and np.isfinite(target_score),
                    "candidate_distance_domain": candidate_distance,
                    "target_prospectivity_score": safe_float(target_score),
                    "target_national_percentile": safe_float(target_percentile),
                    "target_score_rank_among_50": target_rank,
                    "target_is_centroid_top1": target == grid_row["top_material"],
                    "target_in_centroid_top5": target in published_top5,
                    "centroid_published_top_material": grid_row["top_material"],
                    "centroid_published_record_class": grid_row["record_class"],
                    "centroid_is_published_candidate": grid_row["record_class"]
                    in {"priority_candidate", "high_priority_candidate"},
                    "target_specific_priority_gate": candidate_gate,
                    "source_label_limitations": (
                        "The source identifies an auction or exploration target, not a confirmed deposit, "
                        "resource, reserve, discovery, grade continuity, economic viability, current grant, "
                        "operating mine, or permission to enter land. Source-independent publication does "
                        "not prove knowledge-independence from historical mineral evidence."
                    ),
                    "data_quality_flags_json": jdump(flags),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["source_family", "source_record_id", "target_material"]
    ).reset_index(drop=True)


def bootstrap_metrics(
    positive_scores: np.ndarray,
    positive_groups: np.ndarray,
    background_scores: np.ndarray,
    background_groups: np.ndarray,
    rng: np.random.Generator,
) -> tuple[float, float, float, float]:
    positive_unique = np.unique(positive_groups)
    background_unique = np.unique(background_groups)
    aucs = []
    recalls = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sampled_positive_groups = rng.choice(
            positive_unique, size=len(positive_unique), replace=True
        )
        sampled_background_groups = rng.choice(
            background_unique, size=len(background_unique), replace=True
        )
        positive_index = np.concatenate(
            [np.flatnonzero(positive_groups == group) for group in sampled_positive_groups]
        )
        background_index = np.concatenate(
            [np.flatnonzero(background_groups == group) for group in sampled_background_groups]
        )
        positive = positive_scores[positive_index]
        background = background_scores[background_index]
        labels = np.concatenate([np.ones(len(positive)), np.zeros(len(background))])
        values = np.concatenate([positive, background])
        aucs.append(roc_auc_score(labels, values))
        threshold = np.percentile(background, 95)
        recalls.append(float(np.mean(positive >= threshold)))
    return (
        float(np.quantile(aucs, 0.025)),
        float(np.quantile(aucs, 0.975)),
        float(np.quantile(recalls, 0.025)),
        float(np.quantile(recalls, 0.975)),
    )


def evaluate_materials(
    observations: pd.DataFrame,
    grid: pd.DataFrame,
    materials: list[dict],
    support: pd.DataFrame,
    scores: np.ndarray,
    distances: np.ndarray,
) -> tuple[pd.DataFrame, dict]:
    material_index = {item["material_name"]: i for i, item in enumerate(materials)}
    support_by_name = support.set_index("material_name")
    grid_coords = np.radians(grid[["latitude", "longitude"]].to_numpy())
    grid_groups = np.array(
        [h3.latlng_to_cell(lat, lon, 3) for lat, lon in zip(grid["latitude"], grid["longitude"])]
    )
    minimum_background_to_known = math.inf
    minimum_background_to_official = math.inf
    results = []

    for item in materials:
        name = item["material_name"]
        index = material_index[name]
        pairs = observations[observations["target_material"].eq(name)].copy()
        primary = pairs[pairs["primary_transfer_cohort"]].copy()
        internal_auc = support_by_name.loc[name, "spatial_holdout_pseudoabsence_roc_auc"]
        internal_recall = support_by_name.loc[
            name, "spatial_holdout_recall_at_background_top5pct"
        ]
        base = {
            "record_id": f"OBT-MATERIAL-{item['priority_rank']:02d}-{slug(name)}",
            "material_name": name,
            "priority_rank": item["priority_rank"],
            "known_evidence_records": int(support_by_name.loc[name, "known_evidence_records"]),
            "internal_spatial_cv_auc": safe_float(internal_auc),
            "internal_spatial_cv_recall_at_background_top5pct": safe_float(internal_recall),
            "official_block_material_pairs": int(len(pairs)),
            "central_critical_block_pairs": int(
                pairs["source_family"].eq("central_critical_mineral_auction").sum()
            ),
            "state_auction_mbs_block_pairs": int(
                pairs["source_family"].eq("ibm_2023_24_state_auction_mbs").sum()
            ),
            "outside_25km_official_block_pairs": int(
                pairs["outside_25km_known_evidence"].sum()
            ),
            "candidate_distance_domain_pairs": int(pairs["candidate_distance_domain"].sum()),
            "primary_transfer_positive_blocks": int(len(primary)),
            "primary_transfer_positive_h3_r3_groups": int(primary["h3_r3"].nunique()),
            "background_cells_sampled": 0,
            "transfer_roc_auc": None,
            "transfer_roc_auc_ci95_low": None,
            "transfer_roc_auc_ci95_high": None,
            "transfer_average_precision": None,
            "transfer_recall_at_background_top5pct": None,
            "transfer_recall_ci95_low": None,
            "transfer_recall_ci95_high": None,
            "official_block_median_national_percentile": None,
            "official_block_share_at_or_above_p95": None,
            "official_block_share_at_or_above_p99": None,
            "official_block_share_at_or_above_p995": None,
            "target_material_top1_rate": None,
            "target_material_top5_rate": None,
            "published_candidate_centroid_rate": None,
            "target_specific_priority_gate_rate": None,
            "minimum_positive_to_known_evidence_km": (
                safe_float(primary["nearest_known_target_evidence_km"].min())
                if len(primary)
                else None
            ),
            "transfer_evaluation_status": "",
            "passes_predeclared_statistical_gate": False,
            "source_label_independence_resolved": SOURCE_LABEL_INDEPENDENCE_RESOLVED,
            "passes_production_admission_gate": False,
            "candidate_scores_recomputed": False,
            "production_scoring_changed": False,
            "interpretation": "",
        }
        if not np.isfinite(scores[:, index]).any():
            base["transfer_evaluation_status"] = "not_evaluated_no_published_material_score"
            base["interpretation"] = "No MRDS evidence exists for a v0.6 target score."
            results.append(base)
            continue
        if len(primary) < MIN_EVALUATION_BLOCKS:
            base["transfer_evaluation_status"] = "not_evaluated_fewer_than_5_outside_25km_official_blocks"
            base["interpretation"] = "Too few official block centroids remain after the 25 km evidence exclusion."
            results.append(base)
            continue
        if primary["h3_r3"].nunique() < MIN_EVALUATION_GROUPS:
            base["transfer_evaluation_status"] = "not_evaluated_fewer_than_3_positive_h3_r3_groups"
            base["interpretation"] = "Official block centroids occupy too few broad spatial groups for group uncertainty."
            results.append(base)
            continue

        all_official = pairs[np.isfinite(pairs["nearest_known_target_evidence_km"])].copy()
        official_tree = BallTree(
            np.radians(all_official[["latitude", "longitude"]].to_numpy()),
            metric="haversine",
        )
        official_distance, _ = official_tree.query(grid_coords, k=1)
        official_distance_km = official_distance[:, 0] * EARTH_RADIUS_KM
        eligible_background = np.flatnonzero(
            np.isfinite(scores[:, index])
            & (distances[:, index] > PRIMARY_EXCLUSION_KM)
            & (official_distance_km > PRIMARY_EXCLUSION_KM)
        )
        if len(eligible_background) < 100:
            base["transfer_evaluation_status"] = "not_evaluated_insufficient_background_pool"
            base["interpretation"] = "Fewer than 100 uncontaminated background cells remain."
            results.append(base)
            continue
        sample_count = min(len(eligible_background), max(500, len(primary) * 20))
        rng = np.random.default_rng(GLOBAL_SEED + index)
        background_index = rng.choice(
            eligible_background, size=sample_count, replace=False
        )
        positive_scores = primary["target_prospectivity_score"].to_numpy(float)
        positive_groups = primary["h3_r3"].to_numpy(str)
        background_scores = scores[background_index, index].astype(float)
        background_groups = grid_groups[background_index]
        labels = np.concatenate(
            [np.ones(len(positive_scores)), np.zeros(len(background_scores))]
        )
        values = np.concatenate([positive_scores, background_scores])
        auc = float(roc_auc_score(labels, values))
        average_precision = float(average_precision_score(labels, values))
        threshold = float(np.percentile(background_scores, 95))
        recall = float(np.mean(positive_scores >= threshold))
        auc_low, auc_high, recall_low, recall_high = bootstrap_metrics(
            positive_scores,
            positive_groups,
            background_scores,
            background_groups,
            rng,
        )
        minimum_background_to_known = min(
            minimum_background_to_known,
            float(np.min(distances[background_index, index])),
        )
        minimum_background_to_official = min(
            minimum_background_to_official,
            float(np.min(official_distance_km[background_index])),
        )
        pct = primary["target_national_percentile"].dropna().to_numpy(float)
        top5_rate = float(primary["target_in_centroid_top5"].mean())
        statistical_gate = bool(
            len(primary) >= MIN_GATE_BLOCKS
            and primary["h3_r3"].nunique() >= MIN_GATE_GROUPS
            and int(support_by_name.loc[name, "known_evidence_records"]) >= 10
            and pd.notna(internal_auc)
            and internal_auc >= 0.60
            and auc >= MIN_GATE_AUC
            and auc_low > 0.50
            and recall >= MIN_GATE_RECALL
            and top5_rate >= MIN_GATE_TOP5_RATE
        )
        base.update(
            {
                "background_cells_sampled": sample_count,
                "transfer_roc_auc": auc,
                "transfer_roc_auc_ci95_low": auc_low,
                "transfer_roc_auc_ci95_high": auc_high,
                "transfer_average_precision": average_precision,
                "transfer_recall_at_background_top5pct": recall,
                "transfer_recall_ci95_low": recall_low,
                "transfer_recall_ci95_high": recall_high,
                "official_block_median_national_percentile": (
                    float(np.median(pct)) if len(pct) else None
                ),
                "official_block_share_at_or_above_p95": (
                    float(np.mean(pct >= 0.95)) if len(pct) else None
                ),
                "official_block_share_at_or_above_p99": (
                    float(np.mean(pct >= 0.99)) if len(pct) else None
                ),
                "official_block_share_at_or_above_p995": (
                    float(np.mean(pct >= 0.995)) if len(pct) else None
                ),
                "target_material_top1_rate": float(primary["target_is_centroid_top1"].mean()),
                "target_material_top5_rate": top5_rate,
                "published_candidate_centroid_rate": float(
                    primary["centroid_is_published_candidate"].mean()
                ),
                "target_specific_priority_gate_rate": float(
                    primary["target_specific_priority_gate"].mean()
                ),
                "transfer_evaluation_status": "evaluated_diagnostic_only",
                "passes_predeclared_statistical_gate": statistical_gate,
                "passes_production_admission_gate": (
                    statistical_gate and SOURCE_LABEL_INDEPENDENCE_RESOLVED
                ),
                "interpretation": (
                    "Source-independent official block alignment test. Auction or exploration targeting "
                    "is not a confirmed deposit label, and complete historical knowledge-independence is "
                    "not established; no production admission follows from this result."
                ),
            }
        )
        results.append(base)
    diagnostics = {
        "minimum_sampled_background_to_known_evidence_km": (
            None if math.isinf(minimum_background_to_known) else minimum_background_to_known
        ),
        "minimum_sampled_background_to_official_block_km": (
            None if math.isinf(minimum_background_to_official) else minimum_background_to_official
        ),
    }
    return pd.DataFrame(results), diagnostics


def update_dictionary(summary: pd.DataFrame, observations: pd.DataFrame) -> pd.DataFrame:
    dictionary_path = OUT / "data_dictionary.csv"
    dictionary = pd.read_csv(dictionary_path, dtype=str, keep_default_na=False)
    table_definitions = {
        SUMMARY_PATH.name: SUMMARY_FIELDS,
        OBSERVATION_PATH.name: OBSERVATION_FIELDS,
    }
    dictionary = dictionary[
        ~dictionary["table"].isin(table_definitions)
    ].copy()
    additions = []
    for table_name, frame in [
        (SUMMARY_PATH.name, summary),
        (OBSERVATION_PATH.name, observations),
    ]:
        definitions = table_definitions[table_name]
        for column in frame.columns:
            description, data_type, unit = definitions[column]
            additions.append(
                {
                    "table": table_name,
                    "column": column,
                    "definition": description,
                    "data_type": data_type,
                    "unit": unit,
                    "missing_value_policy": (
                        "Blank means unavailable, not applicable, or not evaluated; zero remains a measured or counted zero."
                    ),
                }
            )
    return pd.concat([dictionary, pd.DataFrame(additions)], ignore_index=True)


def main() -> None:
    candidate_hash_before = sha256(CANDIDATE_PATH)
    grid_hash_before = sha256(GRID_PATH)
    input_hashes = {
        "national_grid": grid_hash_before,
        "candidate_table": candidate_hash_before,
        "known_sites": sha256(KNOWN_PATH),
        "material_configuration": sha256(MATERIAL_CONFIG_PATH),
        "material_model_support": sha256(MODEL_SUPPORT_PATH),
        "central_critical_blocks": sha256(CENTRAL_BLOCK_PATH),
        "state_auction_mbs_geometries": sha256(STATE_BLOCK_PATH),
    }
    materials = json.loads(MATERIAL_CONFIG_PATH.read_text(encoding="utf-8"))
    target_names = {item["material_name"] for item in materials}
    grid = pd.read_csv(
        GRID_PATH,
        usecols=[
            "h3_r6",
            "latitude",
            "longitude",
            "geology_geom_id",
            "record_class",
            "top_material",
            "top_materials_json",
            "top_material_scores_json",
            "top_material_percentiles_json",
            "top_material_nearest_known_km_json",
        ],
    )
    known = pd.read_csv(
        KNOWN_PATH,
        usecols=[
            "record_id",
            "latitude",
            "longitude",
            "geology_geom_id",
            "district_2011",
            "priority_materials_json",
            "source_dataset_id",
        ],
    )
    known["_priority_materials"] = known["priority_materials_json"].map(json.loads)
    known = known[
        known["latitude"].between(5, 38.5)
        & known["longitude"].between(67, 99)
        & known["district_2011"].notna()
    ].copy()
    support = pd.read_csv(MODEL_SUPPORT_PATH)
    central_raw = pd.read_csv(CENTRAL_BLOCK_PATH)
    state_raw = pd.read_csv(STATE_BLOCK_PATH)
    central_accepted_events = central_raw[
        central_raw["auction_event_kind"].eq("auction_offer")
        & central_raw["geometry_quality_flag"].eq("accepted")
        & central_raw["block_boundary_wkt"].notna()
    ].copy()
    central_reoffer_material_sets_invariant = bool(
        central_accepted_events.groupby("block_lineage_key")[
            "normalized_top50_materials_json"
        ].nunique(dropna=False).le(1).all()
    )
    central_reoffer_geometries_invariant = bool(
        central_accepted_events.groupby("block_lineage_key")[
            "block_boundary_wkt"
        ].nunique(dropna=False).le(1).all()
    )

    scores, percentiles, distances, support_counts = score_all_materials(
        grid, known, materials
    )
    parity = validate_score_parity(
        grid,
        {item["material_name"]: index for index, item in enumerate(materials)},
        scores,
        percentiles,
        distances,
    )
    central = canonical_central_blocks(central_raw)
    state = canonical_state_blocks(state_raw, target_names)
    blocks = pd.concat([central, state], ignore_index=True)
    observations = build_observations(
        blocks,
        grid,
        materials,
        support,
        scores,
        percentiles,
        distances,
        support_counts,
    )
    summary, background_diagnostics = evaluate_materials(
        observations,
        grid,
        materials,
        support,
        scores,
        distances,
    )
    summary = summary[list(SUMMARY_FIELDS)]
    observations = observations[list(OBSERVATION_FIELDS)]
    summary.to_csv(
        SUMMARY_PATH,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
        float_format="%.8f",
        na_rep="",
    )
    observations.to_csv(
        OBSERVATION_PATH,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
        float_format="%.8f",
        na_rep="",
    )
    dictionary = update_dictionary(summary, observations)
    dictionary.to_csv(OUT / "data_dictionary.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    candidate_hash_after = sha256(CANDIDATE_PATH)
    grid_hash_after = sha256(GRID_PATH)
    evaluated = summary[summary["transfer_evaluation_status"].eq("evaluated_diagnostic_only")]
    contributing_footprints = observations[
        ["source_family", "source_record_id"]
    ].drop_duplicates()
    checks = [
        {"name": "summary_rows", "passed": len(summary) == 50, "observed": len(summary), "expected": 50},
        {"name": "unique_summary_ids", "passed": summary["record_id"].is_unique, "observed": int(summary["record_id"].nunique()), "expected": 50},
        {"name": "observation_rows", "passed": len(observations) == 221, "observed": len(observations), "expected": 221},
        {"name": "unique_observation_ids", "passed": observations["record_id"].is_unique, "observed": int(observations["record_id"].nunique()), "expected": len(observations)},
        {"name": "data_dictionary_rows", "passed": len(dictionary) == 1561, "observed": len(dictionary), "expected": 1561},
        {"name": "unique_data_dictionary_fields", "passed": not dictionary.duplicated(["table", "column"]).any(), "observed": int(dictionary[["table", "column"]].drop_duplicates().shape[0]), "expected": len(dictionary)},
        {"name": "official_block_target_materials_known", "passed": set(observations["target_material"]).issubset(target_names), "observed": sorted(observations["target_material"].unique().tolist()), "expected": "subset of configured v0.6 targets"},
        {"name": "central_unique_accepted_footprints", "passed": len(central) == 99, "observed": len(central), "expected": 99},
        {"name": "central_reoffer_material_sets_invariant", "passed": central_reoffer_material_sets_invariant, "observed": central_reoffer_material_sets_invariant, "expected": True},
        {"name": "central_reoffer_geometries_invariant", "passed": central_reoffer_geometries_invariant, "observed": central_reoffer_geometries_invariant, "expected": True},
        {"name": "state_admitted_footprints", "passed": len(state) == 67, "observed": len(state), "expected": 67},
        {"name": "unique_official_footprints_screened", "passed": len(blocks) == 166, "observed": len(blocks), "expected": 166},
        {"name": "target_mapped_contributing_footprints", "passed": len(contributing_footprints) == 151, "observed": len(contributing_footprints), "expected": 151},
        {"name": "all_block_centroids_join_grid", "passed": observations["h3_r6"].notna().all(), "observed": int(observations["h3_r6"].notna().sum()), "expected": len(observations)},
        {"name": "published_score_parity", "passed": parity["exact_published_score_parity"], "observed": parity, "expected": {"score_mismatches": 0, "percentile_mismatches": 0, "distance_mismatches": 0}},
        {"name": "evaluated_materials", "passed": len(evaluated) >= 5, "observed": len(evaluated), "expected": ">=5"},
        {"name": "primary_positive_distance_exclusion", "passed": bool(observations.loc[observations["primary_transfer_cohort"], "nearest_known_target_evidence_km"].gt(PRIMARY_EXCLUSION_KM).all()), "observed": safe_float(observations.loc[observations["primary_transfer_cohort"], "nearest_known_target_evidence_km"].min()), "expected": f">{PRIMARY_EXCLUSION_KM}"},
        {"name": "sampled_background_known_evidence_exclusion", "passed": background_diagnostics["minimum_sampled_background_to_known_evidence_km"] is not None and background_diagnostics["minimum_sampled_background_to_known_evidence_km"] > PRIMARY_EXCLUSION_KM, "observed": background_diagnostics["minimum_sampled_background_to_known_evidence_km"], "expected": f">{PRIMARY_EXCLUSION_KM}"},
        {"name": "sampled_background_official_block_exclusion", "passed": background_diagnostics["minimum_sampled_background_to_official_block_km"] is not None and background_diagnostics["minimum_sampled_background_to_official_block_km"] > PRIMARY_EXCLUSION_KM, "observed": background_diagnostics["minimum_sampled_background_to_official_block_km"], "expected": f">{PRIMARY_EXCLUSION_KM}"},
        {"name": "central_source_excluded_from_scoring", "passed": central["geometry_model_role"].str.contains("not_used_in_prospectivity", na=False).all(), "observed": sorted(central["geometry_model_role"].unique().tolist()), "expected": "all contain not_used_in_prospectivity"},
        {"name": "state_source_context_only", "passed": state["geometry_model_role"].eq("context_only").all(), "observed": sorted(state["geometry_model_role"].unique().tolist()), "expected": ["context_only"]},
        {"name": "training_source_is_mrds_only", "passed": set(known["source_dataset_id"]) == {"SRC_USGS_MRDS"}, "observed": sorted(known["source_dataset_id"].unique().tolist()), "expected": ["SRC_USGS_MRDS"]},
        {"name": "source_label_independence_guardrail", "passed": not SOURCE_LABEL_INDEPENDENCE_RESOLVED and not summary["passes_production_admission_gate"].any(), "observed": "unresolved_and_blocks_production_admission", "expected": "unresolved_and_blocks_production_admission"},
        {"name": "candidate_scores_not_recomputed", "passed": summary["candidate_scores_recomputed"].eq(False).all(), "observed": bool(summary["candidate_scores_recomputed"].eq(False).all()), "expected": True},
        {"name": "production_scoring_unchanged", "passed": summary["production_scoring_changed"].eq(False).all(), "observed": bool(summary["production_scoring_changed"].eq(False).all()), "expected": True},
        {"name": "candidate_hash_unchanged", "passed": candidate_hash_before == candidate_hash_after, "observed": candidate_hash_after, "expected": candidate_hash_before},
        {"name": "national_grid_hash_unchanged", "passed": grid_hash_before == grid_hash_after, "observed": grid_hash_after, "expected": grid_hash_before},
    ]
    validation = {
        "release_version": RELEASE_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "model_version": MODEL_VERSION,
        "input_sha256": input_hashes,
        "method": {
            "unit_of_analysis": "one unique official block footprint and normalized target-material pair; central reoffer events are deduplicated by block_lineage_key",
            "positive_label": "centroid of an admitted official auction or exploration block naming the target material",
            "primary_positive_exclusion": f">{PRIMARY_EXCLUSION_KM} km from any MRDS training occurrence for the material",
            "background": f"deterministic India H3 r6 sample >{PRIMARY_EXCLUSION_KM} km from MRDS evidence and >{PRIMARY_EXCLUSION_KM} km from any official block centroid for the material",
            "score": "exact full-data v0.6 target-material reconnaissance score; no refitting",
            "uncertainty": f"{BOOTSTRAP_REPLICATES}-replicate separate positive/background H3 r3 group bootstrap",
            "central_reoffer_handling": "latest event retained as canonical after confirming invariant geometry and normalized material set; all represented event IDs retained",
            "geometry_sampling": "one H3 r6 cell containing the authoritative block centroid; block size does not weight the result",
            "known_limitation": "official targeting is source-independent from MRDS publication but not proven knowledge-independent; blocks are not confirmed deposits",
        },
        "predeclared_statistical_gate": {
            "minimum_primary_positive_blocks": MIN_GATE_BLOCKS,
            "minimum_positive_h3_r3_groups": MIN_GATE_GROUPS,
            "minimum_known_evidence_records": 10,
            "minimum_internal_spatial_cv_auc": 0.60,
            "minimum_transfer_roc_auc": MIN_GATE_AUC,
            "transfer_auc_ci95_lower_bound_strictly_above": 0.50,
            "minimum_transfer_recall_at_background_top5pct": MIN_GATE_RECALL,
            "minimum_target_material_top5_rate": MIN_GATE_TOP5_RATE,
        },
        "production_gate": {
            "statistical_gate_required": True,
            "complete_source_label_independence_required": True,
            "source_label_independence_resolved": SOURCE_LABEL_INDEPENDENCE_RESOLVED,
            "effect": "None. A statistical pass is diagnostic support only; production admission also requires a genuinely independent confirmed occurrence/deposit set or field validation.",
        },
        "central_offer_event_rows": int(central_raw["auction_event_kind"].eq("auction_offer").sum()),
        "central_accepted_offer_event_rows": int((central_raw["auction_event_kind"].eq("auction_offer") & central_raw["geometry_quality_flag"].eq("accepted")).sum()),
        "central_unique_accepted_footprints": len(central),
        "state_geometry_rows": len(state_raw),
        "state_admitted_footprints": len(state),
        "unique_official_footprints_screened": int(blocks[["source_family", "source_record_id"]].drop_duplicates().shape[0]),
        "target_mapped_contributing_footprints": len(contributing_footprints),
        "central_target_mapped_contributing_footprints": int(contributing_footprints["source_family"].eq("central_critical_mineral_auction").sum()),
        "state_target_mapped_contributing_footprints": int(contributing_footprints["source_family"].eq("ibm_2023_24_state_auction_mbs").sum()),
        "observation_rows": len(observations),
        "materials_with_official_block_pairs": int(summary["official_block_material_pairs"].gt(0).sum()),
        "evaluated_materials": len(evaluated),
        "materials_passing_statistical_gate": int(summary["passes_predeclared_statistical_gate"].sum()),
        "statistical_gate_materials": summary.loc[summary["passes_predeclared_statistical_gate"], "material_name"].tolist(),
        "materials_passing_production_admission_gate": int(summary["passes_production_admission_gate"].sum()),
        "production_admission_materials": summary.loc[summary["passes_production_admission_gate"], "material_name"].tolist(),
        "source_label_independence_resolved": SOURCE_LABEL_INDEPENDENCE_RESOLVED,
        "candidate_scores_recomputed": False,
        "production_scoring_changed": False,
        "candidate_table_sha256_unchanged": candidate_hash_before == candidate_hash_after,
        "national_grid_sha256_unchanged": grid_hash_before == grid_hash_after,
        "score_parity": parity,
        "background_exclusion_diagnostics": background_diagnostics,
        "checks": checks,
        "checks_pass": bool(all(bool(check["passed"]) for check in checks)),
        "output_sha256": {
            "summary_csv": sha256(SUMMARY_PATH),
            "observation_csv": sha256(OBSERVATION_PATH),
        },
    }
    VALIDATION_PATH.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=json_default) + "\n",
        encoding="utf-8",
    )
    release_path = OUT / "validation_report.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["official_block_transfer_validation"] = {
        key: validation[key]
        for key in [
            "experiment_version",
            "unique_official_footprints_screened",
            "target_mapped_contributing_footprints",
            "observation_rows",
            "materials_with_official_block_pairs",
            "evaluated_materials",
            "materials_passing_statistical_gate",
            "statistical_gate_materials",
            "materials_passing_production_admission_gate",
            "production_admission_materials",
            "source_label_independence_resolved",
            "candidate_scores_recomputed",
            "production_scoring_changed",
            "candidate_table_sha256_unchanged",
            "national_grid_sha256_unchanged",
            "checks_pass",
        ]
    }
    release_path.write_text(
        json.dumps(release, indent=2, ensure_ascii=False, default=json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(validation, indent=2, ensure_ascii=False, default=json_default))
    if not validation["checks_pass"]:
        raise SystemExit("official block transfer validation failed")


if __name__ == "__main__":
    main()
