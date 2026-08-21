"""Keepa API client.

Two modes:

  live     - real API calls, needs a key
  fixture  - replays a recorded response, needs nothing

Fixture mode exists because the person who has the key is not the person writing
the code. It lets the entire matching -> pricing -> ROI chain be exercised and
tested offline, so what ships has actually run.

FIELD NAMES AND CSV INDICES BELOW FOLLOW KEEPA'S DOCUMENTED FORMAT. Verify them
against the current docs before trusting live output - the parser is deliberately
defensive so a renamed field degrades to None rather than crashing.
"""
import json
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

from .fetcher import DirectFetcher, FetchError

BASE = "https://api.keepa.com"

# Keepa packs history into csv[] arrays. Index = data type.
CSV_AMAZON, CSV_NEW, CSV_SALES_RANK = 0, 1, 3
CSV_NEW_FBA, CSV_COUNT_NEW, CSV_BUYBOX = 10, 11, 18

# Keepa returns prices in cents, and uses -1 to mean "no data".
def _price(v) -> Optional[float]:
    if v is None or v < 0:
        return None
    return round(v / 100.0, 2)


def _rank(v) -> Optional[int]:
    return None if v is None or v < 0 else int(v)


@dataclass
class KeepaProduct:
    asin: str
    title: Optional[str] = None
    brand: Optional[str] = None
    upcs: List[str] = field(default_factory=list)
    category: Optional[str] = None
    buybox_price: Optional[float] = None
    amazon_price: Optional[float] = None
    new_price: Optional[float] = None
    offer_count: Optional[int] = None
    amazon_on_listing: bool = False
    bsr: Optional[int] = None
    bsr_90d_avg: Optional[int] = None
    fba_fee: Optional[float] = None
    referral_pct: Optional[float] = None
    weight_grams: Optional[int] = None

    @property
    def sale_price(self) -> Optional[float]:
        """What you would realistically sell at: Buy Box, else lowest new."""
        return self.buybox_price or self.new_price or self.amazon_price

    @property
    def has_rank_history(self) -> bool:
        return self.bsr_90d_avg is not None


class KeepaError(RuntimeError):
    pass


def parse_product(p: dict) -> KeepaProduct:
    """Defensive parse - every field optional, nothing raises on a missing key."""
    stats = p.get("stats") or {}
    cur = stats.get("current") or []
    avg90 = stats.get("avg90") or []

    def at(arr, i):
        return arr[i] if isinstance(arr, list) and len(arr) > i else None

    fba = (p.get("fbaFees") or {}).get("pickAndPackFee")
    ref = p.get("referralFeePercent", p.get("referralFeePercentage"))

    return KeepaProduct(
        asin=p.get("asin", ""),
        title=p.get("title"),
        brand=p.get("brand"),
        upcs=[str(u) for u in (p.get("upcList") or []) if u],
        category=p.get("categoryTree", [{}])[-1].get("name")
                 if p.get("categoryTree") else None,
        buybox_price=_price(at(cur, CSV_BUYBOX)),
        amazon_price=_price(at(cur, CSV_AMAZON)),
        new_price=_price(at(cur, CSV_NEW_FBA)) or _price(at(cur, CSV_NEW)),
        offer_count=_rank(at(cur, CSV_COUNT_NEW)),
        amazon_on_listing=_price(at(cur, CSV_AMAZON)) is not None,
        bsr=_rank(at(cur, CSV_SALES_RANK)),
        bsr_90d_avg=_rank(at(avg90, CSV_SALES_RANK)),
        fba_fee=_price(fba) if fba is not None else None,
        referral_pct=(ref / 100.0) if isinstance(ref, (int, float)) else None,
        weight_grams=p.get("packageWeight") if p.get("packageWeight", 0) > 0 else None,
    )


class KeepaClient:
    def __init__(self, api_key=None, domain=1, fetcher=None, fixture=None):
        self.api_key, self.domain = api_key, domain
        self.fetcher = fetcher or DirectFetcher(delay=0.25)
        self.fixture = fixture          # dict -> replay instead of calling out
        self.tokens_left: Optional[int] = None

    @property
    def mode(self):
        return "fixture" if self.fixture is not None else "live"

    def _call(self, path, **params):
        if self.fixture is not None:
            return self.fixture
        if not self.api_key:
            raise KeepaError("no API key configured")
        params = {"key": self.api_key, "domain": self.domain, **params}
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        try:
            data = json.loads(self.fetcher.get(url))
        except FetchError as e:
            if e.status == 429:
                raise KeepaError("Keepa rate limit / out of tokens") from e
            raise KeepaError(f"Keepa request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise KeepaError("Keepa returned a non-JSON response") from e
        if isinstance(data, dict):
            self.tokens_left = data.get("tokensLeft", self.tokens_left)
            if data.get("error"):
                raise KeepaError(str(data["error"]))
        return data

    def tokens(self) -> Optional[int]:
        """Cheap key validity check - costs no product tokens."""
        data = self._call("token")
        return data.get("tokensLeft")

    def by_asin(self, asin, stats_days=90) -> Optional[KeepaProduct]:
        data = self._call("product", asin=asin, stats=stats_days, buybox=1)
        items = data.get("products") or []
        return parse_product(items[0]) if items else None

    def search(self, term, stats_days=90) -> List[KeepaProduct]:
        """Keyword search - candidate generation for fuzzy matching.

        Costs more tokens than an ASIN lookup, so the funnel filters hard before
        anything reaches here.
        """
        data = self._call("search", type="product", term=term, stats=stats_days)
        return [parse_product(p) for p in (data.get("products") or [])]

    def by_upc(self, upc, stats_days=90) -> List[KeepaProduct]:
        """UPC/EAN lookup - the high-precision matching path."""
        data = self._call("product", code=str(upc).strip(), stats=stats_days, buybox=1)
        return [parse_product(p) for p in (data.get("products") or [])]


# A recorded-shape response so the full chain runs with no key and no network.
FIXTURE = {
    "tokensLeft": 1200,
    "refillRate": 20,
    "products": [{
        "asin": "B00EXAMPLE1",
        "title": "Example Brand Vitamin D3 5000 IU, 240 Softgels",
        "brand": "Example Brand",
        "upcList": ["012345678905"],
        "categoryTree": [{"name": "Health & Household"}, {"name": "Vitamins"}],
        "packageWeight": 181,
        "fbaFees": {"pickAndPackFee": 415},
        "referralFeePercent": 15,
        "stats": {
            # index:            0     1    2     3       ...        10    11   ...   18
            "current": [1899, 1749, -1, 8432, -1, -1, -1, -1, -1, -1, 1799, 7, -1,
                        -1, -1, -1, -1, -1, 1799],
            "avg90":   [1999, 1849, -1, 9110, -1, -1, -1, -1, -1, -1, 1899, 9, -1,
                        -1, -1, -1, -1, -1, 1879],
        },
    }],
}


def fixture_client(domain=1) -> KeepaClient:
    return KeepaClient(api_key=None, domain=domain, fixture=FIXTURE)
