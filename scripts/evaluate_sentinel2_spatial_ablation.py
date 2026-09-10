#!/usr/bin/env python3
"""Evaluate whether Sentinel-2 surface context adds generalizable mineral signal.

This is a shadow-model experiment. It compares the same regularized logistic
classifier with and without a compact Sentinel-2 feature family under purged
H3-resolution-3 grouped folds. It never rewrites candidate scores, classes or
ranks. Missing Sentinel values receive training-fold medians without adding
Sentinel missingness indicators to the model.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.neighbors import BallTree

from evaluate_emag2_spatial_ablation import (
    BACKGROUND_EXCLUSION_KM,
    BASE_DYNAMIC_FEATURES,
    BASE_STATIC_FEATURES,
    BOOTSTRAP_REPLICATES,
    EARTH_RADIUS_KM,
    MIN_ADMISSION_POSITIVE_CELLS,
    MIN_ADMISSION_SPATIAL_GROUPS,
    MIN_EVALUATION_POSITIVE_CELLS,
    PURGE_DISTANCE_KM,
    balltree_distance_km,
    fold_dynamic_features,
    make_model,
    parse_materials,
    recall_at_background_top5,
    sha256,
    spatial_group_bootstrap_delta,
    stable_seed,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
SENTINEL_PATH = OUT / "india_sentinel2_surface_context_h3_r6.csv"
KNOWN_PATH = OUT / "india_known_mining_sites.csv"
MATERIAL_PATH = OUT / "india_strategic_materials_top50.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"
REFERENCE_SUMMARY_PATH = OUT / "material_soilgrids_spatial_ablation.csv"
REFERENCE_FOLD_PATH = OUT / "material_soilgrids_spatial_ablation_folds.csv"
SUMMARY_PATH = OUT / "material_sentinel2_spatial_ablation.csv"
FOLD_PATH = OUT / "material_sentinel2_spatial_ablation_folds.csv"
VALIDATION_PATH = OUT / "sentinel2_spatial_ablation_validation.json"
DICTIONARY_PATH = OUT / "data_dictionary.csv"

RELEASE_VERSION = "v1.0-alpha.19"
EXPERIMENT_VERSION = "sentinel2-spatial-ablation-v0.1"
FEATURE_VERSION = "sentinel2-l2a-h3-r6-surface-context-v0.1"
SURFACE_DISTURBANCE_LABEL_LEAKAGE_RESOLVED = False

# Compact, process-agnostic surface family. Observation counts, support classes,
# quality flags and missingness are deliberately excluded from predictors.
SENTINEL_FEATURES = [
    "annual_bare_b02_reflectance_median",
    "annual_bare_b03_reflectance_median",
    "annual_bare_b04_reflectance_median",
    "annual_bare_b08_reflectance_median",
    "annual_bare_b11_reflectance_median",
    "annual_bare_b12_reflectance_median",
    "annual_bare_ndvi_median",
    "annual_bare_ndmi_median",
    "annual_bare_bsi_median",
    "annual_bare_ndti_median",
    "annual_bare_red_blue_ratio_median",
    "annual_bare_swir1_swir2_ratio_median",
    "dry_clear_land_ndvi_median",
    "dry_clear_land_ndmi_median",
    "dry_clear_land_bsi_median",
    "post_clear_land_ndvi_median",
    "post_clear_land_ndmi_median",
    "post_clear_land_bsi_median",
]
GRID_COLUMNS = [
    "h3_r6",
    "latitude",
    "longitude",
    "geology_geom_id",
    *BASE_STATIC_FEATURES,
]
SENTINEL_COLUMNS = ["h3_r6", "feature_version", "model_use_status", *SENTINEL_FEATURES]


SUMMARY_FIELDS = {
    "record_id": ("Stable material-ablation record identifier.", "text", ""),
    "material_name": ("Normalized v0.6 modeling-target name.", "text", ""),
    "known_evidence_records_raw": ("Coordinate-valid source records naming the material before H3-cell deduplication.", "integer", "records"),
    "unique_positive_h3_cells": ("Unique H3 resolution-6 positive cells used for eligibility.", "integer", "cells"),
    "positive_h3_r3_groups": ("Unique H3 resolution-3 groups containing positive cells.", "integer", "groups"),
    "positive_sentinel_complete_cells": ("Positive cells with all 18 Sentinel-2 model features present before fold-only imputation.", "integer", "cells"),
    "positive_sentinel_complete_rate": ("Share of positive cells with all 18 Sentinel-2 model features present before fold-only imputation.", "number", "0-1 share"),
    "background_cells_sampled": ("Deterministically sampled pseudo-absence cells farther than 25 km from any positive cell.", "integer", "cells"),
    "background_sentinel_complete_rate": ("Share of sampled background cells with all 18 Sentinel-2 model features present before fold-only imputation.", "number", "0-1 share"),
    "spatial_cv_folds": ("Completed purged spatial cross-validation folds.", "integer", "folds"),
    "oof_positive_rows": ("Positive rows with paired out-of-fold predictions.", "integer", "rows"),
    "oof_background_rows": ("Background rows with paired out-of-fold predictions.", "integer", "rows"),
    "baseline_roc_auc": ("Pooled out-of-fold pseudo-absence ROC AUC without Sentinel-2.", "number", "0-1"),
    "sentinel2_roc_auc": ("Pooled out-of-fold pseudo-absence ROC AUC after adding Sentinel-2 surface context.", "number", "0-1"),
    "delta_roc_auc": ("Sentinel-2 ROC AUC minus baseline ROC AUC on identical out-of-fold rows.", "number", "AUC points"),
    "delta_roc_auc_group_bootstrap_ci95_low": ("Lower 2.5th percentile of the spatial-group bootstrap AUC delta.", "number", "AUC points"),
    "delta_roc_auc_group_bootstrap_ci95_high": ("Upper 97.5th percentile of the spatial-group bootstrap AUC delta.", "number", "AUC points"),
    "baseline_average_precision": ("Pooled out-of-fold average precision without Sentinel-2.", "number", "0-1"),
    "sentinel2_average_precision": ("Pooled out-of-fold average precision after adding Sentinel-2.", "number", "0-1"),
    "delta_average_precision": ("Sentinel-2 average precision minus baseline average precision.", "number", "AP points"),
    "baseline_recall_at_background_top5pct": ("Positive recall at each fold's baseline background 95th-percentile threshold.", "number", "0-1"),
    "sentinel2_recall_at_background_top5pct": ("Positive recall at each fold's Sentinel-2 background 95th-percentile threshold.", "number", "0-1"),
    "delta_recall_at_background_top5pct": ("Sentinel-2 recall minus baseline recall at the paired background threshold.", "number", "recall points"),
    "baseline_brier_score": ("Out-of-fold mean squared probability error without Sentinel-2; class-balanced fitting makes calibration provisional.", "number", "0-1 loss"),
    "sentinel2_brier_score": ("Out-of-fold mean squared probability error after adding Sentinel-2; class-balanced fitting makes calibration provisional.", "number", "0-1 loss"),
    "folds_with_positive_auc_gain": ("Completed folds where Sentinel-2 increased ROC AUC.", "integer", "folds"),
    "folds_with_negative_auc_gain": ("Completed folds where Sentinel-2 decreased ROC AUC.", "integer", "folds"),
    "minimum_test_positive_to_training_positive_km": ("Smallest held-out-positive distance to a retained training positive after spatial purge.", "number", "km"),
    "admission_gate_result": ("Whether the predefined evidence gate passed; this does not admit the feature to production scoring.", "boolean", ""),
    "sentinel2_feature_admission_decision": ("Shadow-model interpretation of the ablation result.", "category", ""),
    "decision_reason": ("Machine-readable concise reason for the admission decision.", "text", ""),
    "production_scoring_status": ("Production-use state; always not admitted in this experiment.", "category", ""),
    "candidate_scores_recomputed": ("Whether this experiment rewrote candidate scores, classes or ranks.", "boolean", ""),
    "experiment_version": ("Version of the ablation method.", "text", ""),
    "background_interpretation": ("Required caveat for pseudo-absence cells.", "text", ""),
    "baseline_features_json": ("JSON array of baseline feature names.", "JSON array", ""),
    "sentinel2_features_json": ("JSON array of added Sentinel-2 feature names.", "JSON array", ""),
}

FOLD_FIELDS = {
    "record_id": ("Stable material-fold record identifier.", "text", ""),
    "material_name": ("Normalized v0.6 modeling-target name.", "text", ""),
    "fold_id": ("One-based cross-validation fold identifier.", "integer", "fold"),
    "train_positive_rows": ("Training positive cells remaining after the 50 km purge.", "integer", "rows"),
    "train_background_rows": ("Training background cells remaining after the 50 km purge.", "integer", "rows"),
    "test_positive_rows": ("Held-out positive cells.", "integer", "rows"),
    "test_background_rows": ("Held-out background cells.", "integer", "rows"),
    "train_spatial_groups": ("Unique H3 resolution-3 training groups after purge.", "integer", "groups"),
    "test_spatial_groups": ("Unique H3 resolution-3 test groups.", "integer", "groups"),
    "train_test_groups_disjoint": ("Whether training and test H3 resolution-3 groups are disjoint.", "boolean", ""),
    "purge_distance_km": ("Minimum intended buffer around held-out positives.", "number", "km"),
    "minimum_test_positive_to_training_positive_km": ("Observed nearest distance from a test positive to a retained training positive.", "number", "km"),
    "test_sentinel_complete_rate": ("Share of test rows with all 18 Sentinel-2 model features present before fold-only imputation.", "number", "0-1 share"),
    "baseline_roc_auc": ("Fold pseudo-absence ROC AUC without Sentinel-2.", "number", "0-1"),
    "sentinel2_roc_auc": ("Fold pseudo-absence ROC AUC after adding Sentinel-2.", "number", "0-1"),
    "delta_roc_auc": ("Fold Sentinel-2 ROC AUC minus baseline ROC AUC.", "number", "AUC points"),
    "baseline_average_precision": ("Fold average precision without Sentinel-2.", "number", "0-1"),
    "sentinel2_average_precision": ("Fold average precision after adding Sentinel-2.", "number", "0-1"),
    "baseline_recall_at_background_top5pct": ("Fold positive recall above the baseline background 95th percentile.", "number", "0-1"),
    "sentinel2_recall_at_background_top5pct": ("Fold positive recall above the Sentinel-2 background 95th percentile.", "number", "0-1"),
    "experiment_version": ("Version of the ablation method.", "text", ""),
}


def sentinel_complete(frame: pd.DataFrame) -> pd.Series:
    """Return rows with every candidate Sentinel predictor observed."""
    return frame[SENTINEL_FEATURES].notna().all(axis=1)


def fill_sentinel_from_training(
    train: pd.DataFrame, test: pd.DataFrame, material: str, fold_id: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Impute Sentinel values from training-fold medians without missingness flags."""
    medians = train[SENTINEL_FEATURES].median(axis=0, skipna=True)
    missing_medians = medians[medians.isna()].index.tolist()
    if missing_medians:
        raise RuntimeError(
            f"Sentinel feature entirely missing in {material} fold {fold_id}: {missing_medians}"
        )
    train_filled = train[SENTINEL_FEATURES].fillna(medians)
    test_filled = test[SENTINEL_FEATURES].fillna(medians)
    if train_filled.isna().any().any() or test_filled.isna().any().any():
        raise RuntimeError(f"Sentinel fold imputation incomplete for {material} fold {fold_id}")
    return train_filled, test_filled


