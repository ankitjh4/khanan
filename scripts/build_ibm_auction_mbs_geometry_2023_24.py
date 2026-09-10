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
import pypdf.filters as pypdf_filters
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
    "Andhra Pradesh": "474",
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
    "IBM-IMYB2024-AUCTION-001": r"^adakula(?:\s+mine)?(?:\s+block)?(?:\s+summary)?$",
    "IBM-IMYB2024-AUCTION-002": r"^addankivaripalem(?:\s+iron\s+ore)?(?:\s+block)?(?:\s+summary)?$",
    "IBM-IMYB2024-AUCTION-003": r"^lakshmakapalle\s+north(?:\s+iron\s+ore)?(?:\s+block)?(?:\s+summary)?$",
    "IBM-IMYB2024-AUCTION-004": r"^lakshmakapalle\s+south(?:\s+iron\s+ore)?(?:\s+block)?(?:\s+summary)?$",
    "IBM-IMYB2024-AUCTION-005": r"^mincheri\s+rf(?:\s+iron\s+ore)?(?:\s+block)?(?:\s+summary)?$",
    "IBM-IMYB2024-AUCTION-006": r"north\s+of\s+arjunda",
    "IBM-IMYB2024-AUCTION-007": r"\bsaloni\b",
    "IBM-IMYB2024-AUCTION-008": r"\bdevri\b.*\blimestone\b|\blimestone\b.*\bdevri\b",
    "IBM-IMYB2024-AUCTION-009": r"kareli\s+chandi",
    "IBM-IMYB2024-AUCTION-010": r"giroud\s+uprani",
    "IBM-IMYB2024-AUCTION-011": r"tumrisur[\s-]+garda\s*(?:ii|2)",
    "IBM-IMYB2024-AUCTION-012": r"^mevasa block 1 summary$",
    "IBM-IMYB2024-AUCTION-013": r"^mevasa block summary$",
    "IBM-IMYB2024-AUCTION-014": r"^kukaras block summary$",
    "IBM-IMYB2024-AUCTION-015": r"^nandana block summary$",
    "IBM-IMYB2024-AUCTION-016": r"^kodidara block summary$",
    "IBM-IMYB2024-AUCTION-017": r"^virpur lusari block summary$",
    "IBM-IMYB2024-AUCTION-018": r"\bchiropat\b.*\bbauxite\b",
    "IBM-IMYB2024-AUCTION-019": r"\bbaraiburu\b.*\btatiba\b.*\biron\b.*\bmanganese\b",
    "IBM-IMYB2024-AUCTION-020": r"\bmeralgara\b.*\bbarabaljori\b.*\biron\b",
    "IBM-IMYB2024-AUCTION-021": r"\bblock\s*no\s*4\b.*\bhrg\b",
    "IBM-IMYB2024-AUCTION-022": r"\btimmanahalli\b",
    "IBM-IMYB2024-AUCTION-023": r"\bjaisinghpura\s+north\b",
    "IBM-IMYB2024-AUCTION-024": r"\bbasavana?gudda\b",
    "IBM-IMYB2024-AUCTION-025": r"\bniddodi\b",
    "IBM-IMYB2024-AUCTION-026": r"\bkudarka\b.*\bbauxite\b",
    "IBM-IMYB2024-AUCTION-027": r"^summary of katni limestone block$",
    "IBM-IMYB2024-AUCTION-028": r"^summary of pahari limestone block$",
    "IBM-IMYB2024-AUCTION-029": r"^summary of pipartola manganese ore block$",
    "IBM-IMYB2024-AUCTION-030": r"^summary of chorgadi puraina limestone block$",
    "IBM-IMYB2024-AUCTION-031": r"^summary of bhilapar manganese ore (?:and )?dolomite block$",
    "IBM-IMYB2024-AUCTION-032": r"^summary of dhamani nana manganese ore block$",
    "IBM-IMYB2024-AUCTION-033": r"^summary of guvali manganese ore block$",
    "IBM-IMYB2024-AUCTION-034": r"^summary of katangjhari manganese ore block$",
    "IBM-IMYB2024-AUCTION-035": r"^summary of lingaponar manganese ore block$",
    "IBM-IMYB2024-AUCTION-036": r"^summary of naganwat chhoti manganese ore block$",
    "IBM-IMYB2024-AUCTION-037": r"^summary of uberao manganese ore block$",
    "IBM-IMYB2024-AUCTION-038": r"^summary of bamanbardi limestone block$",
    "IBM-IMYB2024-AUCTION-039": r"^summary of doter guvali manganese ore block$",
    "IBM-IMYB2024-AUCTION-040": r"^summary of east of dabri limestone block$",
    "IBM-IMYB2024-AUCTION-041": r"^summary of garhi upcha limestone block$",
    "IBM-IMYB2024-AUCTION-042": r"^summary of nawapara rampura manganese ore block$",
    "IBM-IMYB2024-AUCTION-043": r"^summary of piploda phosphorite block$",
    "IBM-IMYB2024-AUCTION-044": r"^summary of shitalpani copper block$",
    "IBM-IMYB2024-AUCTION-045": r"^summary of siluwa and jhansi iron ore block$",
    "IBM-IMYB2024-AUCTION-046": r"^summary of modri phosphorite block$",
    "IBM-IMYB2024-AUCTION-047": r"^summary of pindrai iron ore block$",
    "IBM-IMYB2024-AUCTION-048": r"^summary of makra graphite vanadium block$",
    "IBM-IMYB2024-AUCTION-049": r"^summary of devalmari katepalli block$",
    "IBM-IMYB2024-AUCTION-050": r"^summary of surjagad 1 2 1 23$",
    "IBM-IMYB2024-AUCTION-051": r"^summary of surjagad 2 2 1 23$",
    "IBM-IMYB2024-AUCTION-052": r"^summary of surjagad 3 2 1 23$",
    "IBM-IMYB2024-AUCTION-053": r"^summary of surjagad 4 2 1 23$",
    "IBM-IMYB2024-AUCTION-054": r"^summary of south padve block$",
    "IBM-IMYB2024-AUCTION-055": r"^summary of surjagad 6 2 1 23$",
    "IBM-IMYB2024-AUCTION-056": r"^summary of kondhala block$",
    "IBM-IMYB2024-AUCTION-057": r"^summary of minzhari copper block$",
    "IBM-IMYB2024-AUCTION-058": r"^summary of savali manganese block$",
    "IBM-IMYB2024-AUCTION-090": r"\bphase\s*4\b.*\bgirar\b.*\biron\b.*\bgold\b",
    "IBM-IMYB2024-AUCTION-091": r"\bphase\s*4\b.*\bbharhari\b.*\biron\b",
    "IBM-IMYB2024-AUCTION-092": r"\bphase\s*4\b.*\bsona\s*pahari\b.*\bgold\b",
    "IBM-IMYB2024-AUCTION-093": r"(?:block\s*)?(?:v|5).*advalpale.*thivim|advalpale.*thivim",
    "IBM-IMYB2024-AUCTION-094": r"(?:block\s*)?(?:vi|6).*cudnem.*cormolem|cudnem.*cormolem",
    "IBM-IMYB2024-AUCTION-095": r"(?:block\s*)?(?:vii|7).*cudnem\b|\bcudnem\b.*(?:block\s*)?(?:vii|7)",
    "IBM-IMYB2024-AUCTION-096": r"(?:block\s*)?(?:viii|8).*thivim.*pirna|thivim.*pirna",
    "IBM-IMYB2024-AUCTION-097": r"(?:block\s*)?(?:ix|9).*surla.*sonshi|surla.*sonshi",
}

# Madhya Pradesh reuses several block names in later auction phases. These
# file IDs are the visually verified Phase-XI tranche that corresponds to IBM
# Table 5 (2023-24); selecting the numerically latest same-name upload would
# silently attach a later auction document to the historical IBM row.
CURATED_FILE_ID_OVERRIDES = {
    "IBM-IMYB2024-AUCTION-027": "10915",
    "IBM-IMYB2024-AUCTION-028": "10950",
    "IBM-IMYB2024-AUCTION-029": "10914",
    "IBM-IMYB2024-AUCTION-030": "10937",
    "IBM-IMYB2024-AUCTION-031": "10925",
    "IBM-IMYB2024-AUCTION-032": "10912",
    "IBM-IMYB2024-AUCTION-033": "10911",
    "IBM-IMYB2024-AUCTION-034": "10910",
    "IBM-IMYB2024-AUCTION-035": "10921",
    "IBM-IMYB2024-AUCTION-036": "10931",
    "IBM-IMYB2024-AUCTION-037": "10955",
    "IBM-IMYB2024-AUCTION-038": "10922",
    "IBM-IMYB2024-AUCTION-039": "10948",
    "IBM-IMYB2024-AUCTION-040": "10941",
    "IBM-IMYB2024-AUCTION-041": "10945",
    "IBM-IMYB2024-AUCTION-042": "10936",
    "IBM-IMYB2024-AUCTION-043": "10939",
    "IBM-IMYB2024-AUCTION-044": "10913",
    "IBM-IMYB2024-AUCTION-045": "10949",
    "IBM-IMYB2024-AUCTION-046": "10938",
    "IBM-IMYB2024-AUCTION-047": "10930",
    "IBM-IMYB2024-AUCTION-048": "10919",
}

# The current public Andhra Pradesh MBS index exposes newer 2025-26 tranches,
# not these five IBM 2023-24 rows.  Their exact-name searches are still part of
# the reviewed scope, but absence from the current index cannot be converted to
# a polygon.  A separate status-evidence layer records dated official sources.
REVIEWED_NO_CURRENT_MBS = {
    f"IBM-IMYB2024-AUCTION-{value:03d}": (
        "Exact block-name review found no matching document in the current public Andhra Pradesh "
        "MSTC Mine Block Summary index; geometry is withheld without inferring coordinates."
    )
    for value in range(1, 6)
}


def dms(degrees: float, minutes: float, seconds: float) -> float:
    return degrees + minutes / 60 + seconds / 3600


