#!/usr/bin/env python3
"""Build IBM IMYB 2024 State Review mineral-occurrence context.

The source is an official IBM compilation, but its place lists are broad and
mix current, historical, renamed and split administrative geographies.  This
builder keeps the published place terms, applies an explicit 2011 Census
district crosswalk, and only admits unambiguous one-to-one matches to the H3
context table.  No output from this script is a mine, discovery, reserve,
resource estimate, grade, licence, or model label.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "ibm_imyb_2024_state_review_occurrences.json"
PDF = ROOT / "sources" / "raw" / "ibm_imyb_2024" / "IMYB_2024_EBookFinal.pdf"
BOUNDARIES = ROOT / "sources" / "raw" / "2011_Dist.shp"
GRID = ROOT / "outputs" / "india_mining_prospectivity_grid_h3_r6.csv"
ONTOLOGY = ROOT / "outputs" / "india_material_ontology_v1.csv"
SOURCE_REGISTRY = ROOT / "outputs" / "source_registry.csv"
DATA_DICTIONARY = ROOT / "outputs" / "data_dictionary.csv"

STATE_OUTPUT = ROOT / "outputs" / "india_ibm_state_mineral_occurrences_2024.csv"
DISTRICT_OUTPUT = ROOT / "outputs" / "india_ibm_district_mineral_occurrences_2024.csv"
H3_OUTPUT = ROOT / "outputs" / "india_ibm_district_mineral_context_h3_r6.csv"
VALIDATION_OUTPUT = ROOT / "outputs" / "ibm_imyb_state_review_occurrences_validation.json"

RELEASE_VERSION = "v1.0-alpha.22"
SOURCE_ID = "SRC_IBM_INDIAN_MINERALS_YEARBOOK_2024_STATE_REVIEWS"


STATE_FIELDS = [
    "record_id", "source_id", "release_version", "source_region",
    "evidence_geography_type", "source_material_term",
    "normalized_material_ids_json", "normalized_material_names_json",
    "chemical_names_json", "symbols_or_formulae_json",
    "chemical_or_english_names_json", "source_place_terms_json",
    "source_place_term_count", "source_pdf_pages_json",
    "source_printed_pages_json", "source_pdf_url", "source_pdf_sha256",
    "source_publication_date", "source_resource_basis_date",
    "source_term_validation_status", "source_place_validation_status",
    "source_transcription_method", "record_observation_type",
    "knowledge_independence_status", "model_evidence_role",
    "model_exclusion_reason", "data_quality_flags_json", "limitations",
]

DISTRICT_FIELDS = [
    "record_id", "parent_occurrence_record_id", "source_id", "release_version",
    "source_region", "source_material_term", "normalized_material_ids_json",
    "normalized_material_names_json", "chemical_names_json",
    "symbols_or_formulae_json", "chemical_or_english_names_json",
    "source_district_term", "district_boundary_state_2011",
    "district_boundary_name_2011", "census_state_code_2011",
    "census_district_code_2011", "district_centroid_latitude_2011",
    "district_centroid_longitude_2011", "census_area_km2_2011_district",
    "census_population_2011_district", "census_male_2011_district",
    "census_female_2011_district", "census_sc_2011_district",
    "census_st_2011_district", "census_literate_2011_district",
    "census_workers_2011_district", "district_crosswalk_status",
    "district_crosswalk_match_index", "district_crosswalk_match_count",
    "district_crosswalk_admitted_to_h3_context", "source_pdf_pages_json",
    "source_pdf_url", "record_observation_type", "model_evidence_role",
    "data_quality_flags_json", "limitations",
]

H3_FIELDS = [
    "h3_r6", "cell_centroid_latitude", "cell_centroid_longitude",
    "state_or_ut_2011", "district_2011", "census_state_code_2011",
    "census_district_code_2011", "grid_area_km2",
    "population_estimate_2020_grid",
    "population_density_estimate_2020_per_km2",
    "census_population_2011_district", "census_male_2011_district",
    "census_female_2011_district", "census_sc_2011_district",
    "census_st_2011_district", "census_literate_2011_district",
    "census_workers_2011_district", "census_area_km2_2011_district",
    "ibm_imyb_2024_district_context_profile_id",
    "ibm_imyb_2024_normalized_material_count",
    "ibm_imyb_2024_source_material_term_count",
    "ibm_imyb_2024_district_occurrence_record_count",
    "ibm_imyb_2024_source_region_count", "source_id", "release_version",
    "record_observation_type", "model_evidence_role",
    "context_inheritance_basis",
    "context_absence_interpretation", "data_quality_flags_json", "limitations",
]


SOURCE_TO_BOUNDARY_STATE = {
    "Arunachal Pradesh": "Arunanchal Pradesh",
    "Delhi": "NCT of Delhi",
    "Telangana": "Andhra Pradesh",
    "Union Territory of Jammu & Kashmir": "Jammu & Kashmir",
    "Ladakh": "Jammu & Kashmir",
}


# Each value is (2011 boundary name(s), crosswalk status).  Multi-match values
# are retained in the district output but are never admitted to H3 context.
DISTRICT_ALIASES: dict[tuple[str, str], tuple[list[str], str]] = {
    ("Andhra Pradesh", "cuddapah"): (["Y.s.r."], "renamed_one_to_one"),
    ("Andhra Pradesh", "nellore"): (["Sri Potti Sriramulu Nellore"], "renamed_one_to_one"),
    ("Assam", "north cachar hills"): (["Dima Hasao"], "renamed_one_to_one"),
    ("Assam", "nowgaon"): (["Nagaon"], "orthographic_one_to_one"),
    ("Assam", "north lakhimpur"): (["Lakhimpur"], "historical_name_one_to_one"),
    ("Bihar", "monghyr"): (["Munger"], "renamed_one_to_one"),
    ("Bihar", "kaimur bhabhua"): (["Kaimur (bhabua)"], "source_spelling_one_to_one"),
    ("Bihar", "purnea"): (["Purnia"], "orthographic_one_to_one"),
    ("Bihar", "jahanabad"): (["Jehanabad"], "orthographic_one_to_one"),
    ("Chhattisgarh", "dantewada"): (["Dakshin Bastar Dantewada"], "expanded_name_one_to_one"),
    ("Chhattisgarh", "kanker"): (["Uttar Bastar Kanker"], "expanded_name_one_to_one"),
    ("Chhattisgarh", "kawardha kabirdham"): (["Kabeerdham"], "renamed_one_to_one"),
    ("Chhattisgarh", "sarguja"): (["Surguja"], "orthographic_one_to_one"),
    ("Gujarat", "banaskantha"): (["Banas Kantha"], "orthographic_one_to_one"),
    ("Gujarat", "sabarkantha"): (["Sabar Kantha"], "orthographic_one_to_one"),
    ("Gujarat", "panchmahals"): (["Panch Mahals"], "orthographic_one_to_one"),
    ("Gujarat", "dahod"): (["Dohad"], "orthographic_one_to_one"),
    ("Himachal Pradesh", "lahaul spiti"): (["Lahul & Spiti"], "orthographic_one_to_one"),
    ("Union Territory of Jammu & Kashmir", "baramulla"): (["Baramula"], "orthographic_one_to_one"),
    ("Union Territory of Jammu & Kashmir", "poonch"): (["Punch"], "orthographic_one_to_one"),
    ("Union Territory of Jammu & Kashmir", "rajauri"): (["Rajouri"], "orthographic_one_to_one"),
    ("Union Territory of Jammu & Kashmir", "leh"): (["Leh (ladakh)"], "administrative_vintage_conflict_one_to_one"),
    ("Jharkhand", "east singhbhum"): (["Purbi Singhbhum"], "translated_direction_one_to_one"),
    ("Jharkhand", "west singhbhum"): (["Pashchimi Singhbhum"], "translated_direction_one_to_one"),
    ("Jharkhand", "sahebganj"): (["Sahibganj"], "orthographic_one_to_one"),
    ("Jharkhand", "koderma"): (["Kodarma"], "orthographic_one_to_one"),
    ("Jharkhand", "palamau"): (["Palamu"], "orthographic_one_to_one"),
    ("Jharkhand", "deogarh"): (["Deoghar"], "orthographic_one_to_one"),
    ("Jharkhand", "saraikela kharaswan"): (["Saraikela-kharsawan"], "source_spelling_one_to_one"),
    ("Karnataka", "belagavi"): (["Belgaum"], "renamed_one_to_one"),
    ("Karnataka", "chikkamagaluru"): (["Chikmagalur"], "renamed_one_to_one"),
    ("Karnataka", "bengaluru"): (["Bangalore"], "renamed_one_to_one"),
    ("Karnataka", "ballari"): (["Bellary"], "renamed_one_to_one"),
    ("Karnataka", "vijayapura"): (["Bijapur"], "renamed_one_to_one"),
    ("Karnataka", "kalaburagi"): (["Gulbarga"], "renamed_one_to_one"),
    ("Karnataka", "mysuru"): (["Mysore"], "renamed_one_to_one"),
    ("Karnataka", "tumakuru"): (["Tumkur"], "renamed_one_to_one"),
    ("Karnataka", "shivamogga"): (["Shimoga"], "renamed_one_to_one"),
    ("Karnataka", "coorg"): (["Kodagu"], "renamed_one_to_one"),
    ("Karnataka", "davangere"): (["Davanagere"], "orthographic_one_to_one"),
    ("Madhya Pradesh", "khandwa"): (["East Nimar"], "historical_name_one_to_one"),
    ("Madhya Pradesh", "khargone"): (["West Nimar"], "historical_name_one_to_one"),
    ("Madhya Pradesh", "narsinghpur"): (["Narsimhapur"], "orthographic_one_to_one"),
    ("Madhya Pradesh", "neemach"): (["Neemuch"], "orthographic_one_to_one"),
    ("Maharashtra", "ahmednagar"): (["Ahmadnagar"], "orthographic_one_to_one"),
    ("Maharashtra", "gadchiroli"): (["Garhchiroli"], "orthographic_one_to_one"),
    ("Maharashtra", "gondia"): (["Gondiya"], "orthographic_one_to_one"),
    ("Maharashtra", "raigad"): (["Raigarh"], "orthographic_one_to_one"),
    ("Odisha", "angul"): (["Anugul"], "orthographic_one_to_one"),
    ("Odisha", "balasore"): (["Baleshwar"], "renamed_one_to_one"),
    ("Odisha", "boudh"): (["Bauda"], "orthographic_one_to_one"),
    ("Odisha", "deogarh"): (["Debagarh"], "orthographic_one_to_one"),
    ("Odisha", "jajpur"): (["Jajapur"], "orthographic_one_to_one"),
    ("Odisha", "khurda"): (["Khordha"], "orthographic_one_to_one"),
    ("Odisha", "sonepur"): (["Subarnapur"], "renamed_one_to_one"),
    ("Punjab", "ropar rupnagar"): (["Rupnagar"], "renamed_one_to_one"),
    ("Rajasthan", "chittorgarh"): (["Chittaurgarh"], "orthographic_one_to_one"),
    ("Rajasthan", "jalore"): (["Jalor"], "orthographic_one_to_one"),
    ("Rajasthan", "jhunjhunu"): (["Jhunjhunun"], "orthographic_one_to_one"),
    ("Rajasthan", "sri ganganagar"): (["Ganganagar"], "shortened_name_one_to_one"),
    ("Sikkim", "east sikkim"): (["East"], "shortened_name_one_to_one"),
    ("Sikkim", "north sikkim"): (["North"], "shortened_name_one_to_one"),
    ("Sikkim", "west sikkim"): (["West"], "shortened_name_one_to_one"),
    ("Tamil Nadu", "kanchipuram"): (["Kancheepuram"], "orthographic_one_to_one"),
    ("Tamil Nadu", "kanyakumari"): (["Kanniyakumari"], "orthographic_one_to_one"),
    ("Tamil Nadu", "nilgiris"): (["The Nilgiris"], "expanded_name_one_to_one"),
    ("Tamil Nadu", "nilgiri"): (["The Nilgiris"], "expanded_name_one_to_one"),
    ("Tamil Nadu", "pudukottai"): (["Pudukkottai"], "orthographic_one_to_one"),
    ("Tamil Nadu", "tiruvallur"): (["Thiruvallur"], "orthographic_one_to_one"),
    ("Tamil Nadu", "tiruvarur"): (["Thiruvarur"], "orthographic_one_to_one"),
    ("Tamil Nadu", "nagapattinam"): (["Nagappattinam"], "orthographic_one_to_one"),
    ("Tamil Nadu", "tiruchirapalli"): (["Tiruchirappalli"], "orthographic_one_to_one"),
    ("Tamil Nadu", "thoothukudi"): (["Thoothukkudi"], "orthographic_one_to_one"),
    ("Tamil Nadu", "villupuram"): (["Viluppuram"], "orthographic_one_to_one"),
    ("Tamil Nadu", "virudhunagar"): (["Virudunagar"], "orthographic_one_to_one"),
    ("Tamil Nadu", "ramnad"): (["Ramanathapuram"], "historical_name_one_to_one"),
    ("Tamil Nadu", "periyar"): (["Erode"], "historical_name_one_to_one"),
    ("Tamil Nadu", "chengai anna"): (["Kancheepuram"], "historical_name_one_to_one"),
    ("Telangana", "rangareddi"): (["Rangareddy"], "orthographic_one_to_one"),
    ("Telangana", "mahabubnagar"): (["Mahbubnagar"], "orthographic_one_to_one"),
    ("Uttar Pradesh", "prayagraj"): (["Allahabad"], "renamed_one_to_one"),
    ("Uttarakhand", "pauri garhwal"): (["Garhwal"], "shortened_name_one_to_one"),
    ("Uttarakhand", "tehri garhwal"): (["Tehri Garhwal"], "punctuation_one_to_one"),
    ("West Bengal", "bardhaman"): (["Barddhaman"], "orthographic_one_to_one"),
    ("West Bengal", "darjeeling"): (["Darjiling"], "orthographic_one_to_one"),
    ("West Bengal", "hooghly"): (["Hugli"], "orthographic_one_to_one"),
    ("West Bengal", "hoogly"): (["Hugli"], "source_spelling_one_to_one"),
    ("West Bengal", "purulia"): (["Puruliya"], "orthographic_one_to_one"),
    ("West Bengal", "24 parganas"): (["North 24 Parganas", "South 24 Parganas"], "historical_parent_one_to_many"),
    ("West Bengal", "midnapur"): (["Pashchim Medinipur", "Purba Medinipur"], "historical_parent_one_to_many"),
}


MATERIAL_ALIASES: dict[str, list[str]] = {
    "antimony": ["element:antimony"],
    "apatite": ["group:apatite-group"],
    "asbestos": ["group:asbestos"],
    "asbestos amphibole": ["group:asbestos"],
    "ball clay": ["group:clay"],
    "barytes": ["mineral:baryte"],
    "calcite": ["group:calcium-and-limestone", "mineral:calcite"],
    "chalk": ["group:calcium-and-limestone", "rock:chalk"],
    "china clay": ["group:kaolin", "mineral:kaolinite"],
    "kaolin": ["group:kaolin", "mineral:kaolinite"],
    "coal": ["commodity:coal"],
    "corundum": ["mineral:corundum"],
    "dolomite": ["mineral:dolomite"],
    "felspar": ["group:feldspar-group"],
    "feldspar": ["group:feldspar-group"],
    "fireclay": ["material:fire-clay", "group:clay"],
    "fire clay": ["material:fire-clay", "group:clay"],
    "fuller s earth": ["group:clay"],
    "garnet": ["group:garnet-group"],
    "gemstones": ["group:gemstones"],
    "granite": ["rock:granite"],
    "iron ore": ["element:iron", "ore:iron-ore"],
    "iron ore haematite": ["element:iron", "ore:iron-ore", "mineral:hematite"],
    "iron ore magnetite": ["element:iron", "ore:iron-ore", "mineral:magnetite"],
    "lead": ["element:lead"],
    "lead zinc": ["element:lead", "element:zinc"],
    "limestone": ["group:calcium-and-limestone", "rock:limestone"],
    "manganese ore": ["element:manganese"],
    "mica": ["group:mica-group"],
    "ochre": ["material:ochre", "material:iron-oxide-pigments"],
    "pyrophyllite": ["mineral:pyrophyllite"],
    "quartz": ["element:silicon", "mineral:quartz"],
    "silica sand": ["element:silicon", "mineral:quartz", "material:sand-and-gravel-industrial"],
    "silica material": ["element:silicon", "mineral:quartz"],
    "quartz silica sand": ["element:silicon", "mineral:quartz", "material:sand-and-gravel-industrial"],
    "quartzite": ["element:silicon", "rock:quartzite"],
    "talc soapstone steatite": ["mineral:talc"],
    "talc steatite soapstone": ["mineral:talc"],
    "talc steatite": ["mineral:talc"],
    "steatite": ["mineral:talc"],
    "vermiculite": ["mineral:vermiculite"],
    "bauxite": ["element:aluminium", "ore:bauxite"],
    "chromite": ["element:chromium", "mineral:chromite"],
    "nickeliferous chromite": ["element:nickel", "element:chromium", "mineral:chromite"],
    "copper": ["element:copper"],
    "copper ore": ["element:copper"],
    "diamond": ["mineral:diamond"],
    "gold": ["element:gold"],
    "graphite": ["mineral:graphite"],
    "gypsum": ["mineral:gypsum"],
    "kyanite": ["mineral:kyanite"],
    "magnesite": ["element:magnesium", "mineral:magnesite"],
    "pyrite": ["mineral:pyrite"],
    "pyrites": ["mineral:pyrite"],
    "sillimanite": ["mineral:sillimanite"],
    "silver": ["element:silver"],
    "titanium": ["element:titanium"],
    "titanium minerals": ["element:titanium", "ore:titanium-mineral-concentrates"],
    "tungsten": ["element:tungsten"],
    "petroleum": ["commodity:petroleum"],
    "natural gas": ["commodity:natural-gas"],
    "dunite": ["group:olivine-group"],
    "dunite pyroxenite": ["group:olivine-group", "group:pyroxene-group"],
    "fluorite": ["element:fluorine", "mineral:fluorite"],
    "fluorspar": ["element:fluorine", "mineral:fluorite"],
    "ruby": ["variety:ruby"],
    "emerald": ["variety:emerald"],
    "platinum group of metals": ["group:platinum-group-elements"],
    "tin": ["element:tin"],
    "vanadiferous magnetite": ["element:vanadium", "element:iron", "mineral:magnetite"],
    "vanadium": ["element:vanadium"],
    "molybdenum": ["element:molybdenum"],
    "potash": ["group:potash"],
    "rock phosphate": ["element:phosphorus", "ore:phosphorite"],
    "marl": ["group:calcium-and-limestone", "rock:marl"],
    "perlite": ["rock:perlite"],
    "diatomite": ["rock:diatomite"],
    "wollastonite": ["mineral:wollastonite"],
    "borax": ["element:boron", "mineral:borax"],
    "sapphire": ["variety:sapphire"],
    "lignite": ["commodity:lignite"],
    "bentonite": ["mineral:montmorillonite", "group:clay"],
    "sulphur": ["element:sulfur", "mineral:sulphur"],
    "diaspore": ["group:kyanite-and-related-minerals"],
    "andalusite": ["mineral:andalusite"],
    "cobalt": ["element:cobalt"],
    "nickel": ["element:nickel"],
    "marble": ["group:calcium-and-limestone"],
    "laterite": ["rock:laterite"],
    "ilmenite": ["element:titanium", "mineral:ilmenite"],
    "rutile": ["element:titanium", "mineral:rutile"],
    "zircon": ["element:zirconium", "mineral:zircon"],
    "monazite": ["group:monazite-group"],
    "glass sand": ["element:silicon", "mineral:quartz", "material:sand-and-gravel-industrial"],
    "plastic clay": ["group:clay"],
    "rock salt": ["mineral:halite"],
}


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_array(values: Any) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def split_materials(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_ontology() -> dict[str, dict[str, str]]:
    rows = load_csv(ONTOLOGY)
    return {row["material_id"]: row for row in rows}


def material_profile(term: str, ontology: dict[str, dict[str, str]]) -> dict[str, str]:
    ids = MATERIAL_ALIASES.get(normalize(term), [])
    missing = [material_id for material_id in ids if material_id not in ontology]
    if missing:
        raise ValueError(f"Material aliases reference missing ontology IDs: {missing}")
    names = [ontology[material_id]["material_name"] for material_id in ids]
    chemical_names: list[str] = []
    formulae: list[str] = []
    for material_id in ids:
        chemical_names.extend(json.loads(ontology[material_id]["chemical_names_json"] or "[]"))
        formulae.extend(json.loads(ontology[material_id]["symbols_or_formulae_json"] or "[]"))
    chemical_names = list(dict.fromkeys(value for value in chemical_names if value))
    formulae = list(dict.fromkeys(value for value in formulae if value))
    display = chemical_names or names or [term]
    return {
        "normalized_material_ids_json": json_array(ids),
        "normalized_material_names_json": json_array(names),
        "chemical_names_json": json_array(chemical_names),
        "symbols_or_formulae_json": json_array(formulae),
        "chemical_or_english_names_json": json_array(display),
    }


def pdf_page_texts(pages: list[int]) -> dict[int, str]:
    from pypdf import PdfReader

    reader = PdfReader(PDF)
    return {page: reader.pages[page - 1].extract_text() or "" for page in pages}


def term_found(term: str, text: str) -> bool:
    needle = normalize(term)
    haystack = normalize(text)
    if needle in haystack:
        return True
    compact_needle = needle.replace(" ", "")
    compact_haystack = haystack.replace(" ", "")
    if len(compact_needle) >= 6 and compact_needle in compact_haystack:
        return True
    shared_phrase_pairs = {
        "north goa": "north and south goa",
        "south goa": "north and south goa",
    }
    if shared_phrase_pairs.get(needle, "") in haystack:
        return True
    removable_suffixes = {
        "coalfield", "coalfields", "deposit", "deposits", "oil field",
        "oilfields", "taluka", "district", "basin", "basins", "area",
        "ultramafic belt",
    }
    for suffix in removable_suffixes:
        suffix_norm = normalize(suffix)
        if needle.endswith(" " + suffix_norm):
            shortened = needle[: -(len(suffix_norm) + 1)].strip()
            if len(shortened) >= 4 and shortened in haystack:
                return True
    alternatives = {
        "haematite": "hematite",
        "pyrites": "pyrite",
        "ultramafic rocks": "ultramafics",
        "bicholim taluka": "bicholim",
        "sanguem taluka": "sanguem",
        "satari taluka": "satari",
        "flux grade districts": "flux grade limestone",
        "chemical grade districts": "chemical grade limestone",
        "cement grade districts": "cement grade deposits",
    }
    return normalize(alternatives.get(needle, "")) in haystack if needle in alternatives else False


def expand_state_rows(config: dict[str, Any], ontology: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    all_pages = sorted({page for chapter in config["chapters"] for page in chapter["pages"]})
    texts = pdf_page_texts(all_pages)
    rows: list[dict[str, Any]] = []
    counter = 0
    for chapter in config["chapters"]:
        pages = chapter["pages"]
        combined_text = "\n".join(texts[page] for page in pages)
        observations: list[tuple[str, str, list[str]]] = []
        for key, places in chapter.get("district_occurrences", {}).items():
            observations.extend(("district_list", term, places) for term in split_materials(key))
        for item in chapter.get("named_area_occurrences", []):
            observations.extend(("named_area_list", term, item["places"]) for term in split_materials(item["materials"]))
        for term in chapter.get("statewide_occurrences", []):
            observations.append(("statewide", term, [chapter["source_region"]]))

        for geography_type, term, places in observations:
            counter += 1
            flags: list[str] = []
            material_status = "found_on_source_pages" if term_found(term, combined_text) else "not_exactly_found_on_source_pages"
            place_checks = [term_found(place, combined_text) for place in places]
            if material_status != "found_on_source_pages":
                flags.append("source_material_term_not_exactly_found_in_pdf_text_extraction")
            if not all(place_checks):
                flags.append("one_or_more_source_place_terms_not_exactly_found_in_pdf_text_extraction")
            profile = material_profile(term, ontology)
            if profile["normalized_material_ids_json"] == "[]":
                flags.append("source_material_term_not_mapped_to_v1_ontology")
            if chapter["source_region"] == "Telangana":
                flags.append("source_region_postdates_2011_boundary_layer")
            if chapter["source_region"] in {"Union Territory of Jammu & Kashmir", "Ladakh"}:
                flags.append("source_and_boundary_administrative_vintages_differ")
            record_type = chapter.get("observation_type_override", "official_compiled_mineral_occurrence_context")
            rows.append({
                "record_id": f"IBM-IMYB2024-STATE-OCC-{counter:04d}",
                "source_id": SOURCE_ID,
                "release_version": RELEASE_VERSION,
                "source_region": chapter["source_region"],
                "evidence_geography_type": geography_type,
                "source_material_term": term,
                **profile,
                "source_place_terms_json": json_array(places),
                "source_place_term_count": len(places),
                "source_pdf_pages_json": json_array(pages),
                "source_printed_pages_json": json_array([page - 15 for page in pages]),
                "source_pdf_url": config["source_pdf_url"],
                "source_pdf_sha256": config["source_pdf_sha256"],
                "source_publication_date": config["source_publication_date"],
                "source_resource_basis_date": "2020-04-01 for the chapter's NMI resource tables; occurrence prose is undated within IMYB 2024",
                "source_term_validation_status": material_status,
                "source_place_validation_status": "all_found_on_source_pages" if all(place_checks) else f"{sum(place_checks)}_of_{len(place_checks)}_found_on_source_pages",
                "source_transcription_method": "curated_page-referenced_transcription_with_machine_text_presence_checks",
                "record_observation_type": record_type,
                "knowledge_independence_status": "official_compilation_not_independently_field_verified_by_khanan",
                "model_evidence_role": "excluded_context_only",
                "model_exclusion_reason": "Broad compiled occurrence geography can overlap source evidence and is not an independent point, assay, reserve, mine or discovery label.",
                "data_quality_flags_json": json_array(flags),
                "limitations": "The IBM State Reviews compile information from multiple sources and advise reader discretion. Place lists mix districts, historical names, named belts, fields and basins; occurrence does not establish grade, quantity, continuity, current legality, economics, access or a new discovery.",
            })
    return rows


def boundary_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    districts = gpd.read_file(BOUNDARIES).to_crs("EPSG:4326")
    projected = districts.to_crs("EPSG:7755")
    points = projected.geometry.representative_point().to_crs("EPSG:4326")
    catalog: dict[str, dict[str, Any]] = {}
    normalized: dict[str, dict[str, str]] = defaultdict(dict)
    for index, row in districts.iterrows():
        state = str(row["ST_NM"])
        district = str(row["DISTRICT"])
        key = f"{state}\u241f{district}"
        catalog[key] = {
            "state": state,
            "district": district,
            "state_code": str(row["ST_CEN_CD"]),
            "district_code": str(row["DT_CEN_CD"]),
            "latitude": round(float(points.iloc[index].y), 8),
            "longitude": round(float(points.iloc[index].x), 8),
        }
        normalized[state][normalize(district)] = district
    return catalog, normalized


def crosswalk_district(
    source_region: str,
    source_term: str,
    normalized_boundaries: dict[str, dict[str, str]],
) -> tuple[str, list[str]]:
    boundary_state = SOURCE_TO_BOUNDARY_STATE.get(source_region, source_region)
    alias = DISTRICT_ALIASES.get((source_region, normalize(source_term)))
    if alias:
        return alias[1], alias[0]
    exact = normalized_boundaries.get(boundary_state, {}).get(normalize(source_term))
    if exact:
        status = "exact_normalized_one_to_one"
        if source_region == "Telangana":
            status = "post_2011_state_split_district_one_to_one"
        return status, [exact]
    return "unmatched", []


def load_district_demographics() -> dict[tuple[str, str], dict[str, str]]:
    wanted = {
        "census_area_km2_2011_district", "census_population_2011_district",
        "census_male_2011_district", "census_female_2011_district",
        "census_sc_2011_district", "census_st_2011_district",
        "census_literate_2011_district", "census_workers_2011_district",
    }
    result: dict[tuple[str, str], dict[str, str]] = {}
    with GRID.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (row["state_or_ut_2011"], row["district_2011"])
            if key not in result:
                result[key] = {field: row[field] for field in wanted}
    return result


def expand_district_rows(
    state_rows: list[dict[str, Any]],
    boundary_rows: dict[str, dict[str, Any]],
    normalized_boundaries: dict[str, dict[str, str]],
    demographics: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counter = 0
    for parent in state_rows:
        if parent["evidence_geography_type"] != "district_list":
            continue
        for source_term in json.loads(parent["source_place_terms_json"]):
            status, matches = crosswalk_district(parent["source_region"], source_term, normalized_boundaries)
            if not matches:
                matches = [""]
            for match_index, district in enumerate(matches, start=1):
                counter += 1
                boundary_state = SOURCE_TO_BOUNDARY_STATE.get(parent["source_region"], parent["source_region"])
                boundary = boundary_rows.get(f"{boundary_state}\u241f{district}", {})
                demo = demographics.get((boundary_state, district), {})
                admitted = bool(district) and len(matches) == 1
                flags = json.loads(parent["data_quality_flags_json"])
                if status == "unmatched":
                    flags.append("source_district_term_unmatched_to_2011_boundary")
                elif len(matches) > 1:
                    flags.append("historical_source_district_crosswalk_is_one_to_many")
                if "administrative_vintage_conflict" in status:
                    flags.append("administrative_vintage_conflict")
                rows.append({
                    "record_id": f"IBM-IMYB2024-DIST-OCC-{counter:05d}",
                    "parent_occurrence_record_id": parent["record_id"],
                    "source_id": SOURCE_ID,
                    "release_version": RELEASE_VERSION,
                    "source_region": parent["source_region"],
                    "source_material_term": parent["source_material_term"],
                    "normalized_material_ids_json": parent["normalized_material_ids_json"],
                    "normalized_material_names_json": parent["normalized_material_names_json"],
                    "chemical_names_json": parent["chemical_names_json"],
                    "symbols_or_formulae_json": parent["symbols_or_formulae_json"],
                    "chemical_or_english_names_json": parent["chemical_or_english_names_json"],
                    "source_district_term": source_term,
                    "district_boundary_state_2011": boundary.get("state", ""),
                    "district_boundary_name_2011": boundary.get("district", ""),
                    "census_state_code_2011": boundary.get("state_code", ""),
                    "census_district_code_2011": boundary.get("district_code", ""),
                    "district_centroid_latitude_2011": boundary.get("latitude", ""),
                    "district_centroid_longitude_2011": boundary.get("longitude", ""),
                    "census_area_km2_2011_district": demo.get("census_area_km2_2011_district", ""),
                    "census_population_2011_district": demo.get("census_population_2011_district", ""),
                    "census_male_2011_district": demo.get("census_male_2011_district", ""),
                    "census_female_2011_district": demo.get("census_female_2011_district", ""),
                    "census_sc_2011_district": demo.get("census_sc_2011_district", ""),
                    "census_st_2011_district": demo.get("census_st_2011_district", ""),
                    "census_literate_2011_district": demo.get("census_literate_2011_district", ""),
                    "census_workers_2011_district": demo.get("census_workers_2011_district", ""),
                    "district_crosswalk_status": status,
                    "district_crosswalk_match_index": match_index,
                    "district_crosswalk_match_count": len(matches) if district else 0,
                    "district_crosswalk_admitted_to_h3_context": admitted,
                    "source_pdf_pages_json": parent["source_pdf_pages_json"],
                    "source_pdf_url": parent["source_pdf_url"],
                    "record_observation_type": "official_compiled_district_mineral_occurrence_context",
                    "model_evidence_role": "excluded_context_only",
                    "data_quality_flags_json": json_array(list(dict.fromkeys(flags))),
                    "limitations": "District-level occurrence context is spatially broad. The representative district coordinate is an indexing point, not the occurrence location or a drill target. Only unambiguous one-to-one 2011 crosswalks enter the H3 context table.",
                })
    return rows


def aggregate_district_context(district_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, list[str]]]:
    fields = {
        "material_ids": "normalized_material_ids_json",
        "material_names": "normalized_material_names_json",
        "display_names": "chemical_or_english_names_json",
        "source_terms": "source_material_term",
        "source_regions": "source_region",
        "record_ids": "record_id",
    }
    result: dict[tuple[str, str], dict[str, list[str]]] = {}
    for row in district_rows:
        if row["district_crosswalk_admitted_to_h3_context"] is not True:
            continue
        key = (row["district_boundary_state_2011"], row["district_boundary_name_2011"])
        bucket = result.setdefault(key, {name: [] for name in fields})
        for name, field in fields.items():
            values = json.loads(row[field]) if field.endswith("_json") else [row[field]]
            bucket[name].extend(value for value in values if value)
    for bucket in result.values():
        for name in bucket:
            bucket[name] = sorted(set(bucket[name]))
    return result


def build_h3_rows(context: dict[tuple[str, str], dict[str, list[str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with GRID.open(newline="", encoding="utf-8-sig") as handle:
        for source in csv.DictReader(handle):
            key = (source["state_or_ut_2011"], source["district_2011"])
            bucket = context.get(key)
            if not bucket:
                continue
            flags: list[str] = ["district_occurrence_context_spatially_broad"]
            if source["state_or_ut_2011"] == "Andhra Pradesh" and "Telangana" in bucket["source_regions"]:
                flags.append("2011_boundary_predates_telangana_statehood")
            if source["state_or_ut_2011"] == "Jammu & Kashmir" and any(
                region in {"Union Territory of Jammu & Kashmir", "Ladakh"} for region in bucket["source_regions"]
            ):
                flags.append("2011_boundary_predates_2019_union_territory_reorganization")
            rows.append({
                "h3_r6": source["h3_r6"],
                "cell_centroid_latitude": source["latitude"],
                "cell_centroid_longitude": source["longitude"],
                "state_or_ut_2011": source["state_or_ut_2011"],
                "district_2011": source["district_2011"],
                "census_state_code_2011": source["census_state_code_2011"],
                "census_district_code_2011": source["census_district_code_2011"],
                "grid_area_km2": source["grid_area_km2"],
                "population_estimate_2020_grid": source["population_estimate_2020_grid"],
                "population_density_estimate_2020_per_km2": source["population_density_estimate_2020_per_km2"],
                "census_population_2011_district": source["census_population_2011_district"],
                "census_male_2011_district": source["census_male_2011_district"],
                "census_female_2011_district": source["census_female_2011_district"],
                "census_sc_2011_district": source["census_sc_2011_district"],
                "census_st_2011_district": source["census_st_2011_district"],
                "census_literate_2011_district": source["census_literate_2011_district"],
                "census_workers_2011_district": source["census_workers_2011_district"],
                "census_area_km2_2011_district": source["census_area_km2_2011_district"],
                "ibm_imyb_2024_district_context_profile_id": f"IBM-IMYB2024-DISTCTX-{source['census_state_code_2011']}-{source['census_district_code_2011']}",
                "ibm_imyb_2024_normalized_material_count": len(bucket["material_ids"]),
                "ibm_imyb_2024_source_material_term_count": len(bucket["source_terms"]),
                "ibm_imyb_2024_district_occurrence_record_count": len(bucket["record_ids"]),
                "ibm_imyb_2024_source_region_count": len(bucket["source_regions"]),
                "source_id": SOURCE_ID,
                "release_version": RELEASE_VERSION,
                "record_observation_type": "district_context_join_to_h3_cell",
                "model_evidence_role": "excluded_context_only",
                "context_inheritance_basis": "matched_2011_district; join detailed materials through state_or_ut_2011 and district_2011",
                "context_absence_interpretation": "Sparse rows only; absence is not mineral absence.",
                "data_quality_flags_json": json_array(flags),
                "limitations": "District-inherited context; not H3-point evidence or a prediction.",
            })
    return rows


def update_source_registry(config: dict[str, Any]) -> None:
    rows = load_csv(SOURCE_REGISTRY)
    fields = list(rows[0])
    rows = [row for row in rows if row["source_id"] != SOURCE_ID]
    rows.append({
        "source_id": SOURCE_ID,
        "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
        "title": "Indian Minerals Yearbook 2024 — State Reviews",
        "release_or_reference_date": "2024 reporting year; PDF created 2026-03-11; NMI resource tables mostly as at 2020-04-01",
        "url": config["source_pdf_url"],
        "download_url": config["source_pdf_url"],
        "license_or_access_note": "Government of India public PDF; no blanket reuse licence asserted by KHANAN. Retain attribution and consult current IBM terms.",
        "used_for": "Official compiled State/UT mineral-occurrence geography, with district, named-area and statewide scope preserved separately.",
        "limitations": "IBM says the Yearbook is internally collated from multiple divisions and sources, advises reader discretion and disclaims warranties. Occurrence prose is not a mine register, assay, reserve, grade, legal status, operating status or new discovery. Administrative names and vintages vary.",
    })
    write_csv(SOURCE_REGISTRY, fields, rows)


def update_data_dictionary() -> None:
    rows = load_csv(DATA_DICTIONARY)
    fields = list(rows[0])
    tables = {
        "india_ibm_state_mineral_occurrences_2024": STATE_FIELDS,
        "india_ibm_district_mineral_occurrences_2024": DISTRICT_FIELDS,
        "india_ibm_district_mineral_context_h3_r6": H3_FIELDS,
    }
    rows = [row for row in rows if row["table"] not in tables]
    definitions = {
        "record_id": "Stable KHANAN record identifier.",
        "parent_occurrence_record_id": "State-occurrence record from which this district row was exploded.",
        "source_id": "Source registry identifier.",
        "release_version": "KHANAN development release that introduced the row.",
        "source_region": "State or Union Territory chapter label in the IBM source; it may differ from 2011 boundaries.",
        "evidence_geography_type": "Source geography class: district list, named-area list, or statewide.",
        "source_material_term": "Material wording transcribed from the source occurrence prose.",
        "normalized_material_ids_json": "JSON array of linked KHANAN v1 ontology identifiers; empty when unresolved.",
        "normalized_material_names_json": "JSON array of linked KHANAN v1 ontology names.",
        "chemical_names_json": "JSON array of defensible chemical names inherited from linked ontology entities.",
        "symbols_or_formulae_json": "JSON array of symbols or formulae inherited from linked ontology entities.",
        "chemical_or_english_names_json": "Chemical names when available; otherwise normalized or source English names, as a JSON array.",
        "source_place_terms_json": "JSON array of published district, field, belt, basin or statewide place terms.",
        "source_place_term_count": "Number of published place terms attached to the occurrence row.",
        "source_pdf_pages_json": "JSON array of one-based physical PDF pages reviewed for the row.",
        "source_printed_pages_json": "JSON array of printed Yearbook page numbers corresponding to physical PDF pages.",
        "source_pdf_url": "Direct official IBM PDF URL.",
        "source_pdf_sha256": "SHA-256 digest of the reviewed source PDF.",
        "source_publication_date": "Date encoded by the source PDF metadata or official publication context.",
        "source_resource_basis_date": "Temporal interpretation of the chapter occurrence/resource context.",
        "source_term_validation_status": "Whether the curated material term was found in extracted source-page text.",
        "source_place_validation_status": "Count/status of curated place terms found in extracted source-page text.",
        "source_transcription_method": "How source terms were transcribed and checked.",
        "record_observation_type": "Semantic observation type; distinguishes context from sites, discoveries and model predictions.",
        "knowledge_independence_status": "Whether KHANAN independently field-verified the compiled occurrence.",
        "model_evidence_role": "Role in the prospectivity pipeline; all rows in this layer are context-only.",
        "model_exclusion_reason": "Reason the record cannot train, validate or rerank the model.",
        "data_quality_flags_json": "JSON array of row-level limitations or administrative/source anomalies.",
        "limitations": "Human-readable interpretation boundary.",
        "source_district_term": "District wording printed in the IBM State Review.",
        "district_boundary_state_2011": "Matched state/UT name in the 2011 district boundary layer.",
        "district_boundary_name_2011": "Matched district name in the 2011 boundary layer.",
        "census_state_code_2011": "2011 Census state code from the boundary/grid framework.",
        "census_district_code_2011": "2011 Census district code from the boundary/grid framework.",
        "district_centroid_latitude_2011": "Representative point latitude for the matched 2011 district; not an occurrence coordinate.",
        "district_centroid_longitude_2011": "Representative point longitude for the matched 2011 district; not an occurrence coordinate.",
        "census_area_km2_2011_district": "2011 Census district area inherited from the KHANAN grid.",
        "census_population_2011_district": "2011 Census district population inherited from the KHANAN grid.",
        "census_male_2011_district": "2011 Census district male population.",
        "census_female_2011_district": "2011 Census district female population.",
        "census_sc_2011_district": "2011 Census district Scheduled Caste population.",
        "census_st_2011_district": "2011 Census district Scheduled Tribe population.",
        "census_literate_2011_district": "2011 Census district literate population.",
        "census_workers_2011_district": "2011 Census district worker population.",
        "district_crosswalk_status": "Explicit relationship between source district wording and a 2011 boundary.",
        "district_crosswalk_match_index": "One-based candidate index when a source district maps to multiple 2011 districts.",
        "district_crosswalk_match_count": "Number of 2011 boundary candidates for the source district term.",
        "district_crosswalk_admitted_to_h3_context": "True only for a resolved one-to-one district crosswalk.",
        "h3_r6": "H3 resolution-6 cell identifier from the KHANAN national grid.",
        "cell_centroid_latitude": "H3 cell-centroid latitude used for indexing, not an occurrence coordinate.",
        "cell_centroid_longitude": "H3 cell-centroid longitude used for indexing, not an occurrence coordinate.",
        "state_or_ut_2011": "Containing 2011 state/UT from the KHANAN grid.",
        "district_2011": "Containing 2011 district from the KHANAN grid.",
        "grid_area_km2": "H3 cell polygon area in square kilometres.",
        "population_estimate_2020_grid": "WorldPop 2020 estimated population summed for the H3 cell.",
        "population_density_estimate_2020_per_km2": "WorldPop 2020 estimated H3 population divided by cell area.",
        "ibm_imyb_2024_district_context_profile_id": "Stable profile key for the containing 2011 district; detailed materials join through the district occurrence table.",
        "ibm_imyb_2024_normalized_material_count": "Count of unique linked ontology entities in the containing district profile.",
        "ibm_imyb_2024_source_material_term_count": "Count of unique IBM source material terms in the containing district profile.",
        "ibm_imyb_2024_district_occurrence_record_count": "Count of admitted district occurrence records in the containing district profile.",
        "ibm_imyb_2024_source_region_count": "Count of IBM source-region chapters contributing to the district profile.",
        "context_inheritance_basis": "District join key and location of detailed material records.",
        "context_absence_interpretation": "Required statement that sparse-table absence is not mineral absence.",
    }
    units = {
        "district_centroid_latitude_2011": "decimal degrees",
        "district_centroid_longitude_2011": "decimal degrees",
        "cell_centroid_latitude": "decimal degrees",
        "cell_centroid_longitude": "decimal degrees",
        "grid_area_km2": "km2",
        "census_area_km2_2011_district": "km2",
        "population_density_estimate_2020_per_km2": "people/km2",
    }
    integer_fields = {
        "source_place_term_count", "district_crosswalk_match_index",
        "district_crosswalk_match_count", "ibm_imyb_2024_normalized_material_count",
        "ibm_imyb_2024_source_material_term_count",
        "ibm_imyb_2024_district_occurrence_record_count",
        "ibm_imyb_2024_source_region_count",
        "census_population_2011_district", "census_male_2011_district",
        "census_female_2011_district", "census_sc_2011_district",
        "census_st_2011_district", "census_literate_2011_district",
        "census_workers_2011_district",
    }
    numeric_fields = {
        "district_centroid_latitude_2011", "district_centroid_longitude_2011",
        "cell_centroid_latitude", "cell_centroid_longitude", "grid_area_km2",
        "census_area_km2_2011_district", "population_estimate_2020_grid",
        "population_density_estimate_2020_per_km2",
    }
    boolean_fields = {"district_crosswalk_admitted_to_h3_context"}
    for table, columns in tables.items():
        for column in columns:
            dtype = "string"
            if column in integer_fields:
                dtype = "integer"
            elif column in numeric_fields:
                dtype = "number"
            elif column in boolean_fields:
                dtype = "boolean"
            elif column.endswith("_json"):
                dtype = "JSON array"
            rows.append({
                "table": table,
                "column": column,
                "definition": definitions.get(column, column.replace("_", " ").capitalize() + "."),
                "data_type": dtype,
                "unit": units.get(column, ""),
                "missing_value_policy": "Blank means unavailable, unresolved or not applicable; it never means zero or absence." if column not in boolean_fields else "Required true/false value.",
            })
    write_csv(DATA_DICTIONARY, fields, rows)


def validate(
    config: dict[str, Any],
    state_rows: list[dict[str, Any]],
    district_rows: list[dict[str, Any]],
    h3_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    state_ids = [row["record_id"] for row in state_rows]
    district_ids = [row["record_id"] for row in district_rows]
    h3_ids = [row["h3_r6"] for row in h3_rows]
    unmatched = [row for row in district_rows if row["district_crosswalk_status"] == "unmatched"]
    admitted = [row for row in district_rows if row["district_crosswalk_admitted_to_h3_context"] is True]
    one_to_many = [row for row in district_rows if row["district_crosswalk_match_count"] > 1]
    unresolved_materials = sorted({
        row["source_material_term"] for row in state_rows
        if row["normalized_material_ids_json"] == "[]"
    })
    material_term_mismatches = [row["record_id"] for row in state_rows if row["source_term_validation_status"] != "found_on_source_pages"]
    place_term_mismatches = [row["record_id"] for row in state_rows if row["source_place_validation_status"] != "all_found_on_source_pages"]
    report = {
        "release_version": RELEASE_VERSION,
        "source_id": SOURCE_ID,
        "source_pdf_url": config["source_pdf_url"],
        "source_pdf_sha256_expected": config["source_pdf_sha256"],
        "source_pdf_sha256_observed": sha256_file(PDF),
        "source_chapter_count": len(config["chapters"]),
        "state_occurrence_rows": len(state_rows),
        "district_occurrence_rows": len(district_rows),
        "district_occurrence_source_mentions": sum(1 for row in district_rows if row["district_crosswalk_match_index"] == 1),
        "district_occurrence_rows_admitted_to_h3_context": len(admitted),
        "district_occurrence_rows_unmatched": len(unmatched),
        "district_occurrence_rows_one_to_many": len(one_to_many),
        "h3_context_rows": len(h3_rows),
        "unique_h3_context_cells": len(set(h3_ids)),
        "unique_source_material_terms": len({row["source_material_term"] for row in state_rows}),
        "unique_normalized_material_ids": len({value for row in state_rows for value in json.loads(row["normalized_material_ids_json"])}),
        "unresolved_source_material_terms": unresolved_materials,
        "unmatched_source_district_terms": sorted({f'{row["source_region"]}: {row["source_district_term"]}' for row in unmatched}),
        "material_term_text_mismatch_record_ids": material_term_mismatches,
        "place_term_text_mismatch_record_ids": place_term_mismatches,
        "checks": {
            "source_pdf_hash_matches": sha256_file(PDF) == config["source_pdf_sha256"],
            "state_record_ids_unique": len(state_ids) == len(set(state_ids)),
            "district_record_ids_unique": len(district_ids) == len(set(district_ids)),
            "h3_ids_unique": len(h3_ids) == len(set(h3_ids)),
            "district_parent_ids_resolve": all(row["parent_occurrence_record_id"] in set(state_ids) for row in district_rows),
            "admitted_crosswalks_are_one_to_one": all(row["district_crosswalk_match_count"] == 1 for row in admitted),
            "h3_context_nonempty": len(h3_rows) > 0,
            "all_model_roles_excluded": all(row["model_evidence_role"] == "excluded_context_only" for row in state_rows + district_rows + h3_rows),
        },
        "interpretation_contract": {
            "is_mine_register": False,
            "is_new_discovery": False,
            "is_reserve_or_resource_estimate": False,
            "is_assay_or_grade": False,
            "is_legal_or_access_authorization": False,
            "used_in_model_training_scoring_or_validation": False,
            "district_context_is_uniform_within_district": False,
            "h3_centroid_is_occurrence_location": False,
        },
    }
    if not all(report["checks"].values()):
        raise RuntimeError(f"Validation failed: {report['checks']}")
    return report


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if sha256_file(PDF) != config["source_pdf_sha256"]:
        raise RuntimeError("Source PDF SHA-256 does not match the curated extraction config")
    ontology = load_ontology()
    state_rows = expand_state_rows(config, ontology)
    boundary_rows, normalized_boundaries = boundary_catalog()
    demographics = load_district_demographics()
    district_rows = expand_district_rows(state_rows, boundary_rows, normalized_boundaries, demographics)
    context = aggregate_district_context(district_rows)
    h3_rows = build_h3_rows(context)
    report = validate(config, state_rows, district_rows, h3_rows)

    write_csv(STATE_OUTPUT, STATE_FIELDS, state_rows)
    write_csv(DISTRICT_OUTPUT, DISTRICT_FIELDS, district_rows)
    write_csv(H3_OUTPUT, H3_FIELDS, h3_rows)
    VALIDATION_OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_source_registry(config)
    update_data_dictionary()
    print(json.dumps({
        "state_rows": len(state_rows),
        "district_rows": len(district_rows),
        "h3_rows": len(h3_rows),
        "unmatched_district_terms": len(report["unmatched_source_district_terms"]),
        "unresolved_material_terms": len(report["unresolved_source_material_terms"]),
        "material_text_mismatches": len(report["material_term_text_mismatch_record_ids"]),
        "place_text_mismatches": len(report["place_term_text_mismatch_record_ids"]),
    }, indent=2))


if __name__ == "__main__":
    main()
