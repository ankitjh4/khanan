#!/usr/bin/env python3
"""Plot KHANAN's independently published EarthChem lithium geochemistry context."""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LogNorm


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "outputs" / "india_earthchem_geochemical_samples.csv"
DISTRICTS = ROOT / "sources" / "raw" / "2011_Dist.shp"
OUTPUT = ROOT / "assets" / "maps" / "khanan-earthchem-lithium-geochemistry-alpha17.png"

INK = "#18232B"
TEXT = "#48545C"
MUTED = "#65717A"
LAND = "#E9E5DC"
PAPER = "#FCFBF7"
ACCENT = "#5D2F86"


def clean_axis(axis) -> None:
    axis.set_facecolor("#F5F2EB")
    for spine in axis.spines.values():
        spine.set_visible(False)


def main() -> None:
    samples = pd.read_csv(SAMPLES, keep_default_na=False)
    samples["li_ppm_bulk"] = pd.to_numeric(samples["li_ppm_bulk"], errors="coerce")
    points = gpd.GeoDataFrame(
        samples,
        geometry=gpd.points_from_xy(samples.longitude, samples.latitude),
        crs="EPSG:4326",
    )
    districts = gpd.read_file(DISTRICTS).to_crs("EPSG:4326")
    states = districts.dissolve(by="ST_NM").reset_index()
    assam_districts = districts[districts.ST_NM == "Assam"].copy()
    sites = (
        samples.groupby(["source_site_id", "source_location_keyword", "latitude", "longitude", "district_2011"], as_index=False)
        .agg(samples=("sample_name", "count"), li_median=("li_ppm_bulk", "median"), li_min=("li_ppm_bulk", "min"), li_max=("li_ppm_bulk", "max"))
    )
    site_points = gpd.GeoDataFrame(
        sites,
        geometry=gpd.points_from_xy(sites.longitude, sites.latitude),
        crs="EPSG:4326",
    )

    fig = plt.figure(figsize=(19, 11), facecolor=PAPER)
    grid = fig.add_gridspec(2, 3, width_ratios=[0.90, 1.25, 1.35], height_ratios=[1.0, 0.48], left=0.045, right=0.975, top=0.84, bottom=0.11, wspace=0.18, hspace=0.24)
    india_ax = fig.add_subplot(grid[0, 0])
    assam_ax = fig.add_subplot(grid[0, 1])
    chemistry_ax = fig.add_subplot(grid[0, 2])
    method_ax = fig.add_subplot(grid[1, 0:2])
    limits_ax = fig.add_subplot(grid[1, 2])
    for axis in [india_ax, assam_ax, chemistry_ax, method_ax, limits_ax]:
        clean_axis(axis)

    states.plot(ax=india_ax, facecolor=LAND, edgecolor="#B9B2A6", linewidth=0.35)
    site_points.plot(ax=india_ax, color=ACCENT, edgecolor="white", linewidth=0.8, markersize=70, zorder=4)
    india_ax.set_xlim(67, 99)
    india_ax.set_ylim(6, 38)
    india_ax.set_xticks([])
    india_ax.set_yticks([])
    india_ax.set_title("India locator · 2 coordinate sites", loc="left", fontsize=13, weight="bold", color=INK, pad=10)
    india_ax.annotate("Assam", (91.0, 26.1), xytext=(-55, -10), textcoords="offset points", color=TEXT, fontsize=10, arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.8})

    assam_districts.plot(ax=assam_ax, facecolor=LAND, edgecolor="#9A9388", linewidth=0.65)
    sizes = 90 + 75 * site_points["samples"]
    site_points.plot(
        ax=assam_ax,
        column="li_median",
        cmap="magma_r",
        norm=LogNorm(vmin=max(site_points.li_median.min(), 1), vmax=site_points.li_median.max()),
        markersize=sizes,
        edgecolor="white",
        linewidth=1.2,
        zorder=5,
    )
    for _, row in site_points.iterrows():
        short = "Chakrasila Hill" if "Chakrasila" in row.source_location_keyword else "Bongaigaon road section"
        offset = (8, 9) if "Chakrasila" in short else (8, -28)
        assam_ax.annotate(
            f"{short}\n{row.samples} samples · median Li {row.li_median:,.0f} ppm\nrange {row.li_min:,.2f}–{row.li_max:,.0f} ppm",
            (row.longitude, row.latitude),
            xytext=offset,
            textcoords="offset points",
            fontsize=9,
            color=INK,
            linespacing=1.25,
        )
    assam_ax.set_xlim(89.7, 91.1)
    assam_ax.set_ylim(25.8, 26.65)
    assam_ax.set_xticks([])
    assam_ax.set_yticks([])
    assam_ax.set_title("Published sample locations · western Assam", loc="left", fontsize=13, weight="bold", color=INK, pad=10)
    assam_ax.text(0.02, 0.03, "Circle area ∝ sample count · fill encodes median bulk Li (log scale)", transform=assam_ax.transAxes, fontsize=8.5, color=MUTED)

    ordered = samples.sort_values("li_ppm_bulk", ascending=True).reset_index(drop=True)
    colors = ["#7F3C8D" if "Chakrasila" in value else "#E16A86" for value in ordered.source_location_keyword]
    chemistry_ax.scatter(ordered.li_ppm_bulk, range(len(ordered)), s=66, c=colors, edgecolors="white", linewidths=0.8, zorder=3)
    chemistry_ax.set_xscale("log")
    chemistry_ax.set_yticks(range(len(ordered)))
    chemistry_ax.set_yticklabels(ordered.sample_name, fontsize=9, color=TEXT)
    chemistry_ax.grid(axis="x", color="#D8D2C8", linewidth=0.7)
    chemistry_ax.set_xlabel("Published bulk-rock lithium concentration (ppm, log scale)", fontsize=9.5, color=TEXT)
    chemistry_ax.tick_params(axis="x", colors=TEXT, labelsize=9)
    chemistry_ax.set_title("Li values vary by four orders of magnitude", loc="left", fontsize=13, weight="bold", color=INK, pad=10)
    chemistry_ax.text(0.98, 0.03, "Purple: Chakrasila Hill\nRose: Bongaigaon road section", ha="right", va="bottom", transform=chemistry_ax.transAxes, fontsize=8.5, color=MUTED)

    method_ax.axis("off")
    method_ax.text(0.02, 0.91, "What alpha.17 adds", fontsize=13.5, weight="bold", color=INK, va="top", transform=method_ax.transAxes)
    method_ax.text(
        0.02,
        0.70,
        "13 published samples · 2 coordinate sites · 1,323 observation rows\n"
        "663 bulk-rock values across 51 parameters · 660 mineral-spot values across 12 parameters\n"
        "WD-XRF major oxides · ICP-MS trace elements · TIMS Sr–Nd isotopes · EMP mineral chemistry",
        fontsize=11.5,
        linespacing=1.55,
        color=TEXT,
        va="top",
        transform=method_ax.transAxes,
    )
    method_ax.text(
        0.02,
        0.16,
        "All source files match publisher SHA-1 checksums. CC-BY-4.0 attribution, source cell coordinates, methods, references, blanks and quality flags travel with every record.",
        fontsize=9.5,
        color=MUTED,
        va="top",
        transform=method_ax.transAxes,
        wrap=True,
    )

    limits_ax.axis("off")
    limits_ax.text(0.03, 0.91, "Interpretation boundary", fontsize=13.5, weight="bold", color=INK, va="top", transform=limits_ax.transAxes)
    limits_ax.text(
        0.03,
        0.70,
        "These are targeted petrological samples, not a regional survey.\n\n"
        "They do not establish a mine, deposit, reserve,\n"
        "new discovery, grade continuity or economic viability.\n\n"
        "They remain excluded from KHANAN v0.6 training\n"
        "and validation pending spatially independent evaluation.",
        fontsize=10.5,
        linespacing=1.42,
        color=TEXT,
        va="top",
        transform=limits_ax.transAxes,
    )

    fig.text(0.05, 0.945, "KHANAN | Independent lithium-pegmatite geochemistry context", fontsize=23, weight="bold", color=INK)
    fig.text(0.05, 0.900, "EarthChem ECL 4498 · Dutt et al. (2026) · Assam–Meghalaya Gneissic Complex · v1.0-alpha.17", fontsize=12, color=TEXT)
    fig.text(
        0.975,
        0.025,
        "Source: Dutt et al. (2026), EarthChem Library, doi:10.60520/IEDA/114498, CC-BY-4.0.\nAdministrative and geological co-location: KHANAN/Census 2011 grid. Published samples are context—not a discovery claim.",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=MUTED,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=260, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