def predict_probability_without_sentinel_indicators(
    model: Any, features: pd.DataFrame, context: str
) -> np.ndarray:
    """Predict and verify that the fitted design did not add Sentinel flags."""
    transformed = model[:-1].transform(features)
    if not np.isfinite(transformed).all() or not np.isfinite(model[-1].coef_).all():
        raise RuntimeError(f"non-finite fitted model inputs or coefficients: {context}")
    with np.errstate(all="ignore"):
        decision = transformed @ model[-1].coef_.T + model[-1].intercept_
    if not np.isfinite(decision).all():
        raise RuntimeError(f"non-finite logistic decision score: {context}")
    return expit(decision[:, 0])


def blank_summary(material: str, raw_count: int, positive: pd.DataFrame) -> dict[str, Any]:
    groups = positive["h3_r3"].nunique() if len(positive) else 0
    complete = int(sentinel_complete(positive).sum()) if len(positive) else 0
    return {
        "record_id": "S2-ABL-" + re.sub(r"[^A-Z0-9]+", "-", material.upper()).strip("-"),
        "material_name": material,
        "known_evidence_records_raw": raw_count,
        "unique_positive_h3_cells": len(positive),
        "positive_h3_r3_groups": groups,
        "positive_sentinel_complete_cells": complete,
        "positive_sentinel_complete_rate": complete / len(positive) if len(positive) else math.nan,
        "background_cells_sampled": 0,
        "background_sentinel_complete_rate": math.nan,
        "spatial_cv_folds": 0,
        "oof_positive_rows": 0,
        "oof_background_rows": 0,
        "baseline_roc_auc": math.nan,
        "sentinel2_roc_auc": math.nan,
        "delta_roc_auc": math.nan,
        "delta_roc_auc_group_bootstrap_ci95_low": math.nan,
        "delta_roc_auc_group_bootstrap_ci95_high": math.nan,
        "baseline_average_precision": math.nan,
        "sentinel2_average_precision": math.nan,
        "delta_average_precision": math.nan,
        "baseline_recall_at_background_top5pct": math.nan,
        "sentinel2_recall_at_background_top5pct": math.nan,
        "delta_recall_at_background_top5pct": math.nan,
        "baseline_brier_score": math.nan,
        "sentinel2_brier_score": math.nan,
        "folds_with_positive_auc_gain": 0,
        "folds_with_negative_auc_gain": 0,
        "minimum_test_positive_to_training_positive_km": math.nan,
        "admission_gate_result": False,
        "sentinel2_feature_admission_decision": "not_evaluated_low_support",
        "decision_reason": (
            "fewer_than_10_unique_positive_h3_cells"
            if len(positive) < MIN_EVALUATION_POSITIVE_CELLS
            else "fewer_than_3_positive_h3_r3_groups"
        ),
        "production_scoring_status": "not_admitted_shadow_evaluation_only",
        "candidate_scores_recomputed": False,
        "experiment_version": EXPERIMENT_VERSION,
        "background_interpretation": "Pseudo-absence cells are not confirmed barren and metrics do not estimate discovery probability.",
        "baseline_features_json": json.dumps(BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES, separators=(",", ":")),
        "sentinel2_features_json": json.dumps(SENTINEL_FEATURES, separators=(",", ":")),
    }


