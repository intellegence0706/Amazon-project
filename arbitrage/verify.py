"""Self-test the whole pipeline.

Written for a specific situation: the person with the API key is not the person
who wrote the code, and cannot debug it. This runs on their machine, checks every
step in order, and says plainly which one failed.

It turns "is it sufficient?" from an opinion into a result.
"""
from dataclasses import dataclass
from typing import Optional

from . import config, db, queries
from .adapters.shopify import ShopifyAdapter
from .economics import evaluate
from .fetcher import DirectFetcher
from .keepa import KeepaClient, KeepaError, fixture_client

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""

    @property
    def icon(self):
        return {PASS: "✓", FAIL: "✗", SKIP: "–", WARN: "!"}[self.status]


def run(live_network=True, keepa_client: Optional[KeepaClient] = None):
    checks, s = [], config.load()
    add = lambda *a, **k: checks.append(Check(*a, **k))

    # 1 -- configuration -----------------------------------------------------
    add("Configuration file", PASS,
        f"min ROI {s.min_roi}%, max BSR {s.max_bsr:,}, inbound ${s.inbound_cost}")

    # 2 -- database ----------------------------------------------------------
    try:
        conn = db.init()
        st = queries.stats(conn)
        add("Database", PASS,
            f"{st['products']:,} products across {st['retailers']} retailers")
    except Exception as e:
        add("Database", FAIL, str(e), "Delete arbitrage.db and re-run ingest.")
        return checks

    # 3 -- retailer data -----------------------------------------------------
    if st["retailers"] == 0:
        add("Retailers registered", FAIL, "none",
            "Run: python3 -m arbitrage.cli add <slug> <host>")
    elif st["products"] == 0:
        add("Retailer catalogs", FAIL, "no products ingested",
            "Run: python3 -m arbitrage.cli ingest <slug>")
    else:
        n, _ = queries.sales(conn, min_discount=15, limit=1)
        add("Retailer catalogs", PASS if n else WARN,
            f"{n} products currently discounted 15%+")

    # 4 -- live retailer fetch ----------------------------------------------
    if not live_network:
        add("Retailer connection", SKIP, "network checks disabled")
    else:
        r = conn.execute(
            "SELECT * FROM retailers WHERE enabled=1 ORDER BY id LIMIT 1").fetchone()
        if r is None:
            add("Retailer connection", SKIP, "no retailer registered")
        else:
            try:
                a = ShopifyAdapter(r["host"], DirectFetcher(delay=0.2), max_pages=1)
                got = next(iter(a.products()), None)
                add("Retailer connection", PASS if got else FAIL,
                    f"{r['name']}: {'live catalog reachable' if got else 'returned nothing'}",
                    "" if got else "Retailer may have changed platform. Re-run fingerprint.")
            except Exception as e:
                add("Retailer connection", FAIL, f"{r['name']}: {e}",
                    "Check internet access, or route this retailer through a scraping service.")

    # 5 -- Keepa key ---------------------------------------------------------
    client, simulated = keepa_client, False
    if client is None:
        if s.keepa_configured:
            client = KeepaClient(s.keepa_api_key, s.keepa_domain)
        else:
            client, simulated = fixture_client(s.keepa_domain), True

    if simulated:
        add("Keepa API key", WARN, "not configured — running in simulation",
            "Add KEEPA_API_KEY to .env. Amazon figures stay MODELLED until then.")
    else:
        try:
            tk = client.tokens()
            add("Keepa API key", PASS, f"valid, {tk} tokens available"
                if tk is not None else "valid")
        except KeepaError as e:
            add("Keepa API key", FAIL, str(e),
                "Check the key is correct and the subscription is active.")
            return checks

    # 6 -- Amazon product lookup --------------------------------------------
    try:
        p = client.by_asin("B00EXAMPLE1" if simulated else "B0BDHWDR12")
        if p is None:
            add("Amazon product lookup", FAIL, "no product returned",
                "Keepa may not have this ASIN. Try another.")
            return checks
        add("Amazon product lookup", PASS,
            f"{(p.title or p.asin)[:52]} — buy box ${p.sale_price}")
    except KeepaError as e:
        add("Amazon product lookup", FAIL, str(e))
        return checks

    # 7 -- sales rank history ------------------------------------------------
    add("Sales rank history", PASS if p.has_rank_history else WARN,
        f"current BSR {p.bsr:,}, 90-day avg {p.bsr_90d_avg:,}"
        if p.has_rank_history else "no rank history returned",
        "" if p.has_rank_history else "Without rank history you cannot tell whether a product sells.")

    # 8 -- fees and ROI ------------------------------------------------------
    if p.sale_price is None:
        add("Profit calculation", FAIL, "no Amazon price available")
        return checks

    override = ({"fba": p.fba_fee, "referral": round(p.sale_price * p.referral_pct, 2)}
                if p.fba_fee is not None and p.referral_pct is not None else None)
    cost = round(p.sale_price * 0.45, 2)
    lead = evaluate(cost=cost, sale_price=p.sale_price,
                    weight_lb=(p.weight_grams or 454) / 453.6,
                    bsr=p.bsr, offer_count=p.offer_count,
                    amazon_on_listing=p.amazon_on_listing,
                    inbound=s.inbound_cost, prep=s.prep_cost,
                    fee_override=override, max_bsr=s.max_bsr, min_roi=s.min_roi)
    add("Profit calculation", PASS,
        f"cost ${cost} → sells ${p.sale_price}, fees ${lead.referral_fee + lead.fba_fee:.2f}, "
        f"net ${lead.net_profit}, ROI {lead.roi_pct}%"
        + (f"  [{', '.join(lead.flags)}]" if lead.flags else ""))
    add("Fee source", PASS if override else WARN,
        "Keepa authoritative fees" if override else "estimated from rate table",
        "" if override else "Keepa did not return fee data for this ASIN.")

    # 9 -- end to end --------------------------------------------------------
    ok = [c for c in checks if c.status == FAIL]
    add("End-to-end pipeline", FAIL if ok else (WARN if simulated else PASS),
        "retailer → sale → Amazon → fees → ROI"
        + (" (simulated — no Keepa key)" if simulated else ""),
        "Add a Keepa key to run this for real." if simulated else "")
    return checks


def report(checks) -> str:
    w = max(len(c.name) for c in checks)
    lines = ["", "  PIPELINE VERIFICATION", "  " + "─" * (w + 58)]
    for c in checks:
        lines.append(f"  {c.icon} {c.name:<{w}}  {c.status:<4} {c.detail}")
        if c.fix:
            lines.append(f"    {'':<{w}}       → {c.fix}")
    n = {s: sum(1 for c in checks if c.status == s) for s in (PASS, WARN, FAIL, SKIP)}
    lines += ["  " + "─" * (w + 58),
              f"  {n[PASS]} passed · {n[WARN]} warnings · {n[FAIL]} failed · {n[SKIP]} skipped", ""]
    if n[FAIL]:
        lines.append("  RESULT: pipeline is broken — see the → lines above.\n")
    elif n[WARN]:
        lines.append("  RESULT: pipeline works. Warnings are limits, not faults.\n")
    else:
        lines.append("  RESULT: fully operational with live Amazon data.\n")
    return "\n".join(lines)
