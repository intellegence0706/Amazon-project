"""Exercise every code path against whichever database is active.

Point it at Supabase and it finds every remaining Postgres incompatibility in
one run, instead of discovering them one at a time through the interface.

    python3 tests/smoke.py                    # local SQLite
    DATABASE_URL='postgres://…' python3 tests/smoke.py    # Supabase
"""
import os
import sys
import pathlib
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from arbitrage import config, db, queries          # noqa: E402

FAILS = []


def case(name, fn):
    try:
        result = fn()
        detail = "" if result is None else str(result)[:58]
        print(f"  ✓ {name:<34} {detail}")
    except Exception as e:                          # noqa: BLE001
        first = str(e).splitlines()[0][:70]
        print(f"  ✗ {name:<34} {type(e).__name__}: {first}")
        FAILS.append((name, traceback.format_exc()))


backend = "Postgres" if db.is_postgres() else "SQLite"
print(f"\nSMOKE TEST — {backend}")
if db.is_postgres():
    print(f"  pooled: {db.pooled()}")
print("─" * 78)

conn = db.init()

print("\nreads")
case("stats", lambda: f"{queries.stats(conn)['products']:,} products")
case("retailers", lambda: f"{len(queries.retailers(conn))} rows")
case("sales (default)", lambda: f"{queries.sales(conn, limit=5)[0]} found")
case("sales (deduped off)", lambda: f"{queries.sales(conn, dedup=False, limit=5)[0]} found")
case("sales (filtered)", lambda: f"{queries.sales(conn, min_discount=50, min_price=5, max_price=200, limit=5)[0]} found")
case("sales (by retailer)", lambda: queries.sales(conn, retailer='vitacost', limit=3)[0])
case("sales (paged)", lambda: len(queries.sales(conn, limit=3, offset=2)[1]))
case("leads (modelled)", lambda: f"{queries.leads(conn, min_roi=50, limit=5)[0]} found")
case("leads (low threshold)", lambda: f"{queries.leads(conn, min_roi=0, limit=3)[0]} found")
case("matched_leads (auto)", lambda: f"{queries.matched_leads(conn, limit=5)[0]} found")
case("matched_leads (pending)", lambda: f"{queries.matched_leads(conn, only_auto=False, limit=5)[0]} found")
case("candidates funnel", lambda: f"{queries.candidates(conn)['keepa_lookups_needed']} lookups")

print("\nrow access (the KeyError: 0 class of bug)")
case("row by name", lambda: conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"])
case("row by position", lambda: conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
case("multi-column row", lambda: conn.execute("SELECT slug, name FROM retailers LIMIT 1").fetchone()[1])
case("empty result is None", lambda: conn.execute("SELECT id FROM products WHERE id = -1").fetchone() is None)

print("\nwrites")
case("insert RETURNING id", lambda: conn.execute(
    "INSERT INTO retailers (slug,name,host,platform,tier) VALUES (?,?,?,?,?) "
    "ON CONFLICT(slug) DO UPDATE SET name=excluded.name RETURNING id",
    ("_smoke", "Smoke Test", "example.invalid", "shopify", 1)).fetchone()["id"])
case("upsert is idempotent", lambda: conn.execute(
    "INSERT INTO retailers (slug,name,host,platform,tier) VALUES (?,?,?,?,?) "
    "ON CONFLICT(slug) DO UPDATE SET name=excluded.name RETURNING id",
    ("_smoke", "Smoke Test 2", "example.invalid", "shopify", 1)).fetchone()["id"])
case("cleanup", lambda: (conn.execute("DELETE FROM retailers WHERE slug=?", ("_smoke",)),
                         conn.commit(), "removed")[2])

print("\nedge cases that differ between backends")
case("divide-by-zero guard", lambda: conn.execute(
    "SELECT ROUND(CAST(1.0 / NULLIF(0, 0) * 100 AS NUMERIC), 1) AS x").fetchone()["x"])
case("ROUND with precision", lambda: conn.execute(
    "SELECT ROUND(CAST(3.14159 AS NUMERIC), 2) AS x").fetchone()["x"])
case("COUNT on empty table", lambda: conn.execute(
    "SELECT COUNT(*) AS c FROM matches").fetchone()["c"])
case("aggregate over no rows", lambda: conn.execute(
    "SELECT MAX(captured_at) AS m FROM price_snapshots WHERE product_id = -1").fetchone()["m"])

print("\nreport generation")
case("render HTML report", lambda: f"{len(__import__('arbitrage.report', fromlist=['render']).render(conn)):,} bytes")

print("\nconfiguration")
case("settings load", lambda: f"min_roi={config.load().min_roi}")
case("keepa configured", lambda: config.load().keepa_configured)

print("\n" + "─" * 78)
if FAILS:
    print(f"  {len(FAILS)} FAILED\n")
    for name, tb in FAILS:
        print(f"── {name} " + "─" * (72 - len(name)))
        print("   " + "\n   ".join(tb.strip().splitlines()[-4:]))
        print()
    sys.exit(1)
print(f"  ALL PASSED on {backend}\n")
