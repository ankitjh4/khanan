#!/usr/bin/env python3
"""Render KHANAN's SoilGrids 2.0 surface-soil context map."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize, TwoSlopeNorm


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
ASSET = ROOT / "assets" / "maps" / "khanan-soilgrids-context-v0.8.png"


def add_boundary(ax: plt.Axes) -> None:
    boundary_path = ROOT / "sources" / "raw" / "india-soi.geojson"
    if boundary_path.exists():
        boundary = gpd.read_file(boundary_path).to_crs("EPSG:4326")
        boundary.boundary.plot(ax=ax, color="#334155", linewidth=0.5, zorder=5)


def style_axis(ax: plt.Axes) -> None:
    ax.set_xlim(67.2, 98.8)
    ax.set_ylim(5.0, 38.8)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude (WGS84)", fontsize=7.5)
    ax.set_ylabel("Latitude (WGS84)", fontsize=7.5)
    ax.tick_params(axis="both", labelsize=6.5, colors="#475569")
    ax.grid(color="#cbd5e1", linewidth=0.28, alpha=0.32)
    ax.set_facecolor("#e2e8f0")
    add_boundary(ax)


def plot_property(
    fig: plt.Figure,
    ax: plt.Axes,
    data: pd.DataFrame,
    column: str,
    title: str,
    colorbar_label: str,
    cmap: str,
    center: float | None = None,
) -> tuple[int, tuple[float, float]]:
    valid = data.dropna(subset=[column])
    low, high = np.nanpercentile(valid[column], [2, 98])
    if center is not None and low < center < high:
        norm = TwoSlopeNorm(vmin=float(low), vcenter=center, vmax=float(high))
    else:
        norm = Normalize(vmin=float(low), vmax=float(high))
    scatter = ax.scatter(
        valid["longitude"],
        valid["latitude"],
        c=valid[column].clip(low, high),
        cmap=cmap,
        norm=norm,
        marker="h",
        s=3.5,
        linewidths=0,
        rasterized=True,
        zorder=2,
    )
    ax.set_title(title, fontsize=11.5, color="#0f172a", pad=10, fontweight="bold")
    bar = fig.colorbar(scatter, ax=ax, fraction=0.038, pad=0.025, shrink=0.80)
    bar.set_label(colorbar_label, fontsize=7.2)
    bar.ax.tick_params(labelsize=6.5)
    style_axis(ax)
    return len(valid), (float(low), float(high))


def main() -> None:
    columns = [
        "latitude",
        "longitude",
        "soilgrids_phh2o_0_5cm_mean",
        "soilgrids_clay_0_5cm_mean",
        "soilgrids_soc_0_5cm_mean",
    ]
    features = pd.read_csv(
        OUT / "india_soilgrids_v2_soil_features_h3_r6.csv",
        usecols=columns,
        low_memory=False,
    )

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig, axes = plt.subplots(1, 3, figsize=(18.2, 8.5), dpi=180, facecolor="#f8fafc")
    p_h_count, _ = plot_property(
        fig,
        axes[0],
        features,
        "soilgrids_phh2o_0_5cm_mean",
        "Surface pH in water",
        "Mean pH (2nd–98th percentile clipped)",
        "BrBG",
        center=7.0,
    )
    clay_count, _ = plot_property(
        fig,
        axes[1],
        features,
        "soilgrids_clay_0_5cm_mean",
        "Surface clay content",
        "Mean clay content (% mass; clipped)",
        "YlOrBr",
    )
    soc_count, _ = plot_property(
        fig,
        axes[2],
        features,
        "soilgrids_soc_0_5cm_mean",
        "Surface soil organic carbon",
        "Mean soil organic carbon (g/kg; clipped)",
        "YlGn",
    )

    minimum_coverage = min(p_h_count, clay_count, soc_count) / len(features)
    fig.suptitle("KHANAN — India SoilGrids 2.0 Context", fontsize=18, color="#0f172a", y=0.975)
    fig.text(
        0.5,
        0.936,
        (
            f"Geospatial feature baseline v0.8 • {len(features):,} H3 r6 cells • "
            f"minimum displayed-property coverage {minimum_coverage:.1%}"
        ),
        ha="center",
        fontsize=9.2,
        color="#475569",
    )
    fig.text(
        0.5,
        0.018,
        (
            "Context only: global machine-learning soil predictions are not field assays or mineral-deposit evidence and do not affect production rankings. "
            "The release also includes 30–60 cm predictions and p05/p95 uncertainty bounds for nine properties.\n"
            "Source: ISRIC SoilGrids 2.0, CC BY 4.0; Poggio et al. (2021), DOI 10.5194/soil-7-217-2021. "
            "Native 250 m maps were requested as a 0.025° WCS derivative before H3-centroid sampling."
        ),
        ha="center",
        va="bottom",
        fontsize=7.0,
        color="#475569",
        linespacing=1.35,
    )
    fig.subplots_adjust(left=0.035, right=0.975, top=0.90, bottom=0.13, wspace=0.20)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSET, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print({"asset": str(ASSET), "cells": len(features), "minimum_displayed_coverage": minimum_coverage})


if __name__ == "__main__":
    main()
