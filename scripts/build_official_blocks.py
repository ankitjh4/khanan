#!/usr/bin/env python3
import json
import re
from pathlib import Path

import pandas as pd
from pyproj import Geod
from shapely import wkt
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CONFIG_PATH = ROOT / "config" / "official_critical_blocks.json"
MBS_INVENTORY_PATH = ROOT / "sources" / "raw" / "official_critical_mineral_mbs" / "official_mbs_inventory.json"
BLOCK_TABLE = "india_official_critical_mineral_blocks.csv"
MANIFEST_TABLE = "india_official_critical_mineral_mbs_manifest.csv"
VALIDATION_FILE = "official_critical_blocks_validation.json"

SOURCE_T1 = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1985839&lang=2&reg=48"
SOURCE_T8 = "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2285144&lang=2&reg=48"
SOURCE_MSTC_RESULTS = "https://www.mstcecommerce.com/auctionhome/mlcln/mineral_auction_result.jsp?sellerRefId=31608"
SOURCE_MSTC_MBS = "https://www.mstcecommerce.com/auctionhome/container.jsp?arcDate=30-11-2021&homepage=index&linkid=0&main_link=y&main_link_name=429&portal=mlcl&sublink=n&title_id=Mine+Block+Summary"

ALIASES = {
    "Aluminous Laterite": "Aluminium",
    "Bauxite": "Aluminium",
    "Ilmenite": "Titanium",
    "Limestone": "Calcium and limestone",
    "Magnetite": "Iron",
    "Phosphate": "Phosphorus",
    "Phosphorite": "Phosphorus",
    "Rock phosphate": "Phosphorus",
    "Yttrium": "Rare-earth elements",
}

MATERIAL_NAME_PATTERN = re.compile(
    r"\b(?:graphite|manganese|glauconite|nickel|chromium|pge|ree|rare\s+earth|rare\s+metal|"
    r"lithium|titanium|bauxite|aluminous|laterite|molybdenum|potash|halite|phosphorite|"
    r"phosphate|limestone|tungsten|vanadium|cobalt|iron|magnetite|ilmenite|copper|"
    r"base\s*metal|associated|mineral|rock\s+phosphate|niobium|zirconium|gallium|rm|nb|"
    r"ni|cr|co|ore)\b",
    re.I,
)

