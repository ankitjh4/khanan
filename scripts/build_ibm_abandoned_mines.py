#!/usr/bin/env python3
"""Build an auditable table of IBM's 82 abandoned mine sites.

The Indian Bureau of Mines page identifies abandoned/orphaned mine sites for
reclamation or rehabilitation.  It publishes state, mine name, mineral, and
earlier lessee, but no district, coordinate, lease geometry, mine code, or
current legal/operational status.  This builder preserves those omissions and
excludes the records from prospectivity evidence until separately georeferenced
and status-checked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw" / "ibm_abandoned_mine_sites_en.html"
OUT = ROOT / "outputs"
OUTPUT = OUT / "india_ibm_abandoned_mine_sites.csv"
VALIDATION = OUT / "ibm_abandoned_mines_validation.json"

SOURCE_ID = "SRC_IBM_ABANDONED_MINE_SITES"
SOURCE_URL = "https://ibm.gov.in/IBMPortal/pages/Abandoned_Mine_Sites"
LANGUAGE_URL = "https://ibm.gov.in/IBMPortal/homepage/change_language_session"
ACCESS_DATE = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

SOURCE_REGISTRY_ROW = {
    "source_id": SOURCE_ID,
    "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
    "title": "List of 82 Abandoned Mine Sites Identified for Reclamation",
    "release_or_reference_date": "source page last-updated date and snapshot access date are recorded in the output; underlying site-identification period not stated",
    "url": SOURCE_URL,
    "download_url": "same as URL; the builder establishes the IBM English-language session before caching the page",
    "license_or_access_note": "Government of India public webpage; retain attribution and verify current IBM website reuse terms.",
    "used_for": "Authoritative named inventory of 82 abandoned/orphaned mine sites identified for reclamation or rehabilitation, with state, source mineral wording, and earlier lessee.",
    "limitations": "No district, coordinate, mine code, lease geometry, closure date, or controlling current status is published. Rows are excluded from prospectivity scoring and are not a current all-mines or all-leases register.",
}

STATE_ALIASES = {
    "Gujrat": "Gujarat",
    "Orissa": "Odisha",
    "Tamilnadu": "Tamil Nadu",
}

# Exact mappings for the 26 source spellings on the IBM page.  Source wording
# remains in mineral_source.  Variable-composition materials receive no formula
# here and are defined separately in the ontology.
MATERIAL_MAPPINGS = {
    "Calcite": (["group:calcium-and-limestone", "mineral:calcite"], ["Calcium and limestone", "Calcite"]),
    "Lime kanker": (["rock:lime-kankar"], ["Lime kankar"]),
    "Quartz": (["element:silicon", "mineral:quartz"], ["Silicon", "Quartz"]),
    "Feldspar": (["group:feldspar-group"], ["Feldspar group"]),
    "Manganese": (["element:manganese"], ["Manganese"]),
    "Iron ore": (["element:iron", "ore:iron-ore"], ["Iron", "Iron ore"]),
    "Chalk": (["group:calcium-and-limestone", "rock:chalk"], ["Calcium and limestone", "Chalk"]),
    "Fireclay": (["group:clay", "material:fire-clay"], ["Clay", "Fire clay"]),
    "Bauxite": (["element:aluminium", "ore:bauxite"], ["Aluminium", "Bauxite"]),
    "Mica": (["group:mica-group"], ["Mica group"]),
    "Gold": (["element:gold"], ["Gold"]),
    "Ochre": (["material:iron-oxide-pigments", "material:ochre"], ["Iron oxide pigments", "Ochre"]),
    "White eatrh": (["material:white-earth"], ["White earth"]),
    "Limestone": (["group:calcium-and-limestone", "rock:limestone"], ["Calcium and limestone", "Limestone"]),
    "Dolomite": (["mineral:dolomite"], ["Dolomite"]),
    "Barytes": (["mineral:baryte"], ["Baryte"]),
    "Laterite": (["rock:laterite"], ["Laterite"]),
    "Kyanite": (["mineral:kyanite"], ["Kyanite"]),
    "Chromite": (["element:chromium", "mineral:chromite"], ["Chromium", "Chromite"]),
    "Quartzite": (["element:silicon", "rock:quartzite"], ["Silicon", "Quartzite"]),
    "Pb-zn-cu": (["element:lead", "element:zinc", "element:copper"], ["Lead", "Zinc", "Copper"]),
    "Gypsum": (["mineral:gypsum"], ["Gypsum"]),
    "Qtrz/felds": (["element:silicon", "mineral:quartz", "group:feldspar-group"], ["Silicon", "Quartz", "Feldspar group"]),
    "Rock phosphate": (["element:phosphorus", "ore:phosphorite"], ["Phosphorus", "Phosphorite"]),
    "Pyrophyllite": (["mineral:pyrophyllite"], ["Pyrophyllite"]),
    "Iron": (["element:iron"], ["Iron"]),
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class TableParser(HTMLParser):
    """Minimal deterministic parser for simple HTML tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self.table = []
        elif self.table is not None and tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"td", "th"}:
            self.cell = []
        elif self.cell is not None and tag == "br":
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None:
            assert self.row is not None
            self.row.append(clean(" ".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                assert self.table is not None
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def fetch_source(refresh: bool) -> bytes:
    if RAW.exists() and RAW.stat().st_size >= 50_000 and not refresh:
        return RAW.read_bytes()

    headers = {"User-Agent": "Mozilla/5.0 (KHANAN reproducible public-data builder)"}
    session = requests.Session()
    first = session.get(SOURCE_URL, headers=headers, timeout=(20, 90))
    first.raise_for_status()
    token_match = re.search(r'name="_csrfToken" value="([^"]+)"', first.text)
    if not token_match:
        raise RuntimeError("IBM language-session CSRF token was not found")
    switched = session.post(
        LANGUAGE_URL,
        data={"lang": "0"},
        headers={**headers, "Referer": SOURCE_URL, "X-CSRF-Token": token_match.group(1)},
        timeout=(20, 90),
    )
    switched.raise_for_status()
    response = session.get(SOURCE_URL, headers=headers, timeout=(20, 90))
    response.raise_for_status()
    body = response.content
    decoded = body.decode(response.encoding or "utf-8", errors="replace")
    if len(body) < 50_000 or "LIST OF 82 ABANDONED MINE SITES" not in decoded or "Borra" not in decoded:
        raise RuntimeError("IBM English abandoned-mine page failed content validation")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    part = RAW.with_suffix(RAW.suffix + ".part")
    part.write_bytes(body)
    os.replace(part, RAW)
    return body


def parse_rows(body: bytes) -> tuple[list[dict], str]:
    text = body.decode("utf-8", errors="replace")
    updated = re.search(r"Last Updated On:\s*([0-9/]+)", text)
    if not updated:
        raise RuntimeError("IBM source-page last-updated date was not found")
    source_last_updated = datetime.strptime(updated.group(1), "%d/%m/%Y").date().isoformat()

    parser = TableParser()
    parser.feed(text)
    matching = [table for table in parser.tables if table and table[0] == ["Sl No.", "State", "Name of Mine Site", "Mineral", "Earlier Lessee"]]
    if len(matching) != 1:
        raise RuntimeError(f"expected one IBM abandoned-mine table; found {len(matching)}")
    source_rows = matching[0][1:]
    if len(source_rows) != 82 or any(len(row) != 5 for row in source_rows):
        raise RuntimeError(f"expected 82 five-column source rows; found {len(source_rows)}")

    rows = []
    for table_row_number, values in enumerate(source_rows, start=2):
        serial_source, state_source, mine_source, mineral_source, lessee_source = map(clean, values)
        if mineral_source not in MATERIAL_MAPPINGS:
            raise RuntimeError(f"unmapped IBM abandoned-mine material: {mineral_source!r}")
        material_ids, material_names = MATERIAL_MAPPINGS[mineral_source]
        serial = int(serial_source)
        rows.append({
            "record_id": f"IBM-ABANDONED-{serial:03d}",
            "record_type": "official_abandoned_mine_inventory_record",
            "source_id": SOURCE_ID,
            "source_serial_number": serial,
            "state_or_ut": STATE_ALIASES.get(state_source, state_source),
            "state_source": state_source,
            "district": "",
            "mine_name": mine_source,
            "mine_name_source": mine_source,
            "mineral_source": mineral_source,
            "normalized_material_ids_json": jdump(material_ids),
            "normalized_material_names_json": jdump(material_names),
            "earlier_lessee": lessee_source,
            "published_status": "abandoned_or_orphaned_site_identified_for_reclamation_or_rehabilitation",
            "published_status_scope": "one of 82 sites remaining after 24 of 106 identified sites became operational again",
            "current_legal_or_operational_status_verified": False,
            "latitude": "",
            "longitude": "",
            "coordinate_source": "",
            "location_precision": "state_and_named_mine_only",
            "model_evidence_role": "excluded_context_only",
            "model_exclusion_reason": "IBM page publishes no coordinate and does not establish current status; geocoding by name would be inferred evidence.",
            "source_url": SOURCE_URL,
            "source_page_last_updated": source_last_updated,
            "source_access_date": ACCESS_DATE,
            "source_page_sha256": hashlib.sha256(body).hexdigest(),
            "source_table_row_number": table_row_number,
            "quality_flags_json": jdump(["coordinates_not_published", "district_not_published", "current_status_not_independently_verified"]),
            "notes": "Source wording is preserved. Earlier lessee is historical context and must not be interpreted as the current owner or rights holder.",
        })
    return rows, source_last_updated


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def upsert_source_registry() -> None:
    path = OUT / "source_registry.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["source_id"] != SOURCE_ID]
    rows.append(SOURCE_REGISTRY_ROW)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def upsert_data_dictionary(columns: list[str]) -> None:
    path = OUT / "data_dictionary.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["table"] != OUTPUT.name]
    definitions = {
        "published_status": "Status wording assigned directly from the IBM page narrative; not a verified current legal or operational status.",
        "published_status_scope": "Source-page explanation of how the listed 82 sites relate to the 106 sites originally identified.",
        "current_legal_or_operational_status_verified": "Always false in this table because the page does not provide a controlling current-status record.",
        "model_evidence_role": "Whether the row may enter prospectivity training or scoring; these rows are context-only and excluded.",
        "source_page_sha256": "SHA-256 hash of the cached English IBM HTML source page.",
        "normalized_material_ids_json": "JSON array of stable material ontology identifiers mapped from the preserved source mineral wording.",
    }
    for column in columns:
        rows.append({
            "table": OUTPUT.name,
            "column": column,
            "definition": definitions.get(column, column.replace("_", " ").capitalize() + "."),
            "data_type": "boolean" if column == "current_legal_or_operational_status_verified" else "string",
            "unit": "JSON array" if column.endswith("_json") else "",
            "missing_value_policy": "Blank means the source did not publish the value; never infer a coordinate, district, or current status from a blank.",
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload the IBM source page")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    body = fetch_source(args.refresh)
    rows, source_last_updated = parse_rows(body)
    write_csv(OUTPUT, rows)

    narrative_text = clean(re.sub(r"<[^>]+>", " ", unescape(body.decode("utf-8", errors="replace"))))
    narrative_checks = {
        "297_sites_identified": bool(re.search(r"297 abandoned mine sites were identified", narrative_text, re.IGNORECASE)),
        "106_sites_requiring_reclamation": bool(re.search(r"identified 106 abandoned mine sites.*?requiring reclamation", narrative_text, re.IGNORECASE)),
        "24_sites_became_operational": bool(re.search(r"24 mine sites become operational again", narrative_text, re.IGNORECASE)),
        "82_sites_remaining": bool(re.search(r"respect of 82 abandoned sites only", narrative_text, re.IGNORECASE)),
    }

    state_counts = Counter(row["state_or_ut"] for row in rows)
    mineral_counts = Counter(row["mineral_source"] for row in rows)
    serials = [int(row["source_serial_number"]) for row in rows]
    validation = {
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "source_access_date": ACCESS_DATE,
        "source_page_last_updated": source_last_updated,
        "source_page_sha256": hashlib.sha256(body).hexdigest(),
        "source_page_bytes": len(body),
        "source_narrative_abandoned_sites_identified": 297,
        "source_narrative_sites_requiring_reclamation_or_rehabilitation": 106,
        "source_narrative_sites_became_operational_again": 24,
        "source_narrative_counts_verified_in_html": narrative_checks,
        "published_table_rows": len(rows),
        "unique_record_ids": len({row["record_id"] for row in rows}),
        "serial_numbers_contiguous_1_to_82": serials == list(range(1, 83)),
        "normalized_states": len(state_counts),
        "rows_by_state": dict(sorted(state_counts.items())),
        "distinct_source_mineral_terms": len(mineral_counts),
        "rows_by_source_mineral": dict(sorted(mineral_counts.items())),
        "rows_with_material_mapping": sum(bool(json.loads(row["normalized_material_ids_json"])) for row in rows),
        "rows_with_blank_coordinates": sum(not row["latitude"] and not row["longitude"] for row in rows),
        "rows_excluded_from_model_evidence": sum(row["model_evidence_role"] == "excluded_context_only" for row in rows),
        "guardrail": "These rows preserve an IBM historical-status inventory. They do not establish current abandonment, ownership, lease rights, production, coordinates, reserves/resources, or permission to enter land.",
    }
    validation["checks_pass"] = bool(
        validation["published_table_rows"] == validation["unique_record_ids"] == 82
        and validation["serial_numbers_contiguous_1_to_82"]
        and validation["rows_with_material_mapping"] == 82
        and validation["rows_with_blank_coordinates"] == 82
        and validation["rows_excluded_from_model_evidence"] == 82
        and all(narrative_checks.values())
        and bool(source_last_updated)
    )
    VALIDATION.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    upsert_source_registry()
    upsert_data_dictionary(list(rows[0]))
    release_path = OUT / "validation_report.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["ibm_abandoned_mine_sites"] = {
        "published_rows": validation["published_table_rows"],
        "source_page_last_updated": source_last_updated,
        "coordinates_published": 0,
        "rows_excluded_from_model_evidence": validation["rows_excluded_from_model_evidence"],
        "checks_pass": validation["checks_pass"],
    }
    release_path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not validation["checks_pass"]:
        raise SystemExit("IBM abandoned-mine validation failed")


if __name__ == "__main__":
    main()
