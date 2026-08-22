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
    """Pull a retailer's catalog and record price changes.

    Reads the retailer's existing products and latest prices in TWO queries up
    front, then compares in memory and writes only what changed. The obvious
    per-product SELECT-then-INSERT costs 3-4 round trips per item, which is free
    against a local file and ruinous against a database in another country -
    500 products became minutes rather than seconds.
    """
    r = conn.execute("SELECT * FROM retailers WHERE slug=?", (slug,)).fetchone()
    if r is None:
        raise KeyError(f"unknown retailer: {slug}")

    adapter_cls = ADAPTERS.get(r["platform"])
    if adapter_cls is None:
        raise NotImplementedError(f"no adapter for platform {r['platform']!r}")

    adapter = adapter_cls(r["host"], fetcher or DirectFetcher(), max_pages=max_pages)
    now = _now()
    stats = {"seen": 0, "new": 0, "price_changes": 0, "on_sale": 0}

    # --- one query: every product we already hold for this retailer ---------
    existing = {
        row["external_id"]: row["id"]
        for row in conn.execute(
            "SELECT id, external_id FROM products WHERE retailer_id=?", (r["id"],))
    }

    # --- one query: the most recent snapshot for each of them --------------
    latest = {
        row["product_id"]: (row["price"], row["list_price"], row["in_stock"])
        for row in conn.execute(
            """SELECT s.product_id, s.price, s.list_price, s.in_stock
                 FROM price_snapshots s
                 JOIN products p ON p.id = s.product_id
                WHERE p.retailer_id = ?
                  AND s.id = (SELECT id FROM price_snapshots
                               WHERE product_id = p.id
                               ORDER BY captured_at DESC LIMIT 1)""",
            (r["id"],))
    }

    touched, snapshots, pending_new = [], [], []

    for raw in adapter.products():
        stats["seen"] += 1
        if raw.on_sale:
            stats["on_sale"] += 1

        pid = existing.get(raw.external_id)
        if pid is None:
            # Buffered: inserted in batches once the catalog is fully read.
            pending_new.append(raw)
            stats["new"] += 1
            continue

        touched.append(pid)
        prev = latest.get(pid)
        if _changed(prev, raw):
            snapshots.append((pid, raw.price, raw.list_price, int(raw.in_stock), now))
            stats["price_changes"] += 1

    # --- new products, in batches -----------------------------------------
    if pending_new:
        returned = _insert_many(
            conn, "products",
            ["retailer_id", "external_id", "url", "title", "brand", "sku",
             "upc", "pack_qty", "grams", "first_seen", "last_seen"],
            [(r["id"], p.external_id, p.url, p.title, p.brand, p.sku, p.upc,
              p.pack_qty, p.grams, now, now) for p in pending_new],
            returning="id, external_id")
        # Map by external_id rather than trusting row order.
        new_ids = {row["external_id"]: row["id"] for row in returned}
        by_ext = {p.external_id: p for p in pending_new}
        for ext, pid in new_ids.items():
            raw = by_ext[ext]
            snapshots.append((pid, raw.price, raw.list_price, int(raw.in_stock), now))
            stats["price_changes"] += 1

    # --- price snapshots, in batches --------------------------------------
    if snapshots:
        _insert_many(conn, "price_snapshots",
                     ["product_id", "price", "list_price", "in_stock", "captured_at"],
                     snapshots)
    conn.commit()

    # last_seen is bookkeeping, not data - one statement for the whole batch.
    for chunk in _chunks(touched, 500):
        marks = ",".join("?" * len(chunk))
        conn.execute(
            f"UPDATE products SET last_seen=? WHERE id IN ({marks})",
            [now, *chunk])
    conn.commit()
    return stats


def _changed(prev, raw):
    return (prev is None
            or prev[0] != raw.price
            or prev[1] != raw.list_price
            or bool(prev[2]) != raw.in_stock)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _insert_many(conn, table, columns, rows, returning=None, chunk=400):
    """One statement per chunk, not one per row.

    Multi-row VALUES is portable to SQLite and Postgres alike, and turns N
    network round trips into N/400. Against a remote database that is the whole
    difference between seconds and minutes.

    Chunk size keeps the parameter count well under Postgres' 65535 limit.
    """
    cols = ",".join(columns)
    width = len(columns)
    out = []
    for part in _chunks(rows, chunk):
        values = ",".join(f"({','.join('?' * width)})" for _ in part)
        sql = f"INSERT INTO {table} ({cols}) VALUES {values}"
        if returning:
            sql += f" RETURNING {returning}"
        flat = [v for row in part for v in row]
        cur = conn.execute(sql, flat)
        if returning:
            out.extend(cur.fetchall())
    return out
