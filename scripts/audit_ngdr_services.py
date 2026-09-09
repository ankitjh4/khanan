#!/usr/bin/env python3
"""Audit selected NGDR/GSI guest OGC layers without republishing feature values.

The public output is a metadata inventory: service availability, feature counts,
bounding boxes, declared schemas, and an explicit model-readiness decision. Raw
capabilities, schemas, the one-feature probes, and the GSI policy PDF are cached
under sources/raw/, which is excluded from Git and release bundles.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RAW = ROOT / "sources" / "raw" / "ngdr_service_audit"

GUEST_URL = "https://geodataindia.gov.in/guestuser"
OGC_PROXY_URL = "https://geodataindia.gov.in/guestuser/wmsurl128/"
POLICY_URL = (
    "https://geodataindia.gov.in/assets/Document_Pdf/"
    "4.%20Data%20Dissemination%20policy%202019.pdf"
)
RELEASE_VERSION = "v1.0-alpha.3"

LAYERS = [
    {
        "name": "cite:commodity_pan_india_mineral_map_ngdr",
        "family": "mineral_occurrence",
        "use": "National commodity occurrence and resource-context evidence.",
        "unit_status": "not_applicable_to_identity_and_location_fields; grade/resource fields require source-specific definitions",
    },
    {
        "name": "cite:critical_mineral_gcs_ngdr",
        "family": "critical_mineral_occurrence",
        "use": "Critical-mineral occurrence, host-rock, grade-text, reserve-text, and reference context.",
        "unit_status": "grade_and_reserve_units_not_established_from_service_schema",
    },
    {
        "name": "cite:mineralization_gcs_ngdr",
        "family": "mineralization",
        "use": "Mapped mineralization evidence and commodity context.",
        "unit_status": "not_applicable_to_identity_and_location_fields; occurrence attributes require source definitions",
    },
    {
        "name": "cite:stream_sediments_gcs_ngdr",
        "family": "stream_sediment_geochemistry",
        "use": "NGCM multi-element stream-sediment geochemical evidence.",
        "unit_status": "analytical_units_methods_detection_limits_not_published_in_service_schema",
    },
    {
        "name": "cite:soil_c_horizon_gcs_ngdr",
        "family": "soil_c_horizon_geochemistry",
        "use": "NGCM multi-element C-horizon soil geochemical evidence.",
        "unit_status": "analytical_units_methods_detection_limits_not_published_in_service_schema",
    },
    {
        "name": "cite:soil_regolith_gcs_ngdr",
        "family": "soil_regolith_geochemistry",
        "use": "NGCM multi-element regolith geochemical evidence.",
        "unit_status": "analytical_units_methods_detection_limits_not_published_in_service_schema",
    },
    {
        "name": "cite:india_soil",
        "family": "soil_mapping",
        "use": "National soil polygons and declared depth, mineral, pH, drainage, texture, erosion, salinity, sodicity, taxonomy, and district fields.",
        "unit_status": "mixed_attributes; units_and_class_definitions_not_fully_established_from_service_schema",
    },
    {
        "name": "cite:magnetic_gcs_ngdr",
        "family": "magnetics",
        "use": "Observed magnetic field, IGRF, and magnetic-anomaly evidence.",
        "unit_status": "field_names_suggest_nt_but_units_and_processing_method_not_established_from_service_schema",
    },
    {
        "name": "cite:gravity_gcs_ngdr",
        "family": "gravity",
        "use": "Observed gravity, theoretical gravity, elevation, and Bouguer-anomaly evidence.",
        "unit_status": "units_reduction_parameters_and_processing_method_not_established_from_service_schema",
    },
    {
        "name": "cite:lithology_gcs_ngdr",
        "family": "lithology",
        "use": "National lithological polygon context.",
        "unit_status": "not_applicable_to_categorical_map_units; map_scale_and_class_definitions_require_source_metadata",
    },
    {
        "name": "cite:geology_2m_gcs_ngdr",
        "family": "regional_geology",
        "use": "Two-million-scale age, group, supergroup, and stratigraphic context.",
        "unit_status": "not_applicable_to_categorical_map_units; geometry completeness and source definitions require review",
    },
]

SOURCE_ROWS = [
    {
        "source_id": "SRC_GSI_NGDR_GUEST_OGC_CATALOG",
        "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
        "title": "National Geoscience Data Repository guest OGC service catalog",
        "release_or_reference_date": "live service; audited 2026-09-10",
        "url": GUEST_URL,
        "download_url": OGC_PROXY_URL,
        "license_or_access_note": "Guest map and OGC service are publicly viewable. Raw feature redistribution is not authorized by KHANAN; consult the GSI Data Sharing and Accessibility Policy and obtain any required registration or permission.",
        "used_for": "Metadata-only audit of authoritative mineral, geochemistry, geophysics, soil, lithology, and geology layers. No raw feature values are published or used in scoring in this release.",
        "limitations": "Live service content can change. Analytical units, methods, detection limits, scale, and redistribution status are not sufficiently established for model integration from service schemas alone.",
    },
    {
        "source_id": "SRC_GSI_DATA_SHARING_POLICY_2019",
        "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
        "title": "Data Sharing and Accessibility Policy of Geological Survey of India, 2019",
        "release_or_reference_date": "2019; audited 2026-09-10",
        "url": POLICY_URL,
        "download_url": POLICY_URL,
        "license_or_access_note": "Policy distinguishes open viewing from registered downloads and imposes GSI attribution and restrictions on transfer or redistribution of supplied thematic data. Obtain authoritative legal review or written permission before republishing raw NGDR features.",
        "used_for": "Controls KHANAN's access, attribution, caching, redistribution, and derivative-data decision for NGDR/GSI evidence.",
        "limitations": "KHANAN does not provide legal advice. Applicability can depend on access class, dataset, user category, agreement, and current portal terms.",
    },
]

FIELD_DEFINITIONS = {
    "source_id": ("Source-registry identifier for the audited service.", "text", None),
    "layer_id": ("Stable KHANAN identifier derived from the WFS feature-type name.", "text", None),
    "service_type": ("OGC service used for the metadata audit.", "category", None),
    "feature_type_name": ("Exact namespace-qualified WFS feature-type name.", "text", None),
    "layer_title": ("Layer title published in WFS capabilities.", "text", None),
    "publisher": ("Organization responsible for the service.", "text", None),
    "evidence_family": ("KHANAN evidence-family classification.", "category", None),
    "intended_use": ("Potential scientific role if access, units, methods, and validation gates are satisfied.", "text", None),
    "wms_available": ("Whether the named layer was present in WMS capabilities.", "boolean", None),
    "wfs_available": ("Whether the named feature type was present in WFS capabilities.", "boolean", None),
    "feature_probe_succeeded": ("Whether a bounded one-feature GeoJSON request succeeded.", "boolean", None),
    "feature_count_reported": ("Total feature count reported by the live WFS GeoJSON response; no feature values are republished.", "integer", "features"),
    "sample_geometry_type": ("Geometry type of the single bounded probe when its geometry was non-null.", "category", None),
    "declared_geometry_field": ("Geometry-property name declared by DescribeFeatureType.", "text", None),
    "declared_geometry_type": ("GML geometry-property type declared by DescribeFeatureType.", "text", None),
    "coordinate_reference_system": ("Default SRS published in WFS capabilities.", "text", None),
    "bbox_west": ("Western WGS84 bounding coordinate published in WFS capabilities.", "number", "decimal degrees"),
    "bbox_south": ("Southern WGS84 bounding coordinate published in WFS capabilities.", "number", "decimal degrees"),
    "bbox_east": ("Eastern WGS84 bounding coordinate published in WFS capabilities.", "number", "decimal degrees"),
    "bbox_north": ("Northern WGS84 bounding coordinate published in WFS capabilities.", "number", "decimal degrees"),
    "bbox_valid_wgs84": ("Whether the four capability bounding coordinates form a plausible ordered WGS84 box.", "boolean", None),
    "bbox_raw_json": ("JSON object preserving capability bounding coordinates, including any invalid service sentinel.", "JSON object", None),
    "attribute_count": ("Count of non-geometry properties declared by DescribeFeatureType.", "integer", "fields"),
    "attribute_schema_json": ("JSON array of declared non-geometry field names and XML schema types; contains no observation values.", "JSON array", None),
    "access_surface": ("Portal surface used to establish the guest session.", "text", None),
    "access_level": ("Observed access class for this audit.", "category", None),
    "licence_policy_url": ("Official GSI policy consulted for the publication decision.", "URL", None),
    "redistribution_class": ("KHANAN redistribution decision for this release.", "category", None),
    "unit_metadata_status": ("Whether measurement units and required analytical metadata are established.", "category", None),
    "coordinate_metadata_status": ("Coordinate metadata state observed in the service.", "category", None),
    "model_evidence_status": ("Whether the layer contributes to current prospectivity scores.", "category", None),
    "model_evidence_exclusion_reason": ("Reason the layer is not yet admitted to production scoring.", "text", None),
    "raw_feature_values_published": ("Whether KHANAN publishes feature-property values from this service.", "boolean", None),
    "capabilities_accessed_on": ("Local calendar date of the live service audit.", "ISO date", None),
    "wfs_request_template": ("Reproducible request parameters for authorized future retrieval; the guest session must be established first.", "text", None),
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_layer_id(feature_type_name: str) -> str:
    return "NGDR-WFS-" + feature_type_name.split(":", 1)[-1].upper().replace("_", "-")


def fetch(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, timeout: int = 120) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after retries: {url} {params or {}}") from last_error


def xml_nodes(root: ET.Element, wanted: str) -> list[ET.Element]:
    return [node for node in root.iter() if local_name(node.tag) == wanted]


def child_text(node: ET.Element, wanted: str) -> str:
    for child in node:
        if local_name(child.tag) == wanted:
            return (child.text or "").strip()
    return ""


def parse_wfs_capabilities(raw: bytes) -> dict[str, dict[str, Any]]:
    root = ET.fromstring(raw)
    result: dict[str, dict[str, Any]] = {}
    for feature_type in xml_nodes(root, "FeatureType"):
        name = child_text(feature_type, "Name")
        if not name:
            continue
        bbox = next((x for x in feature_type if local_name(x.tag) == "LatLongBoundingBox"), None)
        result[name] = {
            "title": child_text(feature_type, "Title"),
            "srs": child_text(feature_type, "SRS"),
            "bbox_west": float(bbox.attrib["minx"]) if bbox is not None else None,
            "bbox_south": float(bbox.attrib["miny"]) if bbox is not None else None,
            "bbox_east": float(bbox.attrib["maxx"]) if bbox is not None else None,
            "bbox_north": float(bbox.attrib["maxy"]) if bbox is not None else None,
        }
    return result


def parse_wms_names(raw: bytes) -> set[str]:
    root = ET.fromstring(raw)
    names: set[str] = set()
    for layer in xml_nodes(root, "Layer"):
        name = child_text(layer, "Name")
        if name:
            names.add(name)
    return names


def parse_schema(raw: bytes, layer_name: str) -> tuple[list[dict[str, Any]], str, str]:
    root = ET.fromstring(raw)
    basename = layer_name.split(":", 1)[-1]
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sequence in xml_nodes(root, "sequence"):
        for element in sequence.iter():
            if local_name(element.tag) != "element":
                continue
            name = element.attrib.get("name", "").strip()
            field_type = element.attrib.get("type", "").strip()
            if not name or name == basename or name in seen:
                continue
            seen.add(name)
            fields.append(
                {
                    "name": name,
                    "type": field_type,
                    "min_occurs": element.attrib.get("minOccurs", "1"),
                    "max_occurs": element.attrib.get("maxOccurs", "1"),
                    "nillable": element.attrib.get("nillable", "false"),
                }
            )
    geometry = next(
        (
            field
            for field in fields
            if field["type"].startswith("gml:")
            or field["type"].endswith("PropertyType")
            or field["name"].lower() in {"geom", "geometry", "the_geom"}
        ),
        None,
    )
    non_geometry = [field for field in fields if field is not geometry]
    return non_geometry, (geometry or {}).get("name", ""), (geometry or {}).get("type", "")


def valid_wgs84_bbox(bbox: dict[str, Any]) -> bool:
    west = bbox.get("bbox_west")
    south = bbox.get("bbox_south")
    east = bbox.get("bbox_east")
    north = bbox.get("bbox_north")
    return bool(
        all(value is not None for value in [west, south, east, north])
        and -180 <= west <= east <= 180
        and -90 <= south <= north <= 90
    )


def upsert_source_registry() -> None:
    path = OUT / "source_registry.csv"
    existing = pd.read_csv(path, keep_default_na=False)
    incoming = pd.DataFrame(SOURCE_ROWS)
    retained = existing.loc[~existing["source_id"].isin(incoming["source_id"])].copy()
    pd.concat([retained, incoming], ignore_index=True).to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def upsert_dictionary(columns: list[str]) -> None:
    path = OUT / "data_dictionary.csv"
    existing = pd.read_csv(path, keep_default_na=False)
    table_name = "ngdr_service_inventory.csv"
    retained = existing.loc[existing["table"] != table_name].copy()
    rows = []
    for column in columns:
        definition, data_type, unit = FIELD_DEFINITIONS[column]
        rows.append(
            {
                "table": table_name,
                "column": column,
                "definition": definition,
                "data_type": data_type,
                "unit": unit or "",
                "missing_value_policy": "Blank means the live service did not publish or the audit could not establish the value; never infer zero.",
            }
        )
    pd.concat([retained, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def update_release_validation(audit: dict[str, Any]) -> None:
    path = OUT / "validation_report.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["ngdr_service_audit"] = {
        "selected_layer_rows": audit["selected_layer_rows"],
        "wms_named_layer_count": audit["wms_named_layer_count"],
        "wfs_feature_type_count": audit["wfs_feature_type_count"],
        "selected_layer_feature_count_reported_total": audit["selected_layer_feature_count_reported_total"],
        "selected_layers_available_in_wfs": audit["selected_layers_available_in_wfs"],
        "selected_layers_with_successful_feature_probe": audit["selected_layers_with_successful_feature_probe"],
        "selected_layers_with_valid_wgs84_bbox": audit["selected_layers_with_valid_wgs84_bbox"],
        "selected_layers_with_invalid_or_missing_wgs84_bbox": audit["selected_layers_with_invalid_or_missing_wgs84_bbox"],
        "raw_feature_values_published": False,
        "model_evidence_status": "not_integrated",
        "checks_pass": audit["checks_pass"],
    }
    path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    accessed_on = date.today().isoformat()
    accessed_at = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; KHANAN metadata audit/1.0; public-interest geoscience research)",
            "Referer": GUEST_URL,
        }
    )
    guest = fetch(session, GUEST_URL, timeout=60)
    if "National Geoscience Data Repository" not in guest.text and len(guest.content) < 50_000:
        raise RuntimeError("NGDR guest session did not return the expected application page")

    wms_response = fetch(
        session,
        OGC_PROXY_URL,
        params={"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetCapabilities"},
    )
    wfs_response = fetch(
        session,
        OGC_PROXY_URL,
        params={"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetCapabilities"},
    )
    policy_response = fetch(session, POLICY_URL)
    if not policy_response.content.startswith(b"%PDF"):
        raise RuntimeError("GSI policy URL did not return a PDF")

    raw_files = {
        "wms_capabilities.xml": wms_response.content,
        "wfs_capabilities.xml": wfs_response.content,
        "gsi_data_sharing_and_accessibility_policy_2019.pdf": policy_response.content,
    }
    for filename, content in raw_files.items():
        (RAW / filename).write_bytes(content)

    wms_names = parse_wms_names(wms_response.content)
    wfs_types = parse_wfs_capabilities(wfs_response.content)
    rows: list[dict[str, Any]] = []
    probe_summary: list[dict[str, Any]] = []

    for layer in LAYERS:
        name = layer["name"]
        if name not in wfs_types:
            raise RuntimeError(f"selected NGDR feature type is missing: {name}")
        schema_response = fetch(
            session,
            OGC_PROXY_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "1.0.0",
                "REQUEST": "DescribeFeatureType",
                "typeName": name,
            },
        )
        probe_response = fetch(
            session,
            OGC_PROXY_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "1.0.0",
                "REQUEST": "GetFeature",
                "typeName": name,
                "maxFeatures": 1,
                "outputFormat": "application/json",
            },
        )
        safe_name = name.replace(":", "__")
        (RAW / f"describe_{safe_name}.xml").write_bytes(schema_response.content)
        (RAW / f"probe_{safe_name}.geojson").write_bytes(probe_response.content)

        attributes, geom_field, geom_type = parse_schema(schema_response.content, name)
        probe = probe_response.json()
        feature_count = probe.get("totalFeatures", probe.get("numberMatched"))
        feature_count = int(feature_count) if feature_count is not None else None
        features = probe.get("features") or []
        geometry = features[0].get("geometry") if features else None
        sample_geometry_type = geometry.get("type", "") if isinstance(geometry, dict) else ""
        capability = wfs_types[name]
        bbox_raw = {
            key: capability[key]
            for key in ["bbox_west", "bbox_south", "bbox_east", "bbox_north"]
        }
        bbox_is_valid = valid_wgs84_bbox(bbox_raw)
        wms_available = name in wms_names or name.split(":", 1)[-1] in wms_names
        row = {
            "source_id": "SRC_GSI_NGDR_GUEST_OGC_CATALOG",
            "layer_id": stable_layer_id(name),
            "service_type": "WFS 1.0.0 with WMS 1.1.1 availability cross-check",
            "feature_type_name": name,
            "layer_title": capability["title"],
            "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
            "evidence_family": layer["family"],
            "intended_use": layer["use"],
            "wms_available": bool(wms_available),
            "wfs_available": True,
            "feature_probe_succeeded": bool(features and feature_count and feature_count > 0),
            "feature_count_reported": feature_count,
            "sample_geometry_type": sample_geometry_type,
            "declared_geometry_field": geom_field,
            "declared_geometry_type": geom_type,
            "coordinate_reference_system": capability["srs"],
            "bbox_west": capability["bbox_west"] if bbox_is_valid else None,
            "bbox_south": capability["bbox_south"] if bbox_is_valid else None,
            "bbox_east": capability["bbox_east"] if bbox_is_valid else None,
            "bbox_north": capability["bbox_north"] if bbox_is_valid else None,
            "bbox_valid_wgs84": bbox_is_valid,
            "bbox_raw_json": json.dumps(bbox_raw, separators=(",", ":")),
            "attribute_count": len(attributes),
            "attribute_schema_json": json.dumps(attributes, ensure_ascii=False, separators=(",", ":")),
            "access_surface": GUEST_URL,
            "access_level": "guest_open_view_and_bounded_machine_readable_probe",
            "licence_policy_url": POLICY_URL,
            "redistribution_class": "metadata_only_pending_dataset_specific_licence_review_or_permission",
            "unit_metadata_status": layer["unit_status"],
            "coordinate_metadata_status": (
                "default_srs_and_plausible_wgs84_bbox_published; record_precision_and_survey_method_require_source_metadata"
                if bbox_is_valid
                else "default_srs_published_but_capability_bbox_contains_invalid_numeric_sentinel; bbox_withheld_from_numeric_columns"
            ),
            "model_evidence_status": "not_integrated",
            "model_evidence_exclusion_reason": "Raw redistribution authority and required units, methods, detection limits, scale, processing, and missingness metadata are not fully established for production scoring.",
            "raw_feature_values_published": False,
            "capabilities_accessed_on": accessed_on,
            "wfs_request_template": "Establish GET /guestuser session, then GET /guestuser/wmsurl128/ with SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature&typeName=<feature_type_name>&outputFormat=application/json",
        }
        rows.append(row)
        probe_summary.append(
            {
                "feature_type_name": name,
                "feature_count_reported": feature_count,
                "sample_geometry_type": sample_geometry_type or None,
                "declared_geometry_type": geom_type or None,
                "attribute_count": len(attributes),
                "schema_sha256": sha256_bytes(schema_response.content),
                "bounded_probe_sha256": sha256_bytes(probe_response.content),
            }
        )

    inventory = pd.DataFrame(rows)
    output_path = OUT / "ngdr_service_inventory.csv"
    inventory.to_csv(output_path, index=False, quoting=csv.QUOTE_MINIMAL)
    upsert_source_registry()
    upsert_dictionary(list(inventory.columns))

    total_features = int(inventory["feature_count_reported"].sum())
    validation = {
        "release_version": RELEASE_VERSION,
        "audit_scope": "Metadata and bounded service probes only; no raw NGDR feature values are included in public outputs or model scoring.",
        "accessed_at_utc": accessed_at,
        "guest_portal_url": GUEST_URL,
        "ogc_proxy_url": OGC_PROXY_URL,
        "gsi_policy_url": POLICY_URL,
        "guest_page_status_code": guest.status_code,
        "wms_named_layer_count": len(wms_names),
        "wfs_feature_type_count": len(wfs_types),
        "selected_layer_rows": int(len(inventory)),
        "selected_layers_available_in_wms": int(inventory["wms_available"].sum()),
        "selected_layers_available_in_wfs": int(inventory["wfs_available"].sum()),
        "selected_layers_with_successful_feature_probe": int(inventory["feature_probe_succeeded"].sum()),
        "selected_layers_with_valid_wgs84_bbox": int(inventory["bbox_valid_wgs84"].sum()),
        "selected_layers_with_invalid_or_missing_wgs84_bbox": int((~inventory["bbox_valid_wgs84"]).sum()),
        "selected_layer_feature_count_reported_total": total_features,
        "selected_layers": probe_summary,
        "raw_cache": {
            filename: {"bytes": len(content), "sha256": sha256_bytes(content)}
            for filename, content in raw_files.items()
        },
        "public_output_contains_feature_property_values": False,
        "production_model_uses_ngdr_feature_values": False,
        "redistribution_decision": "Publish service metadata and reproducibility instructions only until dataset-specific reuse authority and scientific measurement metadata are established.",
    }
    validation["checks_pass"] = bool(
        validation["wms_named_layer_count"] >= 1_000
        and validation["wfs_feature_type_count"] >= 700
        and validation["selected_layers_available_in_wfs"] == len(LAYERS)
        and validation["selected_layers_with_successful_feature_probe"] == len(LAYERS)
        and validation["selected_layer_feature_count_reported_total"] > 2_000_000
        and not validation["public_output_contains_feature_property_values"]
        and not validation["production_model_uses_ngdr_feature_values"]
    )
    (OUT / "ngdr_service_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    update_release_validation(validation)
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not validation["checks_pass"]:
        raise SystemExit("NGDR service audit validation failed")


if __name__ == "__main__":
    main()
