# Deploying to Vercel

The customer opens a URL. Nothing to install.

```
Vercel
├─ web/out/          static Next.js export        →  served by Vercel's CDN
└─ api/index.py      FastAPI serverless function  →  /api/*
                            ↓
                     Hosted Postgres (Neon / Supabase / Vercel Postgres)
                            ↑
              Ingestion runs locally or on a scheduled worker
```

## 1. Create a database

Any hosted Postgres with a free tier works. Neon has first-party Vercel
integration. Copy the connection string.

## 2. Push your data up

Serverless functions are too short-lived to scan retailer catalogs, so scan
locally and push the result:

```bash
python3 -m arbitrage.cli ingest vitacost        # local, unlimited time
DATABASE_URL='postgres://…' python3 -m arbitrage.cli migrate
```

`migrate` copies retailers, products, price history, Amazon products and matches,
remapping foreign keys as Postgres assigns new IDs. It is idempotent — re-running
skips rows that already exist.

## 3. Deploy

```bash
npm i -g vercel
vercel
```

Then set two environment variables in the Vercel project settings:

| Variable | Value |
|---|---|
| `DATABASE_URL` | your Postgres connection string |
| `KEEPA_API_KEY` | the Keepa key (optional — without it, figures stay modelled) |

Redeploy after adding them.

## 4. Keeping data fresh

Serverless cannot run the scans. Pick one:

- **Manual** — run `ingest` then `migrate` locally whenever you want fresh data
- **Scheduled worker** — a small always-on box (Railway, Render, Fly, or a cron
  on any machine) running `ingest` with `DATABASE_URL` set, writing straight to
  the same Postgres

The second is what a production version would do.

## What changes on Vercel

| | Local | Vercel |
|---|---|---|
| Database | SQLite file | Postgres via `DATABASE_URL` |
| Keepa key | `.env` file, editable from the UI | environment variable |
| Scanning | any duration | **not supported** — run it elsewhere |
| API path | `/api/*` | `/api/*` — identical |

The frontend bundle is byte-identical in both environments. There is no
build-time target switch.

## Verified vs unverified

**Verified locally:** the dual-backend data layer, portable `RETURNING` inserts,
placeholder translation, `/api` mounting, the whole pipeline through `/api/*`,
and the frontend build.

**Not verified:** the Postgres path against a real Postgres server, and the
Vercel deployment itself. Both need credentials this machine does not have.
Before showing it to anyone, run:

```bash
DATABASE_URL='postgres://…' python3 -m arbitrage.cli migrate
DATABASE_URL='postgres://…' python3 -m arbitrage.cli verify --offline
```

If those pass, the deployment will work.
