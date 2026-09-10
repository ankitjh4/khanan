#!/usr/bin/env python3
"""Plot the reviewed IBM 2023-24 auction/MBS geometry subset."""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GEOMETRIES = ROOT / "outputs" / "india_ibm_auctioned_concession_geometries_2023_24.geojson"
MATCHES = ROOT / "outputs" / "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv"
STATUS_EVIDENCE = ROOT / "outputs" / "india_ibm_auctioned_concession_status_evidence_2023_24.csv"
DISTRICTS = ROOT / "sources" / "raw" / "2011_Dist.shp"
OUTPUT = ROOT / "assets" / "maps" / "khanan-ibm-auction-mbs-geometries-alpha13.png"

COLORS = {
    "Bauxite": "#A46636",
    "Gold": "#D6A51D",
    "Glauconite": "#6F4E9C",
    "Glauconite (Potash)": "#6F4E9C",
    "Iron Ore": "#B8473D",
    "Limestone": "#4D83B3",
}


def material_color(value: str) -> str:
    for name, color in COLORS.items():
        if name.lower() in value.lower():
            return color
    return "#5F6B73"


def style_axis(axis) -> None:
    axis.set_facecolor("#F5F2EB")
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)


def label_polygons(axis, frame: gpd.GeoDataFrame) -> None:
    for _, row in frame.iterrows():
        point = row.geometry.representative_point()
        label = row["block_name"].replace(" Mineral Block", "").replace(" Block", "")
        offset = {"Mevasa-1": (4, 10), "Mevasa": (4, -12)}.get(label, (4, 4))
        axis.annotate(
            label,
            (point.x, point.y),
            xytext=offset,
            textcoords="offset points",
            fontsize=8,
            color="#18232B",
            path_effects=[],
        )


