#!/usr/bin/env python3
"""Plot the diagnostic official-block transfer validation."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
ASSET = ROOT / "assets" / "figures" / "khanan-official-block-transfer-v0.1.png"


def main() -> None:
    data = pd.read_csv(OUT / "material_official_block_transfer_validation.csv")
    observations = pd.read_csv(
        OUT / "official_block_transfer_observations.csv",
        usecols=["source_family", "source_record_id"],
    )
    unique_footprints = len(observations.drop_duplicates())
    data = data[data["transfer_evaluation_status"].eq("evaluated_diagnostic_only")].copy()
    data = data.sort_values("transfer_roc_auc", ascending=True).reset_index(drop=True)
    labels = [
        f"{name} (n={int(count)})"
        for name, count in zip(data["material_name"], data["primary_transfer_positive_blocks"])
    ]
    y = np.arange(len(data))
    colors = np.where(data["transfer_roc_auc"] >= 0.5, "#0b76a8", "#c12a26")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig = plt.figure(figsize=(14.5, 9.5), facecolor="#f5f7fa")
    grid = fig.add_gridspec(
        1,
        2,
        width_ratios=[1.75, 1.15],
        left=0.17,
        right=0.98,
        top=0.83,
        bottom=0.18,
        wspace=0.18,
    )
    ax_auc = fig.add_subplot(grid[0, 0], facecolor="white")
    ax_rate = fig.add_subplot(grid[0, 1], facecolor="white", sharey=ax_auc)

    x = data["transfer_roc_auc"].to_numpy(float)
    low = data["transfer_roc_auc_ci95_low"].to_numpy(float)
    high = data["transfer_roc_auc_ci95_high"].to_numpy(float)
    ax_auc.errorbar(
        x,
        y,
        xerr=np.vstack([x - low, high - x]),
        fmt="none",
        ecolor="#94a3b8",
        elinewidth=2,
        capsize=0,
        zorder=1,
    )
    ax_auc.scatter(x, y, s=55, c=colors, edgecolor="white", linewidth=0.8, zorder=2)
    ax_auc.axvline(0.5, color="#475569", linestyle="--", linewidth=1.2)
    ax_auc.set_xlim(0.0, 1.0)
    ax_auc.set_yticks(y)
    ax_auc.set_yticklabels(labels)
    ax_auc.set_xlabel("Official-block versus background ROC-AUC")
    ax_auc.set_title("Transfer discrimination with spatial-group 95% intervals", loc="left", fontweight="bold")

    top5 = data["target_material_top5_rate"].to_numpy(float)
    recall = data["transfer_recall_at_background_top5pct"].to_numpy(float)
    ax_rate.scatter(top5, y + 0.12, s=48, color="#0b76a8", label="Target appears in published top five")
    ax_rate.scatter(recall, y - 0.12, s=48, color="#f59e0b", label="Recall at background top 5%")
    ax_rate.axvline(0.2, color="#475569", linestyle="--", linewidth=1.2)
    ax_rate.set_xlim(-0.02, 1.02)
    ax_rate.set_xlabel("Share of official block centroids")
    ax_rate.set_title("Material retrieval and high-score recall", loc="left", fontweight="bold")
    ax_rate.tick_params(axis="y", labelleft=False)
    ax_rate.legend(loc="lower right", frameon=False, fontsize=8.5)

    for axis in [ax_auc, ax_rate]:
        axis.grid(axis="x", color="#dbe3ec", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.spines["bottom"].set_color("#94a3b8")

    fig.suptitle("KHANAN — Official Block Transfer Validation", x=0.5, y=0.965, fontsize=22, color="#0f172a")
    fig.text(
        0.5,
        0.905,
        (
            f"{len(data)} materials evaluated • {unique_footprints} target-mapped footprints • >25 km from MRDS evidence • "
            "500 spatial-group bootstrap replicates • 0 passed the statistical gate"
        ),
        ha="center",
        fontsize=12,
        color="#475569",
    )
    fig.text(
        0.17,
        0.08,
        (
            "Auction and exploration blocks are external targeting observations, not confirmed deposits.\n"
            "Manganese separates strongly but has only seven eligible blocks; Iron and Phosphorus intervals cross 0.5.\n"
            "Complete historical knowledge-independence is unresolved. No score, candidate class, or rank changes."
        ),
        ha="left",
        va="bottom",
        fontsize=9.5,
        color="#52647b",
    )
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSET, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print({"asset": str(ASSET), "evaluated_materials": len(data), "statistical_gate_passes": int(data["passes_predeclared_statistical_gate"].sum())})


if __name__ == "__main__":
    main()