def evaluate_material(
    material: str,
    raw_count: int,
    positive: pd.DataFrame,
    grid: pd.DataFrame,
    grid_coords: np.ndarray,
    grid_unit_counts: pd.Series,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    summary = blank_summary(material, raw_count, positive)
    if len(positive) < MIN_EVALUATION_POSITIVE_CELLS or positive["h3_r3"].nunique() < 3:
        return summary, [], 0

    positive_tree = BallTree(
        np.radians(positive[["latitude", "longitude"]].to_numpy()), metric="haversine"
    )
    distance_to_positive, _ = positive_tree.query(grid_coords, k=1)
    pool_mask = distance_to_positive[:, 0] * EARTH_RADIUS_KM > BACKGROUND_EXCLUSION_KM
    pool_mask &= ~grid["h3_r6"].isin(positive["h3_r6"]).to_numpy()
    pool_index = np.flatnonzero(pool_mask)
    if len(pool_index) < 500:
        summary["sentinel2_feature_admission_decision"] = "not_evaluated_insufficient_background"
        summary["decision_reason"] = "fewer_than_500_background_cells_beyond_25km"
        return summary, [], 0

    rng = np.random.default_rng(stable_seed(material))
    background_count = min(len(pool_index), max(1000, len(positive) * 30))
    background = grid.iloc[rng.choice(pool_index, size=background_count, replace=False)].copy()
    background["label"] = 0
    positive = positive.copy()
    positive["label"] = 1
    sample = pd.concat([positive, background], ignore_index=True)
    sample["h3_r3"] = sample["h3_r6"].map(lambda cell: h3.cell_to_parent(cell, 3))
    labels = sample["label"].to_numpy(dtype=int)
    groups = sample["h3_r3"].to_numpy()
    n_splits = min(5, positive["h3_r3"].nunique())
    splitter = StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=stable_seed(material)
    )
    baseline_oof = np.full(len(sample), np.nan)
    sentinel_oof = np.full(len(sample), np.nan)
    fold_rows: list[dict[str, Any]] = []

    for fold_id, (train_index, test_index) in enumerate(
        splitter.split(sample, labels, groups), start=1
    ):
        train = sample.iloc[train_index].copy()
        test = sample.iloc[test_index].copy()
        test_positive = test[test["label"].eq(1)]
        if test_positive.empty or test["label"].nunique() != 2:
            continue
        purge_distance = balltree_distance_km(test_positive, train)
        train = train.loc[purge_distance >= PURGE_DISTANCE_KM].copy()
        train_positive = train[train["label"].eq(1)].copy()
        if len(train_positive) < 5 or train["label"].nunique() != 2:
            continue
        train_groups = set(train["h3_r3"])
        test_groups = set(test["h3_r3"])
        groups_disjoint = train_groups.isdisjoint(test_groups)
        if not groups_disjoint:
            raise RuntimeError(f"spatial group leakage for {material} fold {fold_id}")

        train_dynamic = fold_dynamic_features(
            train, train_positive, grid_unit_counts, set(train_positive["h3_r6"])
        )
        test_dynamic = fold_dynamic_features(test, train_positive, grid_unit_counts, set())
        baseline_columns = BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES
        train_baseline = pd.concat([train[BASE_STATIC_FEATURES], train_dynamic], axis=1)[
            baseline_columns
        ]
        test_baseline = pd.concat([test[BASE_STATIC_FEATURES], test_dynamic], axis=1)[
            baseline_columns
        ]
        train_sentinel_values, test_sentinel_values = fill_sentinel_from_training(
            train, test, material, fold_id
        )
        train_sentinel = pd.concat([train_baseline, train_sentinel_values], axis=1)
        test_sentinel = pd.concat([test_baseline, test_sentinel_values], axis=1)
        for name, matrix in {
            "train_baseline": train_baseline,
            "test_baseline": test_baseline,
            "train_sentinel": train_sentinel,
            "test_sentinel": test_sentinel,
        }.items():
            if np.isinf(matrix.to_numpy(dtype=float)).any():
                raise RuntimeError(f"infinite input feature in {material} fold {fold_id}: {name}")

        baseline_model = make_model()
        sentinel_model = make_model()
        train_y = train["label"].to_numpy(dtype=int)
        test_y = test["label"].to_numpy(dtype=int)
        baseline_model.fit(train_baseline, train_y)
        sentinel_model.fit(train_sentinel, train_y)
        baseline_width = baseline_model[:-1].transform(train_baseline.iloc[:1]).shape[1]
        sentinel_width = sentinel_model[:-1].transform(train_sentinel.iloc[:1]).shape[1]
        if sentinel_width - baseline_width != len(SENTINEL_FEATURES):
            raise RuntimeError(
                f"unexpected Sentinel missingness-indicator columns for {material} fold {fold_id}"
            )
        baseline_probability = predict_probability_without_sentinel_indicators(
            baseline_model, test_baseline, f"{material} fold {fold_id} baseline"
        )
        sentinel_probability = predict_probability_without_sentinel_indicators(
            sentinel_model, test_sentinel, f"{material} fold {fold_id} Sentinel-2"
        )
        baseline_oof[test.index] = baseline_probability
        sentinel_oof[test.index] = sentinel_probability
        baseline_auc = float(roc_auc_score(test_y, baseline_probability))
        sentinel_auc = float(roc_auc_score(test_y, sentinel_probability))
        baseline_recall = recall_at_background_top5(test_y, baseline_probability)
        sentinel_recall = recall_at_background_top5(test_y, sentinel_probability)
        minimum_distance = float(balltree_distance_km(train_positive, test_positive).min())
        fold_rows.append(
            {
                "record_id": f"{summary['record_id']}-F{fold_id}",
                "material_name": material,
                "fold_id": fold_id,
                "train_positive_rows": int(train["label"].sum()),
                "train_background_rows": int(train["label"].eq(0).sum()),
                "test_positive_rows": int(test_y.sum()),
                "test_background_rows": int((test_y == 0).sum()),
                "train_spatial_groups": len(train_groups),
                "test_spatial_groups": len(test_groups),
                "train_test_groups_disjoint": groups_disjoint,
                "purge_distance_km": PURGE_DISTANCE_KM,
                "minimum_test_positive_to_training_positive_km": minimum_distance,
                "test_sentinel_complete_rate": float(sentinel_complete(test).mean()),
                "baseline_roc_auc": baseline_auc,
                "sentinel2_roc_auc": sentinel_auc,
                "delta_roc_auc": sentinel_auc - baseline_auc,
                "baseline_average_precision": float(
                    average_precision_score(test_y, baseline_probability)
                ),
                "sentinel2_average_precision": float(
                    average_precision_score(test_y, sentinel_probability)
                ),
                "baseline_recall_at_background_top5pct": baseline_recall,
                "sentinel2_recall_at_background_top5pct": sentinel_recall,
                "experiment_version": EXPERIMENT_VERSION,
            }
        )

    evaluated = np.isfinite(baseline_oof) & np.isfinite(sentinel_oof)
    evaluated_y = labels[evaluated]
    completed_folds = len(fold_rows)
    summary["background_cells_sampled"] = len(background)
    summary["background_sentinel_complete_rate"] = float(sentinel_complete(background).mean())
    summary["spatial_cv_folds"] = completed_folds
    if completed_folds < 3 or evaluated_y.size == 0 or np.unique(evaluated_y).size != 2:
        summary["sentinel2_feature_admission_decision"] = "not_evaluated_incomplete_spatial_folds"
        summary["decision_reason"] = "fewer_than_3_complete_purged_folds"
        return summary, fold_rows, 0

    evaluated_baseline = baseline_oof[evaluated]
    evaluated_sentinel = sentinel_oof[evaluated]
    evaluated_groups = groups[evaluated]
    baseline_auc = float(roc_auc_score(evaluated_y, evaluated_baseline))
    sentinel_auc = float(roc_auc_score(evaluated_y, evaluated_sentinel))
    baseline_ap = float(average_precision_score(evaluated_y, evaluated_baseline))
    sentinel_ap = float(average_precision_score(evaluated_y, evaluated_sentinel))
    fold_frame = pd.DataFrame(fold_rows)
    recall_weights = fold_frame["test_positive_rows"].to_numpy(dtype=float)
    baseline_recall = float(
        np.average(fold_frame["baseline_recall_at_background_top5pct"], weights=recall_weights)
    )
    sentinel_recall = float(
        np.average(fold_frame["sentinel2_recall_at_background_top5pct"], weights=recall_weights)
    )
    ci_low, ci_high, bootstrap_completed = spatial_group_bootstrap_delta(
        evaluated_y,
        evaluated_baseline,
        evaluated_sentinel,
        evaluated_groups,
        stable_seed(material) + 197,
    )
    delta_auc = sentinel_auc - baseline_auc
    minimum_distance = float(fold_frame["minimum_test_positive_to_training_positive_km"].min())
    intended_folds_complete = completed_folds == n_splits
    gate = bool(
        len(positive) >= MIN_ADMISSION_POSITIVE_CELLS
        and positive["h3_r3"].nunique() >= MIN_ADMISSION_SPATIAL_GROUPS
        and intended_folds_complete
        and minimum_distance >= PURGE_DISTANCE_KM - 1e-6
        and summary["positive_sentinel_complete_rate"] >= 0.80
        and sentinel_auc >= 0.60
        and delta_auc >= 0.02
        and np.isfinite(ci_low)
        and ci_low > 0
        and sentinel_recall >= baseline_recall
        and SURFACE_DISTURBANCE_LABEL_LEAKAGE_RESOLVED
    )
    if gate:
        decision = "passes_gate_for_domain_review_and_separate_shadow_ranking"
        reason = "all_predefined_support_spatial_auc_uncertainty_and_recall_gates_pass"
    elif delta_auc < 0:
        decision = "not_admitted_performance_degraded"
        reason = "paired_out_of_fold_roc_auc_decreased"
    else:
        decision = "not_admitted_inconclusive_or_below_threshold"
        reason = "one_or_more_predefined_admission_gates_failed"
    summary.update(
        {
            "oof_positive_rows": int(evaluated_y.sum()),
            "oof_background_rows": int((evaluated_y == 0).sum()),
            "baseline_roc_auc": baseline_auc,
            "sentinel2_roc_auc": sentinel_auc,
            "delta_roc_auc": delta_auc,
            "delta_roc_auc_group_bootstrap_ci95_low": ci_low,
            "delta_roc_auc_group_bootstrap_ci95_high": ci_high,
            "baseline_average_precision": baseline_ap,
            "sentinel2_average_precision": sentinel_ap,
            "delta_average_precision": sentinel_ap - baseline_ap,
            "baseline_recall_at_background_top5pct": baseline_recall,
            "sentinel2_recall_at_background_top5pct": sentinel_recall,
            "delta_recall_at_background_top5pct": sentinel_recall - baseline_recall,
            "baseline_brier_score": float(brier_score_loss(evaluated_y, evaluated_baseline)),
            "sentinel2_brier_score": float(
                brier_score_loss(evaluated_y, evaluated_sentinel)
            ),
            "folds_with_positive_auc_gain": int((fold_frame["delta_roc_auc"] > 0).sum()),
            "folds_with_negative_auc_gain": int((fold_frame["delta_roc_auc"] < 0).sum()),
            "minimum_test_positive_to_training_positive_km": minimum_distance,
            "admission_gate_result": gate,
            "sentinel2_feature_admission_decision": decision,
            "decision_reason": reason,
        }
    )
    return summary, fold_rows, bootstrap_completed


