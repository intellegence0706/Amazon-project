"""Shopify adapter - covers every Shopify-backed retailer with one module.

/products.json is public, paginated, needs no auth, and carries compare_at_price,
which IS the sale signal. No price-history diffing required to detect a discount.
"""
import json

from .base import Adapter, RawProduct, parse_pack_qty
from ..fetcher import FetchError


class ShopifyAdapter(Adapter):
    platform = "shopify"
    PAGE_SIZE = 250          # Shopify's hard maximum

    def __init__(self, host, fetcher, max_pages=None):
        super().__init__(host, fetcher)
        self.max_pages = max_pages

    def products(self):
        page = 1
        while self.max_pages is None or page <= self.max_pages:
            url = (f"https://{self.host}/products.json"
                   f"?limit={self.PAGE_SIZE}&page={page}")
            try:
                batch = json.loads(self.fetcher.get(url)).get("products", [])
            except (FetchError, json.JSONDecodeError):
                return
            if not batch:
                return
            for p in batch:
                yield from self._variants(p)
            page += 1

    def _variants(self, p):
        handle = p.get("handle", "")
        brand = (p.get("vendor") or "").strip() or None
        images = p.get("images") or []
        product_image = images[0].get("src") if images else None
        for v in p.get("variants", []):
            price = _num(v.get("price"))
            # Zero/near-zero rows are gifts-with-purchase and promo placeholders,
            # not sourceable inventory. Found by running against live Brooklinen
            # data, where they surfaced as bogus "100% off" leads.
            if price is None or price < 0.50:
                continue
            list_price = _num(v.get("compare_at_price"))
            # Shopify sets compare_at == price when nothing is discounted.
            if list_price is not None and list_price <= price:
                list_price = None

            title = p.get("title") or ""
            vt = (v.get("title") or "").strip()
            if vt and vt.lower() != "default title":
                title = f"{title} - {vt}"

            # Variant image where one exists, otherwise the product's first.
            vimg = v.get("featured_image") or {}
            image = (vimg.get("src") if isinstance(vimg, dict) else None) or product_image

            yield RawProduct(
                external_id=str(v["id"]),
                title=title,
                price=price,
                list_price=list_price,
                in_stock=bool(v.get("available")),
                brand=brand,
                sku=(v.get("sku") or "").strip() or None,
                upc=(v.get("barcode") or "").strip() or None,
                url=f"https://{self.host}/products/{handle}" if handle else None,
                grams=v.get("grams"),
                image_url=_thumb(image),
                pack_qty=parse_pack_qty(title),
            )


def _thumb(url, width=240):
    """Shopify serves resized variants via a query parameter - ask for a modest
    one rather than shipping full-resolution images into a table view.

    240px covers a 76px thumbnail at 3x device pixel ratio without being large.
    """
    if not url:
        return None
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}width={width}"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
