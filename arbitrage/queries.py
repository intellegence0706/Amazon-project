"""Single source of truth for reads.

The CLI, the static report and the API all call these. Previously the report
deduped colourway variants and the CLI did not, so the same pillowcase appeared
twelve times in one surface and once in the other. Shared code makes that class
of drift impossible.
"""
from dataclasses import dataclass, asdict
from typing import Optional

from .economics import evaluate

# Latest snapshot per product, joined to its retailer. Everything reads from this.
_BASE = """
SELECT r.slug AS retailer_slug, r.name AS retailer, p.id AS product_id,
       p.title, p.brand, p.url, p.sku, p.upc, p.pack_qty, p.grams, p.image_url,
       s.price, s.list_price, s.in_stock, s.captured_at,
       ROUND(CAST((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100 AS NUMERIC), 1) AS discount_pct
  FROM products p
  JOIN retailers r ON r.id = p.retailer_id
  JOIN price_snapshots s ON s.id = (
       SELECT id FROM price_snapshots
        WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
"""


@dataclass
class SaleRow:
    retailer: str
    retailer_slug: str
    product_id: int
    title: str
    brand: Optional[str]
    url: Optional[str]
    pack_qty: Optional[int]
    price: float
    list_price: float
    discount_pct: float
    captured_at: str

    def dict(self):
        return asdict(self)


@dataclass
class LeadRow(SaleRow):
    amazon_price: float = 0.0
    net_profit: float = 0.0
    roi_pct: float = 0.0
    margin_pct: float = 0.0
    referral_fee: float = 0.0
    fba_fee: float = 0.0
    flags: tuple = ()
    modelled: bool = True          # False only once real Keepa data is attached


def _dedup(rows):
    """Colourway and size variants share a product URL at the same price.

    Twelve pillowcases in six colours is one sourcing decision, not twelve leads.
    Products without a URL fall back to (retailer, title) so nothing is lost.
    """
    seen, out = set(), []
    for r in rows:
        key = (r["url"] or f"{r['retailer_slug']}:{r['title']}", round(r["price"], 2))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def sales(conn, min_discount=15.0, retailer=None, min_price=0.50,
          max_price=None, in_stock=True, dedup=True, limit=100, offset=0):
    where = ["s.list_price IS NOT NULL", "s.list_price > s.price",
             "s.price >= ?", "((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100) >= ?"]
    args = [min_price, min_discount]
    if in_stock:
        where.append("s.in_stock = 1")
    if retailer:
        where.append("r.slug = ?")
        args.append(retailer)
    if max_price is not None:
        where.append("s.price <= ?")
        args.append(max_price)

    sql = f"{_BASE} WHERE {' AND '.join(where)} ORDER BY discount_pct DESC"
    rows = conn.execute(sql, args).fetchall()
    if dedup:
        rows = _dedup(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return total, [SaleRow(
        retailer=r["retailer"], retailer_slug=r["retailer_slug"],
        product_id=r["product_id"], title=r["title"], brand=r["brand"],
        url=r["url"], pack_qty=r["pack_qty"], price=r["price"],
        list_price=r["list_price"], discount_pct=r["discount_pct"],
        captured_at=r["captured_at"]) for r in page]


def leads(conn, min_roi=30.0, multiplier=0.85, min_discount=15.0, retailer=None,
          min_price=5.0, max_price=200.0, limit=100, offset=0):
    """Model profit for discounted products.

    multiplier stands in for the Amazon price until a Keepa key exists. Every
    LeadRow carries modelled=True so no surface can present these as verified.
    """
    total_sales, rows = sales(conn, min_discount=min_discount, retailer=retailer,
                              min_price=min_price, max_price=max_price,
                              limit=10 ** 9, offset=0)
    out = []
    for s in rows:
        amz = round(s.list_price * multiplier, 2)
        # grams is not carried on SaleRow; re-read it only for the survivors.
        g = conn.execute("SELECT grams FROM products WHERE id=?",
                         (s.product_id,)).fetchone()
        weight = (g["grams"] or 454) / 453.6 if g else 1.0
        ev = evaluate(cost=s.price, sale_price=amz, weight_lb=weight, min_roi=min_roi)
        if ev.roi_pct < min_roi:
            continue
        out.append(LeadRow(
            **s.dict(), amazon_price=amz, net_profit=ev.net_profit,
            roi_pct=ev.roi_pct, margin_pct=ev.margin_pct,
            referral_fee=ev.referral_fee, fba_fee=ev.fba_fee,
            flags=tuple(ev.flags), modelled=True))
    return len(out), out[offset:offset + limit]


def candidates(conn, min_price=5.0, max_price=200.0):
    """The Keepa-token funnel: how few lookups a full catalog actually needs."""
    one = lambda q, a=(): conn.execute(q, a).fetchone()[0]
    total = one("SELECT COUNT(*) FROM products")
    disc, _ = sales(conn, min_discount=0.01, dedup=False, limit=10 ** 9)
    band, _ = sales(conn, min_discount=0.01, min_price=min_price,
                    max_price=max_price, dedup=False, limit=10 ** 9)
    uniq, _ = sales(conn, min_discount=0.01, min_price=min_price,
                    max_price=max_price, dedup=True, limit=10 ** 9)
    pct = lambda n: round(n / total * 100, 1) if total else 0.0
    return {
        "skus_ingested": total,
        "discounted_in_stock": disc, "discounted_pct": pct(disc),
        "within_price_band": band, "band_pct": pct(band),
        "keepa_lookups_needed": uniq, "lookup_pct": pct(uniq),
        "reduction_factor": round(total / uniq, 1) if uniq else None,
    }


def stats(conn):
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "retailers": one("SELECT COUNT(*) FROM retailers"),
        "products": one("SELECT COUNT(*) FROM products"),
        "price_snapshots": one("SELECT COUNT(*) FROM price_snapshots"),
        "amazon_products": one("SELECT COUNT(*) FROM amazon_products"),
        "matches": one("SELECT COUNT(*) FROM matches"),
        "last_scan": one("SELECT MAX(captured_at) FROM price_snapshots"),
    }


