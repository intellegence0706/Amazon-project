"""Profit, ROI and margin.

IMPORTANT: the rate tables below are a MODEL, not an authority. Amazon changes
its rate card and the numbers drift. Keepa returns per-ASIN fba_fee and
referral_pct - when a Keepa key exists, prefer those and treat this as fallback
only. Rates here should be checked against Amazon's current US rate card.
"""
from dataclasses import dataclass
from typing import Optional

# Referral fee by category. 15% is the common default across most categories.
REFERRAL_PCT = {
    "default": 0.15,
    "health": 0.15, "beauty": 0.15, "grocery": 0.15,
    "electronics": 0.08, "computers": 0.08, "video games": 0.15,
    "toys": 0.15, "home": 0.15, "clothing": 0.17,
}
REFERRAL_MIN = 0.30

# Simplified US FBA fulfilment tiers keyed on shipping weight (lb).
# Verify against the current rate card before quoting these to a client.
FBA_TIERS = [
    (0.25, 3.06), (0.50, 3.15), (0.75, 3.60), (1.00, 3.95),
    (1.50, 4.60), (2.00, 5.05), (3.00, 5.80),
]
FBA_OVER_3LB_BASE = 6.30
FBA_OVER_3LB_PER_LB = 0.38


@dataclass
class Lead:
    cost: float
    sale_price: float
    referral_fee: float
    fba_fee: float
    inbound: float
    prep: float
    net_profit: float
    roi_pct: float
    margin_pct: float
    flags: list

    def __str__(self):
        return (f"${self.cost:>7.2f} -> ${self.sale_price:>7.2f}  "
                f"net ${self.net_profit:>7.2f}  ROI {self.roi_pct:>6.1f}%  "
                f"margin {self.margin_pct:>5.1f}%")


def fba_fee(weight_lb: float) -> float:
    for limit, fee in FBA_TIERS:
        if weight_lb <= limit:
            return fee
    extra = max(0.0, weight_lb - 3.0)
    return round(FBA_OVER_3LB_BASE + extra * FBA_OVER_3LB_PER_LB, 2)


def referral_fee(sale_price: float, category: Optional[str] = None) -> float:
    pct = REFERRAL_PCT.get((category or "").lower(), REFERRAL_PCT["default"])
    return round(max(sale_price * pct, REFERRAL_MIN), 2)


def evaluate(cost, sale_price, weight_lb=1.0, category=None, inbound=0.55,
             prep=0.0, bsr=None, offer_count=None, amazon_on_listing=False,
             fee_override=None, max_bsr=250_000, min_roi=30.0):
    """Compute a lead. fee_override accepts Keepa's authoritative fees."""
    ref = fee_override["referral"] if fee_override else referral_fee(sale_price, category)
    fba = fee_override["fba"] if fee_override else fba_fee(weight_lb)

    invested = cost + inbound + prep
    net = round(sale_price - ref - fba - invested, 2)
    roi = round(net / invested * 100, 1) if invested else 0.0
    margin = round(net / sale_price * 100, 1) if sale_price else 0.0

    flags = []
    if amazon_on_listing:
        flags.append("AMAZON_ON_LISTING")
    if offer_count is not None and offer_count > 15:
        flags.append(f"CROWDED({offer_count})")
    if bsr is not None and bsr > max_bsr:
        flags.append(f"SLOW_BSR({bsr:,})")
    if bsr is None:
        flags.append("NO_RANK_HISTORY")      # cannot judge velocity without Keepa
    if roi < min_roi:
        flags.append("BELOW_ROI_TARGET")
    if net <= 0:
        flags.append("UNPROFITABLE")

    return Lead(cost, sale_price, ref, fba, inbound, prep, net, roi, margin, flags)
