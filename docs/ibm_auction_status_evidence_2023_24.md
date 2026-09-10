# IBM 2023-24 Andhra auction rows: dated status evidence

**Development release:** `v1.0-alpha.13`

**Sources:** Prakasam District Administration, Government of Andhra Pradesh; Ministry of Mines, Government of India

**Model status:** context only; excluded from training labels, validation labels, scoring, candidate promotion and geometry

## Purpose

The current public Andhra Pradesh MSTC Mine Block Summary index does not expose exact-name boundary documents for the five Andhra rows in IBM's 2023-24 auction table. KHANAN therefore withholds their geometry and publishes dated status evidence in a separate five-row table rather than collapsing current, historical and controlling legal evidence into one claim.

`outputs/india_ibm_auctioned_concession_status_evidence_2023_24.csv` preserves the IBM block identity and material arrays, the source status wording, structured dated events, areas, bidder and bid fields, source URL and hash, source-date basis, evidence level and quality flags. No row is promoted to an operating mine.

## Evidence retained

The Prakasam District Administration page, last updated 2 September 2026, reports:

| Block | Source area | Block-specific source status |
|---|---:|---|
| Addankivaripalem | 914 ha | Prospecting Licence executed March 2025; 38 of 89 boreholes completed; Form-C approval dated 19 December 2025 |
| Lakshmakapalle North | 1,194.7 ha | Prospecting Licence executed March 2025; 21 of 66 boreholes completed; Form-C approval dated 7 January 2026 |
| Lakshmakapalle South | 1,825.8 ha | New composite licence block |

The same named three-block JSW section lists an auction date of 28 July 2023, Letter of Intent on 11 September 2023, Revenue Department NOC on 20 January 2025, and prospecting-licence execution on 4 March 2025 with three-year validity. The builder applies those shared section-level milestones to the three named rows and flags that scope explicitly. It does not invent a block-specific Form-C date for Lakshmakapalle South.

The Ministry of Mines' January 2025 *National Mining Ministers' Conference — Auction & Operationalization of Mineral Blocks* presentation reports on physical PDF page 50:

| Block | Area | Preferred bidder | Final bid | Historical status |
|---|---:|---|---:|---|
| Adakula | 36.997 ha | Shri P. Satyanarayana | 3.6% | LoI to be issued |
| Mincheri RF | 1,327 ha | South-West Mining Limited | 12.6% | LoI to be issued |

The Ministry slide prints 14 April 2024 as Mincheri's auction date, while IBM prints 11 March 2024. Both values remain in separate fields, `auction_date_agrees_with_ibm=false`, and the conflict is included in `quality_flags_json`.

## Interpretation limits

These are official secondary sources, not the controlling licence, grant, lease, cadastral boundary or clearance documents. The Ministry slide is a historical January 2025 snapshot. The Prakasam page provides useful later administrative evidence but no coordinates. Consequently:

- `current_legal_or_operational_status_verified=false` for all five rows;
- `geometry_published=false` for all five rows;
- status events are tied to their published dates or source snapshot date;
- source conflicts remain visible; and
- every row remains `context_only` for modeling.

Rebuild with:

```bash
.venv/bin/python scripts/build_ibm_auction_status_evidence_2023_24.py --refresh
```
