#!/usr/bin/env python3
"""Build known-site and nationwide mining-prospectivity CSV datasets for India.

The prospectivity score is a reconnaissance screening index, not a probability
of discovery or a mineral-resource estimate. It uses public occurrence points,
mapped geological units, distance, and local occurrence density. It does not
replace geochemical sampling, geophysics, drilling, resource classification,
environmental review, land access, or community consultation.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import date
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin, rowcol
from scipy.stats import rankdata
from shapely.geometry import Point, Polygon
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import BallTree


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw"
OUT = ROOT / "outputs"
CONFIG = ROOT / "config"
H3_RESOLUTION = 6
MODEL_VERSION = "recon-screening-v0.1.0"
EARTH_RADIUS_KM = 6371.0088
WEATHER_CONFIG = json.loads((CONFIG / "weather_window.json").read_text(encoding="utf-8"))
WEATHER_START = date.fromisoformat(WEATHER_CONFIG["reference_period_start"])
WEATHER_END = date.fromisoformat(WEATHER_CONFIG["reference_period_end"])
WEATHER_EXPECTED_DAYS = (WEATHER_END - WEATHER_START).days + 1
WEATHER_MONTH_LABELS = [
    period.strftime("%Y-%m")
    for period in pd.period_range(WEATHER_START, WEATHER_END, freq="M")
]
POWER_DIR = RAW / f"nasa_power_daily_rolling_12m_{WEATHER_START.isoformat()}_{WEATHER_END.isoformat()}"


SOURCE_REGISTRY = [
    {
        "source_id": "SRC_USGS_MRDS",
        "publisher": "U.S. Geological Survey",
        "title": "Mineral Resources Data System (MRDS), CSV extract",
        "release_or_reference_date": "2022-08-23",
        "url": "https://mrdata.usgs.gov/mrds/",
        "download_url": "https://mrdata.usgs.gov/mrds/mrds-csv.zip",
        "license_or_access_note": "U.S. federal government data; verify source-specific reuse terms and citations.",
        "used_for": "Known mines, past producers, prospects, occurrences, commodities, and source geological descriptions.",
        "limitations": "India coverage is useful but not an exhaustive or current statutory register; many records are historical and point precision varies.",
    },
    {
        "source_id": "SRC_ESRI_INDIA_GEOLOGY",
        "publisher": "Esri India Living Atlas",
        "title": "India Geology feature service",
        "release_or_reference_date": "service accessed 2026-09-09",
        "url": "https://livingatlas.esri.in/server1/rest/services/Geology/Geology/MapServer",
        "download_url": "ArcGIS REST query against layer 0",
        "license_or_access_note": "Publicly queryable service; item metadata does not state a reuse license. Dataset exports contain only sampled unit attributes, not redistributed polygons.",
        "used_for": "Geological age, supergroup, group, and stratigraphy sampled at H3 cell centroids.",
        "limitations": "Service metadata does not identify polygon provenance or license; map-unit scale and positional accuracy are not stated.",
    },
    {
        "source_id": "SRC_CENSUS_PCA_2011",
        "publisher": "Office of the Registrar General & Census Commissioner, India",
        "title": "Basic Population Figures of India/State/District/Sub-District/Village, Primary Census Abstract 2011",
        "release_or_reference_date": "2011",
        "url": "https://www.censusindia.gov.in/nada/index.php/catalog/42559",
        "download_url": "https://censusindia.gov.in/nada/index.php/catalog/42559/download/46185/2011-IndiaStateDistSbDistTwn-0000.xlsx",
        "license_or_access_note": "Government of India census publication; retain attribution and verify website terms for redistribution.",
        "used_for": "District population, households, sex, ages 0-6, Scheduled Caste/Tribe, literacy, and work participation.",
        "limitations": "2011 reference geography and population; not a current population count.",
    },
    {
        "source_id": "SRC_CENSUS_A01_2011",
        "publisher": "Office of the Registrar General & Census Commissioner, India",
        "title": "A-01 Number of villages, towns, households, population and area",
        "release_or_reference_date": "2011",
        "url": "https://www.censusindia.gov.in/nada/index.php/catalog/42526",
        "download_url": "https://censusindia.gov.in/nada/index.php/catalog/42526/download/46152/A-1_NO_OF_VILLAGES_TOWNS_HOUSEHOLDS_POPULATION_AND_AREA.xlsx",
        "license_or_access_note": "Government of India census publication; retain attribution and verify website terms for redistribution.",
        "used_for": "Census 2011 district area and population density.",
        "limitations": "2011 administrative geography.",
    },
    {
        "source_id": "SRC_DATAMEET_DISTRICTS_2011",
        "publisher": "DataMeet India community",
        "title": "India Census 2011 district boundaries",
        "release_or_reference_date": "repository accessed 2026-09-09",
        "url": "https://github.com/datameet/maps/tree/master/Districts/Census_2011",
        "download_url": "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.shp",
        "license_or_access_note": "CC BY 2.5 India as stated in the directory README.",
        "used_for": "Spatial assignment to 2011 Census districts.",
        "limitations": "Community-derived boundary data; known shifts and geometry imperfections are documented by DataMeet.",
    },
    {
        "source_id": "SRC_DATAMEET_INDIA_BOUNDARY",
        "publisher": "DataMeet India community",
        "title": "India land boundary derived from Survey of India/Census district data",
        "release_or_reference_date": "repository accessed 2026-09-09",
        "url": "https://github.com/datameet/maps/tree/master/Country",
        "download_url": "https://raw.githubusercontent.com/datameet/maps/master/Country/india-soi.geojson",
        "license_or_access_note": "CC BY-SA 2.5 / ODbL as stated in the Country README.",
        "used_for": "Nationwide H3 grid generation.",
        "limitations": "Boundary representation follows the cited India-source convention; H3 center containment creates partial coastal cells.",
    },
    {
        "source_id": "SRC_NASA_POWER_ROLLING_12M",
        "publisher": "NASA Langley Research Center POWER Project",
        "title": "POWER Daily API, rolling 12-month MERRA-2/near-real-time meteorology",
        "release_or_reference_date": f"{WEATHER_START.isoformat()} through {WEATHER_END.isoformat()}",
        "url": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        "download_url": "https://power.larc.nasa.gov/api/temporal/daily/regional",
        "license_or_access_note": "NASA open data; cite the POWER project and its underlying MERRA-2 source.",
        "used_for": "Rolling 12-month temperature, precipitation, relative humidity, and wind-speed summaries.",
        "limitations": "Meteorological data at native source resolution. Recent near-real-time values may later be superseded by long-term MERRA-2 products; the exact daily source files and checksums are cached for reproducibility.",
    },
    {
        "source_id": "SRC_WORLDPOP_2020",
        "publisher": "WorldPop, University of Southampton",
        "title": "India unconstrained population count, 1 km, 2020, UN-adjusted",
        "release_or_reference_date": "2020",
        "url": "https://hub.worldpop.org/",
        "download_url": "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif",
        "license_or_access_note": "WorldPop open-data terms; commonly distributed under CC BY 4.0. Verify the release page for operational reuse.",
        "used_for": "Estimated population summed within each H3 cell.",
        "limitations": "Modelled 2020 population surface, not a census; unconstrained pixels and boundary differences can affect local sums.",
    },
    {
        "source_id": "SRC_WORLDCLIM_ELEV",
        "publisher": "WorldClim",
        "title": "WorldClim 2.1 elevation at 2.5 arc-minutes, derived from SRTM",
        "release_or_reference_date": "2020 distribution",
        "url": "https://www.worldclim.org/data/worldclim21.html",
        "download_url": "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_2.5m_elev.zip",
        "license_or_access_note": "WorldClim data terms require citation; review current terms before commercial redistribution.",
        "used_for": "Centroid elevation, approximate slope, relief, and terrain class.",
        "limitations": "Approximately 4.5 km cells; slope and relief are reconnaissance-scale approximations.",
    },
    {
        "source_id": "SRC_INDIA_CRITICAL_2023",
        "publisher": "Ministry of Mines, Government of India",
        "title": "Critical Minerals for India, Report of the Committee",
        "release_or_reference_date": "2023-06",
        "url": "https://www.mines.gov.in/admin/storage/app/uploads/649d4212cceb01688027666.pdf",
        "download_url": "same as URL",
        "license_or_access_note": "Government publication; retain attribution.",
        "used_for": "Official first 30 entries in the strategic-material priority list.",
        "limitations": "Criticality priorities can change; the report recommends periodic review.",
    },
    {
        "source_id": "SRC_PIB_CRITICAL_BLOCKS_T1",
        "publisher": "Press Information Bureau / Ministry of Mines, Government of India",
        "title": "First tranche: 20 critical and strategic mineral blocks notified for auction",
        "release_or_reference_date": "2023-12-13",
        "url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1985839&lang=2&reg=48",
        "download_url": "same as URL",
        "license_or_access_note": "Government publication; retain attribution.",
        "used_for": "Official block-name, state, mineral, and concession-type inventory.",
        "limitations": "Summary table provides no exact coordinates or polygons; records are inventory-only and excluded from spatial modelling.",
    },
    {
        "source_id": "SRC_PIB_CRITICAL_BLOCKS_T5",
        "publisher": "Press Information Bureau / Ministry of Mines, Government of India",
        "title": "Tranche V: 10 successfully auctioned critical and strategic mineral blocks",
        "release_or_reference_date": "2025-05-27",
        "url": "https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2131723&lang=2&reg=48",
        "download_url": "same as URL",
        "license_or_access_note": "Government publication; retain attribution.",
        "used_for": "Official block-name, state, mineral, concession, bidder, and final-offer inventory.",
        "limitations": "Summary table provides no exact coordinates or polygons; records are inventory-only and excluded from spatial modelling.",
    },
    {
        "source_id": "SRC_IBM_NMI_2025",
        "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
        "title": "National Mineral Inventory at a Glance 2025, Chapter 5: Mineral-wise reserves and resources",
        "release_or_reference_date": "resources as on 2025-04-01",
        "url": "https://ibm.gov.in/IBMPortal/pages/national-mineral-inventory-at-a-glance-2025",
        "download_url": "https://ibm.gov.in/writereaddata/files/17848872906a6337fae632bChapter__5_Mineral_wise.pdf",
        "license_or_access_note": "Government of India publication; retain attribution and verify current IBM website reuse terms.",
        "used_for": "Authoritative 2025 UNFC reserves/resources by mineral, grade or measure, and state/UT.",
        "limitations": "National/state aggregates are not deposit locations; the source chapter provides no coordinates or polygons and figures are rounded.",
    },
    {
        "source_id": "SRC_IBM_ABANDONED_MINE_SITES",
        "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
        "title": "List of 82 Abandoned Mine Sites Identified for Reclamation",
        "release_or_reference_date": "source page last-updated date and snapshot access date are recorded in the output; underlying site-identification period not stated",
        "url": "https://ibm.gov.in/IBMPortal/pages/Abandoned_Mine_Sites",
        "download_url": "same as URL; the builder establishes the IBM English-language session before caching the page",
        "license_or_access_note": "Government of India public webpage; retain attribution and verify current IBM website reuse terms.",
        "used_for": "Authoritative named inventory of 82 abandoned/orphaned mine sites identified for reclamation or rehabilitation, with state, source mineral wording, and earlier lessee.",
        "limitations": "No district, coordinate, mine code, lease geometry, closure date, or controlling current status is published. Rows are excluded from prospectivity scoring and are not a current all-mines or all-leases register.",
    },
    {
        "source_id": "SRC_IMA_CNMNC_MINERAL_LIST_2026_09",
        "publisher": "Commission on New Minerals, Nomenclature and Classification, International Mineralogical Association",
        "title": "The New IMA List of Minerals — A Work in Progress",
        "release_or_reference_date": "2026-09",
        "url": "https://cnmnc.units.it/",
        "download_url": "https://cnmnc.units.it/files/editor/IMA_Master_List_(2026-09).pdf",
        "license_or_access_note": "The document states Creative Commons Attribution-ShareAlike 3.0; retain attribution and share adaptations under compatible terms.",
        "used_for": "Canonical mineral-species names, approved formulae, IMA status, and authority verification in the v1 material ontology.",
        "limitations": "The IMA list defines mineral species; rocks, ores, mixtures, varieties, commodity groups, and industrial products require separate classification.",
    },
    {
        "source_id": "SRC_IUPAC_PERIODIC_TABLE_2022",
        "publisher": "International Union of Pure and Applied Chemistry",
        "title": "IUPAC Periodic Table of the Elements",
        "release_or_reference_date": "2022-05-04",
        "url": "https://iupac.org/what-we-do/periodic-table-of-elements/",
        "download_url": "https://iupac.org/what-we-do/periodic-table-of-elements/",
        "license_or_access_note": "Reference source; retain IUPAC attribution and review reuse terms before redistributing source artwork.",
        "used_for": "Element names, symbols, and atomic numbers for ontology entities that are independently evidenced or members of official critical-mineral groups.",
        "limitations": "Element membership does not imply a mineable occurrence, recoverable grade, or deposit in India.",
    },
    {
        "source_id": "SRC_USGS_MCS_2026",
        "publisher": "U.S. Geological Survey, National Minerals Information Center",
        "title": "Mineral Commodity Summaries 2026 data release",
        "release_or_reference_date": "2026-05-27 version 1.3",
        "url": "https://doi.org/10.5066/P1WKQ63T",
        "download_url": "https://www.sciencebase.gov/catalog/item/69837e43b66b01367d7ec7c7",
        "license_or_access_note": "U.S. Geological Survey data release; public domain, with citation requested.",
        "used_for": "Independent commodity vocabulary and India-reported commodity evidence in the v1 material ontology.",
        "limitations": "Commodity statistics are not deposit locations and U.S. commodity groupings are not an Indian statutory classification.",
    },
    {
        "source_id": "SRC_GSI_NGDR_GUEST_OGC_CATALOG",
        "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
        "title": "National Geoscience Data Repository guest OGC service catalog",
        "release_or_reference_date": "live service; audited 2026-09-10",
        "url": "https://geodataindia.gov.in/guestuser",
        "download_url": "https://geodataindia.gov.in/guestuser/wmsurl128/",
        "license_or_access_note": "Guest map and OGC service are publicly viewable. Raw feature redistribution is not authorized by KHANAN; consult the GSI Data Sharing and Accessibility Policy and obtain any required registration or permission.",
        "used_for": "Metadata-only audit of authoritative mineral, geochemistry, geophysics, soil, lithology, and geology layers. No raw feature values are published or used in scoring in this release.",
        "limitations": "Live service content can change. Analytical units, methods, detection limits, scale, and redistribution status are not sufficiently established for model integration from service schemas alone.",
    },
    {
        "source_id": "SRC_GSI_DATA_SHARING_POLICY_2019",
        "publisher": "Geological Survey of India, Ministry of Mines, Government of India",
        "title": "Data Sharing and Accessibility Policy of Geological Survey of India, 2019",
        "release_or_reference_date": "2019; audited 2026-09-10",
        "url": "https://geodataindia.gov.in/assets/Document_Pdf/4.%20Data%20Dissemination%20policy%202019.pdf",
        "download_url": "https://geodataindia.gov.in/assets/Document_Pdf/4.%20Data%20Dissemination%20policy%202019.pdf",
        "license_or_access_note": "Policy distinguishes open viewing from registered downloads and imposes GSI attribution and restrictions on transfer or redistribution of supplied thematic data. Obtain authoritative legal review or written permission before republishing raw NGDR features.",
        "used_for": "Controls KHANAN's access, attribution, caching, redistribution, and derivative-data decision for NGDR/GSI evidence.",
        "limitations": "KHANAN does not provide legal advice. Applicability can depend on access class, dataset, user category, agreement, and current portal terms.",
    },
]


MRDS_MATERIAL_PATTERNS = {
    "Antimony": [r"\bantimony\b"],
    "Beryllium": [r"\bberyllium\b"],
    "Bismuth": [r"\bbismuth\b"],
    "Cobalt": [r"\bcobalt\b"],
    "Copper": [r"\bcopper\b"],
    "Gallium": [r"\bgallium\b"],
    "Germanium": [r"\bgermanium\b"],
    "Graphite": [r"\bgraphite\b"],
    "Hafnium": [r"\bhafnium\b"],
    "Indium": [r"\bindium\b"],
    "Lithium": [r"\blithium\b"],
    "Molybdenum": [r"\bmolybdenum\b"],
    "Niobium": [r"\bniobium\b", r"\bcolumbium\b"],
    "Nickel": [r"\bnickel\b"],
    "Platinum-group elements": [r"\bplatinum\b", r"\bpalladium\b", r"\brhodium\b", r"\bruthenium\b", r"\biridium\b", r"\bosmium\b", r"\bpge\b"],
    "Phosphorus": [r"\bphosphorus\b", r"\bphosphate", r"\bphosphorite\b"],
    "Potash": [r"\bpotash\b", r"\bpotassium\b", r"\bglauconite\b"],
    "Rare-earth elements": [r"\bree\b", r"rare earth", r"\bmonazite\b"],
    "Rhenium": [r"\brhenium\b"],
    "Silicon": [r"\bsilicon\b", r"\bsilica\b", r"\bquartz\b"],
    "Strontium": [r"\bstrontium\b"],
    "Tantalum": [r"\btantalum\b"],
    "Tellurium": [r"\btellurium\b"],
    "Tin": [r"\btin\b"],
    "Titanium": [r"\btitanium\b", r"\bilmenite\b", r"\brutile\b"],
    "Tungsten": [r"\btungsten\b", r"\bwolfram"],
    "Vanadium": [r"\bvanadium\b"],
    "Zirconium": [r"\bzirconium\b", r"\bzircon\b"],
    "Selenium": [r"\bselenium\b"],
    "Cadmium": [r"\bcadmium\b"],
    "Aluminium": [r"\baluminum\b", r"\baluminium\b", r"\bbauxite\b"],
    "Iron": [r"\biron\b"],
    "Manganese": [r"\bmanganese\b"],
    "Chromium": [r"\bchromium\b", r"\bchrome\b", r"\bferrochrome\b", r"\bchromite\b"],
    "Lead": [r"\blead\b"],
    "Zinc": [r"\bzinc\b"],
    "Gold": [r"\bgold\b"],
    "Silver": [r"\bsilver\b"],
    "Uranium": [r"\buranium\b"],
    "Thorium": [r"\bthorium\b"],
    "Coal": [r"\bcoal\b"],
    "Lignite": [r"\blignite\b"],
    "Petroleum": [r"\bpetroleum\b", r"\bcrude oil\b", r"\bbitumen\b"],
    "Natural gas": [r"\bnatural gas\b", r"\bmethane\b"],
    "Boron": [r"\bboron\b", r"\bborate"],
    "Fluorine": [r"\bfluorine\b", r"\bfluorite\b"],
    "Magnesium": [r"\bmagnesium\b", r"\bmagnesite\b"],
    "Barium": [r"\bbarium\b", r"\bbarite\b", r"\bbaryte\b"],
    "Calcium and limestone": [r"\blimestone\b", r"\bcalcite\b", r"\bcalcium\b"],
    "Kaolin": [r"\bkaolin\b", r"\bkaolinite\b"],
}


ORE_FORMULAE = {
    "hematite": "Fe2O3",
    "magnetite": "Fe3O4",
    "goethite": "FeO(OH)",
    "gibbsite": "Al(OH)3",
    "boehmite": "AlO(OH)",
    "diaspore": "AlO(OH)",
    "pyrolusite": "MnO2",
    "braunite": "Mn2+Mn3+6SiO12",
    "hollandite": "Ba(Mn4+,Mn3+)8O16",
    "galena": "PbS",
    "sphalerite": "ZnS",
    "chalcopyrite": "CuFeS2",
    "bornite": "Cu5FeS4",
    "chalcocite": "Cu2S",
    "malachite": "Cu2CO3(OH)2",
    "azurite": "Cu3(CO3)2(OH)2",
    "cassiterite": "SnO2",
    "wolframite": "(Fe,Mn)WO4",
    "scheelite": "CaWO4",
    "chromite": "FeCr2O4",
    "ilmenite": "FeTiO3",
    "rutile": "TiO2",
    "monazite": "(Ce,La,Nd,Th)PO4",
    "bastnaesite": "(Ce,La)CO3F",
    "uraninite": "UO2",
    "zircon": "ZrSiO4",
    "barite": "BaSO4",
    "baryte": "BaSO4",
    "fluorite": "CaF2",
    "magnesite": "MgCO3",
    "apatite": "Ca5(PO4)3(F,Cl,OH)",
    "graphite": "C",
    "gold": "Au",
    "silver": "Ag",
    "platinum": "Pt",
    "pyrite": "FeS2",
    "molybdenite": "MoS2",
    "stibnite": "Sb2S3",
    "beryl": "Be3Al2Si6O18",
    "spodumene": "LiAlSi2O6",
    "petalite": "LiAlSi4O10",
}


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def clean_text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def unique_nonempty(values):
    seen = set()
    result = []
    for value in values:
        value = clean_text(value)
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result


def load_materials():
    items = json.loads((CONFIG / "materials.json").read_text(encoding="utf-8"))
    items.sort(key=lambda item: item["priority_rank"])
    by_name = {item["material_name"]: item for item in items}
    export = pd.DataFrame(items)
    for column in ["chemical_names", "symbols_or_formulae", "representative_ores_or_forms", "use_categories"]:
        export[column] = export[column].map(jdump)
    return items, by_name, export


def load_census_districts():
    wanted = [
        "State", "District", "Level", "Name", "TRU", "No_HH", "TOT_P", "TOT_M", "TOT_F",
        "P_06", "P_SC", "P_ST", "P_LIT", "TOT_WORK_P", "NON_WORK_P",
    ]
    pca = pd.read_excel(
        RAW / "census2011_pca_india.xlsx",
        sheet_name="Data",
        usecols=wanted,
        dtype={"State": str, "District": str, "Level": str, "Name": str, "TRU": str},
    )
    pca = pca[(pca["Level"] == "DISTRICT") & (pca["TRU"] == "Total")].copy()
    pca["census_state_code_2011"] = pca["State"].str.zfill(2)
    pca["census_district_code_2011"] = pca["District"].str.zfill(3)
    numeric = ["No_HH", "TOT_P", "TOT_M", "TOT_F", "P_06", "P_SC", "P_ST", "P_LIT", "TOT_WORK_P", "NON_WORK_P"]
    pca[numeric] = pca[numeric].apply(pd.to_numeric, errors="coerce")
    pca = pca.rename(
        columns={
            "Name": "census_district_name_source",
            "No_HH": "census_households_2011_district",
            "TOT_P": "census_population_2011_district",
            "TOT_M": "census_male_2011_district",
            "TOT_F": "census_female_2011_district",
            "P_06": "census_age_0_6_2011_district",
            "P_SC": "census_sc_2011_district",
            "P_ST": "census_st_2011_district",
            "P_LIT": "census_literate_2011_district",
            "TOT_WORK_P": "census_workers_2011_district",
            "NON_WORK_P": "census_nonworkers_2011_district",
        }
    )
    denom_lit = pca["census_population_2011_district"] - pca["census_age_0_6_2011_district"]
    pca["census_female_share_2011_district"] = pca["census_female_2011_district"] / pca["census_population_2011_district"]
    pca["census_age_0_6_share_2011_district"] = pca["census_age_0_6_2011_district"] / pca["census_population_2011_district"]
    pca["census_sc_share_2011_district"] = pca["census_sc_2011_district"] / pca["census_population_2011_district"]
    pca["census_st_share_2011_district"] = pca["census_st_2011_district"] / pca["census_population_2011_district"]
    pca["census_literacy_rate_2011_district_age7plus"] = pca["census_literate_2011_district"] / denom_lit.replace(0, np.nan)
    pca["census_worker_share_2011_district"] = pca["census_workers_2011_district"] / pca["census_population_2011_district"]

    area_names = [
        "state_code", "district_code", "subdistrict_code", "admin_level", "name", "sector",
        "villages_inhabited", "villages_uninhabited", "towns", "households", "population",
        "males", "females", "area_sq_km", "population_density",
    ]
    area = pd.read_excel(
        RAW / "census2011_area.xlsx", header=None, skiprows=4, names=area_names,
        dtype={"state_code": str, "district_code": str, "admin_level": str, "sector": str},
    )
    area = area[(area["admin_level"] == "DISTRICT") & (area["sector"] == "Total")].copy()
    area["census_state_code_2011"] = area["state_code"].str.zfill(2)
    area["census_district_code_2011"] = area["district_code"].str.zfill(3)
    area["census_area_km2_2011_district"] = pd.to_numeric(area["area_sq_km"], errors="coerce")
    area["census_population_density_2011_district"] = pd.to_numeric(area["population_density"], errors="coerce")
    pca = pca.merge(
        area[["census_state_code_2011", "census_district_code_2011", "census_area_km2_2011_district", "census_population_density_2011_district"]],
        on=["census_state_code_2011", "census_district_code_2011"], how="left", validate="one_to_one",
    )
    keep = [column for column in pca.columns if column.startswith("census_")]
    return pca[keep]


def make_h3_grid():
    india = gpd.read_file(RAW / "india-soi.geojson").to_crs(4326)
    geometry = india.geometry.union_all()
    cell_ids = set(h3.geo_to_cells(geometry.__geo_interface__, H3_RESOLUTION))
    # Center-containment omits a few coastal hexagons that still contain source
    # sites. Include those cells so every plausible India MRDS point can inherit
    # cell-level population, climate, and terrain attributes.
    for chunk in pd.read_csv(
        RAW / "mrds" / "mrds.csv",
        usecols=["country", "latitude", "longitude"],
        chunksize=50_000,
        low_memory=False,
    ):
        india_rows = chunk[chunk["country"].astype(str).str.casefold() == "india"].copy()
        india_rows["latitude"] = pd.to_numeric(india_rows["latitude"], errors="coerce")
        india_rows["longitude"] = pd.to_numeric(india_rows["longitude"], errors="coerce")
        india_rows = india_rows[
            india_rows["latitude"].between(5, 38.5)
            & india_rows["longitude"].between(67, 99)
        ]
        cell_ids.update(
            h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
            for lat, lon in zip(india_rows["latitude"], india_rows["longitude"])
        )
    cell_ids = sorted(cell_ids)
    rows = []
    polygons = []
    for cell_id in cell_ids:
        lat, lon = h3.cell_to_latlng(cell_id)
        boundary = h3.cell_to_boundary(cell_id)
        rows.append(
            {
                "h3_r6": cell_id,
                "latitude": lat,
                "longitude": lon,
                "grid_area_km2": h3.cell_area(cell_id, unit="km^2"),
            }
        )
        polygons.append(Polygon([(lng, lat_) for lat_, lng in boundary]))
    cells = gpd.GeoDataFrame(rows, geometry=polygons, crs=4326)
    centroids = gpd.GeoDataFrame(
        cells.drop(columns="geometry"),
        geometry=gpd.points_from_xy(cells["longitude"], cells["latitude"]), crs=4326,
    )
    return cells, centroids, geometry


def attach_districts(cells, centroids, census):
    districts = gpd.read_file(RAW / "2011_Dist.shp").to_crs(4326)
    districts["census_state_code_2011"] = districts["ST_CEN_CD"].astype(str).str.zfill(2)
    districts["census_district_code_2011"] = districts["censuscode"].astype(str).str.zfill(3)
    lookup = districts[["DISTRICT", "ST_NM", "census_state_code_2011", "census_district_code_2011", "geometry"]].rename(
        columns={"DISTRICT": "district_2011", "ST_NM": "state_or_ut_2011"}
    )
    lookup["state_or_ut_2011"] = lookup["state_or_ut_2011"].replace({
        "Arunanchal Pradesh": "Arunachal Pradesh",
        "Dadara & Nagar Havelli": "Dadra & Nagar Haveli",
        "Andaman & Nicobar Island": "Andaman and Nicobar Islands",
    })
    joined = gpd.sjoin(centroids, lookup, how="left", predicate="within")
    joined = joined.sort_values(["h3_r6", "index_right"], na_position="last").drop_duplicates("h3_r6")
    attrs = joined.drop(columns=["geometry", "index_right"])
    attrs = attrs.merge(census, on=["census_state_code_2011", "census_district_code_2011"], how="left", validate="many_to_one")
    result = cells.merge(attrs.drop(columns=["latitude", "longitude", "grid_area_km2"]), on="h3_r6", how="left", validate="one_to_one")
    return result, districts


def attach_geology(cells, centroids):
    geology = gpd.read_file(RAW / "india_geology_esri_living_atlas.geojson").to_crs(4326)
    geology = geology[~geology.geometry.is_empty].dropna(subset=["geometry"]).copy()
    geology["geometry"] = geology.geometry.make_valid()
    # Point-in-polygon against a few very complex units is slow because GEOS
    # repeatedly evaluates their rings. Rasterize the map-unit ID at 0.01
    # degrees and sample the cell centroids instead. This is appropriate for a
    # six-kilometre reconnaissance grid and makes the sampling deterministic.
    geology["_area_m2"] = geology.to_crs(6933).geometry.area.to_numpy()
    geology = geology.sort_values("_area_m2", ascending=False)
    min_lon, min_lat, max_lon, max_lat = centroids.total_bounds
    resolution = 0.01
    width = int(math.ceil((max_lon - min_lon) / resolution)) + 1
    height = int(math.ceil((max_lat - min_lat) / resolution)) + 1
    transform = from_origin(min_lon, max_lat, resolution, resolution)
    unit_raster = rasterize(
        ((geometry, int(objectid)) for geometry, objectid in zip(geology.geometry, geology["objectid"])),
        out_shape=(height, width), transform=transform, fill=0, all_touched=False, dtype="int32",
    )
    rr, cc = rowcol(transform, centroids["longitude"].to_numpy(), centroids["latitude"].to_numpy())
    rr = np.clip(np.asarray(rr), 0, height - 1)
    cc = np.clip(np.asarray(cc), 0, width - 1)
    sampled_ids = unit_raster[rr, cc]
    sampled = pd.DataFrame({"h3_r6": centroids["h3_r6"].to_numpy(), "objectid": sampled_ids})
    sampled.loc[sampled["objectid"] == 0, "objectid"] = np.nan
    lookup = geology[["objectid", "age_code", "age", "supergroup", "group_", "geom_id", "stratigraphy"]].drop_duplicates("objectid")
    joined = sampled.merge(lookup, on="objectid", how="left", validate="many_to_one")
    attrs = joined[["h3_r6", "objectid", "age_code", "age", "supergroup", "group_", "geom_id", "stratigraphy"]].rename(
        columns={
            "objectid": "geology_objectid",
            "age_code": "geology_age_code",
            "age": "geology_age",
            "supergroup": "geology_supergroup",
            "group_": "geology_group",
            "geom_id": "geology_geom_id",
            "stratigraphy": "geology_stratigraphy",
        }
    )
    result = cells.merge(attrs, on="h3_r6", how="left", validate="one_to_one")
    return result, geology


def read_power_csv(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    marker = "-END HEADER-"
    if marker not in text:
        raise ValueError(f"invalid POWER file: {path}")
    table_text = text.split(marker, 1)[1].lstrip("\r\n")
    return pd.read_csv(io.StringIO(table_text))


def load_power_grid():
    parameters = WEATHER_CONFIG["parameters"]
    parameter_frames = {}
    parameter_daily = {}
    for parameter in parameters:
        paths = sorted(POWER_DIR.glob(f"{parameter}_lat*.csv"))
        if len(paths) != 16:
            raise ValueError(f"expected 16 NASA POWER tiles for {parameter}, found {len(paths)} in {POWER_DIR}")
        frames = [read_power_csv(path) for path in paths]
        data = pd.concat(frames, ignore_index=True)
        required = {"LAT", "LON", "YEAR", "DOY", parameter}
        if not required.issubset(data.columns):
            raise ValueError(f"missing POWER columns for {parameter}: {sorted(required - set(data.columns))}")
        year = pd.to_numeric(data["YEAR"], errors="coerce").astype("Int64").astype(str)
        doy = pd.to_numeric(data["DOY"], errors="coerce").astype("Int64").astype(str).str.zfill(3)
        data["_date"] = pd.to_datetime(year + doy, format="%Y%j", errors="coerce")
        data["_value"] = pd.to_numeric(data[parameter], errors="coerce")
        data.loc[data["_value"] <= -900, "_value"] = np.nan
        data = data[
            data["_date"].between(pd.Timestamp(WEATHER_START), pd.Timestamp(WEATHER_END))
        ].drop_duplicates(["LAT", "LON", "_date"])
        data["_month"] = data["_date"].dt.strftime("%Y-%m")
        parameter_daily[parameter] = data[["LAT", "LON", "_date", "_month", "_value"]]
        grouped = data.groupby(["LAT", "LON"], sort=True)["_value"]
        parameter_frames[parameter] = pd.DataFrame({
            "mean": grouped.mean(),
            "sum": grouped.sum(min_count=1),
            "valid_days": grouped.count(),
        })

    base = parameter_frames["T2M"].reset_index()[["LAT", "LON"]]
    index = pd.MultiIndex.from_frame(base)
    result = base.copy()
    result["weather_reference_period_start"] = WEATHER_START.isoformat()
    result["weather_reference_period_end"] = WEATHER_END.isoformat()
    result["weather_reference_period_days"] = WEATHER_EXPECTED_DAYS
    result["weather_temporal_resolution"] = WEATHER_CONFIG["temporal_resolution"]
    result["weather_time_standard"] = WEATHER_CONFIG["time_standard"]
    output_fields = {
        "T2M": ("temperature_mean_c_rolling_12m", "mean"),
        "T2M_MIN": ("temperature_mean_daily_min_c_rolling_12m", "mean"),
        "T2M_MAX": ("temperature_mean_daily_max_c_rolling_12m", "mean"),
        "PRECTOTCORR": ("precipitation_total_mm_rolling_12m", "sum"),
        "RH2M": ("relative_humidity_mean_pct_rolling_12m", "mean"),
        "WS2M": ("wind_speed_2m_mean_m_s_rolling_12m", "mean"),
    }
    valid_day_arrays = []
    for parameter, (field, aggregation) in output_fields.items():
        aggregate = parameter_frames[parameter].reindex(index)
        result[field] = aggregate[aggregation].to_numpy()
        valid_day_arrays.append(aggregate["valid_days"].to_numpy())
    valid_days_min = np.min(np.vstack(valid_day_arrays), axis=0)
    result["weather_valid_days_min_rolling_12m"] = valid_days_min
    result["weather_data_completeness_pct_rolling_12m"] = 100 * valid_days_min / WEATHER_EXPECTED_DAYS

    def monthly_matrix(parameter, aggregation):
        data = parameter_daily[parameter]
        grouped = data.groupby(["LAT", "LON", "_month"])["_value"]
        monthly = grouped.mean() if aggregation == "mean" else grouped.sum(min_count=1)
        return monthly.unstack("_month").reindex(index=index, columns=WEATHER_MONTH_LABELS).to_numpy()

    temperature_monthly = monthly_matrix("T2M", "mean")
    precipitation_monthly = monthly_matrix("PRECTOTCORR", "sum")
    result["temperature_monthly_mean_c_json_rolling_12m"] = [
        jdump([
            {"month": month, "mean_c": None if np.isnan(value) else round(float(value), 2)}
            for month, value in zip(WEATHER_MONTH_LABELS, row)
        ])
        for row in temperature_monthly
    ]
    result["precipitation_monthly_total_mm_json_rolling_12m"] = [
        jdump([
            {"month": month, "total_mm": None if np.isnan(value) else round(float(value), 2)}
            for month, value in zip(WEATHER_MONTH_LABELS, row)
        ])
        for row in precipitation_monthly
    ]
    return result


def attach_climate(cells):
    climate = load_power_grid()
    tree = BallTree(np.radians(climate[["LAT", "LON"]].to_numpy()), metric="haversine")
    distance, index = tree.query(np.radians(cells[["latitude", "longitude"]].to_numpy()), k=1)
    matched = climate.iloc[index[:, 0]].reset_index(drop=True)
    for column in matched.columns:
        if column not in ["LAT", "LON"]:
            cells[column] = matched[column].to_numpy()
    cells["climate_grid_latitude"] = matched["LAT"].to_numpy()
    cells["climate_grid_longitude"] = matched["LON"].to_numpy()
    cells["climate_grid_distance_km"] = distance[:, 0] * EARTH_RADIUS_KM
    return cells, climate


def validate_weather_source(climate):
    files = sorted(POWER_DIR.glob("*.csv"))
    files_by_parameter = {
        parameter: sorted(POWER_DIR.glob(f"{parameter}_lat*.csv"))
        for parameter in WEATHER_CONFIG["parameters"]
    }
    source_files = [
        {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    checks = {
        "source_id": "SRC_NASA_POWER_ROLLING_12M",
        "source_api": "https://power.larc.nasa.gov/api/temporal/daily/regional",
        "source_documentation": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        "reference_period_start": WEATHER_START.isoformat(),
        "reference_period_end": WEATHER_END.isoformat(),
        "expected_days": WEATHER_EXPECTED_DAYS,
        "time_standard": WEATHER_CONFIG["time_standard"],
        "temporal_resolution": WEATHER_CONFIG["temporal_resolution"],
        "selection_basis": WEATHER_CONFIG["selection_basis"],
        "source_file_count": len(files),
        "source_files_by_parameter": {key: len(value) for key, value in files_by_parameter.items()},
        "climate_grid_points": int(len(climate)),
        "unique_climate_grid_points": int(climate[["LAT", "LON"]].drop_duplicates().shape[0]),
        "valid_days_min": int(climate["weather_valid_days_min_rolling_12m"].min()),
        "valid_days_max": int(climate["weather_valid_days_min_rolling_12m"].max()),
        "complete_grid_point_rate": float((climate["weather_valid_days_min_rolling_12m"] == WEATHER_EXPECTED_DAYS).mean()),
        "temperature_mean_c_range": [
            float(climate["temperature_mean_c_rolling_12m"].min()),
            float(climate["temperature_mean_c_rolling_12m"].max()),
        ],
        "precipitation_total_mm_range": [
            float(climate["precipitation_total_mm_rolling_12m"].min()),
            float(climate["precipitation_total_mm_rolling_12m"].max()),
        ],
        "source_files": source_files,
        "provisionality_note": "NASA notes that recent near-real-time meteorology may later be superseded by long-term MERRA-2 products. Cached files and SHA256 values freeze this release input.",
    }
    checks["checks_pass"] = bool(
        checks["source_file_count"] == 16 * len(WEATHER_CONFIG["parameters"])
        and all(value == 16 for value in checks["source_files_by_parameter"].values())
        and checks["climate_grid_points"] == checks["unique_climate_grid_points"] > 0
        and checks["valid_days_min"] == checks["valid_days_max"] == WEATHER_EXPECTED_DAYS
        and checks["complete_grid_point_rate"] == 1.0
        and climate["temperature_mean_c_rolling_12m"].between(-50, 60).all()
        and climate["precipitation_total_mm_rolling_12m"].between(0, 15_000).all()
        and climate["relative_humidity_mean_pct_rolling_12m"].between(0, 100).all()
        and climate["wind_speed_2m_mean_m_s_rolling_12m"].between(0, 100).all()
    )
    return checks


def attach_population(cells):
    with rasterio.open(RAW / "ind_ppp_2020_1km_UNadj.tif") as src:
        if src.crs is None:
            raise ValueError("WorldPop raster has no CRS")
        shapes = ((geometry, index + 1) for index, geometry in enumerate(cells.geometry))
        labels = rasterize(
            shapes, out_shape=(src.height, src.width), transform=src.transform,
            fill=0, all_touched=False, dtype="int32",
        )
        population = src.read(1, masked=True)
        valid = (~population.mask) & np.isfinite(population.data) & (population.data >= 0) & (labels > 0)
        sums = np.bincount(
            labels[valid], weights=population.data[valid].astype("float64"), minlength=len(cells) + 1,
        )
    cells["population_estimate_2020_grid"] = np.round(sums[1:], 1)
    cells["population_density_estimate_2020_per_km2"] = np.round(
        cells["population_estimate_2020_grid"] / cells["grid_area_km2"], 2
    )
    return cells


def _sample_raster(src, coordinates):
    values = np.fromiter(
        (float(sample[0]) if not np.ma.is_masked(sample[0]) else np.nan for sample in src.sample(coordinates, masked=True)),
        dtype=float, count=len(coordinates),
    )
    if src.nodata is not None:
        values[np.isclose(values, src.nodata)] = np.nan
    return values


def attach_terrain(cells):
    lon = cells["longitude"].to_numpy()
    lat = cells["latitude"].to_numpy()
    with rasterio.open(RAW / "wc2.1_2.5m_elev.tif") as src:
        xres = abs(src.transform.a)
        yres = abs(src.transform.e)
        coordinate_sets = {
            "c": list(zip(lon, lat)),
            "n": list(zip(lon, lat + yres)),
            "s": list(zip(lon, lat - yres)),
            "e": list(zip(lon + xres, lat)),
            "w": list(zip(lon - xres, lat)),
            "ne": list(zip(lon + xres, lat + yres)),
            "nw": list(zip(lon - xres, lat + yres)),
            "se": list(zip(lon + xres, lat - yres)),
            "sw": list(zip(lon - xres, lat - yres)),
        }
        samples = {key: _sample_raster(src, coords) for key, coords in coordinate_sets.items()}
    dx_m = 2 * xres * 111_320 * np.cos(np.radians(lat))
    dy_m = 2 * yres * 110_574
    dzdx = (samples["e"] - samples["w"]) / dx_m
    dzdy = (samples["n"] - samples["s"]) / dy_m
    slope = np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))
    stack = np.vstack(list(samples.values()))
    relief = np.full(stack.shape[1], np.nan)
    valid_relief = np.isfinite(stack).any(axis=0)
    relief[valid_relief] = np.nanmax(stack[:, valid_relief], axis=0) - np.nanmin(stack[:, valid_relief], axis=0)
    cells["elevation_m"] = np.round(samples["c"], 1)
    cells["slope_degrees_approx"] = np.round(slope, 2)
    cells["local_relief_m_approx"] = np.round(relief, 1)
    terrain = np.full(len(cells), "plateau_or_plain", dtype=object)
    terrain[cells["elevation_m"].to_numpy() < 50] = "coastal_or_lowland"
    terrain[cells["slope_degrees_approx"].to_numpy() >= 5] = "hilly"
    terrain[cells["slope_degrees_approx"].to_numpy() >= 15] = "steep_mountainous"
    terrain[cells["elevation_m"].to_numpy() >= 3000] = "high_mountain_or_alpine"
    terrain[np.isnan(cells["elevation_m"].to_numpy())] = "unavailable"
    cells["terrain_class"] = terrain
    return cells


def classify_weather(row):
    temp = row.get("temperature_mean_c_rolling_12m")
    precip = row.get("precipitation_total_mm_rolling_12m")
    if pd.isna(temp) or pd.isna(precip):
        return "unavailable"
    if temp < 10:
        return "cold_or_highland"
    if temp >= 24 and precip < 500:
        return "hot_arid_or_semiarid"
    if temp >= 24 and precip >= 1500:
        return "hot_humid"
    if temp >= 20 and precip >= 800:
        return "warm_monsoonal"
    if precip < 500:
        return "temperate_semiarid"
    return "temperate_monsoonal"


def priority_materials_from_text(text):
    text = (text or "").casefold()
    return [
        name for name, patterns in MRDS_MATERIAL_PATTERNS.items()
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
    ]


def formulae_from_ore(text):
    text = (clean_text(text) or "").casefold()
    return unique_nonempty([formula for mineral, formula in ORE_FORMULAE.items() if mineral in text])


def build_known_sites(cell_features, materials_by_name, census):
    chunks = []
    for chunk in pd.read_csv(RAW / "mrds" / "mrds.csv", chunksize=50_000, low_memory=False):
        chunks.append(chunk[chunk["country"].astype(str).str.casefold() == "india"])
    data = pd.concat(chunks, ignore_index=True)
    data = data[pd.to_numeric(data["latitude"], errors="coerce").notna() & pd.to_numeric(data["longitude"], errors="coerce").notna()].copy()
    data["latitude"] = pd.to_numeric(data["latitude"], errors="coerce")
    data["longitude"] = pd.to_numeric(data["longitude"], errors="coerce")
    data["_known_row"] = np.arange(len(data))
    data["h3_r6"] = [h3.latlng_to_cell(lat, lon, H3_RESOLUTION) for lat, lon in zip(data["latitude"], data["longitude"])]
    data["_source_materials"] = data[["commod1", "commod2", "commod3"]].apply(lambda row: unique_nonempty(row.tolist()), axis=1)
    combined = data[["commod1", "commod2", "commod3", "ore", "other_matl"]].fillna("").agg(" ".join, axis=1)
    data["_priority_materials"] = combined.map(priority_materials_from_text)
    data["source_materials_json"] = data["_source_materials"].map(jdump)
    data["priority_materials_json"] = data["_priority_materials"].map(jdump)
    data["chemical_names_json"] = data["_priority_materials"].map(
        lambda names: jdump(unique_nonempty(value for name in names for value in materials_by_name[name]["chemical_names"]))
    )
    data["symbols_or_formulae_json"] = data["_priority_materials"].map(
        lambda names: jdump(unique_nonempty(value for name in names for value in materials_by_name[name]["symbols_or_formulae"]))
    )
    data["ore_mineral_formulae_json"] = data["ore"].map(formulae_from_ore).map(jdump)
    data["record_class"] = np.select(
        [
            data["dev_stat"].isin(["Producer", "Past Producer"]),
            data["dev_stat"].eq("Plant"),
            data["dev_stat"].isin(["Prospect", "Occurrence"]),
        ],
        ["known_mine", "known_processing_plant", "known_prospect_or_occurrence"],
        default="known_site_status_unknown",
    )
    data["record_id"] = "MRDS-" + data["dep_id"].astype(str)
    data["coordinate_reference_system"] = "EPSG:4326"
    data["coordinate_precision_note"] = "MRDS point coordinate; apparent decimal precision is not a surveyed lease-boundary accuracy statement."
    data["source_dataset_id"] = "SRC_USGS_MRDS"
    data["source_record_id"] = data["dep_id"].astype(str)
    data["source_last_updated"] = "2022-08-23"
    data["record_observation_type"] = "source-reported factual occurrence/status; verify current status"
    data["source_state_name"] = data["state"].map(clean_text)
    data["source_district_name"] = data["county"].map(clean_text)

    districts = gpd.read_file(RAW / "2011_Dist.shp").to_crs(4326)
    districts["census_state_code_2011"] = districts["ST_CEN_CD"].astype(str).str.zfill(2)
    districts["census_district_code_2011"] = districts["censuscode"].astype(str).str.zfill(3)
    lookup = districts[["DISTRICT", "ST_NM", "census_state_code_2011", "census_district_code_2011", "geometry"]].rename(
        columns={"DISTRICT": "district_2011", "ST_NM": "state_or_ut_2011"}
    )
    points = gpd.GeoDataFrame(
        data[["_known_row"]].copy(),
        geometry=gpd.points_from_xy(data["longitude"], data["latitude"]), crs=4326,
    )
    direct_admin = gpd.sjoin(points, lookup, how="left", predicate="within")
    direct_admin = direct_admin.sort_values(["_known_row", "index_right"], na_position="last").drop_duplicates("_known_row")
    direct_admin = direct_admin.drop(columns=["geometry", "index_right"])
    direct_admin = direct_admin.merge(
        census, on=["census_state_code_2011", "census_district_code_2011"], how="left", validate="many_to_one"
    )
    data = data.merge(direct_admin, on="_known_row", how="left", validate="one_to_one")

    admin_columns = {
        "state_or_ut_2011", "district_2011", "census_state_code_2011", "census_district_code_2011",
        *[column for column in census.columns if column.startswith("census_")],
    }
    enrich_columns = [
        column for column in cell_features.columns
        if column != "geometry" and column not in ["latitude", "longitude"] and column not in admin_columns
    ]
    enriched = data.merge(cell_features[enrich_columns], on="h3_r6", how="left", validate="many_to_one")
    rename = {
        "site_name": "site_name",
        "dev_stat": "development_status",
        "oper_type": "operation_type",
        "dep_type": "deposit_type",
        "prod_size": "production_size",
        "ore": "ore_minerals_source",
        "gangue": "gangue_minerals_source",
        "other_matl": "other_materials_source",
        "hrock_unit": "host_rock_unit_source",
        "hrock_type": "host_rock_type_source",
        "arock_unit": "associated_rock_unit_source",
        "arock_type": "associated_rock_type_source",
        "orebody_fm": "orebody_form_source",
        "model": "deposit_model_source",
        "alteration": "alteration_source",
        "structure": "structure_source",
        "tectonic": "tectonic_setting_source",
        "ore_ctrl": "ore_controls_source",
        "score": "source_quality_code",
        "ref": "source_reference_text",
        "url": "source_url",
    }
    enriched = enriched.rename(columns=rename)
    enriched["geological_profile_json"] = enriched.apply(
        lambda row: jdump({
            "map_age": clean_text(row.get("geology_age")),
            "map_supergroup": clean_text(row.get("geology_supergroup")),
            "map_group": clean_text(row.get("geology_group")),
            "map_stratigraphy": clean_text(row.get("geology_stratigraphy")),
            "source_host_rock_unit": clean_text(row.get("host_rock_unit_source")),
            "source_host_rock_type": clean_text(row.get("host_rock_type_source")),
            "source_deposit_model": clean_text(row.get("deposit_model_source")),
        }), axis=1,
    )
    enriched["geographical_assessment_json"] = enriched.apply(
        lambda row: jdump({
            "elevation_m": None if pd.isna(row.get("elevation_m")) else round(float(row["elevation_m"]), 1),
            "slope_degrees_approx": None if pd.isna(row.get("slope_degrees_approx")) else round(float(row["slope_degrees_approx"]), 2),
            "local_relief_m_approx": None if pd.isna(row.get("local_relief_m_approx")) else round(float(row["local_relief_m_approx"]), 1),
            "terrain_class": clean_text(row.get("terrain_class")),
        }), axis=1,
    )
    enriched["weather_profile_json"] = enriched.apply(
        lambda row: jdump({
            "reference_period": f"{WEATHER_START.isoformat()}/{WEATHER_END.isoformat()}",
            "temporal_resolution": WEATHER_CONFIG["temporal_resolution"],
            "time_standard": WEATHER_CONFIG["time_standard"],
            "weather_class_derived": clean_text(row.get("weather_class_derived")),
            "temperature_mean_c": None if pd.isna(row.get("temperature_mean_c_rolling_12m")) else round(float(row["temperature_mean_c_rolling_12m"]), 2),
            "precipitation_total_mm": None if pd.isna(row.get("precipitation_total_mm_rolling_12m")) else round(float(row["precipitation_total_mm_rolling_12m"]), 1),
            "relative_humidity_mean_pct": None if pd.isna(row.get("relative_humidity_mean_pct_rolling_12m")) else round(float(row["relative_humidity_mean_pct_rolling_12m"]), 2),
            "wind_speed_2m_mean_m_s": None if pd.isna(row.get("wind_speed_2m_mean_m_s_rolling_12m")) else round(float(row["wind_speed_2m_mean_m_s_rolling_12m"]), 2),
            "valid_days_min": None if pd.isna(row.get("weather_valid_days_min_rolling_12m")) else int(row["weather_valid_days_min_rolling_12m"]),
            "data_completeness_pct": None if pd.isna(row.get("weather_data_completeness_pct_rolling_12m")) else round(float(row["weather_data_completeness_pct_rolling_12m"]), 2),
        }), axis=1,
    )
    def flags(row):
        result = ["point_not_lease_polygon", "current_operational_status_not_verified"]
        if not (5 <= row.get("latitude", -999) <= 38.5 and 67 <= row.get("longitude", -999) <= 99):
            result.append("coordinate_outside_expected_india_bounds_excluded_from_model")
        if pd.isna(row.get("district_2011")):
            result.append("district_spatial_join_missing")
        if pd.isna(row.get("geology_geom_id")):
            result.append("geology_map_unit_missing")
        if pd.isna(row.get("temperature_mean_c_rolling_12m")):
            result.append("climate_join_missing")
        elif row.get("weather_data_completeness_pct_rolling_12m", 0) < 100:
            result.append("rolling_weather_incomplete")
        if pd.isna(row.get("population_estimate_2020_grid")):
            result.append("population_estimate_missing")
        if not row.get("_priority_materials"):
            result.append("no_top50_material_mapping")
        if row.get("source_quality_code") in ["D", "E"]:
            result.append("lower_mrds_source_quality_code")
        return jdump(result)
    enriched["data_quality_flags_json"] = enriched.apply(flags, axis=1)

    preferred = [
        "record_id", "record_class", "site_name", "development_status", "operation_type", "deposit_type", "production_size",
        "latitude", "longitude", "coordinate_reference_system", "coordinate_precision_note", "h3_r6", "grid_area_km2",
        "state_or_ut_2011", "district_2011", "census_state_code_2011", "census_district_code_2011",
        "source_state_name", "source_district_name", "source_materials_json", "priority_materials_json", "chemical_names_json",
        "symbols_or_formulae_json", "ore_minerals_source", "ore_mineral_formulae_json", "gangue_minerals_source", "other_materials_source",
        "host_rock_unit_source", "host_rock_type_source", "associated_rock_unit_source", "associated_rock_type_source",
        "orebody_form_source", "deposit_model_source", "alteration_source", "structure_source", "tectonic_setting_source", "ore_controls_source",
        "geology_age", "geology_supergroup", "geology_group", "geology_stratigraphy", "geology_geom_id", "geological_profile_json",
        "elevation_m", "slope_degrees_approx", "local_relief_m_approx", "terrain_class", "geographical_assessment_json",
        "weather_class_derived", "weather_reference_period_start", "weather_reference_period_end", "weather_reference_period_days",
        "weather_temporal_resolution", "weather_time_standard", "temperature_mean_c_rolling_12m",
        "temperature_mean_daily_min_c_rolling_12m", "temperature_mean_daily_max_c_rolling_12m",
        "temperature_monthly_mean_c_json_rolling_12m", "precipitation_total_mm_rolling_12m",
        "precipitation_monthly_total_mm_json_rolling_12m", "relative_humidity_mean_pct_rolling_12m",
        "wind_speed_2m_mean_m_s_rolling_12m", "weather_valid_days_min_rolling_12m",
        "weather_data_completeness_pct_rolling_12m", "climate_grid_latitude", "climate_grid_longitude",
        "climate_grid_distance_km", "weather_profile_json", "population_estimate_2020_grid", "population_density_estimate_2020_per_km2",
        "census_households_2011_district", "census_population_2011_district", "census_male_2011_district", "census_female_2011_district",
        "census_age_0_6_2011_district", "census_sc_2011_district", "census_st_2011_district", "census_literate_2011_district",
        "census_workers_2011_district", "census_nonworkers_2011_district", "census_female_share_2011_district",
        "census_age_0_6_share_2011_district", "census_sc_share_2011_district", "census_st_share_2011_district",
        "census_literacy_rate_2011_district_age7plus", "census_worker_share_2011_district", "census_area_km2_2011_district",
        "census_population_density_2011_district", "source_dataset_id", "source_record_id", "source_url", "source_quality_code",
        "source_reference_text", "source_last_updated", "record_observation_type", "data_quality_flags_json",
    ]
    preferred = [column for column in preferred if column in enriched.columns]
    return enriched[preferred + ["_priority_materials"]]


def score_prospectivity(cells, known, materials, materials_by_name):
    coords = np.radians(cells[["latitude", "longitude"]].to_numpy())
    all_known_coords = np.radians(known[["latitude", "longitude"]].to_numpy())
    all_tree = BallTree(all_known_coords, metric="haversine")
    any_distance, _ = all_tree.query(coords, k=1)
    cells["nearest_known_site_km"] = np.round(any_distance[:, 0] * EARTH_RADIUS_KM, 2)
    cells["known_site_count_within_100km"] = all_tree.query_radius(coords, r=100 / EARTH_RADIUS_KM, count_only=True)

    n_cells = len(cells)
    n_materials = len(materials)
    scores = np.full((n_cells, n_materials), np.nan, dtype="float32")
    percentiles = np.full((n_cells, n_materials), np.nan, dtype="float32")
    nearest = np.full((n_cells, n_materials), np.nan, dtype="float32")
    support_counts = np.zeros(n_materials, dtype=int)
    stats = []
    all_unit_counts = known["geology_geom_id"].value_counts(dropna=True)

    for material_index, item in enumerate(materials):
        name = item["material_name"]
        mask = known["_priority_materials"].map(lambda values: name in values)
        evidence = known[mask].copy()
        n = len(evidence)
        support_counts[material_index] = n
        if n == 0:
            stats.append({
                "material_name": name, "known_evidence_records": 0, "modelled": False,
                "model_support_level": "none", "score_note": "No mapped MRDS evidence in India; no grid score produced.",
            })
            continue
        tree = BallTree(np.radians(evidence[["latitude", "longitude"]].to_numpy()), metric="haversine")
        dist, _ = tree.query(coords, k=1)
        dist_km = dist[:, 0] * EARTH_RADIUS_KM
        density = tree.query_radius(coords, r=100 / EARTH_RADIUS_KM, count_only=True).astype(float)
        distance_score = np.exp(-dist_km / 100.0)
        density_scale = max(float(np.percentile(density, 95)), 1.0)
        density_score = np.clip(density / density_scale, 0, 1)

        pos_counts = evidence["geology_geom_id"].value_counts(dropna=True)
        raw_geo = {}
        for unit, pos_count in pos_counts.items():
            total = float(all_unit_counts.get(unit, 0))
            raw_geo[unit] = (float(pos_count) + 0.5) / (total + 5.0)
        geo_values = cells["geology_geom_id"].map(raw_geo).fillna(0).to_numpy(dtype=float)
        if raw_geo:
            scale = max(float(np.percentile(list(raw_geo.values()), 95)), 1e-9)
            geo_score = np.clip(geo_values / scale, 0, 1)
        else:
            geo_score = np.zeros(n_cells)

        if n >= 5:
            combined = 0.50 * geo_score + 0.35 * distance_score + 0.15 * density_score
            support_level = "high" if n >= 20 else "medium"
        else:
            combined = 0.80 * distance_score + 0.20 * density_score
            support_level = "low"
        support_weight = 0.4 + 0.6 * min(1.0, math.log1p(n) / math.log1p(20))
        combined = np.clip(combined * support_weight, 0, 1)
        scores[:, material_index] = combined.astype("float32")
        nearest[:, material_index] = dist_km.astype("float32")
        if n >= 5:
            eligible = dist_km > 10
            ranks = np.full(n_cells, np.nan, dtype=float)
            ranks[eligible] = rankdata(combined[eligible], method="average") / eligible.sum()
            percentiles[:, material_index] = ranks.astype("float32")
        stats.append({
            "material_name": name,
            "known_evidence_records": n,
            "modelled": True,
            "model_support_level": support_level,
            "score_note": "0.50 geology + 0.35 distance + 0.15 density" if n >= 5 else "0.80 distance + 0.20 density; insufficient evidence for candidate percentiles",
        })

    safe = np.where(np.isnan(scores), -np.inf, scores)
    top_idx = np.argpartition(safe, -5, axis=1)[:, -5:]
    top_vals = np.take_along_axis(safe, top_idx, axis=1)
    order = np.argsort(top_vals, axis=1)[:, ::-1]
    top_idx = np.take_along_axis(top_idx, order, axis=1)
    material_names = np.array([item["material_name"] for item in materials], dtype=object)

    top_materials_json = []
    top_scores_json = []
    top_percentiles_json = []
    top_nearest_json = []
    top_chemicals_json = []
    top_symbols_json = []
    top_material = []
    top_score = []
    top_percentile = []
    top_distance = []
    top_support = []
    top_support_level = []
    stat_by_name = {row["material_name"]: row for row in stats}
    for row_number, indexes in enumerate(top_idx):
        valid_indexes = [int(index) for index in indexes if np.isfinite(scores[row_number, index])]
        names = [str(material_names[index]) for index in valid_indexes]
        values = [round(float(scores[row_number, index]), 4) for index in valid_indexes]
        pct = [None if np.isnan(percentiles[row_number, index]) else round(float(percentiles[row_number, index]), 5) for index in valid_indexes]
        distances = [round(float(nearest[row_number, index]), 2) for index in valid_indexes]
        top_materials_json.append(jdump(names))
        top_scores_json.append(jdump(values))
        top_percentiles_json.append(jdump(pct))
        top_nearest_json.append(jdump(distances))
        top_chemicals_json.append(jdump(unique_nonempty(value for name in names for value in materials_by_name[name]["chemical_names"])))
        top_symbols_json.append(jdump(unique_nonempty(value for name in names for value in materials_by_name[name]["symbols_or_formulae"])))
        if names:
            top_material.append(names[0])
            top_score.append(values[0])
            top_percentile.append(pct[0])
            top_distance.append(distances[0])
            top_support.append(int(stat_by_name[names[0]]["known_evidence_records"]))
            top_support_level.append(stat_by_name[names[0]]["model_support_level"])
        else:
            top_material.append(None); top_score.append(np.nan); top_percentile.append(np.nan); top_distance.append(np.nan); top_support.append(0); top_support_level.append("none")

    cells["top_material"] = top_material
    cells["top_materials_json"] = top_materials_json
    cells["top_material_scores_json"] = top_scores_json
    cells["top_material_percentiles_json"] = top_percentiles_json
    cells["top_material_nearest_known_km_json"] = top_nearest_json
    cells["top_material_chemical_names_json"] = top_chemicals_json
    cells["top_material_symbols_or_formulae_json"] = top_symbols_json
    cells["prospectivity_score_max"] = top_score
    cells["top_material_percentile"] = top_percentile
    cells["top_material_nearest_known_km"] = top_distance
    cells["top_material_known_evidence_records"] = top_support
    cells["model_support_level"] = top_support_level
    known_nearby = cells["nearest_known_site_km"] <= 5
    support_ok = cells["top_material_known_evidence_records"] >= 10
    distance_ok = (cells["top_material_nearest_known_km"] > 25) & (cells["top_material_nearest_known_km"] <= 250)
    high = (~known_nearby) & distance_ok & support_ok & (cells["top_material_percentile"] >= 0.999) & (cells["prospectivity_score_max"] >= 0.55)
    medium = (~known_nearby) & distance_ok & support_ok & (cells["top_material_percentile"] >= 0.995) & (cells["prospectivity_score_max"] >= 0.50)
    cells["record_class"] = np.select(
        [known_nearby, high, medium],
        ["known_evidence_area", "high_priority_candidate", "priority_candidate"],
        default="regional_background",
    )
    candidate_order = cells.loc[high | medium, ["top_material_percentile", "prospectivity_score_max"]].sort_values(
        ["top_material_percentile", "prospectivity_score_max"], ascending=False
    )
    rank_map = pd.Series(np.arange(1, len(candidate_order) + 1), index=candidate_order.index)
    cells["candidate_rank_national"] = rank_map.reindex(cells.index).astype("Int64")
    cells["model_version"] = MODEL_VERSION
    cells["prospectivity_index_definition"] = "Reconnaissance index (0-1), not discovery probability: host-unit enrichment, distance to known material evidence, and 100 km evidence density."
    cells["model_limitations"] = "No national geochemistry, airborne/ground geophysics, alteration mineral mapping, deposit-grade/tonnage, depth, drilling, lease, protected-area, land-tenure, water-stress, or infrastructure features in v0.1. Spatial autocorrelation can inflate apparent support."
    cells["record_observation_type"] = "modelled reconnaissance screening cell"
    cells["source_dataset_ids_json"] = jdump(["SRC_USGS_MRDS", "SRC_ESRI_INDIA_GEOLOGY", "SRC_CENSUS_PCA_2011", "SRC_CENSUS_A01_2011", "SRC_DATAMEET_DISTRICTS_2011", "SRC_DATAMEET_INDIA_BOUNDARY", "SRC_NASA_POWER_ROLLING_12M", "SRC_WORLDPOP_2020", "SRC_WORLDCLIM_ELEV"])
    return cells, pd.DataFrame(stats)


def validate_material_models(cells, known, materials):
    """Spatial group holdout against pseudo-absence/background grid cells.

    These metrics measure whether the same screening recipe ranks held-out
    catalog occurrences above sampled background cells. They are not estimates
    of discovery probability, because the background is not confirmed barren.
    """
    grid_coords = np.radians(cells[["latitude", "longitude"]].to_numpy())
    grid_units = cells["geology_geom_id"].to_numpy()
    all_unit_counts = known["geology_geom_id"].value_counts(dropna=True)
    results = []
    for material_index, item in enumerate(materials):
        name = item["material_name"]
        evidence = known[known["_priority_materials"].map(lambda values: name in values)].copy()
        n = len(evidence)
        base = {
            "material_name": name,
            "spatial_cv_positive_records": n,
            "spatial_cv_folds": 0,
            "spatial_cv_background_cells": 0,
            "spatial_holdout_pseudoabsence_roc_auc": np.nan,
            "spatial_holdout_recall_at_background_top5pct": np.nan,
            "validation_note": "Not validated: fewer than 10 mapped India evidence records.",
        }
        if n < 10:
            results.append(base)
            continue
        evidence_coords = np.radians(evidence[["latitude", "longitude"]].to_numpy())
        full_tree = BallTree(evidence_coords, metric="haversine")
        distance_all, _ = full_tree.query(grid_coords, k=1)
        background_pool = np.flatnonzero(distance_all[:, 0] * EARTH_RADIUS_KM > 25)
        if len(background_pool) < 100:
            base["validation_note"] = "Not validated: insufficient background cells beyond 25 km from evidence."
            results.append(base)
            continue
        rng = np.random.default_rng(20260909 + material_index)
        background_count = min(len(background_pool), max(500, n * 20))
        background_index = rng.choice(background_pool, size=background_count, replace=False)
        background_coords = grid_coords[background_index]
        background_units = grid_units[background_index]
        groups = np.array([
            h3.latlng_to_cell(lat, lon, 3)
            for lat, lon in zip(evidence["latitude"], evidence["longitude"])
        ])
        unique_groups = np.unique(groups)
        if len(unique_groups) < 3:
            base["validation_note"] = "Not validated: evidence occupies fewer than three H3 resolution-3 spatial groups."
            results.append(base)
            continue
        n_splits = min(5, len(unique_groups))
        splitter = GroupKFold(n_splits=n_splits)
        aucs = []
        recalls = []
        weights = []
        for train_index, test_index in splitter.split(evidence, groups=groups):
            train = evidence.iloc[train_index]
            test = evidence.iloc[test_index]
            train_coords = np.radians(train[["latitude", "longitude"]].to_numpy())
            train_tree = BallTree(train_coords, metric="haversine")
            evaluation_coords = np.vstack([
                np.radians(test[["latitude", "longitude"]].to_numpy()),
                background_coords,
            ])
            evaluation_units = np.concatenate([test["geology_geom_id"].to_numpy(), background_units])
            distance_eval, _ = train_tree.query(evaluation_coords, k=1)
            density_eval = train_tree.query_radius(
                evaluation_coords, r=100 / EARTH_RADIUS_KM, count_only=True
            ).astype(float)
            density_grid = train_tree.query_radius(
                grid_coords, r=100 / EARTH_RADIUS_KM, count_only=True
            ).astype(float)
            density_scale = max(float(np.percentile(density_grid, 95)), 1.0)
            distance_score = np.exp(-(distance_eval[:, 0] * EARTH_RADIUS_KM) / 100.0)
            density_score = np.clip(density_eval / density_scale, 0, 1)
            pos_counts = train["geology_geom_id"].value_counts(dropna=True)
            raw_geo = {
                unit: (float(pos_count) + 0.5) / (float(all_unit_counts.get(unit, 0)) + 5.0)
                for unit, pos_count in pos_counts.items()
            }
            if raw_geo:
                geo_scale = max(float(np.percentile(list(raw_geo.values()), 95)), 1e-9)
                geo_score = np.array([
                    min(1.0, raw_geo.get(unit, 0.0) / geo_scale) if not pd.isna(unit) else 0.0
                    for unit in evaluation_units
                ])
            else:
                geo_score = np.zeros(len(evaluation_units))
            fold_score = 0.50 * geo_score + 0.35 * distance_score + 0.15 * density_score
            support_weight = 0.4 + 0.6 * min(1.0, math.log1p(len(train)) / math.log1p(20))
            fold_score = np.clip(fold_score * support_weight, 0, 1)
            labels = np.concatenate([np.ones(len(test)), np.zeros(background_count)])
            aucs.append(roc_auc_score(labels, fold_score))
            background_scores = fold_score[len(test):]
            threshold = np.percentile(background_scores, 95)
            recalls.append(float(np.mean(fold_score[:len(test)] >= threshold)))
            weights.append(len(test))
        base.update({
            "spatial_cv_folds": n_splits,
            "spatial_cv_background_cells": background_count,
            "spatial_holdout_pseudoabsence_roc_auc": float(np.average(aucs, weights=weights)),
            "spatial_holdout_recall_at_background_top5pct": float(np.average(recalls, weights=weights)),
            "validation_note": "Spatial GroupKFold by H3 resolution-3; held-out evidence compared with sampled cells more than 25 km from catalog evidence. Background is not confirmed barren.",
        })
        results.append(base)
    return pd.DataFrame(results)


def apply_validation_gated_candidate_classes(cells, model_validation):
    """Publish candidate labels only when the top-material model passes spatial holdout gates."""
    validation = model_validation.set_index("material_name")
    cells["top_material_spatial_cv_auc"] = cells["top_material"].map(
        validation["spatial_holdout_pseudoabsence_roc_auc"]
    )
    cells["top_material_spatial_cv_recall_at_background_top5pct"] = cells["top_material"].map(
        validation["spatial_holdout_recall_at_background_top5pct"]
    )
    auc = cells["top_material_spatial_cv_auc"]
    recall = cells["top_material_spatial_cv_recall_at_background_top5pct"]
    known_nearby = cells["nearest_known_site_km"] <= 5
    support_ok = cells["top_material_known_evidence_records"] >= 10
    distance_ok = (cells["top_material_nearest_known_km"] > 25) & (cells["top_material_nearest_known_km"] <= 250)
    validation_ok = auc >= 0.60
    high_validation = (auc >= 0.75) & (recall >= 0.20)
    high = (
        (~known_nearby) & distance_ok & support_ok & high_validation
        & (cells["top_material_percentile"] >= 0.999)
        & (cells["prospectivity_score_max"] >= 0.55)
    )
    medium = (
        (~known_nearby) & distance_ok & support_ok & validation_ok
        & (cells["top_material_percentile"] >= 0.995)
        & (cells["prospectivity_score_max"] >= 0.50)
    )
    cells["record_class"] = np.select(
        [known_nearby, high, medium],
        ["known_evidence_area", "high_priority_candidate", "priority_candidate"],
        default="regional_background",
    )
    cells["model_validation_tier"] = np.select(
        [high_validation, validation_ok, auc.notna()],
        ["strong_holdout", "passes_minimum_holdout", "fails_minimum_holdout"],
        default="not_spatially_validated",
    )
    candidate_order = cells.loc[high | medium, [
        "top_material_spatial_cv_auc", "top_material_percentile", "prospectivity_score_max"
    ]].sort_values(
        ["top_material_spatial_cv_auc", "top_material_percentile", "prospectivity_score_max"], ascending=False
    )
    rank_map = pd.Series(np.arange(1, len(candidate_order) + 1), index=candidate_order.index)
    cells["candidate_rank_national"] = rank_map.reindex(cells.index).astype("Int64")
    cells["candidate_promotion_rule"] = (
        "Known-evidence exclusion <=5 km; evidence distance >25 and <=250 km; >=10 source records; "
        "priority requires spatial holdout AUC >=0.60, percentile >=0.995, score >=0.50; high priority "
        "also requires AUC >=0.75, recall at background top 5% >=0.20, percentile >=0.999, score >=0.55."
    )
    return cells


def add_profiles_and_flags(cells):
    cells["weather_class_derived"] = cells.apply(classify_weather, axis=1)
    cells["geological_profile_json"] = cells.apply(
        lambda row: jdump({
            "age": clean_text(row.get("geology_age")),
            "supergroup": clean_text(row.get("geology_supergroup")),
            "group": clean_text(row.get("geology_group")),
            "stratigraphy": clean_text(row.get("geology_stratigraphy")),
            "geom_id": None if pd.isna(row.get("geology_geom_id")) else int(row["geology_geom_id"]),
        }), axis=1,
    )
    cells["geographical_assessment_json"] = cells.apply(
        lambda row: jdump({
            "elevation_m": None if pd.isna(row.get("elevation_m")) else round(float(row["elevation_m"]), 1),
            "slope_degrees_approx": None if pd.isna(row.get("slope_degrees_approx")) else round(float(row["slope_degrees_approx"]), 2),
            "local_relief_m_approx": None if pd.isna(row.get("local_relief_m_approx")) else round(float(row["local_relief_m_approx"]), 1),
            "terrain_class": clean_text(row.get("terrain_class")),
        }), axis=1,
    )
    cells["weather_profile_json"] = cells.apply(
        lambda row: jdump({
            "reference_period": f"{WEATHER_START.isoformat()}/{WEATHER_END.isoformat()}",
            "temporal_resolution": WEATHER_CONFIG["temporal_resolution"],
            "time_standard": WEATHER_CONFIG["time_standard"],
            "weather_class_derived": clean_text(row.get("weather_class_derived")),
            "temperature_mean_c": None if pd.isna(row.get("temperature_mean_c_rolling_12m")) else round(float(row["temperature_mean_c_rolling_12m"]), 2),
            "temperature_mean_daily_min_c": None if pd.isna(row.get("temperature_mean_daily_min_c_rolling_12m")) else round(float(row["temperature_mean_daily_min_c_rolling_12m"]), 2),
            "temperature_mean_daily_max_c": None if pd.isna(row.get("temperature_mean_daily_max_c_rolling_12m")) else round(float(row["temperature_mean_daily_max_c_rolling_12m"]), 2),
            "precipitation_total_mm": None if pd.isna(row.get("precipitation_total_mm_rolling_12m")) else round(float(row["precipitation_total_mm_rolling_12m"]), 1),
            "relative_humidity_mean_pct": None if pd.isna(row.get("relative_humidity_mean_pct_rolling_12m")) else round(float(row["relative_humidity_mean_pct_rolling_12m"]), 2),
            "wind_speed_2m_mean_m_s": None if pd.isna(row.get("wind_speed_2m_mean_m_s_rolling_12m")) else round(float(row["wind_speed_2m_mean_m_s_rolling_12m"]), 2),
            "valid_days_min": None if pd.isna(row.get("weather_valid_days_min_rolling_12m")) else int(row["weather_valid_days_min_rolling_12m"]),
            "data_completeness_pct": None if pd.isna(row.get("weather_data_completeness_pct_rolling_12m")) else round(float(row["weather_data_completeness_pct_rolling_12m"]), 2),
        }), axis=1,
    )
    cells["record_id"] = "GRID-" + cells["h3_r6"]
    cells["coordinate_reference_system"] = "EPSG:4326"
    cells["coordinate_precision_note"] = "Latitude/longitude are H3 cell centroids; use cell_boundary_wkt and grid_area_km2 for the represented area."
    cells["cell_boundary_wkt"] = cells.geometry.to_wkt(rounding_precision=5)
    def flags(row):
        result = []
        if pd.isna(row.get("district_2011")):
            result.append("district_spatial_join_missing")
        if pd.isna(row.get("geology_geom_id")):
            result.append("geology_map_unit_missing")
        if pd.isna(row.get("temperature_mean_c_rolling_12m")):
            result.append("climate_join_missing")
        elif row.get("weather_data_completeness_pct_rolling_12m", 0) < 100:
            result.append("rolling_weather_incomplete")
        if pd.isna(row.get("population_estimate_2020_grid")):
            result.append("population_estimate_missing")
        if row.get("model_support_level") in ["low", "none"]:
            result.append("low_or_no_material_evidence_support")
        if row.get("model_validation_tier") in ["fails_minimum_holdout", "not_spatially_validated"]:
            result.append("top_material_model_not_promoted_by_spatial_validation")
        if row.get("record_class") == "known_evidence_area":
            result.append("near_known_source_record_not_undiscovered_candidate")
        result.append("candidate_requires_field_validation")
        return jdump(result)
    cells["data_quality_flags_json"] = cells.apply(flags, axis=1)
    return cells


def make_data_dictionary(known, grid, materials):
    definitions = {
        "record_id": ("Stable record identifier within this release.", "text", None),
        "record_class": ("Factual site type or grid screening class.", "category", None),
        "latitude": ("WGS84 latitude of site point or H3 cell centroid.", "number", "decimal degrees"),
        "longitude": ("WGS84 longitude of site point or H3 cell centroid.", "number", "decimal degrees"),
        "h3_r6": ("H3 resolution-6 cell identifier.", "text", None),
        "grid_area_km2": ("Full H3 cell area; coastal land coverage may be smaller.", "number", "km2"),
        "cell_boundary_wkt": ("H3 cell boundary encoded as WKT polygon.", "text", None),
        "population_estimate_2020_grid": ("WorldPop 2020 population pixels summed within the H3 cell.", "number", "people"),
        "weather_reference_period_start": ("First UTC day included in the rolling weather summary.", "ISO date", None),
        "weather_reference_period_end": ("Last UTC day included in the rolling weather summary.", "ISO date", None),
        "weather_reference_period_days": ("Inclusive number of days in the configured weather window.", "integer", "days"),
        "weather_temporal_resolution": ("Temporal resolution of the source observations used for aggregation.", "category", None),
        "weather_time_standard": ("Time standard requested from the NASA POWER daily API.", "category", None),
        "temperature_mean_c_rolling_12m": ("Mean of daily NASA POWER T2M values across the configured rolling 12-month window.", "number", "degrees C"),
        "temperature_mean_daily_min_c_rolling_12m": ("Mean of daily NASA POWER T2M_MIN values across the configured rolling 12-month window.", "number", "degrees C"),
        "temperature_mean_daily_max_c_rolling_12m": ("Mean of daily NASA POWER T2M_MAX values across the configured rolling 12-month window.", "number", "degrees C"),
        "temperature_monthly_mean_c_json_rolling_12m": ("JSON array of month labels and mean daily T2M values for each month in the rolling window.", "JSON array", "degrees C"),
        "precipitation_total_mm_rolling_12m": ("Sum of daily NASA POWER PRECTOTCORR values across the configured rolling 12-month window.", "number", "mm"),
        "precipitation_monthly_total_mm_json_rolling_12m": ("JSON array of month labels and summed daily PRECTOTCORR values for each month in the rolling window.", "JSON array", "mm"),
        "relative_humidity_mean_pct_rolling_12m": ("Mean of daily NASA POWER RH2M values across the configured rolling 12-month window.", "number", "%"),
        "wind_speed_2m_mean_m_s_rolling_12m": ("Mean of daily NASA POWER WS2M values across the configured rolling 12-month window.", "number", "m/s"),
        "weather_valid_days_min_rolling_12m": ("Minimum valid daily observation count across the six weather parameters at the matched source-grid point.", "integer", "days"),
        "weather_data_completeness_pct_rolling_12m": ("Minimum valid-day count divided by the configured weather-window day count.", "number", "%"),
        "climate_grid_latitude": ("Latitude of the nearest native NASA POWER meteorological grid point.", "number", "decimal degrees"),
        "climate_grid_longitude": ("Longitude of the nearest native NASA POWER meteorological grid point.", "number", "decimal degrees"),
        "climate_grid_distance_km": ("Great-circle distance from the site/cell coordinate to the matched NASA POWER grid point.", "number", "km"),
        "prospectivity_score_max": ("Highest material reconnaissance score for the cell; not a probability.", "number", "0-1 index"),
        "top_material_percentile": ("Within-material percentile for cells more than 10 km from mapped evidence; unavailable for fewer than five evidence records.", "number", "0-1 percentile"),
        "candidate_rank_national": ("Rank among high-priority and priority candidate cells in this release.", "integer", "rank"),
        "top_material_spatial_cv_auc": ("Spatial group holdout pseudo-absence ROC AUC for the top-material model; background cells are not confirmed barren.", "number", "0-1"),
        "top_material_spatial_cv_recall_at_background_top5pct": ("Share of held-out evidence records above the 95th percentile of sampled background scores.", "number", "0-1"),
        "data_quality_flags_json": ("Machine-readable JSON array of record-level caveats.", "JSON array", None),
    }
    rows = []
    for table_name, frame in [("india_known_mining_sites.csv", known), ("india_mining_prospectivity_grid_h3_r6.csv", grid), ("india_strategic_materials_top50.csv", materials)]:
        for column in frame.columns:
            definition, dtype, unit = definitions.get(column, (None, None, None))
            if definition is None:
                if column.endswith("_json") or "_json_" in column:
                    definition, dtype = "JSON-encoded structured value; see column name and methodology for meaning.", "JSON"
                elif column.startswith("census_"):
                    definition, dtype = "Census 2011 district attribute or derived share; district-level context, not a cell-level count.", "number or text"
                elif column.startswith("geology_"):
                    definition, dtype = "Geological map-unit attribute sampled at the point or cell centroid.", "text or number"
                elif column.startswith("temperature_"):
                    definition, dtype, unit = f"NASA POWER daily temperature summary for {WEATHER_START.isoformat()} through {WEATHER_END.isoformat()}.", "number or JSON", "degrees C"
                elif column.startswith("precipitation_"):
                    definition, dtype, unit = f"NASA POWER daily precipitation summary for {WEATHER_START.isoformat()} through {WEATHER_END.isoformat()}.", "number or JSON", "mm"
                elif column.startswith("source_"):
                    definition, dtype = "Source provenance field retained from the contributing dataset or registry.", "text"
                elif column in ["elevation_m", "local_relief_m_approx"]:
                    definition, dtype, unit = "WorldClim/SRTM-derived reconnaissance terrain value at or around the centroid.", "number", "m"
                elif column == "slope_degrees_approx":
                    definition, dtype, unit = "Approximate local slope derived from neighboring 2.5 arc-minute elevation cells.", "number", "degrees"
                else:
                    definition, dtype = column.replace("_", " ").capitalize() + ".", "text or number"
            rows.append({"table": table_name, "column": column, "definition": definition, "data_type": dtype, "unit": unit, "missing_value_policy": "Blank means unavailable/not reported; zero is retained only as a measured or derived zero."})
    return pd.DataFrame(rows)


def validate_outputs(known, grid, materials, material_stats):
    valid_known_bounds = known["latitude"].between(5, 38.5) & known["longitude"].between(67, 99)
    checks = {
        "release_date": date.today().isoformat(),
        "model_version": MODEL_VERSION,
        "known_site_rows": int(len(known)),
        "known_site_unique_record_ids": int(known["record_id"].nunique()),
        "known_site_coordinates_within_expected_india_bounds": int(valid_known_bounds.sum()),
        "known_site_coordinates_outside_expected_india_bounds": int((~valid_known_bounds).sum()),
        "known_site_out_of_bounds_record_ids": known.loc[~valid_known_bounds, "record_id"].tolist(),
        "grid_rows": int(len(grid)),
        "grid_unique_h3_cells": int(grid["h3_r6"].nunique()),
        "grid_unique_record_ids": int(grid["record_id"].nunique()),
        "grid_candidate_rows": int(grid["record_class"].isin(["high_priority_candidate", "priority_candidate"]).sum()),
        "grid_high_priority_candidate_rows": int((grid["record_class"] == "high_priority_candidate").sum()),
        "grid_known_evidence_area_rows": int((grid["record_class"] == "known_evidence_area").sum()),
        "grid_district_join_rate": float(grid["district_2011"].notna().mean()),
        "grid_geology_join_rate": float(grid["geology_geom_id"].notna().mean()),
        "grid_climate_join_rate": float(grid["temperature_mean_c_rolling_12m"].notna().mean()),
        "weather_reference_period_start": WEATHER_START.isoformat(),
        "weather_reference_period_end": WEATHER_END.isoformat(),
        "weather_expected_days": WEATHER_EXPECTED_DAYS,
        "grid_weather_complete_period_rate": float((grid["weather_valid_days_min_rolling_12m"] == WEATHER_EXPECTED_DAYS).mean()),
        "grid_population_join_rate": float(grid["population_estimate_2020_grid"].notna().mean()),
        "priority_material_rows": int(len(materials)),
        "official_india_critical_rows": int(materials["official_india_critical_2023"].sum()),
        "materials_with_any_mrds_evidence": int((material_stats["known_evidence_records"] > 0).sum()),
        "materials_with_candidate_percentiles": int((material_stats["known_evidence_records"] >= 5).sum()),
        "materials_spatially_validated": int((material_stats["spatial_cv_folds"] > 0).sum()),
        "material_models_passing_minimum_holdout_auc": int((material_stats["spatial_holdout_pseudoabsence_roc_auc"] >= 0.60).sum()),
        "candidate_rows_by_top_material": {
            str(key): int(value) for key, value in grid.loc[
                grid["record_class"].isin(["high_priority_candidate", "priority_candidate"]), "top_material"
            ].value_counts().sort_index().items()
        },
        "high_priority_materials": sorted(grid.loc[grid["record_class"] == "high_priority_candidate", "top_material"].dropna().unique().tolist()),
        "score_min": float(grid["prospectivity_score_max"].min()),
        "score_max": float(grid["prospectivity_score_max"].max()),
        "required_interpretation": "Candidate scores are reconnaissance indices and must not be interpreted as discoveries, reserves, resources, grades, or drilling targets.",
    }
    checks["checks_pass"] = bool(
        checks["known_site_rows"] > 0
        and checks["known_site_rows"] == checks["known_site_unique_record_ids"]
        and checks["grid_rows"] == checks["grid_unique_h3_cells"] == checks["grid_unique_record_ids"]
        and checks["priority_material_rows"] == 50
        and checks["official_india_critical_rows"] == 30
        and checks["grid_climate_join_rate"] > 0.99
        and checks["grid_weather_complete_period_rate"] > 0.99
        and 0 <= checks["score_min"] <= checks["score_max"] <= 1
    )
    return checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    materials, materials_by_name, materials_export = load_materials()
    print("loading census")
    census = load_census_districts()
    print("building H3 grid")
    cells, centroids, _ = make_h3_grid()
    print(f"H3 cells: {len(cells):,}")
    print("joining districts")
    cells, _ = attach_districts(cells, centroids, census)
    print("joining geology")
    cells, _ = attach_geology(cells, centroids)
    print("joining climate")
    cells, climate = attach_climate(cells)
    print("aggregating WorldPop")
    cells = attach_population(cells)
    print("sampling terrain")
    cells = attach_terrain(cells)
    cells["weather_class_derived"] = cells.apply(classify_weather, axis=1)
    print("building known sites")
    known = build_known_sites(cells.drop(columns="geometry"), materials_by_name, census)
    print("scoring prospectivity")
    known_for_model = known[
        known["latitude"].between(5, 38.5)
        & known["longitude"].between(67, 99)
        & known["district_2011"].notna()
    ].copy()
    cells, material_stats = score_prospectivity(cells, known_for_model, materials, materials_by_name)
    print("spatially validating supported material models")
    model_validation = validate_material_models(cells, known_for_model, materials)
    material_stats = material_stats.merge(model_validation, on="material_name", how="left", validate="one_to_one")
    cells = apply_validation_gated_candidate_classes(cells, model_validation)
    cells = add_profiles_and_flags(cells)

    grid_columns = [
        "record_id", "record_class", "latitude", "longitude", "coordinate_reference_system", "coordinate_precision_note",
        "h3_r6", "grid_area_km2", "cell_boundary_wkt", "state_or_ut_2011", "district_2011", "census_state_code_2011",
        "census_district_code_2011", "population_estimate_2020_grid", "population_density_estimate_2020_per_km2",
        "census_households_2011_district", "census_population_2011_district", "census_male_2011_district", "census_female_2011_district",
        "census_age_0_6_2011_district", "census_sc_2011_district", "census_st_2011_district", "census_literate_2011_district",
        "census_workers_2011_district", "census_nonworkers_2011_district", "census_female_share_2011_district",
        "census_age_0_6_share_2011_district", "census_sc_share_2011_district", "census_st_share_2011_district",
        "census_literacy_rate_2011_district_age7plus", "census_worker_share_2011_district", "census_area_km2_2011_district",
        "census_population_density_2011_district", "geology_age_code", "geology_age", "geology_supergroup", "geology_group",
        "geology_stratigraphy", "geology_geom_id", "geological_profile_json", "elevation_m", "slope_degrees_approx",
        "local_relief_m_approx", "terrain_class", "geographical_assessment_json", "weather_class_derived",
        "weather_reference_period_start", "weather_reference_period_end", "weather_reference_period_days",
        "weather_temporal_resolution", "weather_time_standard", "temperature_mean_c_rolling_12m",
        "temperature_mean_daily_min_c_rolling_12m", "temperature_mean_daily_max_c_rolling_12m",
        "temperature_monthly_mean_c_json_rolling_12m", "precipitation_total_mm_rolling_12m",
        "precipitation_monthly_total_mm_json_rolling_12m", "relative_humidity_mean_pct_rolling_12m",
        "wind_speed_2m_mean_m_s_rolling_12m", "weather_valid_days_min_rolling_12m",
        "weather_data_completeness_pct_rolling_12m", "climate_grid_latitude", "climate_grid_longitude",
        "climate_grid_distance_km", "weather_profile_json", "nearest_known_site_km", "known_site_count_within_100km",
        "top_material", "top_materials_json", "top_material_scores_json", "top_material_percentiles_json",
        "top_material_nearest_known_km_json", "top_material_chemical_names_json", "top_material_symbols_or_formulae_json",
        "prospectivity_score_max", "top_material_percentile", "top_material_nearest_known_km", "top_material_known_evidence_records",
        "model_support_level", "top_material_spatial_cv_auc", "top_material_spatial_cv_recall_at_background_top5pct",
        "model_validation_tier", "candidate_rank_national", "candidate_promotion_rule", "model_version",
        "prospectivity_index_definition", "model_limitations",
        "record_observation_type", "source_dataset_ids_json", "data_quality_flags_json",
    ]
    grid = pd.DataFrame(cells.drop(columns="geometry"))[grid_columns]
    known_export = known.drop(columns=["_priority_materials"])

    known_path = OUT / "india_known_mining_sites.csv"
    grid_path = OUT / "india_mining_prospectivity_grid_h3_r6.csv"
    candidate_path = OUT / "india_mining_candidate_areas_validation_gated.csv"
    materials_path = OUT / "india_strategic_materials_top50.csv"
    stats_path = OUT / "material_model_support.csv"
    model_validation_path = OUT / "material_model_validation.csv"
    sources_path = OUT / "source_registry.csv"
    dictionary_path = OUT / "data_dictionary.csv"
    known_export.to_csv(known_path, index=False, quoting=csv.QUOTE_MINIMAL)
    grid.to_csv(grid_path, index=False, quoting=csv.QUOTE_MINIMAL)
    grid.loc[
        grid["record_class"].isin(["high_priority_candidate", "priority_candidate"])
    ].sort_values("candidate_rank_national").to_csv(candidate_path, index=False, quoting=csv.QUOTE_MINIMAL)
    materials_export.to_csv(materials_path, index=False)
    material_stats.to_csv(stats_path, index=False)
    model_validation.to_csv(model_validation_path, index=False)
    pd.DataFrame(SOURCE_REGISTRY).to_csv(sources_path, index=False)
    dictionary = make_data_dictionary(known_export, grid, materials_export)
    dictionary.to_csv(dictionary_path, index=False)
    validation = validate_outputs(known_export, grid, materials_export, material_stats)
    (OUT / "validation_report.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    weather_validation = validate_weather_source(climate)
    (OUT / "nasa_power_rolling_12m_validation.json").write_text(
        json.dumps(weather_validation, indent=2), encoding="utf-8"
    )
    print(json.dumps(validation, indent=2))
    if not validation["checks_pass"]:
        raise SystemExit("validation checks failed")
    if not weather_validation["checks_pass"]:
        raise SystemExit("NASA POWER rolling-weather validation checks failed")


if __name__ == "__main__":
    main()
