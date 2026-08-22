# Operating guide

Everything you will actually need to do, by task.

---

## Daily use — local

### Start it

```bash
cd "/home/desktop/Documents/Amazon project"
./start.sh
```

Opens **http://localhost:8000** in your browser. Ctrl+C to stop.

### See what is on sale right now

```bash
python3 -m arbitrage.cli sales --min-discount 30
```

### See profit estimates

```bash
python3 -m arbitrage.cli leads --min-roi 50
```

### Export for a spreadsheet

```bash
python3 -m arbitrage.cli sales --min-discount 25 --csv > leads.csv
```

### Check everything is healthy

```bash
python3 -m arbitrage.cli verify
```

Green means working. Anything red tells you the fix on the next line.

---

## Refreshing data

### Locally

```bash
python3 -m arbitrage.cli ingest vitacost
python3 -m arbitrage.cli ingest brooklinen
python3 -m arbitrage.cli ingest swanson
python3 -m arbitrage.cli ingest pipingrock
python3 -m arbitrage.cli ingest grove
```

Each takes 30–90 seconds. Safe to re-run — only changed prices are recorded.

### On the live site

You do nothing. GitHub Actions refreshes it every 6 hours.

To force it now: **GitHub → Actions → Refresh retailer data → Run workflow**.

---

## Adding a retailer

```bash
# 1. Can we read its catalog?
python3 -m arbitrage.cli fingerprint www.example.com

# 2. If it says tier 1, add it
python3 -m arbitrage.cli add example www.example.com --name "Example Store"

# 3. Pull the catalog
python3 -m arbitrage.cli ingest example
```

**What the tiers mean**

| Tier | Meaning | What to do |
|---|---|---|
| 1 | Open catalog | Add it — works immediately, free |
| 2 | Reachable, no open catalog | Needs an affiliate feed |
| 3 | Has an official API | Sign up for a key |
| 4 | Blocked | Needs an affiliate feed or a paid scraping service |

Only tier 1 works with no extra setup.

**To find more tier-1 retailers**, feed it a list:

```bash
python3 -m arbitrage.cli fingerprint www.shop1.com www.shop2.com www.shop3.com
```

Keep the ones that come back tier 1.

**Also add it to the schedule**: open `.github/workflows/refresh.yml` and copy
one of the `Scan …` steps, changing the slug.

---

## Turning on real Amazon data

Everything Amazon-side is **modelled** until a Keepa key exists.

### Locally

Either paste the key into the dashboard (Step 1 on the home page), or:

```bash
echo "KEEPA_API_KEY=your_key_here" >> .env
python3 -m arbitrage.cli verify
```

### On the live site

**Vercel → Settings → Environment Variables → add `KEEPA_API_KEY` → Redeploy.**

Also add it to **GitHub → Settings → Secrets → Actions** so scheduled matching runs.

### Then match products

```bash
python3 -m arbitrage.cli match --limit 50   # retailer product -> ASIN
python3 -m arbitrage.cli real               # leads with REAL Amazon data
```

---

## Adjusting your criteria

Edit `.env`:

```
MIN_ROI=30            # minimum return on investment, percent
MIN_PROFIT=3.00       # minimum profit per unit, dollars
MAX_BSR=250000        # ignore items ranked worse than this
MAX_OFFER_COUNT=15    # ignore listings this crowded
INBOUND_COST=0.55     # your shipping cost per unit into Amazon
PREP_COST=0.00        # your prep cost per unit
```

No restart needed for CLI commands; restart the server for the web interface.

---

## Deploying an update

```bash
git add -A && git commit -m "what changed"
git push
```

Vercel rebuilds automatically if the repo is connected. Otherwise:

```bash
cd web && npm run build && cd ..
vercel --prod
```

---

## When something breaks

**Always start here:**

```bash
python3 -m arbitrage.cli verify        # local
python3 -m arbitrage.cli preflight     # deployment
```

| Symptom | Cause | Fix |
|---|---|---|
| Live site shows 0 products | Vercel's `DATABASE_URL` differs from yours | Re-check the Vercel env var, redeploy |
| `password authentication failed` | Wrong database password | Supabase → Settings → Database → Reset |
| Connection times out | Supabase project paused | Open the Supabase dashboard to resume |
| A retailer scan returns nothing | Site changed platform | `fingerprint` it again |
| ROI figures look wrong | No Keepa key — they are modelled | Add the key |
| "unknown retailer" | Not registered in that database | Run `add` first |

**Supabase free tier pauses after ~1 week idle.** If the live site suddenly
fails, check the Supabase dashboard first.

---

## Command reference

| Command | Purpose |
|---|---|
| `ui` | Start the server and open the browser |
| `verify` | Self-test every stage |
| `preflight` | Check deployment readiness |
| `fingerprint <host>` | Sort a domain into an acquisition tier |
| `add <slug> <host>` | Register a retailer |
| `ingest <slug>` | Pull a catalog, record price changes |
| `sales` | Discounted products (real data) |
| `leads` | Profit estimates (modelled) |
| `match` | Match products to Amazon ASINs |
| `real` | Leads from real Amazon data |
| `migrate` | Copy local database into Supabase |

Add `--help` to any of them.
