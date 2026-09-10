#!/usr/bin/env python3
"""Render KHANAN's non-scoring Sentinel-2 surface-context summary."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
FEATURE_PATH = OUT / "india_sentinel2_surface_context_h3_r6.csv"
ASSET = ROOT / "assets" / "maps" / "khanan-sentinel2-surface-context-alpha18.png"


def add_boundary(axis: plt.Axes) -> None:
    boundary_path = ROOT / "sources" / "raw" / "india-soi.geojson"
    if boundary_path.exists():
        boundary = gpd.read_file(boundary_path).to_crs("EPSG:4326")
        boundary.boundary.plot(ax=axis, color="#334155", linewidth=0.52, zorder=5)


def style_axis(axis: plt.Axes) -> None:
    axis.set_xlim(67.2, 98.8)
    axis.set_ylim(5.0, 38.8)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Longitude (WGS84)", fontsize=7.5)
    axis.set_ylabel("Latitude (WGS84)", fontsize=7.5)
    axis.tick_params(axis="both", labelsize=6.5, colors="#475569")
    axis.grid(color="#cbd5e1", linewidth=0.28, alpha=0.32)
    axis.set_facecolor("#e2e8f0")
    add_boundary(axis)


def map_panel(
    figure: plt.Figure,
    axis: plt.Axes,
    data: pd.DataFrame,
    column: str,
    title: str,
    colorbar_label: str,
    cmap: str,
    vmin: float,
    vmax: float,
) -> int:
    valid = data.dropna(subset=[column])
    points = axis.scatter(
        valid["longitude"],
        valid["latitude"],
        c=valid[column].clip(vmin, vmax),
        cmap=cmap,
        norm=Normalize(vmin=vmin, vmax=vmax),
        marker="h",
        s=3.55,
        linewidths=0,
        rasterized=True,
        zorder=2,
    )
    axis.set_title(title, fontsize=11.5, color="#0f172a", pad=10, fontweight="bold")
    bar = figure.colorbar(points, ax=axis, fraction=0.038, pad=0.025, shrink=0.80)
    bar.set_label(colorbar_label, fontsize=7.2)
    bar.ax.tick_params(labelsize=6.5)
    style_axis(axis)
    return len(valid)


def main() -> None:
    columns = [
        "latitude",
        "longitude",
        "annual_clear_land_sample_fraction",
        "annual_bare_sample_fraction",
        "annual_bare_swir1_swir2_ratio_median",
        "bare_surface_quality_status",
    ]
    data = pd.read_csv(FEATURE_PATH, usecols=columns, low_memory=False)
    supported = data[data["bare_surface_quality_status"] != "insufficient_bare_support"].copy()
    ratio = supported["annual_bare_swir1_swir2_ratio_median"].dropna()
    ratio_low, ratio_high = np.nanpercentile(ratio, [2, 98]) if len(ratio) else (0.5, 1.5)

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    figure, axes = plt.subplots(1, 3, figsize=(18.2, 8.5), dpi=180, facecolor="#f8fafc")
    clear_count = map_panel(
        figure,
        axes[0],
        data,
        "annual_clear_land_sample_fraction",
        "Two-season clear-land support",
        "Fraction of 98 samples (SCL 4/5)",
        "viridis",
        0.0,
        1.0,
    )
    bare_count = map_panel(
        figure,
        axes[1],
        data,
        "annual_bare_sample_fraction",
        "Two-season not-vegetated support",
        "Fraction of 98 samples (SCL 5)",
        "YlOrBr",
        0.0,
        1.0,
    )
    ratio_count = map_panel(
        figure,
        axes[2],
        supported,
        "annual_bare_swir1_swir2_ratio_median",
        "Bare-surface SWIR1/SWIR2 ratio",
        "Median B11/B12 (2nd–98th percentile clipped)",
        "PuOr_r",
        float(ratio_low),
        float(ratio_high),
    )

    two_season_rate = data["bare_surface_quality_status"].eq("two_season_bare_support").mean()
    figure.suptitle("KHANAN — India Sentinel-2 Surface Context", fontsize=18, color="#0f172a", y=0.975)
    figure.text(
        0.5,
        0.936,
        (
            f"v1.0-alpha.18 • {len(data):,} H3 r6 cells • two 2025 seasonal windows • "
            f"two-season bare support {two_season_rate:.1%}"
        ),
        ha="center",
        fontsize=9.2,
        color="#475569",
    )
    figure.text(
        0.5,
        0.018,
        (
            "Each cell uses all 49 H3 r8 child centroids per season; categorical SCL is sampled at native 20 m and six BOA bands from ~160 m COG overviews. "
            f"Displayed rows: clear {clear_count:,}, bare {bare_count:,}, supported SWIR ratio {ratio_count:,}.\n"
            "The B11/B12 ratio is broad, non-specific surface context—not a mineral identification, subsurface observation, discovery, grade, resource, reserve or drill target. "
            "Sentinel-2 does not affect v0.6 rankings. Source: Copernicus Sentinel-2 L2A via Microsoft Planetary Computer."
        ),
        ha="center",
        va="bottom",
        fontsize=6.8,
        color="#475569",
        linespacing=1.35,
    )
    figure.subplots_adjust(left=0.035, right=0.975, top=0.90, bottom=0.13, wspace=0.20)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(ASSET, dpi=180, facecolor=figure.get_facecolor(), bbox_inches="tight")
    plt.close(figure)
    print(
        {
            "asset": str(ASSET),
            "cells": len(data),
            "two_season_bare_support_rate": two_season_rate,
            "swir_ratio_display_rows": ratio_count,
        }
    )


if __name__ == "__main__":
    main()
