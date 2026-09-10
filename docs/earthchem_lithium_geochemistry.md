# EarthChem lithium-pegmatite geochemistry

## Scope

KHANAN v1.0-alpha.17 adds the first redistributable, coordinate-bearing analytical geochemistry layer to the public release. It is derived from EarthChem Library dataset ECL 4498, *Analytical data of Li-rich pegmatites and associated leucogranites of the Assam-Meghalaya Gneissic Complex, northeast India*, published by Dutt, Paul, Goswami, Ray and Dash in 2026 ([doi:10.60520/IEDA/114498](https://doi.org/10.60520/IEDA/114498)).

The publisher assigns Creative Commons Attribution 4.0 International (CC-BY-4.0). KHANAN records research use, retains attribution on every row, and verifies the publisher's SHA-1 checksums before extraction.

This is an independent context layer. It does not modify the v0.6 model, train a new model, validate an existing candidate, or establish a discovery.

## Published source

| Item | Value |
|---|---|
| KHANAN source ID | `SRC_EARTHCHEM_ECL_4498_DUTT_2026` |
| DOI | `10.60520/IEDA/114498` |
| License | CC-BY-4.0 |
| Source archive | `all_dataset_4498.zip` |
| Archive publisher SHA-1 | `35918ae2fc602798980bb6b3df914966fc1f0eb4` |
| Bulk workbook | `4498-1_Duttetal_2026_BulkAnalysis.xls` |
| Bulk workbook publisher SHA-1 | `118bc636e3cd7a3b42a109ca4c6985b7a4926f2f` |
| In-situ workbook | `4498-2_Duttetal_2026_InsituAnalysis.xls` |
| In-situ workbook publisher SHA-1 | `30abe32ae1a77e661342e5083abc98446b3918ef` |
| Access date | 2026-09-10 |

The source contains 13 sample IDs at two unique published coordinate pairs:

- Chakrasila Hill: 10 sample IDs at 26.30345° N, 90.37555° E and 258 m source elevation.
- Road section along Bongaigaon: three sample IDs at 26.189967° N, 90.555333° E and 65.54 m source elevation.

The source sample table does not report an IGSN or per-sample lithology. The dataset abstract describes Li-rich pegmatites, barren garnet-bearing pegmatites and two-mica granites, but it does not map those descriptions to individual sample IDs. KHANAN therefore retains the dataset-level statement without assigning a rock class to any sample.

## Output tables

`outputs/india_earthchem_geochemical_samples.csv` contains one row per source sample. It carries the published coordinate and elevation, source location keyword, H3 resolution-6 cell, Census 2011 State/district co-location, grid geology context, key bulk trace-element columns, arrays of represented parameters and ontology identifiers, source hashes, citation and model-exclusion fields.

`outputs/india_earthchem_geochemical_observations.csv` contains one row per source analysis/parameter cell:

| Analysis family | Source analysis rows | Parameters | Long-form rows |
|---|---:|---:|---:|
| Whole-rock bulk | 13 | 51 | 663 |
| In-situ mineral spots | 55 | 12 | 660 |
| **Total** | **68** | — | **1,323** |

All 1,323 source cells are retained so missingness can be audited. The 51 bulk parameters comprise 10 major oxides, 38 trace elements, two isotope ratios and calculated epsilon Nd. The in-situ parameters comprise 11 oxides and fluorine.

The source mineral abbreviations are retained verbatim and accompanied by conservative curated expansions: `Lpd` lepidolite, `Ms` muscovite, `Grt` garnet group, `Kfs` K-feldspar, `Pl` plagioclase, `Chl` chlorite group, `Bt` biotite group and `Ep` epidote. The curated name does not replace the source code. Where the current ontology contains only a parent group, the parent identifier is used; no new ontology entity is invented merely to increase the ontology count.

## Analytical methods

The source reports:

- Major oxides by WD-XRF using a Rigaku ZSX Primus II at the Advanced Center for Material Science, IIT Kanpur, with source-stated accuracy better than 2%.
- Trace elements by ICP-MS using a Thermo Fisher Scientific iCAP Q at the Department of Earth Sciences, IIT Kanpur. The source states accuracy better than 5% for most trace elements and better than 10% for V, Sc, Pb and Cs.
- Sr and Nd isotope ratios by TIMS using an Isoprobe-T at the Physical Research Laboratory, India.
- Epsilon Nd as a calculated field.
- Mineral chemistry by electron microprobe using a JEOL JXA 8530 Plus at the Physical Research Laboratory, India, with source-stated accuracy better than 2%.

Reference-material measurements are serialized with each applicable observation. Method-specific metadata also retains the 359 pg Sr and 405 pg Nd total procedural blanks and the source's TIMS normalization reference values.

## Missing-value and conflict policy

KHANAN never converts a source blank or qualifier to zero:

- Numeric source values become `measurement_status=measured_numeric`.
- `b.d.l.` becomes `below_detection`; the numeric field remains blank because the source does not report a numeric detection limit.
- `NA` becomes `source_na_token_unresolved`. The source note literally says “NA stands for analyzed,” which does not supply a numeric value or a sufficiently clear missing-value meaning.
- A source dash becomes `source_dash` and remains nonnumeric.
- An empty source cell becomes `missing`.

Two source inconsistencies are intentionally visible:

1. The bulk Data sheet assigns method code 4 to both `143Nd/144Nd` and `eNd`, while Primary Analytical Metadata assigns TIMS method code 3 to `143Nd/144Nd` and calculation code 4 to `eNd`. Both codes are retained and every affected isotope-ratio observation carries `source_method_code_conflict`.
2. The in-situ method sheet reports a `1mm` beam diameter. KHANAN retains that exact text and flags it rather than silently changing the unit or magnitude.

## Spatial joining

The published coordinates are assigned to EPSG:4326 for interoperability because the source provides decimal-degree GPS locations but does not state a datum or collection accuracy. Each coordinate is mapped to an H3 resolution-6 cell and joined to the existing KHANAN national grid for Census 2011 administration, regional geology and co-located v0.6 top-five material scores.

This join is deterministic context. The EarthChem samples did not train the v0.6 model, and the co-located rankings must not be interpreted as source confirmation. At Chakrasila Hill the v0.6 top five do not include lithium; at the Bongaigaon road-section cell they also do not include lithium. Because the released model table stores only the top five values, KHANAN does not invent a lithium score for either cell.

## Validation and limitations

`outputs/earthchem_geochemical_validation.json` verifies the archive and workbook checksums, source dimensions, 13 sample IDs, two coordinate sites, 1,323 unique observations, parameter counts, India coordinate bounds, H3 validity, administrative joins, numeric ranges, method-conflict flags and mandatory model exclusions.

The dataset is valuable evidence of measured chemistry at its published sample locations, but it is targeted petrological sampling—not a systematic regional geochemical survey. It cannot establish:

- the continuity, shape, thickness or tonnage of mineralization;
- a mineral resource or reserve;
- mineability, recovery, processing behaviour or economic viability;
- an undiscovered deposit or a new discovery;
- legal access, title, permission to sample, or permission to drill.

The next scientific step is to add spatially broader and independently sampled geochemistry with compatible methods and detection-limit metadata, then test whether it improves out-of-region prospectivity under the existing spatial-leakage gates.

## Reproduction

From the repository root:

```bash
.venv/bin/python scripts/build_earthchem_geochemistry.py --refresh
.venv/bin/python scripts/plot_earthchem_geochemistry.py
```

The build records research use, downloads the CC-BY archive, verifies publisher checksums, converts the two original XLS workbooks in a temporary directory using LibreOffice, parses them without modifying the originals, and regenerates the CSV and validation JSON outputs.
