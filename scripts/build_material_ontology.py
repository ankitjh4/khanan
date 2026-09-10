#!/usr/bin/env python3
"""Build KHANAN's source-observed, authority-verified v1 material ontology.

The ontology deliberately separates material identity from model eligibility.
Adding an element, mineral species, ore, rock, group, or industrial material to
the catalogue never causes a prospectivity score to be generated.  The v0.6
model targets remain unchanged until independent evidence and validation justify
an explicit modelling change.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from build_dataset import MRDS_MATERIAL_PATTERNS, SOURCE_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sources" / "raw"
OUT = ROOT / "outputs"
CONFIG = ROOT / "config"

IMA_SOURCE_ID = "SRC_IMA_CNMNC_MINERAL_LIST_2026_09"
IUPAC_SOURCE_ID = "SRC_IUPAC_PERIODIC_TABLE_2022"
MCS_SOURCE_ID = "SRC_USGS_MCS_2026"
IBM_ABANDONED_SOURCE_ID = "SRC_IBM_ABANDONED_MINE_SITES"
IBM_CONCESSIONS_SOURCE_ID = "SRC_IBM_INDIAN_MINERALS_YEARBOOK_2024_CONCESSIONS"
IBM_STATE_REVIEW_SOURCE_ID = "SRC_IBM_INDIAN_MINERALS_YEARBOOK_2024_STATE_REVIEWS"

ONTOLOGY_PATH = OUT / "india_material_ontology_v1.csv"
CROSSWALK_PATH = OUT / "material_source_term_crosswalk_v1.csv"
VALIDATION_PATH = OUT / "material_ontology_validation_v1.json"

BASELINE_GRID_SHA256 = "13307723efac1054666308c77b52ca0c93820a63ce535f578b23a294906136d9"
BASELINE_CANDIDATE_SHA256 = "f730ee1c72a72764c49e95b0cf1b29873df4e32f2ceed2610e534915c760cf04"
IBM_STATE_REVIEW_CANONICAL_ADDITIONS = [
    "Ball clay", "Calcareous shale", "Copper ore", "Diaspore", "Dunite",
    "Fuller's earth", "Glass sand", "Lead-zinc ore", "Leucoxene",
    "Manganese ore", "Marble", "Nickeliferous chromite", "Plastic clay",
    "Pyroxenite", "Sandstone", "Shale", "Silica sand", "Slate",
    "Soapstone", "Ultramafic rocks", "Vanadiferous magnetite",
]


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.casefold().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", "", value)


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


ELEMENT_ROWS = [
    (1, "Hydrogen", "H"), (2, "Helium", "He"), (3, "Lithium", "Li"),
    (4, "Beryllium", "Be"), (5, "Boron", "B"), (6, "Carbon", "C"),
    (7, "Nitrogen", "N"), (8, "Oxygen", "O"), (9, "Fluorine", "F"),
    (10, "Neon", "Ne"), (11, "Sodium", "Na"), (12, "Magnesium", "Mg"),
    (13, "Aluminium", "Al"), (14, "Silicon", "Si"), (15, "Phosphorus", "P"),
    (16, "Sulfur", "S"), (17, "Chlorine", "Cl"), (18, "Argon", "Ar"),
    (19, "Potassium", "K"), (20, "Calcium", "Ca"), (21, "Scandium", "Sc"),
    (22, "Titanium", "Ti"), (23, "Vanadium", "V"), (24, "Chromium", "Cr"),
    (25, "Manganese", "Mn"), (26, "Iron", "Fe"), (27, "Cobalt", "Co"),
    (28, "Nickel", "Ni"), (29, "Copper", "Cu"), (30, "Zinc", "Zn"),
    (31, "Gallium", "Ga"), (32, "Germanium", "Ge"), (33, "Arsenic", "As"),
    (34, "Selenium", "Se"), (35, "Bromine", "Br"), (36, "Krypton", "Kr"),
    (37, "Rubidium", "Rb"), (38, "Strontium", "Sr"), (39, "Yttrium", "Y"),
    (40, "Zirconium", "Zr"), (41, "Niobium", "Nb"), (42, "Molybdenum", "Mo"),
    (43, "Technetium", "Tc"), (44, "Ruthenium", "Ru"), (45, "Rhodium", "Rh"),
    (46, "Palladium", "Pd"), (47, "Silver", "Ag"), (48, "Cadmium", "Cd"),
    (49, "Indium", "In"), (50, "Tin", "Sn"), (51, "Antimony", "Sb"),
    (52, "Tellurium", "Te"), (53, "Iodine", "I"), (54, "Xenon", "Xe"),
    (55, "Cesium", "Cs"), (56, "Barium", "Ba"), (57, "Lanthanum", "La"),
    (58, "Cerium", "Ce"), (59, "Praseodymium", "Pr"), (60, "Neodymium", "Nd"),
    (61, "Promethium", "Pm"), (62, "Samarium", "Sm"), (63, "Europium", "Eu"),
    (64, "Gadolinium", "Gd"), (65, "Terbium", "Tb"), (66, "Dysprosium", "Dy"),
    (67, "Holmium", "Ho"), (68, "Erbium", "Er"), (69, "Thulium", "Tm"),
    (70, "Ytterbium", "Yb"), (71, "Lutetium", "Lu"), (72, "Hafnium", "Hf"),
    (73, "Tantalum", "Ta"), (74, "Tungsten", "W"), (75, "Rhenium", "Re"),
    (76, "Osmium", "Os"), (77, "Iridium", "Ir"), (78, "Platinum", "Pt"),
    (79, "Gold", "Au"), (80, "Mercury", "Hg"), (81, "Thallium", "Tl"),
    (82, "Lead", "Pb"), (83, "Bismuth", "Bi"), (84, "Polonium", "Po"),
    (85, "Astatine", "At"), (86, "Radon", "Rn"), (87, "Francium", "Fr"),
    (88, "Radium", "Ra"), (89, "Actinium", "Ac"), (90, "Thorium", "Th"),
    (91, "Protactinium", "Pa"), (92, "Uranium", "U"), (93, "Neptunium", "Np"),
    (94, "Plutonium", "Pu"), (95, "Americium", "Am"), (96, "Curium", "Cm"),
    (97, "Berkelium", "Bk"), (98, "Californium", "Cf"), (99, "Einsteinium", "Es"),
    (100, "Fermium", "Fm"), (101, "Mendelevium", "Md"), (102, "Nobelium", "No"),
    (103, "Lawrencium", "Lr"), (104, "Rutherfordium", "Rf"), (105, "Dubnium", "Db"),
    (106, "Seaborgium", "Sg"), (107, "Bohrium", "Bh"), (108, "Hassium", "Hs"),
    (109, "Meitnerium", "Mt"), (110, "Darmstadtium", "Ds"), (111, "Roentgenium", "Rg"),
    (112, "Copernicium", "Cn"), (113, "Nihonium", "Nh"), (114, "Flerovium", "Fl"),
    (115, "Moscovium", "Mc"), (116, "Livermorium", "Lv"), (117, "Tennessine", "Ts"),
    (118, "Oganesson", "Og"),
]
ELEMENTS = {fold(name): {"atomic_number": number, "name": name, "symbol": symbol} for number, name, symbol in ELEMENT_ROWS}

PGE_MEMBERS = ["Platinum", "Palladium", "Rhodium", "Ruthenium", "Iridium", "Osmium"]
REE_MEMBERS = [
    "Scandium", "Yttrium", "Lanthanum", "Cerium", "Praseodymium", "Neodymium",
    "Promethium", "Samarium", "Europium", "Gadolinium", "Terbium", "Dysprosium",
    "Holmium", "Erbium", "Thulium", "Ytterbium", "Lutetium",
]


# Terms that are useful geological or industrial entities but are not one IMA
# mineral species.  Blank formulae are intentional for groups, mixtures, rocks,
# and process products.
CURATED_ENTITIES = {
    "Abrasives (manufactured)": ("industrial_material", "", "Manufactured-material commodity; composition varies."),
    "Alumina": ("compound_or_industrial_material", "Al2O3", "Aluminium oxide commodity."),
    "Aluminous laterite": ("rock_or_ore", "", "Lateritic material enriched in aluminium; composition varies."),
    "Apatite group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Asbestos": ("industrial_mineral_group", "", "Commercial fibrous-mineral group; not one mineral species."),
    "Base metals": ("material_group", "", "Nonspecific commodity group."),
    "Bauxite": ("rock_or_ore", "", "Aluminium ore comprising multiple minerals; not one mineral species."),
    "Biotite group": ("mineral_group", "", "Group-level term under modern mica nomenclature."),
    "Calcareous shell material": ("industrial_material", "", "Source term limeshell; composition varies."),
    "Cement": ("industrial_material", "", "Manufactured binder; composition varies."),
    "Chalk": ("rock_or_industrial_material", "", "Soft fine-grained carbonate rock; composition and purity vary."),
    "Chalcedony": ("mineral_variety", "SiO2", "Microcrystalline quartz variety, not a separate IMA species."),
    "Chert": ("rock", "", "Siliceous sedimentary rock; composition varies."),
    "Chlorite group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Clay": ("industrial_mineral_group", "", "Particle-size/material class comprising multiple clay minerals."),
    "Diatomite": ("rock_or_industrial_material", "", "Biogenic siliceous sedimentary material; composition varies."),
    "Emerald": ("mineral_variety", "Be3Al2Si6O18", "Chromium/vanadium-bearing beryl variety."),
    "Feldspar group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Fire clay": ("industrial_material", "", "Refractory clay commodity comprising variable clay-mineral assemblages."),
    "Garnet group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Gemstones": ("material_group", "", "Use-based group rather than a mineral species."),
    "Granite": ("rock", "", "Igneous rock and dimension-stone commodity; composition varies."),
    "Iron and steel": ("alloy_or_industrial_material", "", "Commodity group including iron and steel products."),
    "Iron ore": ("ore_group", "", "Ore-class term; mineralogy and grade vary."),
    "Iron oxide pigments": ("industrial_material", "", "Pigment commodity comprising natural or synthetic iron oxides."),
    "Kaolin": ("industrial_mineral_group", "", "Kaolin is an industrial clay dominated by kaolinite-group minerals."),
    "Kyanite and related minerals": ("mineral_group", "Al2SiO5", "Industrial grouping of Al2SiO5 polymorphs."),
    "Lignite": ("energy_commodity", "", "Low-rank coal; composition varies."),
    "Lime": ("compound_or_industrial_material", "CaO", "Commercial lime is primarily calcium oxide; products vary."),
    "Lime kankar": ("rock_or_industrial_material", "", "Impure nodular calcareous material; composition varies. IBM source spells this 'Lime kanker'."),
    "Limestone": ("rock_or_industrial_material", "", "Carbonate rock; commonly calcite-rich but composition varies."),
    "Limonite": ("mineral_mixture_or_ore", "", "Field/ore term for hydrated iron oxides; not one mineral species."),
    "Magnesium compounds": ("compound_group", "", "Commodity group; no single chemical formula."),
    "Manganese oxide mixture": ("mineral_mixture_or_ore", "", "Hydrous manganese-oxide source term; composition varies."),
    "Marl": ("rock", "", "Calcareous clay-rich sedimentary material; composition varies."),
    "Mica group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Mineral pigments": ("industrial_material", "", "Use-based mineral commodity group."),
    "Monazite group": ("mineral_group", "", "REE-phosphate mineral group; species depends on dominant REE."),
    "Moulding sand": ("industrial_material", "", "Foundry-sand commodity; composition and specifications vary."),
    "Natural gas": ("energy_commodity", "", "Hydrocarbon mixture, commonly methane-rich."),
    "Nitrogen (fixed)—ammonia": ("compound_or_industrial_material", "NH3", "Fixed-nitrogen commodity represented by ammonia."),
    "Olivine group": ("mineral_group", "", "Solid-solution mineral group; composition varies."),
    "Ochre": ("industrial_material", "", "Natural earthy pigment material; mineral composition varies."),
    "Perlite": ("rock_or_industrial_material", "", "Hydrated volcanic glass used as an industrial material."),
    "Petroleum": ("energy_commodity", "", "Complex hydrocarbon mixture; no single chemical formula."),
    "Phosphorite": ("rock_or_ore", "", "Phosphate rock; mineralogy and grade vary."),
    "Platinum-group elements": ("material_group", "", "Aggregate of six platinum-group elements."),
    "Potash": ("industrial_material_group", "", "Potassium-bearing fertilizer commodity; compounds vary."),
    "Psilomelane": ("mineral_mixture_or_obsolete_name", "", "Historical field term for hard manganese oxides; not one valid IMA species."),
    "Pyroxene group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Rare metals": ("material_group", "", "Nonspecific exploration/commodity group."),
    "Rare-earth elements": ("material_group", "", "Aggregate of scandium, yttrium, and the lanthanides used by the project."),
    "Ruby": ("mineral_variety", "Al2O3", "Chromium-bearing corundum variety."),
    "Sand and gravel (industrial)": ("industrial_material", "", "Specification-based aggregate commodity; composition varies."),
    "Sapphire": ("mineral_variety", "Al2O3", "Gem corundum variety."),
    "Semi-precious gemstones": ("material_group", "", "Use-based historical commodity group."),
    "Sericite": ("mineral_mixture_or_variety", "", "Fine-grained white mica field term; not one mineral species."),
    "Serpentine group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Siliceous earth": ("industrial_material", "", "Silica-rich earthy material; composition varies."),
    "Soda ash": ("compound_or_industrial_material", "Na2CO3", "Commercial sodium carbonate commodity."),
    "Sodium sulfate": ("compound_or_industrial_material", "Na2SO4", "Sodium sulfate chemical commodity."),
    "Sulfuric acid": ("compound_or_industrial_material", "H2SO4", "Sulfuric-acid chemical commodity."),
    "Titanium dioxide pigment": ("compound_or_industrial_material", "TiO2", "Pigment-grade titanium dioxide product."),
    "Titanium mineral concentrates": ("ore_concentrate_group", "", "Concentrate commodity; mineral composition varies."),
    "Titanium sponge metal": ("industrial_material", "Ti", "Porous titanium metal intermediate."),
    "Tourmaline group": ("mineral_group", "", "Group-level source term; species and formula vary."),
    "Vermiculite": ("industrial_mineral_group", "", "Commercial/group term; composition varies."),
    "Wad": ("mineral_mixture_or_ore", "", "Soft hydrous manganese-oxide mixture; not one mineral species."),
    "Wolframite group": ("mineral_group", "(Fe,Mn)WO4", "Solid-solution ore-mineral series/group term."),
    "White earth": ("industrial_material", "", "Nonspecific source commodity term retained without a chemical formula."),
    "Laterite": ("rock", "", "Highly weathered residual material; composition and ore significance vary."),
    "Quartzite": ("rock", "", "Quartz-rich metamorphic rock; composition and purity vary."),
}


ALIASES = {
    "amethyst": ["Quartz"],
    "aluminum": ["Aluminium"],
    "bariumbarite": ["Baryte"],
    "barite": ["Baryte"],
    "bentonite": ["Montmorillonite", "Clay"],
    "boehmite": ["Böhmite"],
    "bixbyite": ["Bixbyite-(Mn)"],
    "cryptomalene": ["Cryptomelane"],
    "fluorinefluorite": ["Fluorite"],
    "gypsumanhydrite": ["Gypsum", "Anhydrite"],
    "hausmanite": ["Hausmannite"],
    "piedmontite": ["Piemontite"],
    "spessartite": ["Spessartine"],
    "sulfurpyrite": ["Sulfur", "Pyrite"],
    "titaniumilmenite": ["Ilmenite"],
    "titaniumrutile": ["Rutile"],
    "apatite": ["Apatite group"],
    "bauxite": ["Bauxite"],
    "biotite": ["Biotite group"],
    "chalcedony": ["Chalcedony"],
    "chert": ["Chert"],
    "chlorite": ["Chlorite group"],
    "clay": ["Clay"],
    "feldspar": ["Feldspar group"],
    "felspar": ["Feldspar group"],
    "garnet": ["Garnet group"],
    "hypersthene": ["Pyroxene group"],
    "iridosmine": ["Osmium", "Iridium"],
    "jasper": ["Chalcedony"],
    "kaolin": ["Kaolin"],
    "limonite": ["Limonite"],
    "martite": ["Hematite"],
    "mica": ["Mica group"],
    "monazite": ["Monazite group"],
    "olivine": ["Olivine group"],
    "psilomelane": ["Psilomelane"],
    "pyroxene": ["Pyroxene group"],
    "sericite": ["Sericite"],
    "serpentine": ["Serpentine group"],
    "specularite": ["Hematite"],
    "tetrahedrite": ["Tetrahedrite group"],
    "tourmaline": ["Tourmaline group"],
    "wad": ["Wad"],
    "wolframite": ["Wolframite group"],
    "manganeseoxhydrous": ["Manganese oxide mixture"],
    "argentite": ["Acanthite"],
    "aluminouslaterite": ["Aluminous laterite"],
    "asbestos": ["Asbestos"],
    "diatomite": ["Diatomite"],
    "emerald": ["Emerald"],
    "granite": ["Granite"],
    "ironore": ["Iron ore"],
    "ironorehematite": ["Iron ore", "Hematite"],
    "ironoremagnetite": ["Iron ore", "Magnetite"],
    "iolite": ["Cordierite"],
    "kyaniteandrelatedminerals": ["Kyanite and related minerals"],
    "leadzinore": ["Lead-zinc ore", "Lead", "Zinc", "Iron ore"],
    "leadzincore": ["Lead-zinc ore", "Lead", "Zinc"],
    "limeshell": ["Calcareous shell material"],
    "limestone": ["Limestone"],
    "magnesiumcompounds": ["Magnesium compounds"],
    "manganeseore": ["Manganese ore", "Manganese"],
    "marl": ["Marl"],
    "mouldingsand": ["Moulding sand"],
    "perlite": ["Perlite"],
    "phosphaterock": ["Phosphorite"],
    "phosphorite": ["Phosphorite"],
    "rockphosphate": ["Phosphorite"],
    "rocksalt": ["Halite"],
    "ruby": ["Ruby"],
    "sapphire": ["Sapphire"],
    "selenite": ["Gypsum"],
    "semipreciousstone": ["Semi-precious gemstones"],
    "gemstonecatseye": ["Semi-precious gemstones"],
    "siliceousearth": ["Siliceous earth"],
    "sillamanite": ["Sillimanite"],
    "sodaash": ["Soda ash"],
    "sodiumsulfate": ["Sodium sulfate"],
    "sulphurnative": ["Sulfur"],
    "sulfuricacid": ["Sulfuric acid"],
    "vermiculite": ["Vermiculite"],
    "vermuculite": ["Vermiculite"],
    "basemetals": ["Base metals"],
    "glauconite": ["Glauconite group"],
    "raremetals": ["Rare metals"],
    "rareearthelements": ["Rare-earth elements"],
    "abrasivesmanufactured": ["Abrasives (manufactured)"],
    "alumina": ["Alumina"],
    "cement": ["Cement"],
    "chalk": ["Chalk"],
    "chinaclay": ["Kaolin", "Kaolinite"],
    "clays": ["Clay"],
    "fireclay": ["Fire clay", "Clay"],
    "diamondindustrial": ["Diamond"],
    "feldsparandnephelinesyenite": ["Feldspar group", "Nepheline", "Nepheline syenite"],
    "fluorspar": ["Fluorite"],
    "garnetindustrial": ["Garnet group"],
    "gemstones": ["Gemstones"],
    "graniteonly": ["Granite"],
    "graphitenatural": ["Graphite"],
    "ironandsteel": ["Iron and steel"],
    "ironoxidepigments": ["Iron oxide pigments"],
    "nitrogenfixedammonia": ["Nitrogen (fixed)—ammonia"],
    "rareearths": ["Rare-earth elements"],
    "sandandgravelindustrial": ["Sand and gravel (industrial)"],
    "salt": ["Halite"],
    "lime": ["Lime"],
    "limekanker": ["Lime kankar"],
    "limekankar": ["Lime kankar"],
    "laterite": ["Laterite"],
    "ochre": ["Ochre", "Iron oxide pigments"],
    "whiteeatrh": ["White earth"],
    "whiteearth": ["White earth"],
    "quartzite": ["Quartzite"],
    "ballclay": ["Ball clay", "Clay"],
    "calcareousshale": ["Calcareous shale"],
    "copperore": ["Copper ore", "Copper"],
    "dunite": ["Dunite"],
    "fullersearth": ["Fuller's earth", "Clay"],
    "glasssand": ["Glass sand", "Silica sand", "Quartz"],
    "leadzinc": ["Lead-zinc ore", "Lead", "Zinc"],
    "leucoxene": ["Leucoxene"],
    "marble": ["Marble"],
    "nickeliferouschromite": ["Nickeliferous chromite", "Chromite", "Nickel", "Chromium"],
    "plasticclay": ["Plastic clay", "Clay"],
    "pyrites": ["Pyrite"],
    "pyroxenite": ["Pyroxenite"],
    "sandstone": ["Sandstone"],
    "shale": ["Shale"],
    "silicasand": ["Silica sand", "Quartz"],
    "slate": ["Slate"],
    "soapstone": ["Soapstone", "Talc"],
    "steatite": ["Talc"],
    "ultramaficrocks": ["Ultramafic rocks"],
    "vanadiferousmagnetite": ["Vanadiferous magnetite", "Magnetite", "Vanadium", "Iron"],
    "qtrzfelds": ["Quartz", "Feldspar group"],
    "pbzncu": ["Lead", "Zinc", "Copper"],
    "barytes": ["Baryte"],
    "phyllite": ["Phyllite"],
    "hornblende": ["Hornblende group"],
    "stonedimension": ["Granite"],
    "talcandpyrophyllite": ["Talc", "Pyrophyllite"],
    "tio2pigment": ["Titanium dioxide pigment"],
    "titaniummineralconcentrates": ["Titanium mineral concentrates"],
    "titaniumspongemetal": ["Titanium sponge metal"],
}

# The few group-level names below are not in the main dictionary only because
# they are most naturally introduced through source aliases.
CURATED_ENTITIES.update({
    "Ball clay": ("industrial_mineral_group", "", "Fine-grained plastic kaolinitic clay commodity; mineral proportions vary."),
    "Calcareous shale": ("rock", "", "Calcium-carbonate-bearing shale; mineral composition varies."),
    "Copper ore": ("ore_group", "", "Copper-bearing ore-class term; mineralogy and grade vary."),
    "Dunite": ("rock", "", "Olivine-rich ultramafic igneous rock; mineral proportions vary."),
    "Fuller's earth": ("industrial_mineral_group", "", "Absorbent clay commodity; mineral composition varies."),
    "Glass sand": ("industrial_material", "", "Silica-rich sand selected for glass manufacture; mineralogy and specifications vary."),
    "Glauconite group": ("mineral_group", "", "Group-level/ill-defined source term under modern nomenclature."),
    "Hornblende group": ("mineral_group", "", "Field/group term covering several amphibole species."),
    "Lead-zinc ore": ("ore_group", "", "Combined lead-zinc ore-class term; mineralogy and grade vary."),
    "Leucoxene": ("mineral_mixture_or_ore", "", "Fine-grained titanium-oxide alteration mixture; not one IMA mineral species."),
    "Manganese ore": ("ore_group", "", "Manganese-bearing ore-class term; mineralogy and grade vary."),
    "Marble": ("rock_or_industrial_material", "", "Recrystallized carbonate rock and dimension-stone commodity; composition varies."),
    "Nepheline syenite": ("rock_or_industrial_material", "", "Feldspathoid-rich igneous rock and industrial commodity."),
    "Nickeliferous chromite": ("mineral_mixture_or_ore", "", "Nickel-bearing chromite ore term; mineralogy and grade vary."),
    "Phyllite": ("rock", "", "Fine-grained foliated metamorphic rock; composition varies."),
    "Plastic clay": ("industrial_mineral_group", "", "Plastic-forming clay commodity; mineral composition and specifications vary."),
    "Pyroxenite": ("rock", "", "Pyroxene-rich ultramafic igneous rock; mineral proportions vary."),
    "Sandstone": ("rock_or_industrial_material", "", "Sand-sized clastic sedimentary rock; mineral composition and industrial suitability vary."),
    "Shale": ("rock", "", "Fine-grained fissile sedimentary rock; mineral composition varies."),
    "Silica sand": ("industrial_material", "", "Quartz-rich sand commodity; mineralogy, purity and specifications vary."),
    "Slate": ("rock_or_industrial_material", "", "Fine-grained foliated metamorphic rock and dimension-stone commodity; composition varies."),
    "Soapstone": ("rock_or_industrial_material", "", "Talc-rich metamorphic rock and industrial material; composition varies."),
    "Tetrahedrite group": ("mineral_group", "", "Group-level source term; species depends on dominant constituents."),
    "Ultramafic rocks": ("rock", "", "Broad rock class rich in mafic minerals; individual rock types and compositions vary."),
    "Vanadiferous magnetite": ("mineral_mixture_or_ore", "", "Vanadium-bearing magnetite ore term; mineralogy and grade vary."),
})


def parse_ima_list() -> dict[str, dict]:
    path = RAW / "ima_master_list_2026-09.pdf"
    pattern = re.compile(
        r"^(.+?)\s+(\S.*?)\s+(A|G|Rd|Rn|Q)\s+"
        r"(?:\?|(?:\d{4}(?:-\d{3}[a-z]?| s\.p\.)?))\s+"
    )
    result = {}
    for page_number, page in enumerate(PdfReader(path).pages[2:], start=3):
        for source_line in (page.extract_text() or "").splitlines():
            match = pattern.match(source_line.strip())
            if not match:
                continue
            name, formula, status = match.groups()
            result.setdefault(fold(name), {
                "name": name,
                "formula": formula,
                "status": status,
                "page": page_number,
            })
    if len(result) < 6_000:
        raise RuntimeError(f"IMA parser recovered only {len(result):,} species; expected at least 6,000")
    return result


def legacy_links(text: str, legacy_name_to_id: dict[str, str]) -> list[str]:
    links = []
    for name, patterns in MRDS_MATERIAL_PATTERNS.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            links.append(legacy_name_to_id[name])
    return links


def make_entity_id(entity_type: str, name: str) -> str:
    prefix = {
        "element": "element",
        "mineral_species": "mineral",
        "mineral_group": "group",
        "material_group": "group",
        "industrial_mineral_group": "group",
        "industrial_material_group": "group",
        "compound_group": "group",
        "ore_group": "ore",
        "ore_concentrate_group": "ore",
        "rock_or_ore": "ore",
        "mineral_mixture_or_ore": "ore",
        "energy_commodity": "commodity",
        "rock": "rock",
        "rock_or_industrial_material": "rock",
        "mineral_variety": "variety",
        "mineral_mixture_or_variety": "variety",
        "mineral_mixture_or_obsolete_name": "historical",
        "compound_or_industrial_material": "compound",
        "industrial_material": "material",
        "alloy_or_industrial_material": "material",
    }.get(entity_type, "material")
    return f"{prefix}:{slug(name)}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ima = parse_ima_list()
    legacy = json.loads((CONFIG / "materials.json").read_text(encoding="utf-8"))
    support = pd.read_csv(OUT / "material_model_support.csv", keep_default_na=False).set_index("material_name")

    entities: dict[str, dict] = {}
    names_to_id: dict[str, str] = {}
    entity_sources: defaultdict[str, set[str]] = defaultdict(set)
    entity_notes: defaultdict[str, set[str]] = defaultdict(set)
    parent_ids: defaultdict[str, set[str]] = defaultdict(set)
    evidence_counts: defaultdict[str, Counter] = defaultdict(Counter)

    def add_entity(
        name: str,
        entity_type: str,
        *,
        formula: str = "",
        chemical_names: list[str] | None = None,
        aliases: list[str] | None = None,
        source_ids: list[str] | None = None,
        note: str = "",
        ima_row: dict | None = None,
        atomic_number: int | None = None,
        official: bool = False,
        official_member: bool = False,
        legacy_rank: int | None = None,
        model_target: bool = False,
        representative: list[str] | None = None,
        use_categories: list[str] | None = None,
    ) -> str:
        name_key = fold(name)
        existing_id = names_to_id.get(name_key)
        entity_id = existing_id or make_entity_id(entity_type, name)
        if not existing_id:
            entities[entity_id] = {
                "material_id": entity_id,
                "material_name": name,
                "entity_type": entity_type,
                "english_names": [name],
                "chemical_names": chemical_names or [],
                "symbols_or_formulae": [formula] if formula else [],
                "aliases": aliases or [],
                "representative_ores_or_forms": representative or [],
                "use_categories": use_categories or [],
                "official_india_critical_2023": bool(official),
                "official_india_critical_member_2023": bool(official or official_member),
                "legacy_top50_rank": legacy_rank,
                "model_target_v0_6": bool(model_target),
                "atomic_number": atomic_number,
                "ima_status": "",
                "ima_approved_formula": "",
                "ima_list_page": None,
            }
            names_to_id[name_key] = entity_id
        row = entities[entity_id]
        row["official_india_critical_2023"] = bool(row["official_india_critical_2023"] or official)
        row["official_india_critical_member_2023"] = bool(
            row["official_india_critical_member_2023"] or official or official_member
        )
        row["model_target_v0_6"] = bool(row["model_target_v0_6"] or model_target)
        if legacy_rank is not None:
            row["legacy_top50_rank"] = legacy_rank
        if atomic_number is not None:
            row["atomic_number"] = atomic_number
        for key, values in [
            ("chemical_names", chemical_names or []),
            ("aliases", aliases or []),
            ("representative_ores_or_forms", representative or []),
            ("use_categories", use_categories or []),
        ]:
            existing = {fold(value) for value in row[key]}
            row[key].extend(value for value in values if fold(value) not in existing)
        if formula and formula not in row["symbols_or_formulae"]:
            row["symbols_or_formulae"].append(formula)
        if ima_row:
            row["ima_status"] = ima_row["status"]
            row["ima_approved_formula"] = ima_row["formula"]
            row["ima_list_page"] = ima_row["page"]
            if ima_row["formula"] not in row["symbols_or_formulae"]:
                row["symbols_or_formulae"].append(ima_row["formula"])
            entity_sources[entity_id].add(IMA_SOURCE_ID)
        entity_sources[entity_id].update(source_ids or [])
        if note:
            entity_notes[entity_id].add(note)
        return entity_id

    legacy_name_to_id = {}
    for item in sorted(legacy, key=lambda row: row["priority_rank"]):
        name = item["material_name"]
        element = ELEMENTS.get(fold(name))
        if element:
            entity_type = "element"
            formula = element["symbol"]
            atomic_number = element["atomic_number"]
            sources = [IUPAC_SOURCE_ID]
        elif name == "Graphite":
            entity_type = "mineral_species"
            formula = "C"
            atomic_number = None
            sources = []
        elif name in {"Platinum-group elements", "Rare-earth elements"}:
            entity_type = "material_group"
            formula = ""
            atomic_number = None
            sources = []
        elif name in {"Coal", "Lignite", "Petroleum", "Natural gas"}:
            entity_type = "energy_commodity"
            formula = ""
            atomic_number = None
            sources = []
        elif name in {"Potash", "Kaolin"}:
            entity_type = CURATED_ENTITIES[name][0]
            formula = CURATED_ENTITIES[name][1]
            atomic_number = None
            sources = []
        else:
            entity_type = "material_group"
            formula = ""
            atomic_number = None
            sources = []
        ima_row = ima.get(fold(name)) if entity_type == "mineral_species" else None
        entity_id = add_entity(
            name,
            entity_type,
            formula=formula,
            chemical_names=item["chemical_names"],
            source_ids=sources + ["SRC_INDIA_CRITICAL_2023"] if item["official_india_critical_2023"] else sources,
            note="Legacy v0.6 model target retained without expanding model eligibility.",
            ima_row=ima_row,
            atomic_number=atomic_number,
            official=item["official_india_critical_2023"],
            official_member=item["official_india_critical_2023"],
            legacy_rank=item["priority_rank"],
            model_target=True,
            representative=item["representative_ores_or_forms"],
            use_categories=item["use_categories"],
        )
        legacy_name_to_id[name] = entity_id

    for group_name, members in [
        ("Platinum-group elements", PGE_MEMBERS),
        ("Rare-earth elements", REE_MEMBERS),
    ]:
        group_id = legacy_name_to_id[group_name]
        for member in members:
            element = ELEMENTS[fold(member)]
            member_id = add_entity(
                element["name"], "element", formula=element["symbol"],
                chemical_names=[element["name"].casefold()],
                source_ids=[IUPAC_SOURCE_ID, "SRC_INDIA_CRITICAL_2023"],
                note=f"Independently identified member of the official aggregate {group_name}; not an independently scored v0.6 target.",
                atomic_number=element["atomic_number"],
                official_member=True,
            )
            parent_ids[member_id].add(group_id)

    def ensure_name(name: str, source_id: str) -> str:
        existing = names_to_id.get(fold(name))
        if existing:
            entity_sources[existing].add(source_id)
            ima_row = ima.get(fold(name))
            if ima_row and not entities[existing]["ima_status"]:
                entities[existing]["ima_status"] = ima_row["status"]
                entities[existing]["ima_approved_formula"] = ima_row["formula"]
                entities[existing]["ima_list_page"] = ima_row["page"]
                entity_sources[existing].add(IMA_SOURCE_ID)
            return existing
        element = ELEMENTS.get(fold(name))
        if element:
            return add_entity(
                element["name"], "element", formula=element["symbol"],
                chemical_names=[element["name"].casefold()],
                source_ids=[source_id, IUPAC_SOURCE_ID],
                note="Element independently present in a source-observed India material or commodity term.",
                atomic_number=element["atomic_number"],
            )
        ima_row = ima.get(fold(name))
        if ima_row:
            return add_entity(
                ima_row["name"], "mineral_species", formula=ima_row["formula"],
                chemical_names=[ima_row["name"].casefold()], source_ids=[source_id],
                note="Mineral species observed in an India source and verified against the IMA-CNMNC list.",
                ima_row=ima_row,
            )
        if name not in CURATED_ENTITIES:
            raise KeyError(f"No controlled entity definition for {name!r}")
        entity_type, formula, note = CURATED_ENTITIES[name]
        return add_entity(
            name, entity_type, formula=formula, chemical_names=[] if not formula else [name.casefold()],
            source_ids=[source_id], note=note,
        )

    def precise_links(term: str, source_id: str) -> tuple[list[str], str]:
        ids = []
        method = []
        term_key = fold(term)
        if term_key in ALIASES:
            ids.extend(ensure_name(name, source_id) for name in ALIASES[term_key])
            method.append("curated_alias")
        if term_key in ELEMENTS:
            ids.append(ensure_name(ELEMENTS[term_key]["name"], source_id))
            method.append("iupac_element_name_match")
        if term_key in ima:
            ids.append(ensure_name(ima[term_key]["name"], source_id))
            method.append("ima_name_match")
        pieces = re.split(r"\s*(?:,|;|/|&|\+|\band\b)\s*", term, flags=re.IGNORECASE)
        for piece in pieces:
            piece = re.sub(r"\([^)]*\)", "", piece)
            piece = re.sub(r"\b(?:ore|metal|minerals?|stones?|only)\b", "", piece, flags=re.IGNORECASE)
            piece = clean(piece)
            if not piece:
                continue
            piece_key = fold(piece)
            if piece_key in ALIASES:
                ids.extend(ensure_name(name, source_id) for name in ALIASES[piece_key])
                method.append("curated_component_alias")
            elif piece_key in ELEMENTS:
                ids.append(ensure_name(ELEMENTS[piece_key]["name"], source_id))
                method.append("iupac_element_component_match")
            elif piece_key in ima:
                ids.append(ensure_name(ima[piece_key]["name"], source_id))
                method.append("ima_component_match")
        ids = list(dict.fromkeys(ids))
        return ids, "+".join(sorted(set(method))) or "none"

    crosswalk_rows = []

    def add_crosswalk(source_id: str, source_table: str, source_field: str, term: str, count: int, inherited_names: list[str] | None = None):
        inherited_ids = [legacy_name_to_id[name] for name in (inherited_names or []) if name in legacy_name_to_id]
        pattern_ids = legacy_links(term, legacy_name_to_id)
        precise_ids, method = precise_links(term, source_id)
        ids = list(dict.fromkeys(inherited_ids + pattern_ids + precise_ids))
        methods = []
        if inherited_ids:
            methods.append("source_pipeline_mapping")
        if pattern_ids:
            methods.append("legacy_anchored_pattern")
        if method != "none":
            methods.append(method)
        if not ids:
            methods.append("unresolved_or_nonspecific")
        for entity_id in ids:
            entity_sources[entity_id].add(source_id)
            evidence_counts[entity_id]["source_term_occurrences_total"] += int(count)
            evidence_counts[entity_id][source_table] += int(count)
        crosswalk_rows.append({
            "source_id": source_id,
            "source_table": source_table,
            "source_field": source_field,
            "source_term": term,
            "source_term_occurrences": int(count),
            "normalized_material_ids_json": jdump(ids),
            "normalized_material_names_json": jdump([entities[entity_id]["material_name"] for entity_id in ids]),
            "mapping_method": "+".join(methods),
            "mapping_status": "mapped" if ids else "unresolved_or_nonspecific",
        })

    mrds = pd.read_csv(RAW / "mrds" / "mrds.csv", low_memory=False)
    mrds = mrds[mrds["country"].astype(str).str.casefold().eq("india")].copy()
    for fields, source_field in [
        (["commod1", "commod2", "commod3"], "commodity"),
        (["ore"], "ore_mineral"),
        (["gangue"], "gangue_mineral"),
        (["other_matl"], "other_material"),
    ]:
        counter = Counter()
        for _, row in mrds[fields].iterrows():
            row_terms = set()
            for value in row:
                if not clean(value):
                    continue
                row_terms.update(clean(piece) for piece in re.split(r"[,;]", str(value)) if clean(piece))
            counter.update(row_terms)
        for term, count in sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold())):
            add_crosswalk("SRC_USGS_MRDS", "mrds_india", source_field, term, count)

    def grouped_pipeline_terms(
        path: Path,
        term_column: str,
        mapping_column: str,
        source_id: str,
        source_table: str,
        filters: dict[str, str] | None = None,
    ):
        frame = pd.read_csv(path, keep_default_na=False)
        for column, value in (filters or {}).items():
            frame = frame.loc[frame[column].astype(str).eq(value)].copy()
        grouped = defaultdict(lambda: {"count": 0, "names": set()})
        for row in frame.itertuples(index=False):
            term = clean(getattr(row, term_column))
            if not term:
                continue
            grouped[term]["count"] += 1
            try:
                grouped[term]["names"].update(json.loads(getattr(row, mapping_column)))
            except (TypeError, json.JSONDecodeError):
                pass
        for term, values in sorted(grouped.items(), key=lambda item: item[0].casefold()):
            add_crosswalk(source_id, source_table, term_column, term, values["count"], sorted(values["names"]))

    grouped_pipeline_terms(
        OUT / "india_ibm_nmi_2025_resource_inventory.csv", "mineral_name_source",
        "normalized_top50_materials_json", "SRC_IBM_NMI_2025", "ibm_nmi_2025",
    )
    grouped_pipeline_terms(
        OUT / "india_ibm_mcdr_inspection_events_2023_2026.csv", "mineral_source",
        "normalized_top50_materials_json", "SRC_IBM_MCDR_INSPECTIONS_2023_2026", "ibm_mcdr_events",
    )
    grouped_pipeline_terms(
        OUT / "india_ibm_abandoned_mine_sites.csv", "mineral_source",
        "normalized_material_names_json", IBM_ABANDONED_SOURCE_ID, "ibm_abandoned_mine_sites",
    )
    grouped_pipeline_terms(
        OUT / "india_ibm_mining_lease_distribution_2024.csv", "category_source",
        "normalized_material_names_json", IBM_CONCESSIONS_SOURCE_ID,
        "ibm_mineral_concession_2024_by_mineral", {"dimension": "mineral", "is_total": "False"},
    )
    grouped_pipeline_terms(
        OUT / "india_ibm_auctioned_mineral_concessions_2023_24.csv", "mineral_source",
        "normalized_material_names_json", IBM_CONCESSIONS_SOURCE_ID,
        "ibm_auctioned_concessions_2023_24",
    )

    state_review_config = json.loads(
        (CONFIG / "ibm_imyb_2024_state_review_occurrences.json").read_text(encoding="utf-8")
    )
    state_review_terms = Counter()
    for chapter in state_review_config["chapters"]:
        for combined_term in chapter.get("district_occurrences", {}):
            state_review_terms.update(clean(term) for term in combined_term.split("|") if clean(term))
        for occurrence in chapter.get("named_area_occurrences", []):
            state_review_terms.update(
                clean(term) for term in occurrence["materials"].split("|") if clean(term)
            )
        state_review_terms.update(clean(term) for term in chapter.get("statewide_occurrences", []) if clean(term))
    for term, count in sorted(state_review_terms.items(), key=lambda item: item[0].casefold()):
        add_crosswalk(
            IBM_STATE_REVIEW_SOURCE_ID,
            "ibm_imyb_state_review_occurrences",
            "source_material_term",
            term,
            int(count),
        )

    auction = pd.read_csv(OUT / "india_official_critical_mineral_blocks.csv", keep_default_na=False)
    auction_terms = Counter()
    for row in auction.itertuples(index=False):
        source_names = json.loads(row.source_materials_json)
        for term in source_names:
            auction_terms[term] += 1
    for term, count in sorted(auction_terms.items(), key=lambda item: item[0].casefold()):
        add_crosswalk(
            "SRC_MSTC_CRITICAL_MBS_T1_T8", "critical_mineral_auction_events", "source_materials_json",
            term, count,
        )

    mcs = pd.read_csv(RAW / "usgs_mcs2026_commodities_data.csv", encoding="cp1252", low_memory=False)
    india_mcs = mcs[mcs["Country"].astype(str).str.casefold().eq("india")]
    for term, count in india_mcs["Commodity"].value_counts().sort_index().items():
        add_crosswalk(MCS_SOURCE_ID, "usgs_mcs2026_india_rows", "Commodity", term, int(count))

    source_count_columns = [
        "mrds_india", "ibm_nmi_2025", "ibm_mcdr_events",
        "ibm_abandoned_mine_sites", "ibm_mineral_concession_2024_by_mineral",
        "ibm_auctioned_concessions_2023_24", "ibm_imyb_state_review_occurrences",
        "critical_mineral_auction_events",
        "usgs_mcs2026_india_rows",
    ]
    ontology_rows = []
    for entity_id, row in entities.items():
        model_level = ""
        model_records = 0
        if row["material_name"] in support.index:
            support_row = support.loc[row["material_name"]]
            model_level = clean(support_row.get("model_support_level"))
            model_records = int(float(support_row.get("known_evidence_records") or 0))
        if row["entity_type"] == "element":
            authority_status = "iupac_element"
        elif row["ima_status"]:
            authority_status = "ima_cnmnc_valid_species"
        elif row["entity_type"] in {"rock", "rock_or_ore", "rock_or_industrial_material"}:
            authority_status = "source_observed_geological_material_curated_classification"
        else:
            authority_status = "source_observed_curated_classification"
        result = dict(row)
        for key in ["english_names", "chemical_names", "symbols_or_formulae", "aliases", "representative_ores_or_forms", "use_categories"]:
            result[f"{key}_json"] = jdump(result.pop(key))
        result["parent_material_ids_json"] = jdump(sorted(parent_ids[entity_id]))
        result["evidence_source_ids_json"] = jdump(sorted(entity_sources[entity_id]))
        result["authority_status"] = authority_status
        result["model_support_level_v0_6"] = model_level
        result["model_known_evidence_records_v0_6"] = model_records
        result["source_term_occurrences_total"] = evidence_counts[entity_id]["source_term_occurrences_total"]
        for column in source_count_columns:
            result[f"{column}_source_term_occurrences"] = evidence_counts[entity_id][column]
        result["ontology_notes"] = " ".join(sorted(entity_notes[entity_id]))
        ontology_rows.append(result)

    ontology = pd.DataFrame(ontology_rows).sort_values(
        ["model_target_v0_6", "official_india_critical_2023", "entity_type", "material_name"],
        ascending=[False, False, True, True],
    )
    ontology.insert(0, "ontology_rank", range(1, len(ontology) + 1))
    crosswalk = pd.DataFrame(crosswalk_rows).sort_values(
        ["source_id", "source_table", "source_field", "source_term"],
    )

    ibm_state_review_addition_ids = [
        names_to_id.get(fold(name), "") for name in IBM_STATE_REVIEW_CANONICAL_ADDITIONS
    ]
    grid_sha256 = sha256_file(OUT / "india_mining_prospectivity_grid_h3_r6.csv")
    candidate_sha256 = sha256_file(OUT / "india_mining_candidate_areas_validation_gated.csv")
    validation = {
        "ontology_version": "v1.0-alpha.23",
        "ontology_rows": int(len(ontology)),
        "unique_material_ids": int(ontology["material_id"].nunique()),
        "unique_material_names_casefolded": int(ontology["material_name"].str.casefold().nunique()),
        "entity_type_counts": {str(k): int(v) for k, v in ontology["entity_type"].value_counts().sort_index().items()},
        "legacy_model_targets": int(ontology["model_target_v0_6"].sum()),
        "official_india_critical_aggregate_targets": int(ontology["official_india_critical_2023"].sum()),
        "official_india_critical_entities_or_group_members": int(ontology["official_india_critical_member_2023"].sum()),
        "ima_verified_species": int(ontology["ima_status"].ne("").sum()),
        "iupac_element_entities": int(ontology["entity_type"].eq("element").sum()),
        "entities_with_direct_source_term_occurrences": int(ontology["source_term_occurrences_total"].gt(0).sum()),
        "crosswalk_rows": int(len(crosswalk)),
        "crosswalk_source_terms_mapped": int(crosswalk["mapping_status"].eq("mapped").sum()),
        "crosswalk_source_terms_unresolved_or_nonspecific": int(crosswalk["mapping_status"].ne("mapped").sum()),
        "crosswalk_mapping_rate": float(crosswalk["mapping_status"].eq("mapped").mean()),
        "unresolved_terms": crosswalk.loc[
            crosswalk["mapping_status"].ne("mapped"),
            ["source_id", "source_field", "source_term", "source_term_occurrences"],
        ].to_dict(orient="records"),
        "ima_parser_species_rows": int(len(ima)),
        "ima_source_pdf_pages": int(len(PdfReader(RAW / "ima_master_list_2026-09.pdf").pages)),
        "ima_source_pdf_sha256": sha256_file(RAW / "ima_master_list_2026-09.pdf"),
        "ima_document_stated_valid_species": 6239,
        "ima_parser_document_row_coverage": float(len(ima) / 6239),
        "usgs_mcs2026_source_rows": int(len(mcs)),
        "usgs_mcs2026_india_rows": int(len(india_mcs)),
        "usgs_mcs2026_source_sha256": sha256_file(RAW / "usgs_mcs2026_commodities_data.csv"),
        "ibm_abandoned_mine_source_terms": int(
            crosswalk.loc[crosswalk["source_id"].eq(IBM_ABANDONED_SOURCE_ID), "source_term"].nunique()
        ),
        "ibm_abandoned_mine_source_terms_mapped": int(
            crosswalk.loc[
                crosswalk["source_id"].eq(IBM_ABANDONED_SOURCE_ID)
                & crosswalk["mapping_status"].eq("mapped")
            ].shape[0]
        ),
        "ibm_mineral_concession_2024_source_terms": int(
            crosswalk.loc[
                crosswalk["source_id"].eq(IBM_CONCESSIONS_SOURCE_ID)
                & crosswalk["source_table"].eq("ibm_mineral_concession_2024_by_mineral"),
                "source_term",
            ].nunique()
        ),
        "ibm_auctioned_concession_2023_24_source_terms": int(
            crosswalk.loc[
                crosswalk["source_id"].eq(IBM_CONCESSIONS_SOURCE_ID)
                & crosswalk["source_table"].eq("ibm_auctioned_concessions_2023_24"),
                "source_term",
            ].nunique()
        ),
        "ibm_state_review_source_terms": int(
            crosswalk.loc[
                crosswalk["source_id"].eq(IBM_STATE_REVIEW_SOURCE_ID),
                "source_term",
            ].nunique()
        ),
        "ibm_state_review_source_term_occurrences": int(sum(state_review_terms.values())),
        "ibm_state_review_source_terms_mapped": int(
            crosswalk.loc[
                crosswalk["source_id"].eq(IBM_STATE_REVIEW_SOURCE_ID)
                & crosswalk["mapping_status"].eq("mapped")
            ].shape[0]
        ),
        "ibm_state_review_canonical_entity_additions": IBM_STATE_REVIEW_CANONICAL_ADDITIONS,
        "ibm_state_review_canonical_entity_addition_count": len(IBM_STATE_REVIEW_CANONICAL_ADDITIONS),
        "ibm_state_review_canonical_entity_additions_all_present": all(ibm_state_review_addition_ids),
        "ibm_state_review_canonical_entity_additions_all_source_attributed": all(
            entity_id and IBM_STATE_REVIEW_SOURCE_ID in entity_sources[entity_id]
            for entity_id in ibm_state_review_addition_ids
        ),
        "baseline_grid_sha256_expected": BASELINE_GRID_SHA256,
        "baseline_grid_sha256_observed": grid_sha256,
        "baseline_grid_unchanged": grid_sha256 == BASELINE_GRID_SHA256,
        "baseline_candidate_sha256_expected": BASELINE_CANDIDATE_SHA256,
        "baseline_candidate_sha256_observed": candidate_sha256,
        "baseline_candidate_unchanged": candidate_sha256 == BASELINE_CANDIDATE_SHA256,
        "model_eligibility_policy": "Ontology inclusion does not confer model eligibility. Only the 50 explicitly retained v0.6 model targets are scored until separately reviewed and validated.",
    }
    validation["checks_pass"] = bool(
        validation["ontology_rows"] == validation["unique_material_ids"] == validation["unique_material_names_casefolded"]
        and validation["ontology_rows"] >= 250
        and validation["legacy_model_targets"] == 50
        and validation["official_india_critical_aggregate_targets"] == 30
        and validation["ima_verified_species"] >= 60
        and validation["ibm_abandoned_mine_source_terms"] == 26
        and validation["ibm_abandoned_mine_source_terms_mapped"] == 26
        and validation["ibm_state_review_source_terms"] == 101
        and validation["ibm_state_review_source_term_occurrences"] == 586
        and validation["ibm_state_review_source_terms_mapped"] == 101
        and validation["ibm_state_review_canonical_entity_addition_count"] == 21
        and validation["ibm_state_review_canonical_entity_additions_all_present"]
        and validation["ibm_state_review_canonical_entity_additions_all_source_attributed"]
        and validation["baseline_grid_unchanged"]
        and validation["baseline_candidate_unchanged"]
        and validation["crosswalk_mapping_rate"] >= 0.90
        and validation["ima_parser_species_rows"] >= 6_000
    )

    ontology.to_csv(ONTOLOGY_PATH, index=False, quoting=csv.QUOTE_MINIMAL)
    crosswalk.to_csv(CROSSWALK_PATH, index=False, quoting=csv.QUOTE_MINIMAL)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    release_validation_path = OUT / "validation_report.json"
    release_validation = json.loads(release_validation_path.read_text(encoding="utf-8"))
    release_validation["development_release_version"] = "v1.0-alpha.23"
    release_validation["material_ontology_v1"] = {
        "ontology_rows": validation["ontology_rows"],
        "ima_verified_species": validation["ima_verified_species"],
        "iupac_element_entities": validation["iupac_element_entities"],
        "crosswalk_rows": validation["crosswalk_rows"],
        "crosswalk_source_terms_mapped": validation["crosswalk_source_terms_mapped"],
        "crosswalk_source_terms_unresolved_or_nonspecific": validation["crosswalk_source_terms_unresolved_or_nonspecific"],
        "crosswalk_mapping_rate": validation["crosswalk_mapping_rate"],
        "ibm_abandoned_mine_source_terms_mapped": validation["ibm_abandoned_mine_source_terms_mapped"],
        "ibm_mineral_concession_2024_source_terms": validation["ibm_mineral_concession_2024_source_terms"],
        "ibm_auctioned_concession_2023_24_source_terms": validation["ibm_auctioned_concession_2023_24_source_terms"],
        "ibm_state_review_source_terms": validation["ibm_state_review_source_terms"],
        "ibm_state_review_source_term_occurrences": validation["ibm_state_review_source_term_occurrences"],
        "ibm_state_review_source_terms_mapped": validation["ibm_state_review_source_terms_mapped"],
        "ibm_state_review_canonical_entity_addition_count": validation["ibm_state_review_canonical_entity_addition_count"],
        "baseline_grid_unchanged": validation["baseline_grid_unchanged"],
        "baseline_candidate_unchanged": validation["baseline_candidate_unchanged"],
        "legacy_model_targets_unchanged": validation["legacy_model_targets"],
        "checks_pass": validation["checks_pass"],
    }
    release_validation_path.write_text(
        json.dumps(release_validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    source_registry = pd.read_csv(OUT / "source_registry.csv", keep_default_na=False)
    base = pd.DataFrame(SOURCE_REGISTRY)
    source_registry = source_registry.loc[~source_registry["source_id"].isin(base["source_id"])].copy()
    pd.concat([base, source_registry], ignore_index=True).to_csv(OUT / "source_registry.csv", index=False)

    dictionary_path = OUT / "data_dictionary.csv"
    dictionary = pd.read_csv(dictionary_path, keep_default_na=False)
    dictionary = dictionary.loc[~dictionary["table"].isin([ONTOLOGY_PATH.name, CROSSWALK_PATH.name])].copy()
    definitions = []
    for table_name, frame in [(ONTOLOGY_PATH.name, ontology), (CROSSWALK_PATH.name, crosswalk)]:
        for column in frame.columns:
            definitions.append({
                "table": table_name,
                "column": column,
                "definition": {
                    "material_id": "Stable, type-prefixed KHANAN ontology identifier.",
                    "mapping_status": "Whether a source term maps to one or more controlled ontology entities.",
                    "authority_status": "Authority/classification basis for the entity identity.",
                    "source_term_occurrences": "Number of rows or records in the named source carrying the source term.",
                    "ibm_imyb_state_review_occurrences_source_term_occurrences": "Number of IBM 2024 State Review occurrence-geography rows whose published material term maps to the entity.",
                }.get(column, column.replace("_", " ").capitalize() + "."),
                "data_type": str(frame[column].dtype),
                "unit": "JSON array" if column.endswith("_json") else None,
                "missing_value_policy": "Blank means not applicable, unavailable, or not yet established; never infer zero unless explicitly stated.",
            })
    pd.concat([dictionary, pd.DataFrame(definitions)], ignore_index=True).to_csv(dictionary_path, index=False)

    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if not validation["checks_pass"]:
        raise SystemExit("material ontology validation failed")


if __name__ == "__main__":
    main()
