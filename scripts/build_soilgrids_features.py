#!/usr/bin/env python3
"""Build uncertainty-aware SoilGrids 2.0 features for KHANAN's India H3 grid.

The script downloads reproducible, resolution-controlled WCS subsets for nine
pedological properties at surface and subsoil depth, samples the rasters at H3
resolution-6 centroids, and appends context-only fields to the nationwide and
candidate tables. Published prospectivity scores and ranks are preserved.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.transform import rowcol, xy


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RAW = ROOT / "sources" / "raw" / "soilgrids_v2_india_0p025deg"

RELEASE_VERSION = "v1.0-alpha.6"
GEOSPATIAL_FEATURE_VERSION = "v0.8"
FEATURE_VERSION = "soilgrids-v2-h3-r6-v0.1"
SOURCE_ACCESSED_DATE = "2026-09-10"

PRODUCT_URL = "https://docs.isric.org/globaldata/soilgrids/index.html"
LAYERS_URL = "https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html"
ACCESS_URL = "https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_02.html"
WCS_DOC_URL = "https://docs.isric.org/globaldata/soilgrids/wcs.html"
PAPER_DOI = "https://doi.org/10.5194/soil-7-217-2021"
WCS_URL = "https://maps.isric.org/mapserv"

# The rectangle contains the KHANAN India grid. A 0.025-degree output grid is
# resolution-controlled at approximately 2.2--2.8 km across India. The source
# product remains a 250 m model; this coarser derivative is appropriate for
# approximately 36 km2 H3 cells and keeps the release reproducible and compact.
BBOX = (68.0, 6.0, 98.0, 38.0)
OUTPUT_RESOLUTION_DEGREES = 0.025
WIDTH = 1200
HEIGHT = 1280

DEPTHS = {
    "0-5cm": "0_5cm",
    "30-60cm": "30_60cm",
}

# Conversion divisors and conventional units follow the official SoilGrids
# layer documentation. Raw WCS integers are converted before publication.
PROPERTIES = {
    "phh2o": {"label": "pH in water", "raw_unit": "pH x 10", "divisor": 10.0, "unit": "pH"},
    "clay": {"label": "clay content", "raw_unit": "g/kg", "divisor": 10.0, "unit": "percent by mass"},
    "sand": {"label": "sand content", "raw_unit": "g/kg", "divisor": 10.0, "unit": "percent by mass"},
    "silt": {"label": "silt content", "raw_unit": "g/kg", "divisor": 10.0, "unit": "percent by mass"},
    "soc": {"label": "soil organic carbon", "raw_unit": "dg/kg", "divisor": 10.0, "unit": "g/kg"},
    "cec": {"label": "cation exchange capacity at pH 7", "raw_unit": "mmol(c)/kg", "divisor": 10.0, "unit": "cmol(c)/kg"},
    "nitrogen": {"label": "total nitrogen", "raw_unit": "cg/kg", "divisor": 100.0, "unit": "g/kg"},
    "bdod": {"label": "bulk density of fine earth", "raw_unit": "cg/cm3", "divisor": 100.0, "unit": "kg/dm3"},
    "cfvo": {"label": "coarse fragments", "raw_unit": "cm3/dm3", "divisor": 10.0, "unit": "volume percent"},
}

PREDICTIONS = {
    "mean": "mean",
    "Q0.05": "p05",
    "Q0.95": "p95",
}

FEATURE_TABLE = OUT / "india_soilgrids_v2_soil_features_h3_r6.csv"
VALIDATION_PATH = OUT / "soilgrids_v2_soil_features_validation.json"
GRID_PATH = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
CANDIDATE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"

CORE_RANKING_COLUMNS = [
    "h3_r6",
    "record_class",
    "top_material",
    "prospectivity_score_max",
    "top_material_percentile",
    "top_material_nearest_known_km",
    "candidate_rank_national",
    "model_version",
]


def value_column(property_name: str, depth_slug: str, statistic: str) -> str:
    return f"soilgrids_{property_name}_{depth_slug}_{statistic}"


VALUE_COLUMNS = [
    value_column(property_name, depth_slug, statistic)
    for property_name in PROPERTIES
    for depth_slug in DEPTHS.values()
    for statistic in ["mean", "p05", "p95"]
]

LEGACY_INTERVAL_COLUMNS = [
    value_column(property_name, depth_slug, "interval_width_90")
    for property_name in PROPERTIES
    for depth_slug in DEPTHS.values()
]

METADATA_COLUMNS = [
    "soilgrids_texture_class_usda_0_5cm",
    "soilgrids_texture_class_usda_30_60cm",
    "soilgrids_texture_fraction_sum_0_5cm_pct",
    "soilgrids_texture_fraction_sum_30_60cm_pct",
    "soilgrids_source_grid_longitude",
    "soilgrids_source_grid_latitude",
    "soilgrids_source_grid_distance_km",
    "soilgrids_native_resolution_m",
    "soilgrids_wcs_output_resolution_degrees",
    "soilgrids_source_crs",
    "soilgrids_feature_version",
    "soilgrids_model_use_status",
    "soilgrids_uncertainty_interpretation",
    "soilgrids_data_quality_flags_json",
    "soil_source_dataset_ids_json",
]

SIGNAL_COLUMNS = VALUE_COLUMNS + METADATA_COLUMNS
ALL_MANAGED_COLUMNS = SIGNAL_COLUMNS + LEGACY_INTERVAL_COLUMNS


def source_row() -> dict[str, str]:
    return {
        "source_id": "SRC_ISRIC_SOILGRIDS_V2",
        "publisher": "ISRIC - World Soil Information",
        "title": "SoilGrids 2.0 global gridded soil information with quantified uncertainty",
        "release_or_reference_date": f"SoilGrids 2.0; source snapshot accessed {SOURCE_ACCESSED_DATE}",
        "url": PRODUCT_URL,
        "download_url": WCS_URL,
        "license_or_access_note": "SoilGrids maps are publicly available under CC BY 4.0. Cite Poggio et al. (2021), DOI 10.5194/soil-7-217-2021, and retain ISRIC attribution.",
        "used_for": "Resolution-controlled WCS subsets of nine soil properties at 0-5 cm and 30-60 cm, including mean predictions and 90% prediction intervals sampled at H3 resolution-6 centroids.",
        "limitations": "Global machine-learning predictions at native 250 m resolution, not field assays or mineral-deposit evidence. KHANAN samples a coarser 0.025-degree WCS derivative. SoilGrids uses environmental covariates including climate, land cover and terrain, so feature dependence and leakage must be tested before model admission.",
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_columns_sha256(path: Path, columns: list[str]) -> str:
    digest = hashlib.sha256()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(column not in reader.fieldnames for column in columns):
            raise RuntimeError(f"ranking columns missing from {path}")
        digest.update(("\x1f".join(columns) + "\n").encode("utf-8"))
        for row in reader:
            digest.update(("\x1f".join(row[column] for column in columns) + "\n").encode("utf-8"))
    return digest.hexdigest()


def request_url(property_name: str, depth: str, prediction: str) -> str:
    params = {
        "map": f"/map/{property_name}.map",
        "SERVICE": "WCS",
        "VERSION": "1.0.0",
        "REQUEST": "GetCoverage",
        "COVERAGE": f"{property_name}_{depth}_{prediction}",
        "CRS": "EPSG:4326",
        "BBOX": ",".join(str(value) for value in BBOX),
        "WIDTH": str(WIDTH),
        "HEIGHT": str(HEIGHT),
        "FORMAT": "GEOTIFF_INT16",
        "INTERPOLATION": "nearest",
    }
    return WCS_URL + "?" + urlencode(params)


def raster_metadata(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        array = dataset.read(1, masked=True)
        return {
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0],
            "crs": str(dataset.crs),
            "nodata": dataset.nodata,
            "transform": [float(value) for value in list(dataset.transform)[:6]],
            "bounds": [float(value) for value in dataset.bounds],
            "valid_pixels": int(array.count()),
            "valid_pixel_rate": float(array.count() / array.size),
        }


def validate_raster(path: Path) -> dict[str, Any]:
    metadata = raster_metadata(path)
    expected_transform = [OUTPUT_RESOLUTION_DEGREES, 0.0, BBOX[0], 0.0, -OUTPUT_RESOLUTION_DEGREES, BBOX[3]]
    if (
        metadata["width"] != WIDTH
        or metadata["height"] != HEIGHT
        or metadata["count"] != 1
        or metadata["dtype"] != "int16"
        or metadata["crs"] != "EPSG:4326"
        or not np.allclose(metadata["transform"], expected_transform, atol=1e-10, rtol=0)
        or not np.allclose(metadata["bounds"], BBOX, atol=1e-10, rtol=0)
    ):
        raise RuntimeError(f"unexpected WCS raster metadata for {path}: {metadata}")
    return metadata


def download_raster(
    session: requests.Session,
    property_name: str,
    depth: str,
    prediction: str,
    refresh: bool,
) -> tuple[Path, dict[str, Any]]:
    depth_slug = DEPTHS[depth]
    prediction_slug = PREDICTIONS[prediction]
    path = RAW / f"{property_name}_{depth_slug}_{prediction_slug}.tif"
    url = request_url(property_name, depth, prediction)
    if refresh or not path.exists():
        error: Exception | None = None
        for attempt in range(4):
            try:
                response = session.get(url, timeout=180, stream=True)
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                if "tiff" not in content_type.lower() and "octet-stream" not in content_type.lower():
                    raise RuntimeError(f"unexpected WCS content type {content_type!r}")
                temp = path.with_suffix(path.suffix + ".part")
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                temp.replace(path)
                error = None
                break
            except (requests.RequestException, RuntimeError) as exc:
                error = exc
                if attempt < 3:
                    time.sleep(1.5 * (attempt + 1))
        if error is not None:
            raise RuntimeError(f"WCS request failed after retries: {url}") from error
    metadata = validate_raster(path)
    return path, {
        "property": property_name,
        "depth": depth,
        "prediction": prediction,
        "request_url": url,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "raster_metadata": metadata,
    }


def haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    radius_km = 6371.0088
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    value = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius_km * np.arctan2(np.sqrt(value), np.sqrt(1 - value))


def read_centroid_values(path: Path, rows: np.ndarray, cols: np.ndarray, divisor: float) -> np.ndarray:
    with rasterio.open(path) as dataset:
        values = dataset.read(1)[rows, cols].astype("float64")
        invalid = ~np.isfinite(values)
        if dataset.nodata is not None:
            invalid |= np.isclose(values, dataset.nodata)
    values[invalid] = np.nan
    values /= divisor
    return values


def usda_texture_class(sand: float, silt: float, clay: float) -> str:
    if not all(math.isfinite(value) for value in [sand, silt, clay]) or sand + silt + clay <= 0:
        return ""
    total = sand + silt + clay
    sand, silt, clay = (100 * value / total for value in [sand, silt, clay])
    if sand >= 85 and silt + 1.5 * clay < 15:
        return "sand"
    if sand >= 70 and silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        return "loamy sand"
    if clay >= 40 and sand <= 45 and silt <= 40:
        return "clay"
    if clay >= 40 and silt > 40:
        return "silty clay"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if 20 <= clay < 35 and sand > 45 and silt < 28:
        return "sandy clay loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if silt >= 50 and clay < 27:
        return "silt loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if clay < 20 and sand >= 43 and silt < 50:
        return "sandy loam"
    return "loam"


def format_float(value: Any, digits: int = 6) -> Any:
    if value is None or (isinstance(value, (float, np.floating)) and not math.isfinite(float(value))):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return value


def build_features(grid: pd.DataFrame, paths: dict[tuple[str, str, str], Path]) -> pd.DataFrame:
    lons = grid["longitude"].to_numpy(dtype="float64")
    lats = grid["latitude"].to_numpy(dtype="float64")
    first_path = next(iter(paths.values()))
    with rasterio.open(first_path) as dataset:
        rows, cols = rowcol(dataset.transform, lons, lats)
        src_lons, src_lats = xy(dataset.transform, rows, cols, offset="center")
    rows = np.asarray(rows, dtype="int64")
    cols = np.asarray(cols, dtype="int64")
    if rows.min() < 0 or cols.min() < 0 or rows.max() >= HEIGHT or cols.max() >= WIDTH:
        raise RuntimeError("one or more KHANAN centroids falls outside the SoilGrids WCS subset")

    result = grid[["h3_r6", "latitude", "longitude"]].copy()
    result.insert(0, "record_id", "SOILGRIDS-" + result["h3_r6"].astype(str))
    arrays: dict[tuple[str, str, str], np.ndarray] = {}
    for property_name, property_config in PROPERTIES.items():
        for depth, depth_slug in DEPTHS.items():
            for prediction, statistic in PREDICTIONS.items():
                values = read_centroid_values(
                    paths[(property_name, depth, prediction)],
                    rows,
                    cols,
                    property_config["divisor"],
                )
                arrays[(property_name, depth_slug, statistic)] = values
                result[value_column(property_name, depth_slug, statistic)] = values
    for depth_slug in DEPTHS.values():
        sand = arrays[("sand", depth_slug, "mean")]
        silt = arrays[("silt", depth_slug, "mean")]
        clay = arrays[("clay", depth_slug, "mean")]
        result[f"soilgrids_texture_fraction_sum_{depth_slug}_pct"] = sand + silt + clay
        result[f"soilgrids_texture_class_usda_{depth_slug}"] = [
            usda_texture_class(a, b, c) for a, b, c in zip(sand, silt, clay)
        ]

    src_lons_array = np.asarray(src_lons, dtype="float64")
    src_lats_array = np.asarray(src_lats, dtype="float64")
    result["soilgrids_source_grid_longitude"] = src_lons_array
    result["soilgrids_source_grid_latitude"] = src_lats_array
    result["soilgrids_source_grid_distance_km"] = haversine_km(
        lats, lons, src_lats_array, src_lons_array
    )
    result["soilgrids_native_resolution_m"] = 250
    result["soilgrids_wcs_output_resolution_degrees"] = OUTPUT_RESOLUTION_DEGREES
    result["soilgrids_source_crs"] = "EPSG:4326"
    result["soilgrids_feature_version"] = FEATURE_VERSION
    result["soilgrids_model_use_status"] = "context_only_not_used_in_production_scoring"
    result["soilgrids_uncertainty_interpretation"] = "p05_p95_are_90pct_prediction_bounds_not_deposit_confidence"
    source_ids = json.dumps(["SRC_ISRIC_SOILGRIDS_V2"], separators=(",", ":"))
    any_value_missing = result[VALUE_COLUMNS].isna().any(axis=1).to_numpy()
    surface_sums = result["soilgrids_texture_fraction_sum_0_5cm_pct"].to_numpy(dtype="float64")
    subsoil_sums = result["soilgrids_texture_fraction_sum_30_60cm_pct"].to_numpy(dtype="float64")
    flags = []
    for index in range(len(result)):
        row_flags = [
            "ml_prediction_not_field_assay",
            "wcs_resampled_0p025deg",
            "not_scored",
        ]
        if any_value_missing[index]:
            row_flags.append("one_or_more_soilgrids_values_missing")
        surface_sum = surface_sums[index]
        subsoil_sum = subsoil_sums[index]
        if math.isfinite(surface_sum) and abs(float(surface_sum) - 100) > 5:
            row_flags.append("surface_texture_fraction_sum_differs_from_100pct")
        if math.isfinite(subsoil_sum) and abs(float(subsoil_sum) - 100) > 5:
            row_flags.append("subsoil_texture_fraction_sum_differs_from_100pct")
        flags.append(json.dumps(row_flags, separators=(",", ":")))
    result["soilgrids_data_quality_flags_json"] = flags
    result["soil_source_dataset_ids_json"] = source_ids

    expected = ["record_id", "h3_r6", "latitude", "longitude"] + SIGNAL_COLUMNS
    return result[expected]


def augment_csv(path: Path, features: pd.DataFrame) -> None:
    feature_matrix = features[SIGNAL_COLUMNS].to_numpy(dtype=object)
    h3_to_index = {h3: index for index, h3 in enumerate(features["h3_r6"].astype(str))}
    temp = path.with_suffix(path.suffix + ".soilgrids.tmp")
    with path.open("r", encoding="utf-8", newline="") as source, temp.open(
        "w", encoding="utf-8", newline=""
    ) as target:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "h3_r6" not in reader.fieldnames:
            raise RuntimeError(f"missing h3_r6 in {path}")
        base_fields = [field for field in reader.fieldnames if field not in ALL_MANAGED_COLUMNS]
        writer = csv.DictWriter(
            target,
            fieldnames=base_fields + SIGNAL_COLUMNS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        row_count = 0
        for row in reader:
            feature_index = h3_to_index.get(row["h3_r6"])
            if feature_index is None:
                raise RuntimeError(f"SoilGrids feature missing for {row['h3_r6']} in {path}")
            output = {field: row.get(field, "") for field in base_fields}
            output.update(
                {
                    column: format_float(value)
                    for column, value in zip(SIGNAL_COLUMNS, feature_matrix[feature_index])
                }
            )
            writer.writerow(output)
            row_count += 1
    if row_count == 0:
        raise RuntimeError(f"no rows written while augmenting {path}")
    temp.replace(path)


def field_definition(column: str) -> tuple[str, str, str | None]:
    if column == "record_id":
        return "Stable SoilGrids grid-feature record identifier.", "text", None
    if column == "h3_r6":
        return "H3 resolution-6 cell identifier.", "text", None
    if column == "latitude":
        return "WGS84 H3 cell-centroid latitude.", "number", "decimal degrees"
    if column == "longitude":
        return "WGS84 H3 cell-centroid longitude.", "number", "decimal degrees"
    if column.startswith("soilgrids_") and any(column.startswith(f"soilgrids_{name}_") for name in PROPERTIES):
        property_name = next(name for name in PROPERTIES if column.startswith(f"soilgrids_{name}_"))
        config = PROPERTIES[property_name]
        depth_text = "0-5 cm" if "_0_5cm_" in column else "30-60 cm"
        if column.endswith("_mean"):
            statistic = "mean prediction"
        elif column.endswith("_p05"):
            statistic = "5th-percentile prediction, the lower bound of the 90% prediction interval"
        elif column.endswith("_p95"):
            statistic = "95th-percentile prediction, the upper bound of the 90% prediction interval"
        else:
            raise KeyError(column)
        return f"SoilGrids {config['label']} {statistic} for {depth_text}.", "number", config["unit"]
    definitions = {
        "soilgrids_texture_class_usda_0_5cm": ("USDA texture class derived after normalizing the three SoilGrids surface mean texture fractions to 100%.", "category", None),
        "soilgrids_texture_class_usda_30_60cm": ("USDA texture class derived after normalizing the three SoilGrids 30-60 cm mean texture fractions to 100%.", "category", None),
        "soilgrids_texture_fraction_sum_0_5cm_pct": ("Sum of surface mean sand, silt and clay predictions before normalization for texture classification.", "number", "percent by mass"),
        "soilgrids_texture_fraction_sum_30_60cm_pct": ("Sum of 30-60 cm mean sand, silt and clay predictions before normalization for texture classification.", "number", "percent by mass"),
        "soilgrids_source_grid_longitude": ("Longitude of the matched resolution-controlled WCS output pixel centre.", "number", "decimal degrees"),
        "soilgrids_source_grid_latitude": ("Latitude of the matched resolution-controlled WCS output pixel centre.", "number", "decimal degrees"),
        "soilgrids_source_grid_distance_km": ("Great-circle distance between the H3 centroid and the matched WCS output pixel centre.", "number", "km"),
        "soilgrids_native_resolution_m": ("Nominal native SoilGrids product resolution; the WCS derivative is coarser.", "integer", "m"),
        "soilgrids_wcs_output_resolution_degrees": ("Latitude/longitude cell size requested from WCS before H3 centroid sampling.", "number", "decimal degrees"),
        "soilgrids_source_crs": ("Coordinate reference system of the resolution-controlled WCS derivative.", "text", None),
        "soilgrids_feature_version": ("Version of the KHANAN SoilGrids transformation.", "text", None),
        "soilgrids_model_use_status": ("Whether SoilGrids features affect published prospectivity rankings.", "category", None),
        "soilgrids_uncertainty_interpretation": ("Interpretation and limitations of SoilGrids prediction bounds.", "text", None),
        "soilgrids_data_quality_flags_json": ("JSON array of record-level SoilGrids caveats and missingness flags.", "JSON array", None),
        "soil_source_dataset_ids_json": ("JSON array of source-registry identifiers for soil features.", "JSON array", None),
    }
    if column not in definitions:
        raise KeyError(column)
    return definitions[column]


def upsert_source_registry() -> None:
    path = OUT / "source_registry.csv"
    existing = pd.read_csv(path, keep_default_na=False)
    row = source_row()
    retained = existing.loc[existing["source_id"] != row["source_id"]].copy()
    pd.concat([retained, pd.DataFrame([row])], ignore_index=True).to_csv(path, index=False)


def upsert_dictionary(feature_columns: list[str]) -> None:
    path = OUT / "data_dictionary.csv"
    dictionary = pd.read_csv(path, keep_default_na=False)
    targets = {
        FEATURE_TABLE.name: feature_columns,
        GRID_PATH.name: SIGNAL_COLUMNS,
        CANDIDATE_PATH.name: SIGNAL_COLUMNS,
    }
    remove = np.zeros(len(dictionary), dtype=bool)
    for table_name in targets:
        managed = feature_columns if table_name == FEATURE_TABLE.name else ALL_MANAGED_COLUMNS
        remove |= (dictionary["table"] == table_name) & dictionary["column"].isin(managed)
    retained = dictionary.loc[~remove].copy()
    rows = []
    for table_name, columns in targets.items():
        for column in columns:
            definition, data_type, unit = field_definition(column)
            rows.append(
                {
                    "table": table_name,
                    "column": column,
                    "definition": definition,
                    "data_type": data_type,
                    "unit": unit or "",
                    "missing_value_policy": "Blank means the source prediction is missing or invalid; source zeros are retained as numeric zero.",
                }
            )
    pd.concat([retained, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)


def update_release_validation(validation: dict[str, Any]) -> None:
    path = OUT / "validation_report.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["dataset_release_version"] = GEOSPATIAL_FEATURE_VERSION
    release["soilgrids_v2_soil_context"] = {
        key: validation[key]
        for key in [
            "feature_rows",
            "unique_h3_cells",
            "source_raster_count",
            "minimum_mean_property_coverage_rate",
            "minimum_prediction_interval_coverage_rate",
            "quantile_order_violations",
            "maximum_source_grid_distance_km",
            "candidate_feature_rows",
            "candidate_scores_recomputed",
            "core_ranking_columns_unchanged",
            "checks_pass",
        ]
    }
    path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Redownload all SoilGrids WCS subsets")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "KHANAN/1.0 SoilGrids reproducible soil feature build"})

    paths: dict[tuple[str, str, str], Path] = {}
    source_files = []
    for property_name in PROPERTIES:
        for depth in DEPTHS:
            for prediction in PREDICTIONS:
                path, metadata = download_raster(
                    session, property_name, depth, prediction, args.refresh
                )
                paths[(property_name, depth, prediction)] = path
                source_files.append(metadata)

    grid = pd.read_csv(
        GRID_PATH,
        usecols=["h3_r6", "latitude", "longitude"],
        dtype={"h3_r6": str},
    )
    if len(grid) != grid["h3_r6"].nunique():
        raise RuntimeError("nationwide grid H3 identifiers are not unique")

    ranking_hashes_before = {
        "national_grid": selected_columns_sha256(GRID_PATH, CORE_RANKING_COLUMNS),
        "candidate_table": selected_columns_sha256(CANDIDATE_PATH, CORE_RANKING_COLUMNS),
    }
    features = build_features(grid, paths)
    features.to_csv(FEATURE_TABLE, index=False, float_format="%.6f")
    augment_csv(GRID_PATH, features)
    augment_csv(CANDIDATE_PATH, features)
    upsert_source_registry()
    upsert_dictionary(list(features.columns))
    ranking_hashes_after = {
        "national_grid": selected_columns_sha256(GRID_PATH, CORE_RANKING_COLUMNS),
        "candidate_table": selected_columns_sha256(CANDIDATE_PATH, CORE_RANKING_COLUMNS),
    }

    coverage = {
        column: float(features[column].notna().mean())
        for column in VALUE_COLUMNS
        if column.endswith(("_mean", "_p05", "_p95"))
    }
    mean_coverage = {key: value for key, value in coverage.items() if key.endswith("_mean")}
    interval_coverage = {
        key: value for key, value in coverage.items() if key.endswith(("_p05", "_p95"))
    }
    quantile_order_violations = 0
    interval_negative_width_violations = 0
    property_summaries: dict[str, Any] = {}
    for property_name, config in PROPERTIES.items():
        property_summaries[property_name] = {}
        for depth_slug in DEPTHS.values():
            lower = features[value_column(property_name, depth_slug, "p05")]
            mean = features[value_column(property_name, depth_slug, "mean")]
            upper = features[value_column(property_name, depth_slug, "p95")]
            valid = lower.notna() & mean.notna() & upper.notna()
            quantile_order_violations += int((lower[valid] > upper[valid]).sum())
            width = upper - lower
            interval_negative_width_violations += int((width[valid] < 0).sum())
            property_summaries[property_name][depth_slug] = {
                "unit": config["unit"],
                "valid_rows": int(valid.sum()),
                "mean_minimum": float(mean[mean.notna()].min()),
                "mean_median": float(mean[mean.notna()].median()),
                "mean_maximum": float(mean[mean.notna()].max()),
                "median_interval_width_90": float(width[valid].median()),
            }

    candidate = pd.read_csv(
        CANDIDATE_PATH,
        usecols=["h3_r6"] + SIGNAL_COLUMNS,
        dtype={"h3_r6": str},
    )
    metadata_aligned = len(
        {
            (
                tuple(item["raster_metadata"]["transform"]),
                tuple(item["raster_metadata"]["bounds"]),
                item["raster_metadata"]["width"],
                item["raster_metadata"]["height"],
                item["raster_metadata"]["crs"],
            )
            for item in source_files
        }
    ) == 1
    core_unchanged = ranking_hashes_before == ranking_hashes_after
    validation = {
        "release_version": RELEASE_VERSION,
        "geospatial_feature_version": GEOSPATIAL_FEATURE_VERSION,
        "feature_version": FEATURE_VERSION,
        "build_date": date.today().isoformat(),
        "source_accessed_date": SOURCE_ACCESSED_DATE,
        "source_product_url": PRODUCT_URL,
        "source_layers_and_units_url": LAYERS_URL,
        "source_access_and_license_url": ACCESS_URL,
        "source_wcs_documentation_url": WCS_DOC_URL,
        "source_paper_doi": PAPER_DOI,
        "source_license": "CC BY 4.0",
        "wcs_request_bbox_epsg4326": list(BBOX),
        "wcs_output_width": WIDTH,
        "wcs_output_height": HEIGHT,
        "wcs_output_resolution_degrees": OUTPUT_RESOLUTION_DEGREES,
        "native_product_resolution_m": 250,
        "source_raster_count": len(source_files),
        "source_files": source_files,
        "properties": list(PROPERTIES),
        "depth_intervals_cm": list(DEPTHS),
        "prediction_statistics": list(PREDICTIONS),
        "feature_rows": int(len(features)),
        "unique_h3_cells": int(features["h3_r6"].nunique()),
        "minimum_mean_property_coverage_rate": min(mean_coverage.values()),
        "minimum_prediction_interval_coverage_rate": min(interval_coverage.values()),
        "coverage_by_value_column": coverage,
        "quantile_order_violations": quantile_order_violations,
        "interval_negative_width_violations": interval_negative_width_violations,
        "property_summaries": property_summaries,
        "surface_texture_class_distribution": features["soilgrids_texture_class_usda_0_5cm"].value_counts(dropna=False).to_dict(),
        "subsoil_texture_class_distribution": features["soilgrids_texture_class_usda_30_60cm"].value_counts(dropna=False).to_dict(),
        "texture_fraction_sum_surface_pct": {
            "minimum": float(features["soilgrids_texture_fraction_sum_0_5cm_pct"].min()),
            "median": float(features["soilgrids_texture_fraction_sum_0_5cm_pct"].median()),
            "maximum": float(features["soilgrids_texture_fraction_sum_0_5cm_pct"].max()),
        },
        "texture_fraction_sum_subsoil_pct": {
            "minimum": float(features["soilgrids_texture_fraction_sum_30_60cm_pct"].min()),
            "median": float(features["soilgrids_texture_fraction_sum_30_60cm_pct"].median()),
            "maximum": float(features["soilgrids_texture_fraction_sum_30_60cm_pct"].max()),
        },
        "maximum_source_grid_distance_km": float(features["soilgrids_source_grid_distance_km"].max()),
        "rasters_aligned": metadata_aligned,
        "candidate_feature_rows": int(len(candidate)),
        "candidate_minimum_mean_property_coverage_rate": min(
            float(candidate[column].notna().mean()) for column in mean_coverage
        ),
        "candidate_scores_recomputed": False,
        "ranking_column_hashes_before": ranking_hashes_before,
        "ranking_column_hashes_after": ranking_hashes_after,
        "core_ranking_columns_unchanged": core_unchanged,
        "model_use_status": "Context-only. A separate leakage-aware spatial ablation is required before any property can affect production scores.",
    }
    validation["checks_pass"] = bool(
        validation["source_raster_count"] == len(PROPERTIES) * len(DEPTHS) * len(PREDICTIONS)
        and validation["feature_rows"] == validation["unique_h3_cells"] == len(grid) == 88_857
        and validation["candidate_feature_rows"] == 2_784
        and validation["minimum_mean_property_coverage_rate"] >= 0.98
        and validation["minimum_prediction_interval_coverage_rate"] >= 0.98
        and validation["candidate_minimum_mean_property_coverage_rate"] >= 0.98
        and validation["quantile_order_violations"] == 0
        and validation["interval_negative_width_violations"] == 0
        and validation["maximum_source_grid_distance_km"] < 2.1
        and validation["rasters_aligned"]
        and validation["core_ranking_columns_unchanged"]
        and not validation["candidate_scores_recomputed"]
    )
    VALIDATION_PATH.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    update_release_validation(validation)
    print(
        json.dumps(
            {
                "feature_rows": validation["feature_rows"],
                "source_raster_count": validation["source_raster_count"],
                "minimum_mean_property_coverage_rate": validation["minimum_mean_property_coverage_rate"],
                "minimum_prediction_interval_coverage_rate": validation["minimum_prediction_interval_coverage_rate"],
                "maximum_source_grid_distance_km": validation["maximum_source_grid_distance_km"],
                "core_ranking_columns_unchanged": validation["core_ranking_columns_unchanged"],
                "checks_pass": validation["checks_pass"],
            },
            indent=2,
        )
    )
    if not validation["checks_pass"]:
        raise SystemExit("SoilGrids feature validation failed")


if __name__ == "__main__":
    main()
