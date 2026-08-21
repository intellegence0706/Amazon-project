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
python3 -m uvicorn arbitrage.web.api:app --port 8000
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

## Status

Working: fingerprinting, Shopify ingestion, price history, sale detection,
fee/ROI math, filtering, CSV export.

**Not yet real:** Amazon-side data. `leads` currently models the Amazon price as
`list_price × multiplier`. The ROI figures prove the *math*, not the *market*.

## The one blocker

Real leads need a **Keepa API key (~€49/mo)** for ASIN matching, Buy Box price,
BSR history and authoritative fees. Everything else is built and runs for $0.

Note: fee tables in `economics.py` are a model. Verify against Amazon's current
US rate card, and prefer Keepa's per-ASIN fees once a key exists.

## Known refinements

- Colourway variants produce near-duplicate leads — dedup on parent product
- `pack_qty` parses supplement/grocery titles well, soft goods poorly
- Matching engine (Stage 2) not started — blocked on Keepa
