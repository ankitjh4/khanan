#!/usr/bin/env python3
"""Render the README overview map from KHANAN's published release tables."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from shapely import wkt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
ASSET = ROOT / "assets" / "maps" / "khanan-india-prospectivity-overview-v0.6.png"


def load_wkt_frame(path: Path, column: str, usecols: list[str]) -> gpd.GeoDataFrame:
    frame = pd.read_csv(path, usecols=usecols).dropna(subset=[column]).copy()
    geometry = frame[column].map(wkt.loads)
    return gpd.GeoDataFrame(frame.drop(columns=[column]), geometry=geometry, crs="EPSG:4326")


def main() -> None:
    boundary = gpd.read_file(ROOT / "sources" / "raw" / "india-soi.geojson").to_crs("EPSG:4326")
    candidates = load_wkt_frame(
        OUT / "india_mining_candidate_areas_validation_gated.csv",
        "cell_boundary_wkt",
        ["record_class", "cell_boundary_wkt", "prospectivity_score_max"],
    )
    known = pd.read_csv(
        OUT / "india_known_mining_sites.csv",
        usecols=["record_class", "latitude", "longitude"],
    ).dropna(subset=["latitude", "longitude"])
    known = known[
        known["latitude"].between(6, 38)
        & known["longitude"].between(68, 98)
    ]
    known_points = gpd.GeoDataFrame(
        known,
        geometry=gpd.points_from_xy(known["longitude"], known["latitude"]),
        crs="EPSG:4326",
    )
    official = load_wkt_frame(
        OUT / "india_official_critical_mineral_blocks.csv",
        "block_boundary_wkt",
        ["auction_event_kind", "block_boundary_wkt"],
    )
    official = official[official["auction_event_kind"].eq("auction_offer")]
    high = candidates[candidates["record_class"].eq("high_priority_candidate")]

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titleweight": "bold"})
    fig, ax = plt.subplots(figsize=(10.5, 12.5), dpi=180, facecolor="#f8fafc")
    ax.set_facecolor("#eaf2f3")
    boundary.plot(ax=ax, color="#f8fafc", edgecolor="#475569", linewidth=0.65, zorder=1)

    score_min = float(candidates["prospectivity_score_max"].min())
    score_max = float(candidates["prospectivity_score_max"].max())
    norm = Normalize(vmin=score_min, vmax=score_max)
    candidates.plot(
        ax=ax,
        column="prospectivity_score_max",
        cmap="viridis",
        norm=norm,
        linewidth=0,
        alpha=0.78,
        zorder=2,
    )
    high.boundary.plot(ax=ax, color="#ef4444", linewidth=0.85, alpha=0.95, zorder=3)
    official.boundary.plot(ax=ax, color="#06b6d4", linewidth=0.55, alpha=0.9, zorder=4)
    known_points.plot(ax=ax, color="#111827", markersize=2.6, alpha=0.42, zorder=5)

    colorbar = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap="viridis"),
        ax=ax,
        fraction=0.032,
        pad=0.025,
        shrink=0.72,
    )
    colorbar.set_label("Maximum material prospectivity index", fontsize=9)
    colorbar.ax.tick_params(labelsize=8)

    legend = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#111827", alpha=0.6, markersize=5, label="Mapped source site"),
        Line2D([0], [0], color="#ef4444", linewidth=2, label="High-priority candidate cell"),
        Line2D([0], [0], color="#06b6d4", linewidth=2, label="Official auction-offer footprint"),
    ]
    ax.legend(handles=legend, loc="lower left", frameon=True, framealpha=0.94, fontsize=8.5)

    ax.set_title("KHANAN — India Mineral Prospectivity Research Map", fontsize=18, color="#0f172a", pad=20)
    ax.text(
        0.5,
        1.008,
        "Research baseline v0.6 • validation-gated screening cells and observed public-source evidence",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color="#475569",
    )
    ax.text(
        0.015,
        0.985,
        (
            f"{len(candidates):,} candidate cells\n"
            f"{len(high):,} high-priority cells\n"
            f"{len(known_points):,} mapped source sites\n"
            f"{len(official):,} auction-offer observations"
        ),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        color="#0f172a",
        bbox={"boxstyle": "round,pad=0.55", "facecolor": "white", "edgecolor": "#cbd5e1", "alpha": 0.94},
    )
    ax.set_xlabel("Longitude (WGS84)", fontsize=9)
    ax.set_ylabel("Latitude (WGS84)", fontsize=9)
    ax.tick_params(axis="both", labelsize=8, colors="#475569")
    ax.grid(color="#cbd5e1", linewidth=0.35, alpha=0.45)
    ax.set_xlim(67.2, 98.8)
    ax.set_ylim(5.0, 38.8)
    ax.set_aspect("equal", adjustable="box")

    fig.text(
        0.5,
        0.018,
        (
            "Reconnaissance indices—not discoveries, reserves, grades, legal concessions, or drill targets. "
            "Auction footprints are shown for context and excluded from model training/scoring.\n"
            "Sources: USGS MRDS, IBM, Ministry of Mines/MSTC, Census 2011, WorldPop, NASA POWER, WorldClim, "
            "DataMeet and Esri India Living Atlas. Boundary display follows source data and implies no position on legal status."
        ),
        ha="center",
        va="bottom",
        fontsize=7.2,
        color="#475569",
        linespacing=1.35,
    )
    fig.subplots_adjust(left=0.08, right=0.92, top=0.91, bottom=0.075)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSET, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print({"asset": str(ASSET), "candidate_cells": len(candidates), "high_priority_cells": len(high)})


if __name__ == "__main__":
    main()