# (longitude, latitude), in the exact source-published point order. These
# tables were transcribed after visual review of the coordinate-bearing pages
# at 150 dpi. Kareli-
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
    "IBM-IMYB2024-AUCTION-012": [
        (dms(69, 17, 42.47), dms(22, 14, 26.00)),
        (dms(69, 17, 47.64), dms(22, 14, 26.44)),
        (dms(69, 17, 48.19), dms(22, 14, 24.13)),
        (dms(69, 17, 49.20), dms(22, 14, 22.08)),
        (dms(69, 17, 49.62), dms(22, 14, 20.58)),
        (dms(69, 17, 47.83), dms(22, 14, 17.20)),
        (dms(69, 17, 44.43), dms(22, 14, 14.51)),
        (dms(69, 17, 42.58), dms(22, 14, 14.12)),
        (dms(69, 17, 41.68), dms(22, 14, 15.43)),
        (dms(69, 17, 42.84), dms(22, 14, 20.04)),
        (dms(69, 17, 42.11), dms(22, 14, 21.64)),
    ],
    "IBM-IMYB2024-AUCTION-013": [
        (dms(69, 18, 5.62), dms(22, 15, 10.54)),
        (dms(69, 18, 7.93), dms(22, 15, 12.98)),
        (dms(69, 18, 14.75), dms(22, 15, 14.85)),
        (dms(69, 18, 18.21), dms(22, 15, 14.91)),
        (dms(69, 18, 18.66), dms(22, 15, 14.49)),
        (dms(69, 18, 18.54), dms(22, 15, 6.88)),
        (dms(69, 18, 16.72), dms(22, 15, 6.20)),
        (dms(69, 18, 16.62), dms(22, 15, 9.55)),
        (dms(69, 18, 13.69), dms(22, 15, 8.80)),
        (dms(69, 18, 13.04), dms(22, 15, 8.93)),
        (dms(69, 18, 12.50), dms(22, 15, 9.65)),
        (dms(69, 18, 10.56), dms(22, 15, 9.28)),
        (dms(69, 18, 10.35), dms(22, 15, 9.43)),
        (dms(69, 18, 9.43), dms(22, 15, 9.38)),
        (dms(69, 18, 7.40), dms(22, 15, 9.34)),
    ],
    "IBM-IMYB2024-AUCTION-014": [
        (dms(70, 31, 29.52), dms(20, 56, 48.76)),
        (dms(70, 31, 30.57), dms(20, 56, 43.28)),
        (dms(70, 31, 31.83), dms(20, 56, 38.75)),
        (dms(70, 31, 33.71), dms(20, 56, 39.91)),
        (dms(70, 31, 34.14), dms(20, 56, 40.17)),
        (dms(70, 31, 35.83), dms(20, 56, 40.30)),
        (dms(70, 31, 39.21), dms(20, 56, 41.54)),
        (dms(70, 31, 39.03), dms(20, 56, 42.95)),
        (dms(70, 31, 42.88), dms(20, 56, 44.90)),
        (dms(70, 31, 42.77), dms(20, 56, 45.36)),
        (dms(70, 31, 44.80), dms(20, 56, 45.95)),
        (dms(70, 31, 47.01), dms(20, 56, 45.18)),
        (dms(70, 31, 49.56), dms(20, 56, 44.95)),
        (dms(70, 31, 50.67), dms(20, 56, 44.75)),
        (dms(70, 31, 52.67), dms(20, 56, 44.73)),
        (dms(70, 31, 55.28), dms(20, 56, 44.73)),
        (dms(70, 31, 56.94), dms(20, 56, 50.47)),
        (dms(70, 31, 58.61), dms(20, 56, 57.67)),
        (dms(70, 31, 59.36), dms(20, 57, 0.86)),
        (dms(70, 31, 52.76), dms(20, 57, 0.80)),
        (dms(70, 31, 52.54), dms(20, 56, 56.34)),
        (dms(70, 31, 52.53), dms(20, 56, 54.00)),
        (dms(70, 31, 53.95), dms(20, 56, 49.32)),
        (dms(70, 31, 46.20), dms(20, 56, 48.62)),
        (dms(70, 31, 45.71), dms(20, 56, 53.24)),
        (dms(70, 31, 45.44), dms(20, 56, 54.18)),
        (dms(70, 31, 45.40), dms(20, 56, 55.63)),
        (dms(70, 31, 45.18), dms(20, 56, 55.85)),
        (dms(70, 31, 43.75), dms(20, 56, 57.22)),
        (dms(70, 31, 42.41), dms(20, 56, 59.25)),
        (dms(70, 31, 42.25), dms(20, 56, 59.50)),
        (dms(70, 31, 41.89), dms(20, 57, 1.55)),
        (dms(70, 31, 37.72), dms(20, 57, 1.60)),
        (dms(70, 31, 37.00), dms(20, 57, 2.45)),
        (dms(70, 31, 33.66), dms(20, 57, 2.14)),
        (dms(70, 31, 32.91), dms(20, 57, 1.93)),
        (dms(70, 31, 32.88), dms(20, 56, 58.06)),
        (dms(70, 31, 33.93), dms(20, 56, 58.05)),
        (dms(70, 31, 34.04), dms(20, 56, 57.17)),
        (dms(70, 31, 34.79), dms(20, 56, 55.19)),
        (dms(70, 31, 34.50), dms(20, 56, 55.10)),
        (dms(70, 31, 38.10), dms(20, 56, 51.16)),
        (dms(70, 31, 36.82), dms(20, 56, 49.81)),
        (dms(70, 31, 32.48), dms(20, 56, 49.03)),
        (dms(70, 31, 30.87), dms(20, 56, 48.91)),
        (dms(70, 31, 29.93), dms(20, 56, 48.84)),
    ],
    "IBM-IMYB2024-AUCTION-021": [
        (dms(76, 38, 26.12099), dms(15, 1, 37.10603)),
        (dms(76, 38, 17.91794), dms(15, 1, 29.56321)),
        (dms(76, 38, 0.83978), dms(15, 1, 50.49850)),
        (dms(76, 38, 0.02294), dms(15, 1, 56.14179)),
        (dms(76, 38, 12.80336), dms(15, 2, 0.36111)),
        (dms(76, 38, 16.15934), dms(15, 1, 56.41782)),
        (dms(76, 38, 18.90596), dms(15, 1, 57.22219)),
    ],
    "IBM-IMYB2024-AUCTION-023": [
        (dms(76, 27, 27.189), dms(15, 11, 30.366)),
        (dms(76, 27, 4.281), dms(15, 11, 45.192)),
        (dms(76, 27, 11.070), dms(15, 11, 52.529)),
        (dms(76, 27, 1.554), dms(15, 12, 4.357)),
        (dms(76, 26, 26.653), dms(15, 12, 26.678)),
        (dms(76, 26, 5.650), dms(15, 12, 43.610)),
        (dms(76, 26, 15.794), dms(15, 12, 47.982)),
        (dms(76, 26, 20.071), dms(15, 12, 54.781)),
        (dms(76, 26, 36.306), dms(15, 12, 45.294)),
        (dms(76, 27, 27.036), dms(15, 12, 26.660)),
        (dms(76, 27, 54.301), dms(15, 12, 9.837)),
    ],
    "IBM-IMYB2024-AUCTION-024": [
        (dms(76, 42, 7.12464), dms(13, 44, 23.94298)),
        (dms(76, 41, 16.95603), dms(13, 39, 35.90764)),
        (dms(76, 39, 57.28846), dms(13, 39, 40.06938)),
        (dms(76, 40, 29.92120), dms(13, 44, 41.99450)),
        (dms(76, 41, 49.13156), dms(13, 44, 23.98329)),
    ],
    "IBM-IMYB2024-AUCTION-025": [
        (dms(74, 55, 22.8285), dms(13, 2, 45.2987)),
        (dms(74, 55, 35.7582), dms(13, 3, 10.9646)),
        (dms(74, 55, 55.5981), dms(13, 2, 57.7868)),
        (dms(74, 55, 40.2600), dms(13, 2, 37.8240)),
    ],
    "IBM-IMYB2024-AUCTION-050": [
        (dms(80, 24, 51.37), dms(19, 40, 36.14)),
        (dms(80, 25, 47.21), dms(19, 41, 39.03)),
        (dms(80, 27, 58.87), dms(19, 39, 41.15)),
        (dms(80, 26, 30.56), dms(19, 38, 23.54)),
    ],
    "IBM-IMYB2024-AUCTION-051": [
        (dms(80, 25, 48.07), dms(19, 41, 40.52)),
        (dms(80, 26, 8.82), dms(19, 42, 7.18)),
        (dms(80, 27, 20.97), dms(19, 41, 15.9)),
        (dms(80, 27, 34.61), dms(19, 41, 34.03)),
        (dms(80, 28, 52.29), dms(19, 40, 29.07)),
        (dms(80, 27, 59.88), dms(19, 39, 42.11)),
    ],
    "IBM-IMYB2024-AUCTION-052": [
        (dms(80, 26, 9.54), dms(19, 42, 8.11)),
        (dms(80, 27, 4.3), dms(19, 43, 15.02)),
        (dms(80, 28, 8.71), dms(19, 42, 21.88)),
        (dms(80, 27, 20.74), dms(19, 41, 17.7)),
    ],
    "IBM-IMYB2024-AUCTION-053": [
        (dms(80, 27, 35.73), dms(19, 41, 35.51)),
        (dms(80, 28, 0.37), dms(19, 42, 8.26)),
        (dms(80, 29, 24.42), dms(19, 41, 2.79)),
        (dms(80, 28, 53.62), dms(19, 40, 30.47)),
    ],
    "IBM-IMYB2024-AUCTION-055": [
        (dms(80, 27, 4.98), dms(19, 43, 15.8)),
        (dms(80, 28, 4.1), dms(19, 44, 23.83)),
        (dms(80, 29, 4.16), dms(19, 43, 41.94)),
        (dms(80, 28, 9.49), dms(19, 42, 22.9)),
    ],
    "IBM-IMYB2024-AUCTION-056": [
        (dms(78, 58, 43.55), dms(20, 18, 46.87)),
        (dms(78, 59, 31.14), dms(20, 18, 46.09)),
        (dms(78, 59, 30.82), dms(20, 18, 7.38)),
        (dms(78, 58, 44.28), dms(20, 18, 8.06)),
    ],
    "IBM-IMYB2024-AUCTION-057": [
        (dms(79, 34, 30.73), dms(20, 21, 33.84)),
        (dms(79, 36, 7.55), dms(20, 21, 39.96)),
        (dms(79, 35, 40.55), dms(20, 18, 27.36)),
        (dms(79, 34, 9.47), dms(20, 18, 27.36)),
        (dms(79, 34, 2.63), dms(20, 20, 21.12)),
    ],
    "IBM-IMYB2024-AUCTION-058": [
        (dms(79, 2, 52.8), dms(21, 25, 26.04)),
        (dms(79, 4, 37.2), dms(21, 25, 26.04)),
        (dms(79, 4, 37.2), dms(21, 23, 16.44)),
        (dms(79, 2, 52.8), dms(21, 23, 16.8)),
    ],
    "IBM-IMYB2024-AUCTION-090": [
        (dms(78, 54, 27.518), dms(24, 18, 35.641)),
        (dms(78, 55, 11.120), dms(24, 18, 50.653)),
        (dms(78, 55, 31.457), dms(24, 18, 57.653)),
        (dms(78, 56, 29.234), dms(24, 19, 17.536)),
        (dms(78, 56, 33.818), dms(24, 19, 3.338)),
        (dms(78, 55, 47.272), dms(24, 18, 41.476)),
        (dms(78, 55, 33.709), dms(24, 18, 44.805)),
        (dms(78, 55, 32.497), dms(24, 18, 48.401)),
        (dms(78, 55, 29.688), dms(24, 18, 30.757)),
        (dms(78, 55, 30.309), dms(24, 18, 43.774)),
        (dms(78, 55, 23.698), dms(24, 18, 49.273)),
        (dms(78, 54, 50.634), dms(24, 18, 8.137)),
    ],
    "IBM-IMYB2024-AUCTION-091": [
        (dms(82, 51, 41.482), dms(24, 33, 48.067)),
        (dms(82, 52, 23.013), dms(24, 33, 58.731)),
        (dms(82, 53, 12.501), dms(24, 34, 7.358)),
        (dms(82, 53, 15.992), dms(24, 33, 48.825)),
        (dms(82, 52, 31.951), dms(24, 33, 43.248)),
        (dms(82, 51, 45.154), dms(24, 33, 34.047)),
    ],
    "IBM-IMYB2024-AUCTION-092": [
        (dms(83, 1, 41.257), dms(24, 21, 50.0)),
        (dms(83, 1, 41.023), dms(24, 21, 58.0)),
        (dms(83, 1, 26.782), dms(24, 21, 58.0)),
        (dms(83, 1, 26.5), dms(24, 22, 8.7)),
        (dms(83, 1, 32.4), dms(24, 22, 12.9)),
        (dms(83, 1, 45.786), dms(24, 22, 10.785)),
        (dms(83, 1, 51.513), dms(24, 22, 12.653)),
        (dms(83, 2, 13.067), dms(24, 22, 12.63)),
        (dms(83, 2, 13.716), dms(24, 21, 50.0)),
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

# Madhya Pradesh Phase-XI tables with short, visually reviewed coordinate
# lists. Longer numeric tables are parsed below with strict contiguous-ID
# checks so the release builder does not carry thousands of copied literals.
DMS_GEOMETRIES.update({
    "IBM-IMYB2024-AUCTION-037": [
        (dms(74, 28, 58.71), dms(22, 41, 51.24)),
        (dms(74, 29, 1.78), dms(22, 41, 51.32)),
        (dms(74, 29, 3.15), dms(22, 41, 51.18)),
        (dms(74, 29, 3.24), dms(22, 41, 50.57)),
        (dms(74, 29, 3.64), dms(22, 41, 50.07)),
        (dms(74, 29, 4.28), dms(22, 41, 48.61)),
        (dms(74, 29, 4.62), dms(22, 41, 47.58)),
        (dms(74, 29, 4.87), dms(22, 41, 45.39)),
        (dms(74, 29, 5.54), dms(22, 41, 44.29)),
        (dms(74, 29, 5.58), dms(22, 41, 43.13)),
        (dms(74, 29, 5.77), dms(22, 41, 42.80)),
        (dms(74, 29, 6.09), dms(22, 41, 42.82)),
        (dms(74, 29, 7.29), dms(22, 41, 38.89)),
        (dms(74, 29, 7.56), dms(22, 41, 38.50)),
        (dms(74, 29, 8.40), dms(22, 41, 35.15)),
        (dms(74, 29, 6.68), dms(22, 41, 33.87)),
        (dms(74, 29, 5.06), dms(22, 41, 31.49)),
        (dms(74, 29, 3.86), dms(22, 41, 31.32)),
        (dms(74, 29, 3.71), dms(22, 41, 35.07)),
        (dms(74, 29, 6.62), dms(22, 41, 36.14)),
        (dms(74, 29, 6.44), dms(22, 41, 37.51)),
        (dms(74, 29, 5.05), dms(22, 41, 41.26)),
        (dms(74, 29, 3.88), dms(22, 41, 43.11)),
        (dms(74, 29, 3.07), dms(22, 41, 45.20)),
        (dms(74, 29, 2.96), dms(22, 41, 45.06)),
        (dms(74, 29, 2.10), dms(22, 41, 45.16)),
        (dms(74, 29, 0.52), dms(22, 41, 49.31)),
        (dms(74, 29, 0.12), dms(22, 41, 49.34)),
        (dms(74, 28, 57.40), dms(22, 41, 47.97)),
        (dms(74, 28, 57.05), dms(22, 41, 48.02)),
        (dms(74, 28, 56.53), dms(22, 41, 47.82)),
        (dms(74, 28, 56.50), dms(22, 41, 48.19)),
        (dms(74, 28, 57.21), dms(22, 41, 49.36)),
        (dms(74, 28, 58.76), dms(22, 41, 50.30)),
    ],
    "IBM-IMYB2024-AUCTION-038": [
        (dms(74, 39, 18.485), dms(22, 19, 56.104)),
        (dms(74, 40, 36.706), dms(22, 19, 56.104)),
        (dms(74, 40, 35.629), dms(22, 17, 23.610)),
        (dms(74, 39, 44.678), dms(22, 17, 24.328)),
        (dms(74, 39, 29.249), dms(22, 18, 19.943)),
        (dms(74, 39, 15.614), dms(22, 18, 19.943)),
    ],
    "IBM-IMYB2024-AUCTION-039": [
        (dms(74, 22, 39.955), dms(22, 58, 7.035)),
        (dms(74, 23, 30.966), dms(22, 58, 7.189)),
        (dms(74, 24, 6.836), dms(22, 55, 57.960)),
        (dms(74, 22, 39.843), dms(22, 55, 57.853)),
        (dms(74, 22, 39.877), dms(22, 56, 36.847)),
        (dms(74, 23, 12.232), dms(22, 56, 36.847)),
        (dms(74, 23, 10.697), dms(22, 56, 53.310)),
        (dms(74, 22, 39.891), dms(22, 56, 53.342)),
    ],
    "IBM-IMYB2024-AUCTION-040": [
        (dms(74, 37, 23.905), dms(22, 20, 17.433)),
        (dms(74, 38, 19.812), dms(22, 20, 17.079)),
        (dms(74, 38, 19.812), dms(22, 19, 54.463)),
        (dms(74, 39, 16.579), dms(22, 19, 53.727)),
        (dms(74, 39, 14.768), dms(22, 18, 15.820)),
        (dms(74, 38, 21.116), dms(22, 18, 13.016)),
        (dms(74, 38, 18.952), dms(22, 18, 33.343)),
        (dms(74, 38, 3.272), dms(22, 18, 38.133)),
        (dms(74, 38, 2.391), dms(22, 19, 6.924)),
        (dms(74, 37, 24.493), dms(22, 19, 45.410)),
    ],
    "IBM-IMYB2024-AUCTION-041": [
        (77.29571, 26.07884),
        (77.30639, 26.07868),
        (77.30606, 26.12983),
        (77.28866, 26.12967),
        (77.28331, 26.11537),
    ],
    "IBM-IMYB2024-AUCTION-042": [
        (dms(74, 23, 57.230), dms(22, 58, 7.370)),
        (dms(74, 24, 59.880), dms(22, 58, 7.410)),
        (dms(74, 24, 59.770), dms(22, 55, 58.080)),
        (dms(74, 24, 7.210), dms(22, 55, 58.080)),
        (dms(74, 23, 39.710), dms(22, 57, 37.450)),
        (dms(74, 24, 0.600), dms(22, 57, 41.700)),
        (dms(74, 24, 3.400), dms(22, 57, 50.670)),
    ],
    "IBM-IMYB2024-AUCTION-043": [
        (dms(74, 27, 17.200), dms(22, 55, 12.750)),
        (dms(74, 28, 26.070), dms(22, 55, 28.800)),
        (dms(74, 28, 49.080), dms(22, 54, 54.880)),
        (dms(74, 28, 49.080), dms(22, 54, 0.000)),
        (dms(74, 27, 59.040), dms(22, 54, 0.000)),
        (dms(74, 27, 59.040), dms(22, 54, 2.880)),
        (dms(74, 27, 48.600), dms(22, 54, 28.800)),
        (dms(74, 27, 46.080), dms(22, 54, 48.600)),
        (dms(74, 27, 18.000), dms(22, 55, 6.240)),
    ],
    "IBM-IMYB2024-AUCTION-044": [
        (dms(80, 39, 35.514), dms(22, 4, 29.561)),
        (dms(80, 40, 8.786), dms(22, 4, 14.484)),
        (dms(80, 39, 36.432), dms(22, 3, 14.525)),
        (dms(80, 39, 2.423), dms(22, 3, 30.287)),
    ],
    "IBM-IMYB2024-AUCTION-046": [
        (dms(76, 6, 30.330), dms(22, 17, 39.061)),
        (dms(76, 7, 55.141), dms(22, 17, 39.598)),
        (dms(76, 7, 55.365), dms(22, 16, 6.218)),
        (dms(76, 6, 30.330), dms(22, 16, 5.314)),
    ],
    "IBM-IMYB2024-AUCTION-048": [
        (dms(77, 39, 1.50297), dms(21, 53, 14.97172)),
        (dms(77, 39, 27.99477), dms(21, 53, 20.99025)),
        (dms(77, 39, 28.55088), dms(21, 53, 16.27665)),
        (dms(77, 39, 34.06401), dms(21, 53, 17.60946)),
        (dms(77, 39, 34.18544), dms(21, 53, 7.20862)),
        (dms(77, 39, 3.81036), dms(21, 53, 1.81932)),
    ],
})

DMS_POINT_IDS = {
    "IBM-IMYB2024-AUCTION-021": list(range(1, 8)),
    "IBM-IMYB2024-AUCTION-023": list(range(1, 12)),
    "IBM-IMYB2024-AUCTION-024": list("ABCDE"),
    "IBM-IMYB2024-AUCTION-025": list("ABCD"),
    "IBM-IMYB2024-AUCTION-090": list("ABCDEFGHIJKL"),
    "IBM-IMYB2024-AUCTION-091": list("ABCDEF"),
    "IBM-IMYB2024-AUCTION-092": list("ABCDEFGHI"),
    "IBM-IMYB2024-AUCTION-096": [1, 2, 3, 4, 5, 7, 8, 9, 10, 11],
}

DMS_POINT_IDS.update({
    "IBM-IMYB2024-AUCTION-038": list("ABCDEF"),
    "IBM-IMYB2024-AUCTION-039": list("ABCDEFGH"),
    "IBM-IMYB2024-AUCTION-040": list("ABCDEFGHIJ"),
    "IBM-IMYB2024-AUCTION-041": list("ABCDE"),
    "IBM-IMYB2024-AUCTION-042": list("ABCDEFG"),
    "IBM-IMYB2024-AUCTION-043": list("ABCDEFGHI"),
    "IBM-IMYB2024-AUCTION-044": list("ABCD"),
    "IBM-IMYB2024-AUCTION-046": list("ABCD"),
    "IBM-IMYB2024-AUCTION-048": ["A", "B", "C", "I", "J", "H"],
})

MBS_AREA_HA = {
    "IBM-IMYB2024-AUCTION-006": 600.0,
    "IBM-IMYB2024-AUCTION-007": 670.0,
    "IBM-IMYB2024-AUCTION-008": 630.0,
    "IBM-IMYB2024-AUCTION-009": 500.0,
    "IBM-IMYB2024-AUCTION-010": 2400.0,
    "IBM-IMYB2024-AUCTION-011": 240.0,
    "IBM-IMYB2024-AUCTION-012": 5.9933,
    "IBM-IMYB2024-AUCTION-013": 5.5320,
    "IBM-IMYB2024-AUCTION-014": 29.1681,
    "IBM-IMYB2024-AUCTION-015": 5.3152,
    "IBM-IMYB2024-AUCTION-016": 41.3186,
    "IBM-IMYB2024-AUCTION-017": 6.2265,
    "IBM-IMYB2024-AUCTION-018": 63.0,
    "IBM-IMYB2024-AUCTION-019": 258.98968,
    "IBM-IMYB2024-AUCTION-020": 115.220,
    "IBM-IMYB2024-AUCTION-021": 40.04,
    "IBM-IMYB2024-AUCTION-022": 2000.0,
    "IBM-IMYB2024-AUCTION-023": 298.59,
    "IBM-IMYB2024-AUCTION-024": 2501.9,
    "IBM-IMYB2024-AUCTION-025": 52.82,
    "IBM-IMYB2024-AUCTION-026": 52.0,
    "IBM-IMYB2024-AUCTION-027": 120.949,
    "IBM-IMYB2024-AUCTION-028": 102.861,
    "IBM-IMYB2024-AUCTION-029": 4.653,
    "IBM-IMYB2024-AUCTION-030": 332.654,
    "IBM-IMYB2024-AUCTION-031": 9.037,
    "IBM-IMYB2024-AUCTION-032": 4.70,
    "IBM-IMYB2024-AUCTION-033": 4.61,
    "IBM-IMYB2024-AUCTION-034": 5.101,
    "IBM-IMYB2024-AUCTION-035": 9.712,
    "IBM-IMYB2024-AUCTION-036": 11.86,
    "IBM-IMYB2024-AUCTION-037": 4.68,
    "IBM-IMYB2024-AUCTION-038": 913.3954,
    "IBM-IMYB2024-AUCTION-039": 736.4,
    "IBM-IMYB2024-AUCTION-040": 815.0,
    "IBM-IMYB2024-AUCTION-041": 1001.95,
    "IBM-IMYB2024-AUCTION-042": 725.7,
    "IBM-IMYB2024-AUCTION-043": 464.0,
    "IBM-IMYB2024-AUCTION-044": 220.971,
    "IBM-IMYB2024-AUCTION-045": 4.59,
    "IBM-IMYB2024-AUCTION-046": 699.55,
    "IBM-IMYB2024-AUCTION-047": 6.0,
    "IBM-IMYB2024-AUCTION-048": 37.5,
    "IBM-IMYB2024-AUCTION-049": 537.54,
    "IBM-IMYB2024-AUCTION-050": 1526.0,
    "IBM-IMYB2024-AUCTION-051": 886.0,
    "IBM-IMYB2024-AUCTION-052": 640.0,
    "IBM-IMYB2024-AUCTION-053": 397.0,
    "IBM-IMYB2024-AUCTION-054": 500.0,
    "IBM-IMYB2024-AUCTION-055": 658.0,
    "IBM-IMYB2024-AUCTION-056": 105.0,
    "IBM-IMYB2024-AUCTION-057": 1743.24,
    "IBM-IMYB2024-AUCTION-058": 1200.0,
    "IBM-IMYB2024-AUCTION-090": 231.175,
    "IBM-IMYB2024-AUCTION-091": 134.77,
    "IBM-IMYB2024-AUCTION-092": 79.0,
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
    "IBM-IMYB2024-AUCTION-012": {"exploration_level": "G2", "borehole_count": 2, "drilled_meterage_m": 89.0},
    "IBM-IMYB2024-AUCTION-013": {"exploration_level": "G2", "borehole_count": 5, "drilled_meterage_m": 134.0},
    "IBM-IMYB2024-AUCTION-014": {"exploration_level": "G2", "borehole_count": 7, "drilled_meterage_m": 488.0},
    "IBM-IMYB2024-AUCTION-015": {"exploration_level": "G2", "borehole_count": 3, "drilled_meterage_m": 71.0},
    "IBM-IMYB2024-AUCTION-016": {"exploration_level": "G2", "borehole_count": 11, "drilled_meterage_m": 352.5},
    "IBM-IMYB2024-AUCTION-017": {"exploration_level": "G2", "borehole_count": 4, "drilled_meterage_m": 131.0},
    "IBM-IMYB2024-AUCTION-018": {"exploration_level": "G2", "borehole_count": 20, "drilled_meterage_m": 15.25},
    "IBM-IMYB2024-AUCTION-019": {"exploration_level": "G2; G4", "borehole_count": 22, "drilled_meterage_m": 2488.7},
    "IBM-IMYB2024-AUCTION-020": {"exploration_level": "G1; G4", "borehole_count": 378, "drilled_meterage_m": 21102.75},
    "IBM-IMYB2024-AUCTION-021": {"exploration_level": "G3", "borehole_count": 16, "drilled_meterage_m": 727.0},
    "IBM-IMYB2024-AUCTION-022": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-023": {"exploration_level": "G3", "borehole_count": 61, "drilled_meterage_m": 3956.3},
    "IBM-IMYB2024-AUCTION-024": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-025": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-026": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-027": {"exploration_level": "G3", "borehole_count": 21, "drilled_meterage_m": 655.0},
    "IBM-IMYB2024-AUCTION-028": {"exploration_level": "G3", "borehole_count": 11, "drilled_meterage_m": 220.0},
    "IBM-IMYB2024-AUCTION-029": {"exploration_level": "G2", "borehole_count": 4, "drilled_meterage_m": 84.0},
    "IBM-IMYB2024-AUCTION-030": {"exploration_level": "G2", "borehole_count": 37, "drilled_meterage_m": 1082.4},
    "IBM-IMYB2024-AUCTION-031": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-032": {"exploration_level": "G3", "borehole_count": 2, "drilled_meterage_m": 27.0},
    "IBM-IMYB2024-AUCTION-033": {"exploration_level": "G3", "borehole_count": 5, "drilled_meterage_m": 155.0},
    "IBM-IMYB2024-AUCTION-034": {"exploration_level": "G3", "borehole_count": 2, "drilled_meterage_m": 76.4},
    "IBM-IMYB2024-AUCTION-035": {"exploration_level": "G4; considered G3 under MEMC Rules 2021", "borehole_count": 7, "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-036": {"exploration_level": "G3", "borehole_count": 24, "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-037": {"exploration_level": "G3", "borehole_count": 2, "drilled_meterage_m": 46.0},
    "IBM-IMYB2024-AUCTION-038": {"exploration_level": "G4", "borehole_count": "", "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-039": {"exploration_level": "G4", "borehole_count": 1, "drilled_meterage_m": 80.0},
    "IBM-IMYB2024-AUCTION-040": {"exploration_level": "G4", "borehole_count": "", "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-041": {"exploration_level": "G4", "borehole_count": "", "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-042": {"exploration_level": "G4", "borehole_count": 2, "drilled_meterage_m": 190.4},
    "IBM-IMYB2024-AUCTION-043": {"exploration_level": "G4", "borehole_count": "", "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-044": {"exploration_level": "G4", "borehole_count": 9, "drilled_meterage_m": 1544.85},
    "IBM-IMYB2024-AUCTION-045": {"exploration_level": "G3", "borehole_count": 10, "drilled_meterage_m": 300.0},
    "IBM-IMYB2024-AUCTION-046": {"exploration_level": "G4", "borehole_count": "", "drilled_meterage_m": ""},
    "IBM-IMYB2024-AUCTION-047": {"exploration_level": "G3", "borehole_count": 6, "drilled_meterage_m": 110.0},
    "IBM-IMYB2024-AUCTION-048": {"exploration_level": "G3", "borehole_count": 4, "drilled_meterage_m": 337.6},
    "IBM-IMYB2024-AUCTION-049": {"exploration_level": "G2", "borehole_count": 128, "drilled_meterage_m": 6234.45},
    "IBM-IMYB2024-AUCTION-050": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-051": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-052": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-053": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-054": {"exploration_level": "G4", "borehole_count": 15, "drilled_meterage_m": 149.5},
    "IBM-IMYB2024-AUCTION-055": {"exploration_level": "G4", "borehole_count": 0, "drilled_meterage_m": 0.0},
    "IBM-IMYB2024-AUCTION-056": {"exploration_level": "G2", "borehole_count": 27, "drilled_meterage_m": 2373.65},
    "IBM-IMYB2024-AUCTION-057": {"exploration_level": "G3", "borehole_count": 10, "drilled_meterage_m": 1746.9},
    "IBM-IMYB2024-AUCTION-058": {"exploration_level": "G4", "borehole_count": 3, "drilled_meterage_m": 281.5},
    "IBM-IMYB2024-AUCTION-090": {"exploration_level": "G3", "borehole_count": 44, "drilled_meterage_m": 8265.12},
    "IBM-IMYB2024-AUCTION-091": {"exploration_level": "G3", "borehole_count": 8, "drilled_meterage_m": 822.7},
    "IBM-IMYB2024-AUCTION-092": {"exploration_level": "G3", "borehole_count": 19, "drilled_meterage_m": 2359.9},
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
    "IBM-IMYB2024-AUCTION-012": {
        "exploration_agency_source": "M. K. Soil Testing Laboratory, Ahmedabad.",
        "borehole_summary_source": "2 boreholes with cumulative meterage of 89.00 m (40 m and 49 m).",
        "mineral_source_mbs": "Laterite and aluminous laterite (bauxite), described as cement grade.",
        "geological_resources_source": "Indicated resource (332): 2,357,197 tonnes aluminous laterite (bauxite) and 2,776,165 tonnes laterite.",
        "grade_source": "Aluminous laterite (bauxite): 25.75% Al2O3, 37.73% SiO2 and 16.29% Fe2O3; laterite: 16.66% Al2O3, 50.32% SiO2 and 15.22% Fe2O3.",
        "mineral_zones_source": "Aluminous laterite (bauxite) and laterite.",
        "dip_strike_source": "Horizontal bedded.",
        "thickness_source": "Average thickness 18.18 m for aluminous laterite (bauxite) and 19.44 m for laterite.",
        "accessibility_source": "Bhatiya Railway Station 16.73 km; State Highway 6 at 8.37 km; Porbandar Airport 75.36 km.",
        "hydrography_source": "Dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 2,594 mm; December temperature 10.6-25.2 C; June temperature 29.6-41.7 C.",
        "topography_source": "Flat terrain; Survey of India toposheet 41 F/08.",
    },
    "IBM-IMYB2024-AUCTION-013": {
        "exploration_agency_source": "Vinayak Engimech Pvt. Ltd.",
        "borehole_summary_source": "5 boreholes with cumulative meterage of 134.00 m.",
        "mineral_source_mbs": "Bauxite and marl.",
        "geological_resources_source": "Indicated resource (332): 217,740.12 tonnes bauxite; 1,692,208.95 tonnes aluminous laterite (major mineral); 88,575.98 tonnes marl.",
        "grade_source": "Bauxite: 44.64% Al2O3 and 6.15% SiO2; aluminous laterite: 39.10% Al2O3 and 16.57% SiO2; marl: 30.50% CaO and 2.10% MgO.",
        "mineral_zones_source": "Bauxite and marl.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Average thickness 1.20 m bauxite, 12.07 m aluminous laterite and 0.49 m marl.",
        "accessibility_source": "Bhatiya Railway Station approximately 22 km; Gujarat State Highways 29 and 6; Jamnagar Airport approximately 92 km.",
        "hydrography_source": "Dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 580.60 mm; temperature 15-42 C.",
        "topography_source": "Undulatory terrain with small hillocks; Survey of India toposheets 41F/6 and 41F/7.",
    },
    "IBM-IMYB2024-AUCTION-014": {
        "exploration_agency_source": "Vinayak Engimech Pvt. Ltd.",
        "borehole_summary_source": "7 boreholes with cumulative meterage of 488.00 m.",
        "mineral_source_mbs": "Limestone and marl.",
        "geological_resources_source": "Indicated resource (332): 7,138,102.29 tonnes cement-grade limestone, 1,868,408.99 tonnes limestone and 1,164,058.58 tonnes marl.",
        "grade_source": "Cement-grade limestone: 44.74% CaO and 0.53% MgO; limestone: 37.86% CaO and 1.13% MgO; marl: 30.34% CaO and 1.00% MgO.",
        "mineral_zones_source": "Limestone and marl.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Average thickness 9.15 m cement-grade limestone, 2.72 m limestone and 1.49 m marl.",
        "accessibility_source": "Veraval Junction Railway Station; NH-8D; Diu Airport; Veraval (Mangrol) seaport.",
        "hydrography_source": "Sub-dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 1,135.75 mm; December temperature 11-28 C; June temperature 28-42 C.",
        "topography_source": "Flat terrain with small undulations; Survey of India toposheets 41L/9 and 41L/10.",
    },
    "IBM-IMYB2024-AUCTION-015": {
        "exploration_agency_source": "Vinayak Engimech Pvt. Ltd.",
        "borehole_summary_source": "3 boreholes with cumulative meterage of 71.00 m.",
        "mineral_source_mbs": "Bauxite, limestone and marl.",
        "geological_resources_source": "Indicated resource (332): 145,744.93 tonnes bauxite; 1,346,321.34 tonnes aluminous laterite; 100,403.06 tonnes cement-grade limestone; 16,196.50 tonnes limestone; 69,015.48 tonnes marl.",
        "grade_source": "Bauxite: 45.29% Al2O3 and 6.71% SiO2; aluminous laterite: 38.02% Al2O3 and 18.41% SiO2; cement-grade limestone: 46.43% CaO and 0.30% MgO; limestone: 35.00% CaO and 0.32% MgO; marl: 32.38% CaO and 0.33% MgO.",
        "mineral_zones_source": "Bauxite, limestone and marl.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Average thickness 1.32 m bauxite, 9.42 with no unit printed for aluminous laterite, 1.60 m cement-grade limestone, 0.58 m limestone and 0.93 m marl.",
        "accessibility_source": "Bhatiya Railway Station approximately 8 km; Gujarat State Highway 29; Porbandar Airport approximately 86 km.",
        "hydrography_source": "Dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 580.60 mm; temperature 15-42 C.",
        "topography_source": "Undulatory terrain with small hillocks; Survey of India toposheet 41F/8.",
    },
    "IBM-IMYB2024-AUCTION-016": {
        "exploration_agency_source": "Vinayak Engimech Pvt. Ltd.",
        "borehole_summary_source": "11 boreholes with cumulative meterage of 352.50 m.",
        "mineral_source_mbs": "Limestone and marl.",
        "geological_resources_source": "Indicated resource (332): 3,364,189.08 tonnes cement-grade limestone, 1,498,679.45 tonnes limestone and 883,236.77 tonnes marl.",
        "grade_source": "Cement-grade limestone: 45.47% CaO and 0.26% MgO; limestone: 37.50% CaO and 0.39% MgO; marl: 29.63% CaO and 0.46% MgO.",
        "mineral_zones_source": "Limestone and marl.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Average thickness 3.04 m cement-grade limestone, 1.42 m limestone and 0.82 m marl.",
        "accessibility_source": "Veraval Junction Railway Station; NH-8D; Diu Airport; Veraval (Mangrol) seaport.",
        "hydrography_source": "Sub-dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 1,135.75 mm; December temperature 11-28 C; June temperature 28-42 C.",
        "topography_source": "Flat terrain with small undulations; Survey of India toposheets 41L/9 and 41L/10.",
    },
    "IBM-IMYB2024-AUCTION-017": {
        "exploration_agency_source": "Vinayak Engimech Pvt. Ltd.",
        "borehole_summary_source": "4 boreholes with cumulative meterage of 131.00 m.",
        "mineral_source_mbs": "Bauxite (aluminous laterite), limestone and marl.",
        "geological_resources_source": "Indicated resource (332): 750,960.61 tonnes aluminous laterite, 108,236.81 tonnes cement-grade limestone, 35,340.09 tonnes limestone and 17,549.12 tonnes marl.",
        "grade_source": "Aluminous laterite: 38.03% Al2O3 and 27.15% SiO2; cement-grade limestone: 42.96% CaO and 1.13% MgO; limestone: 37.78% CaO and 0.74% MgO; marl: 28.34% CaO and 1.91% MgO.",
        "mineral_zones_source": "Bauxite (aluminous laterite), limestone and marl.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Average thickness 4.63 m aluminous laterite, 0.65 m cement-grade limestone, 0.27 m limestone and 0.22 m marl.",
        "accessibility_source": "Bhatiya Railway Station approximately 22 km; Gujarat State Highway 29; Jamnagar Airport approximately 92 km.",
        "hydrography_source": "Dendritic drainage; seasonal tributaries.",
        "climate_source": "Mean annual rainfall 580.60 mm; temperature 15-42 C.",
        "topography_source": "Undulatory terrain with small hillocks; Survey of India toposheets 42J/7 and 42J/8.",
    },
    "IBM-IMYB2024-AUCTION-018": {
        "exploration_agency_source": "Directorate of Geology, Department of Mines and Geology, Jharkhand.",
        "mineral_source_mbs": "Bauxite",
        "geological_resources_source": "4.412454 million tonnes of bauxite.",
        "grade_source": "Average 40.02% Al2O3 and 4.91% SiO2.",
        "borehole_summary_source": "20 boreholes; total meterage printed as 15.25 m.",
        "climate_source": "Mean annual rainfall 1800-2000 mm; minimum temperature 14 C; maximum temperature 38.2 C.",
        "topography_source": "Undulatory terrain; altitude varies across the area.",
    },
    "IBM-IMYB2024-AUCTION-019": {
        "exploration_agency_source": "Ex-lessee M/s Rameshwara Jute Mills Ltd.; reassessed by Directorate of Geology, Jharkhand.",
        "mineral_source_mbs": "Iron and manganese ores",
        "geological_resources_source": "Iron ore: 32.230 million tonnes at G2 plus 45.6238 million tonnes at G4; manganese ore: 1.524 million tonnes at G2 plus 2.089 million tonnes at G4, as at 2020-04-01 after production deduction.",
        "grade_source": "Iron ore average 55.68% Fe; manganese average above 20% and below 25% Mn.",
        "borehole_summary_source": "22 boreholes with cumulative meterage of 2,488.7 m.",
        "climate_source": "Mean annual rainfall 200 cm; minimum temperature 3-4 C; maximum temperature 45 C.",
        "topography_source": "Undulatory terrain; altitude ranges from 443 m to 681 m.",
    },
    "IBM-IMYB2024-AUCTION-020": {
        "exploration_agency_source": "Ex-lessee M/s Rungta Mines Ltd.; reassessed by Directorate of Geology, Jharkhand.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "640,319.08 tonnes: 469,595.42 tonnes in UNFC 331 and 170,723.66 tonnes in UNFC 334.",
        "grade_source": "Average 54.77% Fe at 45% Fe cut-off; 63.50% production/dispatch-derived average used for VER calculation.",
        "borehole_summary_source": "378 boreholes with cumulative meterage of 21,102.75 m.",
        "climate_source": "Annual rainfall printed as a 65-225 cm range; minimum temperature 4.8 C; maximum temperature 47 C.",
        "topography_source": "Undulatory terrain.",
    },
    "IBM-IMYB2024-AUCTION-021": {
        "exploration_agency_source": "KIOCL, based on erstwhile-lessee exploration data for 32.00 ha.",
        "borehole_summary_source": "16 core boreholes with cumulative meterage of 727.00 m, drilled by the erstwhile lessee in 32.00 ha.",
        "mineral_source_mbs": "Iron ore and banded hematite quartzite (BHQ)",
        "geological_resources_source": "5.32 million tonnes of iron ore.",
        "grade_source": "Average 64.66% Fe.",
        "mineral_zones_source": "One band, flanked by shale on either side.",
        "dip_strike_source": "N35W-S35E strike with steep 75-80 degree dips toward ENE.",
        "thickness_source": "Refer to the Geological Report.",
        "accessibility_source": "Ranjithpura Railway Station; 15 km from Sandur and 60 km from Ballari; Vidyanagar Airport, Toranagallu.",
        "hydrography_source": "Dendritic drainage; Tungabhadra River and Narihalla stream.",
        "climate_source": "Mean annual rainfall 40-80 cm; December temperature 21-26 C; June temperature 24-29 C.",
        "topography_source": "Undulating, hilly terrain.",
    },
    "IBM-IMYB2024-AUCTION-022": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Gold",
        "geological_resources_source": "Resources have not been estimated at G4 level.",
        "grade_source": "Two sampled zones: 0.076 g/t Au over 4 m and 0.95 g/t over 1 m; 0.3 g/t over 1 m and 0.59 g/t over 5 m.",
        "mineral_zones_source": "Two 100 m mineralized zones in the westernmost and easternmost BIF units.",
        "dip_strike_source": "N10W-S10E to N50W-S50E; moderate to steep dips east or west.",
        "thickness_source": "Not applicable.",
        "accessibility_source": "Tumkur Railway Station; Bangalore-Hosadurga National Highway via Chiknayakanahalli and NH-69; Bengaluru Airport.",
        "hydrography_source": "Dendritic drainage; Borankanave reservoir is near the block and a canal crosses its northeastern corner.",
        "climate_source": "Mean annual rainfall 458 mm; April temperature 30.2 C; December temperature 22.7 C.",
        "topography_source": "Undulating, rugged terrain.",
    },
    "IBM-IMYB2024-AUCTION-023": {
        "exploration_agency_source": "Mineral Exploration and Consultancy Limited (MECL).",
        "borehole_summary_source": "61 boreholes (37 core and 24 reverse-circulation) with cumulative meterage of 3,956.30 m; 40 by MECL and 21 by erstwhile lessees.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "17.66 million tonnes total: 9.89 million tonnes massive, 5.64 million tonnes laminated, and 2.13 million tonnes siliceous iron ore.",
        "grade_source": "Massive iron ore averages 66.61% Fe; laminated 56.56% Fe; siliceous 40.57% Fe.",
        "mineral_zones_source": "Three prominent, approximately parallel BIF reefs trending northwest-southeast.",
        "dip_strike_source": "Northwest-southeast strike with 65-85 degree dips toward southwest.",
        "thickness_source": "Refer to the Geological Report.",
        "accessibility_source": "Ingaligi Railway Station; 20 km from Hosapete and Sandur and 75 km from Ballari; Vidyanagar Airport, Toranagallu.",
        "hydrography_source": "Dendritic drainage; Tungabhadra River and Narihalla stream.",
        "climate_source": "Mean annual rainfall 40-80 cm; December temperature 21-26 C; June temperature 24-29 C.",
        "topography_source": "Undulating, hilly terrain.",
    },
    "IBM-IMYB2024-AUCTION-024": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Gold ore",
        "geological_resources_source": "Mineral resources have not been estimated at G4 level.",
        "grade_source": "A 240 m mineralized zone has a reported weighted average of 0.178 g/t Au over 3.5 m.",
        "mineral_zones_source": "One 240 m mineralized zone was established in earlier work; the source notes scope for additional zones.",
        "dip_strike_source": "North-south to NNE-SSW strike; east dipping.",
        "thickness_source": "Not applicable.",
        "accessibility_source": "Tumkur Railway Station; State Highway 69 passes 5 km south of the block; Bengaluru Airport.",
        "hydrography_source": "Dendritic drainage; Chikka Tore stream flows northwest through the block toward the Suvarna Mukhi River.",
        "climate_source": "Mean annual rainfall 55-65 cm; December temperature 26-28 C; June temperature 35-38 C.",
        "topography_source": "Undulating, hilly terrain.",
    },
    "IBM-IMYB2024-AUCTION-025": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Bauxite in the block title and grade text; the quantity row anomalously prints 'Iron ore'.",
        "geological_resources_source": "145,000 tonnes (0.145 million tonnes); the source quantity row contains the mineral-label anomaly noted separately.",
        "grade_source": "Bauxite grade bands by Al2O3: Grade I above 51%; Grade II 48-51%; Grade III 45-48%; Grade IV 38-45%.",
        "mineral_zones_source": "Four bauxite grade classes calculated by area of influence around pits using a tonnage factor of two.",
        "dip_strike_source": "Not applicable for the bulk commodity; mineralization is controlled by weathering.",
        "thickness_source": "Not applicable.",
        "accessibility_source": "Mangaluru Railway Station; Niddodi is 35 km from Mangalore and 32 km south-southwest of Karkala; Mangaluru Airport.",
        "hydrography_source": "Plateau with sparse first-order drainage; no river or stream is listed.",
        "climate_source": "Mean annual rainfall 3,635 mm; December temperature 21 C; June temperature 42 C.",
        "topography_source": "Undulating plateau.",
    },
    "IBM-IMYB2024-AUCTION-026": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Bauxite",
        "geological_resources_source": "254,300 tonnes total: 116,800 tonnes Type I and 137,500 tonnes Type II.",
        "grade_source": "Type I averages 42.21% Al2O3; Type II averages 34.12% Al2O3; total average 38.17% Al2O3.",
        "mineral_zones_source": "Irregular lenses and fillings in vertical joints and fissures within massive laterite.",
        "dip_strike_source": "Not applicable for the bulk commodity; mineralization is controlled by weathering.",
        "thickness_source": "Not determined.",
        "accessibility_source": "Mulki Railway Station around 17 km away; 40 km from Mangalore and 8 km from Moodbidri; Mangalore Airport.",
        "hydrography_source": "Dendritic to sub-dendritic drainage; Mulki River in the central part and Pavanje River in the southern part.",
        "climate_source": "Mean annual rainfall 350 cm; April temperature 32 C; December temperature 22.4 C.",
        "topography_source": "Undulating, hilly terrain.",
    },
    "IBM-IMYB2024-AUCTION-027": {
        "exploration_agency_source": "UltraTech Cement Limited, Vikram Cement Unit.",
        "borehole_summary_source": "21 boreholes with cumulative meterage of 655.00 m.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "7.621 million tonnes of inferred limestone resources in the 87.756 ha mineralized area.",
        "grade_source": "Average 45.2% CaO, 2.2% MgO and 12.14% SiO2; described as cement-grade limestone.",
        "climate_source": "Mean annual rainfall about 1,100 mm; temperatures range from 4 C in winter to 47 C in summer.",
    },
    "IBM-IMYB2024-AUCTION-028": {
        "exploration_agency_source": "GIEM (India) Consortium; qualified person Balram Singh Associates Pvt. Ltd.",
        "borehole_summary_source": "11 boreholes with cumulative drill depth of 220 m.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "23.915 million tonnes inferred in the revised 102.861 ha DGPS block; 20.048 million tonnes in the 86.226 ha available area.",
        "grade_source": "Cement-grade limestone; 35-49.40% CaO, 3-10% SiO2 and 3-5% MgO.",
        "climate_source": "Rainfall and seasonal temperatures are not reported in the selected MBS.",
    },
    "IBM-IMYB2024-AUCTION-029": {
        "exploration_agency_source": "S. V. Gokhale (RQP) and Nikhil Pashine for M. S. Minerals.",
        "borehole_summary_source": "4 inclined boreholes with cumulative meterage of 84.00 m.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "35,658 tonnes, treated as indicated resource (332) under MEMC 2021 in the MBS.",
        "grade_source": "17.20-39.20% Mn in pit samples and 18.50-32.90% Mn in borehole-core samples; source guidance is +25% Mn.",
        "climate_source": "Rainfall and seasonal temperatures are reported as NA.",
    },
    "IBM-IMYB2024-AUCTION-030": {
        "exploration_agency_source": "Directorate of Geology and Mining, Madhya Pradesh.",
        "borehole_summary_source": "37 boreholes with cumulative drill depth of 1,082.40 m.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "100.98 million tonnes indicated over 284.430 ha: 61.896608 million tonnes cement grade and 39.085487 million tonnes blendable grade.",
        "grade_source": "Average 44.10% CaO; cement-grade resource averages 46.89% CaO and blendable resource 39.39% CaO.",
        "climate_source": "Mean annual rainfall 1,074.7 mm; December temperature 9 C; June temperature 47 C.",
    },
    "IBM-IMYB2024-AUCTION-031": {
        "exploration_agency_source": "S. P. Mahakud, consultant geologist.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Manganese ore and dolomite",
        "geological_resources_source": "Reconnaissance resources: 63,000 tonnes manganese ore and 161,280 tonnes dolomite.",
        "grade_source": "12.50-29.40% Mn; refractory-grade dolomite reported at 34.23% CaO and 18.91% MgO.",
        "climate_source": "Rainfall and seasonal temperatures are not reported in the selected MBS.",
    },
    "IBM-IMYB2024-AUCTION-032": {
        "exploration_agency_source": "Indraneel Dawande (RQP) for Jhabua Ferro Alloys.",
        "borehole_summary_source": "2 vertical boreholes with cumulative meterage of 27.00 m.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "44,887 tonnes of inferred manganese resource over 4.70 ha.",
        "grade_source": "21.52-22.81% Mn, 18.97-21.87% SiO2, 12.20-18.35% Fe and 0.038-0.043% P.",
        "climate_source": "Mean annual rainfall 800 mm; December temperature 6 C; June temperature 46 C.",
    },
    "IBM-IMYB2024-AUCTION-033": {
        "exploration_agency_source": "Manoj Kumar (RQP), Geo Solutions Pvt. Ltd., for V. S. Alloys & Steel Pvt. Ltd.",
        "borehole_summary_source": "5 vertical boreholes with cumulative meterage of 155.00 m.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "36,000 tonnes of in-situ inferred manganese resource.",
        "grade_source": "Average 11.50% Mn, 46.81% SiO2, 6.95% Fe2O3, 4.32% Al2O3 and 0.028% P.",
        "climate_source": "Mean annual rainfall 1,200-1,400 mm; December temperature 8 C; June temperature 46 C.",
    },
    "IBM-IMYB2024-AUCTION-034": {
        "exploration_agency_source": "M. S. Waghmare (RQP) for Soham Ferro Manganese Pvt. Ltd. and lessee Aditya Pandit.",
        "borehole_summary_source": "2 vertical boreholes with cumulative meterage of 76.40 m; neither intersected manganese.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "218,357 tonnes of inferred float-ore resource over about 3.97 ha; no resource was estimated from boreholes.",
        "grade_source": "28.06-30.11% Mn, 13.15-16.50% SiO2, 8.80-9.20% Fe2O3 and 0.103-0.125% P.",
        "climate_source": "Rainfall and seasonal temperatures are reported as not available.",
    },
    "IBM-IMYB2024-AUCTION-035": {
        "exploration_agency_source": "Dhiraj Ore Pvt. Ltd.; prospecting report by S. M. Jathar.",
        "borehole_summary_source": "7 boreholes (5 DTH and 2 core); cumulative meterage is not stated.",
        "mineral_source_mbs": "Manganese ore",
        "geological_resources_source": "16,160 tonnes reconnaissance resource: 14,400 tonnes in situ and 1,760 tonnes float ore.",
        "grade_source": "22.39-38.71% Mn, 5.35-8.05% Fe, 4.81-21.53% SiO2, 11.08% Al2O3 and 0.11-0.49% P2O5.",
        "climate_source": "Mean annual rainfall 1,150 mm; summer reaches 44 C and winter minimum is about 10 C.",
    },
    "IBM-IMYB2024-AUCTION-036": {
        "exploration_agency_source": "Manoj Kumar (RQP) for A V Mines Private Limited.",
        "borehole_summary_source": "24 vertical boreholes; cumulative meterage is not stated.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "54,900 tonnes across two bands, categorized in the source as measured/inferred (331/333).",
        "grade_source": "Average 30.96% Mn.",
        "climate_source": "Annual rainfall 1,100-1,200 mm; December minimum 8 C; June maximum 46 C.",
    },
    "IBM-IMYB2024-AUCTION-037": {
        "exploration_agency_source": "A. K. Srivastava (RQP) for Jhabua Metals.",
        "borehole_summary_source": "2 boreholes with cumulative meterage of 46.00 m: one vertical core hole and one inclined DTH hole.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "20,546.24 tonnes inferred manganese resource; the source says about 40% of the PL area was not explored.",
        "grade_source": "27-32% Mn, 9-12.20% SiO2, 19.88-22.41% Fe and 4.78-5.00% Al2O3.",
        "climate_source": "Mean annual rainfall 1,200 mm; December temperature 4 C; June temperature 46 C.",
    },
    "IBM-IMYB2024-AUCTION-038": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "NA.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "158 million tonnes over 524 ha, derived in the MBS by arithmetic extrapolation from adjacent Kherli-Mogra limestone rather than block drilling.",
        "grade_source": "BRS samples report 36.344-52.36% CaO, 8.284-45.33% SiO2 and 0.081-0.712% MgO.",
        "climate_source": "The MBS prints 871 mm average annual rainfall and separately 280 cm for southwest-monsoon rainfall; December minimum 19.5 C and June maximum 46 C. The internal rainfall-unit conflict is retained.",
    },
    "IBM-IMYB2024-AUCTION-039": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "1 scout borehole (SBH-3) with 80.0 m meterage.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "NA; the selected MBS does not estimate a block resource.",
        "grade_source": "Trench and grab samples reach 34.9% Mn; four drilled intervals are reported at 3.66%, 1.254%, 0.716% and 1.09% Mn.",
        "climate_source": "Annual rainfall 750-1,000 mm; December temperature 4-5 C; June temperature 44 C.",
    },
    "IBM-IMYB2024-AUCTION-040": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "NA.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "105 million tonnes over 348 ha, derived in the MBS by arithmetic extrapolation from adjacent Kherli-Mogra limestone rather than block drilling.",
        "grade_source": "BRS samples report 38.45-51.458% CaO, 9.206-39.204% SiO2 and 0.425-2.954% MgO.",
        "climate_source": "The MBS prints 871 mm average annual rainfall and separately 280 cm for southwest-monsoon rainfall; December minimum 19.5 C and June maximum 46 C. The internal rainfall-unit conflict is retained.",
    },
    "IBM-IMYB2024-AUCTION-041": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "NA.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "76.44 million tonnes over 245 ha of exposed limestone.",
        "grade_source": "Average 41.84% CaO, 1.77% MgO, 1.354% Fe2O3, 2.348% Al2O3 and 10.49% SiO2; described as cement grade.",
        "climate_source": "Mean annual rainfall is NA; December minimum 5 C and June maximum 45 C.",
    },
    "IBM-IMYB2024-AUCTION-042": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "2 scout boreholes with cumulative meterage of 190.4 m.",
        "mineral_source_mbs": "Manganese",
        "geological_resources_source": "NA; the selected MBS does not estimate a block resource.",
        "grade_source": "Trench samples range from 1.8% to 29% Mn; BRS samples range from 5.26% to 42.52% Mn.",
        "climate_source": "Annual rainfall 750-1,000 mm; December temperature 4-5 C; June temperature 44 C.",
    },
    "IBM-IMYB2024-AUCTION-043": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "NA.",
        "mineral_source_mbs": "Phosphorite",
        "geological_resources_source": "Not estimated for the Piploda block; reserve figures printed for adjacent blocks are not attributed to Piploda.",
        "grade_source": "Block-context sampling includes 0.04-0.42% P2O5 in stream sediment/slope wash and seven BRS samples above 2% P2O5.",
        "climate_source": "Mean annual rainfall 902.85 mm; December minimum 4 C; annual minimum/maximum/average printed as 4 C, 45-48 C and 32 C.",
    },
    "IBM-IMYB2024-AUCTION-044": {
        "exploration_agency_source": "Mineral Exploration Corporation Limited, with cited GSI geochemical work.",
        "borehole_summary_source": "9 inclined scout boreholes with cumulative meterage of 1,544.85 m.",
        "mineral_source_mbs": "Copper",
        "geological_resources_source": "0.36 million tonnes net in-situ reconnaissance resource.",
        "grade_source": "Average 0.37% Cu at a 0.2% Cu cut-off; borehole intersections range from 0.23% to 0.65% Cu.",
        "climate_source": "Average rainfall 127 cm for 1979-2002; summer maximum 44.1 C and peak-winter minimum 2.1 C.",
    },
    "IBM-IMYB2024-AUCTION-045": {
        "exploration_agency_source": "Khatri Minerals and Mining Company; prospecting report by M. M. Gosavi.",
        "borehole_summary_source": "10 vertical DTH boreholes with cumulative meterage of 300 m.",
        "mineral_source_mbs": "Iron ore (hematite and blue dust); ochre is also present but has no estimated resource.",
        "geological_resources_source": "0.855 million tonnes in Block-A; 374,400 tonnes inferred in the available 0.832 ha mineralized area.",
        "grade_source": "40.18-49.83% Fe; the source classifies the available resource as low grade (+35% to below 45% Fe).",
        "climate_source": "Mean annual rainfall 1,200 mm; source describes temperatures of 46 C in summer and 4 C in winter.",
    },
    "IBM-IMYB2024-AUCTION-046": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "NA.",
        "mineral_source_mbs": "Phosphorite",
        "geological_resources_source": "50,625 tonnes in situ at 8.46% P2O5, or alternatively 22,500 tonnes at an average 16.66% P2O5.",
        "grade_source": "Channel samples range from 0.1% to 24.57% P2O5; trench samples range from 0.13% to 15.45% P2O5.",
        "climate_source": "Mean annual rainfall about 100 cm; January 8-20 C (average 14 C) and June 40-45 C (average 42 C).",
    },
    "IBM-IMYB2024-AUCTION-047": {
        "exploration_agency_source": "Shivam Borewells and Apex Survey Consultant; prospecting report by Balram Singh Associates for Hazi Steel Traders.",
        "borehole_summary_source": "6 vertical non-core DTH boreholes with cumulative meterage of 110.00 m.",
        "mineral_source_mbs": "Iron ore (hematite)",
        "geological_resources_source": "1,414,888 tonnes above 45% Fe estimated for 4 ha in Blocks 1 and 2; the MBS extrapolates 2,120,582.52 tonnes for the 6 ha auction block.",
        "grade_source": "Fe values 52% and 58.1%; SiO2 7.6% and 9.2%; Al2O3 3.20% and 6.8%; TiO2 0.40% and 1.6%.",
        "climate_source": "Rainfall and seasonal temperatures are reported as NA.",
    },
    "IBM-IMYB2024-AUCTION-048": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "4 boreholes with cumulative meterage of 337.60 m over a 300 m strike length.",
        "mineral_source_mbs": "Graphite and vanadium",
        "geological_resources_source": "0.619 million tonnes graphite resource and 0.49 million tonnes vanadium-bearing material.",
        "grade_source": "Graphite averages 9.05% fixed carbon; vanadium averages 840 ppm V (1,499.6 ppm V2O5) at a 560 ppm V cut-off.",
        "climate_source": "Mean annual rainfall 1,085.2 mm; December minimum 10.5 C and June maximum 45 C.",
    },
    "IBM-IMYB2024-AUCTION-049": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "128 boreholes with cumulative meterage of 6,234.45 m at 100 m by 200 m spacing.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "149.50 million tonnes above 42% CaO: 61.92 million tonnes SMS grade and 87.58 million tonnes cement grade; classified as indicated resource (332).",
        "grade_source": "More than 42% CaO for the auctioned resource.",
        "mineral_zones_source": "One mineral zone.",
        "dip_strike_source": "Northwest-southeast strike; dip 25-80 degrees toward north and south.",
        "thickness_source": "Not stated in the MBS.",
        "accessibility_source": "Ballarshah Junction; Chandrapur-Sironcha State Highway; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Pranhita River and Katepalli Nala are named as major water sources.",
        "climate_source": "Mean annual rainfall 1,500 mm; December temperature 12 C; June temperature 46 C.",
        "topography_source": "Plain terrain with a gentle slope toward the southwest.",
    },
    "IBM-IMYB2024-AUCTION-050": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "Not estimated (NA).",
        "grade_source": "66-68% Fe lumps.",
        "mineral_zones_source": "Nine massive iron-ore zones, 10-150 m long and 10-50 m wide.",
        "dip_strike_source": "Northeast-southwest strike; dip 70-80 degrees southeast.",
        "thickness_source": "Assumed thickness 15-60 m.",
        "accessibility_source": "Wadsa Railway Station; NH-353D; block about 7 km northwest of Puske village; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Bandia River and Jambia Nala.",
        "climate_source": "Mean annual rainfall 450 mm; source prints December temperature up to 42 C and June temperature up to 7 C (apparent seasonal-label anomaly retained).",
        "topography_source": "Hilly terrain and valleys.",
    },
    "IBM-IMYB2024-AUCTION-051": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "Not estimated (NA).",
        "grade_source": "Above 65% Fe lumps; range 63-68% Fe.",
        "mineral_zones_source": "Six massive iron-ore zones at Gandhmaka Meta and two at Edasgunj Meta; reported lengths 20-150 m and widths about 10-20 m.",
        "dip_strike_source": "Gandhmaka Meta: northeast-southwest, dip 80 degrees southeast; Edasgunj Meta: east-northeast-west-southwest, dip 80 degrees southeast.",
        "thickness_source": "Assumed thickness 15-60 m at Gandhmaka Meta and 20-30 m at Edasgunj Meta.",
        "accessibility_source": "Wadsa Railway Station; NH-353D approaches via Modaske and Puske villages; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Bandia River and Jambia Nala.",
        "climate_source": "Mean annual rainfall 450 mm; source prints December temperature up to 42 C and June temperature up to 7 C (apparent seasonal-label anomaly retained).",
        "topography_source": "Hilly terrain and valleys.",
    },
    "IBM-IMYB2024-AUCTION-052": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "Not estimated (NA).",
        "grade_source": "Above 65% Fe lumps; range 63-68% Fe.",
        "mineral_zones_source": "Three massive iron-ore zones at Morgal Meta and one at Warshankoti; reported lengths 30-60 m and widths 3-20 m.",
        "dip_strike_source": "Northeast-southwest strike; dip 70-80 degrees southeast.",
        "thickness_source": "Assumed thickness 15-60 m at Morgal Meta and 15 m at Warshankoti.",
        "accessibility_source": "Wadsa Railway Station; NH-353D; Morgal Meta and Warshankoti about 5 km northwest of Modaske village; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Bandia River and Jambia Nala.",
        "climate_source": "Mean annual rainfall 450 mm; source prints December temperature up to 42 C and June temperature up to 7 C (apparent seasonal-label anomaly retained).",
        "topography_source": "Hilly terrain and valleys.",
    },
    "IBM-IMYB2024-AUCTION-053": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "Not estimated (NA).",
        "grade_source": "Average 62.58% Fe lumps; range 58.53-66.63% Fe.",
        "mineral_zones_source": "Eight lensoid iron-ore zones, 20-220 m long and 10-25 m wide.",
        "dip_strike_source": "Northeast-southwest strike; dip 70-80 degrees southeast.",
        "thickness_source": "Assumed thickness 30-60 m.",
        "accessibility_source": "Wadsa Railway Station; NH-353D; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Bandia River and Jambia Nala.",
        "climate_source": "Mean annual rainfall 450 mm; source prints December temperature up to 42 C and June temperature up to 7 C (apparent seasonal-label anomaly retained).",
        "topography_source": "Hilly terrain and valleys.",
    },
    "IBM-IMYB2024-AUCTION-054": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "15 boreholes with cumulative meterage of 149.50 m, drilled at random spacing.",
        "mineral_source_mbs": "Bauxite",
        "geological_resources_source": "Not estimated (not applicable).",
        "grade_source": "Not stated; the source labels the pockets low to medium grade.",
        "mineral_zones_source": "Two to three pockets of low- to medium-grade bauxite.",
        "dip_strike_source": "Not stated in the MBS.",
        "thickness_source": "Bauxite thickness 0.50-2.50 m; aluminous laterite thickness 0.50-6 m.",
        "accessibility_source": "Rajapur Road railway station; NH-66 east of the area; Kolhapur Airport.",
        "hydrography_source": "Dendritic drainage; Kodvali River.",
        "climate_source": "Mean annual rainfall printed as 600 cm; December temperature 15 C; June temperature 40 C (source unit retained).",
        "topography_source": "Undulating lateritic terrain.",
    },
    "IBM-IMYB2024-AUCTION-055": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "Nil.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "Not estimated (NA).",
        "grade_source": "60-62% Fe lumps.",
        "mineral_zones_source": "Not stated (not applicable in the MBS).",
        "dip_strike_source": "Northeast-southwest strike; dip 55 degrees southeast.",
        "thickness_source": "Not stated in the MBS.",
        "accessibility_source": "Wadsa Railway Station; NH-353D, approaching through Nandwadi village; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; Bandia River and Jambia Nala.",
        "climate_source": "Mean annual rainfall 450 mm; source prints December temperature up to 42 C and June temperature up to 7 C (apparent seasonal-label anomaly retained).",
        "topography_source": "Hilly terrain and valleys.",
    },
    "IBM-IMYB2024-AUCTION-056": {
        "exploration_agency_source": "Directorate of Geology and Mining (DGM), Maharashtra.",
        "borehole_summary_source": "27 boreholes with cumulative meterage of 2,373.65 m at 200 m by 200 m spacing.",
        "mineral_source_mbs": "Limestone",
        "geological_resources_source": "Indicated resource (332): 43.15 million tonnes limestone, comprising 27.07 million tonnes cement grade and 16.08 million tonnes blendable cement grade.",
        "grade_source": "Cement grade: 45.39% CaO, 12.07% SiO2, 1.3% MgO; blendable grade: 38.13% CaO, 18.00% SiO2, 1.14% MgO.",
        "mineral_zones_source": "Stratified bedded deposit.",
        "dip_strike_source": "N55W strike; dip 30 degrees southwest.",
        "thickness_source": "Thickness varies from 2 m to 56 m.",
        "accessibility_source": "Warora and Chandrapur railway stations; SH-264; Nagpur Airport.",
        "hydrography_source": "Dendritic drainage; no river or stream is named.",
        "climate_source": "Mean annual rainfall 1,420 mm; temperature range 2.8-45 C; humidity described as very low.",
        "topography_source": "Linear ridges and undulating topography with isolated mounds and knolls.",
    },
    "IBM-IMYB2024-AUCTION-057": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "10 boreholes with cumulative meterage of 1,746.90 m at 200 m strike spacing.",
        "mineral_source_mbs": "Copper",
        "geological_resources_source": "1.13 million tonnes copper ore at 0.2% cut-off over about 1,400 m strike length; resource category 333.",
        "grade_source": "Average 0.39% Cu at 0.2% cut-off.",
        "mineral_zones_source": "Echelon, dilatational curvilinear quartz veins over a 3.0 km strike length.",
        "dip_strike_source": "Strike NNW-SSE to NNE-SSW.",
        "thickness_source": "Thickness 2-30 m.",
        "accessibility_source": "Sindewahi Railway Station about 15 km; block about 10 km from Navegaon via State Highway 09; Nagpur Airport about 210 km.",
        "hydrography_source": "Dendritic drainage; Human River, Kalvari Nallah, Bokardoh Nadi and Saoli Nadi.",
        "climate_source": "Mean annual rainfall 1,000-1,500 mm; December temperature 15 C; June temperature 48 C.",
        "topography_source": "Undulating, hilly terrain at about 180-240 m above mean sea level.",
    },
    "IBM-IMYB2024-AUCTION-058": {
        "exploration_agency_source": "Geological Survey of India.",
        "borehole_summary_source": "3 boreholes with cumulative meterage of 281.5 m.",
        "mineral_source_mbs": "Manganese ore; braunite with subordinate psilomelane and source-spelled 'pysolusite'.",
        "geological_resources_source": "0.065 million tonnes; resource category 334.",
        "grade_source": "Bedrock sample 0.74-22.24% Mn; 12 of 39 pit/trench samples 10.50-41.67% Mn, remaining samples below 5.35% Mn with 0.02-0.37% P2O5; 8 of 14 core samples 9.31-17.20% Mn, remaining samples below 1.2%.",
        "mineral_zones_source": "Three lensoid manganese-ore bodies controlled by the core of a tight isoclinal synclinal fold; two magnetic/gravity anomalies are described.",
        "dip_strike_source": "Trend N40-60W to S40-60E; dip 35-65 degrees south or southwest.",
        "thickness_source": "Thickness 7.4 m.",
        "accessibility_source": "Nagpur Railway Station; 12 km from NH-7; Nagpur Airport.",
        "hydrography_source": "Dendritic to sub-dendritic drainage; Pench River.",
        "climate_source": "Mean annual rainfall printed as 800 cm; December temperature 8-12 C; June temperature up to 47 C (source unit retained).",
        "topography_source": "Gentle undulating terrain.",
    },
    "IBM-IMYB2024-AUCTION-090": {
        "exploration_agency_source": "Directorate of Geology and Mining, Uttar Pradesh, Lucknow.",
        "mineral_source_mbs": "Gold and iron ore",
        "geological_resources_source": "Iron ore: 100 million tonnes of fines over 2.70 sq km; gold ore: 12.29 million tonnes over 2.35 sq km at 0.2 ppm cut-off.",
        "grade_source": "Gold 0.35 ppm at 0.2 ppm cut-off; hematite iron ore 30% Fe, approximately 90% lumps and 10% fines.",
        "borehole_summary_source": "Gold: 26 boreholes and 4,815.12 m; iron: 18 boreholes and 3,450.0 m.",
        "climate_source": "Mean annual rainfall 800-1300 mm; December temperature 6-14 C; May-June temperature 42.5-48 C.",
        "topography_source": "Rugged terrain.",
    },
    "IBM-IMYB2024-AUCTION-091": {
        "exploration_agency_source": "Geological Survey of India, Northern Region, Lucknow.",
        "mineral_source_mbs": "Iron ore",
        "geological_resources_source": "14.89 million tonnes inferred iron ore resource over 7.9 ha.",
        "grade_source": "Average 34.73% Fe at 30% Fe cut-off; approximately 90% lumps and 10% fines.",
        "climate_source": "Mean annual rainfall 125 cm; temperature 30-46 C; source also prints average 25 C.",
        "topography_source": "Rugged terrain.",
    },
    "IBM-IMYB2024-AUCTION-092": {
        "exploration_agency_source": "Geological Survey of India, Northern Region, Lucknow.",
        "mineral_source_mbs": "Gold",
        "geological_resources_source": "52,806.25 tonnes inferred gold-ore resource over 16.8 ha in sub-block H.",
        "grade_source": "Average 3.03 g/t Au at 0.5 g/t cut-off.",
        "climate_source": "Mean annual rainfall 110-115 cm; December temperature 5-28 C; May-June temperature 24-41 C.",
        "topography_source": "Rugged terrain.",
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

# Coordinate evidence is inventoried independently of geometry admission so a
# reviewed MBS remains useful even when its boundary cannot be published.
COORDINATE_REVIEW = {
    "IBM-IMYB2024-AUCTION-006": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-007": ("ordered_boundary_vertices", [1], ["ibm_mbs_area_conflict"]),
    "IBM-IMYB2024-AUCTION-008": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-009": ("ordered_boundary_vertices_with_source_error", [1], ["malformed_latitude_seconds_points_F_G"]),
    "IBM-IMYB2024-AUCTION-010": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-011": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-012": ("ordered_boundary_vertices", [2], []),
    "IBM-IMYB2024-AUCTION-013": ("ordered_boundary_vertices", [4], []),
    "IBM-IMYB2024-AUCTION-014": ("ordered_boundary_vertices", [3], []),
    "IBM-IMYB2024-AUCTION-015": (
        "ordered_boundary_vertices_with_source_error",
        [4, 5],
        ["longitude_outlier_bp5", "ibm_mbs_area_conflict"],
    ),
    "IBM-IMYB2024-AUCTION-016": ("ordered_boundary_vertices", [3], ["ibm_mbs_area_conflict"]),
    "IBM-IMYB2024-AUCTION-017": ("ordered_boundary_vertices", [4, 5], ["ibm_mbs_area_conflict"]),
    "IBM-IMYB2024-AUCTION-018": ("ordered_boundary_vertices_with_source_error", [1, 2, 3, 4], ["latitude_hemisphere_printed_E_points_J3_K"]),
    "IBM-IMYB2024-AUCTION-019": ("bounding_extents_only", [1], ["no_ordered_boundary_vertices"]),
    "IBM-IMYB2024-AUCTION-020": ("bounding_extents_only", [1], ["no_ordered_boundary_vertices"]),
    "IBM-IMYB2024-AUCTION-021": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-022": ("ordered_boundary_vertices_with_source_error", [1], ["latitude_seconds_point_C_printed_as_60"]),
    "IBM-IMYB2024-AUCTION-023": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-024": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-025": ("ordered_boundary_vertices", [1], ["quantity_row_mineral_label_conflicts_with_bauxite_title_and_grade_text"]),
    "IBM-IMYB2024-AUCTION-026": ("ordered_boundary_vertices_with_source_omission", [1], ["hemisphere_markers_not_printed"]),
    "IBM-IMYB2024-AUCTION-027": ("ordered_boundary_vertices", [3, 4, 5, 6, 7], ["source_order_polygon_invalid", "computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-028": ("ordered_boundary_vertices", [4, 5, 6, 7, 8, 9, 10], ["ibm_mbs_area_difference_within_5pct", "source_alternate_dgps_area_102_894_ha"]),
    "IBM-IMYB2024-AUCTION-029": ("ordered_boundary_vertices", [4], []),
    "IBM-IMYB2024-AUCTION-030": ("ordered_boundary_vertices", [4, 5, 6], ["ibm_mbs_area_conflict"]),
    "IBM-IMYB2024-AUCTION-031": ("ordered_boundary_vertices", [4, 5], ["footprint_not_fully_covered_by_2011_state_boundary"]),
    "IBM-IMYB2024-AUCTION-032": ("ordered_boundary_vertices", [4, 5, 6], ["source_order_polygon_invalid", "computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-033": ("ordered_boundary_vertices", [3], []),
    "IBM-IMYB2024-AUCTION-034": ("ordered_boundary_vertices", [4], ["source_order_polygon_invalid"]),
    "IBM-IMYB2024-AUCTION-035": ("ordered_boundary_vertices", [4], []),
    "IBM-IMYB2024-AUCTION-036": ("ordered_boundary_vertices", [4, 5, 6, 7], []),
    "IBM-IMYB2024-AUCTION-037": ("ordered_boundary_vertices", [4], ["coordinate_table_image_only_manual_visual_transcription"]),
    "IBM-IMYB2024-AUCTION-038": ("ordered_boundary_vertices", [1], ["mbs_internal_area_values_913_3954_and_948_ha", "computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-039": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-040": ("ordered_boundary_vertices", [1], ["source_alternate_georeferenced_area_798_72_ha"]),
    "IBM-IMYB2024-AUCTION-041": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-042": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-043": ("ordered_boundary_vertices", [1], ["source_alternate_georeferenced_area_462_5319_ha"]),
    "IBM-IMYB2024-AUCTION-044": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-045": ("ordered_boundary_vertices", [5], ["source_pdf_filename_labels_limestone_while_document_content_is_iron_ore", "computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-046": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-047": ("ordered_boundary_vertices", [4, 5], ["source_order_polygon_invalid", "source_alternate_dgps_area_5_6664_ha", "computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-048": ("ordered_boundary_vertices", [1], ["source_revenue_area_37_5_ha_and_geological_report_area_35_ha"]),
    "IBM-IMYB2024-AUCTION-049": ("bounding_extents_only", [1], ["ordered_vertices_only_in_unincluded_cadastral_plate_A"]),
    "IBM-IMYB2024-AUCTION-050": ("ordered_boundary_vertices", [1], ["temperature_season_values_appear_reversed"]),
    "IBM-IMYB2024-AUCTION-051": ("ordered_boundary_vertices", [1], ["temperature_season_values_appear_reversed"]),
    "IBM-IMYB2024-AUCTION-052": ("ordered_boundary_vertices", [1], ["temperature_season_values_appear_reversed"]),
    "IBM-IMYB2024-AUCTION-053": ("ordered_boundary_vertices", [1], ["temperature_season_values_appear_reversed"]),
    "IBM-IMYB2024-AUCTION-054": ("bounding_extents_only", [1], ["no_ordered_boundary_vertices", "mean_annual_rainfall_printed_600_cm"]),
    "IBM-IMYB2024-AUCTION-055": ("ordered_boundary_vertices", [1], ["temperature_season_values_appear_reversed"]),
    "IBM-IMYB2024-AUCTION-056": ("ordered_boundary_vertices", [1], ["computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-057": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-058": ("ordered_boundary_vertices", [1], ["mean_annual_rainfall_printed_800_cm"]),
    "IBM-IMYB2024-AUCTION-090": ("ordered_boundary_vertices", [1], ["published_and_computed_area_conflicts"]),
    "IBM-IMYB2024-AUCTION-091": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-092": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-093": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-094": ("ordered_boundary_vertices", [1], ["computed_area_differs_from_mbs_area_gt_5pct"]),
    "IBM-IMYB2024-AUCTION-095": ("ordered_boundary_vertices", [1], []),
    "IBM-IMYB2024-AUCTION-096": ("ordered_boundary_vertices", [1], ["source_point_id_6_absent", "utm_final_northing_inconsistent"]),
    "IBM-IMYB2024-AUCTION-097": ("ordered_boundary_vertices", [1, 2, 3], []),
}

GEOMETRY_WITHHOLD_DECISIONS = {
    "IBM-IMYB2024-AUCTION-007": (
        "withheld_source_conflict",
        "IBM publishes 600 ha while the matched MBS publishes 670 ha; geometry withheld pending source reconciliation.",
    ),
    "IBM-IMYB2024-AUCTION-015": (
        "withheld_source_conflict",
        "The MBS boundary table prints BP-5 at 69 degrees 18 minutes 51.72 seconds E among vertices near 69 degrees 15-16 minutes E, creating an invalid polygon; IBM also publishes 29.17 ha while the MBS publishes 5.3152 ha. Geometry withheld rather than correcting either source by inference.",
    ),
    "IBM-IMYB2024-AUCTION-016": (
        "withheld_source_conflict",
        "IBM publishes 29.17 ha while the matched MBS publishes 41.3186 ha; geometry withheld pending source reconciliation.",
    ),
    "IBM-IMYB2024-AUCTION-017": (
        "withheld_source_conflict",
        "IBM publishes 29.17 ha while the matched MBS publishes 6.2265 ha; geometry withheld pending source reconciliation.",
    ),
    "IBM-IMYB2024-AUCTION-009": (
        "withheld_source_conflict",
        "The matched MBS prints malformed latitude seconds for points F and G ('34.4.00'); geometry withheld rather than corrected by inference.",
    ),
    "IBM-IMYB2024-AUCTION-018": (
        "withheld_source_conflict",
        "The MBS latitude column prints an E hemisphere at boundary points J3 and K; geometry withheld rather than corrected to N by inference.",
    ),
    "IBM-IMYB2024-AUCTION-019": (
        "withheld_insufficient_coordinate_detail",
        "The MBS publishes latitude/longitude extents but no ordered boundary vertices; no concession polygon is inferred from the bounding rectangle.",
    ),
    "IBM-IMYB2024-AUCTION-020": (
        "withheld_insufficient_coordinate_detail",
        "The MBS publishes latitude/longitude extents but no ordered boundary vertices; no concession polygon is inferred from the bounding rectangle.",
    ),
    "IBM-IMYB2024-AUCTION-022": (
        "withheld_source_conflict",
        "The MBS prints 60.00 seconds in the latitude of point C; geometry withheld rather than normalizing the malformed coordinate by inference.",
    ),
    "IBM-IMYB2024-AUCTION-026": (
        "withheld_source_conflict",
        "The MBS coordinate table omits hemisphere markers; geometry withheld rather than inferring N/E signs from the block's location.",
    ),
    "IBM-IMYB2024-AUCTION-030": (
        "withheld_source_conflict",
        "IBM publishes 378.404 ha while the visually matched Phase-XI MBS publishes 332.654 ha; geometry withheld pending source reconciliation.",
    ),
    "IBM-IMYB2024-AUCTION-049": (
        "withheld_insufficient_coordinate_detail",
        "The MBS publishes latitude/longitude extents and says detailed coordinates are in an unincluded cadastral plate; no concession polygon is inferred from the bounding rectangle.",
    ),
    "IBM-IMYB2024-AUCTION-054": (
        "withheld_insufficient_coordinate_detail",
        "The MBS publishes latitude/longitude extents but no ordered boundary vertices; no concession polygon is inferred from the bounding rectangle.",
    ),
}

COORDINATE_DATUM_SOURCE = {
    "IBM-IMYB2024-AUCTION-012": "Not stated; source publishes UTM and geographic coordinate columns",
    "IBM-IMYB2024-AUCTION-021": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-023": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-024": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-025": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-026": "WGS 84",
    "IBM-IMYB2024-AUCTION-050": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-051": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-052": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-053": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-055": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-056": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-057": "Not stated; source publishes geographic DMS boundary points",
    "IBM-IMYB2024-AUCTION-058": "Not stated; source publishes geographic DMS boundary points",
}

COORDINATE_DATUM_SOURCE.update({
    f"IBM-IMYB2024-AUCTION-{number:03d}":
        "Not stated in the selected MBS; published N/E geographic coordinates encoded as EPSG:4326 for distribution"
    for number in range(27, 49)
})


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


def select_document(record_id: str, candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    expected_file_id = CURATED_FILE_ID_OVERRIDES.get(record_id)
    if expected_file_id:
        selected = [doc for doc in candidates if doc["file_id"] == expected_file_id]
        if len(selected) != 1:
            raise ValueError(
                f"{record_id} expected reviewed MSTC file {expected_file_id}, "
                f"found {[doc['file_id'] for doc in candidates]}"
            )
        return selected[0]
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
    # One reviewed Phase-XI MP PDF contains a large compressed page stream.
    # Raising the decompression ceiling permits text extraction without
    # changing the PDF bytes or substituting OCR for text-bearing pages.
    pypdf_filters.ZLIB_MAX_OUTPUT_LENGTH = max(
        pypdf_filters.ZLIB_MAX_OUTPUT_LENGTH, 250_000_000
    )
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


MP_PHASE_XI_TEXT_GEOMETRIES = {
    "IBM-IMYB2024-AUCTION-027": 376,
    "IBM-IMYB2024-AUCTION-028": 617,
    "IBM-IMYB2024-AUCTION-029": 20,
    "IBM-IMYB2024-AUCTION-030": 130,
    "IBM-IMYB2024-AUCTION-031": 53,
    "IBM-IMYB2024-AUCTION-032": 234,
    "IBM-IMYB2024-AUCTION-033": 49,
    "IBM-IMYB2024-AUCTION-034": 73,
    "IBM-IMYB2024-AUCTION-035": 40,
    "IBM-IMYB2024-AUCTION-036": 228,
    "IBM-IMYB2024-AUCTION-045": 44,
    "IBM-IMYB2024-AUCTION-047": 117,
}

MP_STANDARD_DMS_ROW = re.compile(
    r"(?<![\d.])(\d{1,3})\s+(2[1-6])\s+(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)"
    r"\s+(7[4-9]|8[0-2])\s+(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?![\d.])"
)
MP_PIPARTOLA_ROW = re.compile(
    r"(?<![\d.])(\d{1,2})\s+[\d.]+m\s+[\d.]+m\s+"
    r"(7[4-9]|8[0-2])°\s*(\d{1,2})'\s*([\d.]+)\"\s+"
    r"(2[1-6])°\s*(\d{1,2})'\s*([\d.]+)\""
)
MP_LINGAPONAR_ROW = re.compile(
    r"TP-(\d{1,2})\s+[\d.]+\s+[\d.]+\s+"
    r"(2[1-6])\s+(\d{1,2})\s+([\d.]+)\s+"
    r"(7[4-9]|8[0-2])\s+(\d{1,2})\s+([\d.]+)"
)
MP_PAHARI_ROW = re.compile(
    r"(?<![\d.])(\d{1,3})\s+N0?(2[1-6])°\s*(\d{1,2})'\s*([\d.]+)\"\s+"
    r"E0?(7[4-9]|8[0-2])°\s*(\d{1,2})'\s*([\d.]+)\""
)


def extract_mp_phase_xi_points(
    record_id: str, pages: list[str]
) -> tuple[list[tuple[float, float]], list[int], list[int]]:
    """Parse a reviewed Phase-XI geographic table with exact ID checks."""
    configured_pages = COORDINATE_REVIEW[record_id][1]
    points: dict[int, tuple[float, float]] = {}

    def add_point(point_id: str, lat: tuple[str, str, str], lon: tuple[str, str, str]) -> None:
        identifier = int(point_id)
        if identifier in points:
            raise ValueError(f"{record_id} duplicate boundary point {identifier}")
        points[identifier] = (
            dms(float(lon[0]), float(lon[1]), float(lon[2])),
            dms(float(lat[0]), float(lat[1]), float(lat[2])),
        )

    for page_number in configured_pages:
        for line in pages[page_number - 1].splitlines():
            if record_id == "IBM-IMYB2024-AUCTION-029":
                for match in MP_PIPARTOLA_ROW.finditer(line):
                    point, lon_d, lon_m, lon_s, lat_d, lat_m, lat_s = match.groups()
                    add_point(point, (lat_d, lat_m, lat_s), (lon_d, lon_m, lon_s))
            elif record_id == "IBM-IMYB2024-AUCTION-035":
                for match in MP_LINGAPONAR_ROW.finditer(line):
                    point, lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = match.groups()
                    add_point(point, (lat_d, lat_m, lat_s), (lon_d, lon_m, lon_s))
            elif record_id == "IBM-IMYB2024-AUCTION-028":
                for match in MP_PAHARI_ROW.finditer(line):
                    point, lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = match.groups()
                    add_point(point, (lat_d, lat_m, lat_s), (lon_d, lon_m, lon_s))
            else:
                for match in MP_STANDARD_DMS_ROW.finditer(line):
                    point, lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = match.groups()
                    add_point(point, (lat_d, lat_m, lat_s), (lon_d, lon_m, lon_s))

    expected_count = MP_PHASE_XI_TEXT_GEOMETRIES[record_id]
    ids = sorted(points)
    expected_ids = list(range(1, expected_count + 1))
    if ids != expected_ids:
        missing = sorted(set(expected_ids) - set(ids))
        extra = sorted(set(ids) - set(expected_ids))
        raise ValueError(
            f"{record_id} boundary IDs do not match 1..{expected_count}; "
            f"missing={missing}, extra={extra}"
        )
    return [points[point_id] for point_id in ids], ids, configured_pages


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
        for state in {"Chhattisgarh", "Goa", "Gujarat", "Jharkhand", "Karnataka", "Madhya Pradesh", "Maharashtra", "Uttar Pradesh"}
    }


def build_geometry(
    row: dict[str, str], pages: list[str], state_shapes: dict[str, object]
) -> tuple[dict | None, dict]:
    record_id = row["record_id"]
    if record_id in GEOMETRY_WITHHOLD_DECISIONS:
        status, reason = GEOMETRY_WITHHOLD_DECISIONS[record_id]
        return None, {
            "geometry_admission_status": status,
            "geometry_admission_reason": reason,
        }

    if record_id in DMS_GEOMETRIES:
        coordinates = DMS_GEOMETRIES[record_id]
        source_pages = COORDINATE_REVIEW[record_id][1]
        point_ids = DMS_POINT_IDS.get(record_id, list(range(1, len(coordinates) + 1)))
        quality_flags = []
        if COORDINATE_DATUM_SOURCE.get(record_id, "WGS 84").startswith("Not stated"):
            coordinate_method = "source_table_visual_transcription_geographic_dms_encoded_epsg4326"
            quality_flags.append("source_coordinate_datum_not_stated")
        else:
            coordinate_method = "source_table_visual_transcription_dms_wgs84"
        if record_id == "IBM-IMYB2024-AUCTION-096":
            quality_flags.append("source_point_id_6_absent")
        if record_id == "IBM-IMYB2024-AUCTION-041":
            coordinate_method = "source_table_visual_transcription_decimal_degrees_encoded_epsg4326"
    elif record_id in MP_PHASE_XI_TEXT_GEOMETRIES:
        coordinates, point_ids, source_pages = extract_mp_phase_xi_points(record_id, pages)
        coordinate_method = "reviewed_source_table_text_extraction_geographic_dms_encoded_epsg4326"
        quality_flags = []
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

    for flag in COORDINATE_REVIEW[record_id][2]:
        if flag not in quality_flags:
            quality_flags.append(flag)

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
        "limitations": "Alpha.15 reviews 66 of 97 IBM rows: 61 selected State MBS PDFs and five Andhra Pradesh exact-name searches with no match in the current public index. The 22 Madhya Pradesh matches are pinned to the browser-verified Phase-XI file identifiers so later same-name auction uploads cannot silently replace the historical tranche. Mine Block Summaries describe auction-stage technical context and do not independently prove current operation, present legal status, access permission or reserve classification. Source conflicts and failed geometry checks are withheld, not repaired by inference.",
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
        "review_scope": "Whether this IBM row received curated document review in alpha.15.",
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
        "coordinate_evidence_type": "Reviewed coordinate evidence class: ordered boundary vertices, ordered vertices with a source defect, or bounding extents only.",
        "coordinate_review_flags_json": "JSON array of coordinate-table defects, insufficiencies or area conflicts recorded during visual review.",
        "normalized_material_names_json": "JSON array of normalized material English names linked from the IBM source wording.",
        "chemical_or_english_names_json": "JSON array using chemical names where defensible and English names otherwise.",
        "formulae_or_symbols_json": "JSON array of defensible element symbols or material formulae; empty when no single formula applies.",
        "geometry_admission_status": "Whether the source footprint passed the alpha.15 spatial publication gates.",
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
        "model_evidence_role": "Context only in alpha.15; rows do not enter training, labels, scoring or candidate promotion.",
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
    report["development_release_version"] = "v1.0-alpha.15"
    report["ibm_auction_mbs_geometry_2023_24"] = {
        "ibm_input_rows": validation["ibm_input_rows"],
        "state_portal_documents_total": validation["state_portal_documents_total"],
        "curated_records": validation["curated_records"],
        "selected_document_matches": validation["selected_document_matches"],
        "reviewed_profile_complete_rows": validation["reviewed_profile_complete_rows"],
        "coordinate_evidence_type_counts": validation["coordinate_evidence_type_counts"],
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
    profile_fields = [
        "exploration_level", "borehole_count", "drilled_meterage_m", "exploration_agency_source",
        "borehole_summary_source", "mineral_source_mbs", "geological_resources_source", "grade_source",
        "mineral_zones_source", "dip_strike_source", "thickness_source", "accessibility_source",
        "hydrography_source", "climate_source", "topography_source",
    ]

    for row in rows:
        record_id = row["record_id"]
        candidates = candidate_documents(row, inventory)
        selected = select_document(record_id, candidates)
        no_current_mbs_reason = REVIEWED_NO_CURRENT_MBS.get(record_id)
        match = {
            "record_id": record_id,
            "state_or_ut": row["state_or_ut"],
            "block_name": row["block_name"],
            "mineral_source": row["mineral_source"],
            "normalized_material_ids_json": row["normalized_material_ids_json"],
            "normalized_material_names_json": row["normalized_material_names_json"],
            "chemical_or_english_names_json": row["chemical_or_english_names_json"],
            "formulae_or_symbols_json": row["formulae_or_symbols_json"],
            "auction_date": row["auction_date"],
            "concession_type_code": row["concession_type_code"],
            "ibm_area_ha": row["area_ha"],
            "review_scope": "curated_alpha_15" if record_id in CURATED_MATCHES else "not_reviewed_alpha_15",
            "curated_candidate_count": len(candidates),
            "document_selection_rule": "pinned_reviewed_mstc_phase_xi_file_id" if record_id in CURATED_FILE_ID_OVERRIDES and selected else "highest_numeric_mstc_file_id" if len(candidates) > 1 else "unique_curated_name_match" if selected else "record_specific_exact_name_search_current_public_state_mbs_index" if no_current_mbs_reason else "",
            "document_match_status": "selected_curated_name_match" if selected else "reviewed_no_current_public_mbs_match" if no_current_mbs_reason else "not_reviewed_in_this_release",
            "selected_mbs_file_id": "",
            "selected_mbs_title": "",
            "selected_mbs_url": "",
            "selected_mbs_pdf_sha256": "",
            "selected_mbs_pdf_bytes": "",
            "selected_mbs_pdf_page_count": "",
            "mbs_area_ha": MBS_AREA_HA.get(record_id, ""),
            "ibm_to_mbs_area_difference_pct": "",
            "coordinate_evidence_type": "",
            "coordinate_source_pdf_pages_json": "",
            "coordinate_review_flags_json": "",
            **{key: "" for key in profile_fields},
            "geometry_admission_status": "withheld_no_public_boundary_document" if no_current_mbs_reason else "withheld_not_reviewed",
            "geometry_admission_reason": no_current_mbs_reason or "No curated document match was reviewed in this release.",
            "source_portal_url": PORTAL_INDEX,
            "source_access_date": inventory["access_date"],
            "current_legal_or_operational_status_verified": False,
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

        evidence_type, evidence_pages, evidence_flags = COORDINATE_REVIEW[record_id]
        profile = source_profile(pages)
        profile.update(PROFILE_TEXT.get(record_id, {}))
        numeric_profile = PROFILE_NUMBERS[record_id]
        match.update({
            "coordinate_evidence_type": evidence_type,
            "coordinate_source_pdf_pages_json": json.dumps(evidence_pages),
            "coordinate_review_flags_json": json.dumps(evidence_flags),
            **numeric_profile,
            **profile,
        })

        geometry, diagnostics = build_geometry(row, pages, state_shapes)
        if geometry is None:
            match.update({
                "geometry_admission_status": diagnostics["geometry_admission_status"],
                "geometry_admission_reason": diagnostics["geometry_admission_reason"],
            })
            match_rows.append(match)
            continue

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
            "coordinate_datum_source": COORDINATE_DATUM_SOURCE.get(record_id, "WGS 84"),
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
        "normalized_material_names_json", "chemical_or_english_names_json", "formulae_or_symbols_json",
        "auction_date", "concession_type_code", "ibm_area_ha", "review_scope", "curated_candidate_count",
        "document_selection_rule", "document_match_status", "selected_mbs_file_id", "selected_mbs_title",
        "selected_mbs_url", "selected_mbs_pdf_sha256", "selected_mbs_pdf_bytes", "selected_mbs_pdf_page_count",
        "mbs_area_ha", "ibm_to_mbs_area_difference_pct", "coordinate_evidence_type",
        "coordinate_source_pdf_pages_json", "coordinate_review_flags_json", *profile_fields,
        "geometry_admission_status", "geometry_admission_reason", "source_portal_url", "source_access_date",
        "current_legal_or_operational_status_verified", "model_evidence_role", "model_exclusion_reason",
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
    reviewed_rows = [row for row in match_rows if row["selected_mbs_file_id"]]
    coordinate_evidence_counts: dict[str, int] = {}
    for row in reviewed_rows:
        evidence_type = row["coordinate_evidence_type"]
        coordinate_evidence_counts[evidence_type] = coordinate_evidence_counts.get(evidence_type, 0) + 1
    required_profile_fields = [
        "exploration_level", "mineral_source_mbs", "geological_resources_source", "grade_source",
        "climate_source", "coordinate_evidence_type", "coordinate_source_pdf_pages_json",
    ]
    reviewed_profile_complete_rows = sum(
        all(row[field] != "" for field in required_profile_fields) for row in reviewed_rows
    )
    validation = {
        "release": "v1.0-alpha.15",
        "source_portal_url": PORTAL_INDEX,
        "source_access_date": inventory["access_date"],
        "ibm_input_rows": len(rows),
        "state_portal_document_counts": {
            state: value["document_count"] for state, value in inventory["states"].items()
        },
        "state_portal_documents_total": sum(value["document_count"] for value in inventory["states"].values()),
        "curated_records": len(CURATED_MATCHES),
        "selected_document_matches": sum(bool(row["selected_mbs_file_id"]) for row in match_rows),
        "reviewed_profile_complete_rows": reviewed_profile_complete_rows,
        "coordinate_evidence_type_counts": coordinate_evidence_counts,
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
            "This release reviews 66 of the 97 IBM Table 5 records: 61 selected State MBS PDFs and five Andhra Pradesh exact-name searches with no match in the current public index.",
            "The 22 Madhya Pradesh rows are matched to the browser-verified Phase-XI tranche with pinned MSTC file identifiers; later same-name uploads are not substituted.",
            "The five Andhra Pradesh rows are withheld from geometry because no public boundary document was found in the current State MBS index; their dated official-secondary status evidence is published separately.",
            "Katni, Dhamani Nana and Katangjhari source-order boundaries form invalid polygons; Pindrai is also invalid and has a material coordinate-derived area mismatch. These geometries are withheld rather than reordered or repaired.",
            "Chorgadi-Puraina is withheld because IBM publishes 378.404 ha while the Phase-XI MBS publishes 332.654 ha.",
            "Bamanbardi and Siluwa-Jhansi are withheld because coordinate-derived areas exceed the MBS areas by 5.24% and 5.12%, respectively.",
            "Bhilapar is admitted with a flag because its footprint is not fully covered by the dissolved 2011 district-derived Madhya Pradesh boundary, while its centroid and area checks pass.",
            "Bamanbardi and East of Dabri each print internally inconsistent annual-rainfall values (871 mm and 280 cm); both values and the conflict are retained.",
            "The Siluwa-Jhansi source filename labels the document as limestone even though the PDF title and technical content identify iron ore; the anomaly is retained.",
            "Devalmari-Katepalli and South Padve publish bounding extents but no ordered boundary vertices in the selected MBS PDFs; no rectangles are inferred.",
            "Kondhala geometry is withheld because its source-order coordinates compute to about 162.74 ha versus the MBS-published 105 ha.",
            "The Surjagad MBS documents print December temperature up to 42 C and June temperature up to 7 C; the apparent seasonal-label anomaly is retained and flagged.",
            "South Padve and Savali print annual rainfall as 600 cm and 800 cm respectively; these source units are retained and flagged rather than silently corrected.",
            "Kareli-Chandi geometry is withheld because the MBS prints malformed latitude seconds for two vertices.",
            "Saloni geometry is withheld because IBM and MBS publish materially different areas.",
            "Chiropat geometry is withheld because the MBS prints an E hemisphere in the latitude column for two vertices.",
            "Baraiburu-Tatiba and Meralgara-Barabaljori publish bounding extents but no ordered boundary vertices.",
            "Girar geometry is withheld because IBM, MBS and coordinate-derived areas do not reconcile within 5%.",
            "Goa Block VI geometry is withheld because the source coordinates compute to an area 25.31% below the MBS published area.",
            "Timmanahalli geometry is withheld because one source latitude prints 60.00 seconds.",
            "Kudarka geometry is withheld because the source coordinate table omits hemisphere markers.",
            "Nandana geometry is withheld because the source boundary table contains a longitude outlier and its IBM and MBS areas also conflict materially.",
            "Kodidra and Virpur-Lusari geometries are withheld because IBM and the exact-title MBS documents publish materially different areas.",
            "Niddodi is retained with an explicit source anomaly because its bauxite title and Al2O3 grade text conflict with an 'Iron ore' label in the quantity row.",
            "The 2011 district boundary layer is used only as a state-containment diagnostic and is not a current administrative register.",
            "MBS technical context and IBM auction reporting do not independently establish current operation or present legal status.",
        ],
    }
    validation["checks_pass"] = bool(
        validation["ibm_input_rows"] == 97
        and validation["curated_records"] == 66
        and validation["selected_document_matches"] == 61
        and validation["reviewed_profile_complete_rows"] == 61
        and validation["coordinate_evidence_type_counts"] == {
            "ordered_boundary_vertices": 52,
            "ordered_boundary_vertices_with_source_error": 4,
            "bounding_extents_only": 4,
            "ordered_boundary_vertices_with_source_omission": 1,
        }
        and validation["published_geometries"] == 39
        and validation["geometry_admission_status_counts"] == {
            "withheld_not_reviewed": 31,
            "withheld_no_public_boundary_document": 5,
            "admitted_authoritative_source_footprint": 39,
            "withheld_source_conflict": 9,
            "withheld_insufficient_coordinate_detail": 4,
            "withheld_validation_failure": 9,
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
        selected = select_document(row["record_id"], candidates)
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
