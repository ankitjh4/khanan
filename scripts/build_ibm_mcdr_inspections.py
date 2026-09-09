#!/usr/bin/env python3
"""Build an auditable inventory of IBM MCDR inspection-table records.

The Indian Bureau of Mines publishes inspection/report tables by regional
office and financial year.  These pages are useful evidence that a named mine
was inspected, but they are not a statutory all-leases register and do not by
themselves prove that a mine is currently producing.  This builder preserves
that distinction, keeps the original page and row text, and never invents a
coordinate for a non-georeferenced table row.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pandas as pd
from lxml import html


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "sources" / "raw" / "ibm_mcdr_inspection_pages"
OUT = ROOT / "outputs"
EVENT_TABLE = "india_ibm_mcdr_inspection_events_2023_2026.csv"
LATEST_TABLE = "india_ibm_mcdr_latest_inspected_mines.csv"
VALIDATION_FILE = "ibm_mcdr_inspection_validation.json"
SOURCE_ID = "SRC_IBM_MCDR_INSPECTIONS_2023_2026"
ACCESS_DATE = date.today().isoformat()

BASE = "https://ibm.gov.in/IBMPortal/pages/"


def page(region: str, fiscal_year: str, page_number: int, slug: str) -> dict:
    return {
        "region": region,
        "fiscal_year": fiscal_year,
        "page_number": page_number,
        "url": BASE + slug,
    }


# The most recent public table discovered for every IBM regional office is
# included.  Some offices expose 2025-26 tables; for the others the newest
# discoverable table was 2024-25.  Nagpur's newest discoverable table was
# 2023-24.  Each exact URL is preserved in the event output.
PAGE_SPECS = [
    page("Ajmer", "2025-26", 1, "mcdr-reports--amp--violation-letters-for-the-year-2025-26--ajmer-region--page-1"),
    page("Bhubaneswar", "2025-26", 1, "mcdr-inspection-reports-and-violation-letters---2025-26--page-1--bhubaneswar-region-"),
    page("Bhubaneswar", "2025-26", 2, "mcdr-inspection-reports-and-violation-letters---2025-26--page-2--bhubaneswar-region-"),
    page("Dehradun", "2025-26", 1, "mcdr-report-violation-letter-for-the-year-2025-26--dehradun-region-"),
    page("Goa", "2025-26", 1, "mcdr-inspection-reports--violation-letters-etc--2025-26---goa-region"),
    page("Hyderabad", "2025-26", 1, "mcdr-inspection-reports-and-violation-letters---2025-26----hyderabad-region---page-1-"),
    page("Hyderabad", "2025-26", 2, "mcdr-inspection-reports-and-violation-letters---2025-26----hyderabad-region---page-2-"),
    page("Raipur", "2025-26", 1, "mcdr-inspection-reports-and-violation-letters-2025-26--raipur-region-page-1"),
    page("Ranchi", "2025-26", 1, "mcdr-inspection-reports--amp--violation-letters---2025-26---ranchi-region-"),
    page("Ajmer", "2024-25", 1, "mcdr-reports--amp--violation-letters-for-the-year-2024-25--ajmer-region--page-1"),
    page("Ajmer", "2024-25", 2, "mcdr-reports--amp--violation-letters-for-the-year-2024-25--ajmer-region--page-2"),
    page("Ajmer", "2024-25", 3, "mcdr-reports--amp--violation-letters-for-the-year-2024-25--ajmer-region--page-3"),
    page("Bangalore", "2024-25", 1, "mcdr-inspection-reports--amp--violation-letters---2024-25----bengalore-region----page--1"),
    page("Bangalore", "2024-25", 2, "mcdr-inspection-reports--amp--violation-letters---2024-25----bengalore-region----page--2"),
    page("Bhubaneswar", "2024-25", 1, "mcdr-inspection-reports-and-violation-letters---2024-25---page-1--bhubaneswar-region-"),
    page("Chennai", "2024-25", 1, "mcdr-reports-and-violation-letters--2024-25---chennai-region---page-1"),
    page("Chennai", "2024-25", 2, "mcdr-reports-and-violation-letters--2024-25---chennai-region---page-2"),
    page("Chennai", "2024-25", 3, "mcdr-reports-and-violation-letters--2024-25---chennai-region---page-3"),
    page("Goa", "2024-25", 1, "check-up-inspection-reports-of-com--sz----2024-25"),
    page("Gandhinagar", "2024-25", 1, "mcdr-inspection-reports-and-violation-letters--2024-25--gandhinagar-region----page-1"),
    page("Gandhinagar", "2024-25", 2, "mcdr-inspection-reports-and-violation-letters--2024-25--gandhinagar-region----page-2"),
    page("Gandhinagar", "2024-25", 3, "mcdr-inspection-reports-and-violation-letters--2024-25--gandhinagar-region----page-3"),
    page("Gandhinagar", "2024-25", 4, "mcdr-inspection-reports-and-violation-letters--2024-25--gandhinagar-region----page-4"),
    page("Guwahati", "2024-25", 1, "mcdr-inspection-reports-and-violation-letters---2024-25---guwahati-region"),
    page("Hyderabad", "2024-25", 1, "mcdr-inspection-reports-and-violation-letters---2024-25---hyderabad-region---page-1"),
    page("Hyderabad", "2024-25", 2, "mcdr-inspection-reports-and-violation-letters---2024-25---hyderabad-region---page-2"),
    page("Hyderabad", "2024-25", 3, "mcdr-inspection-reports-and-violation-letters---2024-25---hyderabad-region---page-3"),
    page("Hyderabad", "2024-25", 4, "mcdr-inspection-reports-and-violation-letters---2024-25---hyderabad-region---page-4"),
    page("Jabalpur", "2024-25", 1, "mcdr-reports-and-violation-letters---2024-25--jabalpur-region---page-01"),
    page("Jabalpur", "2024-25", 2, "mcdr-reports-and-violation-letters---2024-25--jabalpur-region---page-02"),
    page("Jabalpur", "2024-25", 3, "mcdr-reports-and-violation-letters---2024-25--jabalpur-region---page-03"),
    page("Raipur", "2024-25", 1, "mcdr-inspection-reports-and-violation-letters-2024-25--raipur-region-page-1"),
    page("Ranchi", "2024-25", 1, "mcdr-inspection-reports--amp--violation-letters---2024-25---ranchi-region-page-1"),
    page("Vijayawada", "2024-25", 1, "mcdr-inspection-reports--amp--violation-letters-for-the-year-2024-25-vijayawada-regional-office--page-1-"),
    page("Vijayawada", "2024-25", 2, "mcdr-inspection-reports--amp--violation-letters-for-the-year-2024-25-vijayawada-regional-office--page-2-"),
    page("Nagpur", "2023-24", 1, "mcdr-reports--amp--violation-letters-2023-24--nagpur-region-"),
]


STATE_ALIASES = {
    "andhra pradesh": "Andhra Pradesh",
    "ap": "Andhra Pradesh",
    "a p": "Andhra Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "cg": "Chhattisgarh",
    "c g": "Chhattisgarh",
    "goa": "Goa",
    "south goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "hp": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "j k": "Jammu & Kashmir",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "mp": "Madhya Pradesh",
    "m p": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "odisha": "Odisha",
    "orissa": "Odisha",
    "rajasthan": "Rajasthan",
    "tamil nadu": "Tamil Nadu",
    "tamilnadu": "Tamil Nadu",
    "tn": "Tamil Nadu",
    "telangana": "Telangana",
    "ts": "Telangana",
    "t s": "Telangana",
    "uttar pradesh": "Uttar Pradesh",
    "up": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "uk": "Uttarakhand",
    "west bengal": "West Bengal",
}


MATERIAL_PATTERNS = {
    "Antimony": [r"\bantimony\b"],
    "Bauxite": [],  # handled as Aluminium below
    "Aluminium": [r"\bbauxite\b", r"\baluminous\s+laterite\b", r"\baluminium\b", r"\bkyanite\b", r"\bsillimanite\b", r"बॉक्साइट", r"एल्युमिनस\s+लैटेराइट"],
    "Barium": [r"\bbarite?s?\b", r"\bbaryte?s?\b"],
    "Beryllium": [r"\bberyllium\b", r"\bberyl\b"],
    "Calcium and limestone": [r"\blimestone\b", r"\blimstone\b", r"\blst\b", r"\blime\s*shell\b", r"\blimeshell\b", r"\bchalk\b", r"\bcalcite\b", r"\bdolomite\b", r"\bdolo\b", r"\bwollastonite\b", r"\bselenite\b", r"चूना\s*पत्थर"],
    "Chromium": [r"\bchromite\b", r"\bchromium\b"],
    "Cobalt": [r"\bcobalt\b"],
    "Copper": [r"\bcopper\b"],
    "Fluorine": [r"\bfluorite\b", r"\bfluorspar\b"],
    "Gold": [r"\bgold\b"],
    "Graphite": [r"\bgraphite\b"],
    "Iron": [r"\biron(?:\s+ore)?\b", r"\bhematite\b", r"\bmagnetite\b", r"\bfe\b"],
    "Kaolin": [r"\bkaolin\b", r"\bchina\s+clay\b"],
    "Lead": [r"\blead\b"],
    "Lithium": [r"\blithium\b"],
    "Lignite": [r"\blignite\b"],
    "Magnesium": [r"\bmagnesite\b", r"\bdolomite\b", r"\bdolo\b", r"\bverm[iu]culite\b"],
    "Manganese": [r"\bmanganese\b", r"\bmn\b"],
    "Molybdenum": [r"\bmolybdenum\b"],
    "Nickel": [r"\bnickel\b"],
    "Phosphorus": [r"\bphosphorite\b", r"\bphosphate\b", r"\bapatite\b"],
    "Platinum-group elements": [r"\bplatinum\b", r"\bpalladium\b", r"\bpge\b"],
    "Potash": [r"\bpotash\b", r"\bglauconite\b"],
    "Rare-earth elements": [r"rare\s+earth", r"\bree\b", r"\bmonazite\b"],
    "Silicon": [r"\bsilica\b", r"\bsiliceous\s+earth\b", r"\bmoulding\s+sand\b", r"\bquartz(?:ite)?\b", r"\bqaurtz\b", r"\bwollastonite\b", r"\bkyanite\b", r"\bsillimanite\b"],
    "Silver": [r"\bsilver\b"],
    "Tantalum": [r"\btantalum\b"],
    "Tin": [r"\btin(?:\s+ore)?\b"],
    "Titanium": [r"\btitanium\b", r"\bilmenite\b", r"\brutile\b"],
    "Tungsten": [r"\btungsten\b", r"\bwolfram\b"],
    "Uranium": [r"\buranium\b"],
    "Vanadium": [r"\bvanadium\b"],
    "Zinc": [r"\bzinc\b"],
    "Zirconium": [r"\bzircon\b", r"\bzirconium\b"],
}


SOURCE_REGISTRY_ROW = {
    "source_id": SOURCE_ID,
    "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
    "title": "Regional MCDR inspection reports and violation-letter tables, FY 2023-24 to 2025-26",
    "release_or_reference_date": f"inspection dates through source access {ACCESS_DATE}",
    "url": "https://ibm.gov.in/IBMPortal/pages/Administration_of_MCDR",
    "download_url": "Multiple exact regional-page URLs are retained in the event CSV source_url field.",
    "license_or_access_note": "Government of India public webpages; retain attribution and verify current IBM website reuse terms.",
    "used_for": "Named mine inspection events, dates, regions, state/district, mineral, owner/lessee, mine code, lease area, and linked report/notice documents where published.",
    "limitations": "Inspection tables are not an exhaustive lease or working-mine register. Inclusion shows a published IBM inspection-table record, not current production, legal compliance, reserve size, or georeferenced location.",
}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalized_key(value: str) -> str:
    folded = clean_text(value).casefold()
    kept = "".join(
        character if character.isalnum() or character.isspace() or unicodedata.category(character).startswith("M") else " "
        for character in folded
    )
    return re.sub(r"\s+", " ", kept).strip()


def is_blank(value: str) -> bool:
    raw = clean_text(value)
    return not raw or normalized_key(raw) in {"nan", "na", "n a", "nil", "none", "not issued"} or raw in {"-", "--"}


def normalize_state(value: str) -> str:
    key = normalized_key(value)
    return STATE_ALIASES.get(key, clean_text(value).title() if value and not is_blank(value) else "")


def jdump(values) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def fetch_page(spec: dict) -> tuple[dict, bytes]:
    request = Request(spec["url"], headers={"User-Agent": "Mozilla/5.0 (research dataset builder)"})
    error = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=45) as response:
                body = response.read()
            if len(body) < 20_000:
                raise ValueError(f"unexpectedly short IBM page ({len(body)} bytes)")
            return spec, body
        except Exception as exc:  # pragma: no cover - exercised only on network failure
            error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not download {spec['url']}: {error}")


def cached_page(spec: dict, refresh: bool) -> tuple[dict, bytes, Path]:
    name = f"{spec['fiscal_year'].replace('-', '_')}_{spec['region'].lower()}_p{spec['page_number']}.html"
    path = RAW_DIR / name
    if path.exists() and not refresh:
        return spec, path.read_bytes(), path
    spec, body = fetch_page(spec)
    path.write_bytes(body)
    return spec, body, path


def canonical_header(value: str) -> str | None:
    raw = clean_text(value)
    key = normalized_key(value)
    if not key:
        return None
    if key in {"sl no", "sr no", "sl", "s no", "no"} or key.startswith(("sl no", "sr no")):
        return "source_serial_number"
    if "क्रमांक" in raw:
        return "source_serial_number"
    if "खदान कोड" in raw:
        return "mine_code"
    if "खदान का नाम" in raw:
        return "mine_name"
    if "मालिक का नाम" in raw:
        return "owner_or_lessee"
    if "निरीक्षण अधिकारी" in raw:
        return "inspecting_officer"
    if "निरीक्षण की तारीख" in raw:
        return "inspection_date_source"
    if "निरीक्षण का प्रकार" in raw:
        return "inspection_type"
    if "एमसीडीआर रिपोर्ट" in raw:
        return "inspection_report_source"
    if "उल्लंघन पत्र" in raw:
        return "violation_date_source"
    if "कारण बताओ" in raw:
        return "show_cause_date_source"
    if "mine code" in key:
        return "mine_code"
    if "lease area" in key:
        return "lease_area_ha_source"
    if key == "state":
        return "state_or_ut_source"
    if key == "district":
        return "district_source"
    if key.replace(" ", "") == "mineral":
        return "mineral_source"
    if "name" in key and "mine" in key and "officer" not in key:
        return "mine_name"
    if key in {"mine name"}:
        return "mine_name"
    if "owner" in key or "lessee" in key:
        return "owner_or_lessee"
    if "officer" in key or "official" in key:
        return "inspecting_officer"
    if "type" in key and "inspection" in key:
        return "inspection_type"
    if "date" in key and "inspection" in key:
        return "inspection_date_source"
    if "show cause" in key or "showcause" in key:
        return "show_cause_date_source"
    if ("vio sc" in key or ("violation" in key and "show cause" in key)) and "date" in key:
        return "violation_or_show_cause_source"
    if "violation" in key and ("date" in key or "issued" in key):
        return "violation_date_source"
    if "mcdr report" in key or "reorts for uploading" in key or "reports for uploading" in key:
        return "inspection_report_source"
    if key == "remarks":
        return "remarks_source"
    return None


def find_header_row(table) -> tuple[int, list[str]] | None:
    rows = table.xpath(".//tr")
    for index, row in enumerate(rows[:5]):
        cells = row.xpath("./th|./td")
        headers = [clean_text(" ".join(cell.itertext())) for cell in cells]
        mapped = [canonical_header(item) for item in headers]
        if "mine_name" in mapped and ("mineral_source" in mapped or "mine_code" in mapped):
            return index, headers
    return None


def parse_date(value: str) -> str:
    if is_blank(value):
        return ""
    cleaned = clean_text(value)
    if re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s*(?:&|and)\s*\d{1,2}", cleaned, re.IGNORECASE):
        return ""
    cleaned = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\((?:AN|FN)\)", "", cleaned, flags=re.IGNORECASE).strip()
    # Do not collapse cells containing multiple dates or narrative text into one.
    if len(re.findall(r"\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b", cleaned)) > 1:
        return ""
    parsed = pd.to_datetime(cleaned, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def extract_mine_code(explicit: str, mine_name: str) -> tuple[str, str]:
    if not is_blank(explicit):
        return clean_text(explicit), "explicit_source_column"
    match = re.search(r"\b\d{2}[A-Z]{3}\d{5}\b", mine_name.upper())
    return (match.group(0), "parsed_from_mine_name") if match else ("", "")


def extract_lease_area(explicit: str, mine_name: str) -> tuple[float | None, str, str]:
    if not is_blank(explicit):
        match = re.search(r"\d+(?:\.\d+)?", explicit.replace(",", ""))
        if match:
            return float(match.group(0)), clean_text(explicit), "explicit_source_column"
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:ha\.?|hect(?:are)?s?\b|hc\.?)", mine_name, re.IGNORECASE)
    if match:
        return float(match.group(1)), match.group(0), "parsed_from_mine_name"
    return None, clean_text(explicit) if not is_blank(explicit) else "", ""


def material_links(mineral: str, mine_name: str, material_lookup: dict) -> tuple[list[str], list[str], list[str], str]:
    if not is_blank(mineral):
        search_text = mineral
        basis = "explicit_mineral_column"
    else:
        search_text = mine_name
        basis = "mine_name_text_only"
    normalized = []
    for material, patterns in MATERIAL_PATTERNS.items():
        if material == "Bauxite":
            continue
        if any(re.search(pattern, search_text, re.IGNORECASE) for pattern in patterns):
            normalized.append(material)
    normalized = sorted(set(normalized), key=lambda item: material_lookup[item]["priority_rank"])
    chemicals = sorted({name for item in normalized for name in material_lookup[item]["chemical_names"]})
    symbols = sorted({name for item in normalized for name in material_lookup[item]["symbols_or_formulae"]})
    return normalized, chemicals, symbols, basis


def cell_links(cell, source_url: str) -> list[str]:
    links = []
    for anchor in cell.xpath(".//a[@href]"):
        href = clean_text(anchor.get("href"))
        if href and not href.lower().startswith(("javascript:", "mailto:")):
            links.append(urljoin(source_url, href))
    return sorted(set(links))


def parse_page(spec: dict, body: bytes, raw_path: Path, material_lookup: dict) -> tuple[list[dict], dict]:
    document = html.fromstring(body.decode("utf-8", errors="replace"))
    title = clean_text(" ".join(document.xpath("//h1[1]//text() | //h2[1]//text() | //h3[1]//text()")))
    documented_title_typo = spec["region"] == "Raipur" and spec["fiscal_year"] == "2025-26" and "2025-256" in title
    if spec["fiscal_year"] not in spec["url"]:
        raise ValueError(f"financial year missing from configured source URL: {spec['url']}")
    sha256 = hashlib.sha256(body).hexdigest()
    events = []
    table_summaries = []
    for table_index, table in enumerate(document.xpath("//table"), start=1):
        header_info = find_header_row(table)
        if not header_info:
            continue
        header_index, source_headers = header_info
        canonical = [canonical_header(item) for item in source_headers]
        table_rows = table.xpath(".//tr")
        parsed_count = 0
        for table_row_number, row in enumerate(table_rows[header_index + 1 :], start=header_index + 2):
            cells = row.xpath("./th|./td")
            if len(cells) != len(source_headers):
                continue
            values = [clean_text(" ".join(cell.itertext())) for cell in cells]
            row_data = {}
            row_links = {}
            for index, field in enumerate(canonical):
                if field:
                    row_data[field] = values[index]
                    row_links[field] = cell_links(cells[index], spec["url"])
            mine_name = row_data.get("mine_name", "")
            serial = row_data.get("source_serial_number", "")
            if is_blank(mine_name) or is_blank(serial) or normalized_key(serial).startswith("sl no"):
                continue
            state_source = row_data.get("state_or_ut_source", "")
            district_source = row_data.get("district_source", "")
            mineral_source = row_data.get("mineral_source", "")
            mine_code, mine_code_basis = extract_mine_code(row_data.get("mine_code", ""), mine_name)
            lease_area, lease_area_source, lease_area_basis = extract_lease_area(
                row_data.get("lease_area_ha_source", ""), mine_name
            )
            normalized_materials, chemicals, symbols, mapping_basis = material_links(
                mineral_source, mine_name, material_lookup
            )
            inspection_links = sorted(set(
                row_links.get("inspection_report_source", [])
                + row_links.get("mine_name", [])
                + row_links.get("inspection_type", [])
            ))
            violation_links = sorted(set(
                row_links.get("violation_date_source", [])
                + row_links.get("violation_or_show_cause_source", [])
            ))
            show_cause_links = sorted(set(row_links.get("show_cause_date_source", [])))
            all_links = sorted(set(link for links in row_links.values() for link in links))
            stable = "|".join([
                spec["fiscal_year"], spec["region"], str(spec["page_number"]),
                str(table_index), str(table_row_number), serial, mine_name,
            ])
            record_id = "IBM-MCDR-EVT-" + hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16].upper()
            events.append({
                "record_id": record_id,
                "record_class": "official_mcdr_inspection_table_event",
                "fiscal_year": spec["fiscal_year"],
                "ibm_regional_office": spec["region"],
                "source_page_number": spec["page_number"],
                "source_table_index": table_index,
                "source_table_row_number": table_row_number,
                "source_serial_number": serial,
                "mine_name": mine_name,
                "mine_code": mine_code,
                "mine_code_basis": mine_code_basis,
                "state_or_ut_source": state_source if not is_blank(state_source) else "",
                "state_or_ut": normalize_state(state_source),
                "district_source": district_source if not is_blank(district_source) else "",
                "district": clean_text(district_source).title() if not is_blank(district_source) else "",
                "mineral_source": mineral_source if not is_blank(mineral_source) else "",
                "material_mapping_basis": mapping_basis,
                "normalized_top50_materials_json": jdump(normalized_materials),
                "chemical_names_json": jdump(chemicals),
                "symbols_or_formulae_json": jdump(symbols),
                "owner_or_lessee": row_data.get("owner_or_lessee", "") if not is_blank(row_data.get("owner_or_lessee", "")) else "",
                "lease_area_ha": lease_area,
                "lease_area_source": lease_area_source,
                "lease_area_basis": lease_area_basis,
                "inspection_type": row_data.get("inspection_type", "") if not is_blank(row_data.get("inspection_type", "")) else "",
                "inspecting_officer": row_data.get("inspecting_officer", "") if not is_blank(row_data.get("inspecting_officer", "")) else "",
                "inspection_date_source": row_data.get("inspection_date_source", "") if not is_blank(row_data.get("inspection_date_source", "")) else "",
                "inspection_date": parse_date(row_data.get("inspection_date_source", "")),
                "violation_date_source": row_data.get("violation_date_source", "") if not is_blank(row_data.get("violation_date_source", "")) else "",
                "violation_date": parse_date(row_data.get("violation_date_source", "")),
                "show_cause_date_source": row_data.get("show_cause_date_source", "") if not is_blank(row_data.get("show_cause_date_source", "")) else "",
                "show_cause_date": parse_date(row_data.get("show_cause_date_source", "")),
                "violation_or_show_cause_source": row_data.get("violation_or_show_cause_source", "") if not is_blank(row_data.get("violation_or_show_cause_source", "")) else "",
                "remarks_source": row_data.get("remarks_source", "") if not is_blank(row_data.get("remarks_source", "")) else "",
                "inspection_report_urls_json": jdump(inspection_links),
                "violation_notice_urls_json": jdump(violation_links),
                "show_cause_notice_urls_json": jdump(show_cause_links),
                "all_linked_document_urls_json": jdump(all_links),
                "latitude": None,
                "longitude": None,
                "coordinates_available_in_summary_source": False,
                "spatial_model_integration_status": "inventory_only_not_used_as_spatial_evidence_without_exact_public_coordinates_or_polygon",
                "source_id": SOURCE_ID,
                "source_url": spec["url"],
                "source_page_title": title,
                "source_page_title_fiscal_year_typo": documented_title_typo,
                "source_html_file": str(raw_path.relative_to(ROOT)),
                "source_html_sha256": sha256,
                "source_accessed_date": ACCESS_DATE,
            })
            parsed_count += 1
        table_summaries.append({
            "table_index": table_index,
            "source_headers": source_headers,
            "parsed_rows": parsed_count,
        })
    if not events:
        raise ValueError(f"no MCDR event rows parsed from {spec['url']}")
    return events, {
        **spec,
        "source_page_title": title,
        "source_page_title_fiscal_year_typo": documented_title_typo,
        "source_html_file": str(raw_path.relative_to(ROOT)),
        "source_html_sha256": sha256,
        "event_rows": len(events),
        "tables": table_summaries,
    }


def identity_key(row: pd.Series) -> tuple[str, str]:
    if row["mine_code"]:
        return "mine_code", normalized_key(row["mine_code"])
    components = [
        row["ibm_regional_office"], row["state_or_ut"], row["district"], row["mine_name"]
    ]
    return "normalized_office_state_district_mine_name", "|".join(normalized_key(str(item)) for item in components)


def make_latest_view(events: pd.DataFrame) -> pd.DataFrame:
    identities = events.apply(identity_key, axis=1, result_type="expand")
    events = events.copy()
    events["mine_identity_method"] = identities[0]
    events["mine_identity_key"] = identities[1]
    events["_valid_inspection_date"] = events["inspection_date"].where(
        events["inspection_date_within_fiscal_year"].eq(True), ""
    )
    events["_date_sort"] = pd.to_datetime(events["_valid_inspection_date"], errors="coerce")
    events["_fy_sort"] = events["fiscal_year"].str.slice(0, 4).astype(int)
    events = events.sort_values(
        ["mine_identity_key", "_date_sort", "_fy_sort", "source_page_number", "source_table_row_number"],
        na_position="first",
    )
    summary = events.groupby("mine_identity_key", dropna=False).agg(
        inspection_event_count=("record_id", "size"),
        earliest_inspection_date=("_valid_inspection_date", lambda values: min([item for item in values if item] or [""])),
        latest_inspection_date=("_valid_inspection_date", lambda values: max([item for item in values if item] or [""])),
        fiscal_years_present_json=("fiscal_year", lambda values: jdump(sorted(set(values)))),
        source_event_record_ids_json=("record_id", lambda values: jdump(list(values))),
    ).reset_index()
    latest = events.groupby("mine_identity_key", dropna=False).tail(1).drop(columns=["_valid_inspection_date", "_date_sort", "_fy_sort"])
    latest = latest.merge(summary, on="mine_identity_key", how="left")
    latest["record_id"] = [
        "IBM-MCDR-MINE-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16].upper()
        for key in latest["mine_identity_key"]
    ]
    latest["record_class"] = "official_mcdr_latest_inspected_mine_view"
    ordered = [
        "record_id", "record_class", "mine_identity_method", "mine_identity_key",
        "inspection_event_count", "earliest_inspection_date", "latest_inspection_date",
        "fiscal_years_present_json", "source_event_record_ids_json",
    ]
    return latest[ordered + [column for column in latest.columns if column not in ordered]]


def add_fiscal_year_date_check(events: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    parsed = pd.to_datetime(result["inspection_date"], errors="coerce")
    checks = []
    for fiscal_year, inspection_date in zip(result["fiscal_year"], parsed):
        if pd.isna(inspection_date):
            checks.append("")
            continue
        start_year = int(fiscal_year.split("-")[0])
        start = pd.Timestamp(start_year, 4, 1)
        end = pd.Timestamp(start_year + 1, 3, 31)
        checks.append(bool(start <= inspection_date <= end))
    result["inspection_date_within_fiscal_year"] = checks
    return result


def update_source_registry() -> None:
    path = OUT / "source_registry.csv"
    frame = pd.read_csv(path, keep_default_na=False) if path.exists() else pd.DataFrame()
    if not frame.empty:
        frame = frame.loc[frame["source_id"] != SOURCE_ID].copy()
    frame = pd.concat([frame, pd.DataFrame([SOURCE_REGISTRY_ROW])], ignore_index=True)
    frame.to_csv(path, index=False)


def update_material_taxonomy(events: pd.DataFrame, latest: pd.DataFrame) -> None:
    path = OUT / "india_strategic_materials_top50.csv"
    if not path.exists():
        return
    materials = pd.read_csv(path, keep_default_na=False)
    summaries = {}
    for material_name in materials["material_name"]:
        event_mask = events["normalized_top50_materials_json"].map(
            lambda value: material_name in json.loads(value)
        )
        latest_mask = latest["normalized_top50_materials_json"].map(
            lambda value: material_name in json.loads(value)
        )
        linked_events = events.loc[event_mask]
        linked_latest = latest.loc[latest_mask]
        summaries[material_name] = {
            "ibm_mcdr_inspection_event_rows": int(len(linked_events)),
            "ibm_mcdr_latest_inspected_mine_rows": int(len(linked_latest)),
            "ibm_mcdr_source_minerals_json": jdump(sorted(
                value for value in linked_events["mineral_source"].unique() if value
            )),
            "ibm_mcdr_regional_office_count": int(linked_events["ibm_regional_office"].nunique()),
        }
    for column in [
        "ibm_mcdr_inspection_event_rows", "ibm_mcdr_latest_inspected_mine_rows",
        "ibm_mcdr_source_minerals_json", "ibm_mcdr_regional_office_count",
    ]:
        materials[column] = [summaries[name][column] for name in materials["material_name"]]
    materials.to_csv(path, index=False)


def definition_for(column: str, table_name: str) -> tuple[str, str, str | None]:
    exact = {
        "record_id": ("Stable record identifier within this IBM MCDR extract.", "text", None),
        "record_class": ("Inspection event or deduplicated latest-inspected-mine view; neither implies current production.", "category", None),
        "fiscal_year": ("IBM table financial year.", "text", None),
        "ibm_regional_office": ("IBM regional office publishing the table.", "text", None),
        "source_page_number": ("Page number within the regional financial-year table series.", "integer", "page"),
        "source_table_index": ("One-based HTML table index on the source page.", "integer", "table"),
        "source_table_row_number": ("One-based HTML row number including the table header.", "integer", "row"),
        "source_serial_number": ("Serial number printed by IBM, retained as text.", "text", None),
        "mine_name": ("Mine name printed in the IBM regional table.", "text", None),
        "mine_code": ("IBM mine code from a source column or strictly parsed from the source mine-name text.", "text", None),
        "mine_code_basis": ("Whether mine_code came from an explicit column or was parsed from mine-name text.", "category", None),
        "state_or_ut_source": ("State/UT text exactly as normalized whitespace from the source.", "text", None),
        "state_or_ut": ("Standardized state/UT name; blank when the source table omits it.", "text", None),
        "district_source": ("District text exactly as normalized whitespace from the source.", "text", None),
        "district": ("Title-cased district label; not reconciled to a boundary vintage.", "text", None),
        "mineral_source": ("Mineral text from an explicit source column; blank where that page omits the column.", "text", None),
        "material_mapping_basis": ("Whether top-50 mapping used the explicit mineral column or only mine-name text.", "category", None),
        "normalized_top50_materials_json": ("JSON array mapping the source mineral/mine text to this project's top-50 taxonomy.", "JSON array", None),
        "chemical_names_json": ("JSON array of taxonomy chemical names linked to mapped materials.", "JSON array", None),
        "symbols_or_formulae_json": ("JSON array of taxonomy symbols/formulae linked to mapped materials.", "JSON array", None),
        "owner_or_lessee": ("Owner or lessee printed in the source table.", "text", None),
        "lease_area_ha": ("Lease area when explicitly tabulated or strictly parsed from a mine name containing a hectare unit.", "number", "hectares"),
        "lease_area_source": ("Source text supporting lease_area_ha.", "text", None),
        "lease_area_basis": ("Whether lease area came from an explicit column or mine-name text.", "category", None),
        "inspection_type": ("Inspection type printed in the source table.", "text", None),
        "inspecting_officer": ("Inspecting officer text printed in the source table.", "text", None),
        "inspection_date_source": ("Inspection date text retained from the source.", "text", None),
        "inspection_date": ("ISO date parsed from a single unambiguous source inspection date.", "date", None),
        "inspection_date_within_fiscal_year": ("Whether the parsed inspection date falls from 1 April through 31 March of the labeled fiscal year; blank when the date could not be parsed.", "boolean", None),
        "violation_date_source": ("Violation-letter date text retained from a dedicated source column.", "text", None),
        "violation_date": ("ISO date parsed from a single unambiguous violation date.", "date", None),
        "show_cause_date_source": ("Show-cause date text retained from a dedicated source column.", "text", None),
        "show_cause_date": ("ISO date parsed from a single unambiguous show-cause date.", "date", None),
        "violation_or_show_cause_source": ("Combined violation/show-cause source cell retained without forcing event type.", "text", None),
        "remarks_source": ("Remarks text retained from the source table.", "text", None),
        "inspection_report_urls_json": ("JSON array of inspection/MCDR report links published in the row.", "JSON array", None),
        "violation_notice_urls_json": ("JSON array of violation-notice links published in the row.", "JSON array", None),
        "show_cause_notice_urls_json": ("JSON array of show-cause links published in the row.", "JSON array", None),
        "all_linked_document_urls_json": ("JSON array of all non-mail document links published in the row.", "JSON array", None),
        "latitude": ("Blank because the regional summary table does not publish a point coordinate.", "number", "decimal degrees"),
        "longitude": ("Blank because the regional summary table does not publish a point coordinate.", "number", "decimal degrees"),
        "coordinates_available_in_summary_source": ("False for these regional summary-table rows.", "boolean", None),
        "spatial_model_integration_status": ("Guardrail excluding non-georeferenced inspection rows from prospectivity evidence.", "text", None),
        "source_id": ("Source-registry identifier.", "text", None),
        "source_url": ("Exact official IBM regional table page.", "URL", None),
        "source_page_title": ("Heading extracted from the official page.", "text", None),
        "source_page_title_fiscal_year_typo": ("True only where the official page title contains a documented fiscal-year typo but the URL/table dates establish the intended year.", "boolean", None),
        "source_html_file": ("Release-relative cached HTML path.", "text", None),
        "source_html_sha256": ("SHA-256 checksum of the cached source HTML.", "text", None),
        "source_accessed_date": ("Date the source page was downloaded or refreshed.", "date", None),
        "mine_identity_method": ("Deduplication method used in the latest-inspected-mine view.", "category", None),
        "mine_identity_key": ("Normalized deterministic grouping key; not an official IBM identifier unless method is mine_code.", "text", None),
        "inspection_event_count": ("Count of event rows grouped into this latest-inspected-mine view row.", "integer", "events"),
        "earliest_inspection_date": ("Earliest parsed inspection date among grouped events.", "date", None),
        "latest_inspection_date": ("Latest parsed inspection date among grouped events.", "date", None),
        "fiscal_years_present_json": ("JSON array of financial years represented by grouped events.", "JSON array", None),
        "source_event_record_ids_json": ("JSON array of source event record IDs grouped into this view row.", "JSON array", None),
    }
    return exact.get(column, (f"{column.replace('_', ' ').capitalize()} in {table_name}.", "text or number", None))


def update_data_dictionary(events: pd.DataFrame, latest: pd.DataFrame) -> None:
    path = OUT / "data_dictionary.csv"
    dictionary = pd.read_csv(path, keep_default_na=False) if path.exists() else pd.DataFrame(
        columns=["table", "column", "definition", "data_type", "unit", "missing_value_policy"]
    )
    dictionary = dictionary.loc[~dictionary["table"].isin([EVENT_TABLE, LATEST_TABLE])].copy()
    rows = []
    for table_name, frame in [(EVENT_TABLE, events), (LATEST_TABLE, latest)]:
        for column in frame.columns:
            definition, data_type, unit = definition_for(column, table_name)
            rows.append({
                "table": table_name,
                "column": column,
                "definition": definition,
                "data_type": data_type,
                "unit": unit,
                "missing_value_policy": "Blank means unavailable, omitted by that regional table, not applicable, or not safely parseable; zero is not imputed.",
            })
    material_table = "india_strategic_materials_top50.csv"
    material_definitions = {
        "ibm_mcdr_inspection_event_rows": ("IBM MCDR inspection event rows mapped to this top-50 material.", "integer", "rows"),
        "ibm_mcdr_latest_inspected_mine_rows": ("Deduplicated latest-inspected-mine view rows mapped to this top-50 material.", "integer", "rows"),
        "ibm_mcdr_source_minerals_json": ("JSON array of explicit IBM table mineral labels mapped to this top-50 material.", "JSON array", None),
        "ibm_mcdr_regional_office_count": ("Distinct IBM regional offices contributing linked inspection events.", "integer", "regional offices"),
    }
    dictionary = dictionary.loc[
        ~(dictionary["table"].eq(material_table) & dictionary["column"].isin(material_definitions))
    ].copy()
    for column, (definition, data_type, unit) in material_definitions.items():
        rows.append({
            "table": material_table,
            "column": column,
            "definition": definition,
            "data_type": data_type,
            "unit": unit,
            "missing_value_policy": "Zero or [] means no linked IBM MCDR inspection-table record in this extract.",
        })
    dictionary = pd.concat([dictionary, pd.DataFrame(rows)], ignore_index=True)
    dictionary.to_csv(path, index=False)


def update_release_validation(validation: dict) -> None:
    path = OUT / "validation_report.json"
    release = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    prior_pass = bool(release.get("checks_pass", True))
    release.update({
        "ibm_mcdr_source_page_count": validation["source_page_count"],
        "ibm_mcdr_inspection_event_rows": validation["event_rows"],
        "ibm_mcdr_latest_inspected_mine_rows": validation["latest_mine_rows"],
        "ibm_mcdr_regional_offices_covered": validation["regional_offices_covered"],
        "ibm_mcdr_fiscal_years_covered": validation["fiscal_years_covered"],
        "ibm_mcdr_rows_with_mine_code": validation["rows_with_mine_code"],
        "ibm_mcdr_rows_with_lease_area": validation["rows_with_lease_area"],
        "ibm_mcdr_rows_linked_to_top50_taxonomy": validation["rows_linked_to_top50_taxonomy"],
        "ibm_mcdr_rows_with_linked_documents": validation["rows_with_linked_documents"],
        "ibm_mcdr_unparsed_multiday_inspection_date_rows": validation["rows_with_unparsed_nonblank_inspection_date"],
        "ibm_mcdr_source_date_anomalies_outside_labeled_fiscal_year": validation["rows_with_parsed_date_outside_labeled_fiscal_year"],
        "ibm_mcdr_guardrail": validation["interpretation_guardrail"],
        "checks_pass": bool(prior_pass and validation["checks_pass"]),
    })
    path.write_text(json.dumps(release, indent=2), encoding="utf-8")


def main() -> None:
    refresh = "--refresh" in __import__("sys").argv
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    materials = json.loads((ROOT / "config" / "materials.json").read_text(encoding="utf-8"))
    material_lookup = {item["material_name"]: item for item in materials}

    downloaded = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cached_page, spec, refresh) for spec in PAGE_SPECS]
        for future in as_completed(futures):
            downloaded.append(future.result())
    downloaded.sort(key=lambda item: (
        -int(item[0]["fiscal_year"].split("-")[0]), item[0]["region"], item[0]["page_number"]
    ))

    all_events = []
    page_validation = []
    for spec, body, raw_path in downloaded:
        events, summary = parse_page(spec, body, raw_path, material_lookup)
        all_events.extend(events)
        page_validation.append(summary)
    events = add_fiscal_year_date_check(pd.DataFrame(all_events))
    events["_valid_event_date_sort"] = pd.to_datetime(
        events["inspection_date"].where(events["inspection_date_within_fiscal_year"].eq(True)),
        errors="coerce",
    )
    events = events.sort_values(
        ["_valid_event_date_sort", "fiscal_year", "ibm_regional_office", "source_page_number", "source_table_row_number"],
        ascending=[False, False, True, True, True],
        na_position="last",
    ).drop(columns="_valid_event_date_sort").reset_index(drop=True)
    latest = make_latest_view(events).sort_values(
        ["latest_inspection_date", "ibm_regional_office", "mine_name"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    invalid_date_rows = events.loc[
        events["inspection_date"].eq("") & events["inspection_date_source"].ne("")
    ]
    outside_fiscal_year = events.loc[events["inspection_date_within_fiscal_year"].eq(False)]
    expected_regions = {
        "Ajmer", "Bangalore", "Bhubaneswar", "Chennai", "Dehradun", "Gandhinagar", "Goa",
        "Guwahati", "Hyderabad", "Jabalpur", "Nagpur", "Raipur", "Ranchi", "Vijayawada",
    }
    covered_regions = set(events["ibm_regional_office"])
    validation = {
        "source_accessed_date": ACCESS_DATE,
        "source_page_count": len(page_validation),
        "event_rows": int(len(events)),
        "unique_event_record_ids": int(events["record_id"].nunique()),
        "latest_mine_rows": int(len(latest)),
        "unique_latest_mine_record_ids": int(latest["record_id"].nunique()),
        "regional_offices_covered": sorted(covered_regions),
        "fiscal_years_covered": sorted(events["fiscal_year"].unique()),
        "event_rows_by_fiscal_year": {
            str(key): int(value) for key, value in events["fiscal_year"].value_counts().sort_index().items()
        },
        "event_rows_by_regional_office": {
            str(key): int(value) for key, value in events["ibm_regional_office"].value_counts().sort_index().items()
        },
        "rows_with_parsed_inspection_date": int(events["inspection_date"].ne("").sum()),
        "rows_with_unparsed_nonblank_inspection_date": int(len(invalid_date_rows)),
        "unparsed_inspection_date_examples": invalid_date_rows[["record_id", "inspection_date_source"]].head(20).to_dict("records"),
        "rows_with_parsed_date_outside_labeled_fiscal_year": int(len(outside_fiscal_year)),
        "outside_fiscal_year_date_examples": outside_fiscal_year[
            ["record_id", "fiscal_year", "inspection_date_source", "inspection_date", "source_url"]
        ].head(20).to_dict("records"),
        "rows_with_mine_code": int(events["mine_code"].ne("").sum()),
        "rows_with_lease_area": int(events["lease_area_ha"].notna().sum()),
        "rows_with_state": int(events["state_or_ut"].ne("").sum()),
        "rows_with_district": int(events["district"].ne("").sum()),
        "rows_linked_to_top50_taxonomy": int(events["normalized_top50_materials_json"].ne("[]").sum()),
        "rows_with_linked_documents": int(events["all_linked_document_urls_json"].ne("[]").sum()),
        "page_extraction": page_validation,
        "checks_pass": bool(
            len(events) >= 1_400
            and events["record_id"].is_unique
            and latest["record_id"].is_unique
            and covered_regions == expected_regions
            and events["coordinates_available_in_summary_source"].eq(False).all()
            and events[["latitude", "longitude"]].isna().all().all()
            and events["inspection_date"].ne("").mean() >= 0.98
        ),
        "interpretation_guardrail": (
            "This is an inventory of public IBM regional inspection-table records, not an exhaustive lease/working-mine register. "
            "Presence shows a published inspection event, not current production, compliance, reserve/resource quantity, exact location, or legal/access status. "
            "No coordinates were inferred, and these rows were excluded from spatial prospectivity modelling."
        ),
    }

    events.to_csv(OUT / EVENT_TABLE, index=False, quoting=csv.QUOTE_MINIMAL)
    latest.to_csv(OUT / LATEST_TABLE, index=False, quoting=csv.QUOTE_MINIMAL)
    (OUT / VALIDATION_FILE).write_text(json.dumps(validation, indent=2), encoding="utf-8")
    update_source_registry()
    update_material_taxonomy(events, latest)
    update_data_dictionary(events, latest)
    update_release_validation(validation)
    print(json.dumps({key: value for key, value in validation.items() if key != "page_extraction"}, indent=2))
    if not validation["checks_pass"]:
        raise SystemExit("IBM MCDR inspection extraction validation failed")


if __name__ == "__main__":
    main()
