#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = path.join(root, "outputs", "diagnostics", "sentinel2_csv_artifact_qa");

const targets = [
  {
    file: "india_sentinel2_surface_context_h3_r6.csv",
    range: "A1:N12",
    expectedRows: 88857,
    expectedColumns: 86,
  },
  {
    file: "india_sentinel2_scene_manifest_2025.csv",
    range: "A1:R12",
    expectedRows: 950,
    expectedColumns: 49,
  },
  {
    file: "source_registry.csv",
    range: "A33:I37",
    expectedRows: 36,
    expectedColumns: 9,
  },
  {
    file: "data_dictionary.csv",
    range: "A1290:F1307",
    expectedRows: 1482,
    expectedColumns: 6,
  },
];

function countCsvShape(csvText) {
  let rows = 0;
  let columns = 0;
  let inQuotes = false;
  let currentColumns = 1;
  for (let index = 0; index < csvText.length; index += 1) {
    const character = csvText[index];
    if (character === '"') {
      if (inQuotes && csvText[index + 1] === '"') {
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (!inQuotes && character === "," && rows === 0) {
      currentColumns += 1;
    } else if (!inQuotes && character === "\n") {
      rows += 1;
      if (rows === 1) columns = currentColumns;
    }
  }
  if (csvText.length && !csvText.endsWith("\n")) rows += 1;
  return { rows: Math.max(rows - 1, 0), columns };
}

await fs.mkdir(outputDir, { recursive: true });
const summary = [];

for (const target of targets) {
  const inputPath = path.join(root, "outputs", target.file);
  const csvText = await fs.readFile(inputPath, "utf8");
  const shape = countCsvShape(csvText);
  if (shape.rows !== target.expectedRows || shape.columns !== target.expectedColumns) {
    throw new Error(`${target.file} shape ${JSON.stringify(shape)} did not match expected ${target.expectedRows}x${target.expectedColumns}`);
  }

  const workbook = await Workbook.fromCSV(csvText, { sheetName: "Data" });
  const region = await workbook.inspect({
    kind: "region",
    sheetId: "Data",
    range: target.range,
    include: "values,formulas",
    maxChars: 12000,
    tableMaxRows: 18,
    tableMaxCols: 18,
    tableMaxCellChars: 140,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 300 },
    summary: `formula error scan for ${target.file}`,
  });
  const preview = await workbook.render({
    sheetName: "Data",
    range: target.range,
    scale: 1.25,
    format: "png",
  });
  const previewPath = path.join(outputDir, `${path.basename(target.file, ".csv")}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

  summary.push({
    file: target.file,
    rows: shape.rows,
    columns: shape.columns,
    inspectedRange: target.range,
    regionInspection: region.ndjson,
    formulaErrorScan: errors.ndjson,
    previewPath,
  });

  // Allow the very large national-grid workbook to be reclaimed before the next import.
  if (global.gc) global.gc();
}

await fs.writeFile(path.join(outputDir, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
console.log(JSON.stringify(summary.map(({ file, rows, columns, inspectedRange, previewPath }) => ({
  file,
  rows,
  columns,
  inspectedRange,
  previewPath,
})), null, 2));
