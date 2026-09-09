#!/usr/bin/env python3
"""Build H3-resolution magnetic features from NOAA/NCEI EMAG2v3.

The output samples the globally consistent 4 km upward-continued anomaly grid,
the accompanying error-estimate grid, and the source-code grid. It also adds
the feature columns to the nationwide and candidate CSVs. The existing
prospectivity scores are deliberately unchanged until a separate spatial
ablation demonstrates out-of-region improvement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.transform import rowcol, xy
from rasterio.windows import Window


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RAW = ROOT / "sources" / "raw" / "emag2v3"
RELEASE_VERSION = "v1.0-alpha.5"
GEOSPATIAL_FEATURE_VERSION = "v0.7"
FEATURE_VERSION = "emag2v3-h3-r6-v0.1"

PRODUCT_URL = "https://www.ncei.noaa.gov/products/earth-magnetic-model-anomaly-grid-2"
METADATA_URL = "https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.geophysical_models:EMAG2_V3"
DOI_URL = "https://doi.org/10.7289/V5H70CVX"
BASE_URL = "https://www.ngdc.noaa.gov/geomag/data/EMAG2/"
FILES = {
    "anomaly": ("EMAG2_V3_UpCont_DataTiff.tif", BASE_URL + "EMAG2_V3_UpCont_DataTiff.tif"),
    "error": ("EMAG2_V3_Error_DataTiff.tif", BASE_URL + "EMAG2_V3_Error_DataTiff.tif"),
    "source_code": ("EMAG2_V3_Code.tif", BASE_URL + "EMAG2_V3_Code.tif"),
    "readme": ("EMAG2_readme.txt", BASE_URL + "EMAG2_readme.txt"),
}

FEATURE_TABLE = OUT / "india_emag2v3_magnetic_features_h3_r6.csv"
VALIDATION_PATH = OUT / "emag2v3_magnetic_features_validation.json"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"

SOURCE_ROW = {
    "source_id": "SRC_NOAA_EMAG2V3",
    "publisher": "NOAA National Centers for Environmental Information",
    "title": "EMAG2v3: Earth Magnetic Anomaly Grid, 2-arc-minute resolution",
    "release_or_reference_date": "Version 3 published 2017-05-30; accessed 2026-09-10",
    "url": METADATA_URL,
    "download_url": BASE_URL,
    "license_or_access_note": "NCEI metadata states the NOAA-produced dataset is not subject to copyright protection within the United States. Cite Meyer, Saltus and Chulliat (2017), DOI 10.7289/V5H70CVX, and retain NOAA/NCEI attribution and use limitations.",
    "used_for": "Two-arc-minute magnetic anomaly at a consistent 4 km altitude, source error estimate, and source-grid code sampled at H3 resolution-6 centroids, with local 3x3 source-pixel summaries.",
    "limitations": "A global compilation of heterogeneous satellite, ship, airborne and precompiled sources. Resolution and error vary; values are regional geophysical context, not deposit evidence, grade, depth or economic viability. The GeoTIFF lacks embedded CRS metadata, so EPSG:4326 is assigned from NCEI ISO metadata.",
}

SIGNAL_COLUMNS = [
    "emag2_upcont_anomaly_nt",
    "emag2_upcont_abs_anomaly_nt",
    "emag2_upcont_local_mean_nt_3x3",
    "emag2_upcont_local_std_nt_3x3",
    "emag2_upcont_local_range_nt_3x3",
    "emag2_anomaly_percentile_india_h3",
    "emag2_anomaly_robust_z_india_h3",
    "emag2_abs_robust_z_india_h3",
    "emag2_error_estimate_nt",
    "emag2_error_raw_value",
    "emag2_abs_signal_to_error_ratio",
    "emag2_source_code",
    "emag2_source_code_label",
    "emag2_source_native_india_grid",
    "emag2_source_ambiguous_or_no_data",
    "emag2_source_grid_longitude",
    "emag2_source_grid_latitude",
    "emag2_source_grid_distance_km",
    "emag2_source_resolution_arc_minutes",
    "emag2_observation_elevation_basis",
    "emag2_source_crs",
    "emag2_source_crs_assignment_basis",
    "emag2_uncertainty_interpretation",
    "emag2_feature_version",
    "emag2_model_use_status",
    "emag2_data_quality_flags_json",
    "geophysical_profile_json",
    "geophysics_source_dataset_ids_json",
]

FIELD_DEFINITIONS = {
    "record_id": ("Stable grid-feature record identifier.", "text", None),
    "h3_r6": ("H3 resolution-6 cell identifier.", "text", None),
    "latitude": ("WGS84 H3 cell-centroid latitude.", "number", "decimal degrees"),
    "longitude": ("WGS84 H3 cell-centroid longitude.", "number", "decimal degrees"),
    "emag2_upcont_anomaly_nt": ("Nearest-pixel EMAG2v3 magnetic anomaly at a consistent 4 km altitude.", "number", "nT"),
    "emag2_upcont_abs_anomaly_nt": ("Absolute value of the nearest-pixel upward-continued magnetic anomaly.", "number", "nT"),
    "emag2_upcont_local_mean_nt_3x3": ("Mean valid anomaly in the 3x3 source-pixel neighbourhood around the matched pixel.", "number", "nT"),
    "emag2_upcont_local_std_nt_3x3": ("Population standard deviation of valid anomalies in the 3x3 source-pixel neighbourhood.", "number", "nT"),
    "emag2_upcont_local_range_nt_3x3": ("Maximum minus minimum valid anomaly in the 3x3 source-pixel neighbourhood.", "number", "nT"),
    "emag2_anomaly_percentile_india_h3": ("Empirical percentile of the signed anomaly across valid India H3 centroids in this release.", "number", "0-1 percentile"),
    "emag2_anomaly_robust_z_india_h3": ("Signed anomaly centered on the India H3 median and divided by 1.4826 times the median absolute deviation.", "number", "robust z-score"),
    "emag2_abs_robust_z_india_h3": ("Absolute value of the India-relative robust anomaly z-score.", "number", "robust z-score"),
    "emag2_error_estimate_nt": ("NCEI error estimate when the source value is non-negative and finite.", "number", "nT"),
    "emag2_error_raw_value": ("Raw error-raster value, preserving negative ambiguity and no-data codes.", "number", "nT or source sentinel"),
    "emag2_abs_signal_to_error_ratio": ("Absolute anomaly divided by positive source error estimate; unavailable for zero, negative or missing error.", "number", "ratio"),
    "emag2_source_code": ("Nearest-pixel EMAG2v3 primary data-source code.", "integer", None),
    "emag2_source_code_label": ("Source-region label parsed from the official EMAG2 format file.", "text", None),
    "emag2_source_native_india_grid": ("Whether the source code is 020 India or 021 East India.", "boolean", None),
    "emag2_source_ambiguous_or_no_data": ("Whether the source code is 888 Ambiguous or 999 No data.", "boolean", None),
    "emag2_source_grid_longitude": ("Longitude of the matched EMAG2v3 pixel centre.", "number", "decimal degrees"),
    "emag2_source_grid_latitude": ("Latitude of the matched EMAG2v3 pixel centre.", "number", "decimal degrees"),
    "emag2_source_grid_distance_km": ("Great-circle distance from the H3 centroid to the matched source-pixel centre.", "number", "km"),
    "emag2_source_resolution_arc_minutes": ("Nominal EMAG2v3 grid resolution.", "number", "arc-minutes"),
    "emag2_observation_elevation_basis": ("Elevation basis stated for the selected magnetic-anomaly product.", "category", None),
    "emag2_source_crs": ("Coordinate reference system assigned to source longitude and latitude.", "text", None),
    "emag2_source_crs_assignment_basis": ("Reason for assigning a CRS when the GeoTIFF has no embedded CRS tag.", "text", None),
    "emag2_uncertainty_interpretation": ("Interpretation limit for the source error estimate.", "text", None),
    "emag2_feature_version": ("Version of the KHANAN EMAG2 feature transformation.", "text", None),
    "emag2_model_use_status": ("Whether these features affect the published prospectivity ranking.", "category", None),
    "emag2_data_quality_flags_json": ("JSON array of record-level source and measurement caveats.", "JSON array", None),
    "geophysical_profile_json": ("JSON object containing the EMAG2 signal, uncertainty, source code and model-use state.", "JSON object", None),
    "geophysics_source_dataset_ids_json": ("JSON array of source-registry identifiers for geophysical features.", "JSON array", None),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(session: requests.Session, path: Path, url: str, refresh: bool) -> dict[str, Any]:
    head = session.head(url, timeout=60, allow_redirects=True)
    head.raise_for_status()
    expected_size = int(head.headers.get("Content-Length", "0") or 0)
    if refresh or not path.exists() or (expected_size and path.stat().st_size != expected_size):
        temp = path.with_suffix(path.suffix + ".part")
        with session.get(url, timeout=300, stream=True) as response:
            response.raise_for_status()
            with temp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if expected_size and temp.stat().st_size != expected_size:
            raise RuntimeError(f"download size mismatch for {url}")
        temp.replace(path)
    return {
        "url": url,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "last_modified": head.headers.get("Last-Modified"),
        "etag": head.headers.get("ETag"),
    }


def parse_source_codes(path: Path) -> dict[int, str]:
    codes: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^(\d{3})\s+(.+?)\s*$", line)
        if match:
            codes[int(match.group(1))] = match.group(2)
    required = {20: "India", 21: "East India", 888: "Ambiguous", 999: "No data"}
    for code, label in required.items():
        if codes.get(code) != label:
            raise RuntimeError(f"unexpected EMAG2 source-code mapping for {code}: {codes.get(code)!r}")
    return codes


def raster_metadata(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        return {
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0],
            "embedded_crs": str(dataset.crs) if dataset.crs else None,
            "nodata": dataset.nodata,
            "transform": list(dataset.transform)[:6],
            "bounds": list(dataset.bounds),
        }


def haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    radius_km = 6371.0088
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius_km * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def read_window_values(path: Path, rows: np.ndarray, cols: np.ndarray, padding: int = 1) -> tuple[np.ndarray, Window, Any, float | None]:
    with rasterio.open(path) as dataset:
        min_row = max(0, int(rows.min()) - padding)
        max_row = min(dataset.height - 1, int(rows.max()) + padding)
        min_col = max(0, int(cols.min()) - padding)
        max_col = min(dataset.width - 1, int(cols.max()) + padding)
        window = Window(min_col, min_row, max_col - min_col + 1, max_row - min_row + 1)
        values = dataset.read(1, window=window)
        return values, window, dataset.transform, dataset.nodata


def clean_anomaly(values: np.ndarray, nodata: float | None) -> np.ndarray:
    result = values.astype("float64", copy=True)
    invalid = ~np.isfinite(result) | (result >= 90_000) | (result <= -1e30)
    if nodata is not None:
        invalid |= np.isclose(result, nodata)
    result[invalid] = np.nan
    return result


def format_float(value: Any, digits: int = 6) -> Any:
    if value is None or (isinstance(value, (float, np.floating)) and not math.isfinite(float(value))):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return value


def build_features(grid: pd.DataFrame, paths: dict[str, Path], source_codes: dict[int, str]) -> pd.DataFrame:
    lons = grid["longitude"].to_numpy(dtype="float64")
    lats = grid["latitude"].to_numpy(dtype="float64")
    with rasterio.open(paths["anomaly"]) as dataset:
        rows, cols = rowcol(dataset.transform, lons, lats)
    rows = np.asarray(rows, dtype="int64")
    cols = np.asarray(cols, dtype="int64")

    anomaly_window, window, transform, anomaly_nodata = read_window_values(paths["anomaly"], rows, cols, padding=1)
    error_window, error_window_def, error_transform, error_nodata = read_window_values(paths["error"], rows, cols, padding=1)
    code_window, code_window_def, code_transform, code_nodata = read_window_values(paths["source_code"], rows, cols, padding=1)
    transforms_aligned = np.allclose(
        np.asarray(transform)[:6], np.asarray(error_transform)[:6], rtol=0, atol=1e-4
    ) and np.allclose(
        np.asarray(transform)[:6], np.asarray(code_transform)[:6], rtol=0, atol=1e-4
    )
    if window != error_window_def or window != code_window_def or not transforms_aligned:
        raise RuntimeError("EMAG2 anomaly, error and source-code rasters are not aligned")

    local_rows = rows - int(window.row_off)
    local_cols = cols - int(window.col_off)
    anomaly_clean = clean_anomaly(anomaly_window, anomaly_nodata)
    anomaly = anomaly_clean[local_rows, local_cols]
    error_raw = error_window[local_rows, local_cols].astype("float64")
    error_invalid = ~np.isfinite(error_raw) | (error_raw < 0) | (error_raw <= -1e30)
    if error_nodata is not None:
        error_invalid |= np.isclose(error_raw, error_nodata)
    error = error_raw.copy()
    error[error_invalid] = np.nan
    source_code_raw = code_window[local_rows, local_cols].astype("float64")
    source_code_invalid = ~np.isfinite(source_code_raw) | (source_code_raw <= -1e30)
    if code_nodata is not None:
        source_code_invalid |= np.isclose(source_code_raw, code_nodata)
    source_code = np.where(source_code_invalid, -1, np.rint(source_code_raw)).astype("int64")

    neighbours = np.stack(
        [anomaly_clean[local_rows + dr, local_cols + dc] for dr in (-1, 0, 1) for dc in (-1, 0, 1)],
        axis=0,
    )
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", category=RuntimeWarning)
        local_mean = np.nanmean(neighbours, axis=0)
        local_std = np.nanstd(neighbours, axis=0)
        local_range = np.nanmax(neighbours, axis=0) - np.nanmin(neighbours, axis=0)

    src_lons, src_lats = xy(transform, rows, cols, offset="center")
    src_lons = np.asarray(src_lons, dtype="float64")
    src_lats = np.asarray(src_lats, dtype="float64")
    distance = haversine_km(lats, lons, src_lats, src_lons)

    valid = np.isfinite(anomaly)
    valid_values = anomaly[valid]
    median = float(np.median(valid_values))
    mad = float(np.median(np.abs(valid_values - median)))
    robust_scale = 1.4826 * mad
    robust_z = (anomaly - median) / robust_scale if robust_scale > 0 else np.full_like(anomaly, np.nan)
    percentile = pd.Series(anomaly).rank(method="average", pct=True).to_numpy(dtype="float64")
    signal_error = np.divide(
        np.abs(anomaly),
        error,
        out=np.full_like(anomaly, np.nan),
        where=np.isfinite(error) & (error > 0),
    )
    labels = [source_codes.get(int(code), "Unknown source code") if code >= 0 else "Missing source code" for code in source_code]
    native_india = np.isin(source_code, [20, 21])
    ambiguous = np.isin(source_code, [888, 999]) | source_code_invalid

    flags = []
    profiles = []
    source_ids = json.dumps(["SRC_NOAA_EMAG2V3"], separators=(",", ":"))
    for index in range(len(grid)):
        record_flags = []
        if not valid[index]:
            record_flags.append("emag2_anomaly_missing_or_source_nodata")
        if error_invalid[index]:
            record_flags.append("emag2_error_missing_or_negative_source_flag")
        if ambiguous[index]:
            record_flags.append("emag2_source_ambiguous_or_no_data")
        if not native_india[index] and not ambiguous[index]:
            record_flags.append("emag2_primary_source_grid_not_labelled_india_or_east_india")
        record_flags.append("regional_geophysical_context_not_deposit_evidence")
        record_flags.append("not_used_in_production_candidate_scoring")
        flags.append(json.dumps(record_flags, separators=(",", ":")))
        profiles.append(
            json.dumps(
                {
                    "upward_continued_anomaly_nt": None if not valid[index] else round(float(anomaly[index]), 4),
                    "local_std_nt_3x3": None if not np.isfinite(local_std[index]) else round(float(local_std[index]), 4),
                    "error_estimate_nt": None if not np.isfinite(error[index]) else round(float(error[index]), 4),
                    "source_code": None if source_code[index] < 0 else int(source_code[index]),
                    "source_code_label": labels[index],
                    "model_use_status": "integrated_context_feature_not_used_in_production_candidate_scoring",
                },
                separators=(",", ":"),
            )
        )

    result = grid[["h3_r6", "latitude", "longitude"]].copy()
    result.insert(0, "record_id", "EMAG2-" + result["h3_r6"].astype(str))
    result["emag2_upcont_anomaly_nt"] = anomaly
    result["emag2_upcont_abs_anomaly_nt"] = np.abs(anomaly)
    result["emag2_upcont_local_mean_nt_3x3"] = local_mean
    result["emag2_upcont_local_std_nt_3x3"] = local_std
    result["emag2_upcont_local_range_nt_3x3"] = local_range
    result["emag2_anomaly_percentile_india_h3"] = percentile
    result["emag2_anomaly_robust_z_india_h3"] = robust_z
    result["emag2_abs_robust_z_india_h3"] = np.abs(robust_z)
    result["emag2_error_estimate_nt"] = error
    result["emag2_error_raw_value"] = error_raw
    result["emag2_abs_signal_to_error_ratio"] = signal_error
    result["emag2_source_code"] = pd.array(np.where(source_code >= 0, source_code, None), dtype="Int64")
    result["emag2_source_code_label"] = labels
    result["emag2_source_native_india_grid"] = native_india
    result["emag2_source_ambiguous_or_no_data"] = ambiguous
    result["emag2_source_grid_longitude"] = src_lons
    result["emag2_source_grid_latitude"] = src_lats
    result["emag2_source_grid_distance_km"] = distance
    result["emag2_source_resolution_arc_minutes"] = 2
    result["emag2_observation_elevation_basis"] = "continuous_4_km_altitude_as_described_by_ncei"
    result["emag2_source_crs"] = "EPSG:4326"
    result["emag2_source_crs_assignment_basis"] = "NCEI ISO metadata; source GeoTIFF has no embedded CRS tag"
    result["emag2_uncertainty_interpretation"] = "Source error estimate in nT; not a prediction interval or deposit-confidence measure"
    result["emag2_feature_version"] = FEATURE_VERSION
    result["emag2_model_use_status"] = "integrated_context_feature_not_used_in_production_candidate_scoring"
    result["emag2_data_quality_flags_json"] = flags
    result["geophysical_profile_json"] = profiles
    result["geophysics_source_dataset_ids_json"] = source_ids
    return result


def augment_csv(path: Path, features: pd.DataFrame) -> None:
    feature_values = features.set_index("h3_r6")[SIGNAL_COLUMNS].to_dict(orient="index")
    temp = path.with_suffix(path.suffix + ".emag2.tmp")
    with path.open("r", encoding="utf-8", newline="") as source, temp.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "h3_r6" not in reader.fieldnames:
            raise RuntimeError(f"missing h3_r6 in {path}")
        base_fields = [field for field in reader.fieldnames if field not in SIGNAL_COLUMNS]
        writer = csv.DictWriter(target, fieldnames=base_fields + SIGNAL_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        row_count = 0
        for row in reader:
            values = feature_values.get(row["h3_r6"])
            if values is None:
                raise RuntimeError(f"EMAG2 feature missing for {row['h3_r6']} in {path}")
            output = {field: row.get(field, "") for field in base_fields}
            output.update({key: format_float(value) for key, value in values.items()})
            writer.writerow(output)
            row_count += 1
    if row_count == 0:
        raise RuntimeError(f"no rows written while augmenting {path}")
    temp.replace(path)


def upsert_source_registry() -> None:
    path = OUT / "source_registry.csv"
    existing = pd.read_csv(path, keep_default_na=False)
    retained = existing.loc[existing["source_id"] != SOURCE_ROW["source_id"]].copy()
    pd.concat([retained, pd.DataFrame([SOURCE_ROW])], ignore_index=True).to_csv(path, index=False)


def upsert_dictionary(feature_columns: list[str]) -> None:
    path = OUT / "data_dictionary.csv"
    dictionary = pd.read_csv(path, keep_default_na=False)
    targets = {
        FEATURE_TABLE.name: feature_columns,
        GRID_PATH.name: SIGNAL_COLUMNS,
        CANDIDATE_PATH.name: SIGNAL_COLUMNS,
    }
    masks = [
        (dictionary["table"] == table_name) & dictionary["column"].isin(columns)
        for table_name, columns in targets.items()
    ]
    remove = np.logical_or.reduce(masks) if masks else np.zeros(len(dictionary), dtype=bool)
    retained = dictionary.loc[~remove].copy()
    rows = []
    for table_name, columns in targets.items():
        for column in columns:
            definition, data_type, unit = FIELD_DEFINITIONS[column]
            rows.append(
                {
                    "table": table_name,
                    "column": column,
                    "definition": definition,
                    "data_type": data_type,
                    "unit": unit or "",
                    "missing_value_policy": "Blank means the source value is missing, invalid or not applicable; source zeros are retained as numeric zero.",
                }
            )
    pd.concat([retained, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)


def update_release_validation(validation: dict[str, Any]) -> None:
    path = OUT / "validation_report.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["dataset_release_version"] = GEOSPATIAL_FEATURE_VERSION
    release["emag2v3_geophysics"] = {
        key: validation[key]
        for key in [
            "feature_rows",
            "unique_h3_cells",
            "valid_anomaly_rows",
            "valid_error_rows",
            "missing_anomaly_rows",
            "native_india_source_rows",
            "ambiguous_or_no_data_source_rows",
            "maximum_source_grid_distance_km",
            "candidate_valid_anomaly_rate",
            "candidate_valid_error_rate",
            "candidate_scores_recomputed",
            "checks_pass",
        ]
    }
    path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Redownload official EMAG2 source files")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "KHANAN/1.0 EMAG2 reproducible geophysics build"})
    source_files = {}
    paths: dict[str, Path] = {}
    for key, (filename, url) in FILES.items():
        path = RAW / filename
        paths[key] = path
        source_files[key] = download(session, path, url, args.refresh)

    source_codes = parse_source_codes(paths["readme"])
    metadata = {key: raster_metadata(paths[key]) for key in ["anomaly", "error", "source_code"]}
    grid = pd.read_csv(GRID_PATH, usecols=["h3_r6", "latitude", "longitude"], dtype={"h3_r6": str})
    if len(grid) != grid["h3_r6"].nunique():
        raise RuntimeError("nationwide grid H3 identifiers are not unique")
    features = build_features(grid, paths, source_codes)

    float_columns = [column for column in features.columns if column.startswith("emag2_") and pd.api.types.is_float_dtype(features[column])]
    features.to_csv(FEATURE_TABLE, index=False, float_format="%.6f")
    augment_csv(GRID_PATH, features)
    augment_csv(CANDIDATE_PATH, features)
    upsert_source_registry()
    upsert_dictionary(list(features.columns))

    valid_anomaly = features["emag2_upcont_anomaly_nt"].notna()
    valid_error = features["emag2_error_estimate_nt"].notna()
    missing_anomaly = ~valid_anomaly
    no_data_source = features["emag2_source_code"].eq(999)
    candidate_features = pd.read_csv(
        CANDIDATE_PATH,
        usecols=["h3_r6", "emag2_upcont_anomaly_nt", "emag2_error_estimate_nt"],
    )
    transform_values = [np.asarray(metadata[key]["transform"], dtype="float64") for key in ["anomaly", "error", "source_code"]]
    transform_max_difference = float(
        max(np.max(np.abs(left - right)) for left in transform_values for right in transform_values)
    )
    code_counts = {
        str(int(key)): {"label": source_codes.get(int(key), "Unknown source code"), "rows": int(value)}
        for key, value in features["emag2_source_code"].value_counts(dropna=False).sort_index().items()
        if not pd.isna(key)
    }
    validation = {
        "release_version": RELEASE_VERSION,
        "geospatial_feature_version": GEOSPATIAL_FEATURE_VERSION,
        "feature_version": FEATURE_VERSION,
        "build_date": date.today().isoformat(),
        "source_product_url": PRODUCT_URL,
        "source_metadata_url": METADATA_URL,
        "source_doi": DOI_URL,
        "source_files": source_files,
        "raster_metadata": metadata,
        "feature_rows": int(len(features)),
        "unique_h3_cells": int(features["h3_r6"].nunique()),
        "valid_anomaly_rows": int(valid_anomaly.sum()),
        "valid_anomaly_rate": float(valid_anomaly.mean()),
        "valid_error_rows": int(valid_error.sum()),
        "valid_error_rate": float(valid_error.mean()),
        "missing_anomaly_rows": int(missing_anomaly.sum()),
        "missing_anomaly_rows_with_no_data_source_code": int((missing_anomaly & no_data_source).sum()),
        "native_india_source_rows": int(features["emag2_source_native_india_grid"].sum()),
        "native_india_source_rate": float(features["emag2_source_native_india_grid"].mean()),
        "ambiguous_or_no_data_source_rows": int(features["emag2_source_ambiguous_or_no_data"].sum()),
        "source_code_distribution": code_counts,
        "anomaly_nt_summary": {
            "minimum": float(features.loc[valid_anomaly, "emag2_upcont_anomaly_nt"].min()),
            "median": float(features.loc[valid_anomaly, "emag2_upcont_anomaly_nt"].median()),
            "maximum": float(features.loc[valid_anomaly, "emag2_upcont_anomaly_nt"].max()),
        },
        "error_nt_summary": {
            "minimum": float(features.loc[valid_error, "emag2_error_estimate_nt"].min()),
            "median": float(features.loc[valid_error, "emag2_error_estimate_nt"].median()),
            "maximum": float(features.loc[valid_error, "emag2_error_estimate_nt"].max()),
        },
        "maximum_source_grid_distance_km": float(features["emag2_source_grid_distance_km"].max()),
        "raster_transform_alignment_max_abs_degrees": transform_max_difference,
        "candidate_feature_rows": int(len(candidate_features)),
        "candidate_valid_anomaly_rate": float(candidate_features["emag2_upcont_anomaly_nt"].notna().mean()),
        "candidate_valid_error_rate": float(candidate_features["emag2_error_estimate_nt"].notna().mean()),
        "candidate_scores_recomputed": False,
        "model_use_status": "Integrated into the national and candidate tables as contextual features; admission to scoring requires a separate spatial ablation and leakage audit.",
        "float_columns_written_with_six_decimal_places": float_columns,
    }
    raster_checks = all(
        item["width"] == 10800
        and item["height"] == 5399
        and item["count"] == 1
        and item["dtype"] == "float32"
        and item["embedded_crs"] is None
        for item in metadata.values()
    )
    validation["checks_pass"] = bool(
        validation["feature_rows"] == validation["unique_h3_cells"] == len(grid) == 88_857
        and validation["valid_anomaly_rate"] >= 0.95
        and validation["valid_error_rate"] >= 0.92
        and validation["missing_anomaly_rows"] == validation["missing_anomaly_rows_with_no_data_source_code"]
        and validation["valid_error_rows"] + validation["ambiguous_or_no_data_source_rows"] == len(grid)
        and validation["maximum_source_grid_distance_km"] < 3
        and validation["raster_transform_alignment_max_abs_degrees"] < 0.0001
        and validation["candidate_feature_rows"] == 2_784
        and validation["candidate_valid_anomaly_rate"] >= 0.98
        and validation["candidate_valid_error_rate"] >= 0.96
        and raster_checks
        and not validation["candidate_scores_recomputed"]
    )
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_release_validation(validation)
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not validation["checks_pass"]:
        raise SystemExit("EMAG2 feature validation failed")


if __name__ == "__main__":
    main()
