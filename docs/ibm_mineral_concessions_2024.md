# IBM 2024 mineral-concession context

**Development release:** `v1.0-alpha.8`

**Source:** Indian Bureau of Mines, *Indian Minerals Yearbook 2024*, chapter “Status of Mineral Concession in India”

**Model status:** context only; excluded from training, validation labels, scoring and candidate promotion

## What this layer adds

KHANAN transcribes and normalizes five official IBM tables:

- Table 1: state/UT mining-lease counts and areas as at 31 March 2022, 2023 and provisional 2024;
- Table 2: provisional 2024 mining-lease counts and areas for 37 mineral categories;
- Table 3: provisional 2024 public/private sector distribution;
- Table 4: provisional 2024 lease-count and lease-area bands; and
- Table 5: 97 mining leases or composite licences that IBM describes as granted through auction during 2023–24.

The source reports 2,995 mining leases in force on 31 March 2024 across 21 states and two Union Territories, covering 293,811.5373 hectares. It explicitly excludes atomic minerals, coal, lignite, petroleum, natural gas and minor minerals. These exclusions mean the totals are not a count or area for every form of mining in India.

The normalized outputs are:

- `outputs/india_ibm_mining_lease_distribution_2024.csv` — 123 long-form aggregate rows: 72 state/year rows, 38 mineral rows including the source total, three sector rows and ten area-band rows; and
- `outputs/india_ibm_auctioned_mineral_concessions_2023_24.csv` — all 97 Table 5 block-name records.

Every row carries the source URL, physical and printed PDF page, pinned PDF SHA-256, access date, exact source labels, normalized material arrays, model-use status and quality flags. Chemical names are emitted when the linked ontology supports them; otherwise the English material name is retained in the JSON array.

## Extraction and verification

The builder pins the 686-page PDF to SHA-256 `5b3208e019f95f8976bdb1e7dd7e7dcebba41af78e149ba162a97c98cc070ded`. Tables 1–5 were visually checked against physical PDF pages 38–43 (printed chapter pages 23–28). The transcription is deterministic and validated against source totals, serial continuity and missing-value counts.

Checks include:

- 2,995 leases and 293,811.5373 hectares in the Table 1 provisional India total;
- 37 non-total mineral categories whose counts sum to 2,995;
- public/private counts and areas that reconcile to the Table 1 total;
- area-band counts that sum to 2,995 and areas that reconcile within printed rounding;
- Table 5 serials contiguous from 1 through 97;
- 45 mining leases and 52 composite licences;
- 92 reported block areas and five explicit `N.A.` values; and
- zero coordinates, zero geometries and zero records admitted to model evidence.

IBM prints `n` in the Himachal Pradesh 2024 lease-count cell. The other state values imply a residual of 39, and the accompanying narrative also says 39, but KHANAN does not silently replace the table cell. It preserves `lease_count_source="n"`, leaves numeric `lease_count` blank and records the residual only in validation metadata.

Source spelling is likewise preserved. Examples include `Maharshtra`, `Sillamanite`, and several Rajasthan block labels that say `District Nagpur` where nearby rows say Nagaur. Separate normalized fields or quality flags expose these cases without rewriting the evidence.

## Material identity policy

All 37 Table 2 mineral categories have controlled ontology links. Transparent gem or spelling normalization includes amethyst to quartz, iolite to cordierite, selenite to gypsum, fluorspar to fluorite, and the printed `Sillamanite` to sillimanite. Broad material categories remain groups, rocks or ores rather than being misrepresented as pure compounds.

Ninety-two of the 97 auction rows have controlled material links. The remaining five use only `Basemetal` or `Basemetal& Associated Minerals`; KHANAN preserves those English labels but assigns no specific element because the source does not say which base metals are present.

## Interpretation limits

The Table 5 title is preserved as a published status statement, while each row sets `current_legal_or_operational_status_verified=false`. The chapter does not supply a controlling current grant order, lessee/bidder, coordinates, footprint, production, grade, tonnage, reserves/resources, clearances or operating status.

Block names are not geocoded. Guessing a coordinate from a village or district name would create false spatial precision and could leak ambiguous context into model labels. These records can support source discovery, reconciliation and future state-register work, but they cannot presently act as known-deposit points, mine locations or positive training evidence.

Rebuild with:

```bash
.venv/bin/python scripts/build_ibm_mineral_concessions_2024.py
.venv/bin/python scripts/build_material_ontology.py
```
