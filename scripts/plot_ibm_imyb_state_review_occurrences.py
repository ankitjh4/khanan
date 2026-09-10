#!/usr/bin/env python3
"""Plot district-level IBM IMYB 2024 occurrence context for alpha.23."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap


ROOT = Path(__file__).resolve().parents[1]
DISTRICTS = ROOT / "sources" / "raw" / "2011_Dist.shp"
OCCURRENCES = ROOT / "outputs" / "india_ibm_district_mineral_occurrences_2024.csv"
VALIDATION = ROOT / "outputs" / "ibm_imyb_state_review_occurrences_validation.json"
OUTPUT = ROOT / "assets" / "maps" / "khanan-ibm-state-review-occurrence-context-alpha23.png"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = read_rows(OCCURRENCES)
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    material_terms: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        if row["district_crosswalk_admitted_to_h3_context"] == "True":
            key = (row["district_boundary_state_2011"], row["district_boundary_name_2011"])
            material_terms[key].add(row["source_material_term"])

    districts = gpd.read_file(DISTRICTS).to_crs("EPSG:4326")
    districts["material_count"] = [
        len(material_terms.get((str(row.ST_NM), str(row.DISTRICT)), set()))
        for row in districts.itertuples()
    ]
    states = districts[["ST_NM", "geometry"]].dissolve(by="ST_NM")
    top = districts.nlargest(15, "material_count").sort_values("material_count")

    cmap = LinearSegmentedColormap.from_list(
        "khanan_occurrence", ["#fff7ed", "#fdba74", "#f97316", "#9a3412", "#431407"]
    )
    boundaries = [0, 1, 6, 11, 21, 31, 46, max(60, int(districts["material_count"].max()) + 1)]
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)

    fig = plt.figure(figsize=(16, 10), facecolor="#f8f7f2")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.5, 1], wspace=0.16)
    ax = fig.add_subplot(grid[0, 0])
    bar_ax = fig.add_subplot(grid[0, 1])

    districts.plot(
        ax=ax,
        column="material_count",
        cmap=cmap,
        norm=norm,
        edgecolor="#d6d3d1",
        linewidth=0.18,
        missing_kwds={"color": "#e7e5e4"},
    )
    states.boundary.plot(ax=ax, color="#44403c", linewidth=0.55)
    ax.set_xlim(67.5, 98.5)
    ax.set_ylim(6, 37.8)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Published material terms by matched 2011 district", loc="left", fontsize=14, weight="bold")
    ax.grid(color="#d6d3d1", linewidth=0.3, alpha=0.45)

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.038, pad=0.045, ticks=boundaries[:-1])
    cbar.set_label("Unique IBM source material terms inherited by district")

    state_abbreviations = {
        "Andhra Pradesh": "AP", "Jharkhand": "JH", "Maharashtra": "MH",
        "Rajasthan": "RJ",
    }
    labels = [
        f"{row.DISTRICT} · {state_abbreviations.get(row.ST_NM, row.ST_NM)}"
        for row in top.itertuples()
    ]
    values = top["material_count"].tolist()
    bar_ax.barh(range(len(top)), values, color="#c2410c")
    bar_ax.set_yticks(range(len(top)), [""] * len(top))
    bar_ax.set_xlabel("Unique source material terms")
    bar_ax.set_title("Highest-count matched districts", loc="left", fontsize=14, weight="bold")
    bar_ax.grid(axis="x", color="#d6d3d1", linewidth=0.5, alpha=0.6)
    for index, value in enumerate(values):
        bar_ax.text(0.45, index, labels[index], va="center", ha="left", fontsize=8.1, color="white", weight="bold")
        bar_ax.text(value + 0.5, index, str(value), va="center", fontsize=8.5, color="#292524")
    bar_ax.set_xlim(0, max(values) * 1.16)

    fig.suptitle(
        "KHANAN alpha.23 · IBM Indian Minerals Yearbook 2024 occurrence geography",
        x=0.055,
        ha="left",
        fontsize=19,
        weight="bold",
    )
    fig.text(
        0.055,
        0.018,
        f"{validation['state_occurrence_rows']:,} source-geography rows · "
        f"{validation['district_occurrence_rows_admitted_to_h3_context']:,} admitted district-material rows · "
        f"{validation['h3_context_rows']:,} H3 cells with inherited context · "
        f"{validation['unique_source_material_terms']} source terms / {validation['unique_normalized_material_ids']} ontology IDs.\n"
        "Context only: colors summarize broad published occurrence lists, not exact deposits, uniform district mineralization, model predictions, grades, reserves, discoveries or permission to explore.",
        fontsize=9.8,
        color="#44403c",
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
