"""Tests for the matching engine.

This logic decides whether someone spends money on inventory, and it will run
against a live Keepa key that the author never had access to. So the scoring is
pure and covered here exhaustively - the failure modes are tested, not assumed.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from arbitrage.keepa import KeepaProduct
from arbitrage.matching import (gtin_valid, normalize_gtin, brand_match,
                                title_similarity, score, AUTO_ACCEPT)

def amz(title, brand=None, asin="B0TEST"):
    return KeepaProduct(asin=asin, title=title, brand=brand)

FAILS = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond: FAILS.append(name)

print("\nGTIN normalisation")
check("UPC-A pads to 14", normalize_gtin("012345678905") == "00012345678905")
check("strips non-digits", normalize_gtin("0-12345-67890-5") == "00012345678905")
check("rejects garbage", normalize_gtin("abc") is None)
check("rejects wrong length", normalize_gtin("12345") is None)
check("valid check digit accepted", gtin_valid("012345678905"))
check("bad check digit rejected", not gtin_valid("012345678900"))

print("\nBrand gate")
check("exact match", brand_match("Swanson", "swanson") is True)
check("substring match", brand_match("Swanson", "Swanson Health") is True)
check("different brands", brand_match("Swanson", "NOW Foods") is False)
check("unknown is None not False", brand_match(None, "Swanson") is None)

print("\nTitle similarity")
check("identical is 1.0", title_similarity("Vitamin D3 5000 IU", "Vitamin D3 5000 IU") == 1.0)
check("unrelated is low", title_similarity("Vitamin D3", "Garden Hose 50ft") < 0.3)
check("near-identical is high", title_similarity(
    "Vitamin D3 5000 IU 240 Softgels", "Vitamin D-3 5000IU, 240 Softgels") > 0.5)

print("\nHARD GATE — brand mismatch must reject")
r = score("Vitamin D3 5000 IU", "Swanson", None, amz("Vitamin D3 5000 IU", "NOW Foods"))
check("rejected outright", r.status == "rejected", f"got {r.status} @ {r.confidence}")
check("confidence zero", r.confidence == 0.0)

print("\nHARD GATE — pack mismatch must reject (the expensive mistake)")
r = score("Vitamin D3, 60 Softgels", "Swanson", 60, amz("Vitamin D3, 240 Softgels", "Swanson"))
check("6-pack vs single rejected", r.status == "rejected", f"got {r.status} @ {r.confidence}")
r = score("Tea Bags, 20 Count", "Twinings", 20, amz("Tea Bags, 100 Count", "Twinings"))
check("20ct vs 100ct rejected", r.status == "rejected")

print("\nUnknown pack size caps below auto-accept")
r = score("Widget Deluxe Edition", "Acme", None, amz("Widget Deluxe Edition", "Acme"))
check("not auto-accepted", r.confidence < AUTO_ACCEPT, f"confidence {r.confidence}")
check("still reviewable", r.status == "pending", f"got {r.status}")
check("reason recorded", any("pack size unknown" in x for x in r.reasons))

print("\nGood matches are accepted")
r = score("Vitamin D3 5000 IU, 240 Softgels", "Swanson", 240,
          amz("Vitamin D3 5000 IU, 240 Softgels", "Swanson"))
check("auto-accepted", r.status == "auto", f"got {r.status} @ {r.confidence}")
check("high confidence", r.confidence >= AUTO_ACCEPT)

print("\nUPC matches trusted")
r = score("Some Product", "BrandA", None, amz("Some Product Variant", "BrandA"), method="upc")
check("auto via UPC", r.status == "auto", f"got {r.status} @ {r.confidence}")
check("method recorded", r.method == "upc")

print("\nUPC does NOT override a hard gate")
r = score("Widget", "Swanson", None, amz("Widget", "NOW Foods"), method="upc")
check("brand gate still rejects", r.status == "rejected")

print("\nJunk does not match")
r = score("Garden Hose 50ft", "Acme", None, amz("Vitamin D3 5000 IU", "Swanson"))
check("rejected", r.status == "rejected")

print("\n" + "="*54)
print(f"  {'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
print("="*54)
sys.exit(1 if FAILS else 0)
