#!/usr/bin/env python3
"""Link IBM 2023-24 auction rows to official state Mine Block Summaries.

The script deliberately separates discovery from spatial admission. It first
captures the current MSTC state portal inventory, then applies a reviewed map
for individual IBM rows. A document match is not enough to create geometry:
coordinates must be extracted from a source-labelled boundary table and pass
area and India-coordinate checks before the geometry row is published.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
import geopandas as gpd
from pypdf import PdfReader
from pyproj import Geod, Transformer
from shapely.geometry import Polygon, mapping


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "outputs" / "india_ibm_auctioned_mineral_concessions_2023_24.csv"
RAW = ROOT / "sources" / "raw" / "ibm_auction_mbs_2023_24"
INVENTORY_JSON = RAW / "mstc_state_mbs_inventory.json"
EXTRACTION_AUDIT_JSON = RAW / "selected_document_extraction_audit.json"
MATCH_OUTPUT = ROOT / "outputs" / "india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv"
GEOMETRY_OUTPUT = ROOT / "outputs" / "india_ibm_auctioned_concession_geometries_2023_24.csv"
GEOJSON_OUTPUT = ROOT / "outputs" / "india_ibm_auctioned_concession_geometries_2023_24.geojson"
VALIDATION_OUTPUT = ROOT / "outputs" / "ibm_auction_mbs_geometry_validation.json"
DISTRICT_BOUNDARIES = ROOT / "sources" / "raw" / "2011_Dist.shp"
SOURCE_ID = "SRC_MSTC_STATE_MBS_IBM_AUCTIONS_2023_24"

PORTAL_INDEX = "https://www.mstcecommerce.com/auctionhome/mlcl/index.jsp"
STATE_LINK_CODES = {
    "Andhra Pradesh": "63",
    "Chhattisgarh": "64",
    "Gujarat": "65",
    "Jharkhand": "66",
    "Karnataka": "61",
    "Madhya Pradesh": "67",
    "Maharashtra": "68",
    "Rajasthan": "69",
    "Uttar Pradesh": "301",
    "Goa": "381",
}

# The mapping is intentionally narrow. Each expression was reviewed against the
# state MBS inventory and must resolve to one selected document after the latest
# version rule below. Unlisted IBM records remain unresolved in this release.
CURATED_MATCHES = {
    "IBM-IMYB2024-AUCTION-006": r"north\s+of\s+arjunda",
    "IBM-IMYB2024-AUCTION-007": r"\bsaloni\b",
    "IBM-IMYB2024-AUCTION-008": r"\bdevri\b.*\blimestone\b|\blimestone\b.*\bdevri\b",
    "IBM-IMYB2024-AUCTION-009": r"kareli\s+chandi",
    "IBM-IMYB2024-AUCTION-010": r"giroud\s+uprani",
    "IBM-IMYB2024-AUCTION-011": r"tumrisur[\s-]+garda\s*(?:ii|2)",
    "IBM-IMYB2024-AUCTION-093": r"(?:block\s*)?(?:v|5).*advalpale.*thivim|advalpale.*thivim",
    "IBM-IMYB2024-AUCTION-094": r"(?:block\s*)?(?:vi|6).*cudnem.*cormolem|cudnem.*cormolem",
    "IBM-IMYB2024-AUCTION-095": r"(?:block\s*)?(?:vii|7).*cudnem\b|\bcudnem\b.*(?:block\s*)?(?:vii|7)",
    "IBM-IMYB2024-AUCTION-096": r"(?:block\s*)?(?:viii|8).*thivim.*pirna|thivim.*pirna",
    "IBM-IMYB2024-AUCTION-097": r"(?:block\s*)?(?:ix|9).*surla.*sonshi|surla.*sonshi",
}


def dms(degrees: float, minutes: float, seconds: float) -> float:
    return degrees + minutes / 60 + seconds / 3600


# (longitude, latitude), in the exact source-published point order. These
# tables were transcribed after visual review of page 1 at 150 dpi. Kareli-
# Chandi is intentionally excluded because two latitude cells print malformed
# seconds (34.4.00), and Saloni is retained for audit but withheld because the
# IBM and MBS source areas conflict materially (600 ha versus 670 ha).
DMS_GEOMETRIES = {
    "IBM-IMYB2024-AUCTION-006": [
        (dms(83, 0, 0), dms(21, 16, 46.55)),
        (dms(83, 2, 45.6), dms(21, 16, 46.55)),
        (dms(83, 2, 11.4), dms(21, 17, 37.68)),
        (dms(83, 2, 27.59), dms(21, 17, 46.31)),
        (dms(83, 3, 25.91), dms(21, 16, 13.07)),
        (dms(83, 3, 1.79), dms(21, 16, 1.55)),
        (dms(83, 2, 50.63), dms(21, 16, 17.75)),
        (dms(83, 2, 6.35), dms(21, 16, 11.28)),
        (dms(83, 0, 47.15), dms(21, 16, 20.64)),
        (dms(83, 0, 0), dms(21, 16, 27.48)),
    ],
    "IBM-IMYB2024-AUCTION-007": [
        (dms(82, 7, 13.249), dms(21, 43, 15.560)),
        (dms(82, 7, 12.512), dms(21, 45, 0.058)),
        (dms(82, 8, 26.108), dms(21, 44, 58.316)),
        (dms(82, 8, 25.730), dms(21, 43, 14.860)),
    ],
    "IBM-IMYB2024-AUCTION-008": [
        (dms(82, 8, 26.186), dms(21, 43, 44.180)),
        (dms(82, 8, 26.108), dms(21, 44, 58.316)),
        (dms(82, 10, 0.723), dms(21, 44, 59.100)),
        (dms(82, 10, 0.551), dms(21, 43, 43.109)),
    ],
    "IBM-IMYB2024-AUCTION-010": [
        (dms(82, 30, 13.8695), dms(21, 36, 23.7976)),
        (dms(82, 30, 58.6189), dms(21, 36, 23.9120)),
        (dms(82, 30, 58.6189), dms(21, 37, 1.2600)),
        (dms(82, 33, 8.4804), dms(21, 37, 1.3029)),
        (dms(82, 33, 8.4804), dms(21, 36, 26.0107)),
        (dms(82, 34, 25.2323), dms(21, 36, 26.6960)),
        (dms(82, 34, 24.8896), dms(21, 37, 25.6305)),
        (dms(82, 35, 9.6000), dms(21, 37, 25.6305)),
        (dms(82, 35, 9.6000), dms(21, 35, 41.7081)),
        (dms(82, 33, 44.8193), dms(21, 35, 36.8254)),
        (dms(82, 31, 39.9261), dms(21, 35, 29.8869)),
        (dms(82, 31, 8.7799), dms(21, 34, 33.7792)),
        (dms(82, 30, 13.6297), dms(21, 34, 30.1732)),
    ],
    "IBM-IMYB2024-AUCTION-011": [
        (dms(80, 53, 13.74), dms(20, 11, 19.00)),
        (dms(80, 53, 40.29), dms(20, 11, 19.00)),
        (dms(80, 53, 40.29), dms(20, 13, 0.326)),
        (dms(80, 53, 13.74), dms(20, 13, 0.326)),
    ],
    "IBM-IMYB2024-AUCTION-096": [
        (dms(73, 52, 43.324), dms(15, 39, 20.799)),
        (dms(73, 52, 26.200), dms(15, 39, 20.916)),
        (dms(73, 52, 25.696), dms(15, 39, 16.386)),
        (dms(73, 52, 22.604), dms(15, 38, 53.988)),
        (dms(73, 52, 31.741), dms(15, 38, 44.153)),
        (dms(73, 52, 48.869), dms(15, 38, 44.015)),
        (dms(73, 52, 48.930), dms(15, 38, 45.828)),
        (dms(73, 52, 49.094), dms(15, 38, 52.654)),
        (dms(73, 52, 48.969), dms(15, 38, 54.085)),
        (dms(73, 52, 44.987), dms(15, 39, 9.334)),
    ],
}

MBS_AREA_HA = {
    "IBM-IMYB2024-AUCTION-006": 600.0,
    "IBM-IMYB2024-AUCTION-007": 670.0,
    "IBM-IMYB2024-AUCTION-008": 630.0,
    "IBM-IMYB2024-AUCTION-009": 500.0,
    "IBM-IMYB2024-AUCTION-010": 2400.0,
    "IBM-IMYB2024-AUCTION-011": 240.0,
    "IBM-IMYB2024-AUCTION-093": 36.2202,
    "IBM-IMYB2024-AUCTION-094": 38.5143,
    "IBM-IMYB2024-AUCTION-095": 75.3004,
    "IBM-IMYB2024-AUCTION-096": 72.0544,
    "IBM-IMYB2024-AUCTION-097": 254.51,
}

PROFILE_NUMBERS = {
    "IBM-IMYB2024-AUCTION-006": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-007": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-008": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-009": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-010": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-011": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-093": {"exploration_level": "G1; G2; G3", "borehole_count": 120, "drilled_meterage_m": 6504.9},
    "IBM-IMYB2024-AUCTION-094": {"exploration_level": "G1; G2; G3", "borehole_count": 147, "drilled_meterage_m": 7981.4},
    "IBM-IMYB2024-AUCTION-095": {"exploration_level": "G1; G2; G3", "borehole_count": 94, "drilled_meterage_m": 5886.9},
    "IBM-IMYB2024-AUCTION-096": {"exploration_level": "G1; G2", "borehole_count": 35, "drilled_meterage_m": 1583.6},
    "IBM-IMYB2024-AUCTION-097": {"exploration_level": "G1; G2", "borehole_count": 494, "drilled_meterage_m": 53453.6},
}

# Concise source-normalized summaries for fields where PDF text order causes a
# generic parser to confuse labels such as "Mineral Block" and "Grade-wise"
# with the actual mineral and grade cells. Values are not inferred beyond the
# source: printed anomalies and "not estimated" statements are retained.
PROFILE_TEXT = {
    "IBM-IMYB2024-AUCTION-006": {
        "mineral_source_mbs": "Glauconite (Potash) and associated mineralization",
        "geological_resources_source": "Resources have not been estimated.",
        "grade_source": "K2O ranges from 0.60% to 7.5% (average 1.88%) in pitting-trenching samples.",
        "climate_source": "Mean annual rainfall 1200 mm; December temperature 8 C; June temperature up to 48 C.",
    },
    "IBM-IMYB2024-AUCTION-008": {
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "Tentative resource: 51.03 MnT.",
        "grade_source": "Cement (Portland) grade.",
        "climate_source": "Mean annual rainfall 1223 mm (IMD, 2021); December temperature 6 C; June temperature 46 C.",
    },
    "IBM-IMYB2024-AUCTION-010": {
        "mineral_source_mbs": "Glauconite (Potash) and associated mineralization",
        "geological_resources_source": "Resources have not been estimated.",
        "grade_source": "K2O ranges from 0.20% to 5.08% in pitting-trenching samples; EPMA values reach 8.26 wt% in altered glauconite.",
        "climate_source": "Mean annual rainfall 1200-1500 mm; December temperature 8 C; June temperature up to 46 C.",
    },
    "IBM-IMYB2024-AUCTION-011": {
        "mineral_source_mbs": "Gold",
        "geological_resources_source": "Nil.",
        "grade_source": "0.55-0.73 ppm Au in trench samples, with isolated high values of 1.2 ppm Au.",
        "climate_source": "Mean annual rainfall around 140 cm; December-January temperature down to 10 C; May-June temperature up to 45 C.",
    },
    "IBM-IMYB2024-AUCTION-093": {
        "mineral_source_mbs": "Iron ore (hematite)",
        "geological_resources_source": "In-situ geological resource 3.828 million tons; estimated resource in dumps 417,020 tons, as on 2022-06-01.",
        "grade_source": "In-situ fines Fe 57.43%; lumps Fe 59.58%. Dump material is 45% to below 51% Fe.",
        "climate_source": "Mean annual rainfall 3500 mm; winter temperature 16-21 C; summer temperature 36-38 C.",
    },
    "IBM-IMYB2024-AUCTION-095": {
        "mineral_source_mbs": "Iron ore (hematite)",
        "geological_resources_source": "In-situ geological resource 8.282 million tons; estimated resource in dumps 2,221,350 tons, as on 2022-06-01.",
        "grade_source": "In-situ fines Fe 55.72%; lumps Fe 57.87%. Dump material is 45% to below 51% Fe.",
        "climate_source": "Annual rainfall printed as around 4000 m in the MBS (source-unit anomaly retained); winter temperature 16-21 C; summer temperature 36-38 C.",
    },
    "IBM-IMYB2024-AUCTION-096": {
        "mineral_source_mbs": "Iron ore (hematite)",
        "geological_resources_source": "In-situ geological resource 1.687 million tons; estimated resource in dumps 208,210 tons, as on 2022-06-01.",
        "grade_source": "In-situ fines Fe 54.13%; lumps Fe 55.63%. Dump material is 45% to below 51% Fe.",
        "climate_source": "Mean annual rainfall 3500 mm; winter temperature 16-21 C; summer temperature 36-38 C.",
    },
    "IBM-IMYB2024-AUCTION-097": {
        "mineral_source_mbs": "Iron ore (hematite)",
        "geological_resources_source": "In-situ geological resource 65.728 million tons; estimated resource in dumps 2,686,620 tons, as on 2022-06-01.",
        "grade_source": "In-situ fines Fe 44.63%; lumps Fe 46.38%. Dump material is 45% to below 51% Fe.",
        "climate_source": "Mean annual rainfall 3750 mm (minimum 3500 mm, maximum 4000 mm); winter temperature 20 C; summer temperature 38 C.",
    },
}

GEOMETRY_WITHHOLD_REASONS = {
    "IBM-IMYB2024-AUCTION-007": "IBM publishes 600 ha while the matched MBS publishes 670 ha; geometry withheld pending source reconciliation.",
    "IBM-IMYB2024-AUCTION-009": "The matched MBS prints malformed latitude seconds for points F and G ('34.4.00'); geometry withheld rather than corrected by inference.",
}


@dataclass(frozen=True)
class PortalDocument:
    state: str
    title: str
    href: str
    url: str
    file_id: str


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture = False
        self.href = ""
        self.parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        self.capture = True
        self.href = href
        self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.capture:
            self.anchors.append((normalize_text(" ".join(self.parts)), self.href))
            self.capture = False


def normalize_text(value: str) -> str:
    value = html.unescape(value).replace("\xa0", " ").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value).strip()


def match_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_text(value)).encode("ascii", "ignore").decode()
    value = value.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def file_id_from_url(url: str) -> str:
    source_name = unquote(parse_qs(urlparse(url).query).get("FILE_ID", [""])[0])
    match = re.match(r"(\d+)_", source_name)
    return match.group(1) if match else ""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_filename(value: str, limit: int = 105) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (value or "document")[:limit]


def fetch_state_inventory(session: requests.Session, state: str, code: str) -> tuple[str, list[PortalDocument]]:
    listing_url = "https://www.mstcecommerce.com/auctionhome/mlcl/mlcl_listing.jsp"
    listing = session.post(listing_url, data={"link_id": code}, timeout=90)
    listing.raise_for_status()
    parser = AnchorParser()
    parser.feed(listing.text)
    summary_links = [
        urljoin(listing.url, href)
        for text, href in parser.anchors
        if "mine block summary" in text.lower() and "container.jsp" in href
    ]
    if len(summary_links) != 1:
        raise RuntimeError(f"{state}: expected one Mine Block Summary link, found {len(summary_links)}")

    page = session.get(summary_links[0], timeout=90)
    page.raise_for_status()
    parser = AnchorParser()
    parser.feed(page.text)
    docs: list[PortalDocument] = []
    seen: set[str] = set()
    for title, href in parser.anchors:
        if "download_docs.jsp" not in href:
            continue
        url = urljoin(page.url, href)
        file_id = file_id_from_url(url)
        key = file_id or url
        if key in seen:
            continue
        seen.add(key)
        docs.append(PortalDocument(state, title, href, url, file_id))
    return page.url, docs


def collect_inventory(refresh: bool) -> dict:
    if INVENTORY_JSON.exists() and not refresh:
        return json.loads(INVENTORY_JSON.read_text())

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 KHANAN open research dataset"})
    session.get(PORTAL_INDEX, timeout=90).raise_for_status()
    payload = {
        "source": PORTAL_INDEX,
        "access_date": date.today().isoformat(),
        "states": {},
    }
    for state, code in STATE_LINK_CODES.items():
        page_url, docs = fetch_state_inventory(session, state, code)
        payload["states"][state] = {
            "mine_block_summary_page_url": page_url,
            "document_count": len(docs),
            "documents": [doc.__dict__ for doc in docs],
        }
        print(f"inventory {state}: {len(docs)} documents", file=sys.stderr)
    RAW.mkdir(parents=True, exist_ok=True)
    INVENTORY_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload


def load_ibm_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def candidate_documents(row: dict[str, str], inventory: dict) -> list[dict]:
    expression = CURATED_MATCHES.get(row["record_id"])
    if not expression:
        return []
    docs = inventory["states"][row["state_or_ut"]]["documents"]
    return [doc for doc in docs if re.search(expression, match_text(doc["title"]), flags=re.I)]


def select_latest(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    # MSTC file identifiers increase over time and are stable source identifiers.
    return max(candidates, key=lambda doc: int(doc["file_id"]) if doc["file_id"].isdigit() else -1)


def download_document(doc: dict, refresh: bool) -> tuple[Path, bytes]:
    state_dir = RAW / "pdf" / safe_filename(doc["state"])
    path = state_dir / f"{doc['file_id']}_{safe_filename(doc['title'])}.pdf"
    if path.exists() and not refresh:
        return path, path.read_bytes()
    response = requests.get(doc["url"], timeout=120, headers={"User-Agent": "Mozilla/5.0 KHANAN open research dataset"})
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"MSTC response is not a PDF: {doc['url']}")
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, content


def extract_pdf_pages(path: Path) -> list[str]:
    reader = PdfReader(path)
    return [(page.extract_text() or "") for page in reader.pages]


DMS_TOKEN = re.compile(
    r"(?P<deg>\d{1,3})\s*(?:[°º]|deg(?:ree)?s?)\s*(?P<min>\d{1,2})\s*[\'’′]?\s*"
    r"(?P<sec>\d{1,2}(?:\.\d+)?)\s*[\"”″]?\s*(?P<hem>[NSEW])?",
    flags=re.I,
)


def dms_to_decimal(match: re.Match) -> float:
    value = float(match.group("deg")) + float(match.group("min")) / 60 + float(match.group("sec")) / 3600
    if (match.group("hem") or "").upper() in {"S", "W"}:
        value *= -1
    return value


def extract_coordinate_candidates(pages: list[str]) -> list[dict]:
    """Extract candidate DMS runs; publication still requires reviewed overrides.

    PDF text order is frequently column-major, so these candidates are audit
    evidence only. Coordinates are never paired or reordered automatically.
    """
    output: list[dict] = []
    for page_number, text in enumerate(pages, start=1):
        tokens = []
        for match in DMS_TOKEN.finditer(text):
            value = dms_to_decimal(match)
            if 6 <= abs(value) <= 100:
                tokens.append({"raw": match.group(0), "decimal": value, "start": match.start()})
        if tokens:
            output.append({"page": page_number, "tokens": tokens})
    return output


def extract_utm43_points(pages: list[str]) -> tuple[list[tuple[float, float]], list[int], list[int]]:
    """Read source-ordered WGS84/UTM zone 43N points from text rows.

    The parser requires a labelled BP row and plausible seven-digit northing
    and six-digit easting. It does not repair missing or duplicate point IDs.
    """
    points: dict[int, tuple[float, float]] = {}
    source_pages: dict[int, int] = {}
    pending_id: int | None = None
    for page_number, text in enumerate(pages, start=1):
        for raw_line in text.splitlines():
            line = normalize_text(raw_line)
            label = re.search(r"\bB\s*\.?\s*P\s*\.?\s*(\d{1,3})\b", line, flags=re.I)
            # Some PDFs emit a duplicate/corrupt label on a line between the
            # real point label and its coordinate values (notably BP3 followed
            # by a spurious BP1 in Goa Block VII). Preserve the first pending
            # source label until its coordinate row is consumed.
            if label and pending_id is None:
                pending_id = int(label.group(1))
            if pending_id is None:
                continue
            numbers = [float(value) for value in re.findall(r"\b\d{6,7}(?:\.\d+)?\b", line)]
            northings = [value for value in numbers if 1_000_000 <= value <= 3_000_000]
            eastings = [value for value in numbers if 100_000 <= value <= 900_000]
            if northings and eastings:
                if pending_id in points:
                    raise ValueError(f"duplicate UTM coordinate row for BP {pending_id}")
                points[pending_id] = (eastings[-1], northings[-1])
                source_pages[pending_id] = page_number
                pending_id = None
    if not points:
        raise ValueError("no labelled UTM zone 43N coordinates found")
    ids = sorted(points)
    if ids != list(range(1, max(ids) + 1)):
        raise ValueError(f"non-contiguous boundary point identifiers: {ids}")
    transformer = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
    coordinates = [transformer.transform(*points[point_id]) for point_id in ids]
    return coordinates, ids, sorted(set(source_pages.values()))


def source_profile(pages: list[str]) -> dict[str, str]:
    text = normalize_text("\n".join(pages))

    def between(starts: list[str], ends: list[str], limit: int = 1800) -> str:
        start_match = None
        for start in starts:
            candidate = re.search(start, text, flags=re.I)
            if candidate and (start_match is None or candidate.end() < start_match.end()):
                start_match = candidate
        if not start_match:
            return ""
        tail = text[start_match.end():]
        end_positions = []
        for end in ends:
            candidate = re.search(end, tail, flags=re.I)
            if candidate:
                end_positions.append(candidate.start())
        value = tail[: min(end_positions) if end_positions else limit]
        value = normalize_text(value).strip(" :-")
        return value[:limit]

    return {
        "exploration_agency_source": between([r"Exploration Agency"], [r"Pitting\s*/?\s*Trenching"]),
        "borehole_summary_source": between(
            [r"Total (?:Number|number) of Boreholes?(?: with\s+meterage)?"],
            [r"Borehole Spacing"],
        ),
        "mineral_source_mbs": between(
            [r"\bMinerals?\b"],
            [r"\*?Total Geological Resources", r"Total Geological Resources \(Reserves\)"],
        ),
        "geological_resources_source": between(
            [r"\*?Total Geological Resources(?: \(Reserves\))?(?: As on \d{2}\.\d{2}\.\d{4})?"],
            [r"\bGrade\b", r"Mineralised Zones"],
        ),
        "grade_source": between([r"\bGrade\b"], [r"Minerali[sz]ed Zones"]),
        "mineral_zones_source": between([r"Number of Mineral Zones"], [r"Trend \(Dip"]),
        "dip_strike_source": between(
            [r"Trend \(Dip (?:and|&) Strike\)"],
            [r"Total Thickness", r"Average Thickness", r"\bAccessibility\b"],
        ),
        "thickness_source": between(
            [r"(?:Total|Average) Thickness"],
            [r"\bAccessibility\b"],
        ),
        "accessibility_source": between([r"\bAccessibility\b"], [r"\bHydrography\b"]),
        "hydrography_source": between([r"\bHydrography\b"], [r"\bClimate\b"]),
        "climate_source": between([r"Mean Annual Rainfall"], [r"\bTopography\b"]),
        "topography_source": between([r"Morphology(?: of the Area)?"], [r"Part B", r"PART B"]),
    }


def source_area_difference_pct(ibm_area_ha: str, mbs_area_ha: float) -> float | None:
    if not ibm_area_ha:
        return None
    return abs(float(ibm_area_ha) - mbs_area_ha) / mbs_area_ha * 100


def geodesic_area_ha(polygon: Polygon) -> float:
    geod = Geod(ellps="WGS84")
    area_m2, _ = geod.geometry_area_perimeter(polygon)
    return abs(area_m2) / 10_000


def load_state_shapes() -> dict[str, object]:
    districts = gpd.read_file(DISTRICT_BOUNDARIES).to_crs("EPSG:4326")
    return {
        state: districts.loc[districts["ST_NM"] == state, "geometry"].union_all()
        for state in {"Chhattisgarh", "Goa"}
    }


def build_geometry(
    row: dict[str, str], pages: list[str], state_shapes: dict[str, object]
) -> tuple[dict | None, dict]:
    record_id = row["record_id"]
    if record_id in GEOMETRY_WITHHOLD_REASONS:
        return None, {
            "geometry_admission_status": "withheld_source_conflict",
            "geometry_admission_reason": GEOMETRY_WITHHOLD_REASONS[record_id],
        }

    if record_id in DMS_GEOMETRIES:
        coordinates = DMS_GEOMETRIES[record_id]
        source_pages = [1]
        coordinate_method = "source_table_visual_transcription_dms_wgs84"
        point_ids = list(range(1, len(coordinates) + 1))
        quality_flags = []
        if record_id == "IBM-IMYB2024-AUCTION-096":
            point_ids = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11]
            quality_flags.append("source_point_id_6_absent")
    elif record_id in {
        "IBM-IMYB2024-AUCTION-093",
        "IBM-IMYB2024-AUCTION-094",
        "IBM-IMYB2024-AUCTION-095",
        "IBM-IMYB2024-AUCTION-097",
    }:
        coordinates, point_ids, source_pages = extract_utm43_points(pages)
        coordinate_method = "source_table_text_extraction_utm43n_to_wgs84"
        quality_flags = []
    else:
        return None, {
            "geometry_admission_status": "withheld_not_reviewed",
            "geometry_admission_reason": "No reviewed source-coordinate transcription is configured for this record.",
        }

    polygon = Polygon(coordinates)
    mbs_area_ha = MBS_AREA_HA[record_id]
    computed_area_ha = geodesic_area_ha(polygon)
    computed_difference_pct = abs(computed_area_ha - mbs_area_ha) / mbs_area_ha * 100
    state_shape = state_shapes[row["state_or_ut"]]
    centroid_in_state = bool(state_shape.covers(polygon.centroid))
    footprint_in_state = bool(state_shape.covers(polygon))
    source_difference_pct = source_area_difference_pct(row["area_ha"], mbs_area_ha)

    checks = {
        "polygon_valid": bool(polygon.is_valid),
        "centroid_in_source_state": centroid_in_state,
        "footprint_in_source_state_2011_boundary": footprint_in_state,
        "computed_to_mbs_area_difference_pct": round(computed_difference_pct, 6),
        "ibm_to_mbs_area_difference_pct": round(source_difference_pct, 6) if source_difference_pct is not None else None,
    }
    if not polygon.is_valid:
        reason = "Source point order creates an invalid polygon; geometry withheld."
    elif not centroid_in_state:
        reason = "Polygon centroid falls outside the source state in the 2011 district boundary layer; geometry withheld."
    elif computed_difference_pct > 5:
        reason = f"Computed geodesic area differs from the MBS area by {computed_difference_pct:.2f}%; geometry withheld."
    elif source_difference_pct is not None and source_difference_pct > 5:
        reason = f"IBM and MBS published areas differ by {source_difference_pct:.2f}%; geometry withheld."
    else:
        reason = "Source-labelled boundary table passed polygon validity, state-centroid and 5% area reconciliation checks."

    if "withheld" in reason:
        return None, {
            "geometry_admission_status": "withheld_validation_failure",
            "geometry_admission_reason": reason,
            **checks,
        }

    if not footprint_in_state:
        quality_flags.append("footprint_not_fully_covered_by_2011_state_boundary")
    geometry = {
        "coordinate_method": coordinate_method,
        "coordinate_source_pdf_pages_json": json.dumps(source_pages),
        "boundary_point_ids_json": json.dumps(point_ids),
        "boundary_vertex_count": len(coordinates),
        "polygon_wkt": polygon.wkt,
        "centroid_latitude": round(polygon.centroid.y, 8),
        "centroid_longitude": round(polygon.centroid.x, 8),
        "computed_geodesic_area_ha": round(computed_area_ha, 6),
        "computed_to_mbs_area_difference_pct": round(computed_difference_pct, 6),
        "ibm_to_mbs_area_difference_pct": round(source_difference_pct, 6) if source_difference_pct is not None else "",
        "polygon_valid": True,
        "centroid_in_source_state": centroid_in_state,
        "footprint_in_source_state_2011_boundary": footprint_in_state,
        "geometry_quality_flags_json": json.dumps(quality_flags),
        "geometry_admission_status": "admitted_authoritative_source_footprint",
        "geometry_admission_reason": reason,
        "_polygon": polygon,
    }
    return geometry, checks


def output_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def upsert_source_registry(access_date: str) -> None:
    path = ROOT / "outputs" / "source_registry.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["source_id"] != SOURCE_ID]
    rows.append({
        "source_id": SOURCE_ID,
        "publisher": "MSTC Limited and participating State Governments",
        "title": "State mineral-auction Mine Block Summary portal documents linked to IBM Table 5 (2023-24)",
        "release_or_reference_date": f"source documents reviewed; portal accessed {access_date}",
        "url": PORTAL_INDEX,
        "download_url": "Exact PDF URL, file identifier, SHA-256, byte size and page count are retained per matched row.",
        "license_or_access_note": "Public government-owned auction portal; retain document-level attribution and verify current portal and State Government reuse terms.",
        "used_for": "Reviewed document links, source-published concession boundary coordinates, exploration summaries, geological resources, grades, climate, terrain, hydrology and access context.",
        "limitations": "Only eleven of 97 IBM rows are reviewed in alpha.9. Mine Block Summaries describe auction-stage technical context and do not independently prove current operation, present legal status, access permission or reserve classification. Source conflicts are withheld, not repaired by inference.",
    })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def upsert_data_dictionary(match_fields: list[str], geometry_fields: list[str]) -> None:
    path = ROOT / "outputs" / "data_dictionary.csv"
    table_columns = {
        MATCH_OUTPUT.name: match_fields,
        GEOMETRY_OUTPUT.name: geometry_fields,
    }
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = [row for row in reader if row["table"] not in table_columns]

    definitions = {
        "review_scope": "Whether this IBM row received curated document review in alpha.9.",
        "curated_candidate_count": "Number of MSTC documents matching the reviewed record-specific expression; zero does not mean the portal lacks a relevant document for unreviewed rows.",
        "document_selection_rule": "Rule used to select one official document when a reviewed expression matched multiple versions.",
        "document_match_status": "Outcome of curated IBM-to-MSTC document matching.",
        "selected_mbs_file_id": "Numeric MSTC source-file identifier.",
        "selected_mbs_title": "MSTC link title for the selected Mine Block Summary.",
        "selected_mbs_url": "Exact official Mine Block Summary PDF URL.",
        "selected_mbs_pdf_sha256": "SHA-256 of the downloaded official Mine Block Summary PDF.",
        "selected_mbs_pdf_bytes": "Downloaded Mine Block Summary PDF size in bytes.",
        "selected_mbs_pdf_page_count": "Mine Block Summary PDF page count.",
        "ibm_area_ha": "Concession or block area published in IBM Table 5, in hectares.",
        "mbs_area_ha": "Area published in the selected Mine Block Summary, normalized to hectares.",
        "ibm_to_mbs_area_difference_pct": "Absolute percentage difference between IBM and MBS published areas, relative to the MBS area.",
        "geometry_admission_status": "Whether the source footprint passed the alpha.9 spatial publication gates.",
        "geometry_admission_reason": "Specific evidence or failure responsible for geometry admission or withholding.",
        "coordinate_method": "Reviewed coordinate extraction and CRS-conversion method.",
        "coordinate_source_pdf_pages_json": "JSON array of one-based physical PDF pages containing the boundary coordinate table.",
        "boundary_point_ids_json": "JSON array of source boundary-point identifiers in published order.",
        "boundary_vertex_count": "Number of source boundary vertices used to construct the polygon.",
        "polygon_wkt": "Source-order concession footprint encoded as WKT in EPSG:4326.",
        "geometry_crs": "Coordinate reference system of polygon and centroid fields.",
        "coordinate_datum_source": "Datum stated in the source coordinate table.",
        "centroid_latitude": "Latitude of the source-order polygon centroid.",
        "centroid_longitude": "Longitude of the source-order polygon centroid.",
        "computed_geodesic_area_ha": "WGS84 ellipsoidal polygon area computed from the published boundary vertices.",
        "computed_to_mbs_area_difference_pct": "Absolute percentage difference between computed geodesic area and MBS published area.",
        "polygon_valid": "True when the source-order polygon passes Shapely validity.",
        "centroid_in_source_state": "True when the polygon centroid is covered by the source state in the 2011 district boundary layer.",
        "footprint_in_source_state_2011_boundary": "True when the full polygon is covered by the source state in the 2011 district boundary layer.",
        "geometry_quality_flags_json": "JSON array of non-fatal geometry or source-table caveats.",
        "exploration_level": "Exploration level printed in the Mine Block Summary.",
        "borehole_count": "Boreholes reported for the block; explicit Nil or not-drilled statements are normalized to zero.",
        "drilled_meterage_m": "Cumulative drilling meterage reported for the block; explicit Nil or not-drilled statements are normalized to zero.",
        "exploration_agency_source": "Exploration agency wording extracted from the Mine Block Summary.",
        "borehole_summary_source": "Source text describing block boreholes and meterage.",
        "mineral_source_mbs": "Mineral wording normalized from the selected Mine Block Summary.",
        "geological_resources_source": "Concise source-normalized geological resource statement; no resource is inferred when the source says Nil or not estimated.",
        "grade_source": "Concise source-normalized grade statement with printed units.",
        "mineral_zones_source": "Mine Block Summary text describing mineralized zones.",
        "dip_strike_source": "Mine Block Summary text describing structural trend, dip or strike.",
        "thickness_source": "Mine Block Summary text describing mineralized-zone thickness.",
        "accessibility_source": "Mine Block Summary access and infrastructure text.",
        "hydrography_source": "Mine Block Summary drainage, river and stream text.",
        "climate_source": "Concise source-normalized rainfall and temperature statement; explicit source-unit anomalies are retained and labelled.",
        "topography_source": "Mine Block Summary terrain or morphology text.",
        "current_legal_or_operational_status_verified": "Always false in this layer; the source combination does not independently verify present legal or operating status.",
        "model_evidence_role": "Context only in alpha.9; rows do not enter training, labels, scoring or candidate promotion.",
        "model_exclusion_reason": "Reason the record is excluded from model evidence.",
    }
    boolean_columns = {
        "polygon_valid", "centroid_in_source_state", "footprint_in_source_state_2011_boundary",
        "current_legal_or_operational_status_verified",
    }
    numeric_columns = {
        "curated_candidate_count", "selected_mbs_pdf_bytes", "selected_mbs_pdf_page_count",
        "ibm_area_ha", "mbs_area_ha", "ibm_to_mbs_area_difference_pct", "boundary_vertex_count",
        "centroid_latitude", "centroid_longitude", "computed_geodesic_area_ha",
        "computed_to_mbs_area_difference_pct", "borehole_count", "drilled_meterage_m",
    }
    for table, columns in table_columns.items():
        for column in columns:
            unit = ""
            if column.endswith("_ha"):
                unit = "hectares"
            elif column.endswith("_pct"):
                unit = "percent"
            elif column in {"centroid_latitude", "centroid_longitude"}:
                unit = "decimal degrees"
            elif column == "drilled_meterage_m":
                unit = "metres"
            elif column.endswith("_json"):
                unit = "JSON"
            rows.append({
                "table": table,
                "column": column,
                "definition": definitions.get(column, column.replace("_", " ").capitalize() + "."),
                "data_type": "boolean" if column in boolean_columns else "number" if column in numeric_columns else "string",
                "unit": unit,
                "missing_value_policy": "Blank means not reviewed, not published, not applicable or unavailable; zero appears only for an explicit Nil/not-drilled statement.",
            })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def update_release_validation(validation: dict) -> None:
    path = ROOT / "outputs" / "validation_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["development_release_version"] = "v1.0-alpha.9"
    report["ibm_auction_mbs_geometry_2023_24"] = {
        "ibm_input_rows": validation["ibm_input_rows"],
        "state_portal_documents_total": validation["state_portal_documents_total"],
        "curated_records": validation["curated_records"],
        "selected_document_matches": validation["selected_document_matches"],
        "published_geometries": validation["published_geometries"],
        "geometry_admission_status_counts": validation["geometry_admission_status_counts"],
        "all_geometry_polygons_valid": validation["all_geometry_polygons_valid"],
        "all_geometry_centroids_in_source_state": validation["all_geometry_centroids_in_source_state"],
        "all_geometry_computed_area_differences_lte_5pct": validation["all_geometry_computed_area_differences_lte_5pct"],
        "model_evidence_role": validation["model_evidence_role"],
    }
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def publish_outputs(inventory: dict, rows: list[dict[str, str]], refresh: bool) -> None:
    state_shapes = load_state_shapes()
    match_rows: list[dict] = []
    geometry_rows: list[dict] = []
    features: list[dict] = []

    for row in rows:
        record_id = row["record_id"]
        candidates = candidate_documents(row, inventory)
        selected = select_latest(candidates)
        match = {
            "record_id": record_id,
            "state_or_ut": row["state_or_ut"],
            "block_name": row["block_name"],
            "mineral_source": row["mineral_source"],
            "normalized_material_ids_json": row["normalized_material_ids_json"],
            "auction_date": row["auction_date"],
            "concession_type_code": row["concession_type_code"],
            "ibm_area_ha": row["area_ha"],
            "review_scope": "curated_alpha_9" if record_id in CURATED_MATCHES else "not_reviewed_alpha_9",
            "curated_candidate_count": len(candidates),
            "document_selection_rule": "highest_numeric_mstc_file_id" if len(candidates) > 1 else "unique_curated_name_match" if selected else "",
            "document_match_status": "selected_curated_name_match" if selected else "not_reviewed_in_this_release",
            "selected_mbs_file_id": "",
            "selected_mbs_title": "",
            "selected_mbs_url": "",
            "selected_mbs_pdf_sha256": "",
            "selected_mbs_pdf_bytes": "",
            "selected_mbs_pdf_page_count": "",
            "mbs_area_ha": MBS_AREA_HA.get(record_id, ""),
            "ibm_to_mbs_area_difference_pct": "",
            "geometry_admission_status": "withheld_not_reviewed",
            "geometry_admission_reason": "No curated document match was reviewed in this release.",
            "source_portal_url": PORTAL_INDEX,
            "source_access_date": inventory["access_date"],
            "model_evidence_role": "context_only",
            "model_exclusion_reason": "State MBS and IBM auction context do not independently verify current operation or present legal status.",
        }
        if not selected:
            match_rows.append(match)
            continue

        path, content = download_document(selected, refresh)
        pages = extract_pdf_pages(path)
        match.update({
            "selected_mbs_file_id": selected["file_id"],
            "selected_mbs_title": selected["title"],
            "selected_mbs_url": selected["url"],
            "selected_mbs_pdf_sha256": sha256_bytes(content),
            "selected_mbs_pdf_bytes": len(content),
            "selected_mbs_pdf_page_count": len(pages),
        })
        if record_id in MBS_AREA_HA:
            difference = source_area_difference_pct(row["area_ha"], MBS_AREA_HA[record_id])
            match["ibm_to_mbs_area_difference_pct"] = round(difference, 6) if difference is not None else ""

        geometry, diagnostics = build_geometry(row, pages, state_shapes)
        if geometry is None:
            match.update({
                "geometry_admission_status": diagnostics["geometry_admission_status"],
                "geometry_admission_reason": diagnostics["geometry_admission_reason"],
            })
            match_rows.append(match)
            continue

        profile = source_profile(pages)
        profile.update(PROFILE_TEXT[record_id])
        numeric_profile = PROFILE_NUMBERS[record_id]
        geometry_row = {
            "record_id": record_id,
            "record_type": "official_state_mbs_boundary_context",
            "state_or_ut": row["state_or_ut"],
            "block_name": row["block_name"],
            "block_name_mbs": selected["title"],
            "mineral_source_ibm": row["mineral_source"],
            "normalized_material_ids_json": row["normalized_material_ids_json"],
            "normalized_material_names_json": row["normalized_material_names_json"],
            "chemical_or_english_names_json": row["chemical_or_english_names_json"],
            "formulae_or_symbols_json": row["formulae_or_symbols_json"],
            "auction_date_ibm": row["auction_date"],
            "concession_type_code_ibm": row["concession_type_code"],
            "ibm_area_ha": row["area_ha"],
            "mbs_area_ha": MBS_AREA_HA[record_id],
            **numeric_profile,
            **profile,
            **{key: value for key, value in geometry.items() if key != "_polygon"},
            "geometry_crs": "EPSG:4326",
            "coordinate_datum_source": "WGS 84",
            "selected_mbs_file_id": selected["file_id"],
            "selected_mbs_url": selected["url"],
            "source_access_date": inventory["access_date"],
            "selected_mbs_pdf_sha256": sha256_bytes(content),
            "selected_mbs_pdf_bytes": len(content),
            "selected_mbs_pdf_page_count": len(pages),
            "current_legal_or_operational_status_verified": False,
            "model_evidence_role": "context_only",
            "model_exclusion_reason": "Geometry and technical context are authoritative to the MBS, but current operation and present legal status are not independently verified.",
        }
        geometry_rows.append(geometry_row)
        feature_properties = {key: value for key, value in geometry_row.items() if key != "polygon_wkt"}
        features.append({
            "type": "Feature",
            "geometry": mapping(geometry["_polygon"]),
            "properties": feature_properties,
        })
        match.update({
            "geometry_admission_status": geometry["geometry_admission_status"],
            "geometry_admission_reason": geometry["geometry_admission_reason"],
        })
        match_rows.append(match)

    match_fields = [
        "record_id", "state_or_ut", "block_name", "mineral_source", "normalized_material_ids_json",
        "auction_date", "concession_type_code", "ibm_area_ha", "review_scope", "curated_candidate_count",
        "document_selection_rule", "document_match_status", "selected_mbs_file_id", "selected_mbs_title",
        "selected_mbs_url", "selected_mbs_pdf_sha256", "selected_mbs_pdf_bytes", "selected_mbs_pdf_page_count",
        "mbs_area_ha", "ibm_to_mbs_area_difference_pct", "geometry_admission_status",
        "geometry_admission_reason", "source_portal_url", "source_access_date", "model_evidence_role",
        "model_exclusion_reason",
    ]
    geometry_fields = [
        "record_id", "record_type", "state_or_ut", "block_name", "block_name_mbs", "mineral_source_ibm",
        "normalized_material_ids_json", "normalized_material_names_json", "chemical_or_english_names_json",
        "formulae_or_symbols_json", "auction_date_ibm", "concession_type_code_ibm", "ibm_area_ha", "mbs_area_ha",
        "exploration_level", "borehole_count", "drilled_meterage_m", "exploration_agency_source",
        "borehole_summary_source", "mineral_source_mbs", "geological_resources_source", "grade_source",
        "mineral_zones_source", "dip_strike_source", "thickness_source", "accessibility_source",
        "hydrography_source", "climate_source", "topography_source", "coordinate_method",
        "coordinate_source_pdf_pages_json", "boundary_point_ids_json", "boundary_vertex_count", "polygon_wkt",
        "geometry_crs", "coordinate_datum_source", "centroid_latitude", "centroid_longitude",
        "computed_geodesic_area_ha", "computed_to_mbs_area_difference_pct", "ibm_to_mbs_area_difference_pct",
        "polygon_valid", "centroid_in_source_state", "footprint_in_source_state_2011_boundary",
        "geometry_quality_flags_json", "geometry_admission_status", "geometry_admission_reason",
        "selected_mbs_file_id", "selected_mbs_url", "source_access_date", "selected_mbs_pdf_sha256",
        "selected_mbs_pdf_bytes", "selected_mbs_pdf_page_count", "current_legal_or_operational_status_verified",
        "model_evidence_role", "model_exclusion_reason",
    ]
    write_csv(MATCH_OUTPUT, match_rows, match_fields)
    write_csv(GEOMETRY_OUTPUT, geometry_rows, geometry_fields)
    GEOJSON_OUTPUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n")

    status_counts: dict[str, int] = {}
    for row in match_rows:
        status_counts[row["geometry_admission_status"]] = status_counts.get(row["geometry_admission_status"], 0) + 1
    validation = {
        "release": "v1.0-alpha.9",
        "source_portal_url": PORTAL_INDEX,
        "source_access_date": inventory["access_date"],
        "ibm_input_rows": len(rows),
        "state_portal_document_counts": {
            state: value["document_count"] for state, value in inventory["states"].items()
        },
        "state_portal_documents_total": sum(value["document_count"] for value in inventory["states"].values()),
        "curated_records": len(CURATED_MATCHES),
        "selected_document_matches": sum(bool(row["selected_mbs_file_id"]) for row in match_rows),
        "published_geometries": len(geometry_rows),
        "geometry_admission_status_counts": status_counts,
        "all_geometry_polygons_valid": all(row["polygon_valid"] for row in geometry_rows),
        "all_geometry_centroids_in_source_state": all(row["centroid_in_source_state"] for row in geometry_rows),
        "all_geometry_computed_area_differences_lte_5pct": all(
            float(row["computed_to_mbs_area_difference_pct"]) <= 5 for row in geometry_rows
        ),
        "all_available_ibm_mbs_area_differences_lte_5pct": all(
            row["ibm_to_mbs_area_difference_pct"] == "" or float(row["ibm_to_mbs_area_difference_pct"]) <= 5
            for row in geometry_rows
        ),
        "model_evidence_role": "context_only",
        "outputs": {},
        "limitations": [
            "This release reviews eleven of the 97 IBM Table 5 records; unreviewed rows are explicit in the match audit.",
            "Kareli-Chandi geometry is withheld because the MBS prints malformed latitude seconds for two vertices.",
            "Saloni geometry is withheld because IBM and MBS publish materially different areas.",
            "Goa Block VI geometry is withheld because the source coordinates compute to an area 25.31% below the MBS published area.",
            "The 2011 district boundary layer is used only as a state-containment diagnostic and is not a current administrative register.",
            "MBS technical context and IBM auction reporting do not independently establish current operation or present legal status.",
        ],
    }
    validation["checks_pass"] = bool(
        validation["ibm_input_rows"] == 97
        and validation["curated_records"] == 11
        and validation["selected_document_matches"] == 11
        and validation["published_geometries"] == 8
        and validation["geometry_admission_status_counts"] == {
            "withheld_not_reviewed": 86,
            "admitted_authoritative_source_footprint": 8,
            "withheld_source_conflict": 2,
            "withheld_validation_failure": 1,
        }
        and validation["all_geometry_polygons_valid"]
        and validation["all_geometry_centroids_in_source_state"]
        and validation["all_geometry_computed_area_differences_lte_5pct"]
        and validation["all_available_ibm_mbs_area_differences_lte_5pct"]
    )
    for path in (MATCH_OUTPUT, GEOMETRY_OUTPUT, GEOJSON_OUTPUT):
        validation["outputs"][path.name] = {"sha256": output_sha256(path), "bytes": path.stat().st_size}
    VALIDATION_OUTPUT.write_text(json.dumps(validation, indent=2) + "\n")
    upsert_source_registry(inventory["access_date"])
    upsert_data_dictionary(match_fields, geometry_fields)
    update_release_validation(validation)
    print(f"wrote {MATCH_OUTPUT.relative_to(ROOT)} ({len(match_rows)} rows)", file=sys.stderr)
    print(f"wrote {GEOMETRY_OUTPUT.relative_to(ROOT)} ({len(geometry_rows)} rows)", file=sys.stderr)
    print(f"wrote {GEOJSON_OUTPUT.relative_to(ROOT)} ({len(features)} features)", file=sys.stderr)
    print(f"wrote {VALIDATION_OUTPUT.relative_to(ROOT)}", file=sys.stderr)
    if not validation["checks_pass"]:
        raise SystemExit("IBM auction MBS geometry validation failed")


def write_inventory_probe(inventory: dict, rows: list[dict[str, str]], refresh: bool) -> None:
    audits = []
    for row in rows:
        candidates = candidate_documents(row, inventory)
        selected = select_latest(candidates)
        item = {
            "record_id": row["record_id"],
            "state": row["state_or_ut"],
            "block_name": row["block_name"],
            "candidate_count": len(candidates),
            "candidates": [{k: doc[k] for k in ("title", "url", "file_id")} for doc in candidates],
            "selected": None,
        }
        if selected:
            path, content = download_document(selected, refresh)
            pages = extract_pdf_pages(path)
            item["selected"] = {
                **{k: selected[k] for k in ("title", "url", "file_id")},
                "local_path": str(path.relative_to(ROOT)),
                "sha256": sha256_bytes(content),
                "bytes": len(content),
                "page_count": len(pages),
                "coordinate_candidates": extract_coordinate_candidates(pages),
            }
            text_path = path.with_suffix(".txt")
            text_path.write_text("\n\n".join(f"===== PAGE {i} =====\n{text}" for i, text in enumerate(pages, 1)))
        audits.append(item)
    EXTRACTION_AUDIT_JSON.write_text(json.dumps(audits, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {EXTRACTION_AUDIT_JSON.relative_to(ROOT)}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh portal inventory and cached PDFs")
    parser.add_argument("--inventory-only", action="store_true", help="stop after the raw document and coordinate probe")
    args = parser.parse_args()
    inventory = collect_inventory(args.refresh)
    rows = load_ibm_rows()
    write_inventory_probe(inventory, rows, args.refresh)
    if args.inventory_only:
        return
    publish_outputs(inventory, rows, args.refresh)


if __name__ == "__main__":
    main()
