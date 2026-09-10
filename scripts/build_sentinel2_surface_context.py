#!/usr/bin/env python3
"""Build a nationwide, non-scoring Sentinel-2 surface-context layer for KHANAN.

The pipeline queries the public Microsoft Planetary Computer STAC mirror of
Copernicus Sentinel-2 Level-2A, selects one reproducible scene per India-
relevant MGRS tile in each of two fixed 2025 seasonal windows, and samples each
KHANAN H3 resolution-6 cell at all 49 H3 resolution-8 child centroids.

Six BOA-reflectance bands are averaged to an approximately 160 m overview.
Scene classification is sampled from the native 20 m SCL COG so categorical
classes are never inferred from resampled overview values. Digital numbers are
converted with the per-product BOA quantification value and band offsets parsed
from source metadata. Published outputs are contextual spectral summaries, not
mineral detections, discoveries, deposits, grades, reserves or drill targets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import threading
import time
import warnings
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import h3
import numpy as np
import pandas as pd
import rasterio
import requests
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from shapely import contains_xy
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RAW = ROOT / "sources" / "raw" / "sentinel2_surface_context_2025"
SAMPLE_CACHE = RAW / "scene_samples"

RELEASE_VERSION = "v1.0-alpha.18"
GEOSPATIAL_FEATURE_VERSION = "v0.12"
FEATURE_VERSION = "sentinel2-l2a-h3-r6-surface-context-v0.1"
SOURCE_ACCESSED_DATE = "2026-09-10"
SOURCE_ID = "SRC_COPERNICUS_SENTINEL2_L2A_PC"

STAC_ROOT = "https://planetarycomputer.microsoft.com/api/stac/v1"
STAC_SEARCH = f"{STAC_ROOT}/search"
STAC_COLLECTION = "sentinel-2-l2a"
STAC_COLLECTION_URL = f"{STAC_ROOT}/collections/{STAC_COLLECTION}"
SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COPERNICUS_STAC_DOC_URL = "https://documentation.dataspace.copernicus.eu/APIs/STAC.html"
COPERNICUS_L2A_PRODUCT_URL = (
    "https://sentinels.copernicus.eu/web/sentinel/sentinel-data-access/"
    "sentinel-products/sentinel-2-data-products/collection-0-level-2a"
)
COPERNICUS_LEGAL_URL = (
    "https://sentinels.copernicus.eu/documents/247904/690755/"
    "Sentinel_Data_Legal_Notice"
)

CATALOG_BBOX = (67.0, 5.0, 99.0, 39.5)
CATALOG_CLOUD_CEILING_PCT = 60.0
CATALOG_NODATA_CEILING_PCT = 100.0
SEASONS: OrderedDict[str, tuple[str, str]] = OrderedDict(
    [
        ("dry_pre_monsoon_2025", ("2025-01-01", "2025-05-31")),
        ("post_monsoon_2025", ("2025-10-01", "2025-12-31")),
    ]
)

BANDS = OrderedDict(
    [
        ("B02", {"label": "blue", "native_gsd_m": 10, "band_id": 1}),
        ("B03", {"label": "green", "native_gsd_m": 10, "band_id": 2}),
        ("B04", {"label": "red", "native_gsd_m": 10, "band_id": 3}),
        ("B08", {"label": "nir", "native_gsd_m": 10, "band_id": 7}),
        ("B11", {"label": "swir1", "native_gsd_m": 20, "band_id": 11}),
        ("B12", {"label": "swir2", "native_gsd_m": 20, "band_id": 12}),
    ]
)
BAND_NAMES = list(BANDS)
TARGET_REFLECTANCE_GSD_M = 160.0
SCL_NATIVE_GSD_M = 20.0
PARENT_H3_RESOLUTION = 6
SAMPLE_H3_RESOLUTION = 8
SAMPLES_PER_CELL_PER_SEASON = 49

FEATURE_PATH = OUT / "india_sentinel2_surface_context_h3_r6.csv"
SCENE_MANIFEST_PATH = OUT / "india_sentinel2_scene_manifest_2025.csv"
VALIDATION_PATH = OUT / "sentinel2_surface_context_validation.json"
SELECTED_ITEMS_CACHE = RAW / "selected_stac_items.json"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"
SOURCE_REGISTRY_PATH = OUT / "source_registry.csv"
DATA_DICTIONARY_PATH = OUT / "data_dictionary.csv"
VALIDATION_REPORT_PATH = OUT / "validation_report.json"

MODEL_USE_STATUS = "excluded_from_v0.6_scoring_pending_spatial_ablation"
INTERPRETATION_CODE = "surface_context_not_mineral_detection"

SCL_LABELS = {
    0: "no_data_or_uncovered",
    1: "saturated_or_defective",
    2: "cast_shadow",
    3: "cloud_shadow",
    4: "vegetation",
    5: "not_vegetated",
    6: "water",
    7: "unclassified",
    8: "cloud_medium_probability",
    9: "cloud_high_probability",
    10: "thin_cirrus",
    11: "snow_or_ice",
}
CLEAR_LAND_CLASSES = {4, 5}
CLOUD_OR_SHADOW_CLASSES = {2, 3, 8, 9, 10}
VALID_SCL_CLASSES = set(range(1, 12))

SELECTION_RULE = (
    "maximum India H3 r6 centroid coverage inside the item footprint, then "
    "minimum(cloud_pct + snow_pct + 0.25*cloud_shadow_pct + 0.5*nodata_pct + "
    "10*degraded_pct - 0.02*not_vegetated_pct), then acquisition datetime, "
    "then item ID; among catalog items with cloud<60% and nodata<100%"
)

_THREAD_LOCAL = threading.local()


@dataclass
class GridSamples:
    grid: pd.DataFrame
    parent_h3: list[str]
    latitude: np.ndarray
    longitude: np.ndarray
    parent_index: np.ndarray
    bucket_indices: dict[tuple[int, int], np.ndarray]
    fingerprint: str


@dataclass
class SeasonObservation:
    priority: np.ndarray
    scene_index: np.ndarray
    scl: np.ndarray
    reflectance: np.ndarray
    edge_distance_m: np.ndarray


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_row() -> dict[str, str]:
    return {
        "source_id": SOURCE_ID,
        "publisher": "European Union/ESA Copernicus; COG host and processor Microsoft Planetary Computer",
        "title": "Copernicus Sentinel-2 Level-2A bottom-of-atmosphere reflectance and scene classification",
        "release_or_reference_date": f"2025 fixed seasonal observations; catalog accessed {SOURCE_ACCESSED_DATE}",
        "url": COPERNICUS_L2A_PRODUCT_URL,
        "download_url": STAC_COLLECTION_URL,
        "license_or_access_note": (
            "Copernicus Sentinel data are governed by the Sentinel Data Legal Notice and are available on a free, "
            "full and open basis. Microsoft Planetary Computer hosts cloud-optimized derivatives and its STAC "
            "collection metadata labels the collection license as proprietary. KHANAN publishes derived statistics "
            "and token-free lineage URLs, not source rasters; users must retain Copernicus attribution and review "
            "both providers' current terms."
        ),
        "used_for": (
            "Two fixed 2025 seasonal surface-context snapshots. One selected scene per India-relevant MGRS tile and "
            "season; native 20 m SCL plus six BOA-reflectance bands summarized at all 49 H3 r8 child centroids of "
            "each H3 r6 cell."
        ),
        "limitations": (
            "Multispectral surface reflectance is affected by vegetation, soil moisture, atmosphere, season, land "
            "use, mixed pixels, cloud masking and scene selection. The broad indices and ratios are non-specific "
            "surface proxies, not mineral identification, subsurface evidence, a discovery, grade, resource, reserve "
            "or permission to explore. All features are excluded from production scoring pending spatial ablation."
        ),
    }


def read_grid_samples() -> GridSamples:
    usecols = ["h3_r6", "latitude", "longitude", "grid_area_km2"]
    grid = pd.read_csv(GRID_PATH, usecols=usecols, dtype={"h3_r6": "string"})
    if len(grid) != 88857 or grid["h3_r6"].duplicated().any():
        raise RuntimeError("unexpected KHANAN H3 grid row count or duplicate cell")
    if not all(h3.get_resolution(cell) == PARENT_H3_RESOLUTION for cell in grid["h3_r6"]):
        raise RuntimeError("grid contains a cell outside H3 resolution 6")

    parent_h3 = grid["h3_r6"].astype(str).tolist()
    point_count = len(parent_h3) * SAMPLES_PER_CELL_PER_SEASON
    latitudes = np.empty(point_count, dtype=np.float32)
    longitudes = np.empty(point_count, dtype=np.float32)
    parent_index = np.repeat(np.arange(len(parent_h3), dtype=np.int32), SAMPLES_PER_CELL_PER_SEASON)
    cursor = 0
    digest = hashlib.sha256()
    digest.update(f"h3-child-centroids:{PARENT_H3_RESOLUTION}:{SAMPLE_H3_RESOLUTION}\n".encode())
    for parent in parent_h3:
        children = sorted(h3.cell_to_children(parent, SAMPLE_H3_RESOLUTION))
        if len(children) != SAMPLES_PER_CELL_PER_SEASON:
            raise RuntimeError(f"{parent} has {len(children)} r8 children, expected 49")
        digest.update((parent + "\n").encode())
        for child in children:
            latitude, longitude = h3.cell_to_latlng(child)
            latitudes[cursor] = latitude
            longitudes[cursor] = longitude
            cursor += 1

    bins: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    integer_latitudes = np.floor(latitudes).astype(np.int16)
    integer_longitudes = np.floor(longitudes).astype(np.int16)
    for index, (latitude_bin, longitude_bin) in enumerate(zip(integer_latitudes, integer_longitudes)):
        bins[(int(latitude_bin), int(longitude_bin))].append(index)
    bucket_indices = {key: np.asarray(value, dtype=np.int32) for key, value in bins.items()}
    return GridSamples(
        grid=grid,
        parent_h3=parent_h3,
        latitude=latitudes,
        longitude=longitudes,
        parent_index=parent_index,
        bucket_indices=bucket_indices,
        fingerprint=digest.hexdigest(),
    )


def stac_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "KHANAN/1.0-alpha.18 open-source research"})
        _THREAD_LOCAL.session = session
    return session


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = stac_session().request(method, url, timeout=180, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after retries: {method} {url}") from error


def scene_penalty(item: dict[str, Any]) -> float:
    properties = item["properties"]

    def number(key: str) -> float:
        value = properties.get(key)
        return float(value) if value is not None else 0.0

    return (
        number("eo:cloud_cover")
        + number("s2:snow_ice_percentage")
        + 0.25 * number("s2:cloud_shadow_percentage")
        + 0.5 * number("s2:nodata_pixel_percentage")
        + 10.0 * number("s2:degraded_msi_data_percentage")
        - 0.02 * number("s2:not_vegetated_percentage")
    )


def scene_sort_key(item: dict[str, Any]) -> tuple[float, float, str, str]:
    return (
        -float(item["_khanan_india_grid_centroid_coverage_count"]),
        scene_penalty(item),
        item["properties"]["datetime"],
        item["id"],
    )


def fetch_season_items(season_id: str, start: str, end: str) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "collections": [STAC_COLLECTION],
        "bbox": list(CATALOG_BBOX),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 1000,
        "query": {
            "eo:cloud_cover": {"lt": CATALOG_CLOUD_CEILING_PCT},
            "s2:nodata_pixel_percentage": {"lt": CATALOG_NODATA_CEILING_PCT},
        },
    }
    items: list[dict[str, Any]] = []
    page = 0
    while True:
        response = request_json("POST", STAC_SEARCH, json=body)
        page_items = response.get("features", [])
        items.extend(page_items)
        page += 1
        print(f"catalog {season_id}: page {page}, {len(items):,} items", flush=True)
        next_link = next((link for link in response.get("links", []) if link.get("rel") == "next"), None)
        if next_link is None:
            break
        if next_link.get("method", "GET").upper() != "POST" or not next_link.get("body"):
            raise RuntimeError("unexpected STAC pagination contract")
        body = next_link["body"]
    return items


def item_grid_centroid_coverage_count(item: dict[str, Any], grid: pd.DataFrame) -> int:
    polygon = shape(item["geometry"])
    min_x, min_y, max_x, max_y = polygon.bounds
    longitude = grid["longitude"].to_numpy(dtype=float)
    latitude = grid["latitude"].to_numpy(dtype=float)
    bbox_mask = (
        (longitude >= min_x)
        & (longitude <= max_x)
        & (latitude >= min_y)
        & (latitude <= max_y)
    )
    if not bbox_mask.any():
        return 0
    return int(np.count_nonzero(contains_xy(polygon, longitude[bbox_mask], latitude[bbox_mask])))


def select_items(grid: pd.DataFrame, refresh_catalog: bool) -> dict[str, list[dict[str, Any]]]:
    if SELECTED_ITEMS_CACHE.exists() and not refresh_catalog:
        cached = json.loads(SELECTED_ITEMS_CACHE.read_text(encoding="utf-8"))
        if cached.get("feature_version") == FEATURE_VERSION and cached.get("seasons") == {
            key: list(value) for key, value in SEASONS.items()
        } and cached.get("selection_rule") == SELECTION_RULE:
            selected = cached["selected_items"]
            return {season: sorted(items, key=lambda item: item["properties"]["s2:mgrs_tile"]) for season, items in selected.items()}

    selected: dict[str, list[dict[str, Any]]] = {}
    catalog_counts: dict[str, int] = {}
    for season_id, (start, end) in SEASONS.items():
        items = fetch_season_items(season_id, start, end)
        catalog_counts[season_id] = len(items)
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            grouped[item["properties"]["s2:mgrs_tile"]].append(item)
        relevant: list[dict[str, Any]] = []
        for tile_items in grouped.values():
            for item in tile_items:
                item["_khanan_india_grid_centroid_coverage_count"] = item_grid_centroid_coverage_count(item, grid)
            india_covering_items = [
                item for item in tile_items if item["_khanan_india_grid_centroid_coverage_count"] > 0
            ]
            if india_covering_items:
                relevant.append(min(india_covering_items, key=scene_sort_key))
        selected[season_id] = sorted(relevant, key=lambda item: item["properties"]["s2:mgrs_tile"])
        print(
            f"catalog {season_id}: selected {len(relevant):,} India-relevant tiles from "
            f"{len(grouped):,} catalog tiles",
            flush=True,
        )
    tile_sets = [set(item["properties"]["s2:mgrs_tile"] for item in items) for items in selected.values()]
    if len(tile_sets) != 2 or tile_sets[0] != tile_sets[1]:
        raise RuntimeError("seasonal MGRS tile coverage does not match")
    cache = {
        "feature_version": FEATURE_VERSION,
        "source_accessed_date": SOURCE_ACCESSED_DATE,
        "stac_collection": STAC_COLLECTION,
        "stac_search_url": STAC_SEARCH,
        "catalog_bbox": list(CATALOG_BBOX),
        "catalog_cloud_ceiling_pct": CATALOG_CLOUD_CEILING_PCT,
        "catalog_nodata_ceiling_pct": CATALOG_NODATA_CEILING_PCT,
        "seasons": {key: list(value) for key, value in SEASONS.items()},
        "selection_rule": SELECTION_RULE,
        "catalog_item_counts": catalog_counts,
        "selected_items": selected,
    }
    atomic_json(SELECTED_ITEMS_CACHE, cache)
    return selected


def candidate_point_indices(item: dict[str, Any], samples: GridSamples) -> np.ndarray:
    bbox = item.get("bbox") or shape(item["geometry"]).bounds
    min_x, min_y, max_x, max_y = map(float, bbox)
    arrays: list[np.ndarray] = []
    for latitude_bin in range(math.floor(min_y), math.floor(max_y) + 1):
        for longitude_bin in range(math.floor(min_x), math.floor(max_x) + 1):
            values = samples.bucket_indices.get((latitude_bin, longitude_bin))
            if values is not None:
                arrays.append(values)
    if not arrays:
        return np.empty(0, dtype=np.int32)
    indices = np.unique(np.concatenate(arrays))
    longitude = samples.longitude[indices]
    latitude = samples.latitude[indices]
    mask = (
        (longitude >= min_x)
        & (longitude <= max_x)
        & (latitude >= min_y)
        & (latitude <= max_y)
    )
    return indices[mask]


def append_sas_query(url: str, query: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=query))


def signed_assets(item: dict[str, Any]) -> dict[str, str]:
    hrefs = {name: item["assets"][name]["href"] for name in BAND_NAMES + ["SCL", "product-metadata"]}
    response = request_json("GET", SAS_SIGN_URL, params={"href": hrefs["B02"]})
    query = urlparse(response["href"]).query
    if not query or "sig=" not in query:
        raise RuntimeError("Planetary Computer signer returned no SAS query")
    return {name: append_sas_query(href, query) for name, href in hrefs.items()}


def download_bytes(url: str) -> bytes:
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = stac_session().get(url, timeout=180)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            error = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed after retries: {urlparse(url).path}") from error


def local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_radiometry(metadata: bytes) -> tuple[float, dict[str, float]]:
    root = ElementTree.fromstring(metadata)
    quantification: float | None = None
    offsets_by_id: dict[int, float] = {}
    for element in root.iter():
        name = local_name(element)
        if name == "BOA_QUANTIFICATION_VALUE" and element.text:
            quantification = float(element.text)
        elif name == "BOA_ADD_OFFSET" and element.text and element.attrib.get("band_id") is not None:
            offsets_by_id[int(element.attrib["band_id"])] = float(element.text)
    if quantification is None or quantification <= 0:
        raise RuntimeError("BOA quantification value missing from product metadata")
    offsets = {band: offsets_by_id.get(int(spec["band_id"]), 0.0) for band, spec in BANDS.items()}
    return quantification, offsets


def read_reflectance_overview(
    url: str,
    expected_epsg: int,
    quantification: float,
    offset: float,
) -> tuple[np.ndarray, Affine, tuple[float, float, float, float]]:
    with rasterio.open(url) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != expected_epsg or dataset.count != 1:
            raise RuntimeError("unexpected Sentinel-2 COG CRS or band count")
        native_gsd = float(abs(dataset.transform.a))
        output_width = max(1, round(dataset.width * native_gsd / TARGET_REFLECTANCE_GSD_M))
        output_height = max(1, round(dataset.height * native_gsd / TARGET_REFLECTANCE_GSD_M))
        array = dataset.read(
            1,
            out_shape=(output_height, output_width),
            out_dtype="float32",
            masked=True,
            resampling=Resampling.average,
        ).filled(np.nan)
        transform = dataset.transform * Affine.scale(
            dataset.width / output_width,
            dataset.height / output_height,
        )
        bounds = tuple(float(value) for value in dataset.bounds)
    valid = np.isfinite(array) & (array != 0)
    reflectance = np.full(array.shape, np.nan, dtype=np.float32)
    reflectance[valid] = (array[valid] + offset) / quantification
    return reflectance, transform, bounds


def read_native_scl(url: str, expected_epsg: int) -> tuple[np.ndarray, Affine]:
    with rasterio.open(url) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != expected_epsg or dataset.count != 1:
            raise RuntimeError("unexpected Sentinel-2 SCL COG CRS or band count")
        if not np.isclose(abs(dataset.transform.a), SCL_NATIVE_GSD_M, atol=0.01):
            raise RuntimeError("unexpected Sentinel-2 SCL native resolution")
        array = dataset.read(1)
        transform = dataset.transform
    return array, transform


def sample_array(array: np.ndarray, transform: Affine, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    inverse = ~transform
    column_float, row_float = inverse * (x, y)
    row = np.floor(row_float).astype(np.int32)
    column = np.floor(column_float).astype(np.int32)
    inside = (row >= 0) & (row < array.shape[0]) & (column >= 0) & (column < array.shape[1])
    values = np.full(len(x), np.nan, dtype=np.float32)
    values[inside] = array[row[inside], column[inside]]
    return values, row, column


def cache_path(season_id: str, item: dict[str, Any]) -> Path:
    tile = item["properties"]["s2:mgrs_tile"]
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", item["id"])
    return SAMPLE_CACHE / season_id / f"{tile}__{safe_id}.npz"


def asset_href_fingerprint(item: dict[str, Any]) -> str:
    payload = {name: item["assets"][name]["href"] for name in BAND_NAMES + ["SCL", "product-metadata"]}
    return hashlib.sha256(json_compact(payload).encode()).hexdigest()


def load_scene_cache(path: Path, item: dict[str, Any], samples: GridSamples) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as cached:
            if (
                str(cached["feature_version"].item()) != FEATURE_VERSION
                or str(cached["item_id"].item()) != item["id"]
                or str(cached["sample_fingerprint"].item()) != samples.fingerprint
                or str(cached["asset_href_fingerprint"].item()) != asset_href_fingerprint(item)
            ):
                return None
            return {name: cached[name].copy() for name in cached.files}
    except (OSError, ValueError, KeyError):
        return None


def save_scene_cache(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **values)
    temporary.replace(path)


def extract_scene(
    task: tuple[str, int, dict[str, Any], GridSamples, bool],
) -> dict[str, Any]:
    season_id, scene_index, item, samples, refresh_assets = task
    path = cache_path(season_id, item)
    if not refresh_assets:
        cached = load_scene_cache(path, item, samples)
        if cached is not None:
            cached["scene_index"] = np.asarray(scene_index, dtype=np.int16)
            cached["cache_hit"] = np.asarray(True)
            return cached

    point_index = candidate_point_indices(item, samples)
    if len(point_index) == 0:
        raise RuntimeError(f"selected scene {item['id']} has no candidate sample points")
    expected_epsg = int(item["properties"]["proj:epsg"])
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{expected_epsg}", always_xy=True)
    x, y = transformer.transform(samples.longitude[point_index], samples.latitude[point_index])
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    error: Exception | None = None
    for attempt in range(3):
        try:
            urls = signed_assets(item)
            metadata = download_bytes(urls["product-metadata"])
            quantification, offsets = parse_radiometry(metadata)
            metadata_sha256 = hashlib.sha256(metadata).hexdigest()
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MULTIRANGE="YES",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                GDAL_HTTP_MAX_RETRY="3",
                GDAL_HTTP_RETRY_DELAY="1",
                VSI_CACHE="TRUE",
                VSI_CACHE_SIZE="25000000",
            ):
                scl_array, scl_transform = read_native_scl(urls["SCL"], expected_epsg)
                scl_values, _, _ = sample_array(scl_array, scl_transform, x, y)
                scl_values = np.where(np.isfinite(scl_values), scl_values, 0).astype(np.uint8)

                reflectance_rows: list[np.ndarray] = []
                reference_transform: Affine | None = None
                reference_bounds: tuple[float, float, float, float] | None = None
                reference_row: np.ndarray | None = None
                reference_column: np.ndarray | None = None
                inside_all = np.ones(len(point_index), dtype=bool)
                for band in BAND_NAMES:
                    array, transform, bounds = read_reflectance_overview(
                        urls[band], expected_epsg, quantification, offsets[band]
                    )
                    values, row, column = sample_array(array, transform, x, y)
                    reflectance_rows.append(values)
                    inside_all &= np.isfinite(values) | (
                        (row >= 0) & (row < array.shape[0]) & (column >= 0) & (column < array.shape[1])
                    )
                    if reference_transform is None:
                        reference_transform = transform
                        reference_bounds = bounds
                        reference_row = row
                        reference_column = column
                    elif not np.allclose(tuple(transform)[:6], tuple(reference_transform)[:6], atol=0.25, rtol=0):
                        raise RuntimeError(f"band overview transforms do not align for {item['id']}")
                if reference_row is None or reference_column is None or reference_bounds is None:
                    raise RuntimeError("no reflectance bands extracted")

            reflectance = np.vstack(reflectance_rows).astype(np.float32)
            valid_geometry = (
                (reference_row >= 0)
                & (reference_column >= 0)
                & inside_all
            )
            point_index = point_index[valid_geometry]
            scl_values = scl_values[valid_geometry]
            reflectance = reflectance[:, valid_geometry]
            edge_pixels = np.minimum.reduce(
                [
                    reference_row[valid_geometry],
                    reference_column[valid_geometry],
                    685 - reference_row[valid_geometry],
                    685 - reference_column[valid_geometry],
                ]
            )
            edge_distance_m = np.maximum(edge_pixels, 0).astype(np.float32) * TARGET_REFLECTANCE_GSD_M
            result: dict[str, Any] = {
                "feature_version": np.asarray(FEATURE_VERSION),
                "item_id": np.asarray(item["id"]),
                "scene_index": np.asarray(scene_index, dtype=np.int16),
                "sample_fingerprint": np.asarray(samples.fingerprint),
                "asset_href_fingerprint": np.asarray(asset_href_fingerprint(item)),
                "point_index": point_index.astype(np.int32),
                "scl": scl_values.astype(np.uint8),
                "reflectance": reflectance,
                "edge_distance_m": edge_distance_m,
                "boa_quantification_value": np.asarray(quantification, dtype=np.float32),
                "boa_add_offsets": np.asarray([offsets[band] for band in BAND_NAMES], dtype=np.float32),
                "product_metadata_sha256": np.asarray(metadata_sha256),
                "native_scl_min": np.asarray(int(scl_array.min()), dtype=np.int16),
                "native_scl_max": np.asarray(int(scl_array.max()), dtype=np.int16),
                "cache_hit": np.asarray(False),
            }
            save_scene_cache(path, result)
            return result
        except Exception as exc:  # network/GDAL failures are retried with a fresh SAS token
            error = exc
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"scene extraction failed after retries: {season_id} {item['id']}") from error


def class_priority(scl: np.ndarray) -> np.ndarray:
    priority = np.zeros(len(scl), dtype=np.int32)
    priority[np.isin(scl, list(CLOUD_OR_SHADOW_CLASSES))] = 1
    priority[np.isin(scl, [6, 7, 11])] = 2
    priority[np.isin(scl, list(CLEAR_LAND_CLASSES))] = 3
    return priority


def create_season_observation(point_count: int) -> SeasonObservation:
    return SeasonObservation(
        priority=np.full(point_count, -1, dtype=np.int32),
        scene_index=np.full(point_count, -1, dtype=np.int16),
        scl=np.zeros(point_count, dtype=np.uint8),
        reflectance=np.full((len(BAND_NAMES), point_count), np.nan, dtype=np.float32),
        edge_distance_m=np.full(point_count, -1.0, dtype=np.float32),
    )


def integrate_scene(observation: SeasonObservation, result: dict[str, Any]) -> None:
    point_index = result["point_index"].astype(np.int32)
    scl = result["scl"].astype(np.uint8)
    reflectance = result["reflectance"].astype(np.float32)
    edge_distance = result["edge_distance_m"].astype(np.float32)
    valid_band_count = np.isfinite(reflectance).sum(axis=0).astype(np.int32)
    new_priority = (
        class_priority(scl) * 1_000_000
        + valid_band_count * 10_000
        + np.minimum(edge_distance, 9999).astype(np.int32)
    )
    better = new_priority > observation.priority[point_index]
    if not better.any():
        return
    target = point_index[better]
    observation.priority[target] = new_priority[better]
    observation.scene_index[target] = int(result["scene_index"].item())
    observation.scl[target] = scl[better]
    observation.reflectance[:, target] = reflectance[:, better]
    observation.edge_distance_m[target] = edge_distance[better]


def process_season(
    season_id: str,
    items: list[dict[str, Any]],
    samples: GridSamples,
    workers: int,
    refresh_assets: bool,
) -> tuple[SeasonObservation, list[dict[str, Any]]]:
    observation = create_season_observation(len(samples.latitude))
    scene_results: list[dict[str, Any]] = []
    tasks = [(season_id, index, item, samples, refresh_assets) for index, item in enumerate(items)]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"s2-{season_id[:4]}") as executor:
        for completed, result in enumerate(executor.map(extract_scene, tasks), start=1):
            integrate_scene(observation, result)
            scene_results.append(
                {
                    "scene_index": int(result["scene_index"].item()),
                    "sample_point_candidates_in_tile": int(len(result["point_index"])),
                    "boa_quantification_value": float(result["boa_quantification_value"].item()),
                    "boa_add_offsets": [float(value) for value in result["boa_add_offsets"]],
                    "product_metadata_sha256": str(result["product_metadata_sha256"].item()),
                    "native_scl_min": int(result["native_scl_min"].item()),
                    "native_scl_max": int(result["native_scl_max"].item()),
                    "cache_hit": bool(result["cache_hit"].item()),
                }
            )
            if completed == 1 or completed % 10 == 0 or completed == len(items):
                cache_hits = sum(row["cache_hit"] for row in scene_results)
                print(
                    f"assets {season_id}: {completed}/{len(items)} scenes integrated; "
                    f"cache hits {cache_hits}",
                    flush=True,
                )
    return observation, scene_results


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    result = np.full(a.shape, np.nan, dtype=np.float32)
    denominator = a + b
    valid = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0) & (denominator > 1e-6)
    result[valid] = (a[valid] - b[valid]) / denominator[valid]
    return result


def bare_soil_index(b02: np.ndarray, b04: np.ndarray, b08: np.ndarray, b11: np.ndarray) -> np.ndarray:
    result = np.full(b02.shape, np.nan, dtype=np.float32)
    numerator = (b11 + b04) - (b08 + b02)
    denominator = (b11 + b04) + (b08 + b02)
    valid = (
        np.isfinite(b02)
        & np.isfinite(b04)
        & np.isfinite(b08)
        & np.isfinite(b11)
        & (b02 > 0)
        & (b04 > 0)
        & (b08 > 0)
        & (b11 > 0)
        & (denominator > 1e-6)
    )
    result[valid] = numerator[valid] / denominator[valid]
    return result


def positive_ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    result = np.full(a.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 1e-6)
    result[valid] = a[valid] / b[valid]
    return result


def row_nanmedian(values: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmedian(values, axis=1).astype(np.float32)


def masked_median(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return row_nanmedian(np.where(mask, values, np.nan))


def spectral_index_arrays(reflectance: np.ndarray) -> dict[str, np.ndarray]:
    band = {name: reflectance[index] for index, name in enumerate(BAND_NAMES)}
    return {
        "ndvi": normalized_difference(band["B08"], band["B04"]),
        "ndmi": normalized_difference(band["B08"], band["B11"]),
        "mndwi": normalized_difference(band["B03"], band["B11"]),
        "bsi": bare_soil_index(band["B02"], band["B04"], band["B08"], band["B11"]),
        "ndti": normalized_difference(band["B11"], band["B12"]),
        "red_blue_ratio": positive_ratio(band["B04"], band["B02"]),
        "swir1_swir2_ratio": positive_ratio(band["B11"], band["B12"]),
    }


def source_scene_ids_by_parent(scene_index: np.ndarray, items: list[dict[str, Any]]) -> list[str]:
    matrix = scene_index.reshape(-1, SAMPLES_PER_CELL_PER_SEASON)
    item_ids = [item["id"] for item in items]
    values: list[str] = []
    for row in matrix:
        indices = sorted({int(value) for value in row if value >= 0})
        values.append(json_compact([item_ids[index] for index in indices]))
    return values


def season_summary(
    season_id: str,
    observation: SeasonObservation,
    items: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    parent_count = len(observation.scl) // SAMPLES_PER_CELL_PER_SEASON
    scl = observation.scl.reshape(parent_count, SAMPLES_PER_CELL_PER_SEASON)
    reflectance = observation.reflectance.reshape(
        len(BAND_NAMES), parent_count, SAMPLES_PER_CELL_PER_SEASON
    )
    all_bands_valid = np.all(np.isfinite(reflectance), axis=0)
    valid_scl = np.isin(scl, list(VALID_SCL_CLASSES))
    clear_land = np.isin(scl, list(CLEAR_LAND_CLASSES)) & all_bands_valid
    bare = (scl == 5) & all_bands_valid
    prefix = "dry" if season_id.startswith("dry") else "post"

    summary: dict[str, Any] = {
        f"{prefix}_source_scene_ids_json": source_scene_ids_by_parent(observation.scene_index, items),
        f"{prefix}_covered_sample_count": valid_scl.sum(axis=1).astype(np.int16),
        f"{prefix}_band_valid_sample_count": all_bands_valid.sum(axis=1).astype(np.int16),
        f"{prefix}_clear_land_sample_count": clear_land.sum(axis=1).astype(np.int16),
        f"{prefix}_bare_sample_count": bare.sum(axis=1).astype(np.int16),
        f"{prefix}_vegetation_sample_count": (scl == 4).sum(axis=1).astype(np.int16),
        f"{prefix}_water_sample_count": (scl == 6).sum(axis=1).astype(np.int16),
        f"{prefix}_cloud_or_shadow_sample_count": np.isin(scl, list(CLOUD_OR_SHADOW_CLASSES)).sum(axis=1).astype(np.int16),
        f"{prefix}_snow_or_ice_sample_count": (scl == 11).sum(axis=1).astype(np.int16),
        f"{prefix}_unclassified_sample_count": (scl == 7).sum(axis=1).astype(np.int16),
        f"{prefix}_invalid_or_uncovered_sample_count": (~valid_scl).sum(axis=1).astype(np.int16),
        f"{prefix}_covered_sample_fraction": valid_scl.mean(axis=1).astype(np.float32),
        f"{prefix}_clear_land_sample_fraction": clear_land.mean(axis=1).astype(np.float32),
        f"{prefix}_bare_sample_fraction": bare.mean(axis=1).astype(np.float32),
    }
    for band_index, band_name in enumerate(BAND_NAMES):
        summary[f"{prefix}_clear_land_{band_name.lower()}_reflectance_median"] = masked_median(
            reflectance[band_index], clear_land
        )
    indices = spectral_index_arrays(reflectance)
    for name in ["ndvi", "ndmi", "mndwi", "bsi", "ndti"]:
        summary[f"{prefix}_clear_land_{name}_median"] = masked_median(indices[name], clear_land)
    raw = {
        "reflectance": reflectance,
        "clear_land": clear_land,
        "bare": bare,
        "scl": scl,
    }
    return summary, raw


def annual_bare_summary(season_raw: list[dict[str, np.ndarray]]) -> dict[str, Any]:
    reflectance = np.concatenate([value["reflectance"] for value in season_raw], axis=2)
    bare = np.concatenate([value["bare"] for value in season_raw], axis=1)
    clear_land = np.concatenate([value["clear_land"] for value in season_raw], axis=1)
    result: dict[str, Any] = {
        "annual_clear_land_sample_count": clear_land.sum(axis=1).astype(np.int16),
        "annual_bare_sample_count": bare.sum(axis=1).astype(np.int16),
        "annual_clear_land_sample_fraction": clear_land.mean(axis=1).astype(np.float32),
        "annual_bare_sample_fraction": bare.mean(axis=1).astype(np.float32),
    }
    for band_index, band_name in enumerate(BAND_NAMES):
        result[f"annual_bare_{band_name.lower()}_reflectance_median"] = masked_median(
            reflectance[band_index], bare
        )
    indices = spectral_index_arrays(reflectance)
    for name, values in indices.items():
        result[f"annual_bare_{name}_median"] = masked_median(values, bare)
    return result


def quality_status_and_flags(feature: pd.DataFrame) -> tuple[list[str], list[str]]:
    statuses: list[str] = []
    flags: list[str] = []
    for row in feature.itertuples(index=False):
        row_flags: list[str] = []
        dry_bare = int(row.dry_bare_sample_count)
        post_bare = int(row.post_bare_sample_count)
        annual_bare = int(row.annual_bare_sample_count)
        if dry_bare >= 5 and post_bare >= 5:
            status = "two_season_bare_support"
        elif annual_bare >= 10:
            status = "one_season_dominant_bare_support"
            row_flags.append("bare_support_not_balanced_between_seasons")
        else:
            status = "insufficient_bare_support"
            row_flags.append("fewer_than_10_bare_samples_across_98_requested")
        if row.dry_covered_sample_count < SAMPLES_PER_CELL_PER_SEASON:
            row_flags.append("dry_window_incomplete_coverage")
        if row.post_covered_sample_count < SAMPLES_PER_CELL_PER_SEASON:
            row_flags.append("post_window_incomplete_coverage")
        if row.dry_cloud_or_shadow_sample_count > SAMPLES_PER_CELL_PER_SEASON / 2:
            row_flags.append("dry_window_majority_cloud_or_shadow")
        if row.post_cloud_or_shadow_sample_count > SAMPLES_PER_CELL_PER_SEASON / 2:
            row_flags.append("post_window_majority_cloud_or_shadow")
        if row.annual_clear_land_sample_count == 0:
            row_flags.append("no_clear_land_reflectance_sample")
        statuses.append(status)
        flags.append(json_compact(row_flags))
    return statuses, flags


def build_feature_table(
    samples: GridSamples,
    selected: dict[str, list[dict[str, Any]]],
    observations: dict[str, SeasonObservation],
) -> pd.DataFrame:
    feature = pd.DataFrame(
        {
            "record_id": [f"S2CTX-{cell}" for cell in samples.parent_h3],
            "h3_r6": samples.parent_h3,
            "latitude": samples.grid["latitude"].to_numpy(dtype=float),
            "longitude": samples.grid["longitude"].to_numpy(dtype=float),
            "coordinate_reference_system": "EPSG:4326",
            "grid_area_km2": samples.grid["grid_area_km2"].to_numpy(dtype=float),
            "source_reference_period_start": min(start for start, _ in SEASONS.values()),
            "source_reference_period_end": max(end for _, end in SEASONS.values()),
            "season_windows_json": json_compact({key: {"start": value[0], "end": value[1]} for key, value in SEASONS.items()}),
            "sample_design": "all_h3_r8_child_centroids_within_each_h3_r6_cell",
            "sample_points_per_cell_per_season": SAMPLES_PER_CELL_PER_SEASON,
            "target_reflectance_overview_gsd_m": TARGET_REFLECTANCE_GSD_M,
            "scl_sampling_gsd_m": SCL_NATIVE_GSD_M,
        }
    )
    season_raw: list[dict[str, np.ndarray]] = []
    for season_id in SEASONS:
        summary, raw = season_summary(season_id, observations[season_id], selected[season_id])
        for column, values in summary.items():
            feature[column] = values
        season_raw.append(raw)
    for column, values in annual_bare_summary(season_raw).items():
        feature[column] = values
    statuses, flags = quality_status_and_flags(feature)
    feature["bare_surface_quality_status"] = statuses
    feature["spectral_proxy_interpretation"] = INTERPRETATION_CODE
    feature["feature_version"] = FEATURE_VERSION
    feature["model_use_status"] = MODEL_USE_STATUS
    feature["source_dataset_ids_json"] = json_compact([SOURCE_ID])
    feature["data_quality_flags_json"] = flags
    return feature


def property_number(item: dict[str, Any], key: str) -> float | str:
    value = item["properties"].get(key)
    return "" if value is None else float(value)


def token_free_url(item: dict[str, Any], asset: str) -> str:
    return item["assets"][asset]["href"].split("?", 1)[0]


def build_scene_manifest(
    selected: dict[str, list[dict[str, Any]]],
    scene_results: dict[str, list[dict[str, Any]]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for season_id, items in selected.items():
        start, end = SEASONS[season_id]
        results = {row["scene_index"]: row for row in scene_results[season_id]}
        for scene_index, item in enumerate(items):
            result = results[scene_index]
            properties = item["properties"]
            row: dict[str, Any] = {
                "season_id": season_id,
                "season_start": start,
                "season_end": end,
                "scene_item_id": item["id"],
                "mgrs_tile": properties["s2:mgrs_tile"],
                "acquisition_datetime_utc": properties["datetime"],
                "platform": properties.get("platform", ""),
                "constellation": properties.get("constellation", ""),
                "instrument": json_compact(properties.get("instruments", [])),
                "processing_baseline": properties.get("s2:processing_baseline", ""),
                "relative_orbit": properties.get("sat:relative_orbit", ""),
                "orbit_state": properties.get("sat:orbit_state", ""),
                "cloud_cover_pct": property_number(item, "eo:cloud_cover"),
                "cloud_shadow_pct": property_number(item, "s2:cloud_shadow_percentage"),
                "snow_ice_pct": property_number(item, "s2:snow_ice_percentage"),
                "vegetation_pct": property_number(item, "s2:vegetation_percentage"),
                "not_vegetated_pct": property_number(item, "s2:not_vegetated_percentage"),
                "water_pct": property_number(item, "s2:water_percentage"),
                "nodata_pixel_pct": property_number(item, "s2:nodata_pixel_percentage"),
                "degraded_msi_data_pct": property_number(item, "s2:degraded_msi_data_percentage"),
                "selection_penalty": scene_penalty(item),
                "selection_rule": SELECTION_RULE,
                "proj_epsg": int(properties["proj:epsg"]),
                "product_uri": properties.get("s2:product_uri", ""),
                "source_item_url": next((link["href"] for link in item.get("links", []) if link.get("rel") == "self"), ""),
                "product_metadata_url": token_free_url(item, "product-metadata"),
                "boa_quantification_value": result["boa_quantification_value"],
                "product_metadata_sha256": result["product_metadata_sha256"],
                "native_scl_code_min": result["native_scl_min"],
                "native_scl_code_max": result["native_scl_max"],
                "sample_point_candidates_in_tile": result["sample_point_candidates_in_tile"],
                "india_grid_centroids_in_item_footprint": int(item["_khanan_india_grid_centroid_coverage_count"]),
                "target_reflectance_overview_gsd_m": TARGET_REFLECTANCE_GSD_M,
                "scl_sampling_gsd_m": SCL_NATIVE_GSD_M,
                "source_dataset_id": SOURCE_ID,
                "model_use_status": MODEL_USE_STATUS,
            }
            for band, offset in zip(BAND_NAMES, result["boa_add_offsets"]):
                row[f"boa_add_offset_{band.lower()}_dn"] = offset
                row[f"asset_{band.lower()}_url"] = token_free_url(item, band)
            row["asset_scl_url"] = token_free_url(item, "SCL")
            rows.append(row)
    return pd.DataFrame(rows)


def dictionary_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(table: str, column: str, definition: str, data_type: str, unit: str = "", missing: str = "Blank means unavailable or not applicable; never substitute zero.") -> None:
        rows.append(
            {
                "table": table,
                "column": column,
                "definition": definition,
                "data_type": data_type,
                "unit": unit,
                "missing_value_policy": missing,
            }
        )

    feature_table = FEATURE_PATH.name
    core = [
        ("record_id", "Stable KHANAN Sentinel-2 surface-context record identifier.", "string", ""),
        ("h3_r6", "H3 resolution-6 cell used as the one-to-one join key to the national grid.", "string", ""),
        ("latitude", "WGS84 latitude of the H3 resolution-6 cell centroid.", "number", "decimal degrees"),
        ("longitude", "WGS84 longitude of the H3 resolution-6 cell centroid.", "number", "decimal degrees"),
        ("coordinate_reference_system", "Coordinate reference system for latitude and longitude.", "string", ""),
        ("grid_area_km2", "Spherical area represented by the H3 resolution-6 cell.", "number", "square kilometres"),
        ("source_reference_period_start", "First date included in either fixed 2025 seasonal window.", "date", "ISO 8601 date"),
        ("source_reference_period_end", "Last date included in either fixed 2025 seasonal window.", "date", "ISO 8601 date"),
        ("season_windows_json", "JSON object defining the two fixed seasonal acquisition windows.", "JSON object", ""),
        ("sample_design", "Deterministic within-cell sampling design.", "string", ""),
        ("sample_points_per_cell_per_season", "Number of H3 r8 child-centroid samples requested per H3 r6 cell in each season.", "integer", "sample points"),
        ("target_reflectance_overview_gsd_m", "Approximate output pixel size used for continuous reflectance COG reads.", "number", "metres"),
        ("scl_sampling_gsd_m", "Native pixel size used to sample the categorical scene classification layer.", "number", "metres"),
    ]
    for column, definition, data_type, unit in core:
        add(feature_table, column, definition, data_type, unit)
    for prefix, label in [("dry", "dry/pre-monsoon"), ("post", "post-monsoon")]:
        add(feature_table, f"{prefix}_source_scene_ids_json", f"JSON array of selected STAC scene IDs contributing child-centroid samples in the {label} window.", "JSON array")
        count_definitions = {
            "covered": "samples assigned a valid SCL code 1-11",
            "band_valid": "samples with all six reflectance bands available",
            "clear_land": "all-band-valid samples classified as vegetation or not vegetated (SCL 4 or 5)",
            "bare": "all-band-valid samples classified as not vegetated (SCL 5)",
            "vegetation": "samples classified as vegetation (SCL 4)",
            "water": "samples classified as water (SCL 6)",
            "cloud_or_shadow": "samples classified as cast/cloud shadow, cloud or cirrus (SCL 2, 3, 8, 9 or 10)",
            "snow_or_ice": "samples classified as snow or ice (SCL 11)",
            "unclassified": "samples classified as unclassified (SCL 7)",
            "invalid_or_uncovered": "samples with no selected observation or a code outside the valid SCL 1-11 domain",
        }
        for name, definition in count_definitions.items():
            add(feature_table, f"{prefix}_{name}_sample_count", f"Number of {definition} in the {label} window.", "integer", "sample points")
        for name in ["covered", "clear_land", "bare"]:
            add(feature_table, f"{prefix}_{name}_sample_fraction", f"Fraction of 49 requested samples that are {count_definitions[name]} in the {label} window.", "number", "proportion 0-1")
        for band in BAND_NAMES:
            add(feature_table, f"{prefix}_clear_land_{band.lower()}_reflectance_median", f"Median BOA reflectance for {band} across all-band-valid SCL 4/5 samples in the {label} window.", "number", "unitless reflectance")
        index_definitions = {
            "ndvi": "normalized difference vegetation index (B08-B04)/(B08+B04)",
            "ndmi": "normalized difference moisture index (B08-B11)/(B08+B11)",
            "mndwi": "modified normalized difference water index (B03-B11)/(B03+B11)",
            "bsi": "bare soil index ((B11+B04)-(B08+B02))/((B11+B04)+(B08+B02))",
            "ndti": "normalized difference tillage/SWIR index (B11-B12)/(B11+B12)",
        }
        for name, definition in index_definitions.items():
            add(feature_table, f"{prefix}_clear_land_{name}_median", f"Median {definition} across positive-reflectance SCL 4/5 samples in the {label} window.", "number", "unitless index")
    for column, definition in [
        ("annual_clear_land_sample_count", "Total all-band-valid SCL 4/5 samples across both seasonal windows."),
        ("annual_bare_sample_count", "Total all-band-valid SCL 5 samples across both seasonal windows."),
    ]:
        add(feature_table, column, definition, "integer", "sample points")
    for column, definition in [
        ("annual_clear_land_sample_fraction", "Fraction of 98 requested two-season samples that are all-band-valid SCL 4/5 clear land."),
        ("annual_bare_sample_fraction", "Fraction of 98 requested two-season samples that are all-band-valid SCL 5 not-vegetated surface."),
    ]:
        add(feature_table, column, definition, "number", "proportion 0-1")
    for band in BAND_NAMES:
        add(feature_table, f"annual_bare_{band.lower()}_reflectance_median", f"Median BOA reflectance for {band} across two-season all-band-valid SCL 5 samples.", "number", "unitless reflectance")
    annual_indices = {
        "ndvi": "normalized difference vegetation index",
        "ndmi": "normalized difference moisture index",
        "mndwi": "modified normalized difference water index",
        "bsi": "bare soil index",
        "ndti": "normalized difference tillage/SWIR index",
        "red_blue_ratio": "exploratory B04/B02 red-to-blue ratio",
        "swir1_swir2_ratio": "exploratory B11/B12 SWIR1-to-SWIR2 ratio",
    }
    for name, label in annual_indices.items():
        add(feature_table, f"annual_bare_{name}_median", f"Median {label} across two-season positive-reflectance SCL 5 samples; broad and non-specific, not a mineral identification.", "number", "unitless index or ratio")
    add(feature_table, "bare_surface_quality_status", "Rule-based support class based on the count and seasonal balance of bare-surface samples.", "string")
    add(feature_table, "spectral_proxy_interpretation", "Mandatory interpretation code stating that the layer is surface context, not mineral detection.", "string")
    add(feature_table, "feature_version", "Version of the Sentinel-2 extraction and aggregation contract.", "string")
    add(feature_table, "model_use_status", "Mandatory status excluding this feature family from v0.6 production scoring.", "string")
    add(feature_table, "source_dataset_ids_json", "JSON array of source-registry identifiers.", "JSON array")
    add(feature_table, "data_quality_flags_json", "JSON array of explicit cell-level coverage, cloud and bare-support flags.", "JSON array", "", "An empty JSON array means no enumerated flag fired; it does not prove accuracy or mineral presence.")

    manifest_table = SCENE_MANIFEST_PATH.name
    manifest_columns = [
        ("season_id", "Fixed seasonal selection-window identifier.", "string", ""),
        ("season_start", "Inclusive start date of the fixed seasonal window.", "date", "ISO 8601 date"),
        ("season_end", "Inclusive end date of the fixed seasonal window.", "date", "ISO 8601 date"),
        ("scene_item_id", "Microsoft Planetary Computer STAC item ID for the selected Sentinel-2 L2A scene.", "string", ""),
        ("mgrs_tile", "Sentinel-2 Military Grid Reference System tile identifier.", "string", ""),
        ("acquisition_datetime_utc", "Source sensing datetime in UTC.", "datetime", "ISO 8601 UTC"),
        ("platform", "Sentinel-2 platform reported in STAC metadata.", "string", ""),
        ("constellation", "Constellation reported in STAC metadata.", "string", ""),
        ("instrument", "JSON array of instruments reported in STAC metadata.", "JSON array", ""),
        ("processing_baseline", "Sentinel-2 processing baseline reported by the source item.", "string", ""),
        ("relative_orbit", "Relative orbit number reported by the source item.", "integer", "orbit"),
        ("orbit_state", "Orbit direction reported by the source item.", "string", ""),
    ]
    for column, definition, data_type, unit in manifest_columns:
        add(manifest_table, column, definition, data_type, unit)
    for column, label in [
        ("cloud_cover_pct", "cloud cover"),
        ("cloud_shadow_pct", "cloud shadow"),
        ("snow_ice_pct", "snow or ice"),
        ("vegetation_pct", "vegetation"),
        ("not_vegetated_pct", "not-vegetated surface"),
        ("water_pct", "water"),
        ("nodata_pixel_pct", "no-data pixels"),
        ("degraded_msi_data_pct", "degraded MSI data"),
    ]:
        add(manifest_table, column, f"Tile-level source percentage for {label} used as selection or audit context.", "number", "percent")
    add(manifest_table, "selection_penalty", "Computed tile-scene selection penalty; lower is preferred.", "number", "penalty units")
    add(manifest_table, "selection_rule", "Deterministic formula, filters and tie-breakers used to choose the scene.", "string")
    add(manifest_table, "proj_epsg", "EPSG identifier of the source tile raster CRS.", "integer", "EPSG code")
    add(manifest_table, "product_uri", "Original Sentinel-2 SAFE product URI reported in STAC metadata.", "string")
    add(manifest_table, "source_item_url", "Token-free STAC item URL.", "URL")
    add(manifest_table, "product_metadata_url", "Token-free product metadata asset URL.", "URL")
    add(manifest_table, "boa_quantification_value", "Per-product BOA quantification divisor parsed from source XML.", "number", "DN per reflectance unit")
    add(manifest_table, "product_metadata_sha256", "SHA-256 of the retrieved product metadata XML bytes.", "string", "hex digest")
    add(manifest_table, "native_scl_code_min", "Minimum code observed in the native 20 m SCL COG.", "integer", "SCL code")
    add(manifest_table, "native_scl_code_max", "Maximum code observed in the native 20 m SCL COG.", "integer", "SCL code")
    add(manifest_table, "sample_point_candidates_in_tile", "Number of national child-centroid sample points falling inside the source raster rectangle before overlap arbitration.", "integer", "sample points")
    add(manifest_table, "india_grid_centroids_in_item_footprint", "Number of KHANAN H3 r6 centroids inside the selected source item footprint; maximized before the spectral-quality penalty is minimized.", "integer", "H3 r6 centroids")
    add(manifest_table, "target_reflectance_overview_gsd_m", "Approximate pixel size requested from continuous reflectance COGs.", "number", "metres")
    add(manifest_table, "scl_sampling_gsd_m", "Native SCL pixel size used for categorical sampling.", "number", "metres")
    add(manifest_table, "source_dataset_id", "Source-registry identifier.", "string")
    add(manifest_table, "model_use_status", "Mandatory status excluding this scene family from v0.6 production scoring.", "string")
    for band in BAND_NAMES:
        add(manifest_table, f"boa_add_offset_{band.lower()}_dn", f"BOA additive offset for {band} parsed from the product metadata XML and applied before division.", "number", "digital number")
        add(manifest_table, f"asset_{band.lower()}_url", f"Token-free COG URL for {band}.", "URL")
    add(manifest_table, "asset_scl_url", "Token-free native scene-classification COG URL.", "URL")
    return rows


def upsert_source_registry() -> None:
    frame = pd.read_csv(SOURCE_REGISTRY_PATH, dtype=str, keep_default_na=False)
    frame = frame[frame["source_id"] != SOURCE_ID]
    frame = pd.concat([frame, pd.DataFrame([source_row()])], ignore_index=True)
    frame.to_csv(SOURCE_REGISTRY_PATH, index=False, lineterminator="\n")


def upsert_data_dictionary() -> None:
    frame = pd.read_csv(DATA_DICTIONARY_PATH, dtype=str, keep_default_na=False)
    tables = {FEATURE_PATH.name, SCENE_MANIFEST_PATH.name}
    frame = frame[~frame["table"].isin(tables)]
    frame = pd.concat([frame, pd.DataFrame(dictionary_rows())], ignore_index=True)
    frame.to_csv(DATA_DICTIONARY_PATH, index=False, lineterminator="\n")


def finite_range(frame: pd.DataFrame, columns: Iterable[str]) -> tuple[float | None, float | None]:
    values = frame[list(columns)].to_numpy(dtype=float).ravel()
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return None, None
    return float(values.min()), float(values.max())


def validate_outputs(
    feature: pd.DataFrame,
    manifest: pd.DataFrame,
    grid_sha_before: str,
    candidate_sha_before: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed, "expected": expected})

    season_counts = manifest.groupby("season_id").size().to_dict()
    tile_counts = manifest.groupby("season_id")["mgrs_tile"].nunique().to_dict()
    dry_tiles = set(manifest.loc[manifest["season_id"] == "dry_pre_monsoon_2025", "mgrs_tile"])
    post_tiles = set(manifest.loc[manifest["season_id"] == "post_monsoon_2025", "mgrs_tile"])
    count_columns = [column for column in feature if column.endswith("_sample_count") and column.startswith(("dry_", "post_"))]
    normalized_columns = [column for column in feature if any(token in column for token in ["_ndvi_", "_ndmi_", "_mndwi_", "_bsi_", "_ndti_"])]
    reflectance_columns = [column for column in feature if column.endswith("_reflectance_median")]
    normalized_min, normalized_max = finite_range(feature, normalized_columns)
    reflectance_min, reflectance_max = finite_range(feature, reflectance_columns)
    expected_scl_total = SAMPLES_PER_CELL_PER_SEASON
    dry_partition = (
        feature["dry_vegetation_sample_count"]
        + feature["dry_bare_sample_count"]
        + feature["dry_water_sample_count"]
        + feature["dry_cloud_or_shadow_sample_count"]
        + feature["dry_snow_or_ice_sample_count"]
        + feature["dry_unclassified_sample_count"]
        + feature["dry_invalid_or_uncovered_sample_count"]
        + (feature["dry_covered_sample_count"] - (
            feature["dry_vegetation_sample_count"]
            + feature["dry_bare_sample_count"]
            + feature["dry_water_sample_count"]
            + feature["dry_cloud_or_shadow_sample_count"]
            + feature["dry_snow_or_ice_sample_count"]
            + feature["dry_unclassified_sample_count"]
        ))
    )
    post_partition = (
        feature["post_vegetation_sample_count"]
        + feature["post_bare_sample_count"]
        + feature["post_water_sample_count"]
        + feature["post_cloud_or_shadow_sample_count"]
        + feature["post_snow_or_ice_sample_count"]
        + feature["post_unclassified_sample_count"]
        + feature["post_invalid_or_uncovered_sample_count"]
        + (feature["post_covered_sample_count"] - (
            feature["post_vegetation_sample_count"]
            + feature["post_bare_sample_count"]
            + feature["post_water_sample_count"]
            + feature["post_cloud_or_shadow_sample_count"]
            + feature["post_snow_or_ice_sample_count"]
            + feature["post_unclassified_sample_count"]
        ))
    )
    grid_sha_after = sha256(GRID_PATH)
    candidate_sha_after = sha256(CANDIDATE_PATH)
    token_columns = [column for column in manifest if column.endswith("_url")]

    check("feature_rows", len(feature) == 88857, len(feature), 88857)
    check("unique_h3_cells", feature["h3_r6"].nunique() == len(feature), feature["h3_r6"].nunique(), len(feature))
    check("unique_record_ids", feature["record_id"].nunique() == len(feature), feature["record_id"].nunique(), len(feature))
    check("two_seasons", set(season_counts) == set(SEASONS), season_counts, list(SEASONS))
    check("matching_season_tile_sets", dry_tiles == post_tiles, len(dry_tiles.symmetric_difference(post_tiles)), 0)
    check("unique_tile_per_season", season_counts == tile_counts, {"rows": season_counts, "tiles": tile_counts}, "equal within each season")
    check("substantial_india_tile_coverage", min(tile_counts.values()) >= 430, tile_counts, ">=430 per season")
    check("scene_ids_unique", manifest["scene_item_id"].nunique() == len(manifest), manifest["scene_item_id"].nunique(), len(manifest))
    check("scene_dates_inside_windows", all(
        SEASONS[row.season_id][0] <= str(row.acquisition_datetime_utc)[:10] <= SEASONS[row.season_id][1]
        for row in manifest.itertuples(index=False)
    ), True, True)
    check("catalog_filter_cloud", float(manifest["cloud_cover_pct"].max()) < CATALOG_CLOUD_CEILING_PCT, float(manifest["cloud_cover_pct"].max()), f"<{CATALOG_CLOUD_CEILING_PCT}")
    check("catalog_filter_nodata", float(manifest["nodata_pixel_pct"].max()) < CATALOG_NODATA_CEILING_PCT, float(manifest["nodata_pixel_pct"].max()), f"<{CATALOG_NODATA_CEILING_PCT}")
    check("quantification_values_positive", bool((manifest["boa_quantification_value"] > 0).all()), sorted(manifest["boa_quantification_value"].unique().tolist()), ">0")
    check("native_scl_codes_valid", bool((manifest["native_scl_code_min"] >= 0).all() and (manifest["native_scl_code_max"] <= 11).all()), [int(manifest["native_scl_code_min"].min()), int(manifest["native_scl_code_max"].max())], "0..11")
    check("no_transient_sas_tokens", not manifest[token_columns].astype(str).apply(lambda col: col.str.contains(r"[?&](?:sig|se|st)=", regex=True).any()).any(), False, False)
    check("sample_counts_bounded", bool(((feature[count_columns] >= 0) & (feature[count_columns] <= SAMPLES_PER_CELL_PER_SEASON)).all().all()), [int(feature[count_columns].min().min()), int(feature[count_columns].max().max())], f"0..{SAMPLES_PER_CELL_PER_SEASON}")
    check("dry_scl_partition", bool((dry_partition == expected_scl_total).all()), int((dry_partition != expected_scl_total).sum()), 0)
    check("post_scl_partition", bool((post_partition == expected_scl_total).all()), int((post_partition != expected_scl_total).sum()), 0)
    check("annual_counts_reconcile", bool((feature["annual_bare_sample_count"] == feature["dry_bare_sample_count"] + feature["post_bare_sample_count"]).all()), int((feature["annual_bare_sample_count"] != feature["dry_bare_sample_count"] + feature["post_bare_sample_count"]).sum()), 0)
    check("normalized_index_range", normalized_min is not None and normalized_min >= -1.0001 and normalized_max is not None and normalized_max <= 1.0001, [normalized_min, normalized_max], "[-1,1]")
    check("reflectance_physical_screen", reflectance_min is not None and reflectance_min >= -0.1 and reflectance_max is not None and reflectance_max <= 2.0, [reflectance_min, reflectance_max], "[-0.1,2.0]")
    check("mandatory_model_exclusion", feature["model_use_status"].eq(MODEL_USE_STATUS).all() and manifest["model_use_status"].eq(MODEL_USE_STATUS).all(), True, True)
    check("mandatory_interpretation", feature["spectral_proxy_interpretation"].eq(INTERPRETATION_CODE).all(), True, True)
    check("grid_table_sha256_unchanged", grid_sha_before == grid_sha_after, grid_sha_after, grid_sha_before)
    check("candidate_table_sha256_unchanged", candidate_sha_before == candidate_sha_after, candidate_sha_after, candidate_sha_before)
    check("dictionary_complete", set(feature.columns).issubset({row["column"] for row in dictionary_rows() if row["table"] == FEATURE_PATH.name}) and set(manifest.columns).issubset({row["column"] for row in dictionary_rows() if row["table"] == SCENE_MANIFEST_PATH.name}), True, True)

    failed = [row for row in checks if not row["passed"]]
    validation = {
        "release_version": RELEASE_VERSION,
        "geospatial_feature_version": GEOSPATIAL_FEATURE_VERSION,
        "feature_version": FEATURE_VERSION,
        "source_dataset_id": SOURCE_ID,
        "source_accessed_date": SOURCE_ACCESSED_DATE,
        "stac_collection": STAC_COLLECTION,
        "stac_collection_url": STAC_COLLECTION_URL,
        "catalog_bbox": list(CATALOG_BBOX),
        "season_windows": {key: {"start": value[0], "end": value[1]} for key, value in SEASONS.items()},
        "selection_rule": SELECTION_RULE,
        "sampling_design": {
            "parent_h3_resolution": PARENT_H3_RESOLUTION,
            "sample_h3_resolution": SAMPLE_H3_RESOLUTION,
            "sample_points_per_cell_per_season": SAMPLES_PER_CELL_PER_SEASON,
            "target_reflectance_overview_gsd_m": TARGET_REFLECTANCE_GSD_M,
            "scl_sampling_gsd_m": SCL_NATIVE_GSD_M,
        },
        "feature_rows": len(feature),
        "scene_manifest_rows": len(manifest),
        "scene_rows_by_season": season_counts,
        "unique_mgrs_tiles_per_season": tile_counts,
        "selected_scene_cloud_cover_pct": {
            "minimum": float(manifest["cloud_cover_pct"].min()),
            "median": float(manifest["cloud_cover_pct"].median()),
            "maximum": float(manifest["cloud_cover_pct"].max()),
        },
        "cell_coverage": {
            "dry_complete_49_of_49_rate": float((feature["dry_covered_sample_count"] == 49).mean()),
            "post_complete_49_of_49_rate": float((feature["post_covered_sample_count"] == 49).mean()),
            "any_clear_land_rate": float((feature["annual_clear_land_sample_count"] > 0).mean()),
            "two_season_bare_support_rate": float(feature["bare_surface_quality_status"].eq("two_season_bare_support").mean()),
            "one_season_dominant_bare_support_rate": float(feature["bare_surface_quality_status"].eq("one_season_dominant_bare_support").mean()),
            "insufficient_bare_support_rate": float(feature["bare_surface_quality_status"].eq("insufficient_bare_support").mean()),
        },
        "reflectance_range": [reflectance_min, reflectance_max],
        "normalized_index_range": [normalized_min, normalized_max],
        "candidate_scores_recomputed": False,
        "production_scoring_changed": False,
        "model_use_status": MODEL_USE_STATUS,
        "interpretation": (
            "Sentinel-2 summaries are surface-context and confounder-control features. They do not identify a "
            "specific mineral, subsurface deposit, grade, resource, reserve or discovery."
        ),
        "checks": checks,
        "checks_pass": not failed,
    }
    if failed:
        raise RuntimeError(f"Sentinel-2 validation failed: {[row['name'] for row in failed]}")
    return validation


def update_validation_report(validation: dict[str, Any]) -> None:
    report = json.loads(VALIDATION_REPORT_PATH.read_text(encoding="utf-8"))
    report["development_release_version"] = RELEASE_VERSION
    report["sentinel2_surface_context"] = {
        "feature_version": validation["feature_version"],
        "feature_rows": validation["feature_rows"],
        "scene_manifest_rows": validation["scene_manifest_rows"],
        "scene_rows_by_season": validation["scene_rows_by_season"],
        "unique_mgrs_tiles_per_season": validation["unique_mgrs_tiles_per_season"],
        "selected_scene_cloud_cover_pct": validation["selected_scene_cloud_cover_pct"],
        "cell_coverage": validation["cell_coverage"],
        "candidate_scores_recomputed": False,
        "production_scoring_changed": False,
        "model_use_status": MODEL_USE_STATUS,
        "checks_pass": validation["checks_pass"],
    }
    atomic_json(VALIDATION_REPORT_PATH, report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-catalog", action="store_true", help="Re-query and reselect fixed-window STAC items")
    parser.add_argument("--refresh-assets", action="store_true", help="Re-read scene assets instead of using verified local sample caches")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent scene readers (default: 6)")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 12:
        raise ValueError("--workers must be between 1 and 12")

    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    SAMPLE_CACHE.mkdir(parents=True, exist_ok=True)
    grid_sha_before = sha256(GRID_PATH)
    candidate_sha_before = sha256(CANDIDATE_PATH)
    samples = read_grid_samples()
    selected = select_items(samples.grid, args.refresh_catalog)
    observations: dict[str, SeasonObservation] = {}
    scene_results: dict[str, list[dict[str, Any]]] = {}
    for season_id, items in selected.items():
        observations[season_id], scene_results[season_id] = process_season(
            season_id,
            items,
            samples,
            workers=args.workers,
            refresh_assets=args.refresh_assets,
        )

    feature = build_feature_table(samples, selected, observations)
    manifest = build_scene_manifest(selected, scene_results)
    feature.to_csv(FEATURE_PATH, index=False, float_format="%.6f", na_rep="", lineterminator="\n")
    manifest.to_csv(SCENE_MANIFEST_PATH, index=False, float_format="%.6f", na_rep="", lineterminator="\n")
    upsert_source_registry()
    upsert_data_dictionary()
    validation = validate_outputs(feature, manifest, grid_sha_before, candidate_sha_before)
    atomic_json(VALIDATION_PATH, validation)
    update_validation_report(validation)
    print(
        json.dumps(
            {
                "feature": str(FEATURE_PATH),
                "feature_rows": len(feature),
                "scene_manifest": str(SCENE_MANIFEST_PATH),
                "scene_rows": len(manifest),
                "validation": str(VALIDATION_PATH),
                "checks": len(validation["checks"]),
                "checks_pass": validation["checks_pass"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
