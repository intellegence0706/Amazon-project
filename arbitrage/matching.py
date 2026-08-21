"""Retailer product -> Amazon ASIN.

The most dangerous module here. A false match produces a confident, beautiful ROI
figure for inventory that cannot be sold at that price - the seller loses real
money and blames the tool. So this errs hard toward refusing to match.

Design rules:
  * Hard gates reject outright. Brand mismatch or pack-size mismatch is not a
    low score, it is a no.
  * Unknown pack size CAPS confidence below auto-accept. Unknown is not innocent.
  * Everything scoring-related is pure and offline-testable. Only candidate
    lookup touches the network, so the risky logic is fully covered by tests.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import List, Optional

from .adapters.base import parse_pack_qty
from .keepa import KeepaClient, KeepaError, KeepaProduct

AUTO_ACCEPT = 0.90     # store as 'auto'    - trusted
REVIEW_FLOOR = 0.70    # store as 'pending' - human confirms
UNKNOWN_PACK_CAP = 0.85  # below AUTO_ACCEPT by design

_NOISE = re.compile(
    r"\b(the|and|with|for|new|pack|of|by|size|ct|count|oz|fl|ml|g|kg|lb|lbs|"
    r"free|shipping|value|bonus|pk|each|ea)\b", re.I)
_NONWORD = re.compile(r"[^a-z0-9 ]+")


def normalize_gtin(code) -> Optional[str]:
    """UPC-A / EAN-13 / GTIN-14 -> 14-digit GTIN so codes compare correctly."""
    if not code:
        return None
    d = re.sub(r"\D", "", str(code))
    if len(d) not in (8, 12, 13, 14):
        return None
    return d.zfill(14)


def gtin_valid(code) -> bool:
    """Mod-10 check digit. Catches typos and truncated codes before a lookup."""
    g = normalize_gtin(code)
    if not g:
        return False
    body, check = g[:-1], int(g[-1])
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(body))
    return (10 - total % 10) % 10 == check


def norm_text(s) -> str:
    s = _NONWORD.sub(" ", (s or "").lower())
    return re.sub(r"\s+", " ", _NOISE.sub(" ", s)).strip()


def tokens(s) -> set:
    return {t for t in norm_text(s).split() if len(t) > 1}


def title_similarity(a, b) -> float:
    """Token overlap blended with sequence ratio - neither alone is enough."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()
    return round(0.6 * jaccard + 0.4 * seq, 3)


def brand_match(a, b) -> Optional[bool]:
    """None when either side is unknown - absent is not the same as different."""
    if not a or not b:
        return None
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return None
    return na == nb or na in nb or nb in na


@dataclass
class MatchResult:
    asin: str
    confidence: float
    method: str                 # upc | fuzzy
    status: str                 # auto | pending | rejected
    reasons: List[str]

    @property
    def usable(self) -> bool:
        return self.status in ("auto", "confirmed")


def score(retail_title, retail_brand, retail_pack, amz: KeepaProduct,
          method="fuzzy") -> MatchResult:
    """Pure scoring. No network, no database - exhaustively testable."""
    reasons = []

    # --- hard gate: brand -------------------------------------------------
    bm = brand_match(retail_brand, amz.brand)
    if bm is False:
        return MatchResult(amz.asin, 0.0, method, "rejected",
                           [f"brand mismatch: {retail_brand!r} vs {amz.brand!r}"])
    if bm is True:
        reasons.append("brand matches")
    else:
        reasons.append("brand unknown on one side")

    # --- hard gate: pack size ---------------------------------------------
    amz_pack = parse_pack_qty(amz.title)
    if retail_pack and amz_pack and retail_pack != amz_pack:
        return MatchResult(amz.asin, 0.0, method, "rejected",
                           [f"pack mismatch: {retail_pack} vs {amz_pack}"])

    sim = title_similarity(retail_title, amz.title)
    conf = sim
    if bm is True:
        conf = min(1.0, conf + 0.15)
    if retail_pack and amz_pack and retail_pack == amz_pack:
        conf = min(1.0, conf + 0.10)
        reasons.append(f"pack size matches ({retail_pack})")

    # UPC lookups are near-certain: Keepa resolved the exact barcode.
    if method == "upc":
        conf = max(conf, 0.95)
        reasons.append("matched on UPC")

    # --- unknown pack caps confidence -------------------------------------
    if method != "upc" and (retail_pack is None or amz_pack is None):
        if conf > UNKNOWN_PACK_CAP:
            conf = UNKNOWN_PACK_CAP
        reasons.append("pack size unknown — capped below auto-accept")

    reasons.append(f"title similarity {sim}")
    conf = round(conf, 3)
    status = ("auto" if conf >= AUTO_ACCEPT else
              "pending" if conf >= REVIEW_FLOOR else "rejected")
    return MatchResult(amz.asin, conf, method, status, reasons)


