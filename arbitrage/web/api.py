"""REST API over the sourcing engine.

FastAPI generates the OpenAPI document at /openapi.json. That document is the
real integration deliverable: point any client - or an AI assistant doing the
integration - at it and every endpoint, parameter and response shape is described
machine-readably.
"""
import csv
import io
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db, ingest, queries, verify as _verify
from ..fingerprint import TIERS, probe

app = FastAPI(
    title="Arbitrage Sourcing Engine",
    version="0.1.0",
    description=(
        "Retail-arbitrage lead engine. Ingests retailer catalogs, detects active "
        "sales, and computes profit / ROI / margin.\n\n"
        "**Amazon-side data is modelled, not live.** Every lead carries "
        "`modelled: true` until a Keepa API key is configured. Do not present "
        "modelled ROI as a verified sourcing decision."
    ),
)


def get_conn():
    conn = db.init()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- models

class Retailer(BaseModel):
    slug: str
    name: str
    host: str
    platform: str
    tier: int = Field(description="1 open catalog .. 4 needs paid scraping")
    enabled: int
    products: int


class Sale(BaseModel):
    retailer: str
    retailer_slug: str
    product_id: int
    title: str
    brand: Optional[str] = None
    url: Optional[str] = None
    pack_qty: Optional[int] = None
    price: float
    list_price: float
    discount_pct: float
    captured_at: str


class Lead(Sale):
    amazon_price: float
    net_profit: float
    roi_pct: float
    margin_pct: float
    referral_fee: float
    fba_fee: float
    flags: List[str] = []
    modelled: bool = Field(True, description="True until real Keepa data is attached")


class Page(BaseModel):
    total: int
    count: int
    offset: int
    items: list


class SalePage(Page):
    items: List[Sale]


class LeadPage(Page):
    items: List[Lead]
    modelled: bool = True
    note: str = ("Amazon price is modelled as list_price x multiplier. "
                 "Configure a Keepa API key for live pricing and rank history.")


class Funnel(BaseModel):
    skus_ingested: int
    discounted_in_stock: int
    discounted_pct: float
    within_price_band: int
    band_pct: float
    keepa_lookups_needed: int
    lookup_pct: float
    reduction_factor: Optional[float]


class Stats(BaseModel):
    retailers: int
    products: int
    price_snapshots: int
    amazon_products: int
    matches: int
    last_scan: Optional[str]


class IngestResult(BaseModel):
    retailer: str
    seen: int
    new: int
    price_changes: int
    on_sale: int


class Health(BaseModel):
    status: str
    keepa_configured: bool
    amazon_data: str


# ---------------------------------------------------------------- endpoints

@app.get("/health", response_model=Health, tags=["meta"])
def health(conn=Depends(get_conn)):
    """Liveness plus an honest statement of what the Amazon side can do."""
    has_amz = conn.execute("SELECT COUNT(*) FROM amazon_products").fetchone()[0] > 0
    return Health(
        status="ok",
        keepa_configured=has_amz,
        amazon_data="live" if has_amz else "modelled - no Keepa key configured",
    )


@app.get("/stats", response_model=Stats, tags=["meta"])
def stats(conn=Depends(get_conn)):
    return queries.stats(conn)


@app.get("/retailers", response_model=List[Retailer], tags=["retailers"])
def list_retailers(conn=Depends(get_conn)):
    return queries.retailers(conn)


