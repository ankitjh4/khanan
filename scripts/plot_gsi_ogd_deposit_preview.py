#!/usr/bin/env python3
"""Plot the preview-limited GSI OGD mineral-deposit context layer."""

from __future__ import annotations

import csv
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
DEPOSITS = ROOT / "outputs" / "india_gsi_ogd_mineral_deposit_preview.csv"
AUDIT = ROOT / "outputs" / "gsi_ogd_mineral_deposit_catalog_audit.csv"
BOUNDARIES = ROOT / "sources" / "raw" / "2011_Dist.shp"
OUTPUT = ROOT / "assets" / "maps" / "khanan-gsi-ogd-deposit-preview-alpha21.png"

COLORS = {
    "Bauxite": "#b5651d",
    "Baryte": "#6a4c93",
    "Copper": "#d97706",
    "Diamond": "#38bdf8",
    "Gold": "#eab308",
    "Iron": "#991b1b",
    "Lead-Zinc": "#64748b",
    "Manganese": "#7c3aed",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = read_rows(DEPOSITS)
    audits = read_rows(AUDIT)
    districts = gpd.read_file(BOUNDARIES).to_crs("EPSG:4326")
    states = districts[["ST_NM", "geometry"]].dissolve(by="ST_NM")

    fig = plt.figure(figsize=(16, 10), facecolor="#f7f5ef")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.55, 1], wspace=0.08)
    ax = fig.add_subplot(grid[0, 0])
    bar_ax = fig.add_subplot(grid[0, 1])

    states.plot(ax=ax, facecolor="#ebe7dc", edgecolor="#756f64", linewidth=0.5)
    for commodity in COLORS:
        subset = [row for row in rows if row["commodity_source"] == commodity]
        ax.scatter(
            [float(row["representative_longitude"]) for row in subset],
            [float(row["representative_latitude"]) for row in subset],
            s=44,
            color=COLORS[commodity],
            edgecolor="white",
            linewidth=0.55,
            alpha=0.9,
            zorder=3,
        )
    ax.set_xlim(67.5, 98.5)
    ax.set_ylim(6, 37.8)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Authoritative GSI locations exposed by the public preview", loc="left", fontsize=14, weight="bold")
    ax.grid(color="#cfc9bc", linewidth=0.35, alpha=0.55)
    legend = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=color,
               markeredgecolor="white", markersize=8, label=commodity)
        for commodity, color in COLORS.items()
    ]
    ax.legend(handles=legend, loc="lower left", ncol=2, frameon=True, fontsize=9)

    audits.sort(key=lambda row: int(row["source_reported_total_rows"]))
    labels = [row["commodity_scope"] for row in audits]
    totals = [int(row["source_reported_total_rows"]) for row in audits]
    previews = [int(row["preview_rows_returned"]) for row in audits]
    y = range(len(audits))
    bar_ax.barh(y, totals, color="#d8d2c5", label="Rows reported by portal")
    bar_ax.barh(y, previews, color="#1d4ed8", label="Rows exposed in preview")
    bar_ax.set_yticks(list(y), labels)
    bar_ax.set_xlabel("Rows")
    bar_ax.set_title("Completeness is catalog-specific", loc="left", fontsize=14, weight="bold")
    bar_ax.grid(axis="x", color="#cfc9bc", linewidth=0.5, alpha=0.6)
    bar_ax.legend(loc="lower right", frameon=False)
    for index, (preview, total) in enumerate(zip(previews, totals)):
        bar_ax.text(total + 1.5, index, f"{preview}/{total}", va="center", fontsize=9, color="#312e2a")
    bar_ax.set_xlim(0, max(totals) * 1.22)

    fig.suptitle("KHANAN alpha.21 · GSI OGD mineral-deposit preview audit", x=0.055, ha="left", fontsize=20, weight="bold")
    fig.text(
        0.055,
        0.025,
        "78 first rows exposed out of 381 reported across eight 2013 GSI catalogs. Points use source DMS locations or range midpoints.\n"
        "Context only: the preview is incomplete and non-random, the coordinate datum is unstated, and these are not new discoveries, reserves, or model labels.",
        fontsize=10,
        color="#4b4740",
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