def main() -> None:
    geometries = gpd.read_file(GEOMETRIES).to_crs("EPSG:4326")
    matches = pd.read_csv(MATCHES, keep_default_na=False)
    status_evidence = pd.read_csv(STATUS_EVIDENCE, keep_default_na=False)
    districts = gpd.read_file(DISTRICTS).to_crs("EPSG:4326")
    states = districts.dissolve(by="ST_NM").reset_index()
    admitted = int((matches.geometry_admission_status == "admitted_authoritative_source_footprint").sum())
    unreviewed = int((matches.geometry_admission_status == "withheld_not_reviewed").sum())
    withheld = len(matches) - admitted - unreviewed
    no_public_boundary = int((matches.geometry_admission_status == "withheld_no_public_boundary_document").sum())
    reviewed_mbs_withheld = withheld - no_public_boundary

    fig = plt.figure(figsize=(18, 14), facecolor="#FCFBF7")
    grid = fig.add_gridspec(3, 3, left=0.045, right=0.985, top=0.86, bottom=0.13, wspace=0.12, hspace=0.20)
    axes = [fig.add_subplot(grid[row, column]) for row in range(3) for column in range(3)]
    for axis in axes:
        style_axis(axis)

    states.plot(ax=axes[0], facecolor="#E9E5DC", edgecolor="#B9B2A6", linewidth=0.35)
    geometries.plot(
        ax=axes[0],
        color=[material_color(value) for value in geometries.mineral_source_ibm],
        edgecolor="#FFFFFF",
        linewidth=0.5,
    )
    locator_points = geometries.copy()
    locator_points.geometry = locator_points.geometry.representative_point()
    locator_points.plot(
        ax=axes[0],
        color=[material_color(value) for value in locator_points.mineral_source_ibm],
        edgecolor="#FFFFFF",
        linewidth=0.45,
        markersize=24,
    )
    axes[0].set_title("India locator", loc="left", fontsize=13, weight="bold", color="#18232B", pad=10)

    for axis, state in zip(axes[1:7], ["Chhattisgarh", "Goa", "Gujarat", "Andhra Pradesh", "Uttar Pradesh", "Karnataka"]):
        state_shape = states[states.ST_NM == state]
        subset = geometries[geometries.state_or_ut == state]
        state_shape.plot(ax=axis, facecolor="#E9E5DC", edgecolor="#756E64", linewidth=0.8)
        for _, row in subset.iterrows():
            gpd.GeoSeries([row.geometry], crs="EPSG:4326").plot(
                ax=axis,
                facecolor=material_color(row["mineral_source_ibm"]),
                edgecolor="#FFFFFF",
                linewidth=1.1,
                alpha=0.92,
            )
        label_polygons(axis, subset)
        if not subset.empty:
            minx, miny, maxx, maxy = subset.total_bounds
            xpad = max((maxx - minx) * 0.32, 0.04)
            ypad = max((maxy - miny) * 0.32, 0.04)
            axis.set_xlim(minx - xpad, maxx + xpad)
            axis.set_ylim(miny - ypad, maxy + ypad)
        if state == "Andhra Pradesh":
            axis.text(
                0.5,
                0.5,
                f"{len(status_evidence)} status-linked IBM rows\nNo public boundary document found",
                ha="center",
                va="center",
                fontsize=11,
                linespacing=1.45,
                color="#65717A",
                transform=axis.transAxes,
                bbox={"facecolor": "#FCFBF7", "edgecolor": "none", "alpha": 0.82, "pad": 5},
            )
            axis.set_title("Andhra Pradesh: status evidence only", loc="left", fontsize=13, weight="bold", color="#18232B", pad=10)
        else:
            axis.set_title(f"{state}: {len(subset)} admitted footprints", loc="left", fontsize=13, weight="bold", color="#18232B", pad=10)

    axes[7].axis("off")
    axes[7].text(0.02, 0.94, "Review scope", fontsize=14, weight="bold", color="#18232B", va="top", transform=axes[7].transAxes)
    axes[7].text(
        0.02,
        0.80,
        f"34 IBM rows reviewed\n29 official MBS PDFs selected\n{admitted} footprints admitted\n{reviewed_mbs_withheld} MBS records withheld\n{no_public_boundary} Andhra rows status-linked only\n{unreviewed} IBM rows not yet reviewed",
        fontsize=13,
        linespacing=1.45,
        color="#48545C",
        va="top",
        transform=axes[7].transAxes,
    )
    axes[7].text(
        0.02,
        0.22,
        "Withholding is deliberate: malformed coordinates,\nmissing hemispheres, incomplete boundary detail,\nor area-reconciliation failures are not repaired\nby inference.",
        fontsize=10.5,
        linespacing=1.5,
        color="#65717A",
        va="top",
        transform=axes[7].transAxes,
    )

    axes[8].axis("off")
    axes[8].text(0.02, 0.94, "Evidence and geometry gates", fontsize=14, weight="bold", color="#18232B", va="top", transform=axes[8].transAxes)
    axes[8].text(
        0.02,
        0.80,
        "Exact block identity and dated source\nNo current-status claim without controlling record\nValid source-order polygon\nCentroid and footprint covered by source State\nComputed vs MBS area within 5%\nIBM vs MBS area within 5%",
        fontsize=12,
        linespacing=1.5,
        color="#48545C",
        va="top",
        transform=axes[8].transAxes,
    )
    axes[8].text(
        0.02,
        0.25,
        "Andhra Pradesh adds five dated status-evidence\nrows, but no polygons. Candidate scores and the\nseventeen admitted footprints remain unchanged.",
        fontsize=10.5,
        linespacing=1.5,
        color="#65717A",
        va="top",
        transform=axes[8].transAxes,
    )

    fig.text(0.045, 0.945, "KHANAN | Reviewed state-auction Mine Block Summary geometry", fontsize=22, weight="bold", color="#18232B")
    fig.text(
        0.045,
        0.905,
        f"IBM Table 5 contains 97 blocks. Alpha.13 reviews 34 rows, admits {admitted} source footprints, and leaves {unreviewed} unreviewed.",
        fontsize=12,
        color="#48545C",
    )
    legend_items = []
    seen = set()
    for _, row in geometries.iterrows():
        label = row["mineral_source_ibm"]
        if label in seen:
            continue
        seen.add(label)
        legend_items.append(plt.Line2D([0], [0], marker="s", color="none", markerfacecolor=material_color(label), markeredgecolor="none", markersize=10, label=label))
    fig.legend(handles=legend_items, loc="lower left", bbox_to_anchor=(0.045, 0.047), ncol=6, frameon=False, fontsize=9)
    fig.text(
        0.985,
        0.018,
        "Context only: MBS footprints and official-secondary status evidence do not independently prove present operation.\nSources: MSTC State portal, Prakasam District Administration, Ministry of Mines; State diagnostic boundary: Census 2011 district layer.",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="#65717A",
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=260, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