def upsert_dictionary(summary_columns: list[str], fold_columns: list[str]) -> None:
    dictionary = pd.read_csv(DICTIONARY_PATH, keep_default_na=False)
    targets = {
        "material_sentinel2_spatial_ablation": (summary_columns, SUMMARY_FIELDS),
        "material_sentinel2_spatial_ablation_folds": (fold_columns, FOLD_FIELDS),
    }
    remove = np.zeros(len(dictionary), dtype=bool)
    for table, (columns, _) in targets.items():
        remove |= dictionary["table"].eq(table) & dictionary["column"].isin(columns)
    rows = []
    for table, (columns, definitions) in targets.items():
        for column in columns:
            definition, data_type, unit = definitions[column]
            rows.append(
                {
                    "table": table,
                    "column": column,
                    "definition": definition,
                    "data_type": data_type,
                    "unit": unit,
                    "missing_value_policy": "Blank means not evaluated, not computable or not applicable; zero is retained when observed.",
                }
            )
    pd.concat([dictionary.loc[~remove], pd.DataFrame(rows)], ignore_index=True).to_csv(
        DICTIONARY_PATH, index=False
    )


def baseline_parity(
    summary_frame: pd.DataFrame, fold_frame: pd.DataFrame
) -> tuple[bool, dict[str, float]]:
    """Confirm identical samples/folds reproduce the published baseline."""
    reference_summary = pd.read_csv(REFERENCE_SUMMARY_PATH)
    reference_fold = pd.read_csv(REFERENCE_FOLD_PATH)
    summary_metrics = [
        "known_evidence_records_raw",
        "unique_positive_h3_cells",
        "positive_h3_r3_groups",
        "background_cells_sampled",
        "spatial_cv_folds",
        "oof_positive_rows",
        "oof_background_rows",
        "baseline_roc_auc",
        "baseline_average_precision",
        "baseline_recall_at_background_top5pct",
        "baseline_brier_score",
        "minimum_test_positive_to_training_positive_km",
    ]
    fold_metrics = [
        "train_positive_rows",
        "train_background_rows",
        "test_positive_rows",
        "test_background_rows",
        "train_spatial_groups",
        "test_spatial_groups",
        "minimum_test_positive_to_training_positive_km",
        "baseline_roc_auc",
        "baseline_average_precision",
        "baseline_recall_at_background_top5pct",
    ]
    current_summary = summary_frame[["material_name", *summary_metrics]].copy()
    compare_summary = reference_summary[["material_name", *summary_metrics]].copy()
    summary_join = current_summary.merge(
        compare_summary, on="material_name", suffixes=("_current", "_reference"), validate="one_to_one"
    )
    current_fold = fold_frame[["material_name", "fold_id", *fold_metrics]].copy()
    compare_fold = reference_fold[["material_name", "fold_id", *fold_metrics]].copy()
    fold_join = current_fold.merge(
        compare_fold,
        on=["material_name", "fold_id"],
        suffixes=("_current", "_reference"),
        validate="one_to_one",
    )
    differences: dict[str, float] = {}
    parity = len(summary_join) == len(summary_frame) and len(fold_join) == len(fold_frame)
    for metric in summary_metrics:
        left = pd.to_numeric(summary_join[f"{metric}_current"], errors="coerce")
        right = pd.to_numeric(summary_join[f"{metric}_reference"], errors="coerce")
        delta = (left - right).abs()
        valid = left.isna().eq(right.isna()) & (delta.fillna(0) <= 1e-8)
        differences[f"summary_{metric}_max_abs_difference"] = float(delta.max(skipna=True) or 0.0)
        parity = parity and bool(valid.all())
    for metric in fold_metrics:
        left = pd.to_numeric(fold_join[f"{metric}_current"], errors="coerce")
        right = pd.to_numeric(fold_join[f"{metric}_reference"], errors="coerce")
        delta = (left - right).abs()
        valid = left.isna().eq(right.isna()) & (delta.fillna(0) <= 1e-8)
        differences[f"fold_{metric}_max_abs_difference"] = float(delta.max(skipna=True) or 0.0)
        parity = parity and bool(valid.all())
    return bool(parity), differences


