#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = path.join(root, "outputs", "diagnostics", "sentinel2_ablation_csv_artifact_qa");
const targets = [
  {
    file: "material_sentinel2_spatial_ablation.csv",
    expectedRows: 50,
    expectedColumns: 37,
    ranges: ["A15:Q40", "AB15:AK40"],
  },
  {
    file: "material_sentinel2_spatial_ablation_folds.csv",
    expectedRows: 70,
    expectedColumns: 21,
    ranges: ["A24:U32", "A64:U71"],
  },
  {
    file: "data_dictionary.csv",
    expectedRows: 1561,
    expectedColumns: 6,
    ranges: ["A1425:F1443"],
  },
];

function countCsvShape(csvText) {
  let rows = 0;
  let columns = 0;
  let inQuotes = false;
  let firstRowColumns = 1;
  for (let index = 0; index < csvText.length; index += 1) {
    const character = csvText[index];
    if (character === '"') {
      if (inQuotes && csvText[index + 1] === '"') {
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (!inQuotes && character === "," && rows === 0) {
      firstRowColumns += 1;
    } else if (!inQuotes && character === "\n") {
      rows += 1;
      if (rows === 1) columns = firstRowColumns;
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
  const inspections = [];
  const previews = [];
  for (const [rangeIndex, range] of target.ranges.entries()) {
    const inspection = await workbook.inspect({
      kind: "region",
      sheetId: "Data",
      range,
      include: "values,formulas",
      maxChars: 14000,
      tableMaxRows: 30,
      tableMaxCols: 24,
      tableMaxCellChars: 160,
    });
    inspections.push({ range, ndjson: inspection.ndjson });
    const preview = await workbook.render({
      sheetName: "Data",
      range,
      scale: 1.35,
      format: "png",
    });
    const previewPath = path.join(
      outputDir,
      `${path.basename(target.file, ".csv")}-${rangeIndex + 1}.png`
    );
    await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
    previews.push(previewPath);
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 300 },
    summary: `formula error scan for ${target.file}`,
  });
  summary.push({
    file: target.file,
    rows: shape.rows,
    columns: shape.columns,
    inspections,
    formulaErrorScan: errors.ndjson,
    previews,
  });
}

await fs.writeFile(path.join(outputDir, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
console.log(JSON.stringify(summary.map(({ file, rows, columns, previews }) => ({
  file,
  rows,
  columns,
  previews,
})), null, 2));
