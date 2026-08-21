# Arbitrage Sourcing Engine — Phase 1

Retail-arbitrage lead engine. Ingests retailer catalogs, detects active sales,
and computes profit / ROI / margin. Runs on Python 3.10+ with **no dependencies
and no setup** — SQLite, standard library only.

## Quick start

```bash
python3 -m arbitrage.cli fingerprint www.vitacost.com www.homedepot.com
python3 -m arbitrage.cli add vitacost www.vitacost.com --name Vitacost
python3 -m arbitrage.cli ingest vitacost --pages 6
python3 -m arbitrage.cli sales --min-discount 25
python3 -m arbitrage.cli leads --min-roi 40
python3 -m arbitrage.cli sales --min-discount 30 --csv > leads.csv
```

## REST API

```bash
pip install fastapi uvicorn
./start.sh
```

Interactive docs at `/docs`. Machine-readable spec at `/openapi.json` — hand that
URL to whoever (or whatever) is doing the integration.

| Endpoint | Purpose |
|---|---|
| `GET /leads` | Profit-modelled leads, filter by ROI, price, retailer |
| `GET /sales` | Discounted in-stock products (real retailer data) |
| `GET /candidates` | Keepa-token funnel — how few lookups are actually needed |
| `GET /retailers` | Registered retailers + product counts |
| `GET /fingerprint?host=` | Sort a domain into an acquisition tier |
| `GET /export.csv` | CSV download |
| `POST /retailers/{slug}/ingest` | Trigger a scan |
| `GET /health` `GET /stats` | Status, and whether Keepa is configured |

Every lead carries `modelled: true` until a Keepa key exists. `/health` states it
explicitly. No surface can silently present modelled ROI as verified.

## Architecture

| Module | Role |
|---|---|
| `fingerprint.py` | Sorts any domain into an acquisition tier (1 open → 4 protected) |
| `fetcher.py` | All HTTP goes through here. `DirectFetcher` now, `ScraperAPIFetcher` drops in |
| `adapters/` | One adapter per **platform**, not per retailer |
| `ingest.py` | Idempotent upsert; snapshots written only on price change |
| `economics.py` | FBA + referral fees, net profit, ROI, margin, risk flags |
| `queries.py` | Shared read layer — CLI, report and API all use it |
| `web/api.py` | FastAPI + auto-generated OpenAPI spec |
| `report.py` | Self-contained shareable HTML report |
| `db.py` | Schema. Portable SQL — Postgres migration is a connect() swap |

Adding a retailer already on a supported platform is one `add` command, not code.

## Matching

```bash
python3 -m arbitrage.cli match --limit 25   # retailer product -> ASIN
python3 -m arbitrage.cli real               # leads from REAL Amazon data
```

Two paths: exact GTIN lookup (near-certain), then keyword search with reranking.
**Hard gates reject rather than score down** — a brand mismatch or a pack-size
mismatch is a no, not a low number. Unknown pack size caps confidence *below*
auto-accept, because unknown is not innocent: a 6-pack matched to a single unit
produces a beautiful fake ROI and dead inventory.

| Confidence | Status | Meaning |
|---|---|---|
| ≥ 0.90 | `auto` | Trusted, appears in verified leads |
| 0.70–0.89 | `pending` | Needs a human glance |
| < 0.70 | `rejected` | Discarded |

`/leads` is modelled. `/leads/verified` is real matched data with `modelled: false`.
The two never mix.

## Tests

```bash
python3 tests/test_matching.py    # 24 checks, scoring gates and failure modes
python3 tests/test_pipeline.py    # end-to-end against a mock Keepa
```

Scoring is pure and offline-testable on purpose — it ships to a machine whose
Keepa key the author never had, so its failure modes are tested, not assumed.

## Status

Working: fingerprinting, Shopify ingestion, price history, sale detection,
matching engine, fee/ROI math, filtering, CSV export, REST API, self-verification.

**Not yet real:** Amazon-side data. `leads` currently models the Amazon price as
`list_price × multiplier`. The ROI figures prove the *math*, not the *market*.

## Interface

```bash
./start.sh          # one process, opens the browser
```

Opens at **http://localhost:8000**. See [SETUP.md](SETUP.md).

The interface is a static Next.js export served by the Python API from the same
origin — so there is one process, one port, no CORS, and **no Node needed at
runtime**. The built bundle ships with the project.

Next.js 16 / React 19 / TypeScript. The dashboard walks through key setup,
verification, scanning and matching — every step is a button, so the whole
pipeline is operable without a terminal. Leads switch between *Modelled* and
*Verified*, and the two are never presented as the same thing.

## Setup

```bash
cp .env.example .env      # add your Keepa key
python3 -m arbitrage.cli verify
```

`verify` self-tests every stage — config, database, retailer fetch, Keepa key,
Amazon lookup, rank history, fees, ROI — and names the stage that failed plus how
to fix it. Run it after adding a key. It also exists as `GET /verify`.

Without a key it runs in **simulation mode** against a recorded Keepa response,
so the full chain still executes and every ROI stays flagged `modelled: true`.

## The one blocker

Real leads need a **Keepa API key (~€49/mo)** for ASIN matching, Buy Box price,
BSR history and authoritative fees. Everything else is built and runs for $0.

Note: fee tables in `economics.py` are a model. Verify against Amazon's current
US rate card, and prefer Keepa's per-ASIN fees once a key exists.

## Known refinements

- Colourway variants produce near-duplicate leads — dedup on parent product
- `pack_qty` parses supplement/grocery titles well, soft goods poorly
- Most fuzzy matches land in `pending`, not `auto` — by design, since tier-1
  retailers carry no UPCs. Expect a review queue until UPC-bearing feeds are added.
