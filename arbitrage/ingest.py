"""Idempotent ingest: re-running is a no-op unless something actually changed."""
from datetime import datetime, timezone

from .adapters.shopify import ShopifyAdapter
from .fetcher import DirectFetcher

ADAPTERS = {"shopify": ShopifyAdapter}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def register(conn, slug, name, host, platform, tier=1):
    conn.execute(
        """INSERT INTO retailers (slug, name, host, platform, tier)
           VALUES (?,?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET name=excluded.name,
             host=excluded.host, platform=excluded.platform, tier=excluded.tier""",
        (slug, name, host, platform, tier),
    )
    conn.commit()
    return conn.execute("SELECT * FROM retailers WHERE slug=?", (slug,)).fetchone()


def ingest(conn, slug, fetcher=None, max_pages=None):
    r = conn.execute("SELECT * FROM retailers WHERE slug=?", (slug,)).fetchone()
    if r is None:
        raise KeyError(f"unknown retailer: {slug}")

    adapter_cls = ADAPTERS.get(r["platform"])
    if adapter_cls is None:
        raise NotImplementedError(f"no adapter for platform {r['platform']!r}")

    adapter = adapter_cls(r["host"], fetcher or DirectFetcher(), max_pages=max_pages)
    now = _now()
    stats = {"seen": 0, "new": 0, "price_changes": 0, "on_sale": 0}

    for raw in adapter.products():
        stats["seen"] += 1
        if raw.on_sale:
            stats["on_sale"] += 1

        cur = conn.execute(
            "SELECT id FROM products WHERE retailer_id=? AND external_id=?",
            (r["id"], raw.external_id),
        ).fetchone()

        if cur is None:
            pid = conn.execute(
                """INSERT INTO products (retailer_id, external_id, url, title, brand,
                       sku, upc, pack_qty, grams, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], raw.external_id, raw.url, raw.title, raw.brand, raw.sku,
                 raw.upc, raw.pack_qty, raw.grams, now, now),
            ).lastrowid
            stats["new"] += 1
        else:
            pid = cur["id"]
            conn.execute("UPDATE products SET last_seen=?, title=?, brand=? WHERE id=?",
                         (now, raw.title, raw.brand, pid))

        # Only write a snapshot when the observed price actually moved. This is
        # what keeps the table small enough to refresh daily for years.
        last = conn.execute(
            """SELECT price, list_price, in_stock FROM price_snapshots
               WHERE product_id=? ORDER BY captured_at DESC LIMIT 1""",
            (pid,),
        ).fetchone()

        changed = (
            last is None
            or last["price"] != raw.price
            or last["list_price"] != raw.list_price
            or bool(last["in_stock"]) != raw.in_stock
        )
        if changed:
            conn.execute(
                """INSERT INTO price_snapshots
                       (product_id, price, list_price, in_stock, captured_at)
                   VALUES (?,?,?,?,?)""",
                (pid, raw.price, raw.list_price, int(raw.in_stock), now),
            )
            stats["price_changes"] += 1

    conn.commit()
    return stats
