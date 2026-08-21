"""Sort a domain into an acquisition tier.

This is what makes retailer count a config problem instead of an engineering one:
you point it at a list of candidate domains and it tells you which ones hand over
their catalog for free.
"""
import json
from dataclasses import dataclass, asdict

from .fetcher import DirectFetcher, FetchError

TIERS = {
    1: "open catalog  - free, immediate",
    2: "affiliate feed - free, needs approval",
    3: "official API   - free, needs signup",
    4: "protected      - needs paid scraping service",
}


@dataclass
class Fingerprint:
    host: str
    platform: str
    tier: int
    endpoint: str = ""
    note: str = ""

    def __str__(self):
        return f"{self.host:<26} tier {self.tier}  {self.platform:<14} {self.note}"


def probe(host, fetcher=None):
    f = fetcher or DirectFetcher(delay=0.4)

    # 1. Shopify exposes the whole catalog, paginated, no auth.
    try:
        body = f.get(f"https://{host}/products.json?limit=1")
        data = json.loads(body)
        if "products" in data:
            return Fingerprint(host, "shopify", 1,
                               f"https://{host}/products.json",
                               "open catalog, sale flags included")
    except (FetchError, json.JSONDecodeError, ValueError):
        pass

    # 2. WooCommerce Store API is public by design.
    try:
        body = f.get(f"https://{host}/wp-json/wc/store/products?per_page=1")
        if isinstance(json.loads(body), list):
            return Fingerprint(host, "woocommerce", 1,
                               f"https://{host}/wp-json/wc/store/products",
                               "open catalog")
    except (FetchError, json.JSONDecodeError, ValueError):
        pass

    # 3. Anything that refuses a plain homepage GET is behind bot management.
    try:
        f.get(f"https://{host}/")
        return Fingerprint(host, "unknown", 2, "",
                           "reachable - check affiliate feed or JSON-LD")
    except FetchError as e:
        if e.status in (401, 403, 405, 406, 429, 503):
            return Fingerprint(host, "protected", 4, "",
                               f"HTTP {e.status} - use feed or paid API")
        return Fingerprint(host, "unreachable", 4, "", e.reason)


def scan(hosts, fetcher=None):
    return [probe(h, fetcher) for h in hosts]


if __name__ == "__main__":
    import sys
    for fp in scan(sys.argv[1:]):
        print(fp)
