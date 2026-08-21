"""One adapter per PLATFORM, not per retailer.

Adding a retailer that runs a platform you already support is an INSERT, not a
new module. That is the whole scaling argument: 6 adapters cover hundreds of
stores, and a platform-level fix repairs every retailer on it at once.
"""
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class RawProduct:
    external_id: str
    title: str
    price: float
    list_price: Optional[float] = None   # > price means on sale
    in_stock: bool = True
    brand: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    url: Optional[str] = None
    grams: Optional[int] = None
    pack_qty: Optional[int] = field(default=None)

    @property
    def on_sale(self) -> bool:
        return bool(self.list_price and self.list_price > self.price)

    @property
    def discount_pct(self) -> float:
        if not self.on_sale:
            return 0.0
        return round((self.list_price - self.price) / self.list_price * 100, 1)


# Pack quantity is a hard gate in matching: a 6-pack at the retailer matched to a
# single unit on Amazon produces a beautiful fake ROI and dead inventory. If we
# cannot read it confidently we leave it None and refuse to auto-accept later.
_PACK = re.compile(
    r"\b(\d{1,4})\s*(?:x\s*)?"
    r"(count|ct|pack|pk|tablets?|capsules?|caps|softgels?|veg\s*caps?|"
    r"gummies|bags?|bars?|packets?|servings?|wipes?|sheets?|rolls?)\b",
    re.I,
)


def parse_pack_qty(title: str) -> Optional[int]:
    m = _PACK.search(title or "")
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if 1 <= n <= 5000 else None


class Adapter:
    platform = "base"

    def __init__(self, host: str, fetcher):
        self.host, self.fetcher = host, fetcher

    def products(self) -> Iterator[RawProduct]:
        raise NotImplementedError
