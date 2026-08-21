# Setup

## First time

```bash
pip install fastapi uvicorn
```

That is all. The interface is already built and ships with the project — Node is
not required.

## Every time

```bash
./start.sh
```

Your browser opens at **http://localhost:8000**. One process, one URL.

## Using it

The dashboard walks through four steps:

1. **Amazon data** — paste your Keepa API key. It is checked against Keepa before
   being saved, so you know straight away whether it works.
2. **Check it works** — click *Run verification*. Every stage is tested, and any
   failure names both the stage and the fix.
3. **Scan retailers** — pull each retailer's current catalog and record price changes.
4. **Match to Amazon** — resolve discounted products to ASINs.

Then open **Leads** and switch between:

- **Modelled** — retailer prices are real, Amazon prices are estimated.
  For demonstration only.
- **Verified** — real Amazon data from Keepa. Actual sourcing numbers.

## Without a Keepa key

Everything still runs. Retailer scanning, discounts and price history are real.
Amazon figures stay modelled, and every lead is flagged so nothing can be
mistaken for a verified sourcing decision.

## Rebuilding the interface

Only needed if you change the frontend:

```bash
cd web && npm install && npm run build
```

## API

Interactive docs at http://localhost:8000/docs
Machine-readable spec at http://localhost:8000/openapi.json — point any
integration at that.
