# Setup

Two things run: the **engine** (Python) and the **interface** (browser).

## First time

```bash
pip install fastapi uvicorn
cd web && npm install && npm run build && cd ..
```

## Every time

```bash
./start.sh
```

Then open **http://localhost:3000**

## Using it

The dashboard walks through four steps:

1. **Amazon data** — paste your Keepa API key. It is validated with Keepa before
   being saved, so you know immediately whether it works.
2. **Check it works** — click *Run verification*. Every stage is tested and any
   failure names both the stage and the fix.
3. **Scan retailers** — click *Scan* on any retailer to pull its current catalog
   and record price changes.
4. **Match to Amazon** — resolves discounted products to ASINs.

Then open **Leads**. Switch between *Modelled* and *Verified*:

- **Modelled** — retailer prices are real, Amazon prices are estimated. For
  demonstration only.
- **Verified** — real Amazon data from Keepa. These are actual sourcing numbers.

## Without a Keepa key

Everything still runs. Retailer scanning, discounts and price history are real.
Amazon figures stay modelled and every lead is flagged so nothing can be mistaken
for a verified sourcing decision.