def retailers(conn):
    return [dict(r) for r in conn.execute("""
        SELECT r.slug, r.name, r.host, r.platform, r.tier, r.enabled,
               COUNT(p.id) AS products
          FROM retailers r LEFT JOIN products p ON p.retailer_id = r.id
         GROUP BY r.id ORDER BY r.name""")]


def matched_leads(conn, min_roi=30.0, min_profit=0.0, only_auto=True,
                  limit=100, offset=0, settings=None):
    """Leads built from REAL matched Amazon data. modelled=False.

    Separate from leads() on purpose: nothing here is estimated, so these can be
    presented as sourcing decisions rather than a demonstration of the maths.
    """
    from .config import load as load_settings
    cfg = settings or load_settings()
    status = "('auto','confirmed')" if only_auto else "('auto','confirmed','pending')"
    rows = conn.execute(f"""
        SELECT r.name AS retailer, r.slug AS retailer_slug, p.id AS product_id,
               p.title, p.brand, p.url, p.pack_qty, p.grams,
               s.price, s.list_price, s.captured_at,
               ROUND(CAST((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100 AS NUMERIC), 1) AS discount_pct,
               a.asin, a.buybox_price, a.offer_count, a.amazon_on_listing, a.bsr,
               a.fba_fee, a.referral_pct, a.category, m.confidence, m.method
          FROM matches m
          JOIN products p ON p.id = m.product_id
          JOIN retailers r ON r.id = p.retailer_id
          JOIN amazon_products a ON a.asin = m.asin
          JOIN price_snapshots s ON s.id = (
               SELECT id FROM price_snapshots
                WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
         WHERE m.status IN {status} AND a.buybox_price IS NOT NULL
           AND s.in_stock = 1
         ORDER BY m.confidence DESC""").fetchall()

    out = []
    for x in rows:
        override = None
        if x["fba_fee"] is not None and x["referral_pct"] is not None:
            override = {"fba": x["fba_fee"],
                        "referral": round(x["buybox_price"] * x["referral_pct"], 2)}
        ev = evaluate(cost=x["price"], sale_price=x["buybox_price"],
                      weight_lb=(x["grams"] or 454) / 453.6,
                      category=x["category"], bsr=x["bsr"],
                      offer_count=x["offer_count"],
                      amazon_on_listing=bool(x["amazon_on_listing"]),
                      inbound=cfg.inbound_cost, prep=cfg.prep_cost,
                      fee_override=override, max_bsr=cfg.max_bsr, min_roi=min_roi)
        if ev.roi_pct < min_roi or ev.net_profit < min_profit:
            continue
        out.append(LeadRow(
            retailer=x["retailer"], retailer_slug=x["retailer_slug"],
            product_id=x["product_id"], title=x["title"], brand=x["brand"],
            url=x["url"], pack_qty=x["pack_qty"], price=x["price"],
            list_price=x["list_price"], discount_pct=x["discount_pct"],
            captured_at=x["captured_at"], amazon_price=x["buybox_price"],
            net_profit=ev.net_profit, roi_pct=ev.roi_pct, margin_pct=ev.margin_pct,
            referral_fee=ev.referral_fee, fba_fee=ev.fba_fee,
            flags=tuple(ev.flags), modelled=False))
    return len(out), out[offset:offset + limit]


