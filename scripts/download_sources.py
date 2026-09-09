#!/usr/bin/env python3
"""Download the public inputs used by the India mining dataset build.

Files are cached under sources/raw. Downloads use temporary .part files and are
replaced only after a successful response, so interrupted runs are safe to retry.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw"
CONFIG = ROOT / "config"
WEATHER_CONFIG = json.loads((CONFIG / "weather_window.json").read_text(encoding="utf-8"))
POWER_START = WEATHER_CONFIG["reference_period_start"]
POWER_END = WEATHER_CONFIG["reference_period_end"]
POWER_DIR = RAW / f"nasa_power_daily_rolling_12m_{POWER_START}_{POWER_END}"


STATIC_SOURCES = {
    "mrds-csv.zip": (
        "https://mrdata.usgs.gov/mrds/mrds-csv.zip",
        20_000_000,
    ),
    "india-soi.geojson": (
        "https://raw.githubusercontent.com/datameet/maps/master/Country/india-soi.geojson",
        1_000_000,
    ),
    "2011_Dist.dbf": (
        "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.dbf",
        10_000,
    ),
    "2011_Dist.prj": (
        "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.prj",
        50,
    ),
    "2011_Dist.shp": (
        "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.shp",
        1_000_000,
    ),
    "2011_Dist.shx": (
        "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.shx",
        1_000,
    ),
    "census2011_pca_india.xlsx": (
        "https://censusindia.gov.in/nada/index.php/catalog/42559/download/46185/2011-IndiaStateDistSbDistTwn-0000.xlsx",
        10_000_000,
    ),
    "census2011_area.xlsx": (
        "https://censusindia.gov.in/nada/index.php/catalog/42526/download/46152/A-1_NO_OF_VILLAGES_TOWNS_HOUSEHOLDS_POPULATION_AND_AREA.xlsx",
        1_000_000,
    ),
    "ind_ppp_2020_1km_UNadj.tif": (
        "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif",
        18_000_000,
    ),
    "wc2.1_2.5m_elev.zip": (
        "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_2.5m_elev.zip",
        15_000_000,
    ),
    "ibm_nmi_2025_chapter5_mineral_wise.pdf": (
        "https://ibm.gov.in/writereaddata/files/17848872906a6337fae632bChapter__5_Mineral_wise.pdf",
        1_000_000,
    ),
    "ima_master_list_2026-09.pdf": (
        "https://cnmnc.units.it/files/editor/IMA_Master_List_(2026-09).pdf",
        3_000_000,
    ),
    "usgs_mcs2026_commodities_data.csv": (
        "https://www.sciencebase.gov/catalog/file/get/69837e43b66b01367d7ec7c7?f=__disk__d3%2Fac%2F84%2Fd3ac8466552946c5e8caa2c2c6338d9e1aff655d",
        3_000_000,
    ),
}

GEOLOGY_SERVICE = (
    "https://livingatlas.esri.in/server1/rest/services/Geology/Geology/MapServer/0"
)
POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/regional"
POWER_PARAMETERS = WEATHER_CONFIG["parameters"]
LAT_EDGES = [6.0, 14.0, 22.0, 30.0, 38.0]
LON_EDGES = [68.0, 75.5, 83.0, 90.5, 98.0]


def download(url: str, dest: Path, min_bytes: int, force: bool = False) -> None:
    if not force and dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"cached  {dest.relative_to(ROOT)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, 5):
        try:
            with requests.get(url, timeout=(20, 180), stream=True) as response:
                response.raise_for_status()
                with part.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if part.stat().st_size < min_bytes:
                raise RuntimeError(
                    f"download too small: {part.stat().st_size} bytes; expected >= {min_bytes}"
                )
            os.replace(part, dest)
            print(f"fetched {dest.relative_to(ROOT)}")
            return
        except Exception as exc:
            if attempt == 4:
                raise
            print(f"retry {attempt}/4 {dest.name}: {exc}")
            time.sleep(attempt * 2)


def extract_archives() -> None:
    mrds_dest = RAW / "mrds" / "mrds.csv"
    if not mrds_dest.exists() or mrds_dest.stat().st_size < 100_000_000:
        mrds_dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(RAW / "mrds-csv.zip") as archive:
            archive.extractall(mrds_dest.parent)
        print(f"extracted {mrds_dest.relative_to(ROOT)}")
    elevation_dest = RAW / "wc2.1_2.5m_elev.tif"
    if not elevation_dest.exists() or elevation_dest.stat().st_size < 15_000_000:
        with zipfile.ZipFile(RAW / "wc2.1_2.5m_elev.zip") as archive:
            archive.extract("wc2.1_2.5m_elev.tif", RAW)
        print(f"extracted {elevation_dest.relative_to(ROOT)}")


def download_geology(force: bool = False) -> None:
    dest = RAW / "india_geology_esri_living_atlas.geojson"
    if not force and dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"cached  {dest.relative_to(ROOT)}")
        return
    metadata = requests.get(f"{GEOLOGY_SERVICE}?f=json", timeout=60).json()
    count = requests.get(
        f"{GEOLOGY_SERVICE}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        timeout=60,
    ).json()["count"]
    # Full-resolution polygons can exceed the service's response budget. A
    # 0.001-degree simplification is well below the H3 resolution used later.
    page_size = min(int(metadata.get("maxRecordCount", 2000)), 500)
    features = []
    for offset in range(0, count, page_size):
        response = requests.get(
            f"{GEOLOGY_SERVICE}/query",
            params={
                "where": "1=1",
                "outFields": "objectid,index_,age_code,age,supergroup,group_,geom_id,stratigraphy",
                "returnGeometry": "true",
                "outSR": "4326",
                "geometryPrecision": 4,
                "maxAllowableOffset": 0.001,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "orderByFields": "objectid",
                "f": "geojson",
            },
            timeout=180,
        )
        response.raise_for_status()
        page = response.json()
        features.extend(page.get("features", []))
        print(f"geology {min(offset + page_size, count)}/{count}")
    if len(features) != count:
        raise RuntimeError(f"geology feature count mismatch: {len(features)} != {count}")
    payload = {
        "type": "FeatureCollection",
        "name": "India geology sampled from Esri India Living Atlas service",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(part, dest)
    print(f"fetched {dest.relative_to(ROOT)}")


def _power_task(parameter: str, i: int, j: int, force: bool) -> str:
    lat_min, lat_max = LAT_EDGES[i], LAT_EDGES[i + 1]
    lon_min, lon_max = LON_EDGES[j], LON_EDGES[j + 1]
    filename = f"{parameter}_lat{lat_min:g}_{lat_max:g}_lon{lon_min:g}_{lon_max:g}.csv"
    dest = POWER_DIR / filename
    if not force and dest.exists() and dest.stat().st_size > 500:
        return f"cached  {dest.relative_to(ROOT)}"
    params = {
        "start": POWER_START.replace("-", ""),
        "end": POWER_END.replace("-", ""),
        "latitude-min": lat_min,
        "latitude-max": lat_max,
        "longitude-min": lon_min,
        "longitude-max": lon_max,
        "community": "AG",
        "parameters": parameter,
        "format": "CSV",
        "time-standard": WEATHER_CONFIG["time_standard"],
    }
    for attempt in range(1, 5):
        try:
            response = requests.get(POWER_BASE, params=params, timeout=180)
            response.raise_for_status()
            if "-END HEADER-" not in response.text:
                raise RuntimeError(response.text[:300])
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(dest.suffix + ".part")
            part.write_bytes(response.content)
            os.replace(part, dest)
            return f"fetched {dest.relative_to(ROOT)}"
        except Exception:
            if attempt == 4:
                raise
            time.sleep(attempt * 2)
    raise AssertionError("unreachable")


def download_power(force: bool = False) -> None:
    POWER_DIR.mkdir(parents=True, exist_ok=True)
    print(f"NASA POWER daily weather window: {POWER_START} through {POWER_END}")
    jobs = [
        (parameter, i, j, force)
        for parameter in POWER_PARAMETERS
        for i in range(len(LAT_EDGES) - 1)
        for j in range(len(LON_EDGES) - 1)
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_power_task, *job) for job in jobs]
        for future in as_completed(futures):
            print(future.result())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="redownload cached source files")
    parser.add_argument("--skip-climate", action="store_true")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    for filename, (url, min_bytes) in STATIC_SOURCES.items():
        download(url, RAW / filename, min_bytes, force=args.force)
    extract_archives()
    download_geology(force=args.force)
    if not args.skip_climate:
        download_power(force=args.force)


if __name__ == "__main__":
    main()
