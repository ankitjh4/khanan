#!/usr/bin/env python3
"""Build the typed Alpha 3.0 candidate-area GeoJSON from the frozen CSV."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
SOURCE_PATH = OUT / "india_mining_candidate_areas_validation_gated.csv"
DICTIONARY_PATH = OUT / "data_dictionary.csv"
OUTPUT_PATH = OUT / "india_mining_candidate_areas_validation_gated.geojson"
RELEASE_VERSION = "v1.0-alpha.30"
EXPECTED_ROWS = 2784
SOURCE_TABLE = SOURCE_PATH.name
WKT_PATTERN = re.compile(r"^POLYGON \(\((.+)\)\)$")


def compact_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def row_sha256(fields: list[str], row: dict[str, str]) -> str:
    values = [row.get(field, "") for field in fields]
    return hashlib.sha256(compact_json(values).encode("utf-8")).hexdigest()


def parse_polygon_wkt(value: str) -> list[list[list[float]]]:
    match = WKT_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unsupported candidate geometry: {value[:80]}")
    ring = []
    for coordinate in match.group(1).split(","):
        parts = coordinate.strip().split()
        if len(parts) != 2:
            raise ValueError(f"Malformed coordinate: {coordinate}")
        longitude, latitude = map(float, parts)
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError(f"Coordinate outside WGS84 bounds: {coordinate}")
        ring.append([longitude, latitude])
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("Candidate polygon ring is not closed")
    return [ring]


def dictionary_types() -> dict[str, str]:
    with DICTIONARY_PATH.open(newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(handle)
        return {
            row["column"]: row["data_type"]
            for row in rows
            if row["table"] == SOURCE_TABLE
        }


def typed_value(value: str, data_type: str) -> Any:
    if value == "":
        return None
    if data_type == "integer":
        return int(value)
    if data_type == "number":
        return float(value)
    if data_type == "boolean":
        normalized = value.strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"Invalid boolean value: {value}")
        return normalized == "true"
    if data_type.startswith("JSON"):
        return json.loads(value)
    return value


def main() -> None:
    types = dictionary_types()
    features = []
    source_ids = set()
    with SOURCE_PATH.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if set(fields) != set(types):
            raise ValueError(
                {
                    "dictionary_columns_missing": sorted(set(fields) - set(types)),
                    "dictionary_columns_extra": sorted(set(types) - set(fields)),
                }
            )
        for row in reader:
            record_id = row["record_id"].strip()
            if not record_id or record_id in source_ids:
                raise ValueError(f"Blank or duplicate record_id: {record_id}")
            source_ids.add(record_id)
            properties = {
                field: typed_value(row[field], types[field])
                for field in fields
                if field != "cell_boundary_wkt"
            }
            properties["source_csv_row_sha256"] = row_sha256(fields, row)
            features.append(
                {
                    "type": "Feature",
                    "id": record_id,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": parse_polygon_wkt(row["cell_boundary_wkt"]),
                    },
                    "properties": properties,
                }
            )
    if len(features) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} features, found {len(features)}")
    payload = {
        "type": "FeatureCollection",
        "name": "KHANAN validation-gated candidate areas",
        "release_version": RELEASE_VERSION,
        "coordinate_reference_system": "RFC 7946 WGS84 longitude/latitude",
        "interpretation": (
            "Model-generated reconnaissance hypotheses; not discoveries, reserves, "
            "resources, grades, legal rights or drill targets."
        ),
        "features": features,
    }
    OUTPUT_PATH.write_text(compact_json(payload) + "\n", encoding="utf-8")
    print(
        {
            "output": str(OUTPUT_PATH),
            "features": len(features),
            "properties": len(features[0]["properties"]),
            "bytes": OUTPUT_PATH.stat().st_size,
        }
    )


if __name__ == "__main__":
    main()
