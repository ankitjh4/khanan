# IBM 2023-24 auction rows: State Mine Block Summary geometry

**Development release:** `v1.0-alpha.14`

**Sources:** Indian Bureau of Mines, *Indian Minerals Yearbook 2024*, Table 5; MSTC State mineral-auction Mine Block Summary portal

**Model status:** context only; excluded from training labels, validation labels, scoring and candidate promotion

## Purpose

IBM Table 5 names 97 mining leases or composite licences described as granted through auction during 2023-24, but it publishes no coordinates. Alpha.14 continues the separate task of locating exact State Mine Block Summaries and admitting a footprint only when the source itself publishes a boundary that survives spatial checks.

The new outputs are:

- `outputs/india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv`: one row for every IBM Table 5 record, including review scope, selected MBS provenance, coordinate-evidence class, technical profile and geometry-admission outcome;
- `outputs/india_ibm_auctioned_concession_geometries_2023_24.csv`: 24 admitted source footprints with technical and environmental context;
- `outputs/india_ibm_auctioned_concession_geometries_2023_24.geojson`: the same 24 footprints as GeoJSON; and
- `outputs/ibm_auction_mbs_geometry_validation.json`: inventory, coverage, gate and output-hash evidence.

## Portal inventory and matching

The builder establishes a session with the MSTC State-auction portal, opens the ten State sections represented in IBM Table 5, discovers each dynamic Mine Block Summary page, and records the visible PDF links. The accessed snapshot contains 1,124 document links:

| State | MBS links |
|---|---:|
| Andhra Pradesh | 20 |
| Chhattisgarh | 102 |
| Gujarat | 92 |
| Jharkhand | 17 |
| Karnataka | 94 |
| Madhya Pradesh | 316 |
| Maharashtra | 117 |
| Rajasthan | 311 |
| Uttar Pradesh | 37 |
| Goa | 18 |

These are link-inventory observations, not 1,124 parsed documents or 1,124 mines. Alpha.14 retains 39 selected PDFs: six Chhattisgarh, six Gujarat, three Jharkhand, six Karnataka, ten Maharashtra, three Uttar Pradesh and five Goa blocks. Record-specific expressions are curated from exact names; the Uttar Pradesh expressions also require the Phase 4 label that corresponds to the IBM reporting period. When a reviewed expression contains several versions, the highest numeric MSTC file identifier is selected and the rule is retained in the match audit. This selects the official second-attempt summaries for Timmanahalli, Basavangudda and Niddodi. Gujarat uses exact normalized title anchors for the Phase IX files because later portal phases contain similarly named but distinct blocks.

Alpha.14 keeps the five Andhra Pradesh rows in reviewed scope. The live MSTC portal announces that events with bid starts before 5 February 2024 remain on the old portal, while later events use the new portal. The current public Andhra MBS index exposes newer 2025-26 tranches but no exact-name MBS for Adakula, Addankivaripalem, Lakshmakapalle North, Lakshmakapalle South or Mincheri RF. Those rows are marked `reviewed_no_current_public_mbs_match` and `withheld_no_public_boundary_document`; absence from the current index is not treated as evidence that a boundary never existed. Dated official-secondary status evidence is published separately in `outputs/india_ibm_auctioned_concession_status_evidence_2023_24.csv`.

The Maharashtra review is tranche-aware. The live State index groups the May 2023 Devalmari-Katepalli, Surjagad 1-4 and 6, South Padve and Kondhala summaries in Phase X, while the November 2023 Minzhari and Savali summaries appear in Phase XI. Older phases contain repeated block names; the audit locks each IBM row to the highest file identifier within its exact contemporaneous title pattern instead of combining phases. The remaining 53 IBM rows are labelled `not_reviewed_in_this_release`.

## Coordinate extraction and visual review

Every coordinate-bearing page used by this release was rendered with Poppler at 150 dpi and visually reviewed against the source table.

