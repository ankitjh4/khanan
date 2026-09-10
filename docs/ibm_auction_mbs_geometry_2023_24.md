# IBM 2023-24 auction rows: State Mine Block Summary geometry

**Development release:** `v1.0-alpha.9`

**Sources:** Indian Bureau of Mines, *Indian Minerals Yearbook 2024*, Table 5; MSTC State mineral-auction Mine Block Summary portal

**Model status:** context only; excluded from training labels, validation labels, scoring and candidate promotion

## Purpose

IBM Table 5 names 97 mining leases or composite licences described as granted through auction during 2023-24, but it publishes no coordinates. Alpha.9 begins the separate task of locating exact State Mine Block Summaries and admitting a footprint only when the source itself publishes a boundary that survives spatial checks.

The new outputs are:

- `outputs/india_ibm_auctioned_concession_mbs_match_audit_2023_24.csv`: one row for every IBM Table 5 record, including review scope, selected MBS provenance and geometry-admission outcome;
- `outputs/india_ibm_auctioned_concession_geometries_2023_24.csv`: eight admitted source footprints with technical and environmental context;
- `outputs/india_ibm_auctioned_concession_geometries_2023_24.geojson`: the same eight footprints as GeoJSON; and
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

These are link-inventory observations, not 1,124 parsed documents or 1,124 mines. Alpha.9 downloads and parses eleven selected PDFs: six Chhattisgarh blocks and five Goa blocks. Record-specific expressions are curated from exact names. When the portal contains several versions, the highest numeric MSTC file identifier is selected and the rule is retained in the match audit. The remaining 86 IBM rows are labelled `not_reviewed_in_this_release`; a zero curated-candidate count for those rows must not be interpreted as a failed exhaustive search.

## Coordinate extraction and visual review

Every coordinate-bearing page used by this release was rendered with Poppler at 150 dpi and visually reviewed against the source table.

- Chhattisgarh tables are transcribed from source-labelled WGS84 DMS rows in published point order.
- Goa Blocks V, VII and IX use the source-published WGS84 / UTM zone 43N table, parsed by boundary-point identifier and converted from EPSG:32643 to EPSG:4326.
- Goa Block VIII uses its DMS table because the final source UTM northing is internally inconsistent with the source latitude. The missing source identifier `BP6` is retained as a quality flag; points are not renumbered.
- No points are reordered, interpolated or inferred from names, nearby villages, areas or map appearance.

The builder pins each selected PDF by exact URL, MSTC file identifier, SHA-256, byte size and page count.

## Admission gates

A source footprint is published only when all of the following hold:

1. the source-order polygon is valid;
2. its centroid is covered by the stated State in the 2011 district boundary diagnostic;
3. computed WGS84 ellipsoidal area differs from the MBS area by no more than 5%; and
4. when IBM also publishes an area, the IBM and MBS values differ by no more than 5%.

Full-footprint State containment is retained separately because the community-maintained 2011 administrative boundary can differ from current or legal boundaries. It is a diagnostic, not a controlling cadastral test.

Eight footprints pass:

| IBM record | Block | Material | Vertices | Computed area vs MBS |
|---|---|---|---:|---:|
| IBM-IMYB2024-AUCTION-006 | North of Arjunda | Glauconite (Potash) | 10 | 4.179% |
| IBM-IMYB2024-AUCTION-008 | Devri | Limestone | 4 | 0.493% |
| IBM-IMYB2024-AUCTION-010 | Giroud Uprani | Glauconite | 13 | 1.944% |
| IBM-IMYB2024-AUCTION-011 | Tumrisur Garda II | Gold | 4 | 0.072% |
| IBM-IMYB2024-AUCTION-093 | Block V Advalpale-Thivim | Iron ore | 11 | 0.045% |
| IBM-IMYB2024-AUCTION-095 | Block VII Cudnem | Iron ore | 8 | 0.054% |
| IBM-IMYB2024-AUCTION-096 | Block VIII Thivim-Pirna | Iron ore | 10 | 0.216% |
| IBM-IMYB2024-AUCTION-097 | Block IX Surla-Sonshi | Iron ore | 65 | 2.549% |

Three reviewed records are withheld rather than repaired:

- **Saloni:** IBM publishes 600 ha; the exact-name MBS publishes 670 ha.
- **Kareli-Chandi:** the MBS prints malformed latitude seconds (`34.4.00`) for two vertices.
- **Goa Block VI Cudnem-Cormolem:** both DMS and UTM tables reconstruct to about 28.8 ha, 25.31% below the MBS value of 38.5143 ha.

## Technical profile fields

Admitted rows retain the source mineral wording, normalized material arrays, exploration level and agency, borehole count and drilled meterage, resources, grade, mineral-zone geometry, structural trend, thickness, access, hydrology, climate and topography. Concise source-normalized resource, grade and climate summaries are used where PDF reading order would otherwise confuse headers with values.

Explicit anomalies remain visible. For example, the Block VII Cudnem MBS prints annual rainfall as about `4000 m`; KHANAN retains that source-unit anomaly instead of silently changing it to millimetres.

## Interpretation limits

An MBS is an auction-stage technical source, not a present-tense mine-status register. The joined IBM and MBS evidence does not independently establish the controlling grant, current lessee, production, clearances, legal boundary, permission to access land, current resource classification or operating status. Every row therefore sets `current_legal_or_operational_status_verified=false` and remains context only.

The review is incomplete by design and does not imply that the 86 unreviewed IBM rows lack coordinates. The next Phase 2 increment is to extend the same document-level review and gates across the remaining States, then reconcile successful-auction reporting against controlling State grant records.

Rebuild with:

```bash
.venv/bin/python scripts/build_ibm_auction_mbs_geometry_2023_24.py --refresh
.venv/bin/python scripts/plot_ibm_auction_mbs_geometries.py
```
