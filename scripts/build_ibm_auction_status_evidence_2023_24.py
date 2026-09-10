#!/usr/bin/env python3
"""Build dated official-secondary status evidence for five Andhra IBM auction rows.

This layer does not promote a block to an operating mine and does not create
geometry.  It records dated public-government evidence separately from the IBM
yearbook row and preserves source conflicts, especially the Mincheri auction
date discrepancy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import requests
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "outputs" / "india_ibm_auctioned_mineral_concessions_2023_24.csv"
OUTPUT_CSV = ROOT / "outputs" / "india_ibm_auctioned_concession_status_evidence_2023_24.csv"
VALIDATION_JSON = ROOT / "outputs" / "ibm_auction_status_evidence_2023_24_validation.json"
RAW = ROOT / "sources" / "raw" / "ibm_auction_status_evidence_2023_24"

PRAKASAM_SOURCE_ID = "SRC_AP_PRAKASAM_JSW_IRON_BLOCK_STATUS_2026"
PRAKASAM_URL = "https://prakasam.ap.gov.in/invest-in-prakasam/"
PRAKASAM_CACHE = RAW / "prakasam_invest_in_prakasam.html"
MINES_SOURCE_ID = "SRC_MINES_NMMC_AUCTION_OPERATIONALIZATION_JAN2025"
MINES_URL = "https://mines.gov.in/admin/storage/ckeditor/DAY_1_PPT_4_1737542818.pdf"
MINES_CACHE = RAW / "national_mining_ministers_conference_auction_operationalization_jan2025.pdf"

TARGET_IDS = [f"IBM-IMYB2024-AUCTION-{value:03d}" for value in range(1, 6)]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, path: Path, refresh: bool) -> None:
    if path.exists() and not refresh:
        return
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)


def html_text(path: Path) -> str:
    parser = TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parser.parts)


def load_ibm_rows() -> dict[str, dict[str, str]]:
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        rows = {row["record_id"]: row for row in csv.DictReader(handle) if row["record_id"] in TARGET_IDS}
    if sorted(rows) != TARGET_IDS:
        raise RuntimeError(f"Expected Andhra target rows {TARGET_IDS}; found {sorted(rows)}")
    return rows


def event(event_type: str, event_date: str, detail: str) -> dict[str, str]:
    return {"event_type": event_type, "event_date": event_date, "detail_source": detail}


def build_rows(access_date: str) -> tuple[list[dict], dict]:
    ibm = load_ibm_rows()
    prakasam_text = html_text(PRAKASAM_CACHE)
    required_html = [
        "Addankivaripalem", "Lakshmakapalle North", "Lakshmakapalle South",
        "9.140 sq. km", "11.947 sq. km", "18.258 sq. km",
        "Prospecting Licence executed March 2025; 38 of 89 boreholes completed",
        "Prospecting Licence executed March 2025; 21 of 66 boreholes completed",
        "Letter of Intent Issued", "11 September 2023",
        "Prospecting Licence Executed", "4 March 2025 (3-year validity)",
        "Revenue Department NOC Obtained", "20 January 2025",
        "Form-C Approval — Addankivaripalem", "19 December 2025",
        "Form-C Approval — Lakshmakapalle North", "7 January 2026",
        "Last Updated:", "Sep 02, 2026",
    ]
    missing_html = [value for value in required_html if value not in prakasam_text]
    if missing_html:
        raise RuntimeError(f"Prakasam source changed; missing expected text: {missing_html}")

    pdf = PdfReader(str(MINES_CACHE))
    if len(pdf.pages) != 75:
        raise RuntimeError(f"Expected 75-page Ministry presentation; found {len(pdf.pages)}")
    ministry_page = pdf.pages[49].extract_text() or ""
    required_pdf = [
        "LoI Pending Cases in CL blocks-Andhra pradesh", "Mincheri", "RF", "Iron Ore",
        "14.04.2024", "1327", "12.6", "South-West", "Mining", "Limited",
        "Adakula", "Semi-", "Precious", "stone", "19.03.2024", "36.997", "3.6",
        "Satyanarayana", "LOI to be issued",
    ]
    missing_pdf = [value for value in required_pdf if value not in ministry_page]
    if missing_pdf:
        raise RuntimeError(f"Ministry source changed; missing expected page-50 text: {missing_pdf}")

    prakasam_hash = sha256(PRAKASAM_CACHE)
    mines_hash = sha256(MINES_CACHE)
    common_jsw_events = [
        event("auction_date", "2023-07-28", "Date of Auction: 28 July 2023"),
        event("letter_of_intent_issued", "2023-09-11", "Letter of Intent Issued: 11 September 2023"),
        event("revenue_department_noc_obtained", "2025-01-20", "Revenue Department NOC Obtained: 20 January 2025"),
        event("prospecting_licence_executed", "2025-03-04", "Prospecting Licence Executed: 4 March 2025 (3-year validity)"),
    ]

    evidence = {
        TARGET_IDS[0]: {
            "source_id": MINES_SOURCE_ID,
            "source_url": MINES_URL,
            "source_type": "pdf",
            "source_reference_date": "2025-01-22",
            "source_reference_date_basis": "PDF creation metadata; presentation cover states January 2025",
            "source_pdf_page": 50,
            "source_hash": mines_hash,
            "source_status_summary": "LOI to be issued",
            "events": [
                event("auction_date", "2024-03-19", "Date of auction: 19.03.2024"),
                event("letter_of_intent_pending", "", "LOI to be issued"),
            ],
            "source_area_ha": 36.997,
            "preferred_bidder_source": "Shri P. Satyanarayana",
            "final_bid_pct_source": 3.6,
            "completed_borehole_count_source": "",
            "planned_borehole_count_source": "",
            "quality_flags": ["official_secondary_historical_status_snapshot", "controlling_licence_document_not_reviewed"],
            "status_evidence_level": "official_secondary_historical_snapshot",
        },
        TARGET_IDS[1]: {
            "source_id": PRAKASAM_SOURCE_ID,
            "source_url": PRAKASAM_URL,
            "source_type": "html",
            "source_reference_date": "2026-09-02",
            "source_reference_date_basis": "Page last-updated date",
            "source_pdf_page": "",
            "source_hash": prakasam_hash,
            "source_status_summary": "Prospecting Licence executed March 2025; 38 of 89 boreholes completed; Form-C approval dated 19 December 2025",
            "events": [*common_jsw_events, event("form_c_approval", "2025-12-19", "Form-C Approval — Addankivaripalem: 19 December 2025")],
            "source_area_ha": 914.0,
            "preferred_bidder_source": "",
            "final_bid_pct_source": "",
            "completed_borehole_count_source": 38,
            "planned_borehole_count_source": 89,
            "quality_flags": ["official_secondary_current_page", "shared_jsw_milestones_applied_to_named_three_block_section", "jsw_section_heading_not_a_preferred_bidder_field", "controlling_licence_document_not_reviewed"],
            "status_evidence_level": "official_secondary_dated_evidence",
        },
        TARGET_IDS[2]: {
            "source_id": PRAKASAM_SOURCE_ID,
            "source_url": PRAKASAM_URL,
            "source_type": "html",
            "source_reference_date": "2026-09-02",
            "source_reference_date_basis": "Page last-updated date",
            "source_pdf_page": "",
            "source_hash": prakasam_hash,
            "source_status_summary": "Prospecting Licence executed March 2025; 21 of 66 boreholes completed; Form-C approval dated 7 January 2026",
            "events": [*common_jsw_events, event("form_c_approval", "2026-01-07", "Form-C Approval — Lakshmakapalle North: 7 January 2026")],
            "source_area_ha": 1194.7,
            "preferred_bidder_source": "",
            "final_bid_pct_source": "",
            "completed_borehole_count_source": 21,
            "planned_borehole_count_source": 66,
            "quality_flags": ["official_secondary_current_page", "shared_jsw_milestones_applied_to_named_three_block_section", "jsw_section_heading_not_a_preferred_bidder_field", "controlling_licence_document_not_reviewed"],
            "status_evidence_level": "official_secondary_dated_evidence",
        },
        TARGET_IDS[3]: {
            "source_id": PRAKASAM_SOURCE_ID,
            "source_url": PRAKASAM_URL,
            "source_type": "html",
            "source_reference_date": "2026-09-02",
            "source_reference_date_basis": "Page last-updated date",
            "source_pdf_page": "",
            "source_hash": prakasam_hash,
            "source_status_summary": "New composite licence block; shared JSW-section milestones report LoI, Revenue NOC and prospecting-licence execution dates",
            "events": common_jsw_events,
            "source_area_ha": 1825.8,
            "preferred_bidder_source": "",
            "final_bid_pct_source": "",
            "completed_borehole_count_source": "",
            "planned_borehole_count_source": "",
            "quality_flags": ["official_secondary_current_page", "shared_jsw_milestones_applied_to_named_three_block_section", "jsw_section_heading_not_a_preferred_bidder_field", "block_row_status_has_no_specific_dated_milestone", "controlling_licence_document_not_reviewed"],
            "status_evidence_level": "official_secondary_dated_section_context",
        },
        TARGET_IDS[4]: {
            "source_id": MINES_SOURCE_ID,
            "source_url": MINES_URL,
            "source_type": "pdf",
            "source_reference_date": "2025-01-22",
            "source_reference_date_basis": "PDF creation metadata; presentation cover states January 2025",
            "source_pdf_page": 50,
            "source_hash": mines_hash,
            "source_status_summary": "LOI to be issued",
            "events": [
                event("auction_date", "2024-04-14", "Date of auction: 14.04.2024"),
                event("letter_of_intent_pending", "", "LOI to be issued"),
            ],
            "source_area_ha": 1327.0,
            "preferred_bidder_source": "South-West Mining Limited",
            "final_bid_pct_source": 12.6,
            "completed_borehole_count_source": "",
            "planned_borehole_count_source": "",
            "quality_flags": ["official_secondary_historical_status_snapshot", "auction_date_source_conflict", "controlling_licence_document_not_reviewed"],
            "status_evidence_level": "official_secondary_historical_snapshot",
        },
    }

    rows: list[dict] = []
    for record_id in TARGET_IDS:
        source = evidence[record_id]
        source_area = source["source_area_ha"]
        ibm_area = float(ibm[record_id]["area_ha"]) if ibm[record_id]["area_ha"] else None
        area_difference = abs(ibm_area - source_area) / source_area * 100 if ibm_area is not None else None
        source_auction_date = "2024-04-14" if record_id == TARGET_IDS[4] else ibm[record_id]["auction_date"]
        rows.append({
            "record_id": record_id,
            "state_or_ut": ibm[record_id]["state_or_ut"],
            "block_name": ibm[record_id]["block_name"],
            "mineral_source_ibm": ibm[record_id]["mineral_source"],
            "normalized_material_ids_json": ibm[record_id]["normalized_material_ids_json"],
            "normalized_material_names_json": ibm[record_id]["normalized_material_names_json"],
            "chemical_or_english_names_json": ibm[record_id]["chemical_or_english_names_json"],
            "formulae_or_symbols_json": ibm[record_id]["formulae_or_symbols_json"],
            "auction_date_ibm": ibm[record_id]["auction_date"],
            "auction_date_status_source": source_auction_date,
            "auction_date_agrees_with_ibm": source_auction_date == ibm[record_id]["auction_date"],
            "concession_type_code_ibm": ibm[record_id]["concession_type_code"],
            "ibm_area_ha": ibm_area if ibm_area is not None else "",
            "source_area_ha": source_area,
            "ibm_to_status_source_area_difference_pct": round(area_difference, 6) if area_difference is not None else "",
            "source_status_summary": source["source_status_summary"],
            "status_events_json": json.dumps(source["events"], ensure_ascii=False),
            "preferred_bidder_source": source["preferred_bidder_source"],
            "final_bid_pct_source": source["final_bid_pct_source"],
            "completed_borehole_count_source": source["completed_borehole_count_source"],
            "planned_borehole_count_source": source["planned_borehole_count_source"],
            "status_evidence_level": source["status_evidence_level"],
            "official_status_source_id": source["source_id"],
            "source_reference_date": source["source_reference_date"],
            "source_reference_date_basis": source["source_reference_date_basis"],
            "source_url": source["source_url"],
            "source_type": source["source_type"],
            "source_pdf_page": source["source_pdf_page"],
            "source_document_sha256": source["source_hash"],
            "source_access_date": access_date,
            "current_legal_or_operational_status_verified": False,
            "model_evidence_role": "context_only",
            "model_exclusion_reason": "Official secondary status evidence is useful for reconciliation but does not replace the controlling licence/grant record or prove current operation.",
            "geometry_published": False,
            "quality_flags_json": json.dumps(source["quality_flags"]),
        })

    diagnostics = {
        "prakasam_source_sha256": prakasam_hash,
        "ministry_source_sha256": mines_hash,
        "ministry_pdf_pages": len(pdf.pages),
        "ministry_evidence_pdf_page": 50,
        "required_html_strings_found": len(required_html),
        "required_pdf_strings_found": len(required_pdf),
    }
    return rows, diagnostics


def upsert_source_registry(access_date: str) -> None:
    path = ROOT / "outputs" / "source_registry.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["source_id"] not in {PRAKASAM_SOURCE_ID, MINES_SOURCE_ID}]
    rows.extend([
        {
            "source_id": PRAKASAM_SOURCE_ID,
            "publisher": "Prakasam District Administration, Government of Andhra Pradesh",
            "title": "Invest In Prakasam — JSW Iron Ore Blocks",
            "release_or_reference_date": "page last updated 2026-09-02",
            "url": PRAKASAM_URL,
            "download_url": PRAKASAM_URL,
            "license_or_access_note": "Government public webpage; retain attribution and verify current site reuse terms.",
            "used_for": "Official secondary evidence for the areas, status summaries, common milestones and drilling progress of Addankivaripalem, Lakshmakapalle North and Lakshmakapalle South.",
            "limitations": "The page is not the controlling licence instrument and publishes no block coordinates. Shared milestone rows are scoped to the named three-block JSW section; only two blocks have block-specific Form-C dates.",
        },
        {
            "source_id": MINES_SOURCE_ID,
            "publisher": "Ministry of Mines, Government of India",
            "title": "National Mining Ministers' Conference — Auction & Operationalization of Mineral Blocks",
            "release_or_reference_date": "January 2025; PDF created 2025-01-22",
            "url": MINES_URL,
            "download_url": MINES_URL,
            "license_or_access_note": "Government public presentation; retain attribution and verify current website reuse terms.",
            "used_for": "Official secondary historical status, preferred bidder, final bid and area evidence for Adakula and Mincheri RF on physical PDF page 50.",
            "limitations": "The slide says LoI was pending at that historical snapshot and is not a controlling grant record or proof of present operation. It prints 14 April 2024 for Mincheri, conflicting with IBM's 11 March 2024 auction date.",
        },
    ])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def upsert_data_dictionary(fieldnames_out: list[str]) -> None:
    path = ROOT / "outputs" / "data_dictionary.csv"
    table = OUTPUT_CSV.name
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["table"] != table]
    definitions = {
        "auction_date_status_source": "Auction date printed by the linked status source; preserved separately from the IBM date.",
        "auction_date_agrees_with_ibm": "True when the status-source auction date exactly equals the IBM Table 5 auction date.",
        "source_area_ha": "Block or concession area published by the linked official status source, in hectares.",
        "ibm_to_status_source_area_difference_pct": "Absolute percentage difference between IBM and status-source areas, relative to the status-source area; blank when IBM publishes no area.",
        "source_status_summary": "Concise, source-faithful summary of the dated status evidence.",
        "status_events_json": "JSON array of source-published event types, dates and source wording; blank event_date means the source provides no event date.",
        "preferred_bidder_source": "Preferred bidder printed by the official status source.",
        "final_bid_pct_source": "Final bid percentage printed by the official status source.",
        "completed_borehole_count_source": "Completed boreholes printed by the official status source.",
        "planned_borehole_count_source": "Planned boreholes printed by the official status source.",
        "status_evidence_level": "Evidence class distinguishing dated official-secondary evidence from a historical snapshot or section-level context.",
        "official_status_source_id": "Source-registry identifier for the official status evidence.",
        "source_reference_date": "Date to which the source snapshot is tied.",
        "source_reference_date_basis": "How the source reference date was derived, such as page metadata or a page last-updated label.",
        "source_pdf_page": "One-based physical PDF page containing the evidence; blank for HTML sources.",
        "current_legal_or_operational_status_verified": "False in this layer because no controlling licence/grant instrument or independent current-operation record was reviewed.",
        "geometry_published": "False in this non-spatial status-evidence layer.",
        "quality_flags_json": "JSON array of source-scope, conflict and control-document caveats.",
    }
    boolean_columns = {"auction_date_agrees_with_ibm", "current_legal_or_operational_status_verified", "geometry_published"}
    numeric_columns = {"ibm_area_ha", "source_area_ha", "ibm_to_status_source_area_difference_pct", "final_bid_pct_source", "completed_borehole_count_source", "planned_borehole_count_source", "source_pdf_page"}
    for column in fieldnames_out:
        unit = ""
        if column.endswith("_ha"):
            unit = "hectares"
        elif column.endswith("_pct_source") or column.endswith("_difference_pct"):
            unit = "percent"
        elif column.endswith("_json"):
            unit = "JSON"
        rows.append({
            "table": table,
            "column": column,
            "definition": definitions.get(column, column.replace("_", " ").capitalize() + "."),
            "data_type": "boolean" if column in boolean_columns else "number" if column in numeric_columns else "string",
            "unit": unit,
            "missing_value_policy": "Blank means not published or not applicable. False is explicit and is not a missing-value substitute.",
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def update_release_validation(validation: dict) -> None:
    path = ROOT / "outputs" / "validation_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["development_release_version"] = "v1.0-alpha.13"
    report["ibm_auction_status_evidence_2023_24"] = {
        key: validation[key] for key in [
            "records", "official_source_count", "source_record_counts", "auction_date_agreement_counts",
            "records_with_source_area", "records_with_preferred_bidder", "records_with_dated_events",
            "current_legal_or_operational_status_verified_rows", "geometry_published_rows", "model_evidence_role",
        ]
    }
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh the two cached official sources")
    args = parser.parse_args()
    access_date = date.today().isoformat()
    fetch(PRAKASAM_URL, PRAKASAM_CACHE, args.refresh)
    fetch(MINES_URL, MINES_CACHE, args.refresh)
    rows, diagnostics = build_rows(access_date)
    fieldnames_out = list(rows[0])
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames_out, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    source_counts: dict[str, int] = {}
    agreement_counts: dict[str, int] = {}
    for row in rows:
        source_counts[row["official_status_source_id"]] = source_counts.get(row["official_status_source_id"], 0) + 1
        agreement = str(row["auction_date_agrees_with_ibm"])
        agreement_counts[agreement] = agreement_counts.get(agreement, 0) + 1
    validation = {
        "release": "v1.0-alpha.13",
        "source_access_date": access_date,
        "records": len(rows),
        "official_source_count": len(source_counts),
        "source_record_counts": source_counts,
        "auction_date_agreement_counts": agreement_counts,
        "records_with_source_area": sum(row["source_area_ha"] != "" for row in rows),
        "records_with_preferred_bidder": sum(bool(row["preferred_bidder_source"]) for row in rows),
        "records_with_dated_events": sum(any(event_row["event_date"] for event_row in json.loads(row["status_events_json"])) for row in rows),
        "current_legal_or_operational_status_verified_rows": sum(row["current_legal_or_operational_status_verified"] for row in rows),
        "geometry_published_rows": sum(row["geometry_published"] for row in rows),
        "model_evidence_role": "context_only",
        "diagnostics": diagnostics,
        "output": {"file": OUTPUT_CSV.name, "sha256": sha256(OUTPUT_CSV), "bytes": OUTPUT_CSV.stat().st_size},
        "checks_pass": False,
        "limitations": [
            "The five rows are official-secondary status evidence, not controlling grant or licence instruments.",
            "The Prakasam page publishes no boundary coordinates and the current MSTC Andhra MBS index does not expose these 2023 blocks.",
            "The Ministry slide is a January 2025 historical snapshot and cannot establish present status.",
            "The Ministry slide's Mincheri auction date conflicts with the IBM yearbook date and both values are preserved.",
            "No row is used as a model label, training observation, candidate score input or geometry.",
        ],
    }
    validation["checks_pass"] = bool(
        validation["records"] == 5
        and validation["official_source_count"] == 2
        and validation["source_record_counts"] == {PRAKASAM_SOURCE_ID: 3, MINES_SOURCE_ID: 2}
        and validation["auction_date_agreement_counts"] == {"True": 4, "False": 1}
        and validation["records_with_source_area"] == 5
        and validation["records_with_preferred_bidder"] == 2
        and validation["records_with_dated_events"] == 5
        and validation["current_legal_or_operational_status_verified_rows"] == 0
        and validation["geometry_published_rows"] == 0
    )
    VALIDATION_JSON.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    upsert_source_registry(access_date)
    upsert_data_dictionary(fieldnames_out)
    update_release_validation(validation)
    print(f"wrote {OUTPUT_CSV.relative_to(ROOT)} ({len(rows)} rows)")
    print(f"wrote {VALIDATION_JSON.relative_to(ROOT)}")
    if not validation["checks_pass"]:
        raise SystemExit("IBM auction status-evidence validation failed")


if __name__ == "__main__":
    main()
