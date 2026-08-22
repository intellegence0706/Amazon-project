"""Demo surface. Every command here is something you can show on a screen share."""
import argparse
import csv
import pathlib
import sys

from . import config, db, ingest, matching, queries
from . import verify as _verify
from .keepa import KeepaClient, fixture_client
from .economics import evaluate
from .fingerprint import TIERS, scan


def cmd_fingerprint(a):
    print(f"{'HOST':<26} {'TIER':<6} {'PLATFORM':<14} NOTE")
    print("-" * 88)
    for fp in scan(a.hosts):
        print(fp)
    print("\n" + "\n".join(f"  tier {k}: {v}" for k, v in TIERS.items()))


def cmd_add(a):
    conn = db.init()
    r = ingest.register(conn, a.slug, a.name or a.slug, a.host, a.platform, a.tier)
    print(f"registered #{r['id']} {r['slug']} ({r['platform']}, tier {r['tier']})")


def cmd_ingest(a):
    conn = db.init()
    s = ingest.ingest(conn, a.slug, max_pages=a.pages)
    print(f"{a.slug}: {s['seen']} variants  {s['new']} new  "
          f"{s['price_changes']} price changes  {s['on_sale']} on sale")


def cmd_sales(a):
    conn = db.init()
    rows = conn.execute(
        """SELECT r.name AS retailer, p.title, p.brand, p.pack_qty, p.url,
                  s.price, s.list_price,
                  ROUND(CAST((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100 AS NUMERIC), 1) AS disc
             FROM products p
             JOIN retailers r ON r.id = p.retailer_id
             JOIN price_snapshots s ON s.id = (
                  SELECT id FROM price_snapshots
                   WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
            WHERE s.list_price IS NOT NULL
              AND s.list_price > s.price
              AND s.price >= 0.50
              AND s.in_stock = 1
              AND ((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100) >= ?
            ORDER BY disc DESC LIMIT ?""",
        (a.min_discount, a.limit),
    ).fetchall()

    if a.csv:
        w = csv.writer(sys.stdout)
        w.writerow(["retailer", "brand", "title", "pack_qty", "price", "was", "discount_pct", "url"])
        for x in rows:
            w.writerow([x["retailer"], x["brand"], x["title"], x["pack_qty"],
                        x["price"], x["list_price"], x["disc"], x["url"]])
        return

    print(f"{'DISC':>6}  {'NOW':>8}  {'WAS':>8}  {'PACK':>5}  BRAND / PRODUCT")
    print("-" * 96)
    for x in rows:
        pack = x["pack_qty"] if x["pack_qty"] else "-"
        print(f"{x['disc']:>5.0f}%  ${x['price']:>7.2f}  ${x['list_price']:>7.2f}  "
              f"{str(pack):>5}  {(x['brand'] or '?')[:18]:<18} {x['title'][:44]}")
    print(f"\n{len(rows)} discounted products in stock")


def cmd_leads(a):
    """Model ROI against a hypothetical Amazon price.

    Real Amazon prices arrive with a Keepa key; --multiplier exists so the whole
    pipeline is demonstrable before that key is purchased.
    """
    conn = db.init()
    rows = conn.execute(
        """SELECT p.title, p.brand, p.grams, s.price, s.list_price
             FROM products p
             JOIN price_snapshots s ON s.id = (
                  SELECT id FROM price_snapshots
                   WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
            WHERE s.in_stock = 1 AND s.list_price > s.price
            ORDER BY (s.list_price - s.price) / s.list_price DESC LIMIT ?""",
        (a.limit,),
    ).fetchall()

    print(f"{'ROI':>7} {'NET':>8} {'COST':>8} {'AMZ':>8}  PRODUCT")
    print("-" * 96)
    kept = 0
    for x in rows:
        weight = (x["grams"] or 454) / 453.6
        amz = round(x["list_price"] * a.multiplier, 2)
        lead = evaluate(cost=x["price"], sale_price=amz, weight_lb=weight,
                        min_roi=a.min_roi)
        if lead.roi_pct < a.min_roi:
            continue
        kept += 1
        print(f"{lead.roi_pct:>6.1f}% ${lead.net_profit:>7.2f} ${lead.cost:>7.2f} "
              f"${amz:>7.2f}  {(x['brand'] or '?')[:16]:<16} {x['title'][:40]}")
    print(f"\n{kept} leads at or above {a.min_roi}% ROI")
    print("NOTE: Amazon price modelled at list x %.2f - replace with Keepa data." % a.multiplier)


def cmd_preflight(a):
    """Check everything a deployment needs, before deploying."""
    from . import preflight
    checks = preflight.run()
    print(preflight.report(checks))
    return 1 if any(c.status == "FAIL" for c in checks) else 0


