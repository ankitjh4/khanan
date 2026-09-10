#!/usr/bin/env python3
"""Plot the reviewed IBM 2023-24 auction/MBS geometry subset."""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GEOMETRIES = ROOT / "outputs" / "india_ibm_auctioned_concession_geometries_2023_24.geojson"
MATCHES = ROOT / "outputs" / "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv"
DISTRICTS = ROOT / "sources" / "raw" / "2011_Dist.shp"
OUTPUT = ROOT / "assets" / "maps" / "khanan-ibm-auction-mbs-geometries-alpha12.png"

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
    districts = gpd.read_file(DISTRICTS).to_crs("EPSG:4326")
    states = districts.dissolve(by="ST_NM").reset_index()
    admitted = int((matches.geometry_admission_status == "admitted_authoritative_source_footprint").sum())
    unreviewed = int((matches.geometry_admission_status == "withheld_not_reviewed").sum())
    withheld = len(matches) - admitted - unreviewed

    fig = plt.figure(figsize=(19, 11), facecolor="#FCFBF7")
    grid = fig.add_gridspec(2, 4, left=0.04, right=0.985, top=0.84, bottom=0.12, wspace=0.11, hspace=0.20)
    axes = [fig.add_subplot(grid[row, column]) for row in range(2) for column in range(4)]
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

    for axis, state in zip(axes[1:6], ["Chhattisgarh", "Goa", "Gujarat", "Uttar Pradesh", "Karnataka"]):
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
        axis.set_title(f"{state}: {len(subset)} admitted footprints", loc="left", fontsize=13, weight="bold", color="#18232B", pad=10)

    axes[6].axis("off")
    axes[6].text(0.02, 0.94, "Review scope", fontsize=14, weight="bold", color="#18232B", va="top", transform=axes[6].transAxes)
    axes[6].text(
        0.02,
        0.80,
        f"29 official MBS PDFs reviewed\n{admitted} footprints admitted\n{withheld} reviewed records withheld\n{unreviewed} IBM rows not yet reviewed",
        fontsize=13,
        linespacing=1.65,
        color="#48545C",
        va="top",
        transform=axes[6].transAxes,
    )
    axes[6].text(
        0.02,
        0.28,
        "Withholding is deliberate: malformed coordinates,\nmissing hemispheres, incomplete boundary detail,\nor area-reconciliation failures are not repaired\nby inference.",
        fontsize=10.5,
        linespacing=1.5,
        color="#65717A",
        va="top",
        transform=axes[6].transAxes,
    )

    axes[7].axis("off")
    axes[7].text(0.02, 0.94, "Admission gate", fontsize=14, weight="bold", color="#18232B", va="top", transform=axes[7].transAxes)
    axes[7].text(
        0.02,
        0.80,
        "Valid source-order polygon\nCentroid covered by source State\nComputed vs MBS area within 5%\nIBM vs MBS area within 5%",
        fontsize=12,
        linespacing=1.65,
        color="#48545C",
        va="top",
        transform=axes[7].transAxes,
    )
    axes[7].text(
        0.02,
        0.33,
        "Gujarat adds three admitted footprints.\nThree further exact-title summaries are retained\nas reviewed evidence but withheld for source conflicts.",
        fontsize=10.5,
        linespacing=1.5,
        color="#65717A",
        va="top",
        transform=axes[7].transAxes,
    )

    fig.text(0.045, 0.945, "KHANAN | Reviewed state-auction Mine Block Summary geometry", fontsize=22, weight="bold", color="#18232B")
    fig.text(
        0.045,
        0.905,
        f"IBM Table 5 contains 97 blocks. Alpha.12 admits {admitted} source footprints, withholds {withheld} reviewed records, and leaves {unreviewed} unreviewed.",
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
    fig.legend(handles=legend_items, loc="lower left", bbox_to_anchor=(0.045, 0.038), ncol=6, frameon=False, fontsize=9)
    fig.text(
        0.985,
        0.045,
        "Context only: MBS footprints do not independently prove present legal status or operation.\nSource: MSTC state mineral-auction portal; state diagnostic boundary: Census 2011 district layer.",
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
