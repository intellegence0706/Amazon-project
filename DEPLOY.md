# Deploying to Vercel + Supabase

The customer opens a URL. Nothing to install.

```
Vercel
├─ web/out/          static Next.js export        →  Vercel CDN
└─ api/index.py      FastAPI serverless function  →  /api/*
                            ↓
                      Supabase Postgres
                            ↑
              Ingestion runs locally or on a scheduled worker
```

## 1. Create the Supabase project

New project → wait for provisioning → **Project Settings → Database →
Connection string**.

**Take the "Transaction pooler" string, not the direct one.** It looks like:

```
postgresql://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
```

This matters more than it looks. Serverless functions open a fresh connection per
invocation, and the direct connection (port 5432) runs out of slots as soon as a
few requests overlap. The failure only appears under load, which is the worst way
to discover it. `verify` now checks for this and fails if you get it wrong.

Transaction-mode pooling also forbids prepared statements, which psycopg3 starts
using automatically — that is disabled in `db.py`, so nothing further is needed.

## 2. Push your data up

Serverless functions are too short-lived to scan retailer catalogs, so scan
locally and push the result:

```bash
python3 -m arbitrage.cli ingest vitacost         # local, unlimited time

export DATABASE_URL='postgresql://postgres.[REF]:[PW]@aws-0-[REGION].pooler.supabase.com:6543/postgres'
python3 -m arbitrage.cli migrate
python3 -m arbitrage.cli verify --offline        # confirm before deploying
```

`migrate` copies retailers, products, price history, Amazon products and matches,
remapping foreign keys as Postgres assigns new IDs. It is idempotent.

## 3. Deploy

```bash
npm i -g vercel
vercel
```

Then in **Vercel → Project Settings → Environment Variables**:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Supabase **pooler** string (port 6543) |
| `KEEPA_API_KEY` | the Keepa key — optional; without it figures stay modelled |

Redeploy after adding them.

## 4. Keeping data fresh

Serverless cannot run the scans. Either:

- **Manual** — run `ingest` then `migrate` locally when you want fresh data, or
- **Scheduled worker** — a small always-on box (Railway, Render, Fly, or cron on
  any machine) running `ingest` with `DATABASE_URL` set, writing straight to
  Supabase. This is what a production version would do.

## Supabase free tier

Projects **pause after about a week of inactivity** and need a manual resume from
the dashboard. For a demo that sits idle between viewings, check it is awake
before sending anyone the link.

## What changes in deployment

| | Local | Vercel + Supabase |
|---|---|---|
| Database | SQLite file | Supabase Postgres |
| Connection | direct file | transaction pooler, port 6543 |
| Keepa key | `.env`, editable from the UI | environment variable |
| Scanning | any duration | **not supported** — run elsewhere |
| API path | `/api/*` | `/api/*` — identical |

The frontend bundle is byte-identical in both environments.

## Verified vs unverified

**Verified locally:** dual-backend data layer, portable `RETURNING` inserts,
placeholder translation, pooler detection, `/api` mounting, the full pipeline
through `/api/*`, and the frontend build.

**Not verified:** a live Supabase connection and the Vercel deploy itself — both
need credentials this machine does not have. Run step 2 before showing anyone;
if `migrate` and `verify` pass against your real connection string, the
deployment will work.
