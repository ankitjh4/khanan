#!/usr/bin/env python3
"""Render KHANAN's EMAG2v3 magnetic-context map from release tables."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
ASSET = ROOT / "assets" / "maps" / "khanan-emag2-magnetic-context-v0.7.png"


def add_boundary(ax: plt.Axes) -> None:
    """Draw the project boundary when the reproducible raw source is available."""
    boundary_path = ROOT / "sources" / "raw" / "india-soi.geojson"
    if boundary_path.exists():
        boundary = gpd.read_file(boundary_path).to_crs("EPSG:4326")
        boundary.boundary.plot(ax=ax, color="#334155", linewidth=0.55, zorder=5)


def style_axis(ax: plt.Axes) -> None:
    ax.set_xlim(67.2, 98.8)
    ax.set_ylim(5.0, 38.8)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude (WGS84)", fontsize=8)
    ax.set_ylabel("Latitude (WGS84)", fontsize=8)
    ax.tick_params(axis="both", labelsize=7, colors="#475569")
    ax.grid(color="#cbd5e1", linewidth=0.3, alpha=0.35)
    ax.set_facecolor("#e2e8f0")
    add_boundary(ax)


def main() -> None:
    features = pd.read_csv(
        OUT / "india_emag2v3_magnetic_features_h3_r6.csv",
        usecols=[
            "latitude",
            "longitude",
            "emag2_upcont_anomaly_nt",
            "emag2_error_estimate_nt",
            "emag2_source_ambiguous_or_no_data",
        ],
        low_memory=False,
    )
    known = pd.read_csv(
        OUT / "india_known_mining_sites.csv",
        usecols=["latitude", "longitude"],
    ).dropna(subset=["latitude", "longitude"])
    known = known[
        known["latitude"].between(6, 38)
        & known["longitude"].between(68, 98)
    ]
    candidates = pd.read_csv(
        OUT / "india_mining_candidate_areas_validation_gated.csv",
        usecols=["record_class", "latitude", "longitude"],
    )
    high = candidates[candidates["record_class"].eq("high_priority_candidate")]

    valid_anomaly = features.dropna(subset=["emag2_upcont_anomaly_nt"])
    anomaly_limit = float(
        np.nanpercentile(np.abs(valid_anomaly["emag2_upcont_anomaly_nt"]), 98)
    )
    anomaly_norm = TwoSlopeNorm(vmin=-anomaly_limit, vcenter=0, vmax=anomaly_limit)

    valid_error = features.dropna(subset=["emag2_error_estimate_nt"])
    error_low, error_high = np.nanpercentile(
        valid_error["emag2_error_estimate_nt"], [2, 98]
    )
    error_norm = Normalize(vmin=float(error_low), vmax=float(error_high))

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titleweight": "bold"})
    fig, axes = plt.subplots(1, 2, figsize=(14.8, 8.9), dpi=180, facecolor="#f8fafc")

    anomaly_plot = axes[0].scatter(
        valid_anomaly["longitude"],
        valid_anomaly["latitude"],
        c=valid_anomaly["emag2_upcont_anomaly_nt"].clip(-anomaly_limit, anomaly_limit),
        cmap="RdBu_r",
        norm=anomaly_norm,
        marker="h",
        s=4.0,
        linewidths=0,
        rasterized=True,
        zorder=2,
    )
    axes[0].scatter(
        high["longitude"],
        high["latitude"],
        facecolors="none",
        edgecolors="#facc15",
        linewidths=0.32,
        s=8,
        alpha=0.75,
        zorder=6,
    )
    axes[0].scatter(
        known["longitude"],
        known["latitude"],
        color="#0f172a",
        s=2.0,
        alpha=0.45,
        linewidths=0,
        zorder=7,
    )
    axes[0].set_title("Magnetic anomaly at 4 km altitude", fontsize=13, color="#0f172a", pad=12)
    anomaly_bar = fig.colorbar(anomaly_plot, ax=axes[0], fraction=0.038, pad=0.025, shrink=0.82)
    anomaly_bar.set_label("EMAG2v3 anomaly (nT; 2nd–98th percentile clipped)", fontsize=8)
    anomaly_bar.ax.tick_params(labelsize=7)

    error_plot = axes[1].scatter(
        valid_error["longitude"],
        valid_error["latitude"],
        c=valid_error["emag2_error_estimate_nt"].clip(error_low, error_high),
        cmap="viridis",
        norm=error_norm,
        marker="h",
        s=4.0,
        linewidths=0,
        rasterized=True,
        zorder=2,
    )
    gaps = features[features["emag2_source_ambiguous_or_no_data"].astype(str).str.lower().eq("true")]
    axes[1].scatter(
        gaps["longitude"],
        gaps["latitude"],
        color="#94a3b8",
        marker="h",
        s=4.0,
        linewidths=0,
        alpha=0.9,
        rasterized=True,
        zorder=3,
    )
    axes[1].set_title("Published error estimate and source gaps", fontsize=13, color="#0f172a", pad=12)
    error_bar = fig.colorbar(error_plot, ax=axes[1], fraction=0.038, pad=0.025, shrink=0.82)
    error_bar.set_label("EMAG2v3 error estimate (nT; 2nd–98th percentile clipped)", fontsize=8)
    error_bar.ax.tick_params(labelsize=7)

    for ax in axes:
        style_axis(ax)

    legend = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#0f172a", alpha=0.6, markersize=4, label="Mapped source site (left)"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none", markeredgecolor="#ca8a04", markersize=5, label="High-priority v0.6 cell (left)"),
        Line2D([0], [0], marker="h", color="none", markerfacecolor="#94a3b8", markersize=6, label="Ambiguous or no-data source code (right)"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.075))

    anomaly_rate = valid_anomaly.shape[0] / features.shape[0]
    error_rate = valid_error.shape[0] / features.shape[0]
    fig.suptitle("KHANAN — India EMAG2v3 Magnetic Context", fontsize=18, color="#0f172a", y=0.975)
    fig.text(
        0.5,
        0.935,
        (
            f"Geospatial feature baseline v0.7 • {len(features):,} H3 r6 cells • "
            f"{anomaly_rate:.1%} anomaly coverage • {error_rate:.1%} error coverage"
        ),
        ha="center",
        fontsize=9.5,
        color="#475569",
    )
    fig.text(
        0.5,
        0.022,
        (
            "Context only: the alpha.5 spatial ablation admitted EMAG2v3 to no production material model, so v0.6 rankings remain unchanged. "
            "Magnetic response is not direct evidence of a deposit, grade, depth, recoverability or economic viability.\n"
            "Source: NOAA/NCEI EMAG2v3 (Meyer, Saltus & Chulliat, 2017; DOI 10.7289/V5H70CVX). "
            "Boundary display follows source data and implies no position on legal status."
        ),
        ha="center",
        va="bottom",
        fontsize=7.2,
        color="#475569",
        linespacing=1.35,
    )
    fig.subplots_adjust(left=0.045, right=0.955, top=0.90, bottom=0.13, wspace=0.20)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSET, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(
        {
            "asset": str(ASSET),
            "cells": len(features),
            "valid_anomaly": len(valid_anomaly),
            "valid_error": len(valid_error),
            "high_priority_overlay": len(high),
        }
    )


if __name__ == "__main__":
    main()
