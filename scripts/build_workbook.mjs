import fs from "node:fs/promises";
import { createReadStream } from "node:fs";
import readline from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(root, "outputs");
const workbookDiagnosticsDir = path.join(outDir, "diagnostics", "workbook");
const previewDir = path.join(workbookDiagnosticsDir, "previews");
const font = "Arial";
const navy = "#17365D";
const blue = "#1F4E78";
const paleBlue = "#D9EAF7";
const paleGold = "#FFF2CC";

function parseCsvLine(line) {
  const fields = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (quoted) {
      if (character === '"' && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      fields.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  fields.push(value);
  return fields;
}

function isIsoDateHeader(header) {
  return [
    "reference_date", "source_date", "auction_nit_date", "inspection_date", "violation_date", "show_cause_date",
    "earliest_inspection_date", "latest_inspection_date", "source_accessed_date",
    "weather_reference_period_start", "weather_reference_period_end",
  ].includes(header);
}

function coerce(header, value) {
  if (value === "") return null;
  if (value === "True") return true;
  if (value === "False") return false;
  if (isIsoDateHeader(header) && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T00:00:00Z`);
  }
  if (
    /(^|_)(latitude|longitude)$/.test(header)
    || /(_km2|_km|_pct|_m|_ha|_c_rolling_12m|_mm_rolling_12m|_m_s|_days|_score|_percentile|_auc|_records|_rows|_folds|_cells|_rank|_count|_density|_bytes|^std\d+|reserves_total|resources_total|total_resources|unit_scale|arithmetic_|source_pdf_page|source_page_number|source_table_index|source_table_row_number|inspection_event_count|blank_numeric_cells)/.test(header)
    || ["priority_rank", "auction_tranche"].includes(header)
  ) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return value;
}

async function loadCsv(fileName, options = {}) {
  const input = createReadStream(path.join(outDir, fileName), { encoding: "utf8" });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let sourceHeaders = null;
  let selectedHeaders = null;
  let selectedIndexes = null;
  const rows = [];
  for await (const line of lines) {
    if (!sourceHeaders) {
      sourceHeaders = parseCsvLine(line);
      selectedHeaders = options.columns ?? sourceHeaders;
      selectedIndexes = selectedHeaders.map((header) => sourceHeaders.indexOf(header));
      if (selectedIndexes.some((index) => index < 0)) {
        throw new Error(`Missing selected column in ${fileName}`);
      }
      continue;
    }
    const sourceValues = parseCsvLine(line);
    const rowObject = Object.fromEntries(sourceHeaders.map((header, index) => [header, sourceValues[index] ?? ""]));
    if (options.filter && !options.filter(rowObject)) continue;
    rows.push(selectedIndexes.map((index, selectedIndex) => coerce(selectedHeaders[selectedIndex], sourceValues[index] ?? "")));
    if (options.limit && rows.length >= options.limit) break;
  }
  if (options.sort) rows.sort(options.sort);
  return { headers: selectedHeaders, rows };
}

function columnName(index) {
  let result = "";
  let value = index + 1;
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function styleDataSheet(sheet, headers, rowCount, tableName) {
  const lastColumn = columnName(headers.length - 1);
  const lastRow = rowCount + 1;
  const used = sheet.getRange(`A1:${lastColumn}${lastRow}`);
  used.format.font = { name: font, size: 9 };
  used.format.verticalAlignment = "top";
  used.format.rowHeight = 18;
  const header = sheet.getRange(`A1:${lastColumn}1`);
  header.format = {
    fill: navy,
    font: { name: font, size: 9, bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  header.format.rowHeight = 34;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(Math.min(2, headers.length));
  sheet.tables.add(`A1:${lastColumn}${lastRow}`, true, tableName).style = "TableStyleMedium2";
  headers.forEach((headerName, index) => {
    const column = sheet.getRange(`${columnName(index)}1:${columnName(index)}${lastRow}`);
    let width = 15;
    if (/name|title|definition|note|limitation|used_for|source_reference|profile|json|url|boundary|stratigraphy|assessment|promotion_rule/.test(headerName)) width = 28;
    if (/record_id|h3|class|status|material/.test(headerName)) width = Math.max(width, 20);
    if (headerName === "record_id") width = 40;
    if (["record_class", "mine_identity_method"].includes(headerName)) width = 32;
    if (["geography_name_source", "grade_or_measure_source", "resource_basis", "spatial_integration_status"].includes(headerName)) width = 26;
    column.format.columnWidth = width;
    if (/json|note|limitation|definition|used_for|source_reference|profile|url|assessment|promotion_rule/.test(headerName) || ["record_class", "mine_identity_method"].includes(headerName)) {
      column.format.wrapText = true;
    }
    if (/latitude|longitude|score|percentile|auc|recall|_km$|_km2$/.test(headerName) && rowCount > 0) {
      sheet.getRange(`${columnName(index)}2:${columnName(index)}${lastRow}`).format.numberFormat = "0.0000";
    }
    if (isIsoDateHeader(headerName) && rowCount > 0) {
      sheet.getRange(`${columnName(index)}2:${columnName(index)}${lastRow}`).format.numberFormat = "yyyy-mm-dd";
      column.format.columnWidth = 14;
    }
  });
  for (const metric of ["prospectivity_score_max", "top_material_percentile", "top_material_spatial_cv_auc", "spatial_holdout_pseudoabsence_roc_auc"]) {
    const index = headers.indexOf(metric);
    if (index >= 0 && rowCount > 0) {
      sheet.getRange(`${columnName(index)}2:${columnName(index)}${lastRow}`).conditionalFormats.add("colorScale", {
        colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"],
        thresholds: ["min", { type: "percentile", value: 50 }, "max"],
      });
    }
  }
}

function addDataSheet(workbook, name, data, tableName, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.getRange("A1").write([data.headers, ...data.rows]);
  styleDataSheet(sheet, data.headers, data.rows.length, tableName);
  if (options.bodyRowHeight && data.rows.length > 0) {
    const lastColumn = columnName(data.headers.length - 1);
    sheet.getRange(`A2:${lastColumn}${data.rows.length + 1}`).format.rowHeight = options.bodyRowHeight;
  }
  return sheet;
}

const candidateColumns = [
  "record_id", "record_class", "candidate_rank_national", "state_or_ut_2011", "district_2011", "latitude", "longitude", "h3_r6",
  "top_material", "top_material_chemical_names_json", "top_material_symbols_or_formulae_json", "prospectivity_score_max",
  "top_material_percentile", "top_material_nearest_known_km", "top_material_known_evidence_records", "top_material_spatial_cv_auc",
  "top_material_spatial_cv_recall_at_background_top5pct", "model_validation_tier", "geology_age", "geology_group", "geology_stratigraphy",
  "elevation_m", "terrain_class", "weather_reference_period_start", "weather_reference_period_end",
  "temperature_mean_c_rolling_12m", "precipitation_total_mm_rolling_12m", "weather_data_completeness_pct_rolling_12m", "population_estimate_2020_grid",
  "census_population_2011_district", "data_quality_flags_json",
];
const knownColumns = [
  "record_id", "record_class", "site_name", "development_status", "operation_type", "deposit_type", "production_size", "latitude", "longitude",
  "state_or_ut_2011", "district_2011", "source_materials_json", "priority_materials_json", "chemical_names_json", "symbols_or_formulae_json",
  "ore_minerals_source", "host_rock_unit_source", "host_rock_type_source", "deposit_model_source", "geology_age", "geology_group",
  "weather_reference_period_start", "weather_reference_period_end", "temperature_mean_c_rolling_12m",
  "precipitation_total_mm_rolling_12m", "weather_data_completeness_pct_rolling_12m", "population_estimate_2020_grid", "census_population_2011_district",
  "source_record_id", "source_quality_code", "data_quality_flags_json",
];
const nmiColumns = [
  "record_id", "source_table_number", "source_pdf_page", "reference_date", "mineral_name_source",
  "normalized_top50_materials_json", "scope_type", "state_or_ut", "geography_name_source",
  "grade_or_measure_source", "resource_basis", "unit_source", "unit_scale_to_base", "base_unit",
  "std111_proved", "std121_probable", "std122_probable", "reserves_total_a", "std211_feasibility",
  "std221_prefeasibility", "std222_prefeasibility", "std331_measured", "std332_indicated",
  "std333_inferred", "std334_reconnaissance", "remaining_resources_total_b", "total_resources_a_plus_b",
  "total_resources_base_quantity", "blank_numeric_cells_interpreted_as_zero", "arithmetic_validation_pass",
  "coordinates_available_in_source", "spatial_integration_status", "source_url",
];
const mcdrLatestColumns = [
  "record_id", "record_class", "mine_identity_method", "inspection_event_count", "earliest_inspection_date", "latest_inspection_date",
  "fiscal_years_present_json", "ibm_regional_office", "state_or_ut", "district", "mine_name", "mine_code", "mineral_source",
  "normalized_top50_materials_json", "chemical_names_json", "symbols_or_formulae_json", "owner_or_lessee", "lease_area_ha",
  "inspection_type", "inspection_date_within_fiscal_year", "all_linked_document_urls_json", "coordinates_available_in_summary_source",
  "spatial_model_integration_status", "source_url",
];
const mcdrEventColumns = [
  "record_id", "fiscal_year", "ibm_regional_office", "source_page_number", "source_table_row_number", "source_serial_number",
  "inspection_date", "inspection_date_source", "inspection_date_within_fiscal_year", "state_or_ut", "district", "mine_name", "mine_code",
  "mineral_source", "normalized_top50_materials_json", "chemical_names_json", "symbols_or_formulae_json", "owner_or_lessee",
  "lease_area_ha", "inspection_type", "inspecting_officer", "violation_date", "show_cause_date",
  "violation_or_show_cause_source", "all_linked_document_urls_json", "source_url",
];

const [candidates, known, mcdrLatest, mcdrEvents, official, mbsManifest, nmi, materials, validation, sources, dictionary] = await Promise.all([
  loadCsv("india_mining_prospectivity_grid_h3_r6.csv", {
    columns: candidateColumns,
    filter: (row) => row.record_class === "high_priority_candidate" || row.record_class === "priority_candidate",
    sort: (a, b) => Number(a[2]) - Number(b[2]),
  }),
  loadCsv("india_known_mining_sites.csv", { columns: knownColumns }),
  loadCsv("india_ibm_mcdr_latest_inspected_mines.csv", { columns: mcdrLatestColumns }),
  loadCsv("india_ibm_mcdr_inspection_events_2023_2026.csv", { columns: mcdrEventColumns }),
  loadCsv("india_official_critical_mineral_blocks.csv"),
  loadCsv("india_official_critical_mineral_mbs_manifest.csv"),
  loadCsv("india_ibm_nmi_2025_resource_inventory.csv", { columns: nmiColumns }),
  loadCsv("india_strategic_materials_top50.csv"),
  loadCsv("material_model_validation.csv"),
  loadCsv("source_registry.csv"),
  loadCsv("data_dictionary.csv"),
]);

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const candidateSheet = addDataSheet(workbook, "Top Candidates", candidates, "CandidateTable");
addDataSheet(workbook, "Known Sites", known, "KnownSitesTable");
addDataSheet(workbook, "MCDR Mines", mcdrLatest, "McdrMinesTable", { bodyRowHeight: 26 });
addDataSheet(workbook, "MCDR Events", mcdrEvents, "McdrEventsTable");
addDataSheet(workbook, "Official Blocks", official, "OfficialBlocksTable", { bodyRowHeight: 28 });
addDataSheet(workbook, "MBS Manifest", mbsManifest, "MbsManifestTable", { bodyRowHeight: 28 });
addDataSheet(workbook, "NMI 2025", nmi, "Nmi2025Table");
addDataSheet(workbook, "Materials", materials, "MaterialsTable", { bodyRowHeight: 30 });
addDataSheet(workbook, "Model Validation", validation, "ValidationTable", { bodyRowHeight: 34 });
const sourcesSheet = addDataSheet(workbook, "Sources", sources, "SourcesTable", { bodyRowHeight: 54 });
const dictionarySheet = addDataSheet(workbook, "Dictionary", dictionary, "DictionaryTable", { bodyRowHeight: 34 });
for (const [column, width] of Object.entries({ A: 34, B: 30, C: 44, D: 24, E: 42, F: 42, G: 42, H: 42, I: 42 })) {
  sourcesSheet.getRange(`${column}1:${column}${sources.rows.length + 1}`).format.columnWidth = width;
}
for (const [column, width] of Object.entries({ A: 46, B: 42, C: 48, D: 18, E: 18, F: 52 })) {
  dictionarySheet.getRange(`${column}1:${column}${dictionary.rows.length + 1}`).format.columnWidth = width;
}
const readme = workbook.worksheets.add("Read Me");

summary.showGridLines = false;
summary.freezePanes.freezeRows(3);
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["India Mining & Mineral Prospectivity — Research Baseline v0.6"]];
summary.getRange("A1:H1").format = {
  fill: navy,
  font: { name: font, size: 18, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
};
summary.getRange("A1:H1").format.rowHeight = 34;
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["Screening indices are not discoveries, resources, reserves, grades, or drilling targets. Field validation is required."]];
summary.getRange("A2:H2").format = { fill: paleGold, font: { name: font, size: 10, bold: true, color: "#7F6000" }, wrapText: true };
summary.getRange("A4:B17").values = [
  ["Release metric", "Value"],
  ["Known georeferenced source sites", null],
  ["IBM MCDR inspection events", null],
  ["IBM MCDR latest-inspected-mine rows", null],
  ["IBM NMI 2025 inventory rows", null],
  ["IBM NMI 2025 state/UT rows", null],
  ["Validation-gated candidate cells", null],
  ["High-priority candidate cells", null],
  ["Spatially validated material models", null],
  ["Strategic material taxonomy rows", null],
  ["Official auction event rows", null],
  ["Official auction offer rows", null],
  ["Successful auction result rows", null],
  ["Auction rows with block geometry", null],
];
summary.getRange("B5").formulas = [[`=ROWS('Known Sites'!A2:A${known.rows.length + 1})`]];
summary.getRange("B6").formulas = [[`=ROWS('MCDR Events'!A2:A${mcdrEvents.rows.length + 1})`]];
summary.getRange("B7").formulas = [[`=ROWS('MCDR Mines'!A2:A${mcdrLatest.rows.length + 1})`]];
summary.getRange("B8").formulas = [[`=ROWS('NMI 2025'!A2:A${nmi.rows.length + 1})`]];
summary.getRange("B9").formulas = [[`=COUNTIF('NMI 2025'!G2:G${nmi.rows.length + 1},"state")`]];
summary.getRange("B10").formulas = [[`=ROWS('Top Candidates'!A2:A${candidates.rows.length + 1})`]];
summary.getRange("B11").formulas = [[`=COUNTIF('Top Candidates'!B2:B${candidates.rows.length + 1},"high_priority_candidate")`]];
summary.getRange("B12").formulas = [[`=COUNTIF('Model Validation'!C2:C${validation.rows.length + 1},">0")`]];
summary.getRange("B13").formulas = [[`=ROWS(Materials!A2:A${materials.rows.length + 1})`]];
summary.getRange("B14").formulas = [[`=ROWS('Official Blocks'!A2:A${official.rows.length + 1})`]];
summary.getRange("B15").formulas = [[`=COUNTIF('Official Blocks'!D2:D${official.rows.length + 1},"auction_offer")`]];
summary.getRange("B16").formulas = [[`=COUNTIF('Official Blocks'!D2:D${official.rows.length + 1},"successful_result")`]];
summary.getRange("B17").formulas = [[`=COUNTA('Official Blocks'!O2:O${official.rows.length + 1})`]];
summary.tables.add("A4:B17", true, "ReleaseMetricsTable").style = "TableStyleMedium2";
summary.getRange("A4:B17").format.font = { name: font, size: 10 };
summary.getRange("A4:B4").format = { fill: blue, font: { name: font, size: 10, bold: true, color: "#FFFFFF" } };
summary.getRange("A4:A17").format.columnWidth = 38;
summary.getRange("B4:B17").format.columnWidth = 16;
summary.getRange("D4:E4").values = [["Candidate material", "Cells"]];
const materialIndex = candidateColumns.indexOf("top_material");
const counts = new Map();
for (const row of candidates.rows) counts.set(row[materialIndex], (counts.get(row[materialIndex]) ?? 0) + 1);
const countRows = [...counts.entries()].sort((a, b) => b[1] - a[1]);
summary.getRange("D5").write(countRows);
const countLastRow = 4 + countRows.length;
summary.tables.add(`D4:E${countLastRow}`, true, "CandidateCountsTable").style = "TableStyleMedium2";
summary.getRange(`D4:E${countLastRow}`).format.font = { name: font, size: 9 };
summary.getRange("D4:E4").format = { fill: blue, font: { name: font, size: 9, bold: true, color: "#FFFFFF" } };
summary.getRange(`D4:D${countLastRow}`).format.columnWidth = 22;
summary.getRange(`E4:E${countLastRow}`).format.columnWidth = 12;
const chart = summary.charts.add("bar", summary.getRange(`D4:E${countLastRow}`));
chart.title = "Validation-gated candidate cells by top material";
chart.titleTextStyle.typeface = font;
chart.titleTextStyle.fontSize = 12;
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis", textStyle: { typeface: font, fontSize: 9 } };
chart.yAxis = { numberFormatCode: "#,##0", numberFormatSourceLinked: false, textStyle: { typeface: font, fontSize: 9 } };
chart.setPosition("G4", "N23");
summary.getRange("A20:E25").values = [
  ["Release interpretation", null, null, null, null],
  ["Known evidence area", "Within 5 km of a mapped source record; not an undiscovered candidate.", null, null, null],
  ["Priority candidate", "Passes minimum spatial holdout, evidence, distance, percentile, and score gates.", null, null, null],
  ["High-priority candidate", "Also passes stronger holdout AUC/recall and percentile gates.", null, null, null],
  ["Regional background", "Did not pass release gates; this does not mean barren.", null, null, null],
  ["Canonical data", "The full 88,857-row CSV contains all nationwide grid fields. This workbook is a review companion.", null, null, null],
];
summary.getRange("A20:E20").merge();
for (let row = 21; row <= 25; row += 1) summary.getRange(`B${row}:E${row}`).merge();
summary.getRange("A20:E25").format = { font: { name: font, size: 10 }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A20:E20").format = { fill: paleBlue, font: { name: font, size: 11, bold: true, color: navy } };
summary.getRange("A21:A25").format.font = { name: font, size: 10, bold: true, color: navy };
summary.getRange("A20:A25").format.columnWidth = 25;
summary.getRange("B20:E25").format.columnWidth = 18;

readme.showGridLines = false;
readme.getRange("A1:F1").merge();
readme.getRange("A1").values = [["How to use this workbook"]];
readme.getRange("A1:F1").format = { fill: navy, font: { name: font, size: 16, bold: true, color: "#FFFFFF" } };
readme.getRange("A3:F13").values = [
  ["1", "Canonical release", "The large india_mining_prospectivity_grid_h3_r6.csv is authoritative for the complete grid; Top Candidates is a filtered review view.", null, null, null],
  ["2", "Location", "Candidate latitude/longitude is the H3 cell centroid, not a drill target. Use h3_r6 and the canonical CSV's cell_boundary_wkt.", null, null, null],
  ["3", "Meaning", "Candidate scores are reconnaissance indices, never discovery probabilities, reserves, resources, grades, or evidence of legal/access feasibility.", null, null, null],
  ["4", "Multiple materials", "JSON arrays retain all normalized materials and chemical names/symbols where available; English source names remain preserved.", null, null, null],
  ["5", "MCDR inspections", "MCDR rows are inspection-table records, not a complete working-mine register or proof of production/compliance. Blank coordinates are intentional.", null, null, null],
  ["6", "NMI resources", "IBM NMI 2025 rows are national/state/grade aggregates. Blank coordinates are intentional; never spread state totals across cells or treat them as deposits.", null, null, null],
  ["7", "Official auctions", "Rows preserve dated offer/result events, not legal grant or production status. All 143 offer rows include source-published footprints and document provenance; the MBS Manifest exposes extraction checks. Auction rows remain excluded from model evidence.", null, null, null],
  ["8", "Population", "WorldPop 2020 is a modeled cell estimate. Census demographic fields are 2011 district context, not cell-level counts.", null, null, null],
  ["9", "Weather", "NASA POWER daily UTC values cover 2025-09-01 through 2026-08-31. Completeness is 365/365 days at every native grid point; recent near-real-time values may later be revised by NASA.", null, null, null],
  ["10", "Validation", "Read Model Validation before using any material. Background samples are not confirmed barren, so AUC is not economic-discovery accuracy.", null, null, null],
  ["11", "Sources", "Review Sources for provenance, access/license notes, and dataset-specific limitations before redistribution.", null, null, null],
];
readme.getRange("A3:F13").format = { font: { name: font, size: 10 }, wrapText: true, verticalAlignment: "top" };
readme.getRange("A3:A13").format = { fill: paleBlue, font: { name: font, size: 11, bold: true, color: navy }, horizontalAlignment: "center" };
readme.getRange("B3:B13").format.font = { name: font, size: 10, bold: true, color: navy };
readme.getRange("A3:A13").format.columnWidth = 6;
readme.getRange("B3:B13").format.columnWidth = 22;
for (let row = 3; row <= 13; row += 1) readme.getRange(`C${row}:F${row}`).merge();
readme.getRange("C3:F13").format.columnWidth = 24;
readme.getRange("A3:F13").format.rowHeight = 40;

workbook.recalculate();
await fs.mkdir(previewDir, { recursive: true });
const previewRanges = {
  "Summary": "A1:N25",
  "Top Candidates": `A1:L${Math.min(candidates.rows.length + 1, 25)}`,
  "Known Sites": `A1:L${Math.min(known.rows.length + 1, 25)}`,
  "MCDR Mines": `A1:L${Math.min(mcdrLatest.rows.length + 1, 25)}`,
  "MCDR Events": `A1:L${Math.min(mcdrEvents.rows.length + 1, 25)}`,
  "Official Blocks": `A1:L${Math.min(official.rows.length + 1, 25)}`,
  "MBS Manifest": `A1:R${Math.min(mbsManifest.rows.length + 1, 25)}`,
  "NMI 2025": `A1:N${Math.min(nmi.rows.length + 1, 25)}`,
  "Materials": `A1:H${Math.min(materials.rows.length + 1, 25)}`,
  "Model Validation": `A1:G${Math.min(validation.rows.length + 1, 25)}`,
  "Sources": `A1:I${Math.min(sources.rows.length + 1, 25)}`,
  "Dictionary": `A1:F${Math.min(dictionary.rows.length + 1, 25)}`,
  "Read Me": "A1:F13",
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const preview = await workbook.render({ sheetName, range, scale: 0.8, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const inspection = await workbook.inspect({
  kind: "workbook,sheet,table,formula",
  maxChars: 12000,
  tableMaxRows: 4,
  tableMaxCols: 6,
  options: { maxResults: 100 },
});
await fs.writeFile(path.join(workbookDiagnosticsDir, "workbook_inspection.txt"), inspection.ndjson ?? String(inspection));
const weatherInspection = await workbook.inspect({
  kind: "table",
  range: "Top Candidates!X1:AB4",
  include: "values,formulas",
  tableMaxRows: 4,
  tableMaxCols: 5,
  maxChars: 4000,
});
await fs.writeFile(path.join(workbookDiagnosticsDir, "workbook_weather_inspection.txt"), weatherInspection.ndjson ?? String(weatherInspection));
const officialInspection = await workbook.inspect({
  kind: "table",
  range: "Official Blocks!A1:W5",
  include: "values,formulas",
  tableMaxRows: 5,
  tableMaxCols: 23,
  maxChars: 8000,
});
await fs.writeFile(path.join(workbookDiagnosticsDir, "workbook_official_blocks_inspection.txt"), officialInspection.ndjson ?? String(officialInspection));
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
await fs.writeFile(path.join(workbookDiagnosticsDir, "workbook_error.log"), errors.ndjson ?? String(errors));
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(outDir, "india_mining_dataset_companion.xlsx"));
console.log(JSON.stringify({
  output: path.join(outDir, "india_mining_dataset_companion.xlsx"),
  sheets: Object.keys(previewRanges),
  candidateRows: candidates.rows.length,
  knownRows: known.rows.length,
  mcdrLatestMineRows: mcdrLatest.rows.length,
  mcdrEventRows: mcdrEvents.rows.length,
  officialBlockRows: official.rows.length,
  mbsManifestRows: mbsManifest.rows.length,
  nmiRows: nmi.rows.length,
}, null, 2));
