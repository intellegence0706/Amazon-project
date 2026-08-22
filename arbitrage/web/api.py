"""REST API over the sourcing engine.

FastAPI generates the OpenAPI document at /openapi.json. That document is the
real integration deliverable: point any client - or an AI assistant doing the
integration - at it and every endpoint, parameter and response shape is described
machine-readably.
"""
import csv
import io
import os
import pathlib
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
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


# The UI runs as a separate Next.js process during development.
# Bind the API to 127.0.0.1 in production - these origins are local only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_conn():
    """Open a connection, or explain clearly why it could not be opened.

    A database misconfiguration used to surface as a bare 500, which the
    interface reported as "engine not running" - sending you to look in exactly
    the wrong place. Now the response says what is actually wrong.
    """
    try:
        conn = db.init()
    except Exception as e:                                   # noqa: BLE001
        raw = str(e)
        if not db.is_postgres():
            # On serverless the filesystem is read-only, so falling back to
            # SQLite can never work - the real problem is a missing env var.
            if os.environ.get("VERCEL"):
                detail = "DATABASE_URL is not set on this deployment."
                fix = ("Add DATABASE_URL (your Supabase transaction-pooler "
                       "string, port 6543) in the hosting project's environment "
                       "variables, then redeploy. Serverless storage is "
                       "read-only, so the local database cannot be used here.")
            else:
                detail = f"Cannot open the local database: {raw[:120]}"
                fix = "Delete arbitrage.db and re-run ingest."
        elif "password authentication failed" in raw:
            detail = "DATABASE_URL is set, but Supabase rejected the password."
            fix = ("Either unset DATABASE_URL to use the local database, or "
                   "correct the password. Supabase → Settings → Database → "
                   "Reset database password.")
        elif "timeout" in raw.lower() or "could not connect" in raw.lower():
            detail = "DATABASE_URL is set, but the database did not respond."
            fix = ("The Supabase project may be paused — free-tier projects "
                   "pause after about a week idle. Open the Supabase dashboard "
                   "to resume it, or unset DATABASE_URL to work locally.")
        else:
            detail = f"Database connection failed: {raw.splitlines()[0][:120]}"
            fix = "Run: python3 -m arbitrage.cli preflight"
        raise HTTPException(503, f"{detail}  →  {fix}")
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
    serverless: bool = False
    scanning_available: bool = True


# ---------------------------------------------------------------- endpoints

