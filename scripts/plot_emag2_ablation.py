#!/usr/bin/env python3
"""Plot paired EMAG2 spatial-ablation results for the KHANAN README."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "material_emag2_spatial_ablation.csv"
ASSET = ROOT / "assets" / "figures" / "khanan-emag2-spatial-ablation-v0.1.png"


def main() -> None:
    data = pd.read_csv(SOURCE)
    data = data[data["spatial_cv_folds"].ge(3)].sort_values("delta_roc_auc").reset_index(drop=True)
    if data.empty:
        raise RuntimeError("no evaluated ablation rows")

    y = np.arange(len(data))
    delta_auc = data["delta_roc_auc"].to_numpy()
    ci_low = data["delta_roc_auc_group_bootstrap_ci95_low"].to_numpy()
    ci_high = data["delta_roc_auc_group_bootstrap_ci95_high"].to_numpy()
    colors = np.where(delta_auc >= 0, "#0f766e", "#b91c1c")

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titleweight": "bold"})
    fig, (ax_auc, ax_recall) = plt.subplots(
        1,
        2,
        figsize=(13.4, 8.4),
        dpi=180,
        facecolor="#f8fafc",
        gridspec_kw={"width_ratios": [1.65, 1.0]},
    )
    for ax in (ax_auc, ax_recall):
        ax.set_facecolor("#ffffff")
        ax.axvline(0, color="#475569", linewidth=0.9, linestyle="--", zorder=1)
        ax.grid(axis="x", color="#cbd5e1", linewidth=0.45, alpha=0.7)
        ax.set_axisbelow(True)

    ax_auc.hlines(y, ci_low, ci_high, color="#94a3b8", linewidth=1.5, zorder=2)
    ax_auc.scatter(delta_auc, y, c=colors, s=42, edgecolors="white", linewidths=0.6, zorder=3)
    ax_auc.set_yticks(y)
    ax_auc.set_yticklabels(
        [f"{row.material_name}  (n={row.unique_positive_h3_cells})" for row in data.itertuples()],
        fontsize=8.5,
    )
    ax_auc.set_xlabel("Paired out-of-fold ROC-AUC change after adding EMAG2", fontsize=9)
    ax_auc.set_title("Incremental discrimination with spatial-group 95% intervals", fontsize=11.5, pad=12)
    auc_extent = max(abs(ci_low.min()), abs(ci_high.max()), 0.08)
    ax_auc.set_xlim(-auc_extent * 1.12, auc_extent * 1.12)

    recall_delta = data["delta_recall_at_background_top5pct"].to_numpy()
    recall_colors = np.where(recall_delta >= 0, "#0f766e", "#b91c1c")
    ax_recall.scatter(recall_delta, y, c=recall_colors, s=42, edgecolors="white", linewidths=0.6, zorder=3)
    ax_recall.set_yticks(y)
    ax_recall.set_yticklabels([])
    ax_recall.set_xlabel("Recall change at paired background top 5%", fontsize=9)
    ax_recall.set_title("High-score recall change", fontsize=11.5, pad=12)
    recall_extent = max(abs(recall_delta.min()), abs(recall_delta.max()), 0.10)
    ax_recall.set_xlim(-recall_extent * 1.18, recall_extent * 1.18)

    for axis in (ax_auc, ax_recall):
        axis.tick_params(axis="x", labelsize=8, colors="#475569")
        for side in ["top", "right", "left"]:
            axis.spines[side].set_visible(False)
        axis.spines["bottom"].set_color("#94a3b8")

    passed = int(data["admission_gate_result"].sum())
    fig.suptitle("KHANAN — EMAG2 Spatial Ablation", fontsize=18, color="#0f172a", y=0.975)
    fig.text(
        0.5,
        0.932,
        (
            f"{len(data)} materials evaluated • unique H3 r6 positives • purged H3 r3 folds • "
            f"50 km positive buffer • {passed} passed the shadow gate"
        ),
        ha="center",
        fontsize=9.5,
        color="#475569",
    )
    fig.text(
        0.5,
        0.022,
        (
            "Intervals are 500-replicate spatial-group bootstrap estimates. Background cells are pseudo-absences, not confirmed barren.\n"
            "No interval has a strictly positive lower bound; EMAG2 remains excluded from production scores and rankings."
        ),
        ha="center",
        va="bottom",
        fontsize=7.8,
        color="#475569",
        linespacing=1.35,
    )
    fig.subplots_adjust(left=0.25, right=0.97, top=0.88, bottom=0.13, wspace=0.12)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSET, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print({"asset": str(ASSET), "evaluated_materials": len(data), "shadow_gate_passes": passed})


if __name__ == "__main__":
    main()
