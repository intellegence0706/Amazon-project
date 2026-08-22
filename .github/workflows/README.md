# Scheduled refresh

`refresh.yml` keeps the deployed site's data fresh. Serverless functions cannot
run long scans, so scanning happens here instead — GitHub's runners have no
time limit that matters.

## Setup

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value | Required |
|---|---|---|
| `DATABASE_URL` | Supabase transaction-pooler string (port 6543) | yes |
| `KEEPA_API_KEY` | Keepa API key | no |

Then **Actions → Refresh retailer data → Run workflow** to test it immediately
rather than waiting for the schedule.

## What it does

Writes **straight to Supabase**. There is no local database and no `migrate`
step — `ingest` speaks Postgres directly when `DATABASE_URL` is set.

That distinction matters. Running `ingest` into a fresh local SQLite and then
`migrate` would append a duplicate price snapshot on every run, because a CI
runner starts empty each time and every price looks new. Writing directly means
the existing change-detection works: a snapshot is stored only when a price
actually moved.

## Schedule

Two schedules, doing different jobs:

| Cron | What | Why |
|---|---|---|
| `0 2,8,14,20 * * *` | Partial scan, 4× daily | Keeps prices current, cheaply |
| `30 3 * * *` | **Full** scan, once daily | Only a full scan can detect that a retailer has **removed** a product |

The distinction matters. A partial scan reads the first few catalog pages, so
anything it does not see is simply unread, not gone. If absence were treated as
removal there, every short run would wipe most of the catalog. So only the full
scan marks removals; the partial ones never do.

A manual run is partial unless you tick **Full scan** in the dialog.

## Cost

Public repositories: free and unlimited.
Private repositories: 2,000 minutes/month free. At roughly 6 minutes per run,
four runs a day is about 720 minutes — comfortably inside the free tier.

## Design notes

- **`continue-on-error` per retailer** — a retailer changing its site should not
  stop the other four from refreshing.
- **`concurrency: refresh`** — two scans never overlap and fight over rows.
- **Matching is opt-in on manual runs** so Keepa tokens are never spent by
  accident, but automatic on schedule when a key is configured.
- **Job summary** — every run posts current totals to the Actions summary page,
  so a glance tells you whether data is actually moving.

## Known risk

GitHub runners use datacenter IP addresses, which retailers block more readily
than residential ones. The five current retailers publish open catalogs and are
unlikely to care, but a retailer added later behind bot protection may fail here
while working from your machine. If that happens, route that retailer through a
scraping service in `fetcher.py`.
