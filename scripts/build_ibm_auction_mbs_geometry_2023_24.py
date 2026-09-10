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
    "IBM-IMYB2024-AUCTION-090": r"\bphase\s*4\b.*\bgirar\b.*\biron\b.*\bgold\b",
    "IBM-IMYB2024-AUCTION-091": r"\bphase\s*4\b.*\bbharhari\b.*\biron\b",
    "IBM-IMYB2024-AUCTION-092": r"\bphase\s*4\b.*\bsona\s*pahari\b.*\bgold\b",
    "IBM-IMYB2024-AUCTION-093": r"(?:block\s*)?(?:v|5).*advalpale.*thivim|advalpale.*thivim",
    "IBM-IMYB2024-AUCTION-094": r"(?:block\s*)?(?:vi|6).*cudnem.*cormolem|cudnem.*cormolem",
    "IBM-IMYB2024-AUCTION-095": r"(?:block\s*)?(?:vii|7).*cudnem\b|\bcudnem\b.*(?:block\s*)?(?:vii|7)",
    "IBM-IMYB2024-AUCTION-096": r"(?:block\s*)?(?:viii|8).*thivim.*pirna|thivim.*pirna",
    "IBM-IMYB2024-AUCTION-097": r"(?:block\s*)?(?:ix|9).*surla.*sonshi|surla.*sonshi",
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
}

COORDINATE_DATUM_SOURCE = {
    "IBM-IMYB2024-AUCTION-012": "Not stated; source publishes UTM and geographic coordinate columns",
    "IBM-IMYB2024-AUCTION-021": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-023": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-024": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-025": "Not stated; source labels DGPS latitude/longitude",
    "IBM-IMYB2024-AUCTION-026": "WGS 84",
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
        for state in {"Chhattisgarh", "Goa", "Gujarat", "Jharkhand", "Karnataka", "Uttar Pradesh"}
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
        "limitations": "Alpha.13 reviews 34 of 97 IBM rows: 29 selected State MBS PDFs and five Andhra Pradesh exact-name searches with no match in the current public index. Mine Block Summaries describe auction-stage technical context and do not independently prove current operation, present legal status, access permission or reserve classification. Source conflicts and missing public boundary documents are withheld, not repaired by inference.",
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
        "review_scope": "Whether this IBM row received curated document review in alpha.13.",
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
        "geometry_admission_status": "Whether the source footprint passed the alpha.13 spatial publication gates.",
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
        "model_evidence_role": "Context only in alpha.13; rows do not enter training, labels, scoring or candidate promotion.",
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
    report["development_release_version"] = "v1.0-alpha.13"
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
        selected = select_latest(candidates)
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
            "review_scope": "curated_alpha_13" if record_id in CURATED_MATCHES else "not_reviewed_alpha_13",
            "curated_candidate_count": len(candidates),
            "document_selection_rule": "highest_numeric_mstc_file_id" if len(candidates) > 1 else "unique_curated_name_match" if selected else "record_specific_exact_name_search_current_public_state_mbs_index" if no_current_mbs_reason else "",
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
        "release": "v1.0-alpha.13",
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
            "This release reviews 34 of the 97 IBM Table 5 records: 29 selected State MBS PDFs and five Andhra Pradesh exact-name searches with no match in the current public index.",
            "The five Andhra Pradesh rows are withheld from geometry because no public boundary document was found in the current State MBS index; their dated official-secondary status evidence is published separately.",
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
        and validation["curated_records"] == 34
        and validation["selected_document_matches"] == 29
        and validation["reviewed_profile_complete_rows"] == 29
        and validation["coordinate_evidence_type_counts"] == {
            "ordered_boundary_vertices": 22,
            "ordered_boundary_vertices_with_source_error": 4,
            "bounding_extents_only": 2,
            "ordered_boundary_vertices_with_source_omission": 1,
        }
        and validation["published_geometries"] == 17
        and validation["geometry_admission_status_counts"] == {
            "withheld_not_reviewed": 63,
            "withheld_no_public_boundary_document": 5,
            "admitted_authoritative_source_footprint": 17,
            "withheld_source_conflict": 8,
            "withheld_insufficient_coordinate_detail": 2,
            "withheld_validation_failure": 2,
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