@app.get("/health", response_model=Health, tags=["meta"])
def health(conn=Depends(get_conn)):
    """Liveness plus an honest statement of what the Amazon side can do."""
    has_amz = conn.execute("SELECT COUNT(*) FROM amazon_products").fetchone()[0] > 0
    serverless = os.environ.get("VERCEL") is not None
    return Health(
        status="ok",
        keepa_configured=has_amz,
        amazon_data="live" if has_amz else "modelled - no Keepa key configured",
        serverless=serverless,
        scanning_available=not serverless,
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
    if os.environ.get("VERCEL"):
        raise HTTPException(
            501,
            "Scanning is not available on this deployment. A catalog scan takes "
            "30-90 seconds and serverless functions are cut off long before that. "
            "Data here is refreshed automatically every 6 hours by a scheduled "
            "job, and can be refreshed on demand by running "
            "'arbitrage ingest <retailer>' with DATABASE_URL set.",
        )
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
    if os.environ.get("VERCEL") and limit > 5:
        raise HTTPException(
            501,
            "Matching more than 5 products at a time is not available on this "
            "deployment - each product needs a Keepa round trip and serverless "
            "functions are cut off first. The scheduled job handles bulk matching.",
        )
    from .. import config, matching
    from ..keepa import KeepaClient, fixture_client
    cfg = config.load()
    client = (KeepaClient(cfg.keepa_api_key, cfg.keepa_domain)
              if cfg.keepa_configured else fixture_client(cfg.keepa_domain))
    st = matching.run(conn, client, limit=limit, min_discount=min_discount)
    return MatchStats(**st, keepa_mode=client.mode)



class Product(BaseModel):
    product_id: int
    retailer: str
    retailer_slug: str
    title: str
    brand: Optional[str] = None
    url: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    pack_qty: Optional[int] = None
    image_url: Optional[str] = None
    price: float
    list_price: Optional[float] = None
    in_stock: bool
    discount_pct: Optional[float] = None
    captured_at: str


class ProductPage(Page):
    items: List[Product]


class PricePoint(BaseModel):
    price: float
    list_price: Optional[float] = None
    in_stock: bool
    captured_at: str


@app.get("/products", response_model=ProductPage, tags=["catalog"])
def list_products(
    retailer: Optional[str] = Query(None, description="Retailer slug"),
    q: Optional[str] = Query(None, description="Search title and brand"),
    on_sale: Optional[bool] = None,
    in_stock: Optional[bool] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    """Browse a retailer's full catalog, discounted or not."""
    total, rows = queries.products(
        conn, retailer=retailer, q=q, on_sale=on_sale, in_stock=in_stock,
        min_price=min_price, max_price=max_price, limit=limit, offset=offset)
    return ProductPage(total=total, count=len(rows), offset=offset, items=rows)


@app.get("/products/{product_id}/history", response_model=List[PricePoint],
         tags=["catalog"])
def product_history(product_id: int, limit: int = Query(60, ge=1, le=500),
                    conn=Depends(get_conn)):
    """Every recorded price change for one product."""
    rows = queries.price_history(conn, product_id, limit=limit)
    if not rows:
        raise HTTPException(404, f"no price history for product {product_id}")
    return rows


class KeepaKeyIn(BaseModel):
    api_key: str = Field(min_length=8, description="Keepa API key")


class SettingsOut(BaseModel):
    keepa_configured: bool
    keepa_key_masked: Optional[str] = None
    min_roi: float
    max_bsr: int
    inbound_cost: float
    prep_cost: float


@app.get("/settings", response_model=SettingsOut, tags=["meta"])
def get_settings():
    """Current configuration. The key is never returned in full."""
    from .. import config
    s = config.load()
    return SettingsOut(
        keepa_configured=s.keepa_configured,
        keepa_key_masked=(s.keepa_api_key[:4] + "…" + s.keepa_api_key[-4:]
                          if s.keepa_configured else None),
        min_roi=s.min_roi, max_bsr=s.max_bsr,
        inbound_cost=s.inbound_cost, prep_cost=s.prep_cost,
    )


@app.post("/settings/keepa-key", response_model=SettingsOut, tags=["meta"])
def set_keepa_key(body: KeepaKeyIn):
    """Save a Keepa key to .env, then validate it against Keepa.

    Localhost-only convenience so a non-technical user never has to edit a file.
    Rejects the key if Keepa does not accept it, rather than saving something broken.
    """
    from .. import config
    from ..keepa import KeepaClient, KeepaError

    key = body.api_key.strip()
    try:
        KeepaClient(key, config.load().keepa_domain).tokens()
    except KeepaError as e:
        raise HTTPException(400, f"Keepa rejected this key: {e}")

    if not config.writable():
        raise HTTPException(
            409,
            "This deployment cannot store the key on disk. Set KEEPA_API_KEY as "
            "an environment variable in your hosting project settings and redeploy.",
        )

    path = config.ENV_PATH
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [l for l in lines if not l.strip().startswith("KEEPA_API_KEY")]
    lines.insert(0, f"KEEPA_API_KEY={key}")
    path.write_text("\n".join(lines) + "\n")
    return get_settings()


# ---------------------------------------------------------------- assembly
#
# The API is mounted at /api in BOTH local and serverless deployment, so the
# frontend bundle is identical everywhere - no build-time target switch, no
# environment-specific rebuild.

_routes = app          # the application carrying every endpoint defined above

app = FastAPI(
    title=_routes.title,
    version=_routes.version,
    description=_routes.description,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.mount("/api", _routes, name="api")

_UI_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "web" / "out"

if _UI_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    class _SPAFiles(StaticFiles):
        """Serve the exported pages, falling back to 404.html over a bare error."""

        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    for candidate in (f"{path}/index.html", f"{path}.html", "404.html"):
                        try:
                            return await super().get_response(candidate, scope)
                        except StarletteHTTPException:
                            continue
                raise

    app.mount("/", _SPAFiles(directory=str(_UI_DIR), html=True), name="ui")
else:
    @app.get("/", include_in_schema=False)
    def _no_ui():
        return {"detail": "Interface not built.",
                "fix": "cd web && npm install && npm run build",
                "api_docs": "/api/docs"}
