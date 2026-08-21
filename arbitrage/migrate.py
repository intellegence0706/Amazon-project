"""Copy the local SQLite database into a hosted Postgres.

Deployment needs the data somewhere serverless functions can reach. Ingestion is
too slow to run inside a serverless request, so the pattern is: scan locally (or
on a scheduled worker), then push here.

    DATABASE_URL=postgres://... python3 -m arbitrage.cli migrate
"""
import os
import sqlite3
from pathlib import Path

from . import db

TABLES = [
    ("retailers", "slug,name,host,platform,tier,enabled"),
    ("products", "retailer_id,external_id,url,title,brand,sku,upc,pack_qty,"
                 "grams,first_seen,last_seen"),
    ("price_snapshots", "product_id,price,list_price,in_stock,captured_at"),
    ("amazon_products", "asin,title,brand,upc,buybox_price,offer_count,"
                        "amazon_on_listing,bsr,category,fba_fee,referral_pct,refreshed_at"),
    ("matches", "product_id,asin,confidence,method,status,created_at"),
]

CONFLICT = {
    "retailers": "(slug)",
    "products": "(retailer_id, external_id)",
    "amazon_products": "(asin)",
    "matches": "(product_id, asin)",
    "price_snapshots": None,          # append-only, no natural key
}


def run(sqlite_path=db.DB_PATH, batch=500, progress=print):
    if not db.is_postgres():
        raise RuntimeError(
            "DATABASE_URL is not set to a Postgres connection string.\n"
            "Create a free database (Neon, Supabase or Vercel Postgres), then:\n"
            "  DATABASE_URL=postgres://... python3 -m arbitrage.cli migrate")
    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"no local database at {sqlite_path}")

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    dst = db.init()

    # products.retailer_id and friends reference IDs that Postgres assigns fresh,
    # so remap as we go rather than trusting the source IDs.
    id_map = {"retailers": {}, "products": {}}
    totals = {}

    for table, cols in TABLES:
        names = cols.split(",")
        rows = src.execute(f"SELECT id, {cols} FROM {table}").fetchall()
        moved = 0

        for i in range(0, len(rows), batch):
            for r in rows[i:i + batch]:
                vals = []
                for c in names:
                    v = r[c]
                    if c == "retailer_id":
                        v = id_map["retailers"].get(v, v)
                    elif c == "product_id":
                        v = id_map["products"].get(v, v)
                    vals.append(v)

                ph = ",".join("?" * len(names))
                conflict = CONFLICT.get(table)
                sql = f"INSERT INTO {table} ({cols}) VALUES ({ph})"
                if conflict:
                    sql += f" ON CONFLICT {conflict} DO NOTHING"
                if table in id_map:
                    sql += " RETURNING id"

                cur = dst.execute(sql, vals)
                if table in id_map:
                    got = cur.fetchone()
                    if got is not None:
                        new_id = got["id"] if isinstance(got, dict) else got[0]
                        id_map[table][r["id"]] = new_id
                moved += 1
            dst.commit()
            progress(f"  {table}: {min(i + batch, len(rows))}/{len(rows)}")

        totals[table] = moved

    dst.commit()
    src.close()
    return totals