- Chhattisgarh tables are transcribed from source-labelled WGS84 DMS rows in published point order.
- Uttar Pradesh tables are transcribed from source-labelled DMS rows in published point order.
- Goa Blocks V, VII and IX use the source-published WGS84 / UTM zone 43N table, parsed by boundary-point identifier and converted from EPSG:32643 to EPSG:4326.
- Goa Block VIII uses its DMS table because the final source UTM northing is internally inconsistent with the source latitude. The missing source identifier `BP6` is retained as a quality flag; points are not renumbered.
- Jharkhand's Chiropat table is not transcribed into geometry because two latitude cells print an `E` hemisphere. The other two reviewed Jharkhand MBS documents publish bounding extents rather than ordered boundary vertices; no rectangle is substituted for a concession footprint.
- Gujarat's Mevasa Block, Kukaras, Nandana, Kodidra and Virpur-Lusari tables label their ordered DMS coordinates as WGS84. Mevasa Block-1 publishes both UTM and geographic coordinates without stating a datum or UTM zone; the geographic values are transcribed, and the missing datum statement remains explicit.
- Nandana is withheld because BP-5 prints `69°18'51.72"E` among points near 69°15-16'E and the IBM and MBS areas also conflict. Kodidra and Virpur-Lusari have valid source-order coordinate tables, but IBM and the exact-title MBS documents publish materially different areas.
- Four Karnataka tables are transcribed from source-labelled DGPS latitude/longitude rows. Their PDFs do not print a datum, so `coordinate_datum_source` says so explicitly even though the released analytical geometry is encoded in EPSG:4326.
- Timmanahalli is withheld because point C prints `13°35'60.00"N`. Kudarka is withheld because its table prints latitude and longitude values but no hemisphere markers. Neither defect is silently repaired.
- Eight Maharashtra summaries publish ordered DMS boundary points. Their PDFs do not state a datum, so the audit preserves that omission while encoding the reviewed analytical coordinates in EPSG:4326. Seven pass the admission gates; Kondhala does not.
- Devalmari-Katepalli publishes only latitude/longitude extents and says that detailed coordinates are in an unincluded cadastral plate. South Padve also publishes only extents. Neither is converted to a rectangle.
- The Surjagad summaries print December temperature up to 42 C and June temperature up to 7 C. South Padve and Savali print annual rainfall as 600 cm and 800 cm. These apparent source anomalies are retained and flagged rather than silently corrected.
- No points are reordered, interpolated or inferred from names, nearby villages, areas or map appearance.

The builder pins each selected PDF by exact URL, MSTC file identifier, SHA-256, byte size and page count.

## Admission gates

A source footprint is published only when all of the following hold:

1. the source-order polygon is valid;
2. its centroid is covered by the stated State in the 2011 district boundary diagnostic;
3. computed WGS84 ellipsoidal area differs from the MBS area by no more than 5%; and
4. when IBM also publishes an area, the IBM and MBS values differ by no more than 5%.

Full-footprint State containment is retained separately because the community-maintained 2011 administrative boundary can differ from current or legal boundaries. It is a diagnostic, not a controlling cadastral test.

Twenty-four footprints pass:

| IBM record | Block | Material | Vertices | Computed area vs MBS |
|---|---|---|---:|---:|
| IBM-IMYB2024-AUCTION-006 | North of Arjunda | Glauconite (Potash) | 10 | 4.179% |
| IBM-IMYB2024-AUCTION-008 | Devri | Limestone | 4 | 0.493% |
| IBM-IMYB2024-AUCTION-010 | Giroud Uprani | Glauconite | 13 | 1.944% |
| IBM-IMYB2024-AUCTION-011 | Tumrisur Garda II | Gold | 4 | 0.072% |
| IBM-IMYB2024-AUCTION-012 | Mevasa Block-1 | Bauxite and laterite | 11 | 0.221% |
| IBM-IMYB2024-AUCTION-013 | Mevasa Block | Bauxite and marl | 15 | 0.074% |
| IBM-IMYB2024-AUCTION-014 | Kukaras block (Private) | Limestone and marl | 46 | 0.554% |
| IBM-IMYB2024-AUCTION-021 | Block No. 04, HRG | Iron ore | 7 | 0.004% |
| IBM-IMYB2024-AUCTION-023 | Jaisinghpura North | Iron ore | 11 | 0.043% |
| IBM-IMYB2024-AUCTION-024 | Basavanagudda | Gold | 5 | 2.611% |
| IBM-IMYB2024-AUCTION-025 | Nidodi Bauxite | Bauxite | 4 | 0.110% |
| IBM-IMYB2024-AUCTION-050 | Surjagad – 1 | Iron ore | 4 | 0.580% |
| IBM-IMYB2024-AUCTION-051 | Surjagad – 2 | Iron ore | 6 | 0.030% |
| IBM-IMYB2024-AUCTION-052 | Surjagad – 3 | Iron ore | 4 | 0.601% |
| IBM-IMYB2024-AUCTION-053 | Surjagad – 4 | Iron ore | 4 | 0.237% |
| IBM-IMYB2024-AUCTION-055 | Surjagad – 6 | Iron ore | 4 | 0.979% |
| IBM-IMYB2024-AUCTION-057 | Minzhari | Copper | 5 | 0.193% |
| IBM-IMYB2024-AUCTION-058 | Savali | Manganese | 4 | 0.259% |
| IBM-IMYB2024-AUCTION-091 | Bharhari | Iron ore | 6 | 0.189% |
| IBM-IMYB2024-AUCTION-092 | Sona Pahari | Gold | 9 | 0.568% |
| IBM-IMYB2024-AUCTION-093 | Block V Advalpale-Thivim | Iron ore | 11 | 0.045% |
| IBM-IMYB2024-AUCTION-095 | Block VII Cudnem | Iron ore | 8 | 0.054% |
| IBM-IMYB2024-AUCTION-096 | Block VIII Thivim-Pirna | Iron ore | 10 | 0.216% |
| IBM-IMYB2024-AUCTION-097 | Block IX Surla-Sonshi | Iron ore | 65 | 2.549% |