@app.get("/sales", response_model=SalePage, tags=["leads"])
def list_sales(
    min_discount: float = Query(15.0, ge=0, le=100),
    retailer: Optional[str] = None,
    min_price: float = Query(0.5, ge=0),
    max_price: Optional[float] = Query(None, gt=0),
    dedup: bool = Query(True, description="Collapse colourway/size variants"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    """Products currently discounted and in stock. Real retailer data."""
    total, rows = queries.sales(conn, min_discount=min_discount, retailer=retailer,
                                min_price=min_price, max_price=max_price,
                                dedup=dedup, limit=limit, offset=offset)
    return SalePage(total=total, count=len(rows), offset=offset,
                    items=[r.dict() for r in rows])


@app.get("/leads", response_model=LeadPage, tags=["leads"])
def list_leads(
    min_roi: float = Query(30.0, description="Minimum ROI percent"),
    multiplier: float = Query(0.85, gt=0, le=5,
                              description="Modelled Amazon price as a fraction of list"),
    min_discount: float = Query(15.0, ge=0, le=100),
    retailer: Optional[str] = None,
    min_price: float = Query(5.0, ge=0),
    max_price: float = Query(200.0, gt=0),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    """Profit-modelled leads.

    Retailer cost and discount are real. Amazon price, net profit and ROI are
    MODELLED until a Keepa key exists - see the `modelled` flag.
    """
    total, rows = queries.leads(conn, min_roi=min_roi, multiplier=multiplier,
                                min_discount=min_discount, retailer=retailer,
                                min_price=min_price, max_price=max_price,
                                limit=limit, offset=offset)
    return LeadPage(total=total, count=len(rows), offset=offset,
                    items=[{**r.dict(), "flags": list(r.flags)} for r in rows])


@app.get("/candidates", response_model=Funnel, tags=["leads"])
def funnel(min_price: float = 5.0, max_price: float = 200.0, conn=Depends(get_conn)):
    """How many Keepa lookups a full catalog actually requires.

    Filtering before spending a token is what makes hundreds of retailers viable.
    """
    return queries.candidates(conn, min_price=min_price, max_price=max_price)


@app.get("/export.csv", tags=["leads"], response_class=StreamingResponse)
def export_csv(min_discount: float = 15.0, retailer: Optional[str] = None,
               limit: int = Query(1000, ge=1, le=10000), conn=Depends(get_conn)):
    """Discounted products as CSV."""
    _, rows = queries.sales(conn, min_discount=min_discount, retailer=retailer,
                            limit=limit)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["retailer", "brand", "title", "pack_qty", "price",
                "list_price", "discount_pct", "url"])
    for r in rows:
        w.writerow([r.retailer, r.brand or "", r.title, r.pack_qty or "",
                    r.price, r.list_price, r.discount_pct, r.url or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'})


@app.post("/retailers/{slug}/ingest", response_model=IngestResult, tags=["retailers"])
def run_ingest(slug: str, pages: Optional[int] = Query(None, ge=1, le=200),
               conn=Depends(get_conn)):
    """Pull a retailer's catalog and record any price changes.

    Synchronous by design at phase-1 scale. Move to a queue before adding
    retailers with large catalogs.
    """
    try:
        s = ingest.ingest(conn, slug, max_pages=pages)
    except KeyError:
        raise HTTPException(404, f"unknown retailer: {slug}")
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    return IngestResult(retailer=slug, **s)


@app.get("/fingerprint", tags=["retailers"])
def fingerprint(host: str = Query(..., description="Domain, e.g. www.vitacost.com")):
    """Sort a domain into an acquisition tier before committing to it."""
    fp = probe(host)
    return {**fp.__dict__, "tier_meaning": TIERS[fp.tier]}


class CheckResult(BaseModel):
    name: str
    status: str
    detail: str = ""
    fix: str = ""


class Verification(BaseModel):
    ok: bool
    summary: str
    checks: List[CheckResult]


@app.get("/verify", response_model=Verification, tags=["meta"])
def verify_pipeline(offline: bool = Query(False, description="Skip network checks")):
    """Self-test every stage: config, database, retailer fetch, Keepa, fees, ROI.

    Run this after adding a Keepa key. It reports which stage failed and how to
    fix it, so 'does it work' has an answer rather than an opinion.
    """
    checks = _verify.run(live_network=not offline)
    failed = [c for c in checks if c.status == _verify.FAIL]
    return Verification(
        ok=not failed,
        summary=("pipeline broken" if failed else
                 "operational" if not any(c.status == _verify.WARN for c in checks)
                 else "works, with warnings"),
        checks=[CheckResult(name=c.name, status=c.status, detail=c.detail, fix=c.fix)
                for c in checks],
    )


class MatchStats(BaseModel):
    attempted: int
    auto: int
    pending: int
    rejected: int
    no_candidate: int
    errors: int
    keepa_mode: str


@app.get("/leads/verified", response_model=LeadPage, tags=["leads"])
def verified_leads(min_roi: float = 30.0, min_profit: float = 0.0,
                   include_pending: bool = False,
                   limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                   conn=Depends(get_conn)):
    """Leads built from REAL matched Amazon data — `modelled` is false.

    Empty until `POST /match` has run with a Keepa key configured.
    """
    total, rows = queries.matched_leads(conn, min_roi=min_roi, min_profit=min_profit,
                                        only_auto=not include_pending,
                                        limit=limit, offset=offset)
    return LeadPage(total=total, count=len(rows), offset=offset, modelled=False,
                    note="Real Keepa data. Confidence-gated matches only.",
                    items=[{**r.dict(), "flags": list(r.flags)} for r in rows])


@app.post("/match", response_model=MatchStats, tags=["leads"])
def run_match(limit: int = Query(25, ge=1, le=500), min_discount: float = 15.0,
              conn=Depends(get_conn)):
    """Match discounted products to Amazon ASINs.

    Costs Keepa tokens. Only funnel survivors are attempted.
    """
    from .. import config, matching
    from ..keepa import KeepaClient, fixture_client
    cfg = config.load()
    client = (KeepaClient(cfg.keepa_api_key, cfg.keepa_domain)
              if cfg.keepa_configured else fixture_client(cfg.keepa_domain))
    st = matching.run(conn, client, limit=limit, min_discount=min_discount)
    return MatchStats(**st, keepa_mode=client.mode)
