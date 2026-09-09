#!/usr/bin/env python3
"""Cache and parse official MSTC mineral block summary PDFs.

The output is a source manifest plus a machine-readable JSON inventory consumed
by build_official_blocks.py. Parsed fields retain extraction method and notes;
unreadable values remain blank rather than being inferred from nearby blocks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
import geopandas as gpd
from pypdf import PdfReader
from pyproj import Geod, Transformer
from shapely import wkt
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw" / "official_critical_mineral_mbs"
OUT = ROOT / "outputs"
INDEX_URL = (
    "https://www.mstcecommerce.com/auctionhome/container.jsp?arcDate=30-11-2021"
    "&homepage=index&linkid=0&main_link=y&main_link_name=429&portal=mlcl"
    "&sublink=n&title_id=Mine+Block+Summary"
)
BASE_URL = "https://www.mstcecommerce.com/auctionhome/"
INVENTORY_JSON = RAW / "official_mbs_inventory.json"
MANIFEST_CSV = OUT / "india_official_critical_mineral_mbs_manifest.csv"
BUNDLED_PYTHON = Path(
    "/Users/ankitjh4/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python"
)
EXPECTED_OFFERS = {1: 20, 2: 18, 3: 7, 4: 21, 5: 15, 6: 23, 7: 19, 8: 20}
EXPECTED_CONCESSIONS = {
    1: {"ML": 4, "CL": 16}, 2: {"ML": 1, "CL": 17}, 3: {"ML": 0, "CL": 7},
    4: {"ML": 1, "CL": 20}, 5: {"ML": 2, "CL": 13}, 6: {"ML": 4, "CL": 19},
    7: {"ML": 2, "CL": 17}, 8: {"ML": 3, "CL": 17},
}
SUPERSEDED_FILE_IDS = {"27323", "25650"}
NIT_URLS = {
    1: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=12721_Tranche-1-NIT%2020%20Blocks.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    2: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=14475_GoI-MoM%20Tranche%20II-NIT.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    3: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=14477_Notice%20Inviting%20Tender%20(NIT)%20-%20%20Tranche%20III.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    4: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=15825_1.%20GoI%20MoM%20-%20Tranche%20IV%20-%20NIT.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    5: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=18641_GoI%20MoM%20-%20Tranche%20V%20-%20Notice%20Inviting%20Tender.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    6: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=22681_GoI%20MoM%20-%20Tranche%20VI%20-%20NIT.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    7: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=25649_GoI%20MoM%20-%20Tranche%20VII%20-%20NIT_N.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
    8: "https://www.mstcecommerce.com/auctionhome/download_docs.jsp?FILE_ID=27316_GoI%20MoM%20-%20Tranche%20VIII%20-%20NIT.pdf&path=dynamiclinks&portal=mlcl&mdTyp=-",
}
TRANCHE_DATES = {
    1: "2023-11-29",
    2: "2024-02-29",
    3: "2024-03-14",
    4: "2024-06-24",
    5: "2025-01-20",
    6: "2025-09-16",
    7: "2026-03-23",
    8: "2026-07-15",
}

DISTRICT_BOUNDARIES = ROOT / "sources" / "raw" / "2011_Dist.shp"
BOUNDARY_STATE_ALIASES = {
    "Arunachal Pradesh": "Arunanchal Pradesh",
    "Telangana": "Andhra Pradesh",  # Telangana was not a separate state in the 2011 layer.
    "UT: Jammu and Kashmir": "Jammu & Kashmir",
}

# Source-published boundary tables that require a narrowly scoped, reviewed OCR
# transcription. Values are stored as (longitude, latitude) decimal degrees.
COORDINATE_OVERRIDES = {
    "14089": {
        "block_name_contains": "Lakhasar",
        "method": "source_table_verified_ocr_override",
        "note": "Six boundary points transcribed from the official MBS map after 400 dpi OCR review.",
        "coordinates": [
            (73.85358180555555, 28.113147833333336),
            (73.874111, 28.12073102777778),
            (73.89284913888889, 28.112023555555556),
            (73.90540116666668, 28.09667472222222),
            (73.86453780555556, 28.06978986111111),
            (73.85164125, 28.085519527777777),
        ],
    },
}


MATERIAL_PATTERNS = [
    (r"\baluminous laterite\b", "Aluminous Laterite"),
    (r"\bassociated minerals?\b", "Associated minerals"),
    (r"\bbase\s*metals?\b", "Base metals"),
    (r"\brare earth(?: elements?| minerals?)?\b|\bREE\b", "Rare-earth elements"),
    (r"\brare metals?\b|\bRM\b", "Rare metals"),
    (r"\bplatinum group(?: elements?| minerals?)?\b|\bPGE\b|\bPGM\b", "Platinum-group elements"),
    (r"\brock phosphate\b", "Rock phosphate"),
    (r"\biron ore\b", "Iron"),
    (r"\bbauxite\b", "Bauxite"),
    (r"\bcesium\b|\bcaesium\b", "Cesium"),
    (r"\bchrom(?:ium|ite)\b|\bCr\b", "Chromium"),
    (r"\bcobalt\b|\bCo\b", "Cobalt"),
    (r"\bcopper\b|\bCu\b", "Copper"),
    (r"\bgallium\b", "Gallium"),
    (r"\bglauconite\b", "Glauconite"),
    (r"\bgraphite\b|\bgraphitic\b", "Graphite"),
    (r"\bhalite\b", "Halite"),
    (r"\bilmenite\b", "Ilmenite"),
    (r"\biron\b|\bFe\b", "Iron"),
    (r"\blead\b|\bPb\b", "Lead"),
    (r"\blithium\b|\bLi\b", "Lithium"),
    (r"\bmagnetite\b", "Magnetite"),
    (r"\bmanganese\b|\bMn\b", "Manganese"),
    (r"\bmolybdenum\b|\bMo\b", "Molybdenum"),
    (r"\bnickel\b|\bNi\b", "Nickel"),
    (r"\bphosphorite\b", "Phosphorite"),
    (r"\bphosphate\b", "Phosphate"),
    (r"\bpotash\b", "Potash"),
    (r"\brubidium\b", "Rubidium"),
    (r"\bsilver\b|\bAg\b", "Silver"),
    (r"\btin(?: ore)?\b|\bSn\b", "Tin"),
    (r"\btitanium\b|\bTi\b", "Titanium"),
    (r"\btungsten\b|\bWO3\b", "Tungsten"),
    (r"\bvanadium\b|\bV\b", "Vanadium"),
    (r"\byttrium\b", "Yttrium"),
    (r"\bzinc\b|\bZn\b", "Zinc"),
    (r"\bzirconium\b", "Zirconium"),
]


@dataclass
class Link:
    tranche: int
    title: str
    href: str
    file_id: str


class IndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture_strong = False
        self.strong_text: list[str] = []
        self.current_tranche: int | None = None
        self.capture_link = False
        self.link_href = ""
        self.link_text: list[str] = []
        self.links: list[Link] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "strong":
            self.capture_strong = True
            self.strong_text = []
        elif tag.lower() == "a" and "download_docs.jsp" in attrs.get("href", ""):
            self.capture_link = True
            self.link_href = attrs["href"]
            self.link_text = []

    def handle_data(self, data):
        if self.capture_strong:
            self.strong_text.append(data)
        if self.capture_link:
            self.link_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "strong" and self.capture_strong:
            value = normalize_text(" ".join(self.strong_text))
            match = re.search(r"(?:TRANCHE|PHASE)[^A-Z0-9]*(VIII|VII|VI|IV|V|III|II|I)\b", value, re.I)
            if match:
                roman = match.group(1).upper()
                self.current_tranche = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}[roman]
            self.capture_strong = False
        elif tag.lower() == "a" and self.capture_link:
            if self.current_tranche is None:
                raise ValueError("MBS link encountered before tranche heading")
            title = normalize_text(" ".join(self.link_text))
            query = parse_qs(urlparse(self.link_href).query)
            source_name = unquote(query.get("FILE_ID", [""])[0])
            file_id_match = re.match(r"(\d+)_", source_name)
            if not file_id_match:
                raise ValueError(f"No file id in {self.link_href}")
            self.links.append(Link(self.current_tranche, title, self.link_href, file_id_match.group(1)))
            self.capture_link = False


def normalize_text(value: str) -> str:
    value = html.unescape(value).replace("\x1a", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def safe_filename(value: str, limit: int = 110) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:limit] or "document"


def fetch(url: str, target: Path, refresh: bool) -> bytes:
    if target.exists() and not refresh:
        return target.read_bytes()
    response = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0 Codex research dataset"})
    response.raise_for_status()
    content = response.content
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return content


def exact_url(href: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, href))
    return parsed._replace(path=quote(unquote(parsed.path)), query=quote(unquote(parsed.query), safe="=&,._-()/'")).geturl()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_text(path: Path) -> tuple[str, list[str], int]:
    reader = PdfReader(path)
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages)
    return text, pages, len(reader.pages)


def clean_field(value: str | None) -> str | None:
    if not value:
        return None
    value = normalize_text(value)
    value = re.sub(r"^(?:of\s+)?(?:the\s+)?", "", value, flags=re.I)
    value = value.strip(" :-")
    return value or None


def first_match(patterns: list[str], text: str, flags=re.I | re.S) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return clean_field(match.group(1))
    return None


def parse_block_name(text: str, link_title: str) -> str:
    first_pages = "\n".join(text.splitlines()[:80])
    name = first_match([
        r"^\s*Mineral\s+Block\s+(.+?)(?=\n\s*(?:i\s+)?Location\b|\n\s*Latitudes?\b|\n\s*Longitude\b)",
        r"Name\s+of\s+(?:the\s+)?(?:Mineral\s+)?Block\s*[:\-]?\s*(.+?)(?=\n)",
    ], first_pages, flags=re.I | re.S | re.M)
    if name and len(name) < 180:
        return re.sub(r"\s+", " ", name)
    title = re.sub(r"^\d+\.?\s*", "", link_title)
    title = re.sub(r"^(?:Revised\s+)?(?:MBS|Mineral summary)\s*[_-]?\s*", "", title, flags=re.I)
    title = re.sub(r"(?:\s+Block)?\s+Summary(?:\s+\d{1,2}\.\d{1,2}\.\d{4})?$", " Block", title, flags=re.I)
    title = re.sub(r"_?(?:MBS|Final_CL|CL)$", "", title, flags=re.I)
    return normalize_text(title.replace("_", " "))


def parse_state(text: str) -> str | None:
    head = text[:4500]
    return first_match([r"\n\s*State\s*[:\-]?\s*([^\n]+)"], head, flags=re.I)


def parse_district(text: str) -> str | None:
    head = text[:4500]
    return first_match([r"\n\s*District\s*[:\-]?\s*([^\n]+)"], head, flags=re.I)


def parse_area(text: str) -> float | None:
    matches = []
    for pattern in [
        r"Total\s+Concession\s+Area\s*[:\-]?\s*([\d,]+(?:\.\d+)?)\s*(?:Ha|Hectares?)",
        r"Total\s+Area\s+of\s+Block(?:\s+for\s+Auction)?\s*[:\-]?\s*([\d,]+(?:\.\d+)?)\s*(?:Ha|Hectares?)",
        r"Area\s+of\s+(?:the\s+)?Block\s*[:\-]?\s*([\d,]+(?:\.\d+)?)\s*(?:Ha|Hectares?)",
    ]:
        matches.extend(re.findall(pattern, text, flags=re.I))
    if not matches:
        return None
    return float(matches[-1].replace(",", ""))


def parse_concession(text: str, title: str) -> str | None:
    sample = (text[:5000] + "\n" + title).lower()
    if re.search(r"\b(?:recommended for|auction of|grant of)\s+(?:a\s+)?(?:composite licen[cs]e|cl)\b", sample):
        return "CL"
    if re.search(r"\b(?:recommended for|auction of|grant of)\s+(?:a\s+)?(?:mining lease|ml)\b", sample):
        return "ML"
    if re.search(r"\bfinal[_ -]?cl\b|\bblock[_ -]?cl\b", title, re.I):
        return "CL"
    if re.search(r"\bcomposite licen[cs]e\b", sample):
        return "CL"
    if re.search(r"\bmining lease\b", sample):
        return "ML"
    return None


def material_sample(text: str, block_name: str) -> str:
    section = first_match([
        r"4\s+Quantity\s+of\s+Minerals.*?\n\s*Minerals?\s+(.+?)(?=\n\s*5\s+Minerali[sz]ed)",
        r"\n\s*Minerals?\s*[:\-]?\s*(.+?)(?=\n)",
    ], text[:9000])
    return f"{block_name}\n{section or ''}"


def parse_materials(text: str, block_name: str) -> list[str]:
    sample = material_sample(text, block_name)
    found = []
    for pattern, label in MATERIAL_PATTERNS:
        if re.search(pattern, sample, re.I) and label not in found:
            found.append(label)
    if "Iron" in found and "Magnetite" in found and not re.search(r"\biron(?: ore)?\b", block_name, re.I):
        found.remove("Iron")
    if "Phosphate" in found and "Rock phosphate" in found:
        found.remove("Phosphate")
    return found


def dms_to_decimal(degrees: float, minutes: float, seconds: float, direction: str | None) -> float:
    value = degrees + minutes / 60 + seconds / 3600
    if direction and direction.upper() in {"S", "W"}:
        value = -value
    return value


DMS_RE = re.compile(
    r"(?P<deg>\d{1,3})\s*(?:°|º|˚|0)\s*[:.]?\s*"
    r"(?P<min>\d{1,2})\s*(?:['’′ˈ`!])\s*(?P<sec>\d{1,2}(?:[.,]\d+)?)\s*"
    r"(?:[\"”″ˈ]|'')?",
    re.I,
)


def line_coordinates(line: str, header_order: str) -> list[tuple[float, float]]:
    line = line.replace("\u2018", "'").replace("\u2019", "'").replace("\u2032", "'")
    explicit = re.search(r"(\d{1,2}\.\d+)\s*N\s+(\d{2}\.\d+)\s*E", line, re.I)
    if explicit:
        return [(float(explicit.group(2)), float(explicit.group(1)))]
    explicit = re.search(r"(\d{2}\.\d+)\s*E\s+(\d{1,2}\.\d+)\s*N", line, re.I)
    if explicit:
        return [(float(explicit.group(1)), float(explicit.group(2)))]
    decimals = [float(x) for x in re.findall(r"(?<![\d.])(?:[6-9]\d|[1-3]\d)\.\d{2,}(?!\d)", line)]
    if len(decimals) >= 2 and not DMS_RE.search(line):
        decimal_points = []
        for index in range(0, len(decimals) - 1, 2):
            first, second = decimals[index:index + 2]
            longitude, latitude = (first, second) if header_order == "lon_lat" else (second, first)
            if 68 <= longitude <= 98 and 6 <= latitude <= 38:
                decimal_points.append((longitude, latitude))
        if decimal_points:
            return decimal_points

    components = []
    for match in DMS_RE.finditer(line):
        prefix = line[max(0, match.start() - 2):match.start()]
        suffix = line[match.end():match.end() + 3]
        immediate_prefix = re.search(r"([NSEW])$", prefix, re.I)
        suffix_direction = re.match(r"\s*([NSEW])", suffix, re.I)
        direction = immediate_prefix.group(1) if immediate_prefix else (suffix_direction.group(1) if suffix_direction else None)
        value = dms_to_decimal(float(match.group("deg")), float(match.group("min")), float(match.group("sec").replace(",", ".")), direction)
        components.append((value, direction.upper() if direction else None))
    if len(components) < 2:
        return []
    dms_points = []
    for index in range(0, len(components) - 1, 2):
        pair = components[index:index + 2]
        longitude = next((value for value, direction in pair if direction in {"E", "W"}), None)
        latitude = next((value for value, direction in pair if direction in {"N", "S"}), None)
        if longitude is None or latitude is None:
            values = [value for value, _ in pair]
            longitude, latitude = values if header_order == "lon_lat" else values[::-1]
        if 68 <= longitude <= 98 and 6 <= latitude <= 38:
            dms_points.append((longitude, latitude))
    return dms_points


def line_coordinate(line: str, header_order: str) -> tuple[float, float] | None:
    points = line_coordinates(line, header_order)
    return points[0] if points else None


def annexure_text(text: str) -> str:
    positions = [match.start() for match in re.finditer(r"Annexure\s*[-–]?\s*(?:I|1)\b", text, re.I)]
    return text[positions[-1]:] if positions else ""


def parse_coordinates(text: str) -> list[tuple[float, float]]:
    annex = annexure_text(text)
    if not annex:
        return []
    header_zone = annex[:1600].lower()
    lon_pos = header_zone.find("longitude")
    lat_pos = header_zone.find("latitude")
    header_order = "lon_lat" if 0 <= lon_pos < lat_pos else "lat_lon"
    points = []
    for line in annex.splitlines():
        for point in line_coordinates(line, header_order):
            if point not in points:
                points.append(point)
    if len(points) > 2 and points[0] == points[-1]:
        points.pop()
    return points


def parse_utm_coordinates(text: str) -> list[tuple[float, float]]:
    annex = annexure_text(text)
    zone_match = re.search(r"UTM\s*(?:ZONE)?\s*[-:]?\s*(\d{1,2})", annex, re.I)
    if not zone_match:
        return []
    zone = int(zone_match.group(1))
    transformer = Transformer.from_crs(f"EPSG:326{zone:02d}", "EPSG:4326", always_xy=True)
    points = []
    for line in annex.splitlines():
        values = [float(value.replace(",", "")) for value in re.findall(r"\d{5,7}(?:\.\d+)?", line)]
        eastings = [value for value in values if 100000 <= value <= 900000]
        northings = [value for value in values if 1000000 <= value <= 4500000]
        if eastings and northings:
            point = transformer.transform(eastings[0], northings[0])
            if 68 <= point[0] <= 98 and 6 <= point[1] <= 38 and point not in points:
                points.append(point)
    return points


def geometry_metrics(points: list[tuple[float, float]], source_area_ha: float | None):
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    reordered = False
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        hull = MultiPoint(points).convex_hull
        hull_vertices = len(hull.exterior.coords) - 1 if isinstance(hull, Polygon) else 0
        if isinstance(hull, Polygon) and hull_vertices == len(set(points)):
            polygon = hull
            reordered = True
        else:
            return None
    geod = Geod(ellps="WGS84")
    area_m2, _ = geod.geometry_area_perimeter(polygon)
    area_ha = abs(area_m2) / 10000
    difference = abs(area_ha - source_area_ha) / source_area_ha * 100 if source_area_ha else None
    centroid = polygon.centroid
    return {
        "coordinates": [[round(x, 9), round(y, 9)] for x, y in points],
        "latitude": centroid.y,
        "longitude": centroid.x,
        "geometry_wkt": polygon.wkt,
        "geometry_type": polygon.geom_type,
        "geometry_vertex_count": len(points),
        "geometry_area_geodesic_ha": area_ha,
        "geometry_area_difference_pct": difference,
        "geometry_reordered_to_valid_ring": reordered,
    }


def multi_geometry_metrics(polygons: list[Polygon], source_area_ha: float | None):
    if not polygons or any(not polygon.is_valid or polygon.is_empty for polygon in polygons):
        return None
    geometry = MultiPolygon(polygons)
    geod = Geod(ellps="WGS84")
    area_m2, _ = geod.geometry_area_perimeter(geometry)
    area_ha = abs(area_m2) / 10000
    difference = abs(area_ha - source_area_ha) / source_area_ha * 100 if source_area_ha else None
    centroid = geometry.centroid
    return {
        "coordinates": [],
        "latitude": centroid.y,
        "longitude": centroid.x,
        "geometry_wkt": geometry.wkt,
        "geometry_type": geometry.geom_type,
        "geometry_vertex_count": sum(len(p.exterior.coords) - 1 for p in polygons),
        "geometry_area_geodesic_ha": area_ha,
        "geometry_area_difference_pct": difference,
        "geometry_reordered_to_valid_ring": False,
    }


def parse_khobna_agargaon_cluster(ocr_text: str, source_area_ha: float | None):
    if "Khobna Tungsten Block" not in ocr_text or "Agargaon Tungsten Block" not in ocr_text:
        return None
    khobna_text = ocr_text.split("Khobna Tungsten Block", 1)[1].split("Agargaon Tungsten Block", 1)[0]
    khobna_left = []
    khobna_right = []
    for line in khobna_text.splitlines():
        line_points = line_coordinates(line, "lat_lon")
        if line_points and line_points[0] not in khobna_left:
            khobna_left.append(line_points[0])
        if len(line_points) > 1 and line_points[1] not in khobna_right:
            khobna_right.append(line_points[1])
    khobna_points = khobna_left + khobna_right

    agargaon_text = ocr_text.split("Agargaon Tungsten Block", 1)[1].split("Page 4", 1)[0]
    agargaon_left = []
    agargaon_right = []
    hyphen_dms = re.compile(r"(\d{1,3})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2}(?:\.\d+)?)")
    for line in agargaon_text.splitlines():
        values = [dms_to_decimal(float(d), float(m), float(s), None) for d, m, s in hyphen_dms.findall(line)]
        line_points = []
        for index in range(0, len(values) - 1, 2):
            latitude, longitude = values[index:index + 2]
            point = (longitude, latitude)
            if 68 <= longitude <= 98 and 6 <= latitude <= 38:
                line_points.append(point)
        if line_points and line_points[0] not in agargaon_left:
            agargaon_left.append(line_points[0])
        if len(line_points) > 1 and line_points[1] not in agargaon_right:
            agargaon_right.append(line_points[1])
    agargaon_points = agargaon_left + agargaon_right

    polygons = []
    for points, expected_area in [(khobna_points, 106.79), (agargaon_points, 44.0)]:
        metrics = geometry_metrics(points, expected_area)
        if not metrics or metrics["geometry_area_difference_pct"] > 5:
            return None
        polygons.append(wkt.loads(metrics["geometry_wkt"]))
    return multi_geometry_metrics(polygons, source_area_ha)


def parse_nit_fallback(block_name: str, nit_text: str, source_area_ha: float | None):
    normalized_target = re.sub(r"[^a-z0-9]+", " ", block_name.lower()).strip()
    words = normalized_target.split()
    anchors = [" ".join(words[:min(len(words), width)]) for width in (6, 5, 4, 3)]
    candidates = []
    for anchor in anchors:
        if not anchor:
            continue
        pattern = re.compile(re.escape(anchor).replace(r"\ ", r"\s+"), re.I)
        for match in pattern.finditer(nit_text):
            segment = nit_text[match.start():match.start() + 2200]
            points = parse_coordinates("Annexure-I\n" + segment)
            metrics = geometry_metrics(points, source_area_ha)
            if metrics:
                candidates.append(metrics)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["geometry_area_difference_pct"] if item["geometry_area_difference_pct"] is not None else 1e9)
    return candidates[0]


def load_state_geometries() -> dict[str, object]:
    districts = gpd.read_file(DISTRICT_BOUNDARIES).to_crs("EPSG:4326")
    return {
        state: group.geometry.union_all()
        for state, group in districts.groupby("ST_NM", dropna=True)
    }


def spatial_quality(record: dict, state_geometries: dict[str, object]) -> dict:
    if not record.get("geometry_wkt"):
        return {
            "geometry_quality_flag": "unavailable",
            "centroid_within_stated_state_2011": None,
            "spatial_validation_note": "No parsed geometry available for spatial validation.",
        }
    stated_state = record.get("state_or_ut")
    boundary_state = BOUNDARY_STATE_ALIASES.get(stated_state, stated_state)
    state_geometry = state_geometries.get(boundary_state)
    if state_geometry is None:
        return {
            "geometry_quality_flag": "boundary_lookup_unavailable",
            "centroid_within_stated_state_2011": None,
            "spatial_validation_note": f"No 2011 boundary match for stated state/UT: {stated_state}.",
        }
    centroid = Point(record["longitude"], record["latitude"])
    within = bool(state_geometry.covers(centroid))
    if within:
        note = None
        if stated_state == "Telangana":
            note = "Validated against the undivided Andhra Pradesh boundary in the 2011 Census layer."
        return {
            "geometry_quality_flag": "accepted",
            "centroid_within_stated_state_2011": True,
            "spatial_validation_note": note,
        }
    return {
        "geometry_quality_flag": "source_location_mismatch",
        "centroid_within_stated_state_2011": False,
        "spatial_validation_note": (
            f"Official-source centroid falls outside the stated {stated_state} boundary in the 2011 Census layer; "
            "source coordinates are retained and flagged."
        ),
    }


def ocr_coordinate_pages(
    pdf_path: Path,
    page_texts: list[str],
    cache_dir: Path,
    refresh: bool = False,
    resolution: int = 240,
    psm: int = 4,
) -> str:
    page_indexes = [i for i, value in enumerate(page_texts) if re.search(r"Annexure\s*[-–]?\s*(?:I|1)\b", value, re.I)]
    start = page_indexes[-1] if page_indexes else max(0, len(page_texts) - 2)
    selected = list(range(start, len(page_texts)))
    profile = "" if (resolution, psm) == (240, 4) else f".r{resolution}.p{psm}"
    render_dir = cache_dir / f"{pdf_path.stem}{profile}_rendered"
    ocr_path = cache_dir / f"{pdf_path.stem}{profile}.ocr.txt"
    if ocr_path.exists() and not refresh:
        return ocr_path.read_text(errors="replace")
    python = BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else Path(sys.executable)
    subprocess.run(
        [str(python), str(ROOT / "scripts" / "render_pdf_pages.py"), str(pdf_path), str(render_dir), *map(str, selected), "--resolution", str(resolution)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    chunks = []
    for image in sorted(render_dir.glob("page_*.png")):
        result = subprocess.run(
            ["tesseract", str(image), "stdout", "--psm", str(psm)],
            check=True,
            capture_output=True,
            text=True,
        )
        chunks.append(result.stdout)
    combined = "\n".join(chunks)
    ocr_path.write_text(combined)
    shutil.rmtree(render_dir, ignore_errors=True)
    return combined


def parse_one(link: Link, order: int, refresh: bool, nit_document: dict) -> dict:
    url = exact_url(link.href)
    filename = f"T{link.tranche}_{link.file_id}_{safe_filename(link.title)}.pdf"
    pdf_path = RAW / filename
    data = fetch(url, pdf_path, refresh)
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Non-PDF response for {url}")
    text, pages, page_count = extract_pdf_text(pdf_path)
    text_path = pdf_path.with_suffix(".txt")
    if refresh or not text_path.exists():
        text_path.write_text(text)

    block_name = parse_block_name(text, link.title)
    area = parse_area(text)
    points = parse_coordinates(text)
    coordinate_method = "pypdf_text"
    if len(points) < 3:
        points = parse_utm_coordinates(text)
        coordinate_method = "utm_transform_from_pypdf_text"
    geometry = geometry_metrics(points, area)
    method = coordinate_method if geometry else None
    geometry_source_url = url
    notes = []
    if not geometry:
        try:
            high_resolution = "Lakhasar" in block_name
            ocr_text = ocr_coordinate_pages(
                pdf_path,
                pages,
                RAW,
                refresh=refresh,
                resolution=400 if high_resolution else 240,
                psm=6 if high_resolution else 4,
            )
            if "Khobna and Agargaon Cluster" in block_name:
                geometry = parse_khobna_agargaon_cluster(ocr_text, area)
                ocr_points = []
                ocr_method = "tesseract_ocr_two_part_multipolygon"
            else:
                ocr_points = parse_coordinates("Annexure-I\n" + ocr_text)
                ocr_method = "tesseract_ocr"
                if len(ocr_points) < 3:
                    ocr_points = parse_utm_coordinates("Annexure-I\n" + ocr_text)
                    ocr_method = "utm_transform_from_tesseract_ocr"
                geometry = geometry_metrics(ocr_points, area)
            if geometry:
                method = ocr_method
            else:
                notes.append(f"No valid polygon parsed from text or OCR ({len(points)} text points; {len(ocr_points)} OCR points)")
        except Exception as exc:
            notes.append(f"OCR fallback failed: {type(exc).__name__}: {exc}")
    if geometry and geometry["geometry_area_difference_pct"] is not None and geometry["geometry_area_difference_pct"] > 10:
        notes.append(f"Rejected geometry: source-area difference is {geometry['geometry_area_difference_pct']:.2f}%")
        geometry = None
        method = None
    if not geometry:
        fallback = parse_nit_fallback(block_name, nit_document["text"], area)
        if fallback and (fallback["geometry_area_difference_pct"] is None or fallback["geometry_area_difference_pct"] <= 10):
            geometry = fallback
            method = "pypdf_text_from_official_nit_fallback"
            geometry_source_url = nit_document["url"]
            notes = [note for note in notes if not note.startswith(("No valid polygon", "Rejected geometry"))]
    override = COORDINATE_OVERRIDES.get(link.file_id)
    if not geometry and override and override["block_name_contains"].lower() in block_name.lower():
        candidate = geometry_metrics(override["coordinates"], area)
        if candidate and (candidate["geometry_area_difference_pct"] is None or candidate["geometry_area_difference_pct"] <= 5):
            geometry = candidate
            method = override["method"]
            notes = [note for note in notes if not note.startswith(("No valid polygon", "Rejected geometry"))]
            notes.append(override["note"])

    state = parse_state(text)
    district = parse_district(text)
    concession = parse_concession(text, link.title)
    concession_method = "mbs_text_reconciled_to_official_nit"
    if not concession:
        concession = "ML"
        concession_method = "official_nit_table"
        notes = [note for note in notes if note != "Concession type not parsed"]
    materials = parse_materials(text, block_name)
    if not state:
        notes.append("State not parsed")
    if not district:
        notes.append("District not parsed")
    if area is None:
        notes.append("Concession area not parsed")
    if not materials:
        notes.append("Materials not parsed")

    record = {
        "event_id": f"T{link.tranche}-O{order:02d}",
        "auction_tranche": link.tranche,
        "portal_link_order": order,
        "portal_link_title": link.title,
        "block_name": block_name,
        "state_or_ut": state,
        "district": district,
        "materials": materials,
        "concession_type": concession,
        "block_area_ha": area,
        "auction_nit_date": TRANCHE_DATES[link.tranche],
        "source_date": TRANCHE_DATES[link.tranche],
        "source_url": nit_document["url"],
        "auction_notice_source_url": nit_document["url"],
        "auction_notice_pdf_filename": nit_document["filename"],
        "auction_notice_pdf_sha256": nit_document["sha256"],
        "auction_notice_pdf_bytes": nit_document["bytes"],
        "auction_notice_pdf_page_count": nit_document["page_count"],
        "concession_type_extraction_method": concession_method,
        "mbs_source_url": url,
        "geometry_source_url": geometry_source_url,
        "source_pdf_filename": filename,
        "source_pdf_sha256": sha256(data),
        "source_pdf_bytes": len(data),
        "source_pdf_page_count": page_count,
        "geometry_extraction_method": method,
        "extraction_notes": "; ".join(notes) or None,
        **(geometry or {}),
    }
    return record


def parse_index(index_text: str) -> list[Link]:
    parser = IndexParser()
    parser.feed(index_text)
    return [link for link in parser.links if link.file_id not in SUPERSEDED_FILE_IDS]


def write_manifest(records: list[dict]):
    columns = [
        "event_id", "auction_tranche", "portal_link_order", "block_name", "state_or_ut", "district",
        "concession_type", "block_area_ha", "source_materials_json", "coordinates_available_in_source",
        "geometry_type", "geometry_vertex_count", "geometry_area_geodesic_ha", "geometry_area_difference_pct",
        "geometry_extraction_method", "geometry_quality_flag", "centroid_within_stated_state_2011", "spatial_validation_note",
        "concession_type_extraction_method", "source_pdf_filename", "source_pdf_sha256", "source_pdf_bytes",
        "source_pdf_page_count", "auction_notice_pdf_filename", "auction_notice_pdf_sha256", "auction_notice_pdf_bytes",
        "auction_notice_pdf_page_count", "portal_link_title", "source_url", "mbs_source_url", "geometry_source_url", "extraction_notes",
    ]
    with MANIFEST_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in columns}
            row["source_materials_json"] = json.dumps(record["materials"], ensure_ascii=False, separators=(",", ":"))
            row["coordinates_available_in_source"] = bool(record.get("geometry_wkt"))
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh the index and PDF cache")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = RAW / "mstc_mine_block_summary_index.html"
    index_data = fetch(INDEX_URL, index_path, args.refresh)
    index_text = index_data.decode("latin-1", errors="replace")
    links = parse_index(index_text)
    counts = {tranche: sum(link.tranche == tranche for link in links) for tranche in EXPECTED_OFFERS}
    if counts != EXPECTED_OFFERS:
        raise RuntimeError(f"Unexpected MBS link counts: {counts}")

    nit_documents = {}
    nit_dir = ROOT / "sources" / "raw" / "official_critical_mineral_nit"
    nit_dir.mkdir(parents=True, exist_ok=True)
    for tranche, url in NIT_URLS.items():
        path = nit_dir / f"T{tranche}_NIT.pdf"
        data = fetch(url, path, args.refresh)
        text_value, _, page_count = extract_pdf_text(path)
        path.with_suffix(".txt").write_text(text_value)
        nit_documents[tranche] = {
            "url": url,
            "filename": path.name,
            "sha256": sha256(data),
            "bytes": len(data),
            "page_count": page_count,
            "text": text_value,
        }

    records = []
    for tranche in sorted(EXPECTED_OFFERS):
        tranche_links = [link for link in links if link.tranche == tranche]
        for order, link in enumerate(tranche_links, 1):
            print(f"T{tranche} {order:02d}/{len(tranche_links):02d} {link.title}", flush=True)
            records.append(parse_one(link, order, args.refresh, nit_documents[tranche]))

    state_geometries = load_state_geometries()
    for record in records:
        record.update(spatial_quality(record, state_geometries))

    concession_counts = {
        tranche: {
            kind: sum(record["auction_tranche"] == tranche and record["concession_type"] == kind for record in records)
            for kind in ("ML", "CL")
        }
        for tranche in EXPECTED_OFFERS
    }
    if concession_counts != EXPECTED_CONCESSIONS:
        raise RuntimeError(f"Concession counts do not reconcile to official NIT tables: {concession_counts}")

    INVENTORY_JSON.write_text(json.dumps({
        "source_url": INDEX_URL,
        "source_index_sha256": sha256(index_data),
        "expected_offer_counts_by_tranche": EXPECTED_OFFERS,
        "expected_concession_counts_by_tranche": EXPECTED_CONCESSIONS,
        "superseded_file_ids_excluded": sorted(SUPERSEDED_FILE_IDS),
        "nit_documents": [{key: value for key, value in document.items() if key != "text"} for document in nit_documents.values()],
        "records": records,
    }, ensure_ascii=False, indent=2) + "\n")
    write_manifest(records)
    summary = {
        "records": len(records),
        "counts_by_tranche": counts,
        "concession_counts_by_tranche": concession_counts,
        "geometry_rows": sum(bool(record.get("geometry_wkt")) for record in records),
        "metadata_complete_rows": sum(all(record.get(key) not in (None, [], "") for key in ["state_or_ut", "district", "concession_type", "block_area_ha", "materials"]) for record in records),
        "rows_with_notes": sum(bool(record.get("extraction_notes")) for record in records),
        "geometry_quality_counts": {
            flag: sum(record.get("geometry_quality_flag") == flag for record in records)
            for flag in sorted({record.get("geometry_quality_flag") for record in records})
        },
        "maximum_area_difference_pct": max((record.get("geometry_area_difference_pct") or 0) for record in records),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