Fifteen selected-MBS records are withheld rather than repaired:

- **Saloni:** IBM publishes 600 ha; the exact-name MBS publishes 670 ha.
- **Kareli-Chandi:** the MBS prints malformed latitude seconds (`34.4.00`) for two vertices.
- **Chiropat:** the latitude column prints an `E` hemisphere at points J3 and K.
- **Baraiburu-Tatiba:** the MBS publishes coordinate extents but no ordered boundary vertices.
- **Meralgara-Barabaljori:** the MBS publishes coordinate extents but no ordered boundary vertices.
- **Girar:** IBM publishes 271.18 ha, the Phase 4 MBS publishes 231.175 ha, and the source-order coordinates compute to about 197.73 ha.
- **Goa Block VI Cudnem-Cormolem:** both DMS and UTM tables reconstruct to about 28.8 ha, 25.31% below the MBS value of 38.5143 ha.
- **Timmanahalli:** point C prints a latitude with `60.00` seconds; no normalization to the next minute is inferred.
- **Kudarka:** the source table omits hemisphere markers; no N/E signs are inferred from the State or nearby coordinates.
- **Nandana:** BP-5 contains a longitude outlier that makes the source-order polygon invalid; IBM also publishes 29.17 ha while the MBS publishes 5.3152 ha.
- **Kodidra:** IBM publishes 29.17 ha while the exact-title MBS publishes 41.3186 ha.
- **Virpur-Lusari:** IBM publishes 29.17 ha while the exact-title MBS publishes 6.2265 ha.
- **Devalmari-Katepalli:** the MBS publishes only coordinate extents and refers to an unincluded cadastral plate for detailed vertices.
- **South Padve:** the MBS publishes only coordinate extents; no rectangle is inferred.
- **Kondhala:** the four source-order coordinates form a valid polygon of about 162.74 ha, 54.99% above the MBS-published 105 ha.

## Technical profile fields

Every reviewed row in the match audit retains the source mineral wording, normalized material arrays, exploration level and agency, borehole count and drilled meterage, resources, grade, mineral-zone geometry, structural trend, thickness, access, hydrology, climate and topography. The geometry CSV repeats those fields for admitted footprints. Concise source-normalized resource, grade and climate summaries are used where PDF reading order would otherwise confuse headers with values.

Explicit anomalies remain visible. For example, the Block VII Cudnem MBS prints annual rainfall as about `4000 m`; KHANAN retains that source-unit anomaly instead of silently changing it to millimetres. Niddodi's MBS identifies a bauxite block and reports Al2O3 grade bands, but the quantity row prints `Iron ore`; the audit preserves that conflict while admitting the independently valid boundary. The Maharashtra Surjagad seasonal-temperature labels and the South Padve and Savali rainfall units are preserved under the same rule.

## Interpretation limits

An MBS is an auction-stage technical source, not a present-tense mine-status register. The joined IBM and MBS evidence does not independently establish the controlling grant, current lessee, production, clearances, legal boundary, permission to access land, current resource classification or operating status. Every row therefore sets `current_legal_or_operational_status_verified=false` and remains context only.

The review is incomplete by design and does not imply that the 53 unreviewed IBM rows or the five Andhra status-linked rows lack coordinates. The next Phase 2 increments are the 22 Madhya Pradesh and 31 Rajasthan rows, archival Andhra boundary-document recovery where lawfully public, and reconciliation of successful-auction reporting against controlling State grant records.

Rebuild with:

```bash
.venv/bin/python scripts/build_ibm_auction_mbs_geometry_2023_24.py --refresh
.venv/bin/python scripts/build_ibm_auction_status_evidence_2023_24.py --refresh
.venv/bin/python scripts/plot_ibm_auction_mbs_geometries.py
```
