#!/usr/bin/env python3
"""Evaluate whether EMAG2v3 adds spatially generalizable mineral signal.

This is a shadow-model experiment. It compares the same regularized logistic
classifier with and without EMAG2 features under purged H3-res3 grouped folds.
It never rewrites candidate scores, classes, or ranks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, RobustScaler
from sklearn.neighbors import BallTree
from scipy.special import expit


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
KNOWN_PATH = OUT / "india_known_mining_sites.csv"
MATERIAL_PATH = OUT / "india_strategic_materials_top50.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"
SUMMARY_PATH = OUT / "material_emag2_spatial_ablation.csv"
FOLD_PATH = OUT / "material_emag2_spatial_ablation_folds.csv"
VALIDATION_PATH = OUT / "emag2_spatial_ablation_validation.json"
DICTIONARY_PATH = OUT / "data_dictionary.csv"

RELEASE_VERSION = "v1.0-alpha.5"
EXPERIMENT_VERSION = "emag2-spatial-ablation-v0.1"
EARTH_RADIUS_KM = 6371.0088
GLOBAL_SEED = 20260910
MIN_EVALUATION_POSITIVE_CELLS = 10
MIN_ADMISSION_POSITIVE_CELLS = 20
MIN_ADMISSION_SPATIAL_GROUPS = 4
PURGE_DISTANCE_KM = 50.0
BACKGROUND_EXCLUSION_KM = 25.0
BOOTSTRAP_REPLICATES = 500

BASE_STATIC_FEATURES = [
    "elevation_m",
    "slope_degrees_approx",
    "local_relief_m_approx",
    "temperature_mean_c_rolling_12m",
    "precipitation_total_mm_rolling_12m",
    "relative_humidity_mean_pct_rolling_12m",
    "wind_speed_2m_mean_m_s_rolling_12m",
]
BASE_DYNAMIC_FEATURES = [
    "fold_safe_log1p_distance_to_training_positive_km",
    "fold_safe_log1p_training_positive_count_100km",
    "fold_safe_training_positive_geology_affinity",
]
EMAG_FEATURES = [
    "emag2_upcont_anomaly_nt",
    "emag2_upcont_abs_anomaly_nt",
    "emag2_upcont_local_mean_nt_3x3",
    "emag2_upcont_local_std_nt_3x3",
    "emag2_upcont_local_range_nt_3x3",
    "emag2_anomaly_robust_z_india_h3",
    "emag2_abs_robust_z_india_h3",
    "emag2_error_estimate_nt",
    "emag2_abs_signal_to_error_ratio",
    "emag2_source_ambiguous_or_no_data",
]
GRID_COLUMNS = [
    "h3_r6",
    "latitude",
    "longitude",
    "geology_geom_id",
    *BASE_STATIC_FEATURES,
    *EMAG_FEATURES,
]


SUMMARY_FIELDS = {
    "record_id": ("Stable material-ablation record identifier.", "text", ""),
    "material_name": ("Normalized v0.6 modeling-target name.", "text", ""),
    "known_evidence_records_raw": ("Coordinate-valid source records naming the material before H3-cell deduplication.", "integer", "records"),
    "unique_positive_h3_cells": ("Unique H3 resolution-6 positive cells used for eligibility.", "integer", "cells"),
    "positive_h3_r3_groups": ("Unique H3 resolution-3 groups containing positive cells.", "integer", "groups"),
    "positive_emag_valid_cells": ("Positive cells with a valid EMAG2 anomaly.", "integer", "cells"),
    "positive_emag_valid_rate": ("Share of positive cells with a valid EMAG2 anomaly.", "number", "0-1 share"),
    "background_cells_sampled": ("Deterministically sampled pseudo-absence cells farther than 25 km from any positive cell.", "integer", "cells"),
    "background_emag_valid_rate": ("Share of sampled background cells with a valid EMAG2 anomaly.", "number", "0-1 share"),
    "spatial_cv_folds": ("Completed purged spatial cross-validation folds.", "integer", "folds"),
    "oof_positive_rows": ("Positive rows with paired out-of-fold predictions.", "integer", "rows"),
    "oof_background_rows": ("Background rows with paired out-of-fold predictions.", "integer", "rows"),
    "baseline_roc_auc": ("Pooled out-of-fold pseudo-absence ROC AUC without EMAG2.", "number", "0-1"),
    "emag_roc_auc": ("Pooled out-of-fold pseudo-absence ROC AUC after adding EMAG2.", "number", "0-1"),
    "delta_roc_auc": ("EMAG ROC AUC minus baseline ROC AUC on identical out-of-fold rows.", "number", "AUC points"),
    "delta_roc_auc_group_bootstrap_ci95_low": ("Lower 2.5th percentile of the spatial-group bootstrap AUC delta.", "number", "AUC points"),
    "delta_roc_auc_group_bootstrap_ci95_high": ("Upper 97.5th percentile of the spatial-group bootstrap AUC delta.", "number", "AUC points"),
    "baseline_average_precision": ("Pooled out-of-fold average precision without EMAG2.", "number", "0-1"),
    "emag_average_precision": ("Pooled out-of-fold average precision after adding EMAG2.", "number", "0-1"),
    "delta_average_precision": ("EMAG average precision minus baseline average precision.", "number", "AP points"),
    "baseline_recall_at_background_top5pct": ("Positive recall at each fold's baseline background 95th-percentile threshold.", "number", "0-1"),
    "emag_recall_at_background_top5pct": ("Positive recall at each fold's EMAG background 95th-percentile threshold.", "number", "0-1"),
    "delta_recall_at_background_top5pct": ("EMAG recall minus baseline recall at the paired background threshold.", "number", "recall points"),
    "baseline_brier_score": ("Out-of-fold mean squared probability error without EMAG2; class-balanced fitting makes calibration provisional.", "number", "0-1 loss"),
    "emag_brier_score": ("Out-of-fold mean squared probability error after adding EMAG2; class-balanced fitting makes calibration provisional.", "number", "0-1 loss"),
    "folds_with_positive_auc_gain": ("Completed folds where EMAG2 increased ROC AUC.", "integer", "folds"),
    "folds_with_negative_auc_gain": ("Completed folds where EMAG2 decreased ROC AUC.", "integer", "folds"),
    "minimum_test_positive_to_training_positive_km": ("Smallest held-out-positive distance to a retained training positive after spatial purge.", "number", "km"),
    "admission_gate_result": ("Whether the predefined evidence gate passed; this does not itself admit the feature to production scoring.", "boolean", ""),
    "emag_feature_admission_decision": ("Shadow-model interpretation of the ablation result.", "category", ""),
    "decision_reason": ("Machine-readable concise reason for the admission decision.", "text", ""),
    "production_scoring_status": ("Production-use state; always not admitted in this experiment.", "category", ""),
    "candidate_scores_recomputed": ("Whether this experiment rewrote candidate scores, classes, or ranks.", "boolean", ""),
    "experiment_version": ("Version of the ablation method.", "text", ""),
    "background_interpretation": ("Required caveat for pseudo-absence cells.", "text", ""),
    "baseline_features_json": ("JSON array of baseline feature names.", "JSON array", ""),
    "emag_features_json": ("JSON array of added EMAG2 feature names.", "JSON array", ""),
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
    "test_emag_valid_rate": ("Share of test rows with a valid EMAG2 anomaly.", "number", "0-1 share"),
    "baseline_roc_auc": ("Fold pseudo-absence ROC AUC without EMAG2.", "number", "0-1"),
    "emag_roc_auc": ("Fold pseudo-absence ROC AUC after adding EMAG2.", "number", "0-1"),
    "delta_roc_auc": ("Fold EMAG ROC AUC minus baseline ROC AUC.", "number", "AUC points"),
    "baseline_average_precision": ("Fold average precision without EMAG2.", "number", "0-1"),
    "emag_average_precision": ("Fold average precision after adding EMAG2.", "number", "0-1"),
    "baseline_recall_at_background_top5pct": ("Fold positive recall above the baseline background 95th percentile.", "number", "0-1"),
    "emag_recall_at_background_top5pct": ("Fold positive recall above the EMAG background 95th percentile.", "number", "0-1"),
    "experiment_version": ("Version of the ablation method.", "text", ""),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(material: str) -> int:
    value = int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16)
    return (GLOBAL_SEED + value) % (2**32 - 1)


def parse_materials(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def make_model() -> Any:
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        RobustScaler(quantile_range=(5.0, 95.0)),
        FunctionTransformer(clip_scaled_features, validate=False),
        LogisticRegression(
            solver="liblinear",
            C=1.0,
            class_weight="balanced",
            max_iter=2000,
            random_state=GLOBAL_SEED,
        ),
    )


def clip_scaled_features(values: np.ndarray) -> np.ndarray:
    """Bound fold-extrapolation without using any test-fold statistics."""
    values = np.nan_to_num(values, nan=0.0, posinf=10.0, neginf=-10.0)
    return np.clip(values, -10.0, 10.0)


def predict_probability_checked(model: Any, features: pd.DataFrame, context: str) -> np.ndarray:
    """Compute finite logistic probabilities and reject numerical failures."""
    transformed = model[:-1].transform(features)
    if not np.isfinite(transformed).all() or not np.isfinite(model[-1].coef_).all():
        raise RuntimeError(f"non-finite fitted model inputs or coefficients: {context}")
    # Accelerate-backed NumPy can retain benign floating-point status flags
    # across a finite matrix product; suppress flags locally, then validate.
    with np.errstate(all="ignore"):
        decision = transformed @ model[-1].coef_.T + model[-1].intercept_
    if not np.isfinite(decision).all():
        raise RuntimeError(f"non-finite logistic decision score: {context}")
    return expit(decision[:, 0])


def balltree_distance_km(reference: pd.DataFrame, query: pd.DataFrame) -> np.ndarray:
    tree = BallTree(np.radians(reference[["latitude", "longitude"]].to_numpy()), metric="haversine")
    distance, _ = tree.query(np.radians(query[["latitude", "longitude"]].to_numpy()), k=1)
    return distance[:, 0] * EARTH_RADIUS_KM


def fold_dynamic_features(
    sample: pd.DataFrame,
    train_positive: pd.DataFrame,
    grid_unit_counts: pd.Series,
    leave_one_out_h3: set[str],
) -> pd.DataFrame:
    reference_coords = np.radians(train_positive[["latitude", "longitude"]].to_numpy())
    query_coords = np.radians(sample[["latitude", "longitude"]].to_numpy())
    tree = BallTree(reference_coords, metric="haversine")
    k = 2 if len(train_positive) >= 2 else 1
    distances, _ = tree.query(query_coords, k=k)
    nearest_km = distances[:, 0] * EARTH_RADIUS_KM
    self_mask = sample["h3_r6"].isin(leave_one_out_h3).to_numpy()
    if k == 2:
        nearest_km[self_mask] = distances[self_mask, 1] * EARTH_RADIUS_KM
    density = tree.query_radius(query_coords, r=100 / EARTH_RADIUS_KM, count_only=True).astype(float)
    density[self_mask] = np.maximum(0, density[self_mask] - 1)

    positive_counts = train_positive["geology_geom_id"].value_counts(dropna=True)
    raw_affinity = {
        unit: (float(count) + 0.5) / (float(grid_unit_counts.get(unit, 0)) + 5.0)
        for unit, count in positive_counts.items()
    }
    affinity_scale = max(float(np.percentile(list(raw_affinity.values()), 95)), 1e-12) if raw_affinity else 1.0
    affinity = []
    for is_self, unit in zip(self_mask, sample["geology_geom_id"]):
        if pd.isna(unit):
            affinity.append(0.0)
            continue
        count = float(positive_counts.get(unit, 0)) - (1.0 if is_self else 0.0)
        raw = (max(0.0, count) + 0.5) / (float(grid_unit_counts.get(unit, 0)) + 5.0)
        affinity.append(min(1.0, raw / affinity_scale))
    return pd.DataFrame(
        {
            BASE_DYNAMIC_FEATURES[0]: np.log1p(np.minimum(nearest_km, 3000.0)),
            BASE_DYNAMIC_FEATURES[1]: np.log1p(density),
            BASE_DYNAMIC_FEATURES[2]: affinity,
        },
        index=sample.index,
    )


def recall_at_background_top5(y: np.ndarray, probability: np.ndarray) -> float:
    background = probability[y == 0]
    positive = probability[y == 1]
    if not len(background) or not len(positive):
        return math.nan
    threshold = float(np.percentile(background, 95))
    return float(np.mean(positive >= threshold))


def spatial_group_bootstrap_delta(
    y: np.ndarray,
    base_probability: np.ndarray,
    emag_probability: np.ndarray,
    groups: np.ndarray,
    seed: int,
) -> tuple[float, float, int]:
    frame = pd.DataFrame({"y": y, "base": base_probability, "emag": emag_probability, "group": groups})
    grouped = {group: rows.index.to_numpy() for group, rows in frame.groupby("group", sort=True)}
    positive_groups = sorted(frame.loc[frame["y"].eq(1), "group"].unique())
    background_only_groups = sorted(set(grouped) - set(positive_groups))
    if len(positive_groups) < 3 or not background_only_groups:
        return math.nan, math.nan, 0
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected_positive = rng.choice(positive_groups, size=len(positive_groups), replace=True)
        selected_background = rng.choice(background_only_groups, size=len(background_only_groups), replace=True)
        indexes = np.concatenate([grouped[group] for group in np.concatenate([selected_positive, selected_background])])
        boot_y = y[indexes]
        if np.unique(boot_y).size != 2:
            continue
        deltas.append(
            roc_auc_score(boot_y, emag_probability[indexes])
            - roc_auc_score(boot_y, base_probability[indexes])
        )
    if not deltas:
        return math.nan, math.nan, 0
    low, high = np.percentile(deltas, [2.5, 97.5])
    return float(low), float(high), len(deltas)


def blank_summary(material: str, raw_count: int, positive: pd.DataFrame) -> dict[str, Any]:
    groups = positive["h3_r3"].nunique() if len(positive) else 0
    valid = int(positive["emag2_upcont_anomaly_nt"].notna().sum()) if len(positive) else 0
    return {
        "record_id": "EMAG2-ABL-" + re.sub(r"[^A-Z0-9]+", "-", material.upper()).strip("-"),
        "material_name": material,
        "known_evidence_records_raw": raw_count,
        "unique_positive_h3_cells": len(positive),
        "positive_h3_r3_groups": groups,
        "positive_emag_valid_cells": valid,
        "positive_emag_valid_rate": valid / len(positive) if len(positive) else math.nan,
        "background_cells_sampled": 0,
        "background_emag_valid_rate": math.nan,
        "spatial_cv_folds": 0,
        "oof_positive_rows": 0,
        "oof_background_rows": 0,
        "baseline_roc_auc": math.nan,
        "emag_roc_auc": math.nan,
        "delta_roc_auc": math.nan,
        "delta_roc_auc_group_bootstrap_ci95_low": math.nan,
        "delta_roc_auc_group_bootstrap_ci95_high": math.nan,
        "baseline_average_precision": math.nan,
        "emag_average_precision": math.nan,
        "delta_average_precision": math.nan,
        "baseline_recall_at_background_top5pct": math.nan,
        "emag_recall_at_background_top5pct": math.nan,
        "delta_recall_at_background_top5pct": math.nan,
        "baseline_brier_score": math.nan,
        "emag_brier_score": math.nan,
        "folds_with_positive_auc_gain": 0,
        "folds_with_negative_auc_gain": 0,
        "minimum_test_positive_to_training_positive_km": math.nan,
        "admission_gate_result": False,
        "emag_feature_admission_decision": "not_evaluated_low_support",
        "decision_reason": "fewer_than_10_unique_positive_h3_cells" if len(positive) < 10 else "fewer_than_3_positive_h3_r3_groups",
        "production_scoring_status": "not_admitted_shadow_evaluation_only",
        "candidate_scores_recomputed": False,
        "experiment_version": EXPERIMENT_VERSION,
        "background_interpretation": "Pseudo-absence cells are not confirmed barren and metrics do not estimate discovery probability.",
        "baseline_features_json": json.dumps(BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES, separators=(",", ":")),
        "emag_features_json": json.dumps(EMAG_FEATURES, separators=(",", ":")),
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

    positive_tree = BallTree(np.radians(positive[["latitude", "longitude"]].to_numpy()), metric="haversine")
    distance_to_positive, _ = positive_tree.query(grid_coords, k=1)
    pool_mask = distance_to_positive[:, 0] * EARTH_RADIUS_KM > BACKGROUND_EXCLUSION_KM
    pool_mask &= ~grid["h3_r6"].isin(positive["h3_r6"]).to_numpy()
    pool_index = np.flatnonzero(pool_mask)
    if len(pool_index) < 500:
        summary["emag_feature_admission_decision"] = "not_evaluated_insufficient_background"
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
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=stable_seed(material))
    base_oof = np.full(len(sample), np.nan)
    emag_oof = np.full(len(sample), np.nan)
    fold_rows: list[dict[str, Any]] = []

    for fold_id, (train_index, test_index) in enumerate(splitter.split(sample, labels, groups), start=1):
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

        train_dynamic = fold_dynamic_features(train, train_positive, grid_unit_counts, set(train_positive["h3_r6"]))
        test_dynamic = fold_dynamic_features(test, train_positive, grid_unit_counts, set())
        baseline_columns = BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES
        train_base = pd.concat([train[BASE_STATIC_FEATURES], train_dynamic], axis=1)[baseline_columns]
        test_base = pd.concat([test[BASE_STATIC_FEATURES], test_dynamic], axis=1)[baseline_columns]
        train_emag = pd.concat([train_base, train[EMAG_FEATURES]], axis=1)
        test_emag = pd.concat([test_base, test[EMAG_FEATURES]], axis=1)
        for name, matrix in {
            "train_base": train_base,
            "test_base": test_base,
            "train_emag": train_emag,
            "test_emag": test_emag,
        }.items():
            if np.isinf(matrix.to_numpy(dtype=float)).any():
                raise RuntimeError(f"infinite input feature in {material} fold {fold_id}: {name}")

        base_model = make_model()
        emag_model = make_model()
        train_y = train["label"].to_numpy(dtype=int)
        test_y = test["label"].to_numpy(dtype=int)
        base_model.fit(train_base, train_y)
        emag_model.fit(train_emag, train_y)
        base_probability = predict_probability_checked(base_model, test_base, f"{material} fold {fold_id} baseline")
        emag_probability = predict_probability_checked(emag_model, test_emag, f"{material} fold {fold_id} EMAG")
        base_oof[test.index] = base_probability
        emag_oof[test.index] = emag_probability
        base_auc = float(roc_auc_score(test_y, base_probability))
        emag_auc = float(roc_auc_score(test_y, emag_probability))
        base_recall = recall_at_background_top5(test_y, base_probability)
        emag_recall = recall_at_background_top5(test_y, emag_probability)
        min_distance = float(balltree_distance_km(train_positive, test_positive).min())
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
                "minimum_test_positive_to_training_positive_km": min_distance,
                "test_emag_valid_rate": float(test["emag2_upcont_anomaly_nt"].notna().mean()),
                "baseline_roc_auc": base_auc,
                "emag_roc_auc": emag_auc,
                "delta_roc_auc": emag_auc - base_auc,
                "baseline_average_precision": float(average_precision_score(test_y, base_probability)),
                "emag_average_precision": float(average_precision_score(test_y, emag_probability)),
                "baseline_recall_at_background_top5pct": base_recall,
                "emag_recall_at_background_top5pct": emag_recall,
                "experiment_version": EXPERIMENT_VERSION,
            }
        )

    evaluated = np.isfinite(base_oof) & np.isfinite(emag_oof)
    evaluated_y = labels[evaluated]
    completed_folds = len(fold_rows)
    summary["background_cells_sampled"] = len(background)
    summary["background_emag_valid_rate"] = float(background["emag2_upcont_anomaly_nt"].notna().mean())
    summary["spatial_cv_folds"] = completed_folds
    if completed_folds < 3 or evaluated_y.size == 0 or np.unique(evaluated_y).size != 2:
        summary["emag_feature_admission_decision"] = "not_evaluated_incomplete_spatial_folds"
        summary["decision_reason"] = "fewer_than_3_complete_purged_folds"
        return summary, fold_rows, 0

    evaluated_base = base_oof[evaluated]
    evaluated_emag = emag_oof[evaluated]
    evaluated_groups = groups[evaluated]
    base_auc = float(roc_auc_score(evaluated_y, evaluated_base))
    emag_auc = float(roc_auc_score(evaluated_y, evaluated_emag))
    base_ap = float(average_precision_score(evaluated_y, evaluated_base))
    emag_ap = float(average_precision_score(evaluated_y, evaluated_emag))
    fold_frame = pd.DataFrame(fold_rows)
    recall_weights = fold_frame["test_positive_rows"].to_numpy(dtype=float)
    base_recall = float(np.average(fold_frame["baseline_recall_at_background_top5pct"], weights=recall_weights))
    emag_recall = float(np.average(fold_frame["emag_recall_at_background_top5pct"], weights=recall_weights))
    ci_low, ci_high, bootstrap_completed = spatial_group_bootstrap_delta(
        evaluated_y,
        evaluated_base,
        evaluated_emag,
        evaluated_groups,
        stable_seed(material) + 71,
    )
    delta_auc = emag_auc - base_auc
    minimum_distance = float(fold_frame["minimum_test_positive_to_training_positive_km"].min())
    intended_folds_complete = completed_folds == n_splits
    gate = bool(
        len(positive) >= MIN_ADMISSION_POSITIVE_CELLS
        and positive["h3_r3"].nunique() >= MIN_ADMISSION_SPATIAL_GROUPS
        and intended_folds_complete
        and minimum_distance >= PURGE_DISTANCE_KM - 1e-6
        and summary["positive_emag_valid_rate"] >= 0.80
        and emag_auc >= 0.60
        and delta_auc >= 0.02
        and np.isfinite(ci_low)
        and ci_low > 0
        and emag_recall >= base_recall
    )
    if gate:
        decision = "passes_gate_for_separate_shadow_ranking_test"
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
            "baseline_roc_auc": base_auc,
            "emag_roc_auc": emag_auc,
            "delta_roc_auc": delta_auc,
            "delta_roc_auc_group_bootstrap_ci95_low": ci_low,
            "delta_roc_auc_group_bootstrap_ci95_high": ci_high,
            "baseline_average_precision": base_ap,
            "emag_average_precision": emag_ap,
            "delta_average_precision": emag_ap - base_ap,
            "baseline_recall_at_background_top5pct": base_recall,
            "emag_recall_at_background_top5pct": emag_recall,
            "delta_recall_at_background_top5pct": emag_recall - base_recall,
            "baseline_brier_score": float(brier_score_loss(evaluated_y, evaluated_base)),
            "emag_brier_score": float(brier_score_loss(evaluated_y, evaluated_emag)),
            "folds_with_positive_auc_gain": int((fold_frame["delta_roc_auc"] > 0).sum()),
            "folds_with_negative_auc_gain": int((fold_frame["delta_roc_auc"] < 0).sum()),
            "minimum_test_positive_to_training_positive_km": minimum_distance,
            "admission_gate_result": gate,
            "emag_feature_admission_decision": decision,
            "decision_reason": reason,
        }
    )
    return summary, fold_rows, bootstrap_completed


def upsert_dictionary(summary_columns: list[str], fold_columns: list[str]) -> None:
    dictionary = pd.read_csv(DICTIONARY_PATH, keep_default_na=False)
    targets = {
        "material_emag2_spatial_ablation": (summary_columns, SUMMARY_FIELDS),
        "material_emag2_spatial_ablation_folds": (fold_columns, FOLD_FIELDS),
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
                    "missing_value_policy": "Blank means not evaluated, not computable, or not applicable; zero is retained when observed.",
                }
            )
    pd.concat([dictionary.loc[~remove], pd.DataFrame(rows)], ignore_index=True).to_csv(DICTIONARY_PATH, index=False)


def main() -> None:
    candidate_hash_before = sha256(CANDIDATE_PATH)
    grid = pd.read_csv(GRID_PATH, usecols=GRID_COLUMNS, dtype={"h3_r6": str}, low_memory=False)
    if len(grid) != grid["h3_r6"].nunique() or len(grid) != 88_857:
        raise RuntimeError("unexpected national grid identity")
    grid["emag2_source_ambiguous_or_no_data"] = (
        grid["emag2_source_ambiguous_or_no_data"].astype(str).str.lower().eq("true").astype(int)
    )
    grid["h3_r3"] = grid["h3_r6"].map(lambda cell: h3.cell_to_parent(cell, 3))
    grid_coords = np.radians(grid[["latitude", "longitude"]].to_numpy())
    grid_unit_counts = grid["geology_geom_id"].value_counts(dropna=True)

    known = pd.read_csv(
        KNOWN_PATH,
        usecols=["record_id", "h3_r6", "latitude", "longitude", "district_2011", "priority_materials_json"],
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
            exploded.append({"material_name": material, "record_id": row.record_id, "h3_r6": row.h3_r6})
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
            material,
            raw_count,
            positive,
            grid,
            grid_coords,
            grid_unit_counts,
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

    evaluated = summary_frame[summary_frame["spatial_cv_folds"].ge(3)]
    passed = summary_frame[summary_frame["admission_gate_result"].eq(True)]
    metric_columns = [
        "baseline_roc_auc",
        "emag_roc_auc",
        "baseline_average_precision",
        "emag_average_precision",
        "baseline_recall_at_background_top5pct",
        "emag_recall_at_background_top5pct",
        "baseline_brier_score",
        "emag_brier_score",
    ]
    metrics_valid = all(evaluated[column].dropna().between(0, 1).all() for column in metric_columns)
    checks_pass = bool(
        len(summary_frame) == summary_frame["material_name"].nunique() == 50
        and len(evaluated) >= 10
        and not fold_frame.empty
        and fold_frame["train_test_groups_disjoint"].eq(True).all()
        and fold_frame["minimum_test_positive_to_training_positive_km"].ge(PURGE_DISTANCE_KM - 1e-6).all()
        and summary_frame["candidate_scores_recomputed"].eq(False).all()
        and summary_frame["production_scoring_status"].eq("not_admitted_shadow_evaluation_only").all()
        and candidate_hash_before == candidate_hash_after
        and metrics_valid
        and all(bootstrap_counts[row.material_name] >= 400 for row in evaluated.itertuples())
    )
    validation = {
        "release_version": RELEASE_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "input_sha256": {
            "national_grid": sha256(GRID_PATH),
            "known_sites": sha256(KNOWN_PATH),
            "strategic_materials": sha256(MATERIAL_PATH),
            "candidate_table_before_and_after": candidate_hash_before,
        },
        "method": {
            "classifier": "L2-regularized logistic regression with class-balanced fitting",
            "feature_scaling": "training-fold 5th-to-95th-percentile robust scaling, then clipping to [-10, 10] to bound spatial-fold extrapolation",
            "spatial_split": "StratifiedGroupKFold grouped by H3 resolution-3",
            "purge_distance_km_around_test_positives": PURGE_DISTANCE_KM,
            "background_exclusion_from_any_positive_km": BACKGROUND_EXCLUSION_KM,
            "positive_unit": "unique H3 resolution-6 cell",
            "background_status": "deterministic pseudo-absence; not confirmed barren",
            "baseline_features": BASE_STATIC_FEATURES + BASE_DYNAMIC_FEATURES,
            "added_emag2_features": EMAG_FEATURES,
            "missing_values": "training-fold median imputation plus missingness indicators",
            "uncertainty": f"{BOOTSTRAP_REPLICATES}-replicate stratified spatial-group bootstrap of paired out-of-fold ROC-AUC delta",
        },
        "admission_gate": {
            "minimum_unique_positive_cells": MIN_ADMISSION_POSITIVE_CELLS,
            "minimum_positive_h3_r3_groups": MIN_ADMISSION_SPATIAL_GROUPS,
            "all_planned_folds_complete": True,
            "minimum_positive_emag_coverage": 0.80,
            "minimum_emag_roc_auc": 0.60,
            "minimum_delta_roc_auc": 0.02,
            "delta_auc_ci95_lower_bound_strictly_positive": True,
            "emag_recall_at_background_top5pct_not_lower_than_baseline": True,
            "production_admission_effect": "None. Passing only permits a separate shadow-ranking test.",
        },
        "summary_rows": len(summary_frame),
        "fold_rows": len(fold_frame),
        "evaluated_materials": len(evaluated),
        "materials_passing_shadow_gate": len(passed),
        "passing_materials": passed["material_name"].tolist(),
        "materials_with_positive_pooled_auc_delta": int(evaluated["delta_roc_auc"].gt(0).sum()),
        "materials_with_negative_pooled_auc_delta": int(evaluated["delta_roc_auc"].lt(0).sum()),
        "candidate_scores_recomputed": False,
        "production_scoring_changed": False,
        "candidate_table_sha256_unchanged": candidate_hash_before == candidate_hash_after,
        "output_sha256": {
            "summary_csv": sha256(SUMMARY_PATH),
            "fold_csv": sha256(FOLD_PATH),
        },
        "checks_pass": checks_pass,
    }
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    release_path = OUT / "validation_report.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["emag2_spatial_ablation"] = {
        key: validation[key]
        for key in [
            "experiment_version",
            "summary_rows",
            "fold_rows",
            "evaluated_materials",
            "materials_passing_shadow_gate",
            "passing_materials",
            "candidate_scores_recomputed",
            "production_scoring_changed",
            "candidate_table_sha256_unchanged",
            "checks_pass",
        ]
    }
    release_path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not checks_pass:
        raise SystemExit("EMAG2 spatial ablation validation failed")


if __name__ == "__main__":
    main()