def products(conn, retailer=None, q=None, on_sale=None, in_stock=None,
             min_price=None, max_price=None, limit=100, offset=0):
    """Browse a retailer's full catalog, not just the discounted rows.

    sales() answers "what is on offer"; this answers "what does this shop
    actually stock", which is what you need when judging whether a retailer is
    worth keeping in the list at all.
    """
    where, args = ["1=1"], []
    if retailer:
        where.append("r.slug = ?")
        args.append(retailer)
    if q:
        where.append("(LOWER(p.title) LIKE ? OR LOWER(p.brand) LIKE ?)")
        term = f"%{q.lower()}%"
        args += [term, term]
    if on_sale is True:
        where.append("s.list_price IS NOT NULL AND s.list_price > s.price")
    elif on_sale is False:
        where.append("(s.list_price IS NULL OR s.list_price <= s.price)")
    if in_stock is not None:
        where.append("s.in_stock = ?")
        args.append(1 if in_stock else 0)
    if min_price is not None:
        where.append("s.price >= ?")
        args.append(min_price)
    if max_price is not None:
        where.append("s.price <= ?")
        args.append(max_price)

    clause = " AND ".join(where)
    total = conn.execute(
        f"""SELECT COUNT(*) AS c
              FROM products p
              JOIN retailers r ON r.id = p.retailer_id
              JOIN price_snapshots s ON s.id = (
                   SELECT id FROM price_snapshots
                    WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
             WHERE {clause}""", args).fetchone()["c"]

    rows = conn.execute(
        f"""{_BASE} WHERE {clause}
             ORDER BY discount_pct DESC NULLS LAST, p.title
             LIMIT ? OFFSET ?""", [*args, limit, offset]).fetchall()

    return total, [{
        "product_id": r["product_id"], "retailer": r["retailer"],
        "retailer_slug": r["retailer_slug"], "title": r["title"],
        "brand": r["brand"], "url": r["url"], "sku": r["sku"], "upc": r["upc"],
        "pack_qty": r["pack_qty"], "image_url": r["image_url"], "price": r["price"],
        "list_price": r["list_price"], "in_stock": bool(r["in_stock"]),
        "discount_pct": r["discount_pct"], "captured_at": r["captured_at"],
    } for r in rows]


def price_history(conn, product_id, limit=60):
    """Every recorded price change for one product."""
    return [{
        "price": r["price"], "list_price": r["list_price"],
        "in_stock": bool(r["in_stock"]), "captured_at": r["captured_at"],
    } for r in conn.execute(
        """SELECT price, list_price, in_stock, captured_at
             FROM price_snapshots WHERE product_id = ?
            ORDER BY captured_at DESC LIMIT ?""", (product_id, limit))]