def cmd_migrate(a):
    """Copy the local database into hosted Postgres for deployment."""
    from . import migrate
    try:
        totals = migrate.run(batch=a.batch)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"\n{e}\n")
        return 1
    print("\n  migrated:")
    for t, n in totals.items():
        print(f"    {t:<18} {n:>7,}")
    print()


def cmd_ui(a):
    """Start the engine and open the interface. One command, one URL."""
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{a.port}"
    ui_built = (pathlib.Path(__file__).resolve().parent.parent / "web" / "out").is_dir()

    print(f"\n  Sourcing Engine")
    print(f"  {'─' * 44}")
    print(f"   Interface   {url}")
    print(f"   API docs    {url}/docs")
    if not ui_built:
        print("\n   Interface not built yet. Run:")
        print("     cd web && npm install && npm run build")
    print(f"  {'─' * 44}\n")

    if ui_built and not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("arbitrage.web.api:app", host="127.0.0.1", port=a.port,
                log_level="warning")


def cmd_match(a):
    """Match discounted products to Amazon ASINs."""
    conn = db.init()
    cfg = config.load()
    if cfg.keepa_configured:
        client = KeepaClient(cfg.keepa_api_key, cfg.keepa_domain)
        print("using live Keepa API")
    else:
        client = fixture_client(cfg.keepa_domain)
        print("NO KEEPA KEY — simulation mode, matches are not real\n")

    def show(title, m):
        mark = {"auto": "✓", "pending": "?", "rejected": "✗"}[m.status]
        print(f"  {mark} {m.confidence:>5.2f} {m.method:<6} {title[:52]}")
        if m.status == "rejected":
            print(f"            └ {m.reasons[0]}")

    st = matching.run(conn, client, limit=a.limit, min_discount=a.min_discount,
                      progress=show)
    print(f"\n  attempted {st['attempted']} · auto {st['auto']} · "
          f"review {st['pending']} · rejected {st['rejected']} · "
          f"no candidate {st['no_candidate']} · errors {st['errors']}")


def cmd_real(a):
    """Leads from real matched Amazon data."""
    conn = db.init()
    n, rows = queries.matched_leads(conn, min_roi=a.min_roi, limit=a.limit)
    if not n:
        print("No matched leads yet. Run: arbitrage match  (needs a Keepa key)")
        return
    print(f"{'ROI':>7} {'NET':>8} {'COST':>8} {'AMZ':>8} {'BSR':>9}  PRODUCT")
    print("-" * 96)
    for r in rows:
        print(f"{r.roi_pct:>6.1f}% ${r.net_profit:>7.2f} ${r.price:>7.2f} "
              f"${r.amazon_price:>7.2f} {'':>9}  {r.title[:40]}")
    print(f"\n{n} verified leads (real Amazon data)")


def cmd_verify(a):
    checks = _verify.run(live_network=not a.offline)
    print(_verify.report(checks))
    return 1 if any(c.status == _verify.FAIL for c in checks) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="arbitrage")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fingerprint", help="sort domains into acquisition tiers")
    p.add_argument("hosts", nargs="+")
    p.set_defaults(fn=cmd_fingerprint)

    p = sub.add_parser("add", help="register a retailer")
    p.add_argument("slug"); p.add_argument("host")
    p.add_argument("--name"); p.add_argument("--platform", default="shopify")
    p.add_argument("--tier", type=int, default=1)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("ingest", help="pull catalog + record price changes")
    p.add_argument("slug"); p.add_argument("--pages", type=int, default=None)
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("sales", help="products currently discounted")
    p.add_argument("--min-discount", type=float, default=20.0)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(fn=cmd_sales)

    p = sub.add_parser("leads", help="model profit / ROI")
    p.add_argument("--min-roi", type=float, default=30.0)
    p.add_argument("--multiplier", type=float, default=1.0)
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(fn=cmd_leads)

    p = sub.add_parser("preflight", help="check readiness before deploying")
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser("migrate", help="copy local data into hosted Postgres")
    p.add_argument("--batch", type=int, default=500)
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("ui", help="start the engine and open the interface")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_ui)

    p = sub.add_parser("match", help="match discounted products to Amazon ASINs")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--min-discount", type=float, default=15.0)
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("real", help="leads from real matched Amazon data")
    p.add_argument("--min-roi", type=float, default=30.0)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_real)

    p = sub.add_parser("verify", help="self-test the whole pipeline")
    p.add_argument("--offline", action="store_true", help="skip network checks")
    p.set_defaults(fn=cmd_verify)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    main()
