#!/usr/bin/env python3
"""Extract IBM NMI 2025 mineral/state reserves and resources to audited CSV.

The source is the Indian Bureau of Mines' mineral-wise NMI at a Glance 2025
chapter. Its tables report UNFC categories by mineral, grade/measure, and state
as at 1 April 2025. This script deliberately preserves state/national
granularity and does not invent coordinates or allocate state totals to grid
cells.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
RAW_PDF = ROOT / "sources" / "raw" / "ibm_nmi_2025_chapter5_mineral_wise.pdf"
OUT = ROOT / "outputs"
SOURCE_PAGE = "https://ibm.gov.in/IBMPortal/pages/national-mineral-inventory-at-a-glance-2025"
SOURCE_PDF = "https://ibm.gov.in/writereaddata/files/17848872906a6337fae632bChapter__5_Mineral_wise.pdf"
TABLE_NAME = "india_ibm_nmi_2025_resource_inventory.csv"

NUMERIC_RE = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?$")
HEADER_TOKENS = [
    "STD111", "STD121", "STD122", "(A)", "STD211", "STD221",
    "STD222", "STD331", "STD332", "STD333", "STD334", "(B)", "(A+B)",
]
VALUE_COLUMNS = [
    "std111_proved",
    "std121_probable",
    "std122_probable",
    "reserves_total_a",
    "std211_feasibility",
    "std221_prefeasibility",
    "std222_prefeasibility",
    "std331_measured",
    "std332_indicated",
    "std333_inferred",
    "std334_reconnaissance",
    "remaining_resources_total_b",
    "total_resources_a_plus_b",
]

# Source spellings are retained separately. Aliases only standardize the
# state_or_ut field for joins and filtering.
STATE_ALIASES = {
    "andaman & nicobar islands": "Andaman & Nicobar Islands",
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chandigarh": "Chandigarh",
    "chattisgarh": "Chhattisgarh",
    "chattishgarh": "Chhattisgarh",
    "chhattisgarh": "Chhattisgarh",
    "dadra & nagar haveli": "Dadra & Nagar Haveli",
    "daman & diu": "Daman & Diu",
    "delhi": "Delhi",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jammu & kashmir": "Jammu & Kashmir",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "madhya pradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "puducherry": "Puducherry",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "west bengal": "West Bengal",
}

MEASURE_RE = re.compile(
    r"^(?:ore(?:\s*\([^)]*\))?|metal(?:\s*\([^)]*\))?|lead metal|zinc metal|"
    r"lead\s*&\s*zinc metal|contained\s+.+)$",
    re.IGNORECASE,
)

NMI_TO_TOP50 = {
    "Antimony": ["Antimony"],
    "Apatite": ["Phosphorus"],
    "Bauxite": ["Aluminium"],
    "Borax": ["Boron"],
    "Chromite": ["Chromium"],
    "Cobalt Ore": ["Cobalt"],
    "Copper": ["Copper"],
    "Fluorite": ["Fluorine"],
    "Gold": ["Gold"],
    "Graphite": ["Graphite"],
    "Iron ore (Hematite)": ["Iron"],
    "Iron ore (Magnetite)": ["Iron"],
    "Lead & Zinc Ore": ["Lead", "Zinc"],
    "Limestone": ["Calcium and limestone"],
    "Magnesite": ["Magnesium"],
    "Manganese Ore": ["Manganese"],
    "Marl": ["Calcium and limestone"],
    "Molybdenum": ["Molybdenum"],
    "Nickel Ore": ["Nickel"],
    "Platinum Group of Metals": ["Platinum-group elements"],
    "Potash": ["Potash"],
    "Rare Earth Elements": ["Rare-earth elements"],
    "Rock Phosphate": ["Phosphorus"],
    "Silver": ["Silver"],
    "Tin": ["Tin"],
    "Titanium": ["Titanium"],
    "Tungsten": ["Tungsten"],
    "Vanadium": ["Vanadium"],
    "Zircon": ["Zirconium"],
}

SOURCE_REGISTRY_ROW = {
    "source_id": "SRC_IBM_NMI_2025",
    "publisher": "Indian Bureau of Mines, Ministry of Mines, Government of India",
    "title": "National Mineral Inventory at a Glance 2025, Chapter 5: Mineral-wise reserves and resources",
    "release_or_reference_date": "resources as on 2025-04-01",
    "url": SOURCE_PAGE,
    "download_url": SOURCE_PDF,
    "license_or_access_note": "Government of India publication; retain attribution and verify current IBM website reuse terms.",
    "used_for": "Authoritative 2025 UNFC reserves/resources by mineral, grade or measure, and state/UT.",
    "limitations": "National/state aggregates are not deposit locations; the source chapter provides no coordinates or polygons and figures are rounded.",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\\", "")).strip()


def normalize_state(value: str) -> str | None:
    return STATE_ALIASES.get(normalize_text(value).casefold())


def group_words(words: list[dict], tolerance: float = 4.2) -> list[tuple[float, list[dict]]]:
    groups: list[list] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if not groups or abs(word["top"] - groups[-1][0]) > tolerance:
            groups.append([word["top"], [word]])
        else:
            groups[-1][1].append(word)
    return [(float(top), values) for top, values in groups]


def numeric_column_right_edges(page, words: list[dict]) -> tuple[float, list[float]]:
    first_header = next((word for word in words if word["text"] == "STD111"), None)
    if first_header is None:
        raise ValueError("numeric table header not found")
    header_top = float(first_header["top"])
    header_center = (first_header["x0"] + first_header["x1"]) / 2
    candidate_edges = sorted(
        float(word["x1"])
        for word in words
        if header_top + 5 < word["top"] < page.height - 35
        and word["x1"] > header_center - 25
        and NUMERIC_RE.fullmatch(word["text"].replace(",", ""))
    )
    clusters: list[list[float]] = []
    for edge in candidate_edges:
        if not clusters or edge - clusters[-1][-1] > 10:
            clusters.append([edge])
        else:
            clusters[-1].append(edge)
    clusters = [cluster for cluster in clusters if len(cluster) > 1]
    if len(clusters) != 13:
        summary = [(round(statistics.mean(cluster), 2), len(cluster)) for cluster in clusters]
        raise ValueError(f"expected 13 numeric columns; found {len(clusters)}: {summary}")
    return header_top, [float(statistics.median(cluster)) for cluster in clusters]


def unit_metadata(unit_source: str) -> tuple[float | None, str | None]:
    key = unit_source.casefold().replace("'", "").strip()
    if "million tonne" in key:
        return 1_000_000.0, "tonnes"
    if "000 tonne" in key:
        return 1_000.0, "tonnes"
    if "tonne" in key:
        return 1.0, "tonnes"
    if "kilogram" in key:
        return 1.0, "kilograms"
    if "carat" in key:
        return 1.0, "carats"
    return None, None


def resource_basis(label: str) -> str:
    lowered = label.casefold()
    if "contained" in lowered or "metal" in lowered:
        return "contained_metal_or_compound"
    if "ore" in lowered:
        return "ore"
    return "bulk_mineral_or_source_grade"


def arithmetic_errors(values: list[float]) -> tuple[list[float], float, bool]:
    errors = [
        abs(values[3] - sum(values[0:3])),
        abs(values[11] - sum(values[4:11])),
        abs(values[12] - (values[3] + values[11])),
    ]
    tolerance = max(2.0, abs(values[12]) * 0.00002)
    return errors, tolerance, max(errors) <= tolerance


def extract_rows() -> tuple[pd.DataFrame, dict]:
    if not RAW_PDF.exists():
        raise FileNotFoundError(
            f"Missing {RAW_PDF}. Download it from {SOURCE_PDF} before running this builder."
        )
    sha256 = hashlib.sha256(RAW_PDF.read_bytes()).hexdigest()
    reader = PdfReader(str(RAW_PDF))
    rows: list[dict] = []
    table_names: set[str] = set()
    table_numbers: set[str] = set()
    skipped_blank_pages: list[int] = []
    section = "national_total"
    current_state_source: str | None = None
    current_state: str | None = None
    previous_table: str | None = None
    record_counter: Counter[str] = Counter()

    with pdfplumber.open(str(RAW_PDF)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_number = page_index + 1
            page_text = (reader.pages[page_index].extract_text() or "").replace("\n", " ")
            mineral_match = re.search(
                r"Reserves\s*&\s*Resources\s+of\s+(.+?)\s+as on\s+01\.04\.2025",
                page_text,
                re.IGNORECASE,
            )
            if not mineral_match:
                skipped_blank_pages.append(page_number)
                continue
            mineral = normalize_text(mineral_match.group(1))
            table_match = re.search(r"Table\s+No\.?\s*([0-9.]+)", page_text, re.IGNORECASE)
            unit_match = re.search(r"Unit\s*:\s*(.+?)Reserves\s+Remaining", page_text, re.IGNORECASE)
            if not table_match or not unit_match:
                raise ValueError(f"could not parse table number/unit on PDF page {page_number}")
            table_number = table_match.group(1).rstrip(".")
            unit_source = normalize_text(unit_match.group(1))
            scale_to_base, base_unit = unit_metadata(unit_source)
            table_names.add(mineral)
            table_numbers.add(table_number)

            if mineral != previous_table:
                section = "national_total"
                current_state_source = None
                current_state = None
                previous_table = mineral

            words = page.extract_words(x_tolerance=1, y_tolerance=2, keep_blank_chars=False)
            header_top, right_edges = numeric_column_right_edges(page, words)
            for row_top, row_words in group_words(words):
                if row_top <= header_top + 5:
                    continue
                values: list[float | None] = []
                used_word_ids: set[int] = set()
                for edge in right_edges:
                    matches = [
                        (idx, word)
                        for idx, word in enumerate(row_words)
                        if NUMERIC_RE.fullmatch(word["text"].replace(",", ""))
                        and abs(word["x1"] - edge) < 12
                    ]
                    if matches:
                        idx, word = min(matches, key=lambda item: abs(item[1]["x1"] - edge))
                        used_word_ids.add(idx)
                        values.append(float(word["text"].replace(",", "")))
                    else:
                        values.append(None)

                label = normalize_text(
                    " ".join(
                        word["text"]
                        for idx, word in sorted(enumerate(row_words), key=lambda item: item[1]["x0"])
                        if idx not in used_word_ids and word["x1"] < right_edges[0] - 2
                    )
                )
                lowered = label.casefold()
                if lowered.startswith("by grades"):
                    section = "grade"
                    continue
                if lowered.startswith("by states"):
                    section = "state"
                    current_state_source = None
                    current_state = None
                    continue
                if lowered.startswith("figures") or lowered.startswith("figues"):
                    continue
                if lowered.startswith("all india"):
                    section = "national_total"

                source_state = normalize_state(label)
                populated_values = sum(value is not None for value in values)
                if section == "state" and source_state and populated_values < 11:
                    current_state_source = label
                    current_state = source_state
                    continue
                if populated_values < 11:
                    continue

                blank_cells = sum(value is None for value in values)
                numeric_values = [0.0 if value is None else value for value in values]
                errors, tolerance, arithmetic_pass = arithmetic_errors(numeric_values)
                if not arithmetic_pass:
                    raise ValueError(
                        f"subtotal validation failed on page {page_number}, {mineral}, {label}: "
                        f"errors={errors}, tolerance={tolerance}"
                    )

                if lowered.startswith("all india"):
                    scope_type = "national_total"
                    geography_source = "All India"
                    state_or_ut = None
                    grade_or_measure = "Total"
                elif section == "national_total":
                    scope_type = "national_total"
                    geography_source = "All India"
                    state_or_ut = None
                    grade_or_measure = label or "Total"
                elif section == "grade":
                    scope_type = "grade"
                    geography_source = "All India"
                    state_or_ut = None
                    grade_or_measure = label or "Unspecified"
                else:
                    if source_state:
                        current_state_source = label
                        current_state = source_state
                        grade_or_measure = "Total"
                    elif current_state and MEASURE_RE.fullmatch(label):
                        grade_or_measure = label
                    else:
                        raise ValueError(
                            f"unrecognized state or state-level measure on page {page_number}: {label!r}"
                        )
                    scope_type = "state"
                    geography_source = current_state_source
                    state_or_ut = current_state

                # Restore the chemical subscripts that PDF word extraction emits on
                # a neighboring baseline.
                grade_or_measure = re.sub(r"Contained WO\s*$", "Contained WO3", grade_or_measure)
                grade_or_measure = re.sub(r"Contained V\s*O\s*$", "Contained V2O5", grade_or_measure)
                grade_or_measure = re.sub(r"Contained MoS\s*$", "Contained MoS2", grade_or_measure)
                mapped = NMI_TO_TOP50.get(mineral, [])
                base_key = f"{table_number}-{scope_type}-{state_or_ut or 'all-india'}-{grade_or_measure}"
                record_counter[base_key] += 1
                slug = re.sub(r"[^a-z0-9]+", "-", base_key.casefold()).strip("-")
                record_id = f"IBM-NMI2025-{slug}-{record_counter[base_key]:02d}"

                row = {
                    "record_id": record_id,
                    "record_class": "official_nmi_resource_inventory",
                    "source_table_number": table_number,
                    "source_pdf_page": page_number,
                    "reference_date": "2025-04-01",
                    "mineral_name_source": mineral,
                    "normalized_top50_materials_json": json.dumps(mapped, ensure_ascii=False, separators=(",", ":")),
                    "scope_type": scope_type,
                    "state_or_ut": state_or_ut,
                    "geography_name_source": geography_source,
                    "grade_or_measure_source": grade_or_measure,
                    "resource_basis": resource_basis(grade_or_measure),
                    "unit_source": unit_source,
                    "unit_scale_to_base": scale_to_base,
                    "base_unit": base_unit,
                }
                row.update(dict(zip(VALUE_COLUMNS, numeric_values)))
                row.update({
                    "total_resources_base_quantity": (
                        numeric_values[12] * scale_to_base if scale_to_base is not None else None
                    ),
                    "blank_numeric_cells_interpreted_as_zero": blank_cells,
                    "source_figures_rounded": True,
                    "arithmetic_max_abs_error_source_units": max(errors),
                    "arithmetic_tolerance_source_units": tolerance,
                    "arithmetic_validation_pass": arithmetic_pass,
                    "latitude": None,
                    "longitude": None,
                    "coordinates_available_in_source": False,
                    "spatial_integration_status": "inventory_context_only_not_used_as_point_or_grid_model_evidence",
                    "source_id": "SRC_IBM_NMI_2025",
                    "source_url": SOURCE_PAGE,
                    "source_pdf_url": SOURCE_PDF,
                    "source_file_sha256": sha256,
                    "extraction_method": "pdfplumber_position_aware_columns_with_unfc_subtotal_validation",
                })
                rows.append(row)

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("no IBM NMI resource rows extracted")
    if not frame["record_id"].is_unique:
        duplicates = frame.loc[frame["record_id"].duplicated(), "record_id"].tolist()
        raise ValueError(f"duplicate record IDs: {duplicates[:10]}")
    if len(table_names) != 45:
        raise ValueError(f"expected 45 mineral tables, found {len(table_names)}")
    if not frame["arithmetic_validation_pass"].all():
        raise ValueError("one or more source rows failed UNFC subtotal validation")
    state_to_national_checks = 0
    state_to_national_failures = []
    state_rows = frame.loc[frame["scope_type"] == "state"]
    for (mineral, measure), group in state_rows.groupby(["mineral_name_source", "grade_or_measure_source"]):
        national = frame.loc[
            (frame["mineral_name_source"] == mineral)
            & (frame["scope_type"] == "national_total")
            & (frame["grade_or_measure_source"] == measure)
        ]
        if len(national) != 1:
            continue
        state_to_national_checks += 1
        state_sum = group[VALUE_COLUMNS].sum()
        target = national.iloc[0][VALUE_COLUMNS].astype(float)
        differences = (state_sum - target).abs()
        tolerances = (target.abs() * 0.00005).clip(lower=5.0)
        failed = differences > tolerances
        if failed.any():
            state_to_national_failures.append({
                "mineral": mineral,
                "measure": measure,
                "failed_columns": failed.index[failed].tolist(),
            })
    validation = {
        "source_pdf": str(RAW_PDF),
        "source_file_sha256": sha256,
        "pdf_pages": len(reader.pages),
        "blank_or_graphic_only_pages_skipped": skipped_blank_pages,
        "distinct_mineral_tables": len(table_names),
        "distinct_source_table_numbers": len(table_numbers),
        "rows_total": len(frame),
        "rows_by_scope": {str(key): int(value) for key, value in frame["scope_type"].value_counts().items()},
        "state_or_ut_rows": int((frame["scope_type"] == "state").sum()),
        "distinct_normalized_states_or_uts": int(frame["state_or_ut"].nunique()),
        "rows_linked_to_top50_taxonomy": int(frame["normalized_top50_materials_json"].ne("[]").sum()),
        "distinct_nmi_minerals_linked_to_top50_taxonomy": int(
            frame.loc[frame["normalized_top50_materials_json"].ne("[]"), "mineral_name_source"].nunique()
        ),
        "rows_with_blank_cells_interpreted_as_zero": int(
            frame["blank_numeric_cells_interpreted_as_zero"].gt(0).sum()
        ),
        "blank_cells_interpreted_as_zero_total": int(
            frame["blank_numeric_cells_interpreted_as_zero"].sum()
        ),
        "rows_passing_unfc_subtotal_arithmetic": int(frame["arithmetic_validation_pass"].sum()),
        "state_sums_reconciled_to_matching_national_rows": state_to_national_checks,
        "state_to_national_reconciliation_failures": state_to_national_failures,
        "checks_pass": bool(
            len(table_names) == 45
            and len(frame) > 600
            and frame["record_id"].is_unique
            and frame["arithmetic_validation_pass"].all()
            and frame[VALUE_COLUMNS].notna().all().all()
            and not state_to_national_failures
        ),
        "interpretation_guardrail": (
            "These are national/state/grade aggregate inventory quantities, not deposit coordinates, "
            "site-level grades, economic valuations, or evidence that every part of a state is prospective."
        ),
    }
    return frame, validation


def update_source_registry() -> None:
    path = OUT / "source_registry.csv"
    if path.exists():
        frame = pd.read_csv(path, keep_default_na=False)
        frame = frame.loc[frame["source_id"] != SOURCE_REGISTRY_ROW["source_id"]].copy()
        frame = pd.concat([frame, pd.DataFrame([SOURCE_REGISTRY_ROW])], ignore_index=True)
    else:
        frame = pd.DataFrame([SOURCE_REGISTRY_ROW])
    frame.to_csv(path, index=False)


def update_material_taxonomy(inventory: pd.DataFrame) -> None:
    path = OUT / "india_strategic_materials_top50.csv"
    if not path.exists():
        return
    materials = pd.read_csv(path)
    linked = inventory.loc[inventory["normalized_top50_materials_json"].ne("[]")].copy()
    exploded_rows = []
    for row in linked.itertuples(index=False):
        for material in json.loads(row.normalized_top50_materials_json):
            exploded_rows.append({
                "material_name": material,
                "mineral_name_source": row.mineral_name_source,
                "scope_type": row.scope_type,
                "state_or_ut": row.state_or_ut,
            })
    links = pd.DataFrame(exploded_rows)
    summaries = {}
    for material, group in links.groupby("material_name"):
        summaries[material] = {
            "ibm_nmi2025_resource_inventory_available": True,
            "ibm_nmi2025_source_minerals_json": json.dumps(
                sorted(group["mineral_name_source"].unique()), ensure_ascii=False, separators=(",", ":")
            ),
            "ibm_nmi2025_state_or_ut_count": int(group["state_or_ut"].dropna().nunique()),
            "ibm_nmi2025_linked_inventory_rows": int(len(group)),
        }
    for column, default in [
        ("ibm_nmi2025_resource_inventory_available", False),
        ("ibm_nmi2025_source_minerals_json", "[]"),
        ("ibm_nmi2025_state_or_ut_count", 0),
        ("ibm_nmi2025_linked_inventory_rows", 0),
    ]:
        materials[column] = [summaries.get(name, {}).get(column, default) for name in materials["material_name"]]
    materials.to_csv(path, index=False)


def dictionary_definition(column: str) -> tuple[str, str, str | None]:
    exact = {
        "record_id": ("Stable record identifier within the IBM NMI 2025 extract.", "text", None),
        "record_class": ("Official non-georeferenced NMI aggregate inventory record.", "category", None),
        "source_table_number": ("Table number printed by IBM, retained exactly including source numbering anomalies.", "text", None),
        "source_pdf_page": ("One-based PDF page containing the record.", "integer", "page"),
        "reference_date": ("Inventory reference date stated in the table title.", "date", None),
        "mineral_name_source": ("Mineral name printed in the IBM table title.", "text", None),
        "normalized_top50_materials_json": ("JSON array linking the source mineral to this project's top-50 material taxonomy.", "JSON array", None),
        "scope_type": ("National total, source grade/measure, or state/UT record.", "category", None),
        "state_or_ut": ("Normalized state or union-territory name; blank for national/grade rows.", "text", None),
        "geography_name_source": ("Geography wording retained from the source table.", "text", None),
        "grade_or_measure_source": ("Source grade, ore/metal basis, contained compound, or Total.", "text", None),
        "resource_basis": ("Derived basis distinguishing ore, contained metal/compound, and bulk mineral/source grade.", "category", None),
        "unit_source": ("Unit printed on the source table.", "text", None),
        "unit_scale_to_base": ("Multiplier from the source value to base_unit.", "number", "multiplier"),
        "base_unit": ("Normalized base unit for the optional converted total.", "text", None),
        "total_resources_base_quantity": ("Total resources (A+B) multiplied by unit_scale_to_base; not comparable across ore/metal bases.", "number", "base_unit"),
        "blank_numeric_cells_interpreted_as_zero": ("Count of visually blank numeric category cells set to zero only when published subtotals validate that interpretation.", "integer", "cells"),
        "source_figures_rounded": ("True because the source notes that figures are rounded.", "boolean", None),
        "arithmetic_max_abs_error_source_units": ("Maximum absolute difference across A, B, and A+B subtotal checks.", "number", "source units"),
        "arithmetic_tolerance_source_units": ("Scale-aware tolerance used for rounded subtotal validation.", "number", "source units"),
        "arithmetic_validation_pass": ("Whether all published subtotal identities pass within tolerance.", "boolean", None),
        "latitude": ("Blank: the source table does not publish a point location.", "number", "decimal degrees"),
        "longitude": ("Blank: the source table does not publish a point location.", "number", "decimal degrees"),
        "coordinates_available_in_source": ("False for this aggregate chapter.", "boolean", None),
        "spatial_integration_status": ("Guardrail preventing aggregate state totals from being used as point/grid evidence.", "text", None),
        "source_file_sha256": ("SHA-256 checksum of the downloaded source PDF.", "text", None),
        "extraction_method": ("Auditable PDF extraction method identifier.", "text", None),
    }
    if column in exact:
        return exact[column]
    unfc = {
        "std111_proved": "UNFC 111 proved reserves.",
        "std121_probable": "UNFC 121 probable reserves.",
        "std122_probable": "UNFC 122 probable reserves.",
        "reserves_total_a": "Published total reserves (A).",
        "std211_feasibility": "UNFC 211 feasibility resources.",
        "std221_prefeasibility": "UNFC 221 pre-feasibility resources.",
        "std222_prefeasibility": "UNFC 222 pre-feasibility resources.",
        "std331_measured": "UNFC 331 measured resources.",
        "std332_indicated": "UNFC 332 indicated resources.",
        "std333_inferred": "UNFC 333 inferred resources.",
        "std334_reconnaissance": "UNFC 334 reconnaissance resources.",
        "remaining_resources_total_b": "Published total remaining resources (B).",
        "total_resources_a_plus_b": "Published total resources (A+B).",
    }
    if column in unfc:
        return unfc[column], "number", "unit_source"
    if column.endswith("url") or column in {"source_id"}:
        return "Source provenance field.", "text", None
    return column.replace("_", " ").capitalize() + ".", "text or number", None


def update_data_dictionary(inventory: pd.DataFrame) -> None:
    path = OUT / "data_dictionary.csv"
    if path.exists():
        dictionary = pd.read_csv(path, keep_default_na=False)
        dictionary = dictionary.loc[dictionary["table"] != TABLE_NAME].copy()
    else:
        dictionary = pd.DataFrame(columns=["table", "column", "definition", "data_type", "unit", "missing_value_policy"])
    rows = []
    for column in inventory.columns:
        definition, data_type, unit = dictionary_definition(column)
        rows.append({
            "table": TABLE_NAME,
            "column": column,
            "definition": definition,
            "data_type": data_type,
            "unit": unit,
            "missing_value_policy": (
                "Blank means unavailable/not applicable. Numeric category blanks are zero only where "
                "blank_numeric_cells_interpreted_as_zero records an arithmetic-validated interpretation."
            ),
        })
    dictionary = pd.concat([dictionary, pd.DataFrame(rows)], ignore_index=True)
    material_table = "india_strategic_materials_top50.csv"
    material_definitions = {
        "ibm_nmi2025_resource_inventory_available": (
            "Whether at least one IBM NMI 2025 source-mineral table maps to this taxonomy material.",
            "boolean",
            None,
        ),
        "ibm_nmi2025_source_minerals_json": (
            "JSON array of IBM NMI 2025 source-mineral names mapped to this taxonomy material.",
            "JSON array",
            None,
        ),
        "ibm_nmi2025_state_or_ut_count": (
            "Distinct normalized states/UTs represented by linked IBM NMI 2025 rows.",
            "integer",
            "states/UTs",
        ),
        "ibm_nmi2025_linked_inventory_rows": (
            "Count of linked IBM NMI 2025 national, grade/measure, and state/UT rows.",
            "integer",
            "rows",
        ),
    }
    dictionary = dictionary.loc[
        ~(
            dictionary["table"].eq(material_table)
            & dictionary["column"].isin(material_definitions)
        )
    ].copy()
    material_rows = [
        {
            "table": material_table,
            "column": column,
            "definition": definition,
            "data_type": data_type,
            "unit": unit,
            "missing_value_policy": "False, [] or zero means that no IBM NMI 2025 source-mineral table mapped to the taxonomy material.",
        }
        for column, (definition, data_type, unit) in material_definitions.items()
    ]
    dictionary = pd.concat([dictionary, pd.DataFrame(material_rows)], ignore_index=True)
    dictionary.to_csv(path, index=False)


def update_release_validation(nmi_validation: dict) -> None:
    path = OUT / "validation_report.json"
    if path.exists():
        release = json.loads(path.read_text(encoding="utf-8"))
    else:
        release = {}
    prior_pass = bool(release.get("checks_pass", True))
    release.update({
        "ibm_nmi_2025_rows": nmi_validation["rows_total"],
        "ibm_nmi_2025_distinct_mineral_tables": nmi_validation["distinct_mineral_tables"],
        "ibm_nmi_2025_rows_by_scope": nmi_validation["rows_by_scope"],
        "ibm_nmi_2025_rows_linked_to_top50_taxonomy": nmi_validation["rows_linked_to_top50_taxonomy"],
        "ibm_nmi_2025_rows_passing_unfc_subtotal_arithmetic": nmi_validation["rows_passing_unfc_subtotal_arithmetic"],
        "ibm_nmi_2025_guardrail": nmi_validation["interpretation_guardrail"],
        "checks_pass": bool(prior_pass and nmi_validation["checks_pass"]),
    })
    path.write_text(json.dumps(release, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    inventory, validation = extract_rows()
    inventory.to_csv(OUT / TABLE_NAME, index=False, quoting=csv.QUOTE_MINIMAL)
    (OUT / "ibm_nmi_2025_extraction_validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )
    update_source_registry()
    update_material_taxonomy(inventory)
    update_data_dictionary(inventory)
    update_release_validation(validation)
    print(json.dumps(validation, indent=2))
    if not validation["checks_pass"]:
        raise SystemExit("IBM NMI 2025 extraction validation failed")


if __name__ == "__main__":
    main()