BLOCK_DEFINITIONS = {
    "record_id": ("Stable identifier for one official auction observation/event row.", "text", None),
    "record_class": ("Observation type; rows are auction events, not a deduplicated statutory block register.", "category", None),
    "block_lineage_key": ("Normalized name key for linking repeat observations of the same named block; spelling normalization is documented and is not legal entity resolution.", "text", None),
    "auction_event_kind": ("Whether the row records an auction offer/launch or a successful auction result.", "category", None),
    "auction_tranche": ("Central critical-mineral auction tranche number represented by the source row.", "integer", None),
    "auction_status_at_source_date": ("Auction status explicitly limited to the cited source/reference date.", "category", None),
    "block_name": ("Block name as published in the cited Government of India or MSTC source.", "text", None),
    "state_or_ut": ("State or union territory stated for the block.", "text", None),
    "district": ("District stated in the cited result table or mineral block summary, when published.", "text", None),
    "concession_type": ("Published concession type: mining lease (ML) or composite licence (CL).", "category", None),
    "block_area_ha": ("Auction/concession area published in a mineral block summary, when extracted.", "number", "hectares"),
    "latitude": ("Latitude of the representative point derived as the centroid of the published block-boundary polygon; blank without source geometry.", "number", "decimal degrees"),
    "longitude": ("Longitude of the representative point derived as the centroid of the published block-boundary polygon; blank without source geometry.", "number", "decimal degrees"),
    "coordinates_available_in_source": ("Whether source-published boundary coordinates were transcribed for this event row.", "boolean", None),
    "block_boundary_wkt": ("WGS84 polygon transcribed from source-published corner coordinates, closed by the builder; blank without geometry.", "WKT", "EPSG:4326"),
    "geometry_vertex_count": ("Number of distinct published boundary vertices before polygon closure.", "integer", "vertices"),
    "geometry_area_geodesic_ha": ("Geodesic area computed from the transcribed WGS84 polygon using the WGS84 ellipsoid.", "number", "hectares"),
    "geometry_area_difference_pct": ("Absolute percentage difference between computed geodesic area and source-published block area.", "number", "percent"),
    "geometry_type": ("Geometry type of the published footprint (Polygon or MultiPolygon).", "category", None),
    "geometry_extraction_method": ("Documented method used to extract or transform published boundary coordinates.", "category", None),
    "geometry_quality_flag": ("Spatial-quality flag after area and 2011 stated-state boundary checks; source coordinates are retained when flagged.", "category", None),
    "centroid_within_stated_state_2011": ("Whether the source-published footprint centroid falls within the stated state/UT in the 2011 Census district boundary layer.", "boolean", None),
    "spatial_validation_note": ("Qualification for the spatial boundary check, including historical-state handling or a source-location mismatch.", "text", None),
    "source_materials_json": ("JSON array of source mineral/material names published for the block.", "JSON array", None),
    "normalized_top50_materials_json": ("JSON array of source materials mapped to the project's top-50 taxonomy.", "JSON array", None),
    "unmapped_english_material_names_json": ("JSON array of source material names not mapped to the top-50 taxonomy.", "JSON array", None),
    "chemical_names_json": ("JSON array of chemical names inherited from mapped top-50 material definitions.", "JSON array", None),
    "symbols_or_formulae_json": ("JSON array of symbols or formulae inherited from mapped top-50 material definitions.", "JSON array", None),
    "auction_nit_date": ("Notice Inviting Tender date for the represented tranche/event, when available.", "ISO date", None),
    "auction_start_timestamp_ist": ("MSTC auction start timestamp in Indian Standard Time, when published.", "ISO timestamp", "IST (+05:30)"),
    "auction_close_timestamp_ist": ("MSTC auction close timestamp in Indian Standard Time, when published.", "ISO timestamp", "IST (+05:30)"),
    "auction_number": ("MSTC auction number, when published.", "text", None),
    "preferred_bidder": ("Preferred bidder named in the cited result source, when published.", "text", None),
    "mstc_registration_number": ("MSTC registration number printed in the auction-results table, retained as text.", "text", None),
    "highest_final_price_offer_pct": ("Highest/final price offer or auction premium, numeric percent of value of mineral dispatched as printed by the source.", "number", "percent"),
    "source_date": ("Publication date or event-specific reference date supporting the row.", "ISO date", None),
    "source_url": ("Exact Government of India or MSTC source URL supporting the event row.", "URL", None),
    "geometry_source_url": ("Exact mineral block summary PDF URL supporting boundary, area, and district fields, when used.", "URL", None),
    "mbs_source_url": ("Exact official mineral block summary PDF URL for this offer observation.", "URL", None),
    "source_pdf_filename": ("Locally cached official mineral block summary PDF filename.", "text", None),
    "source_pdf_sha256": ("SHA-256 hash of the locally cached official mineral block summary PDF.", "text", None),
    "source_pdf_bytes": ("Byte size of the locally cached official mineral block summary PDF.", "integer", "bytes"),
    "source_pdf_page_count": ("Page count of the locally cached official mineral block summary PDF.", "integer", "pages"),
    "auction_notice_source_url": ("Exact official Notice Inviting Tender PDF URL for the represented tranche.", "URL", None),
    "auction_notice_pdf_filename": ("Locally cached official Notice Inviting Tender PDF filename.", "text", None),
    "auction_notice_pdf_sha256": ("SHA-256 hash of the locally cached official Notice Inviting Tender PDF.", "text", None),
    "auction_notice_pdf_bytes": ("Byte size of the locally cached official Notice Inviting Tender PDF.", "integer", "bytes"),
    "auction_notice_pdf_page_count": ("Page count of the locally cached official Notice Inviting Tender PDF.", "integer", "pages"),
    "concession_type_extraction_method": ("Method used to identify ML/CL, reconciled to the official tranche tender table.", "category", None),
    "extraction_notes": ("Source-specific extraction qualification; blank when none is required.", "text", None),
    "source_accessed_date": ("Date the live MSTC sources were accessed for this curated release.", "ISO date", None),
    "integration_status": ("Explicit spatial-model inclusion/exclusion status and reason.", "category", None),
}