def find_match(product: dict, client: KeepaClient) -> Optional[MatchResult]:
    """UPC first, fall back to keyword search. Returns the best candidate."""
    title, brand = product.get("title"), product.get("brand")
    pack = product.get("pack_qty") or parse_pack_qty(title)

    upc = product.get("upc")
    if upc and gtin_valid(upc):
        try:
            for p in client.by_upc(upc):
                r = score(title, brand, pack, p, method="upc")
                if r.status != "rejected":
                    return r
        except KeepaError:
            pass

    try:
        cands = client.search(f"{brand or ''} {title}".strip())
    except (KeepaError, AttributeError):
        return None

    best = None
    for p in cands[:10]:
        r = score(title, brand, pack, p, method="fuzzy")
        if best is None or r.confidence > best.confidence:
            best = r
    return best


def store(conn, product_id: int, amz: KeepaProduct, m: MatchResult):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("""
        INSERT INTO amazon_products (asin,title,brand,upc,buybox_price,offer_count,
            amazon_on_listing,bsr,category,fba_fee,referral_pct,refreshed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(asin) DO UPDATE SET
            buybox_price=excluded.buybox_price, offer_count=excluded.offer_count,
            amazon_on_listing=excluded.amazon_on_listing, bsr=excluded.bsr,
            fba_fee=excluded.fba_fee, referral_pct=excluded.referral_pct,
            refreshed_at=excluded.refreshed_at""",
        (amz.asin, amz.title, amz.brand, amz.upcs[0] if amz.upcs else None,
         amz.sale_price, amz.offer_count, int(amz.amazon_on_listing), amz.bsr,
         amz.category, amz.fba_fee, amz.referral_pct, now))
    conn.execute("""
        INSERT INTO matches (product_id,asin,confidence,method,status,created_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(product_id,asin) DO UPDATE SET
            confidence=excluded.confidence, status=excluded.status""",
        (product_id, amz.asin, m.confidence, m.method, m.status, now))
    conn.commit()


def run(conn, client: KeepaClient, limit=50, min_discount=15.0,
        min_price=5.0, max_price=200.0, progress=None):
    """Match the candidate funnel against Amazon.

    Only discounted, in-stock, in-band, deduped products reach here - roughly
    1 in 12 of the catalog - because every call costs Keepa tokens.
    """
    from . import queries
    _, rows = queries.sales(conn, min_discount=min_discount, min_price=min_price,
                            max_price=max_price, dedup=True, limit=limit)
    stats = {"attempted": 0, "auto": 0, "pending": 0, "rejected": 0,
             "no_candidate": 0, "errors": 0}

    for s in rows:
        stats["attempted"] += 1
        p = conn.execute("SELECT upc, pack_qty FROM products WHERE id=?",
                         (s.product_id,)).fetchone()
        product = {"title": s.title, "brand": s.brand,
                   "upc": p["upc"] if p else None,
                   "pack_qty": s.pack_qty or (p["pack_qty"] if p else None)}
        try:
            m = find_match(product, client)
        except KeepaError:
            stats["errors"] += 1
            continue
        if m is None:
            stats["no_candidate"] += 1
            continue
        stats[m.status if m.status in stats else "rejected"] += 1
        if m.status != "rejected":
            amz = client.by_asin(m.asin)
            if amz:
                store(conn, s.product_id, amz, m)
        if progress:
            progress(s.title, m)
    return stats
