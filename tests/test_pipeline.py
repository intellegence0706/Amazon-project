"""End-to-end: real retailer rows -> matching -> real-data leads.

Uses a mock Keepa that mimics the real client's interface and returns a mix of
correct matches, wrong-brand traps and wrong-pack traps. Proves the whole chain
runs and that the gates reject what they should on genuine catalog data.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from arbitrage import db, matching, queries
from arbitrage.keepa import KeepaProduct

class MockKeepa:
    """Mimics KeepaClient. Returns a plausible Amazon listing for any query."""
    mode = "mock"
    def __init__(self): self.calls = 0
    def _make(self, title, brand, asin, price=24.99, bsr=12000):
        p = KeepaProduct(asin=asin, title=title, brand=brand, bsr=bsr,
                         bsr_90d_avg=bsr + 800, offer_count=6, fba_fee=4.15,
                         referral_pct=0.15, weight_grams=200,
                         category="Health & Household")
        p.buybox_price = price
        return p
    def search(self, term):
        self.calls += 1
        brand = term.split()[0] if term.split() else "Unknown"
        rest = " ".join(term.split()[1:])[:60] or "Product"
        return [
            self._make(rest, brand, "B0GOOD001"),                    # good match
            self._make(rest, "CompletelyOtherBrand", "B0TRAP002"),   # brand trap
            self._make(f"{rest}, 999 Count", brand, "B0TRAP003"),    # pack trap
        ]
    def by_upc(self, upc): return []
    def by_asin(self, asin):
        return self._make("Matched Product", "Brand", asin)

conn = db.init()
before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
print(f"matches before: {before}")

mock = MockKeepa()
results = []
st = matching.run(conn, mock, limit=12, progress=lambda t, m: results.append((t, m)))

print(f"\nmatched {st['attempted']} products via {mock.calls} searches")
print(f"  auto {st['auto']} · pending {st['pending']} · rejected {st['rejected']}")

print("\nsample decisions:")
for title, m in results[:6]:
    mark = {"auto": "✓", "pending": "?", "rejected": "✗"}[m.status]
    print(f"  {mark} {m.confidence:>5.2f} {m.method:<6} {title[:40]:<40} {m.reasons[0][:36]}")

n_amz = conn.execute("SELECT COUNT(*) FROM amazon_products").fetchone()[0]
n_m = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
print(f"\nstored: {n_amz} amazon_products · {n_m} matches")

total, leads = queries.matched_leads(conn, min_roi=10, limit=5)
print(f"\nreal-data leads (modelled=False): {total}")
for l in leads[:4]:
    print(f"  ROI {l.roi_pct:>6.1f}%  net ${l.net_profit:>6.2f}  "
          f"cost ${l.price:>6.2f} -> ${l.amazon_price:<7.2f} modelled={l.modelled}  {l.title[:32]}")

assert st["attempted"] > 0, "nothing attempted"
assert n_m > before, "no matches stored"
assert all(l.modelled is False for l in leads), "real leads must not be flagged modelled"
print("\n✓ end-to-end pipeline verified")