MANIFEST_DEFINITIONS = {
    "event_id": ("Stable tranche/offer observation identifier shared with the auction-event table.", "text", None),
    "auction_tranche": BLOCK_DEFINITIONS["auction_tranche"],
    "portal_link_order": ("One-based order of the block-summary link within its tranche on the MSTC portal index.", "integer", None),
    "block_name": BLOCK_DEFINITIONS["block_name"],
    "state_or_ut": BLOCK_DEFINITIONS["state_or_ut"],
    "district": BLOCK_DEFINITIONS["district"],
    "concession_type": BLOCK_DEFINITIONS["concession_type"],
    "block_area_ha": BLOCK_DEFINITIONS["block_area_ha"],
    "source_materials_json": BLOCK_DEFINITIONS["source_materials_json"],
    "coordinates_available_in_source": BLOCK_DEFINITIONS["coordinates_available_in_source"],
    "geometry_type": BLOCK_DEFINITIONS["geometry_type"],
    "geometry_vertex_count": BLOCK_DEFINITIONS["geometry_vertex_count"],
    "geometry_area_geodesic_ha": BLOCK_DEFINITIONS["geometry_area_geodesic_ha"],
    "geometry_area_difference_pct": BLOCK_DEFINITIONS["geometry_area_difference_pct"],
    "geometry_extraction_method": BLOCK_DEFINITIONS["geometry_extraction_method"],
    "geometry_quality_flag": BLOCK_DEFINITIONS["geometry_quality_flag"],
    "centroid_within_stated_state_2011": BLOCK_DEFINITIONS["centroid_within_stated_state_2011"],
    "spatial_validation_note": BLOCK_DEFINITIONS["spatial_validation_note"],
    "concession_type_extraction_method": BLOCK_DEFINITIONS["concession_type_extraction_method"],
    "source_pdf_filename": BLOCK_DEFINITIONS["source_pdf_filename"],
    "source_pdf_sha256": BLOCK_DEFINITIONS["source_pdf_sha256"],
    "source_pdf_bytes": BLOCK_DEFINITIONS["source_pdf_bytes"],
    "source_pdf_page_count": BLOCK_DEFINITIONS["source_pdf_page_count"],
    "auction_notice_pdf_filename": BLOCK_DEFINITIONS["auction_notice_pdf_filename"],
    "auction_notice_pdf_sha256": BLOCK_DEFINITIONS["auction_notice_pdf_sha256"],
    "auction_notice_pdf_bytes": BLOCK_DEFINITIONS["auction_notice_pdf_bytes"],
    "auction_notice_pdf_page_count": BLOCK_DEFINITIONS["auction_notice_pdf_page_count"],
    "portal_link_title": ("MSTC portal link label retained verbatim after whitespace normalization.", "text", None),
    "source_url": BLOCK_DEFINITIONS["source_url"],
    "mbs_source_url": BLOCK_DEFINITIONS["mbs_source_url"],
    "geometry_source_url": BLOCK_DEFINITIONS["geometry_source_url"],
    "extraction_notes": BLOCK_DEFINITIONS["extraction_notes"],
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def lineage_key(name):
    value = name.lower().replace("&", " and ")
    value = value.replace("biarapalli", "biarpalli").replace("naringapanga", "naringpanga")
    value = value.replace("mine block", "block")
    material = MATERIAL_NAME_PATTERN.search(value)
    if material:
        value = value[:material.start()]
    value = re.sub(r"\b(?:amalgamated|cluster|block)\b", " ", value)
    key = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if key in {"naringpanga", "naringpanga-south"}:
        return "naringpanga-south"
    return key


def material_fields(names, lookup):
    normalized = []
    unmapped = []
    for item in names:
        mapped = ALIASES.get(item, item)
        if mapped in lookup:
            if mapped not in normalized:
                normalized.append(mapped)
        elif item not in unmapped:
            unmapped.append(item)
    chemicals = sorted({chemical for item in normalized for chemical in lookup[item]["chemical_names"]})
    symbols = sorted({symbol for item in normalized for symbol in lookup[item]["symbols_or_formulae"]})
    return normalized, unmapped, chemicals, symbols


def geometry_fields(coordinates, source_area_ha):
    if not coordinates:
        return None, None, False, None, None, None, None
    polygon = Polygon(coordinates)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        raise ValueError("Invalid official-block polygon")
    geod = Geod(ellps="WGS84")
    area_m2, _ = geod.geometry_area_perimeter(polygon)
    area_ha = abs(area_m2) / 10000.0
    difference_pct = abs(area_ha - source_area_ha) / source_area_ha * 100 if source_area_ha else None
    centroid = polygon.centroid
    return centroid.y, centroid.x, True, polygon.wkt, len(coordinates), area_ha, difference_pct


def make_row(event, event_kind, status, source_accessed_date, lookup):
    names = event["materials"]
    normalized, unmapped, chemicals, symbols = material_fields(names, lookup)
    if event.get("geometry_wkt"):
        latitude = event.get("latitude")
        longitude = event.get("longitude")
        has_geometry = True
        boundary_wkt = event["geometry_wkt"]
        vertex_count = event.get("geometry_vertex_count")
        area_ha = event.get("geometry_area_geodesic_ha")
        difference_pct = event.get("geometry_area_difference_pct")
    else:
        latitude, longitude, has_geometry, boundary_wkt, vertex_count, area_ha, difference_pct = geometry_fields(
            event.get("coordinates"), event.get("block_area_ha")
        )
    tranche = int(re.match(r"T(\d+)-", event["event_id"]).group(1))
    source_url = event.get("source_url") or (SOURCE_MSTC_RESULTS if event_kind == "successful_result" else SOURCE_T8)
    return {
        "record_id": f"CMB-EVENT-{event['event_id']}",
        "record_class": "official_critical_mineral_auction_event",
        "block_lineage_key": lineage_key(event["block_name"]),
        "auction_event_kind": event_kind,
        "auction_tranche": tranche,
        "auction_status_at_source_date": status,
        "block_name": event["block_name"],
        "state_or_ut": event["state_or_ut"],
        "district": event.get("district"),
        "concession_type": event["concession_type"],
        "block_area_ha": event.get("block_area_ha"),
        "latitude": latitude,
        "longitude": longitude,
        "coordinates_available_in_source": has_geometry,
        "block_boundary_wkt": boundary_wkt,
        "geometry_vertex_count": vertex_count,
        "geometry_area_geodesic_ha": area_ha,
        "geometry_area_difference_pct": difference_pct,
        "geometry_type": event.get("geometry_type") or (wkt.loads(boundary_wkt).geom_type if boundary_wkt else None),
        "geometry_extraction_method": event.get("geometry_extraction_method"),
        "geometry_quality_flag": event.get("geometry_quality_flag"),
        "centroid_within_stated_state_2011": event.get("centroid_within_stated_state_2011"),
        "spatial_validation_note": event.get("spatial_validation_note"),
        "source_materials_json": dump(names),
        "normalized_top50_materials_json": dump(normalized),
        "unmapped_english_material_names_json": dump(unmapped),
        "chemical_names_json": dump(chemicals),
        "symbols_or_formulae_json": dump(symbols),
        "auction_nit_date": event.get("auction_nit_date"),
        "auction_start_timestamp_ist": event.get("auction_start_timestamp_ist"),
        "auction_close_timestamp_ist": event.get("auction_close_timestamp_ist"),
        "auction_number": event.get("auction_number"),
        "preferred_bidder": event.get("preferred_bidder"),
        "mstc_registration_number": event.get("mstc_registration_number"),
        "highest_final_price_offer_pct": event.get("final_offer_pct"),
        "source_date": event["source_date"],
        "source_url": source_url,
        "geometry_source_url": event.get("geometry_source_url"),
        "mbs_source_url": event.get("mbs_source_url"),
        "source_pdf_filename": event.get("source_pdf_filename"),
        "source_pdf_sha256": event.get("source_pdf_sha256"),
        "source_pdf_bytes": event.get("source_pdf_bytes"),
        "source_pdf_page_count": event.get("source_pdf_page_count"),
        "auction_notice_source_url": event.get("auction_notice_source_url"),
        "auction_notice_pdf_filename": event.get("auction_notice_pdf_filename"),
        "auction_notice_pdf_sha256": event.get("auction_notice_pdf_sha256"),
        "auction_notice_pdf_bytes": event.get("auction_notice_pdf_bytes"),
        "auction_notice_pdf_page_count": event.get("auction_notice_pdf_page_count"),
        "concession_type_extraction_method": event.get("concession_type_extraction_method"),
        "extraction_notes": event.get("extraction_notes"),
        "source_accessed_date": source_accessed_date if "mstcecommerce.com" in (source_url + (event.get("geometry_source_url") or "")) else None,
        "integration_status": "geometry_available_for_overlay_not_used_in_prospectivity_training_or_scoring" if has_geometry else "inventory_only_not_used_in_prospectivity_training_or_scoring_without_exact_public_coordinates_or_polygon",
    }


def update_data_dictionary(frame, manifest):
    path = OUT / "data_dictionary.csv"
    columns = ["table", "column", "definition", "data_type", "unit", "missing_value_policy"]
    dictionary = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=columns)
    dictionary = dictionary[~dictionary["table"].isin([BLOCK_TABLE, MANIFEST_TABLE])]
    rows = []
    for column in frame.columns:
        definition, data_type, unit = BLOCK_DEFINITIONS[column]
        rows.append({
            "table": BLOCK_TABLE,
            "column": column,
            "definition": definition,
            "data_type": data_type,
            "unit": unit,
            "missing_value_policy": "Blank means unavailable/not reported; zero is retained only as a measured or derived zero.",
        })
    for column in manifest.columns:
        definition, data_type, unit = MANIFEST_DEFINITIONS[column]
        rows.append({
            "table": MANIFEST_TABLE,
            "column": column,
            "definition": definition,
            "data_type": data_type,
            "unit": unit,
            "missing_value_policy": "Blank means unavailable/not reported; zero is retained only as a measured or derived zero.",
        })
    pd.concat([dictionary, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)


def update_source_registry():
    path = OUT / "source_registry.csv"
    registry = pd.read_csv(path)
    ids = {
        "SRC_PIB_CRITICAL_BLOCKS_T1",
        "SRC_PIB_CRITICAL_RESULTS_T1",
        "SRC_PIB_CRITICAL_RESULTS_T2_T3",
        "SRC_PIB_CRITICAL_RESULTS_T4_A",
        "SRC_PIB_CRITICAL_RESULTS_T4_B",
        "SRC_PIB_CRITICAL_BLOCKS_T5",
        "SRC_MSTC_CRITICAL_RESULTS_T6_T7",
        "SRC_PIB_CRITICAL_BLOCKS_T8",
        "SRC_MSTC_CRITICAL_MBS_T8",
        "SRC_MSTC_CRITICAL_MBS_T1_T8",
        "SRC_MSTC_CRITICAL_NIT_T1_T8",
    }
    registry = registry[~registry["source_id"].isin(ids)]
    rows = [
        ["SRC_PIB_CRITICAL_BLOCKS_T1", "Press Information Bureau / Ministry of Mines, Government of India", "First tranche: 20 critical and strategic mineral blocks notified for auction", "2023-12-13", SOURCE_T1, "same as URL", "Government publication; retain attribution.", "Tranche-I block offer names, states, minerals, and concession types.", "Summary table provides no exact coordinates or polygons; event status is limited to the release date."],
        ["SRC_PIB_CRITICAL_RESULTS_T1", "Press Information Bureau / Ministry of Mines, Government of India", "Preferred bidders for six first-tranche critical-mineral blocks", "2024-06-24", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2028356&lang=2&reg=3", "same as URL", "Government publication; retain attribution.", "Tranche-I successful-auction results, bidders, and premiums.", "A preferred-bidder result is not proof of final grant, production, reserves/resources, or legal/access feasibility."],
        ["SRC_PIB_CRITICAL_RESULTS_T2_T3", "Press Information Bureau / Ministry of Mines, Government of India", "Preferred bidders for tranches II and III", "2024-07-20", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2034634&lang=2&reg=48", "same as URL", "Government publication; retain attribution.", "Eight successful-auction result rows with state, district, concession, and bidder.", "The table does not publish final price offers or exact block geometry."],
        ["SRC_PIB_CRITICAL_RESULTS_T4_A", "Press Information Bureau / Ministry of Mines, Government of India", "Eight successful tranche-IV critical-mineral block auctions", "2024-11-07", "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2071441&lang=2&reg=48", "same as URL", "Government publication; retain attribution.", "First eight tranche-IV successful-auction results.", "The summary table does not publish exact block geometry."],
        ["SRC_PIB_CRITICAL_RESULTS_T4_B", "Press Information Bureau / Ministry of Mines, Government of India", "Completion of tranche IV with two additional successful block auctions", "2024-11-27", "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2077889&lang=2&reg=48", "same as URL", "Government publication; retain attribution.", "Final two tranche-IV successful-auction results and tranche totals.", "The summary table does not publish exact block geometry."],
        ["SRC_PIB_CRITICAL_BLOCKS_T5", "Press Information Bureau / Ministry of Mines, Government of India", "Tranche V: 10 successfully auctioned critical and strategic mineral blocks", "2025-05-27", "https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2131723&lang=2&reg=48", "same as URL", "Government publication; retain attribution.", "Tranche-V successful-auction results, bidders, and final offers.", "The summary table does not publish exact block geometry."],
        ["SRC_MSTC_CRITICAL_RESULTS_T6_T7", "MSTC Limited / Ministry of Mines auction portal", "Critical Mineral Block Auction Results, FY 2025-26 and FY 2026-27", "accessed 2026-09-10", SOURCE_MSTC_RESULTS, "POST form selections FY 2025-2026 and FY 2026-2027", "Government-owned auction portal; retain source URL, access date, and attribution.", "Named tranche-VI and tranche-VII results, auction numbers/timestamps, bidders, registration numbers, and final offers.", "Dynamic results page; mock-auction rows are excluded. Portal display may change, so values are tied to the stated access date."],
        ["SRC_PIB_CRITICAL_BLOCKS_T8", "Press Information Bureau / Ministry of Mines, Government of India", "Eighth tranche launch: 20 critical and strategic mineral blocks", "2026-07-15", SOURCE_T8, "same as URL", "Government publication; retain attribution.", "Tranche-VIII offer status, tranche count, state totals, and mineral portfolio.", "The release provides aggregate state counts rather than a named block table; named rows are linked to MSTC mineral block summaries."],
        ["SRC_MSTC_CRITICAL_MBS_T1_T8", "MSTC Limited / Ministry of Mines auction portal", "Mineral block summary PDFs for central critical-mineral auction tranches I-VIII", "accessed 2026-09-10", SOURCE_MSTC_MBS, "143 individual PDF links, hashes, byte sizes, and page counts retained in the source manifest", "Government-owned auction portal; retain source document URLs, access date, and attribution.", "Block names, districts, concession areas, material portfolios, and source-published boundary coordinates for 143 non-superseded auction-offer observations.", "Two superseded portal files are excluded. Coordinates are checked against published areas and 2011 state boundaries; legal boundaries and current status must be verified from controlling tender/grant documents."],
        ["SRC_MSTC_CRITICAL_NIT_T1_T8", "MSTC Limited / Ministry of Mines auction portal", "Notices Inviting Tender for central critical-mineral auction tranches I-VIII", "accessed 2026-09-10", "https://www.mstcecommerce.com/auctionhome/container.jsp?title_id=Notice%20Inviting%20Tender&linkid=0&main_link=y&sublink=n&main_link_name=427&portal=mlcl&homepage=index&arcDate=30-11-2021", "eight exact NIT PDF URLs, hashes, byte sizes, and page counts retained in inventory metadata and repeated on offer rows", "Government-owned auction portal; retain source document URLs, access date, and attribution.", "Authoritative tranche dates, lists, first/second-attempt sections, concession types, and fallback coordinate tables where standalone summaries omit them.", "Tender notices describe auction events, not final grants, operating mines, reserves, grade assurance, or permission to access land."],
    ]
    additions = pd.DataFrame(rows, columns=registry.columns)
    pd.concat([registry, additions], ignore_index=True).to_csv(path, index=False)


def main():
    config = json.loads(CONFIG_PATH.read_text())
    inventory = json.loads(MBS_INVENTORY_PATH.read_text())
    materials = json.loads((ROOT / "config" / "materials.json").read_text())
    lookup = {item["material_name"]: item for item in materials}
    accessed = "2026-09-10"
    rows = []
    for event in inventory["records"]:
        rows.append(make_row(event, "auction_offer", "notified for auction", accessed, lookup))
    for event in config["successful_results"]:
        rows.append(make_row(event, "successful_result", "successfully auctioned", accessed, lookup))

    OUT.mkdir(exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / BLOCK_TABLE, index=False)
    update_source_registry()
    manifest = pd.read_csv(OUT / MANIFEST_TABLE)
    update_data_dictionary(frame, manifest)

    offers = frame[frame["auction_event_kind"] == "auction_offer"]
    success = frame[frame["auction_event_kind"] == "successful_result"]
    success_by_tranche = {str(key): int(value) for key, value in success.groupby("auction_tranche").size().items()}
    expected = {"1": 6, "2": 4, "3": 4, "4": 10, "5": 10, "6": 12, "7": 10}
    offer_by_tranche = {str(key): int(value) for key, value in offers.groupby("auction_tranche").size().items()}
    expected_offers = {str(key): value for key, value in inventory["expected_offer_counts_by_tranche"].items()}
    concession_counts = {
        str(tranche): {
            kind: int(len(offers[(offers["auction_tranche"] == tranche) & (offers["concession_type"] == kind)]))
            for kind in ("ML", "CL")
        }
        for tranche in range(1, 9)
    }
    expected_concessions = {str(key): value for key, value in inventory["expected_concession_counts_by_tranche"].items()}
    geometry = offers[offers["coordinates_available_in_source"]]
    maximum_area_difference = float(geometry["geometry_area_difference_pct"].max())
    parsed_geometries = geometry["block_boundary_wkt"].map(wkt.loads)
    mismatch = offers[offers["geometry_quality_flag"] == "source_location_mismatch"]
    offer_lineages = int(offers["block_lineage_key"].nunique())
    checks = {
        "record_count_is_199": len(frame) == 199,
        "record_ids_unique": bool(frame["record_id"].is_unique),
        "offer_count_is_143": len(offers) == 143,
        "offer_counts_match_official_tranche_tender_totals": offer_by_tranche == expected_offers,
        "successful_result_count_is_56": len(success) == 56,
        "successful_counts_match_official_tranche_totals": success_by_tranche == expected,
        "concession_counts_match_official_nit_tables": concession_counts == expected_concessions,
        "all_offer_geometries_complete": len(geometry) == 143,
        "all_offer_geometries_valid": bool(all(item.is_valid and not item.is_empty for item in parsed_geometries)),
        "computed_area_within_5_pct_of_source": maximum_area_difference <= 5,
        "all_offer_pdf_provenance_complete": bool(offers[["source_pdf_filename", "source_pdf_sha256", "source_pdf_bytes", "source_pdf_page_count", "mbs_source_url"]].notna().all().all()),
        "all_offer_nit_provenance_complete": bool(offers[["auction_notice_pdf_filename", "auction_notice_pdf_sha256", "auction_notice_pdf_bytes", "auction_notice_pdf_page_count", "auction_notice_source_url"]].notna().all().all()),
        "source_location_mismatch_is_explicitly_flagged": len(mismatch) == 1 and mismatch.iloc[0]["block_name"].startswith("Biarpalli"),
        "all_successful_results_link_to_an_offer_lineage": bool(set(success["block_lineage_key"]).issubset(set(offers["block_lineage_key"]))),
        "geometry_deduplicated_offer_lineage_count_is_100": offer_lineages == 100,
        "no_geometry_used_as_model_evidence": bool(frame["integration_status"].str.contains("not_used_in_prospectivity").all()),
    }
    validation = {
        "release_version": "v0.6",
        "all_checks_passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "auction_event_rows": len(frame),
            "offer_rows": len(offers),
            "offer_rows_by_tranche": offer_by_tranche,
            "successful_result_rows": len(success),
            "successful_results_by_tranche": success_by_tranche,
            "rows_with_boundary_geometry": len(geometry),
            "distinct_block_lineage_keys": int(frame["block_lineage_key"].nunique()),
            "distinct_offer_lineage_keys": offer_lineages,
            "source_location_mismatch_rows": len(mismatch),
        },
        "geometry": {
            "source": "143 non-superseded MSTC mineral block summary PDFs for tranches I-VIII, with official NIT fallback where documented",
            "coordinates": "WGS84 source-published boundary coordinates; UTM coordinates were transformed to WGS84 where explicitly published",
            "maximum_area_difference_pct": maximum_area_difference,
            "source_accessed_date": accessed,
        },
        "lineage_reconciliation": {
            "source_reported_cumulative_blocks_offered_by_tranche_8": 88,
            "event_rows_extracted_from_eight_tranche_portal_indexes": len(offers),
            "distinct_source_footprint_lineages_reconstructed": offer_lineages,
            "status": "not_reconciled",
            "note": "The 143 portal offer observations resolve to 100 distinct published footprints. This does not reconcile to the PIB release's cumulative 88 figure, so the release preserves event-level evidence and flags the aggregate discrepancy rather than forcing 12 unrelated footprints into shared lineages.",
        },
        "guardrail": "Auction offers and preferred-bidder results are event observations, not proof of production, final legal grant, reserves, resources, grade, economic viability, or permission to enter land. Geometry is provided for overlay and is excluded from prospectivity training/scoring.",
    }
    (OUT / VALIDATION_FILE).write_text(json.dumps(validation, indent=2) + "\n")
    release_validation_path = OUT / "validation_report.json"
    if release_validation_path.exists():
        release_validation = json.loads(release_validation_path.read_text())
        release_validation.update({
            "release_date": accessed,
            "dataset_release_version": "v0.6",
            "official_critical_mineral_auction_event_rows": len(frame),
            "official_critical_mineral_offer_rows": len(offers),
            "official_critical_mineral_offer_rows_by_tranche": offer_by_tranche,
            "official_critical_mineral_successful_result_rows": len(success),
            "official_critical_mineral_successful_results_by_tranche": success_by_tranche,
            "official_critical_mineral_rows_with_boundary_geometry": len(geometry),
            "official_critical_mineral_maximum_geometry_area_difference_pct": maximum_area_difference,
            "official_critical_mineral_distinct_offer_lineage_keys": offer_lineages,
            "official_critical_mineral_pib_reported_cumulative_offer_count": 88,
            "official_critical_mineral_lineage_reconciliation_status": "not_reconciled",
            "official_critical_mineral_guardrail": validation["guardrail"],
        })
        release_validation_path.write_text(json.dumps(release_validation, indent=2) + "\n")
    if not validation["all_checks_passed"]:
        raise RuntimeError(json.dumps(validation, indent=2))
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