def main() -> None:
    candidate_hash_before = sha256(CANDIDATE_PATH)
    grid_hash_before = sha256(GRID_PATH)
    grid = pd.read_csv(GRID_PATH, usecols=GRID_COLUMNS, dtype={"h3_r6": str}, low_memory=False)
    sentinel = pd.read_csv(
        SENTINEL_PATH, usecols=SENTINEL_COLUMNS, dtype={"h3_r6": str}, low_memory=False
    )
    if len(grid) != grid["h3_r6"].nunique() or len(grid) != 88_857:
        raise RuntimeError("unexpected national grid identity")
    if len(sentinel) != sentinel["h3_r6"].nunique() or len(sentinel) != len(grid):
        raise RuntimeError("unexpected Sentinel-2 feature identity")
    if sentinel["feature_version"].ne(FEATURE_VERSION).any():
        raise RuntimeError("unexpected Sentinel-2 feature version")
    if sentinel["model_use_status"].ne(
        "excluded_from_v0.6_scoring_pending_spatial_ablation"
    ).any():
        raise RuntimeError("Sentinel-2 source feature exclusion contract changed")
    grid = grid.merge(
        sentinel.drop(columns=["feature_version", "model_use_status"]),
        on="h3_r6",
        how="left",
        validate="one_to_one",
    )
    if len(grid) != 88_857:
        raise RuntimeError("Sentinel-2 join changed national grid cardinality")
    grid["h3_r3"] = grid["h3_r6"].map(lambda cell: h3.cell_to_parent(cell, 3))
    grid_coords = np.radians(grid[["latitude", "longitude"]].to_numpy())
    grid_unit_counts = grid["geology_geom_id"].value_counts(dropna=True)

    known = pd.read_csv(
        KNOWN_PATH,
        usecols=[
            "record_id",
            "h3_r6",
            "latitude",
            "longitude",
            "district_2011",
            "priority_materials_json",
        ],
        dtype={"h3_r6": str},
        low_memory=False,
    )
    known = known[
        known["latitude"].between(5, 38.5)
        & known["longitude"].between(67, 99)
        & known["district_2011"].notna()
    ].copy()
    exploded = []
    for row in known.itertuples(index=False):
        for material in parse_materials(row.priority_materials_json):
            exploded.append(
                {"material_name": material, "record_id": row.record_id, "h3_r6": row.h3_r6}
            )
    evidence = pd.DataFrame(exploded)
    materials = pd.read_csv(MATERIAL_PATH, usecols=["material_name"])["material_name"].tolist()

    summaries = []
    all_folds = []
    bootstrap_counts = {}
    for material in materials:
        material_evidence = evidence[evidence["material_name"].eq(material)]
        raw_count = len(material_evidence)
        positive_h3 = material_evidence["h3_r6"].dropna().drop_duplicates()
        positive = grid[grid["h3_r6"].isin(positive_h3)].copy()
        summary, folds, bootstrap_completed = evaluate_material(
            material, raw_count, positive, grid, grid_coords, grid_unit_counts
        )
        summaries.append(summary)
        all_folds.extend(folds)
        bootstrap_counts[material] = bootstrap_completed
        print(
            {
                "material": material,
                "positive_cells": len(positive),
                "folds": summary["spatial_cv_folds"],
                "delta_auc": summary["delta_roc_auc"],
                "gate": summary["admission_gate_result"],
            }
        )

    summary_frame = pd.DataFrame(summaries, columns=list(SUMMARY_FIELDS))
    fold_frame = pd.DataFrame(all_folds, columns=list(FOLD_FIELDS))
    summary_frame.to_csv(SUMMARY_PATH, index=False, float_format="%.8f")
    fold_frame.to_csv(FOLD_PATH, index=False, float_format="%.8f")
    upsert_dictionary(list(summary_frame.columns), list(fold_frame.columns))
    candidate_hash_after = sha256(CANDIDATE_PATH)
    grid_hash_after = sha256(GRID_PATH)

    # Compare rounded public outputs with the earlier identical baseline protocol.
    public_summary = pd.read_csv(SUMMARY_PATH)
    public_folds = pd.read_csv(FOLD_PATH)
    parity_pass, parity_differences = baseline_parity(public_summary, public_folds)
    evaluated = public_summary[public_summary["spatial_cv_folds"].ge(3)]
    passed = public_summary[public_summary["admission_gate_result"].eq(True)]
    metric_columns = [
        "baseline_roc_auc",
        "sentinel2_roc_auc",
        "baseline_average_precision",
        "sentinel2_average_precision",
        "baseline_recall_at_background_top5pct",
        "sentinel2_recall_at_background_top5pct",
        "baseline_brier_score",
        "sentinel2_brier_score",
    ]
    metrics_valid = all(
        evaluated[column].dropna().between(0, 1).all() for column in metric_columns
    )
    no_observation_quality_predictors = all(
        not re.search(r"count|fraction|status|quality|flag|scene|source", feature)
        for feature in SENTINEL_FEATURES
    )
    checks = [
        {"name": "summary_rows", "passed": len(public_summary) == 50, "observed": len(public_summary), "expected": 50},
        {"name": "unique_materials", "passed": public_summary["material_name"].nunique() == 50, "observed": public_summary["material_name"].nunique(), "expected": 50},
        {"name": "unique_summary_ids", "passed": public_summary["record_id"].nunique() == 50, "observed": public_summary["record_id"].nunique(), "expected": 50},
        {"name": "evaluated_materials", "passed": len(evaluated) >= 10, "observed": len(evaluated), "expected": ">=10"},
        {"name": "fold_rows_present", "passed": len(public_folds) > 0, "observed": len(public_folds), "expected": ">0"},
        {"name": "unique_fold_ids", "passed": public_folds["record_id"].nunique() == len(public_folds), "observed": public_folds["record_id"].nunique(), "expected": len(public_folds)},
        {"name": "train_test_groups_disjoint", "passed": public_folds["train_test_groups_disjoint"].eq(True).all(), "observed": bool(public_folds["train_test_groups_disjoint"].eq(True).all()), "expected": True},
        {"name": "purge_distance_enforced", "passed": public_folds["minimum_test_positive_to_training_positive_km"].ge(PURGE_DISTANCE_KM - 1e-6).all(), "observed": float(public_folds["minimum_test_positive_to_training_positive_km"].min()), "expected": f">={PURGE_DISTANCE_KM}"},
        {"name": "metric_ranges", "passed": metrics_valid, "observed": metrics_valid, "expected": True},
        {"name": "bootstrap_replicates", "passed": all(bootstrap_counts[row.material_name] >= 400 for row in evaluated.itertuples()), "observed": min(bootstrap_counts[row.material_name] for row in evaluated.itertuples()), "expected": ">=400 per evaluated material"},
        {"name": "baseline_parity", "passed": parity_pass, "observed": parity_pass, "expected": True},
        {"name": "no_observation_quality_predictors", "passed": no_observation_quality_predictors, "observed": no_observation_quality_predictors, "expected": True},
        {"name": "post_label_surface_disturbance_leakage_guardrail", "passed": not SURFACE_DISTURBANCE_LABEL_LEAKAGE_RESOLVED, "observed": "unresolved_and_blocks_production_admission", "expected": "unresolved_and_blocks_production_admission"},
        {"name": "candidate_scores_not_recomputed", "passed": public_summary["candidate_scores_recomputed"].eq(False).all(), "observed": bool(public_summary["candidate_scores_recomputed"].eq(False).all()), "expected": True},
        {"name": "production_status_shadow_only", "passed": public_summary["production_scoring_status"].eq("not_admitted_shadow_evaluation_only").all(), "observed": sorted(public_summary["production_scoring_status"].unique().tolist()), "expected": ["not_admitted_shadow_evaluation_only"]},
        {"name": "candidate_hash_unchanged", "passed": candidate_hash_before == candidate_hash_after, "observed": candidate_hash_after, "expected": candidate_hash_before},
        {"name": "national_grid_hash_unchanged", "passed": grid_hash_before == grid_hash_after, "observed": grid_hash_after, "expected": grid_hash_before},
    ]
    for check in checks:
        check["passed"] = bool(check["passed"])
    checks_pass = all(check["passed"] for check in checks)
    validation = {
        "release_version": RELEASE_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "source_feature_version": FEATURE_VERSION,
        "input_sha256": {
            "national_grid": sha256(GRID_PATH),
            "sentinel2_surface_context": sha256(SENTINEL_PATH),
            "known_sites": sha256(KNOWN_PATH),
            "strategic_materials": sha256(MATERIAL_PATH),
            "reference_soilgrids_summary": sha256(REFERENCE_SUMMARY_PATH),
            "reference_soilgrids_folds": sha256(REFERENCE_FOLD_PATH),
            "candidate_table_before_and_after": candidate_hash_before,
        },
        "method": {
            "classifier": "L2-regularized logistic regression with class-balanced fitting",
            "feature_scaling": "training-fold 5th-to-95th-percentile robust scaling, then clipping to [-10, 10]",
            "spatial_split": "StratifiedGroupKFold grouped by H3 resolution-3",
            "purge_distance_km_around_test_positives": PURGE_DISTANCE_KM,
            "background_exclusion_from_any_positive_km": BACKGROUND_EXCLUSION_KM,
            "positive_unit": "unique H3 resolution-6 cell",
            "background_status": "deterministic pseudo-absence; not confirmed barren",
            "baseline_features": BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES,
            "added_sentinel2_features": SENTINEL_FEATURES,
            "sentinel2_feature_count": len(SENTINEL_FEATURES),
            "sentinel2_missing_values": "training-fold median imputation without Sentinel missingness indicators; observation counts, support classes and quality flags are excluded from predictors",
            "uncertainty": f"{BOOTSTRAP_REPLICATES}-replicate stratified spatial-group bootstrap of paired out-of-fold ROC-AUC delta",
            "baseline_parity_reference": "published SoilGrids ablation, which uses identical evidence, background sampling, folds, purge and baseline model",
            "post_label_surface_disturbance_leakage": "unresolved: 2025 reflectance at known sites can encode mining disturbance or infrastructure rather than pre-discovery geology",
        },
        "admission_gate": {
            "minimum_unique_positive_cells": MIN_ADMISSION_POSITIVE_CELLS,
            "minimum_positive_h3_r3_groups": MIN_ADMISSION_SPATIAL_GROUPS,
            "all_planned_folds_complete": True,
            "minimum_positive_complete_sentinel2_coverage": 0.80,
            "minimum_sentinel2_roc_auc": 0.60,
            "minimum_delta_roc_auc": 0.02,
            "delta_auc_ci95_lower_bound_strictly_positive": True,
            "sentinel2_recall_at_background_top5pct_not_lower_than_baseline": True,
            "post_label_surface_disturbance_leakage_resolved": SURFACE_DISTURBANCE_LABEL_LEAKAGE_RESOLVED,
            "production_admission_effect": "None. Statistical criteria plus leakage resolution would permit domain review and a separate shadow-ranking test only.",
        },
        "summary_rows": len(public_summary),
        "fold_rows": len(public_folds),
        "evaluated_materials": len(evaluated),
        "materials_passing_shadow_gate": len(passed),
        "passing_materials": passed["material_name"].tolist(),
        "materials_with_positive_pooled_auc_delta": int(evaluated["delta_roc_auc"].gt(0).sum()),
        "materials_with_negative_pooled_auc_delta": int(evaluated["delta_roc_auc"].lt(0).sum()),
        "candidate_scores_recomputed": False,
        "production_scoring_changed": False,
        "candidate_table_sha256_unchanged": candidate_hash_before == candidate_hash_after,
        "national_grid_sha256_unchanged": grid_hash_before == grid_hash_after,
        "baseline_parity_with_existing_ablation": parity_pass,
        "baseline_parity_max_abs_differences": parity_differences,
        "checks": checks,
        "checks_pass": checks_pass,
        "output_sha256": {
            "summary_csv": sha256(SUMMARY_PATH),
            "fold_csv": sha256(FOLD_PATH),
        },
    }
    VALIDATION_PATH.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    release_path = OUT / "validation_report.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["sentinel2_surface_context"]["source_feature_table_model_use_status"] = (
        "excluded_from_v0.6_scoring_pending_spatial_ablation"
    )
    release["sentinel2_surface_context"]["model_use_status"] = (
        "excluded_from_v0.6_scoring_after_alpha19_spatial_ablation"
    )
    release["sentinel2_surface_context"]["post_build_evaluation_status"] = (
        "no_material_passed_all_support_coverage_auc_uncertainty_recall_and_leakage_gates"
    )
    release["sentinel2_spatial_ablation"] = {
        key: validation[key]
        for key in [
            "experiment_version",
            "summary_rows",
            "fold_rows",
            "evaluated_materials",
            "materials_passing_shadow_gate",
            "passing_materials",
            "materials_with_positive_pooled_auc_delta",
            "materials_with_negative_pooled_auc_delta",
            "candidate_scores_recomputed",
            "production_scoring_changed",
            "candidate_table_sha256_unchanged",
            "baseline_parity_with_existing_ablation",
            "checks_pass",
        ]
    }
    release_path.write_text(
        json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not checks_pass:
        raise SystemExit("Sentinel-2 spatial ablation validation failed")


if __name__ == "__main__":
    main()
