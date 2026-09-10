#!/usr/bin/env python3
"""Build the preview-limited GSI OGD mineral-deposit context layer.

India's OGD portal currently exposes authoritative catalog/resource metadata
and a server-side preview, but direct workbook access requires an interactive
download-purpose form and CAPTCHA.  This builder therefore publishes only the
rows actually returned by the public preview endpoint and audits the unexposed
remainder.  Preview rows are context-only and never become model labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import h3
import requests
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw" / "gsi_ogd_deposit_preview"
OUT = ROOT / "outputs"
DEPOSIT_OUTPUT = OUT / "india_gsi_ogd_mineral_deposit_preview.csv"
AUDIT_OUTPUT = OUT / "gsi_ogd_mineral_deposit_catalog_audit.csv"
VALIDATION_OUTPUT = OUT / "gsi_ogd_mineral_deposit_preview_validation.json"
SOURCE_REGISTRY = OUT / "source_registry.csv"
DATA_DICTIONARY = OUT / "data_dictionary.csv"
KNOWN_SITES = OUT / "india_known_mining_sites.csv"
DISTRICT_BOUNDARIES = ROOT / "sources" / "raw" / "2011_Dist.shp"

RELEASE_VERSION = "v1.0-alpha.21"
SOURCE_ID = "SRC_GSI_OGD_MINERAL_DEPOSIT_CATALOGS_2013"
LICENSE_NAME = "Government Open Data License - India"
LICENSE_URL = "https://www.data.gov.in/godl"
DMS_V2 = "https://www.data.gov.in/backend/dms/v2"
DMS_V1 = "https://www.data.gov.in/backend/dms/v1"


@dataclass(frozen=True)
class CatalogSpec:
    key: str
    catalog_nid: int
    catalog_uuid: str
    resource_nid: int
    resource_uuid: str
    alias: str
    commodity_scope: str
    expected_total: int
    expected_preview_rows: int
    ontology_ids: tuple[str, ...]
    material_names: tuple[str, ...]
    chemical_names: tuple[str, ...]
    formulae: tuple[str, ...]
    model_targets: tuple[str, ...]
    comparison_terms: tuple[str, ...]

    @property
    def catalog_url(self) -> str:
        return f"https://www.data.gov.in/catalog/{self.alias}"

    @property
    def resource_url(self) -> str:
        return f"https://www.data.gov.in/resource/{self.alias}"

    @property
    def catalog_metadata_url(self) -> str:
        return f"{DMS_V2}/catalog/{self.alias}?_format=json"

    @property
    def resource_metadata_url(self) -> str:
        return f"{DMS_V2}/resource/{self.alias}?_format=json"

    @property
    def preview_url(self) -> str:
        return f"{DMS_V1}/ogdp/resource/data/preview/{self.resource_nid}?_format=json"


CATALOGS = (
    CatalogSpec(
        "bauxite", 88877, "4f0e265b-89ee-473c-9176-d6018fb3a3de",
        88876, "9318a72b-de11-427c-8e3a-7ca878e2a89e",
        "location-aluminum-deposits-bauxite-india-and-its-salient-features",
        "Bauxite", 51, 10,
        ("element:aluminium", "ore:bauxite"), ("Aluminium", "Bauxite"),
        ("aluminium",), ("Al",), ("Aluminium",),
        ("Aluminium", "Aluminum", "Bauxite"),
    ),
    CatalogSpec(
        "baryte", 88879, "e00c942c-acb4-4c3c-9d1a-6639ef38290c",
        88878, "916bae9d-b387-44f4-8aaf-5650c0174e51",
        "location-baryte-deposits-india-and-its-salient-features",
        "Baryte", 9, 8,
        ("element:barium", "mineral:baryte"), ("Barium", "Baryte"),
        ("barium sulfate",), ("Ba", "Ba(SO4)"), ("Barium",),
        ("Barium", "Baryte", "Barite", "Barytes"),
    ),
    CatalogSpec(
        "copper", 88881, "cc3653aa-3af4-4ae0-8698-93e1d7eee2f7",
        88880, "8192ef10-7ed7-42eb-93c7-51708a79b221",
        "location-copper-deposits-india-and-its-salient-features",
        "Copper", 106, 10,
        ("element:copper",), ("Copper",), ("copper",), ("Cu",),
        ("Copper",), ("Copper",),
    ),
    CatalogSpec(
        "diamond", 88883, "24d6bb35-325a-4885-a3d4-6dc028582178",
        88882, "0e5a3848-6ea5-4ef0-bd3f-3dbeaf96e9e5",
        "location-diamond-deposits-india-and-its-salient-features",
        "Diamond", 14, 10,
        ("mineral:diamond",), ("Diamond",), ("carbon",), ("C",),
        (), ("Diamond",),
    ),
    CatalogSpec(
        "gold", 88885, "63a985ee-85ab-4aa5-aaf7-366c3fe2958f",
        88884, "f9ddd1f5-7fc6-44e8-9f5c-6a5fc47527e9",
        "location-gold-deposits-india-and-its-salient-features",
        "Gold", 53, 10,
        ("element:gold",), ("Gold",), ("gold",), ("Au",),
        ("Gold",), ("Gold",),
    ),
    CatalogSpec(
        "iron", 88887, "b14cb14b-51f1-4269-a6c4-b8fb728c57d2",
        88886, "4c540e9e-e7b9-4ea7-91da-70c1f4fe12bb",
        "location-iron-ore-deposits-india-and-its-salient-features",
        "Iron", 81, 10,
        ("element:iron",), ("Iron",), ("iron",), ("Fe",),
        ("Iron",), ("Iron", "Iron Ore"),
    ),
    CatalogSpec(
        "lead_zinc", 88889, "61feacce-4312-4515-bda8-1df6416487c4",
        88888, "4886e5de-e06f-440f-a41d-05f96b9682ec",
        "location-lead-zinc-ore-deposits-india-and-its-salient-features",
        "Lead-Zinc", 33, 10,
        ("element:lead", "element:zinc"), ("Lead", "Zinc"),
        ("lead", "zinc"), ("Pb", "Zn"), ("Lead", "Zinc"),
        ("Lead", "Zinc", "Lead-Zinc", "Lead Zinc"),
    ),
    CatalogSpec(
        "manganese", 88891, "4574036c-1538-4100-84e6-41a9280f669f",
        88890, "fd58a160-2b76-4547-b5e6-10431152b88f",
        "location-manganese-ore-deposits-india-and-its-salient-features",
        "Manganese", 34, 10,
        ("element:manganese",), ("Manganese",), ("manganese",), ("Mn",),
        ("Manganese",), ("Manganese", "Manganese Ore"),
    ),
)


DEPOSIT_FIELDS = [
    "record_id", "source_id", "catalog_key", "catalog_nid", "catalog_uuid",
    "resource_nid", "resource_uuid", "source_row_position", "commodity_source",
    "normalized_material_ids_json", "normalized_material_names_json",
    "chemical_names_json", "symbols_or_formulae_json", "model_target_names_json",
    "metallogenic_province_source", "locality_source", "source_state_name",
    "toposheet_source", "latitude_source", "longitude_source", "source_latdd",
    "source_londd", "latitude_min", "latitude_max", "longitude_min", "longitude_max",
    "representative_latitude", "representative_longitude", "coordinate_geometry_type",
    "representative_coordinate_method", "coordinate_reference_system",
    "coordinate_precision_note", "coordinate_span_km", "h3_r6", "state_or_ut_2011",
    "district_2011", "centroid_in_source_state_2011_boundary", "host_rock_source",
    "morphogenesis_source", "formation_source", "source_catalog_total_rows",
    "preview_rows_returned", "preview_coverage_pct", "source_selection_mechanism",
    "source_catalog_url", "source_resource_url", "source_preview_endpoint_url",
    "source_workbook_metadata_url", "source_release_date", "source_updated_timestamp",
    "source_license", "source_license_url", "nearest_known_site_record_id",
    "nearest_known_site_km", "nearest_known_comparable_material_record_id",
    "nearest_known_comparable_material_km", "nearest_known_comparable_material_within_25km",
    "exact_normalized_locality_match_in_known_sites", "knowledge_independence_status",
    "model_evidence_role", "model_exclusion_reason", "data_quality_flags_json",
]


AUDIT_FIELDS = [
    "catalog_record_id", "source_id", "catalog_key", "commodity_scope", "catalog_nid",
    "catalog_uuid", "resource_nid", "resource_uuid", "catalog_title", "catalog_url",
    "resource_url", "catalog_metadata_endpoint_url", "resource_metadata_endpoint_url",
    "preview_endpoint_url", "workbook_metadata_url", "workbook_name",
    "workbook_file_entity_id", "workbook_reported_bytes", "catalog_published_timestamp",
    "catalog_changed_timestamp", "resource_published_timestamp", "resource_changed_timestamp",
    "source_columns_json", "source_reported_total_rows", "preview_rows_returned",
    "preview_coverage_pct", "full_rows_not_exposed_in_preview", "preview_access_status",
    "source_file_http_status", "source_file_access_status", "completeness_status",
    "source_selection_mechanism", "license_name", "license_url", "source_access_date",
    "model_evidence_role", "catalog_metadata_sha256", "resource_metadata_sha256",
    "preview_response_sha256", "limitations",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--access-date", default="2026-09-10")
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fetch_json(url: str, cache_path: Path, refresh: bool) -> tuple[dict[str, Any], str]:
    if cache_path.exists() and not refresh:
        payload = cache_path.read_bytes()
    else:
        response = None
        last_error: requests.RequestException | None = None
        for _ in range(4):
            try:
                response = requests.get(
                    url, timeout=30, headers={"User-Agent": "curl/8.7.1"}
                )
            except requests.RequestException as error:
                last_error = error
                continue
            if response.status_code < 500:
                break
        if response is None:
            assert last_error is not None
            raise last_error
        response.raise_for_status()
        payload = response.content
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(payload)
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return parsed, sha256_bytes(payload)


def json_array(values: tuple[str, ...] | list[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def first_value(entity: dict[str, Any], field: str, key: str = "value") -> Any:
    values = entity.get(field) or []
    return values[0].get(key, "") if values else ""


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def component_value(parts: list[float]) -> float:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] + parts[1] / 60.0
    if len(parts) == 3:
        return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
    raise ValueError(f"Unsupported coordinate component: {parts}")


def parse_coordinate_range(raw_value: str, axis: str) -> tuple[float, float, list[str]]:
    text = str(raw_value or "").strip().upper().replace("°", " ")
    hemispheres = re.findall(r"[NSEW]", text)
    if not hemispheres:
        raise ValueError(f"Missing hemisphere in {axis} coordinate {raw_value!r}")
    hemisphere = hemispheres[-1]
    allowed = {"latitude": {"N", "S"}, "longitude": {"E", "W"}}[axis]
    if hemisphere not in allowed:
        raise ValueError(f"Wrong hemisphere in {axis} coordinate {raw_value!r}")
    body = re.sub(r"[NSEW]", "", text).strip()
    flags: list[str] = []

    if "-" in body:
        left_text, right_text = body.split("-", 1)
        left = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", left_text)]
        right = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", right_text)]
        if not left or not right:
            raise ValueError(f"Malformed coordinate range {raw_value!r}")
        if len(right) < len(left):
            right = left[: len(left) - len(right)] + right
        if len(right) > 3 or len(left) > 3:
            raise ValueError(f"Unsupported coordinate range {raw_value!r}")
        endpoints = [component_value(left), component_value(right)]
    else:
        numbers = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", body)]
        if len(numbers) in {1, 2, 3}:
            endpoints = [component_value(numbers)] * 2
        elif len(numbers) == 4 and numbers[0] == numbers[2]:
            endpoints = [component_value(numbers[:2]), component_value(numbers[2:])]
            flags.append("source_range_separator_missing_interpreted_as_two_degree_minute_endpoints")
        else:
            raise ValueError(f"Unsupported coordinate syntax {raw_value!r}")

    sign = -1.0 if hemisphere in {"S", "W"} else 1.0
    signed = [sign * value for value in endpoints]
    lower, upper = min(signed), max(signed)
    limit = 90.0 if axis == "latitude" else 180.0
    if not (-limit <= lower <= upper <= limit):
        raise ValueError(f"Out-of-range {axis} coordinate {raw_value!r}")
    return lower, upper, flags


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def read_known_sites() -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    with KNOWN_SITES.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (TypeError, ValueError):
                continue
            try:
                materials = json.loads(row.get("source_materials_json") or "[]")
            except json.JSONDecodeError:
                materials = []
            sites.append({
                "record_id": row["record_id"],
                "site_name": row.get("site_name", ""),
                "site_name_norm": normalize_text(row.get("site_name", "")),
                "latitude": latitude,
                "longitude": longitude,
                "materials_norm": {normalize_text(value) for value in materials},
            })
    if not sites:
        raise ValueError("No coordinate-bearing known-site rows are available")
    return sites


def nearest_site(latitude: float, longitude: float, sites: list[dict[str, Any]]) -> tuple[str, float]:
    distances = [
        (haversine_km(latitude, longitude, site["latitude"], site["longitude"]), site["record_id"])
        for site in sites
    ]
    distance, record_id = min(distances)
    return record_id, distance


def boundary_lookup(
    point: Point, boundaries: gpd.GeoDataFrame
) -> tuple[str, str]:
    candidate_indices = list(boundaries.sindex.query(point, predicate="intersects"))
    matches = boundaries.iloc[candidate_indices]
    matches = matches[matches.geometry.apply(lambda geometry: geometry.covers(point))]
    if matches.empty:
        return "", ""
    row = matches.sort_values(["ST_NM", "DISTRICT"]).iloc[0]
    return str(row["ST_NM"]), str(row["DISTRICT"])


STATE_NORMALIZATION = {
    "orissa": "odisha",
    "chattisgarh": "chhattisgarh",
}


def normalized_state(value: str) -> str:
    normalized = normalize_text(value)
    return STATE_NORMALIZATION.get(normalized, normalized)


def workbook_http_status(url: str) -> int:
    try:
        response = requests.get(
            url,
            timeout=20,
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "curl/8.7.1"},
        )
        return int(response.status_code)
    except requests.RequestException:
        return 0


def build_catalog(
    spec: CatalogSpec,
    access_date: str,
    refresh: bool,
    known_sites: list[dict[str, Any]],
    boundaries: gpd.GeoDataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    catalog, catalog_hash = fetch_json(
        spec.catalog_metadata_url, RAW / f"catalog_{spec.catalog_nid}.json", refresh
    )
    resource, resource_hash = fetch_json(
        spec.resource_metadata_url, RAW / f"resource_{spec.resource_nid}.json", refresh
    )
    preview, preview_hash = fetch_json(
        spec.preview_url, RAW / f"preview_{spec.resource_nid}.json", refresh
    )

    checks = {
        "catalog_nid": int(first_value(catalog, "nid")) == spec.catalog_nid,
        "catalog_uuid": first_value(catalog, "uuid") == spec.catalog_uuid,
        "resource_nid": int(first_value(resource, "nid")) == spec.resource_nid,
        "resource_uuid": first_value(resource, "uuid") == spec.resource_uuid,
        "catalog_reference": int(first_value(resource, "field_catalog_reference", "target_id")) == spec.catalog_nid,
        "preview_total": int(preview.get("total", -1)) == spec.expected_total,
        "preview_rows": len(preview.get("records") or []) == spec.expected_preview_rows,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"{spec.key} source contract failed: {failed}")

    source_fields = [item.get("value", "") for item in resource.get("field_meta_field") or []]
    preview_fields = [str(value) for value in preview.get("field") or []]
    if source_fields != preview_fields:
        raise ValueError(f"{spec.key} resource and preview schemas differ")

    workbook_url = first_value(resource, "field_datafile", "url")
    file_status = workbook_http_status(workbook_url)
    preview_count = len(preview["records"])
    coverage_pct = round(100.0 * preview_count / spec.expected_total, 6)
    rows: list[dict[str, Any]] = []
    comparable_norm = {normalize_text(value) for value in spec.comparison_terms}

    for position, source_row in enumerate(preview["records"], start=1):
        latitude_source = str(source_row.get("LATITUDE", "")).strip()
        longitude_source = str(source_row.get("LONGITUDE", "")).strip()
        lat_min, lat_max, lat_flags = parse_coordinate_range(latitude_source, "latitude")
        lon_min, lon_max, lon_flags = parse_coordinate_range(longitude_source, "longitude")
        latitude = (lat_min + lat_max) / 2.0
        longitude = (lon_min + lon_max) / 2.0
        flags = lat_flags + lon_flags
        if not (6 <= latitude <= 38.6 and 68 <= longitude <= 98.5):
            flags.append("representative_coordinate_outside_expected_india_bounds")

        source_latdd = str(source_row.get("LATDD", "")).strip()
        source_londd = str(source_row.get("LONDD", "")).strip()
        for source_dd, lower, upper, label in (
            (source_latdd, lat_min, lat_max, "latdd"),
            (source_londd, lon_min, lon_max, "londd"),
        ):
            if source_dd:
                value = float(source_dd)
                midpoint = (lower + upper) / 2.0
                if min(abs(value - lower), abs(value - upper), abs(value - midpoint)) > 1e-5:
                    flags.append(f"source_{label}_does_not_match_parsed_extent_endpoint_or_midpoint")

        state_2011, district_2011 = boundary_lookup(Point(longitude, latitude), boundaries)
        state_match = bool(state_2011) and normalized_state(state_2011) == normalized_state(
            str(source_row.get("STATE", ""))
        )
        if not state_2011:
            flags.append("representative_coordinate_not_covered_by_2011_district_boundary")
        elif not state_match:
            flags.append("source_state_differs_from_2011_boundary_at_representative_coordinate")

        nearest_id, nearest_distance = nearest_site(latitude, longitude, known_sites)
        comparable_sites = [
            site
            for site in known_sites
            if any(
                term == material or f" {term} " in f" {material} "
                for material in site["materials_norm"]
                for term in comparable_norm
            )
        ]
        if comparable_sites:
            comparable_id, comparable_distance = nearest_site(latitude, longitude, comparable_sites)
        else:
            comparable_id, comparable_distance = "", math.nan
            flags.append("no_comparable_material_rows_in_known_site_layer")

        locality_norm = normalize_text(source_row.get("LOCALITY", ""))
        exact_locality_match = any(site["site_name_norm"] == locality_norm for site in known_sites)
        geometry_type = "point" if lat_min == lat_max and lon_min == lon_max else "coordinate_range"
        coordinate_method = (
            "source_published_dms_point_encoded_as_decimal_degrees"
            if geometry_type == "point"
            else "arithmetic_midpoint_of_source_published_dms_coordinate_ranges"
        )
        span_km = haversine_km(lat_min, lon_min, lat_max, lon_max)
        comparable_within_25 = bool(not math.isnan(comparable_distance) and comparable_distance <= 25)
        row = {
            "record_id": f"GSI-OGD-{spec.key.upper()}-PREVIEW-{position:03d}",
            "source_id": SOURCE_ID,
            "catalog_key": spec.key,
            "catalog_nid": spec.catalog_nid,
            "catalog_uuid": spec.catalog_uuid,
            "resource_nid": spec.resource_nid,
            "resource_uuid": spec.resource_uuid,
            "source_row_position": position,
            "commodity_source": source_row.get("COMMODITY", spec.commodity_scope),
            "normalized_material_ids_json": json_array(spec.ontology_ids),
            "normalized_material_names_json": json_array(spec.material_names),
            "chemical_names_json": json_array(spec.chemical_names),
            "symbols_or_formulae_json": json_array(spec.formulae),
            "model_target_names_json": json_array(spec.model_targets),
            "metallogenic_province_source": source_row.get(
                "METALLOGENESIS", source_row.get("METALLOGENIC PROVINCE", "")
            ),
            "locality_source": source_row.get("LOCALITY", ""),
            "source_state_name": source_row.get("STATE", ""),
            "toposheet_source": source_row.get("TOPOSHEET", ""),
            "latitude_source": latitude_source,
            "longitude_source": longitude_source,
            "source_latdd": source_latdd,
            "source_londd": source_londd,
            "latitude_min": round(lat_min, 8),
            "latitude_max": round(lat_max, 8),
            "longitude_min": round(lon_min, 8),
            "longitude_max": round(lon_max, 8),
            "representative_latitude": round(latitude, 8),
            "representative_longitude": round(longitude, 8),
            "coordinate_geometry_type": geometry_type,
            "representative_coordinate_method": coordinate_method,
            "coordinate_reference_system": "EPSG:4326 encoding; source datum not stated",
            "coordinate_precision_note": "Source DMS point or range; a range midpoint is representative context, not a surveyed deposit boundary.",
            "coordinate_span_km": round(span_km, 6),
            "h3_r6": h3.latlng_to_cell(latitude, longitude, 6),
            "state_or_ut_2011": state_2011,
            "district_2011": district_2011,
            "centroid_in_source_state_2011_boundary": state_match,
            "host_rock_source": source_row.get("HOSTROCK", ""),
            "morphogenesis_source": source_row.get("MORPHOGENESIS", ""),
            "formation_source": source_row.get("FORMATION", ""),
            "source_catalog_total_rows": spec.expected_total,
            "preview_rows_returned": preview_count,
            "preview_coverage_pct": coverage_pct,
            "source_selection_mechanism": "first_rows_returned_by_public_portal_preview_not_random",
            "source_catalog_url": spec.catalog_url,
            "source_resource_url": spec.resource_url,
            "source_preview_endpoint_url": spec.preview_url,
            "source_workbook_metadata_url": workbook_url,
            "source_release_date": str(first_value(resource, "field_date_released")),
            "source_updated_timestamp": str(first_value(resource, "changed")),
            "source_license": LICENSE_NAME,
            "source_license_url": LICENSE_URL,
            "nearest_known_site_record_id": nearest_id,
            "nearest_known_site_km": round(nearest_distance, 6),
            "nearest_known_comparable_material_record_id": comparable_id,
            "nearest_known_comparable_material_km": (
                "" if math.isnan(comparable_distance) else round(comparable_distance, 6)
            ),
            "nearest_known_comparable_material_within_25km": comparable_within_25,
            "exact_normalized_locality_match_in_known_sites": exact_locality_match,
            "knowledge_independence_status": "not_demonstrated_historical_catalog_may_overlap_prior_geological_knowledge",
            "model_evidence_role": "context_only_excluded_from_v0_6_training_validation_scoring",
            "model_exclusion_reason": "preview_is_incomplete_nonrandom_and_not_proven_knowledge_independent",
            "data_quality_flags_json": json.dumps(sorted(set(flags)), separators=(",", ":")),
        }
        rows.append(row)

    audit = {
        "catalog_record_id": f"GSI-OGD-CATALOG-{spec.key.upper()}",
        "source_id": SOURCE_ID,
        "catalog_key": spec.key,
        "commodity_scope": spec.commodity_scope,
        "catalog_nid": spec.catalog_nid,
        "catalog_uuid": spec.catalog_uuid,
        "resource_nid": spec.resource_nid,
        "resource_uuid": spec.resource_uuid,
        "catalog_title": first_value(catalog, "title"),
        "catalog_url": spec.catalog_url,
        "resource_url": spec.resource_url,
        "catalog_metadata_endpoint_url": spec.catalog_metadata_url,
        "resource_metadata_endpoint_url": spec.resource_metadata_url,
        "preview_endpoint_url": spec.preview_url,
        "workbook_metadata_url": workbook_url,
        "workbook_name": Path(workbook_url).name,
        "workbook_file_entity_id": first_value(resource, "field_datafile", "target_id"),
        "workbook_reported_bytes": first_value(resource, "field_file_size"),
        "catalog_published_timestamp": first_value(catalog, "created"),
        "catalog_changed_timestamp": first_value(catalog, "changed"),
        "resource_published_timestamp": first_value(resource, "created"),
        "resource_changed_timestamp": first_value(resource, "changed"),
        "source_columns_json": json.dumps(source_fields, separators=(",", ":")),
        "source_reported_total_rows": spec.expected_total,
        "preview_rows_returned": preview_count,
        "preview_coverage_pct": coverage_pct,
        "full_rows_not_exposed_in_preview": spec.expected_total - preview_count,
        "preview_access_status": "public_preview_endpoint_available",
        "source_file_http_status": file_status,
        "source_file_access_status": "interactive_download_purpose_form_and_captcha_required",
        "completeness_status": "complete_catalog_metadata_preview_rows_only",
        "source_selection_mechanism": "first_rows_returned_by_public_portal_preview_not_random",
        "license_name": LICENSE_NAME,
        "license_url": LICENSE_URL,
        "source_access_date": access_date,
        "model_evidence_role": "source_context_and_access_audit_only",
        "catalog_metadata_sha256": catalog_hash,
        "resource_metadata_sha256": resource_hash,
        "preview_response_sha256": preview_hash,
        "limitations": "The public preview is incomplete and non-random. The workbook was not acquired automatically because the portal requires a purpose form and CAPTCHA. Rows cannot establish current status, grade, tonnage, economic viability, knowledge independence, or a new discovery.",
    }
    hash_map = {
        f"catalog_{spec.catalog_nid}.json": catalog_hash,
        f"resource_{spec.resource_nid}.json": resource_hash,
        f"preview_{spec.resource_nid}.json": preview_hash,
    }
    return rows, audit, hash_map


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def upsert_source_registry(access_date: str) -> None:
    with SOURCE_REGISTRY.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["source_id"] != SOURCE_ID]
    rows.append({
        "source_id": SOURCE_ID,
        "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
        "title": "Location and salient features of eight mineral-deposit catalogs: bauxite, baryte, copper, diamond, gold, iron ore, lead-zinc and manganese",
        "release_or_reference_date": f"published 2013; resources updated 2014-04-17; accessed {access_date}",
        "url": "https://www.data.gov.in/catalog/location-aluminum-deposits-bauxite-india-and-its-salient-features",
        "download_url": "Eight exact catalog, resource, preview and workbook-metadata URLs are retained in the catalog audit.",
        "license_or_access_note": f"{LICENSE_NAME}; {LICENSE_URL}. Attribute the data provider and data.gov.in. Interactive workbook downloads require a purpose form and CAPTCHA.",
        "used_for": "Authoritative preview-limited deposit locality, state, toposheet, coordinate, commodity, host-rock, morphogenesis, formation and metallogenic context; source-access completeness audit.",
        "limitations": "The eight catalogs report 381 rows, but the public preview returned only 78 first rows and is not random. The full workbooks were not acquired automatically because downloads are CAPTCHA-gated. Catalogs are historical and not proven independent of MRDS or prior geological knowledge; all rows are excluded from model training, validation, scoring and candidate promotion.",
    })
    write_csv(SOURCE_REGISTRY, rows, fieldnames)


DEFINITIONS = {
    "record_id": "Stable identifier for one GSI OGD preview row.",
    "source_id": "Foreign key to source_registry.csv.",
    "catalog_key": "Stable short key for the source catalog.",
    "catalog_nid": "OGD catalog node identifier.",
    "catalog_uuid": "OGD catalog UUID.",
    "resource_nid": "OGD resource node identifier.",
    "resource_uuid": "OGD resource UUID.",
    "source_row_position": "One-based row position returned by the public preview endpoint.",
    "commodity_source": "Commodity wording published by GSI.",
    "normalized_material_ids_json": "JSON array of KHANAN ontology identifiers linked to the source commodity.",
    "normalized_material_names_json": "JSON array of normalized English material names.",
    "chemical_names_json": "JSON array of defensible chemical names; empty when none applies.",
    "symbols_or_formulae_json": "JSON array of element symbols or mineral formulae.",
    "model_target_names_json": "JSON array of matching v0.6 model targets; empty where the source commodity is outside v0.6.",
    "metallogenic_province_source": "GSI metallogenic province or belt wording.",
    "locality_source": "GSI locality wording.",
    "source_state_name": "State name as published by GSI in 2013.",
    "toposheet_source": "Survey of India toposheet reference published by GSI.",
    "latitude_source": "Verbatim source latitude point or range.",
    "longitude_source": "Verbatim source longitude point or range.",
    "source_latdd": "Source-provided decimal latitude where present; this can encode the first range endpoint rather than a midpoint.",
    "source_londd": "Source-provided decimal longitude where present; this can encode the first range endpoint rather than a midpoint.",
    "latitude_min": "Lower endpoint parsed from the source latitude.",
    "latitude_max": "Upper endpoint parsed from the source latitude.",
    "longitude_min": "Lower endpoint parsed from the source longitude.",
    "longitude_max": "Upper endpoint parsed from the source longitude.",
    "representative_latitude": "Source point latitude or arithmetic midpoint of a published latitude range.",
    "representative_longitude": "Source point longitude or arithmetic midpoint of a published longitude range.",
    "coordinate_geometry_type": "Whether the source supplies a point or independent coordinate ranges.",
    "representative_coordinate_method": "Method used to encode a representative mapping coordinate.",
    "coordinate_reference_system": "CRS encoding note; the source datum is not stated.",
    "coordinate_precision_note": "Limits on interpreting source coordinate precision and ranges.",
    "coordinate_span_km": "Great-circle diagonal across the parsed latitude/longitude range; zero for a point.",
    "h3_r6": "H3 resolution-6 cell containing the representative coordinate.",
    "state_or_ut_2011": "State or Union Territory from the 2011 district boundary at the representative coordinate.",
    "district_2011": "District from the 2011 boundary at the representative coordinate.",
    "centroid_in_source_state_2011_boundary": "Whether normalized source and 2011-boundary state names agree at the representative coordinate.",
    "host_rock_source": "GSI host-rock wording.",
    "morphogenesis_source": "GSI deposit morphology/genesis wording.",
    "formation_source": "GSI stratigraphic formation wording.",
    "source_catalog_total_rows": "Total rows reported by the portal for the catalog.",
    "preview_rows_returned": "Rows returned by the public server-side preview.",
    "preview_coverage_pct": "Preview rows divided by source-reported total rows.",
    "source_selection_mechanism": "How preview rows were selected; they are first rows, not a random sample.",
    "source_catalog_url": "Official OGD catalog page.",
    "source_resource_url": "Official OGD resource page.",
    "source_preview_endpoint_url": "Official public preview endpoint used for row extraction.",
    "source_workbook_metadata_url": "Workbook URL published in resource metadata; not an automatically acquired file in this release.",
    "source_release_date": "Resource release date published by OGD.",
    "source_updated_timestamp": "Resource update timestamp published by OGD.",
    "source_license": "Published source license name.",
    "source_license_url": "Official source license URL.",
    "nearest_known_site_record_id": "Nearest row in KHANAN's existing known-site layer regardless of material.",
    "nearest_known_site_km": "Great-circle distance to the nearest existing known-site row.",
    "nearest_known_comparable_material_record_id": "Nearest existing known-site row whose source materials match the catalog comparison terms.",
    "nearest_known_comparable_material_km": "Great-circle distance to the nearest comparable-material known-site row.",
    "nearest_known_comparable_material_within_25km": "Whether comparable-material known evidence lies within 25 km.",
    "exact_normalized_locality_match_in_known_sites": "Whether the normalized GSI locality exactly matches any known-site name.",
    "knowledge_independence_status": "Whether independence from historical geological knowledge is demonstrated.",
    "model_evidence_role": "Permitted role in the current release.",
    "model_exclusion_reason": "Why the row cannot enter training, validation, scoring or candidate promotion.",
    "data_quality_flags_json": "JSON array of row-level coordinate, state or comparison caveats.",
    "catalog_record_id": "Stable identifier for one audited GSI OGD catalog.",
    "commodity_scope": "Commodity named by the catalog.",
    "catalog_title": "Official OGD catalog title.",
    "catalog_url": "Official OGD catalog page.",
    "resource_url": "Official OGD resource page.",
    "catalog_metadata_endpoint_url": "Public OGD catalog metadata endpoint.",
    "resource_metadata_endpoint_url": "Public OGD resource metadata endpoint.",
    "preview_endpoint_url": "Public OGD preview endpoint.",
    "workbook_metadata_url": "Workbook URL published in OGD metadata.",
    "workbook_name": "Workbook filename published in OGD metadata.",
    "workbook_file_entity_id": "OGD file-entity identifier.",
    "workbook_reported_bytes": "Workbook byte size reported by OGD metadata.",
    "catalog_published_timestamp": "Catalog creation timestamp in OGD metadata.",
    "catalog_changed_timestamp": "Catalog update timestamp in OGD metadata.",
    "resource_published_timestamp": "Resource creation timestamp in OGD metadata.",
    "resource_changed_timestamp": "Resource update timestamp in OGD metadata.",
    "source_columns_json": "JSON array of source columns published by OGD.",
    "source_reported_total_rows": "Total rows reported by the OGD preview service.",
    "full_rows_not_exposed_in_preview": "Reported total less preview-returned rows.",
    "preview_access_status": "Observed status of the public preview endpoint.",
    "source_file_http_status": "HTTP status returned by the workbook metadata URL without completing the interactive form.",
    "source_file_access_status": "Observed workflow required to acquire the full workbook.",
    "completeness_status": "Explicit completeness classification for the published extraction.",
    "license_name": "Official source license name.",
    "license_url": "Official source license URL.",
    "source_access_date": "Date the public source endpoints were accessed.",
    "catalog_metadata_sha256": "SHA-256 of the cached catalog metadata response.",
    "resource_metadata_sha256": "SHA-256 of the cached resource metadata response.",
    "preview_response_sha256": "SHA-256 of the cached preview response.",
    "limitations": "Catalog-level interpretation and completeness limits.",
}


def upsert_data_dictionary() -> None:
    table_columns = {
        DEPOSIT_OUTPUT.name: DEPOSIT_FIELDS,
        AUDIT_OUTPUT.name: AUDIT_FIELDS,
    }
    with DATA_DICTIONARY.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["table"] not in table_columns]
    booleans = {
        "centroid_in_source_state_2011_boundary",
        "nearest_known_comparable_material_within_25km",
        "exact_normalized_locality_match_in_known_sites",
    }
    numeric = {
        "catalog_nid", "resource_nid", "source_row_position", "source_latdd", "source_londd",
        "latitude_min", "latitude_max", "longitude_min", "longitude_max",
        "representative_latitude", "representative_longitude", "coordinate_span_km",
        "source_catalog_total_rows", "preview_rows_returned", "preview_coverage_pct",
        "nearest_known_site_km", "nearest_known_comparable_material_km",
        "workbook_file_entity_id", "workbook_reported_bytes", "source_reported_total_rows",
        "full_rows_not_exposed_in_preview", "source_file_http_status",
    }
    units = {
        "source_latdd": "decimal degrees", "source_londd": "decimal degrees",
        "latitude_min": "decimal degrees", "latitude_max": "decimal degrees",
        "longitude_min": "decimal degrees", "longitude_max": "decimal degrees",
        "representative_latitude": "decimal degrees", "representative_longitude": "decimal degrees",
        "coordinate_span_km": "km", "nearest_known_site_km": "km",
        "nearest_known_comparable_material_km": "km", "preview_coverage_pct": "percent",
        "workbook_reported_bytes": "bytes",
    }
    for table, columns in table_columns.items():
        for column in columns:
            rows.append({
                "table": table,
                "column": column,
                "definition": DEFINITIONS[column],
                "data_type": "boolean" if column in booleans else "number" if column in numeric else "text",
                "unit": units.get(column, "JSON" if column.endswith("_json") else ""),
                "missing_value_policy": "Blank means unavailable, not applicable, or not exposed by the source; zero is retained only as a measured, reported, or derived zero.",
            })
    write_csv(DATA_DICTIONARY, rows, fieldnames)


def main() -> None:
    args = parse_args()
    boundaries = gpd.read_file(DISTRICT_BOUNDARIES).to_crs("EPSG:4326")
    known_sites = read_known_sites()
    grid_hash_before = sha256_file(OUT / "india_mining_prospectivity_grid_h3_r6.csv")
    candidate_hash_before = sha256_file(OUT / "india_mining_candidate_areas_validation_gated.csv")

    all_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    raw_hashes: dict[str, str] = {}
    for spec in CATALOGS:
        rows, audit, hashes = build_catalog(
            spec, args.access_date, args.refresh, known_sites, boundaries
        )
        all_rows.extend(rows)
        audit_rows.append(audit)
        raw_hashes.update(hashes)

    if len(all_rows) != sum(spec.expected_preview_rows for spec in CATALOGS):
        raise ValueError("Combined preview row count differs from the reviewed source contract")
    if len({row["record_id"] for row in all_rows}) != len(all_rows):
        raise ValueError("Duplicate preview record IDs")
    if any("outside_expected_india_bounds" in row["data_quality_flags_json"] for row in all_rows):
        raise ValueError("A representative coordinate is outside expected India bounds")

    all_rows.sort(key=lambda row: (row["catalog_key"], int(row["source_row_position"])))
    audit_rows.sort(key=lambda row: row["catalog_key"])
    write_csv(DEPOSIT_OUTPUT, all_rows, DEPOSIT_FIELDS)
    write_csv(AUDIT_OUTPUT, audit_rows, AUDIT_FIELDS)
    upsert_source_registry(args.access_date)
    upsert_data_dictionary()

    grid_hash_after = sha256_file(OUT / "india_mining_prospectivity_grid_h3_r6.csv")
    candidate_hash_after = sha256_file(OUT / "india_mining_candidate_areas_validation_gated.csv")
    if grid_hash_before != grid_hash_after or candidate_hash_before != candidate_hash_after:
        raise RuntimeError("Model outputs changed while building context-only GSI data")

    flags = Counter(
        flag
        for row in all_rows
        for flag in json.loads(row["data_quality_flags_json"])
    )
    validation = {
        "release_version": RELEASE_VERSION,
        "source_access_date": args.access_date,
        "source_id": SOURCE_ID,
        "catalog_count": len(CATALOGS),
        "source_reported_total_rows": sum(spec.expected_total for spec in CATALOGS),
        "preview_rows_published": len(all_rows),
        "full_rows_not_exposed_in_preview": sum(spec.expected_total for spec in CATALOGS) - len(all_rows),
        "combined_preview_coverage_pct": round(
            100.0 * len(all_rows) / sum(spec.expected_total for spec in CATALOGS), 6
        ),
        "commodity_row_counts": dict(sorted(Counter(row["catalog_key"] for row in all_rows).items())),
        "coordinate_point_rows": sum(row["coordinate_geometry_type"] == "point" for row in all_rows),
        "coordinate_range_rows": sum(row["coordinate_geometry_type"] == "coordinate_range" for row in all_rows),
        "representative_coordinates_in_expected_india_bounds": sum(
            6 <= float(row["representative_latitude"]) <= 38.6
            and 68 <= float(row["representative_longitude"]) <= 98.5
            for row in all_rows
        ),
        "representative_coordinates_matching_source_state_2011_boundary": sum(
            bool(row["centroid_in_source_state_2011_boundary"]) for row in all_rows
        ),
        "nearest_comparable_material_within_25km": sum(
            bool(row["nearest_known_comparable_material_within_25km"]) for row in all_rows
        ),
        "exact_normalized_locality_matches_in_known_sites": sum(
            bool(row["exact_normalized_locality_match_in_known_sites"]) for row in all_rows
        ),
        "data_quality_flag_counts": dict(sorted(flags.items())),
        "source_file_http_status_counts": dict(
            sorted(Counter(str(row["source_file_http_status"]) for row in audit_rows).items())
        ),
        "model_admission": {
            "training_rows": 0,
            "validation_rows": 0,
            "scoring_rows": 0,
            "candidate_promotions": 0,
            "reason": "Preview rows are incomplete, first-row selected, historical, and not proven independent of prior geological knowledge.",
        },
        "model_output_invariance": {
            "prospectivity_grid_sha256_before": grid_hash_before,
            "prospectivity_grid_sha256_after": grid_hash_after,
            "candidate_output_sha256_before": candidate_hash_before,
            "candidate_output_sha256_after": candidate_hash_after,
            "unchanged": True,
        },
        "raw_response_sha256": dict(sorted(raw_hashes.items())),
        "outputs": {
            DEPOSIT_OUTPUT.name: {"rows": len(all_rows), "sha256": sha256_file(DEPOSIT_OUTPUT)},
            AUDIT_OUTPUT.name: {"rows": len(audit_rows), "sha256": sha256_file(AUDIT_OUTPUT)},
        },
        "limitations": [
            "The public preview exposes 78 of 381 reported rows; the published rows are first rows, not a random sample.",
            "Full workbook downloads require an interactive purpose form and CAPTCHA and were not automated.",
            "Source DMS coordinate ranges are mapped by their arithmetic midpoint; no deposit footprint is inferred.",
            "The source datum is unstated; coordinates are encoded as EPSG:4326 solely for interoperable mapping.",
            "Historical GSI catalogs may overlap MRDS or prior geological knowledge and are not an independent discovery test.",
            "No preview row is evidence of a current mine, reserve, grade, tonnage, economic viability, access right, or new discovery.",
        ],
    }
    VALIDATION_OUTPUT.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "catalogs": len(CATALOGS),
        "reported_rows": validation["source_reported_total_rows"],
        "preview_rows": validation["preview_rows_published"],
        "coverage_pct": validation["combined_preview_coverage_pct"],
        "state_matches": validation["representative_coordinates_matching_source_state_2011_boundary"],
        "within_25km": validation["nearest_comparable_material_within_25km"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
