#!/usr/bin/env python3
"""Build auditable IBM 2024 mining-lease and auction-concession context tables.

The source is the Indian Minerals Yearbook 2024 chapter "Status of Mineral
Concession in India".  Tables 1--4 are aggregate distributions and Table 5 is
a block-name inventory of concessions described by IBM as granted through
auction during 2023-24.  The chapter does not publish coordinates, polygons,
current operating status, production, reserves, or a controlling legal-status
record for the Table 5 blocks.  All rows are therefore context-only and are
excluded from KHANAN prospectivity training and scoring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw" / "ibm_mineral_concessions_2024" / "FINAL_IMYB2024_as_on_21.01.2026.pdf"
OUT = ROOT / "outputs"
AGGREGATE_OUTPUT = OUT / "india_ibm_mining_lease_distribution_2024.csv"
AUCTION_OUTPUT = OUT / "india_ibm_auctioned_mineral_concessions_2023_24.csv"
VALIDATION_OUTPUT = OUT / "ibm_mineral_concessions_2024_validation.json"

SOURCE_ID = "SRC_IBM_INDIAN_MINERALS_YEARBOOK_2024_CONCESSIONS"
SOURCE_URL = "https://ibm.gov.in/writereaddata/files/17690756386971f3b675b8aFINAL_IMYB2024_as_on_21.01.2026.pdf"
SOURCE_DOCUMENT_SHA256 = "5b3208e019f95f8976bdb1e7dd7e7dcebba41af78e149ba162a97c98cc070ded"
SOURCE_ACCESS_DATE = "2026-09-10"
RELEASE_VERSION = "v1.0-alpha.8"
SCOPE_EXCLUSIONS = [
    "atomic_minerals",
    "coal",
    "lignite",
    "petroleum",
    "natural_gas",
    "minor_minerals",
]

SOURCE_REGISTRY_ROW = {
    "source_id": SOURCE_ID,
    "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
    "title": "Indian Minerals Yearbook 2024 — Status of Mineral Concession in India",
    "release_or_reference_date": "2024 reporting year; PDF created 2026-01-21; lease status provisional as at 2024-03-31",
    "url": SOURCE_URL,
    "download_url": SOURCE_URL,
    "license_or_access_note": "Government of India public PDF; retain attribution and verify current IBM website reuse terms.",
    "used_for": "Authoritative national/state/mineral/sector/area-band mining-lease aggregates and the published 2023-24 list of 97 mining leases or composite licences granted through auction.",
    "limitations": "Tables exclude atomic minerals, coal, lignite, petroleum, natural gas and minor minerals. Aggregate rows are non-spatial. Table 5 publishes block names, state, mineral, auction date, concession type and usually area, but no coordinates, polygons, bidder, production, reserves, controlling current legal status or operating status. IBM prints an unparseable 'n' for the Himachal Pradesh 2024 lease count; KHANAN preserves it and leaves the numeric value blank.",
}


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_source(refresh: bool) -> bytes:
    if refresh or not RAW.exists():
        response = requests.get(
            SOURCE_URL,
            headers={"User-Agent": "Mozilla/5.0 (KHANAN reproducible public-data builder)"},
            timeout=(20, 180),
        )
        response.raise_for_status()
        body = response.content
        if not body.startswith(b"%PDF-") or len(body) < 5_000_000:
            raise RuntimeError("IBM yearbook download did not pass PDF content checks")
        RAW.parent.mkdir(parents=True, exist_ok=True)
        part = RAW.with_suffix(RAW.suffix + ".part")
        part.write_bytes(body)
        os.replace(part, RAW)
    body = RAW.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != SOURCE_DOCUMENT_SHA256:
        raise RuntimeError(f"IBM yearbook SHA-256 changed: {digest}")
    page_count = len(PdfReader(RAW).pages)
    if page_count != 686:
        raise RuntimeError(f"expected 686 PDF pages; found {page_count}")
    return body


STATE_ROWS = [
    ("India", "3095", "278008.94", "3007", "282356.54", "2995", "293811.5373", 38, 23),
    ("Andhra Pradesh", "379", "25450.49", "376", "25411.77", "377", "25650.8434", 38, 23),
    ("Assam", "7", "889.5", "7", "889.5", "6", "858.5", 38, 23),
    ("Bihar", "1", "53.38", "1", "53.38", "5", "53.378", 38, 23),
    ("Chhattisgarh", "175", "26210.55", "158", "25491.13", "158", "24825.281", 38, 23),
    ("Goa", "9", "442.49", "9", "439.79", "10", "918.3144", 38, 23),
    ("Gujarat", "440", "26836.82", "432", "27300.96", "377", "26732.8153", 38, 23),
    ("Himachal Pradesh", "40", "2448.58", "40", "2448.61", "n", "2430.489", 38, 23),
    ("Haryana", "4", "46.85", "4", "46.85", "4", "46.85", 38, 23),
    ("Jammu & Kashmir**", "37", "2020.43***", "38", "2146.76", "37", "1330.231", 38, 23),
    ("Jharkhand", "100", "18068.24", "100", "18068.28", "101", "18099.9169", 38, 23),
    ("Karnataka", "298", "33047.05", "293", "32830.72", "262", "30945.005", 38, 23),
    ("Kerala", "5", "421.65", "5", "421.65", "5", "421.654", 38, 23),
    ("Ladakh(UT)***", "", "", "", "", "1", "159", 38, 23),
    ("Meghalaya", "21", "789.34", "23", "1061.39", "23", "824.6102", 38, 23),
    ("Madhya Pradesh", "613", "37838.75", "598", "41196.77", "644", "43658.856", 38, 23),
    ("Maharashtra", "130", "12872.74", "113", "11149.17", "111", "10990.034", 38, 23),
    ("Odisha", "117", "33872.45", "118", "36066.91", "153", "46921.1818", 38, 23),
    ("Rajasthan", "168", "34528.73", "145", "35007.52", "137", "36253.10025", 39, 24),
    ("Tamil Nadu", "459", "9158.7", "456", "9097.96", "455", "9096.255", 39, 24),
    ("Telangana", "80", "10227.38", "79", "10442.61", "78", "10429.733", 39, 24),
    ("Uttar Pradesh", "4", "2579.56", "4", "2579.55", "4", "2960.21", 39, 24),
    ("Uttarakhand", "7", "191.79", "7", "191.79", "7", "191.809", 39, 24),
    ("West Bengal", "1", "13.47", "1", "13.47", "1", "13.47", 39, 24),
]

MINERAL_ROWS = [
    ("Amethyst", "2", "5.83", 39, 24),
    ("Apatite", "1", "13.47", 39, 24),
    ("Bauxite", "310", "23524.363", 39, 24),
    ("Borax", "1", "159", 39, 24),
    ("Chromite", "22", "5620.859", 39, 24),
    ("Copper Ore", "9", "3916.851", 39, 24),
    ("Diamond", "2", "275.963", 39, 24),
    ("Emerald", "2", "125.64", 39, 24),
    ("Epidote", "1", "4.0515", 39, 24),
    ("Fluorite", "7", "416.158", 39, 24),
    ("Garnet", "20", "118.7838", 39, 24),
    ("Gold", "10", "6934.26", 39, 24),
    ("Graphite", "27", "1199.0369", 39, 24),
    ("Iolite", "2", "16.417", 39, 24),
    ("Iron Ore", "337", "56920.617", 39, 24),
    ("Kyanite", "15", "288.982", 39, 24),
    ("Lead and Zinc Ore", "11", "6890.4875", 39, 24),
    ("Limeshell", "18", "873.958", 39, 24),
    ("Limestone", "1812", "168264.605", 39, 24),
    ("Magnesite", "33", "2301.721", 39, 24),
    ("Manganese Ore", "215", "11482.96", 39, 24),
    ("Moulding Sand", "6", "39.232", 39, 24),
    ("Perlite", "1", "144.8831", 39, 24),
    ("Rock Phosphate", "7", "1534.237", 39, 24),
    ("Rock Salt", "1", "8.122", 39, 24),
    ("Semi Precious Stone", "14", "164.214", 39, 24),
    ("Selenite", "4", "624.3466", 39, 24),
    ("Siliceous Earth", "17", "168.4086", 39, 24),
    ("Sillamanite", "1", "4.64", 39, 24),
    ("Stibnite/Antimony", "1", "40.468", 39, 24),
    ("Tin", "17", "338.183", 39, 24),
    ("Vermiculite", "50", "890.9683", 39, 24),
    ("Wollastonite", "12", "254.1042", 39, 24),
    ("Gemstone Cats Eye", "3", "82.357", 40, 25),
    ("Beryl", "2", "9.8", 40, 25),
    ("Fluorspar", "1", "63.2", 40, 25),
    ("Aluminous Laterite", "1", "90.36", 40, 25),
    ("Total", "2995", "293811.54", 40, 25),
]

SECTOR_ROWS = [
    ("Total", "2995", "100", "293811.5373", "100"),
    ("Public", "251", "8.38", "83150.059", "28.30"),
    ("Private", "2744", "91.62", "210661.4783", "71.70"),
]

AREA_BAND_ROWS = [
    ("0 to 2", "337", "398.30"),
    (">2 to 5", "777", "2931.42"),
    (">5 to 10", "392", "2817.74"),
    (">10 to 20", "303", "4400.40"),
    (">20 to 50", "400", "12891.16"),
    (">50 to 100", "223", "15944.85"),
    (">100 to 200", "189", "27245.18"),
    (">200 to 500", "204", "65804.03"),
    ("Above 500", "170", "161378.45"),
    ("Total", "2995", "293811.54"),
]

# Pipe-separated transcription of IBM Table 5, visually checked against PDF
# pages 40--43 (printed chapter pages 25--28).  Source spellings are retained.
AUCTION_ROWS_TEXT = """1|Andhra Pradesh|Adakula|Semi-Precious stone|19.03.2024|CL|36.997
2|Andhra Pradesh|Addankivaripalem|Iron Ore|28.07.2023|CL|N.A.
3|Andhra Pradesh|Lakshmakapalle (North)|Iron Ore|28.07.2023|CL|N.A.
4|Andhra Pradesh|Lakshmakapalle (South)|Iron Ore|28.07.2023|CL|N.A.
5|Andhra Pradesh|Mincheri RF|Iron Ore|11.03.2024|CL|1327
6|Chhattisgarh|North of Arjunda|Glauconite (Potash)|04.07.2023|CL|600
7|Chhattisgarh|Saloni Block|Limestone|21.09.2023|CL|600
8|Chhattisgarh|Devri Limestone Block|Limestone|19.09.2023|CL|630
9|Chhattisgarh|Kareli Chandi Block|Limestone|20.09.2023|CL|500
10|Chhattisgarh|Giroud Uprani Block|Glauconite|27.09.2023|CL|N.A.
11|Chhattisgarh|Tumrisur Garda II|Gold|20.12.2023|CL|240
12|Gujarat|Mevasa Block-1|Bauxite (Aluminous Laterite) and Laterite (minor mineral)|18.07.2023|ML|5.99
13|Gujarat|Mevasa Block|Bauxite, and Marl|18.07.2023|ML|5.53
14|Gujarat|Kukaras block (Private)|Limestone and Marl|18.07.2023|ML|29.17
15|Gujarat|Nandana Block|Bauxite Limestone and Marl|19.07.2023|ML|29.17
16|Gujarat|Kodidra Block|Limestone and Marl|19.07.2023|ML|29.17
17|Gujarat|Virpur Lusari Block|Bauxite (Aluminous Laterite), Limestone and Marl|21.07.2023|ML|29.17
18|Jharkhand|Chiropat Bauxite Block/Gumla&Lohardaga|Bauxite|20.04.2023|ML|63
19|Jharkhand|Baraiburu - Tatiba Iron and Manganese Ore Block|Iron and Manganese Ore|18.08.2023|CL|258.99
20|Jharkhand|Meralgara-Barabaljori Iron Ore Block|Iron Ore Block|10.08.2023|ML|115.22
21|Karnataka|Block No. 04, HRG|Iron Ore|24.07.2023|ML|40.04
22|Karnataka|Thimmanahalli Gold block|Gold|21.08.2023|CL|N.A.
23|Karnataka|Jaisinghpura North Block|Iron Ore|21.08.2023|ML|298.59
24|Karnataka|Basavanagudda|Gold|21.08.2023|CL|2501.9
25|Karnataka|Nidodi Bauxite Block|Bauxite|21.09.2023|CL|52.82
26|Karnataka|Kuddarka Bauxite Block|Bauxite|22.09.2023|CL|52
27|Madhya Pradesh|Katni Limestone Block*(10A2b Case)|Limestone|05.09.2023|ML|120.949
28|Madhya Pradesh|Pahari Limestone Block (10A2d Case)|Limestone|11.09.2023|ML|100.144
29|Madhya Pradesh|Pipartola Manganese Ore Block*(10A2b Case)|Manganese Ore|12.09.2023|ML|4.653
30|Madhya Pradesh|Chorgadi-Puraina Limestone Block|Limestone|06.09.2023|ML|378.404
31|Madhya Pradesh|Bhilapar Manganese Ore & Dolomite Block(10A2b Case)|Manganese Ore & Dolomite|05.09.2023|CL|9.037
32|Madhya Pradesh|Dhamani Nana Manganese Ore Block*(10A2b Case)|Manganese Ore|08.09.2023|CL|4.7
33|Madhya Pradesh|Guvali Manganese Ore Block*(10A2b Case)|Manganese Ore|05.09.2023|CL|4.61
34|Madhya Pradesh|Katangjhari Manganese Ore Block*(10A2b Case)|Manganese Ore|08.09.2023|CL|5.101
35|Madhya Pradesh|Lingaponar Manganese Ore Block(10A2b Case)|Manganese Ore|11.09.2023|CL|9.712
36|Madhya Pradesh|Naganwat-Chhoti Manganese Ore Block*(10A2b Case)|Manganese Ore|08.09.2023|CL|11.86
37|Madhya Pradesh|Uberao Manganese Ore Block*|Manganese Ore|06.09.2023|CL|4.68
38|Madhya Pradesh|Bamanbardi Limestone Block|Limestone|05.09.2023|CL|913.3954
39|Madhya Pradesh|Doter Guvali Manganese Ore Block|Manganese Ore|09.09.2023|CL|736.4
40|Madhya Pradesh|East of Dabri Limestone Block|Limestone|08.09.2023|CL|815
41|Madhya Pradesh|Garhi-Upcha Limestone Block|Limestone|09.09.2023|CL|1001.95
42|Madhya Pradesh|Nawapara Rampura Manganese Ore Block|Manganese Ore|11.09.2023|CL|725.7
43|Madhya Pradesh|Piploda Phosphorite Block|Phosphorite|05.09.2023|CL|464
44|Madhya Pradesh|Shitalpani Copper Block*|Copper|09.09.2023|CL|220.971
45|Madhya Pradesh|Siluwa and Jhansi Iron Ore Block|Iron Ore|13.09.2023|ML|4.59
46|Madhya Pradesh|Modri Phosphorite Block|Phosphorite|13.09.2023|CL|699.55
47|Madhya Pradesh|Pindrai Iron Ore Block|Iron Ore|14.09.2023|ML|6
48|Madhya Pradesh|Makra Block|Graphite Vanadium|14.09.2023|CL|37.5
49|Maharashtra|DevalmariKatepalli Limestone Block|Limestone|09.05.2023|ML|537.54
50|Maharashtra|Surjagad – 1 Iron Ore Block|Iron Ore|09.05.2023|CL|1526
51|Maharashtra|Surjagad – 2 Iron Ore Block|Iron Ore|09.05.2023|CL|886
52|Maharashtra|Surjagad – 3 Iron Ore Block|Iron Ore|09.05.2023|CL|640
53|Maharashtra|Surjagad – 4 Iron Ore Block|Iron Ore|12.05.2023|CL|397
54|Maharashtra|South Padve|Bauxite|09.05.2023|CL|500
55|Maharshtra|Surjagad – 6 Iron Ore Block|Iron Ore|17.05.2023|CL|658
56|Maharashtra|Kondhala|Limestone|19.05.2023|ML|105
57|Maharashtra|Minzhari Copper Block|Copper|21.11.2023|CL|1743
58|Maharashtra|Savali Manganese Block|Manganese|22.11.2023|CL|1200
59|Rajasthan|Nayorana-Dandela|Iron Ore|11.07.2023|CL|16.78
60|Rajasthan|Hariyav Jashpura|Limestone|10.07.2023|ML|94.62
61|Rajasthan|Khakhiliya Khera Block Rajasmand, CL|Basemetal& Associated Minerals|24.08.2023|CL|642.45
62|Rajasthan|Pipliyan Block, Udaipur, CL|Basemetal|25.08.2023|CL|518.65
63|Rajasthan|Manpura Block, Banera, CL|Basemetal& Associated Minerals|28.08.2023|CL|1150
64|Rajasthan|Ladi Ka Bas Block Tehsil Neem ka Thana & District Sikar|Iron Ore|28.08.2023|CL|38.75
65|Rajasthan|Kalakota Block Tehsil Neem ka Thana & District Sikar|Iron Ore|29.08.2023|CL|34.44
66|Rajasthan|Ladanan/v Ladana-Ladani, Tehsil Mavli, District - Udaipur(Raj)|Basemetal|31.08.2023|CL|300
67|Rajasthan|Bhabhriya ka Kheda Block n/v Lakha Ka Khera District Chittaurgarh|Basemetal|04.09.2023|CL|970
68|Rajasthan|Toda Block n/v Toda, Tehsil Neem ka Thana, District Sikar|Iron Ore|12.09.2023|CL|18.43
69|Rajasthan|PSB02 n/V Harima Tehsil, District Nagaur|Limestone|12.09.2023|ML|4.9
70|Rajasthan|PSB01 n/V Tehsil & District Nagaur|Limestone|11.09.2023|ML|4.9
71|Rajasthan|PSB06 n/V Tehsil & District Nagaur|Limestone|18.09.2023|ML|4.8
72|Rajasthan|PSB07 n/V Tehsil & District Nagaur|Limestone|19.09.2023|ML|4.8
73|Rajasthan|HPB 19 n/V Harima Khetolaw, Pithasia, Sarasani|Limestone|03.10.2023|ML|476.8
74|Rajasthan|HPB 20 n/V Harima Khetolaw, Pithasia, Sarasani|Limestone|04.10.2023|ML|547.55
75|Rajasthan|PSB03 n/v Harima Tehsil & District Nagpur|Limestone|21.02.2024|ML|4.8
76|Rajasthan|PSB04 n/v Harima Tehsil & District Nagpur|Limestone|22.02.2024|ML|4.8
77|Rajasthan|PSB05 n/v Harima Tehsil & District Nagpur|Limestone|23.02.2024|ML|4.8
78|Rajasthan|PSB08 n/v Harima Tehsil & District Nagpur|Limestone|26.02.2024|ML|4.8
79|Rajasthan|PSB09 n/v Harima Tehsil & District Nagpur|Limestone|27.02.2024|ML|4.8
80|Rajasthan|PSB010 n/v Harima Tehsil & District Nagpur|Limestone|28.02.2024|ML|4.8
81|Rajasthan|PSB011 n/v Harima Tehsil & District Nagpur|Limestone|29.02.2024|ML|4.8
82|Rajasthan|PSB012 n/v Harima Tehsil & District Nagpur|Limestone|01.03.2024|ML|4.8
83|Rajasthan|PSB013 n/v Harima Tehsil & District Nagpur|Limestone|04.03.2024|ML|4.8
84|Rajasthan|PSB 014 n/v Sarsani tehsil & district Nagaur|Limestone|05.03.2024|ML|4.8
85|Rajasthan|PSB 015 n/v Sarsani tehsil & district Nagaur|Limestone|06.03.2024|ML|4.8
86|Rajasthan|PSB016 n/v Harima Tehsil & District Nagaur|Limestone|07.03.2024|ML|4.8
87|Rajasthan|PSB017 n/v Harima Tehsil & District Nagaur|Limestone|11.03.2024|ML|4.8
88|Rajasthan|PSB 018 n/v Khetolow Tehsil & District Nagaur|Limestone|12.03.2024|ML|4.8
89|Rajasthan|HPB21 n/v Khetolow Tehsil & District Nagaur|Limestone|13.03.2024|ML|307
90|Uttar Pradesh|Girar|Iron Ore & Gold|23.11.2023|CL|271.18
91|Uttar Pradesh|Bharhari|Iron Ore|24.11.2023|CL|134.77
92|Uttar Pradesh|Sona Pahari|Gold|23.11.2023|CL|79
93|Goa|Block V- Advalpale-Thivim Mineral Block|Iron Ore|21.04.2023|ML|36.22
94|Goa|Block VI- Cudnem-Cormolem Mineral Block|Iron Ore|25.04.2023|ML|38.51
95|Goa|Block VII-Cudnem Mineral Block|Iron Ore|26.04.2023|ML|75.3
96|Goa|Block VIII-Thivim-Pirna Mineral Block|Iron Ore|27.04.2023|ML|72.05
97|Goa|Block IX-Surla-Sonshi Mineral Block|Iron Ore|28.04.2023|ML|254.51"""

MATERIAL_MAPPINGS = {
    "Amethyst": ["mineral:quartz"],
    "Apatite": ["group:apatite-group"],
    "Bauxite": ["element:aluminium", "ore:bauxite"],
    "Borax": ["mineral:borax"],
    "Chromite": ["element:chromium", "mineral:chromite"],
    "Copper Ore": ["element:copper"],
    "Diamond": ["mineral:diamond"],
    "Emerald": ["variety:emerald"],
    "Epidote": ["mineral:epidote"],
    "Fluorite": ["element:fluorine", "mineral:fluorite"],
    "Garnet": ["group:garnet-group"],
    "Gold": ["element:gold"],
    "Graphite": ["mineral:graphite"],
    "Iolite": ["mineral:cordierite"],
    "Iron Ore": ["element:iron", "ore:iron-ore"],
    "Iron Ore Block": ["element:iron", "ore:iron-ore"],
    "Kyanite": ["group:kyanite-and-related-minerals", "mineral:kyanite"],
    "Lead and Zinc Ore": ["element:lead", "element:zinc"],
    "Limeshell": ["group:calcium-and-limestone", "material:calcareous-shell-material"],
    "Limestone": ["group:calcium-and-limestone", "rock:limestone"],
    "Magnesite": ["element:magnesium", "mineral:magnesite"],
    "Manganese": ["element:manganese"],
    "Manganese Ore": ["element:manganese"],
    "Moulding Sand": ["material:moulding-sand"],
    "Perlite": ["rock:perlite"],
    "Rock Phosphate": ["element:phosphorus", "ore:phosphorite"],
    "Rock Salt": ["mineral:halite"],
    "Semi Precious Stone": ["group:semi-precious-gemstones"],
    "Selenite": ["mineral:gypsum"],
    "Siliceous Earth": ["material:siliceous-earth"],
    "Sillamanite": ["mineral:sillimanite"],
    "Stibnite/Antimony": ["mineral:stibnite", "element:antimony"],
    "Tin": ["element:tin"],
    "Vermiculite": ["mineral:vermiculite"],
    "Wollastonite": ["mineral:wollastonite"],
    "Gemstone Cats Eye": ["group:semi-precious-gemstones"],
    "Beryl": ["mineral:beryl", "element:beryllium"],
    "Fluorspar": ["element:fluorine", "mineral:fluorite"],
    "Aluminous Laterite": ["element:aluminium", "ore:aluminous-laterite", "rock:laterite"],
    "Semi-Precious stone": ["group:semi-precious-gemstones"],
    "Glauconite (Potash)": ["group:glauconite-group", "group:potash"],
    "Glauconite": ["group:glauconite-group"],
    "Bauxite (Aluminous Laterite) and Laterite (minor mineral)": ["element:aluminium", "ore:bauxite", "ore:aluminous-laterite", "rock:laterite"],
    "Bauxite, and Marl": ["element:aluminium", "ore:bauxite", "rock:marl"],
    "Limestone and Marl": ["group:calcium-and-limestone", "rock:limestone", "rock:marl"],
    "Bauxite Limestone and Marl": ["element:aluminium", "ore:bauxite", "group:calcium-and-limestone", "rock:limestone", "rock:marl"],
    "Bauxite (Aluminous Laterite), Limestone and Marl": ["element:aluminium", "ore:bauxite", "ore:aluminous-laterite", "rock:laterite", "group:calcium-and-limestone", "rock:limestone", "rock:marl"],
    "Iron and Manganese Ore": ["element:iron", "ore:iron-ore", "element:manganese"],
    "Manganese Ore & Dolomite": ["element:manganese", "mineral:dolomite"],
    "Phosphorite": ["element:phosphorus", "ore:phosphorite"],
    "Copper": ["element:copper"],
    "Graphite Vanadium": ["mineral:graphite", "element:vanadium"],
    "Iron Ore & Gold": ["element:iron", "ore:iron-ore", "element:gold"],
}


def load_ontology() -> dict[str, dict]:
    frame = pd.read_csv(OUT / "india_material_ontology_v1.csv", keep_default_na=False)
    ontology = {row.material_id: row._asdict() for row in frame.itertuples(index=False)}
    missing_ids = sorted({item for values in MATERIAL_MAPPINGS.values() for item in values} - set(ontology))
    if missing_ids:
        raise RuntimeError(f"material mappings reference missing ontology IDs: {missing_ids}")
    return ontology


def material_fields(source_term: str, ontology: dict[str, dict]) -> dict[str, str]:
    ids = MATERIAL_MAPPINGS.get(source_term, [])
    names = [ontology[item]["material_name"] for item in ids]
    chemical_or_english = []
    formulae_or_symbols = []
    for item in ids:
        row = ontology[item]
        chemical = json.loads(row["chemical_names_json"] or "[]")
        english = json.loads(row["english_names_json"] or "[]")
        for name in chemical or english or [row["material_name"]]:
            if name not in chemical_or_english:
                chemical_or_english.append(name)
        for value in json.loads(row["symbols_or_formulae_json"] or "[]"):
            if value not in formulae_or_symbols:
                formulae_or_symbols.append(value)
    if not chemical_or_english and source_term not in {"Total", ""}:
        chemical_or_english = [source_term]
    return {
        "normalized_material_ids_json": jdump(ids),
        "normalized_material_names_json": jdump(names),
        "chemical_or_english_names_json": jdump(chemical_or_english),
        "formulae_or_symbols_json": jdump(formulae_or_symbols),
    }


def numeric(raw: str, integer: bool = False):
    cleaned = raw.replace("***", "").strip()
    if not cleaned or cleaned.casefold() in {"n", "n.a."}:
        return ""
    return int(cleaned) if integer else float(cleaned)


def build_aggregate_rows(ontology: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    scope = jdump(SCOPE_EXCLUSIONS)
    sequence = 0

    def add(
        dimension: str,
        category_source: str,
        category_normalized: str,
        as_of_date: str,
        provisional: bool,
        count_source: str,
        area_source: str,
        count_share: str,
        area_share: str,
        is_total: bool,
        source_table: str,
        pdf_page: int,
        printed_page: int,
        quality_flags: list[str],
    ) -> None:
        nonlocal sequence
        sequence += 1
        material = material_fields(category_source if dimension == "mineral" else "", ontology)
        rows.append({
            "record_id": f"IBM-IMYB2024-LEASE-AGG-{sequence:03d}",
            "record_type": "official_mining_lease_aggregate",
            "source_id": SOURCE_ID,
            "dimension": dimension,
            "category_source": category_source,
            "category_normalized": category_normalized,
            "as_of_date": as_of_date,
            "provisional": provisional,
            "lease_count": numeric(count_source, integer=True),
            "lease_count_source": count_source,
            "lease_area_ha": numeric(area_source),
            "lease_area_ha_source": area_source,
            "lease_count_share_pct": numeric(count_share),
            "lease_area_share_pct": numeric(area_share),
            "is_total": is_total,
            **material,
            "source_table": source_table,
            "source_pdf_page": pdf_page,
            "source_printed_page": printed_page,
            "source_url": SOURCE_URL,
            "source_access_date": SOURCE_ACCESS_DATE,
            "source_document_sha256": SOURCE_DOCUMENT_SHA256,
            "scope_exclusions_json": scope,
            "coordinates_published": False,
            "geometry_published": False,
            "model_evidence_role": "excluded_context_only",
            "quality_flags_json": jdump(
                quality_flags + ["non_spatial_aggregate"] + (["provisional_2024_status"] if provisional else [])
            ),
            "notes": "Preserves the source table value and scope; it is not a site, reserve/resource estimate, production record, or proof of current operation.",
        })

    periods = [
        ("2022-03-31", False, 1, 2),
        ("2023-03-31", False, 3, 4),
        ("2024-03-31", True, 5, 6),
    ]
    for source, *values, pdf_page, printed_page in STATE_ROWS:
        normalized = {"Jammu & Kashmir**": "Jammu and Kashmir", "Ladakh(UT)***": "Ladakh"}.get(source, source)
        for as_of_date, provisional, count_index, area_index in periods:
            count_source, area_source = values[count_index - 1], values[area_index - 1]
            flags = []
            if not count_source and not area_source:
                flags.append("source_value_not_reported")
            if count_source == "n":
                flags.append("unparseable_source_lease_count_preserved")
            if "***" in area_source:
                flags.append("source_footnote_includes_ladakh")
            add("state_or_ut", source, normalized, as_of_date, provisional, count_source, area_source, "", "", source == "India", "Table 1", pdf_page, printed_page, flags)

    for source, count_source, area_source, pdf_page, printed_page in MINERAL_ROWS:
        flags = []
        if source == "Sillamanite":
            flags.append("source_spelling_preserved_normalized_to_sillimanite")
        if source not in MATERIAL_MAPPINGS and source != "Total":
            flags.append("material_term_unresolved_or_nonspecific")
        add("mineral", source, "Sillimanite" if source == "Sillamanite" else source, "2024-03-31", True, count_source, area_source, "", "", source == "Total", "Table 2", pdf_page, printed_page, flags)

    for source, count_source, count_share, area_source, area_share in SECTOR_ROWS:
        add("sector", source, source, "2024-03-31", True, count_source, area_source, count_share, area_share, source == "Total", "Table 3", 40, 25, [])

    for source, count_source, area_source in AREA_BAND_ROWS:
        add("lease_area_band", source, source, "2024-03-31", True, count_source, area_source, "", "", source == "Total", "Table 4", 40, 25, [])
    return rows


def parse_auction_rows(ontology: dict[str, dict]) -> list[dict]:
    rows = []
    for line in AUCTION_ROWS_TEXT.splitlines():
        values = line.split("|")
        if len(values) != 7:
            raise RuntimeError(f"expected seven Table 5 fields: {line!r}")
        serial_source, state_source, block_source, mineral_source, date_source, concession_code, area_source = values
        serial = int(serial_source)
        state = {"Maharshtra": "Maharashtra"}.get(state_source, state_source)
        date = datetime.strptime(date_source, "%d.%m.%Y").date().isoformat()
        area = numeric(area_source)
        pdf_page, printed_page = (
            (40, 25) if serial <= 11 else (41, 26) if serial <= 42 else (42, 27) if serial <= 75 else (43, 28)
        )
        flags = ["coordinates_not_published", "geometry_not_published", "current_status_not_independently_verified"]
        if state_source != state:
            flags.append("source_state_spelling_preserved_and_normalized")
        if area == "":
            flags.append("area_not_available_in_source")
        if mineral_source not in MATERIAL_MAPPINGS:
            flags.append("material_term_unresolved_or_nonspecific")
        if "District Nagpur" in block_source:
            flags.append("possible_source_district_inconsistency_preserved")
        rows.append({
            "record_id": f"IBM-IMYB2024-AUCTION-{serial:03d}",
            "record_type": "official_auction_granted_concession_context",
            "source_id": SOURCE_ID,
            "source_serial_number": serial,
            "state_or_ut": state,
            "state_source": state_source,
            "block_name": block_source,
            "block_name_source": block_source,
            "mineral_source": mineral_source,
            **material_fields(mineral_source, ontology),
            "auction_date": date,
            "concession_type_code": concession_code,
            "concession_type": "mining_lease" if concession_code == "ML" else "composite_licence",
            "area_ha": area,
            "area_ha_source": area_source,
            "area_available": area != "",
            "published_status": "granted_through_auction_during_2023_24_per_ibm_table_title",
            "published_status_scope": "IBM Table 5 yearbook compilation; not independently reconciled to a controlling current state grant record",
            "latitude": "",
            "longitude": "",
            "coordinates_published": False,
            "geometry_published": False,
            "current_legal_or_operational_status_verified": False,
            "model_evidence_role": "excluded_context_only",
            "model_exclusion_reason": "The source publishes no coordinate or footprint and does not independently establish current operation, production, reserves/resources, or controlling legal status.",
            "source_table": "Table 5",
            "source_pdf_page": pdf_page,
            "source_printed_page": printed_page,
            "source_url": SOURCE_URL,
            "source_access_date": SOURCE_ACCESS_DATE,
            "source_document_sha256": SOURCE_DOCUMENT_SHA256,
            "quality_flags_json": jdump(flags),
            "notes": "Source wording is preserved. Auction date is the source column; it must not be reinterpreted as commencement of mining or present validity.",
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
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
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def upsert_data_dictionary(outputs: list[tuple[Path, list[dict]]]) -> None:
    path = OUT / "data_dictionary.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        table_names = {output.name for output, _ in outputs}
        rows = [row for row in reader if row["table"] not in table_names]
    definitions = {
        "category_source": "Category wording transcribed from the IBM source table.",
        "category_normalized": "Conservative normalized category label; source wording remains in category_source.",
        "lease_count_source": "Exact printed lease-count value, including blanks or the IBM 'n' anomaly.",
        "lease_area_ha_source": "Exact printed lease-area value before numeric normalization.",
        "chemical_or_english_names_json": "JSON array: ontology chemical names when available, otherwise ontology English names; unresolved source terms fall back to the preserved English source label.",
        "formulae_or_symbols_json": "JSON array of ontology symbols or formulae for mapped materials when available.",
        "published_status": "Status represented by the IBM Table 5 title; not independently verified against a controlling current grant record.",
        "published_status_scope": "Limits on interpreting the IBM Table 5 title as present legal or operating status.",
        "current_legal_or_operational_status_verified": "Always false because the source chapter does not publish a controlling current-status record.",
        "model_evidence_role": "Whether the row may enter KHANAN training or scoring; every row in these tables is excluded context only.",
        "source_pdf_page": "One-based physical page number in the 686-page PDF.",
        "source_printed_page": "Page number printed in the yearbook chapter.",
        "source_document_sha256": "SHA-256 of the pinned IBM yearbook PDF.",
    }
    boolean_columns = {"provisional", "is_total", "coordinates_published", "geometry_published", "area_available", "current_legal_or_operational_status_verified"}
    numeric_columns = {"lease_count", "lease_area_ha", "lease_count_share_pct", "lease_area_share_pct", "area_ha", "source_serial_number", "source_pdf_page", "source_printed_page"}
    for output, output_rows in outputs:
        for column in output_rows[0]:
            rows.append({
                "table": output.name,
                "column": column,
                "definition": definitions.get(column, column.replace("_", " ").capitalize() + "."),
                "data_type": "boolean" if column in boolean_columns else "number" if column in numeric_columns else "string",
                "unit": "hectares" if column in {"lease_area_ha", "area_ha"} else "percent" if column.endswith("share_pct") else "JSON array" if column.endswith("_json") else "",
                "missing_value_policy": "Blank means not published, not applicable, unresolved, or unavailable; zero is never inferred from a blank.",
            })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate(aggregate_rows: list[dict], auction_rows: list[dict], pdf_bytes: bytes) -> dict:
    aggregates = pd.DataFrame(aggregate_rows)
    auctions = pd.DataFrame(auction_rows)
    state_2024 = aggregates[(aggregates.dimension == "state_or_ut") & (aggregates.as_of_date == "2024-03-31")]
    state_2024_non_total = state_2024[~state_2024.is_total]
    state_known_count_sum = sum(int(value) for value in state_2024_non_total.lease_count if value != "")
    mineral = aggregates[(aggregates.dimension == "mineral") & (~aggregates.is_total)]
    sector = aggregates[(aggregates.dimension == "sector") & (~aggregates.is_total)]
    bands = aggregates[(aggregates.dimension == "lease_area_band") & (~aggregates.is_total)]
    validation = {
        "release_version": RELEASE_VERSION,
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "source_access_date": SOURCE_ACCESS_DATE,
        "source_document_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "source_document_bytes": len(pdf_bytes),
        "source_document_pdf_pages": 686,
        "source_tables_visually_reviewed": ["Table 1", "Table 2", "Table 3", "Table 4", "Table 5"],
        "aggregate_rows": len(aggregates),
        "aggregate_rows_by_dimension": {str(k): int(v) for k, v in aggregates.dimension.value_counts().sort_index().items()},
        "state_or_ut_categories_including_india_total": int(aggregates.loc[aggregates.dimension.eq("state_or_ut"), "category_source"].nunique()),
        "state_or_ut_2024_lease_total": int(state_2024.loc[state_2024.is_total, "lease_count"].iloc[0]),
        "state_or_ut_2024_area_total_ha": float(state_2024.loc[state_2024.is_total, "lease_area_ha"].iloc[0]),
        "himachal_pradesh_2024_source_lease_count": state_2024.loc[state_2024.category_source.eq("Himachal Pradesh"), "lease_count_source"].iloc[0],
        "himachal_pradesh_2024_numeric_lease_count_blank": state_2024.loc[state_2024.category_source.eq("Himachal Pradesh"), "lease_count"].iloc[0] == "",
        "himachal_pradesh_2024_count_implied_by_total_not_substituted": 2995 - state_known_count_sum,
        "mineral_categories_excluding_total": len(mineral),
        "mineral_lease_count_sum": int(sum(mineral.lease_count)),
        "mineral_area_sum_ha": float(sum(mineral.lease_area_ha)),
        "mineral_area_sum_minus_rounded_table_total_ha": float(sum(mineral.lease_area_ha) - 293811.54),
        "mineral_categories_with_ontology_mapping": int(mineral.normalized_material_ids_json.ne("[]").sum()),
        "mineral_categories_using_english_fallback": int(mineral.normalized_material_ids_json.eq("[]").sum()),
        "sector_lease_count_sum": int(sum(sector.lease_count)),
        "sector_area_sum_ha": float(sum(sector.lease_area_ha)),
        "area_band_lease_count_sum": int(sum(bands.lease_count)),
        "area_band_area_sum_ha": float(sum(bands.lease_area_ha)),
        "auction_rows": len(auctions),
        "auction_unique_record_ids": int(auctions.record_id.nunique()),
        "auction_serials_contiguous_1_to_97": auctions.source_serial_number.tolist() == list(range(1, 98)),
        "auction_rows_by_state": {str(k): int(v) for k, v in auctions.state_or_ut.value_counts().sort_index().items()},
        "auction_rows_by_concession_type": {str(k): int(v) for k, v in auctions.concession_type_code.value_counts().sort_index().items()},
        "auction_rows_with_area": int(auctions.area_available.sum()),
        "auction_rows_without_area": int((~auctions.area_available).sum()),
        "auction_rows_with_ontology_mapping": int(auctions.normalized_material_ids_json.ne("[]").sum()),
        "auction_rows_using_english_fallback": int(auctions.normalized_material_ids_json.eq("[]").sum()),
        "auction_rows_with_coordinates": int((auctions.latitude.ne("") | auctions.longitude.ne("")).sum()),
        "auction_rows_admitted_to_model_evidence": int(auctions.model_evidence_role.ne("excluded_context_only").sum()),
        "scope_exclusions": SCOPE_EXCLUSIONS,
        "guardrail": "These tables are official concession context, not an exhaustive current mine register, site-level reserve/resource evidence, production evidence, access permission, or proof of current legal or operating status. No aggregate or ungeoreferenced block row enters KHANAN training or scoring.",
    }
    validation["checks_pass"] = bool(
        validation["source_document_sha256"] == SOURCE_DOCUMENT_SHA256
        and validation["aggregate_rows"] == 123
        and validation["aggregate_rows_by_dimension"] == {"lease_area_band": 10, "mineral": 38, "sector": 3, "state_or_ut": 72}
        and validation["state_or_ut_categories_including_india_total"] == 24
        and validation["state_or_ut_2024_lease_total"] == 2995
        and abs(validation["state_or_ut_2024_area_total_ha"] - 293811.5373) < 1e-8
        and validation["himachal_pradesh_2024_source_lease_count"] == "n"
        and validation["himachal_pradesh_2024_numeric_lease_count_blank"]
        and validation["himachal_pradesh_2024_count_implied_by_total_not_substituted"] == 39
        and validation["mineral_categories_excluding_total"] == 37
        and validation["mineral_lease_count_sum"] == 2995
        and validation["mineral_categories_with_ontology_mapping"] == 37
        and abs(validation["mineral_area_sum_minus_rounded_table_total_ha"]) <= 0.01
        and validation["sector_lease_count_sum"] == 2995
        and abs(validation["sector_area_sum_ha"] - 293811.5373) < 1e-8
        and validation["area_band_lease_count_sum"] == 2995
        and abs(validation["area_band_area_sum_ha"] - 293811.53) < 0.02
        and validation["auction_rows"] == validation["auction_unique_record_ids"] == 97
        and validation["auction_serials_contiguous_1_to_97"]
        and validation["auction_rows_with_area"] == 92
        and validation["auction_rows_without_area"] == 5
        and validation["auction_rows_with_ontology_mapping"] == 92
        and validation["auction_rows_using_english_fallback"] == 5
        and validation["auction_rows_with_coordinates"] == 0
        and validation["auction_rows_admitted_to_model_evidence"] == 0
    )
    return validation


def update_release_validation(validation: dict) -> None:
    path = OUT / "validation_report.json"
    release = json.loads(path.read_text(encoding="utf-8"))
    release["development_release_version"] = RELEASE_VERSION
    release["ibm_mineral_concessions_2024"] = {
        "aggregate_rows": validation["aggregate_rows"],
        "mineral_categories_excluding_total": validation["mineral_categories_excluding_total"],
        "state_or_ut_2024_lease_total": validation["state_or_ut_2024_lease_total"],
        "state_or_ut_2024_area_total_ha": validation["state_or_ut_2024_area_total_ha"],
        "auction_rows": validation["auction_rows"],
        "auction_rows_without_area": validation["auction_rows_without_area"],
        "auction_rows_with_coordinates": validation["auction_rows_with_coordinates"],
        "auction_rows_admitted_to_model_evidence": validation["auction_rows_admitted_to_model_evidence"],
        "checks_pass": validation["checks_pass"],
    }
    path.write_text(json.dumps(release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload the pinned IBM yearbook PDF")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    body = fetch_source(args.refresh)
    ontology = load_ontology()
    aggregate_rows = build_aggregate_rows(ontology)
    auction_rows = parse_auction_rows(ontology)
    write_csv(AGGREGATE_OUTPUT, aggregate_rows)
    write_csv(AUCTION_OUTPUT, auction_rows)
    validation = validate(aggregate_rows, auction_rows, body)
    VALIDATION_OUTPUT.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    upsert_source_registry()
    upsert_data_dictionary([(AGGREGATE_OUTPUT, aggregate_rows), (AUCTION_OUTPUT, auction_rows)])
    update_release_validation(validation)
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not validation["checks_pass"]:
        raise SystemExit("IBM mineral-concession validation failed")


if __name__ == "__main__":
    main()
